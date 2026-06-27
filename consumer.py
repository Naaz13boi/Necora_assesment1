import os
import sys
import json
import time
import ast
import requests
from confluent_kafka import Consumer, KafkaError
from neo4j import GraphDatabase

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_SERVERS", "localhost:9092")
KAFKA_TOPIC = "code-changes"
MEMGRAPH_URI = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "http://localhost:8080/v1/chat/completions")

print("[*] Initializing finalized consumer service...")

class MemgraphClient:
    def __init__(self, uri):
        print(f"[*] Connecting to Memgraph on {uri}...")
        self.driver = GraphDatabase.driver(uri, auth=("", ""))
        
    def close(self):
        if self.driver:
            self.driver.close()

    def delete_file_subgraph(self, file_path):
        """Strict clean step using exact base file name matching."""
        pure_filename = os.path.basename(file_path)
        query = """
        MATCH (f:File {path: $pure_filename})
        OPTIONAL MATCH (f)-[:DECLARES]->(child)
        DETACH DELETE child, f
        """
        with self.driver.session() as session:
            session.run(query, pure_filename=pure_filename)

    def write_graph_data(self, file_path, ast_data, semantic_data):
        pure_filename = os.path.basename(file_path)

        with self.driver.session() as session:
            # 1. Ensure File node exists uniquely
            session.run(
                "MERGE (f:File {path: $pure_filename}) SET f.last_updated = timestamp()",
                pure_filename=pure_filename
            )

            # 2. Create Classes cleanly
            for class_info in ast_data["classes"]:
                session.run(
                    """
                    MERGE (c:Class {name: $class_name, file_path: $pure_filename})
                    WITH c
                    MATCH (f:File {path: $pure_filename})
                    MERGE (f)-[:DECLARES]->(c)
                    """,
                    class_name=class_info["name"], pure_filename=pure_filename
                )

            # 3. Create Unique Functions and enforce File ownership
            for func_info in ast_data["functions"]:
                func_name = func_info["name"]
                signature = func_info["signature"]
                sem = semantic_data.get(func_name, {"summary": "No summary available.", "tables": [], "external_apis": []})

                session.run(
                    """
                    MERGE (fn:Function {name: $func_name, file_path: $pure_filename})
                    SET fn.signature = $signature, fn.summary = $summary
                    WITH fn
                    MATCH (f:File {path: $pure_filename})
                    MERGE (f)-[:DECLARES]->(fn)
                    """,
                    func_name=func_name, pure_filename=pure_filename,
                    signature=signature, summary=sem["summary"]
                )

            # =================================================================
            # 4. Connect Function Calls (FOREACH Conditional Workaround)
            # =================================================================
            for call_info in ast_data["calls"]:
                caller = call_info["caller"]
                callee = call_info["callee"]
                if caller:
                    session.run(
                        """
                        // Ensure caller exists
                        MERGE (fn1:Function {name: $caller, file_path: $pure_filename})
                        WITH fn1
                        
                        // Look up global targets safely
                        OPTIONAL MATCH (existingTarget:Function {name: $callee})
                        WITH fn1, existingTarget, [existingTarget] AS targets
                        
                        // Route A: Map to the functional target if it exists
                        FOREACH (t IN case when existingTarget IS NOT NULL and fn1 <> existingTarget then [existingTarget] else [] end |
                            MERGE (fn1)-[:CALLS]->(t)
                        )
                        
                        // Route B: If target function is completely unknown, build baseline placeholder
                        FOREACH (t IN case when existingTarget IS NULL then [1] else [] end |
                            MERGE (placeholder:Function {name: $callee})
                            ON CREATE SET placeholder.file_path = "external"
                            MERGE (fn1)-[:CALLS]->(placeholder)
                        )
                        """,
                        caller=caller, callee=callee, pure_filename=pure_filename
                    )

            # =================================================================
            # 5. Connect imports to physical files (FOREACH Conditional Workaround)
            # =================================================================
            for imp in ast_data["imports"]:
                target_suffix = f"{imp}.py"
                session.run(
                    """
                    MERGE (f1:File {path: $pure_filename})
                    WITH f1
                    
                    OPTIONAL MATCH (existingFile:File {path: $target_suffix})
                    WITH f1, existingFile
                    
                    // Route A: Map link to physical target file
                    FOREACH (f IN case when existingFile IS NOT NULL and f1 <> existingFile then [existingFile] else [] end |
                        MERGE (f1)-[:DEPENDS_ON]->(f)
                    )
                    
                    // Route B: Create placeholder file tracking reference
                    FOREACH (f IN case when existingFile IS NULL then [1] else [] end |
                        MERGE (filePlaceholder:File {path: $target_suffix})
                        MERGE (f1)-[:DEPENDS_ON]->(filePlaceholder)
                    )
                    """,
                    pure_filename=pure_filename, target_suffix=target_suffix
                )

# ----------------- AST Analyzer -----------------
class ASTAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.classes = []
        self.functions = []
        self.calls = []
        self.imports = []
        self.current_class = None
        self.current_function = None

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        class_info = {"name": node.name, "bases": [b.id for b in node.bases if isinstance(b, ast.Name)]}
        self.classes.append(class_info)
        prev_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node):
        args = [arg.arg for arg in node.args.args]
        signature = f"{node.name}({', '.join(args)})"
        func_info = {
            "name": node.name,
            "signature": signature,
            "class_parent": self.current_class,
            "code": ast.unparse(node)
        }
        self.functions.append(func_info)
        prev_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_Call(self, node):
        callee = None
        if isinstance(node.func, ast.Name):
            callee = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee = node.func.attr
        if callee and self.current_function:
            self.calls.append({"caller": self.current_function, "callee": callee})
        self.generic_visit(node)

def analyze_code_structure(code_content):
    try:
        tree = ast.parse(code_content)
        analyzer = ASTAnalyzer()
        analyzer.visit(tree)
        return {"classes": analyzer.classes, "functions": analyzer.functions, "calls": analyzer.calls, "imports": analyzer.imports}
    except SyntaxError:
        return {"classes": [], "functions": [], "calls": [], "imports": []}

def main():
    db = MemgraphClient(MEMGRAPH_URI)
    conf = {
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'codebase-analyzer-final-v9',  # Bumped to clear log lag cleanly
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': True
    }
    consumer = Consumer(conf)
    consumer.subscribe([KAFKA_TOPIC])
    print(f"[+] Subscribed to Kafka topic '{KAFKA_TOPIC}'. Monitoring stream...")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                continue

            try:
                event = json.loads(msg.value().decode('utf-8'))
                file_path = event["file_path"]
                action = event["action"]

                if action == "upsert":
                    code_content = event["content"]
                    ast_data = analyze_code_structure(code_content)
                    semantic_data = {}

                    db.delete_file_subgraph(file_path)
                    db.write_graph_data(file_path, ast_data, semantic_data)
                    print(f"[+] Successfully indexed base structure for: {os.path.basename(file_path)}")

            except Exception as e:
                print(f"[-] Loop error: {e}")
    except KeyboardInterrupt:
        print("[*] Stopping consumer...")
    finally:
        consumer.close()
        db.close()

if __name__ == "__main__":
    main()