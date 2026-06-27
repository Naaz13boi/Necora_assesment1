import os
import sys
import json
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from neo4j import GraphDatabase

# Configs
MEMGRAPH_URI = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1/chat/completions")

app = FastAPI(title="Codebase Dependency Graph RAG")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to Memgraph
try:
    driver = GraphDatabase.driver(MEMGRAPH_URI, auth=("", ""))
    with driver.session() as session:
        session.run("RETURN 1")
    print("[+] API connected to Memgraph.")
except Exception as e:
    print(f"[-] API failed to connect to Memgraph: {e}")
    driver = None

class ChatRequest(BaseModel):
    message: str

# ----------------- Helper: Make unique node ID -----------------
def make_node_id(node):
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    
    if label == "File":
        return f"file:{node.get('path', 'unknown')}"
    elif label == "Class":
        return f"class:{node.get('file_path', 'external')}:{node['name']}"
    elif label == "Function":
        return f"func:{node.get('file_path', 'external')}:{node['name']}"
    elif label == "Table":
        return f"table:{node['name']}"
    elif label == "API":
        return f"api:{node['name']}"
    return f"unknown:{node.element_id}"

def get_node_label(node):
    labels = list(node.labels)
    label = labels[0] if labels else "Unknown"
    
    if label == "File":
        return node["path"]
    elif label in ["Class", "Function", "Table", "API"]:
        return node["name"]
    return "Unknown"

# ----------------- API Endpoints -----------------

@app.get("/api/graph")
async def get_graph():
    if not driver:
        raise HTTPException(status_code=500, detail="Memgraph driver not initialized")
    
    nodes_map = {}
    edges = []
    
    query = """
    MATCH (n)
    OPTIONAL MATCH (n)-[r]->(m)
    RETURN n, r, m
    """
    
    try:
        with driver.session() as session:
            result = session.run(query)
            for record in result:
                n = record["n"]
                r = record["r"]
                m = record["m"]
                
                n_id = make_node_id(n)
                n_label = list(n.labels)[0] if n.labels else "Unknown"
                if n_id not in nodes_map:
                    nodes_map[n_id] = {
                        "id": n_id,
                        "label": get_node_label(n),
                        "group": n_label,
                        "title": f"Type: {n_label}<br>Signature: {n.get('signature', 'N/A')}<br>Summary: {n.get('summary', 'N/A')}"
                    }
                
                if m and r:
                    m_id = make_node_id(m)
                    m_label = list(m.labels)[0] if m.labels else "Unknown"
                    if m_id not in nodes_map:
                        nodes_map[m_id] = {
                            "id": m_id,
                            "label": get_node_label(m),
                            "group": m_label,
                            "title": f"Type: {m_label}<br>Signature: {m.get('signature', 'N/A')}<br>Summary: {m.get('summary', 'N/A')}"
                        }
                    
                    edge_id = f"{n_id}->{r.type}->{m_id}"
                    if not any(e["id"] == edge_id for e in edges):
                        # UNIVERSAL PAYLOAD: We supply EVERY key combination 
                        # (from/to, source/target) so the Javascript engine can't fail.
                        edges.append({
                            "id": edge_id,
                            
                            # Standard Framework keys (D3 / React Flow / Cytoscape)
                            "source": n_id,
                            "target": m_id,
                            
                            # Legacy Network Framework keys (Vis.js)
                            "from": n_id,
                            "to": m_id,
                            
                            "label": r.type,
                            "arrows": "to"
                        })
                        
        return {"nodes": list(nodes_map.values()), "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ----------------- Graph RAG Engine -----------------
def retrieve_graph_context(query_str: str) -> str:
    if not driver:
        return "Graph database connection not available."
        
    words = [w.strip("?,.!-").lower() for w in query_str.split() if len(w) > 2]
    stop_words = {"what", "how", "why", "where", "does", "from", "with", "this", "that", "code", "file", "function", "class"}
    search_terms = [w for w in words if w not in stop_words]
    
    if not search_terms:
        search_terms = [""]

    matched_nodes = {}
    matched_relationships = []
    
    with driver.session() as session:
        for term in search_terms:
            if not term:
                cypher = "MATCH (n) RETURN n LIMIT 10"
                result = session.run(cypher)
            else:
                cypher = """
                MATCH (n)
                WHERE toLower(n.name) CONTAINS $term 
                   OR toLower(n.path) CONTAINS $term 
                   OR toLower(n.summary) CONTAINS $term
                RETURN n LIMIT 6
                """
                result = session.run(cypher, term=term)
                
            for record in result:
                node = record["n"]
                n_id = make_node_id(node)
                if n_id not in matched_nodes:
                    labels = list(node.labels)
                    matched_nodes[n_id] = {
                        "id": n_id,
                        "type": labels[0] if labels else "Unknown",
                        "label": get_node_label(node),
                        "summary": node.get("summary", ""),
                        "signature": node.get("signature", "")
                    }
                    
        if matched_nodes:
            cypher_rel = """
            MATCH (n)-[r]->(m)
            WHERE (labels(n)[0] = 'File' AND n.path IN $paths)
               OR (labels(n)[0] = 'Function' AND n.name IN $names)
               OR (labels(n)[0] = 'Class' AND n.name IN $names)
               OR (labels(m)[0] = 'File' AND m.path IN $paths)
               OR (labels(m)[0] = 'Function' AND m.name IN $names)
               OR (labels(m)[0] = 'Class' AND m.name IN $names)
            RETURN n, r, m LIMIT 30
            """
            names = [n["label"] for n in matched_nodes.values() if n["type"] in ["Function", "Class"]]
            paths = [n["label"] for n in matched_nodes.values() if n["type"] == "File"]
            
            result_rel = session.run(cypher_rel, names=names, paths=paths)
            for record in result_rel:
                n = record["n"]
                r = record["r"]
                m = record["m"]
                
                for node in [n, m]:
                    nid = make_node_id(node)
                    if nid not in matched_nodes:
                        labels = list(node.labels)
                        matched_nodes[nid] = {
                            "id": nid,
                            "type": labels[0] if labels else "Unknown",
                            "label": get_node_label(node),
                            "summary": node.get("summary", ""),
                            "signature": node.get("signature", "")
                        }
                
                rel_str = f"({list(n.labels)[0]} '{get_node_label(n)}') -[{r.type}]-> ({list(m.labels)[0]} '{get_node_label(m)}')"
                if rel_str not in matched_relationships:
                    matched_relationships.append(rel_str)
                    
    if not matched_nodes:
        return "No matching entities or relationships found in the codebase dependency graph."

    context_parts = ["Retrieved Codebase Graph Context:\n"]
    context_parts.append("Entities (Nodes):")
    for nid, node in matched_nodes.items():
        details = f"- {node['type']} '{node['label']}'"
        if node['signature']:
            details += f" with signature `{node['signature']}`"
        if node['summary']:
            details += f" (Summary: {node['summary']})"
        context_parts.append(details)
        
    context_parts.append("\nRelationships (Edges):")
    for rel in matched_relationships:
        context_parts.append(f"- {rel}")
        
    return "\n".join(context_parts)

@app.post("/api/chat")
async def chat(request: ChatRequest):
    graph_context = retrieve_graph_context(request.message)
    
    system_prompt = (
        "You are an intelligent AI coding assistant. You are helping a developer understand their codebase.\n"
        "You are provided with a visual dependency graph context retrieved from their local database (Memgraph).\n"
        "Use this graph context (nodes and edges) to answer their question accurately. Explain dependencies, "
        "parent-child relationships, database tables accessed, or external APIs called based on the graph context.\n"
        "If the context does not contain enough information, explain what is available and suggest what file or function they might want to inspect.\n"
        "Respond directly without any internal reasoning or thinking blocks. /no_think\n\n"
        f"{graph_context}"
    )
    
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message}
        ],
        "temperature": 0.7,
        "stream": True
    }
    
    def generate_stream():
        try:
            response = requests.post(LLAMA_SERVER_URL, json=payload, stream=True, timeout=120.0)
            if response.status_code != 200:
                yield f"data: {json.dumps({'text': 'Error calling backend server'})}\n\n"
                return
            
            in_think_block = False
            buffer = ""
                
            for chunk in response.iter_lines():
                if chunk:
                    chunk_str = chunk.decode("utf-8").strip()
                    
                    if chunk_str.startswith("data:"):
                        data_content = chunk_str.replace("data:", "", 1).strip()
                        
                        if data_content == "[DONE]":
                            break
                        try:
                            data_json = json.loads(data_content)
                            choices = data_json.get("choices", [])
                            if not choices:
                                continue
                                
                            delta = choices[0].get("delta", {}).get("content", "")
                            if not delta:
                                continue
                            
                            buffer += delta
                            
                            # Handle <think> block boundaries cleanly
                            if "<think>" in buffer and not in_think_block:
                                before = buffer.split("<think>")[0]
                                if before:
                                    yield f"data: {json.dumps({'text': before})}\n\n"
                                in_think_block = True
                                buffer = buffer.split("<think>", 1)[1]
                            
                            if in_think_block:
                                if "</think>" in buffer:
                                    in_think_block = False
                                    after = buffer.split("</think>", 1)[1]
                                    buffer = after
                                    if buffer:
                                        yield f"data: {json.dumps({'text': buffer})}\n\n"
                                        buffer = ""
                                else:
                                    if len(buffer) > 20:
                                        buffer = buffer[-20:]
                            else:
                                yield f"data: {json.dumps({'text': buffer})}\n\n"
                                buffer = ""
                                
                        except Exception:
                            pass
        except Exception as e:
            yield f"data: {json.dumps({'text': f'[Stream Error: {str(e)}]'})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    os.makedirs("static", exist_ok=True)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)