# Necora Graph RAG

Necora Graph RAG is an advanced, real-time codebase visualization and AI assistant platform. It combines the structural intelligence of a Graph Database with the reasoning capabilities of a Local Large Language Model (LLM). 

The goal of this project is to solve a fundamental problem in AI-assisted software engineering: **context awareness in complex codebases.**

---
![Necora Graph Dashboard](assets/dashboard.png)

---
## 🌟 Why Graph RAG & AI?

Traditional Retrieval-Augmented Generation (RAG) relies on vector databases and semantic similarity. While great for natural language documents, vector RAG fails spectacularly on codebases. If you ask an AI, *"What happens if I change the `save_user` function?"*, vector search might return the function itself and maybe some documentation, but it will completely miss the five different files and endpoints that silently depend on that function.

Code is not just text; it is an interconnected, hierarchical graph of files, classes, and functions. 

**Graph RAG** solves this by storing the codebase as an actual graph. When the AI is asked a question, it doesn't just guess based on text similarity—it executes Graph queries to definitively trace caller/callee relationships, variable dependencies, and architectural impacts. By combining this deterministic structural context with the generative power of an LLM, developers gain an assistant that truly understands their architecture.

---

## 🏗️ Architecture & Core Technologies

This application is built on a modern, decoupled architecture designed for real-time reactivity and local execution.

### 1. Memgraph (The Graph Database)
We use **Memgraph**, a high-performance, in-memory graph database that is fully compatible with the Cypher query language (Neo4j compatible). 
* **Why Memgraph?** Codebases are graphs. Functions call other functions, files import other files. Memgraph allows us to store these relationships natively (`(Caller)-[:CALLS]->(Callee)`). It is incredibly fast, allowing the AI to traverse deep dependency chains in milliseconds to gather context before answering a question.

### 2. Apache Kafka with KRaft (The Event Pipeline)
The ingestion pipeline is powered by **Apache Kafka** running in **KRaft (Kafka Raft)** mode.
* **Why Kafka?** When a developer is coding, files are constantly changing. Instead of the backend aggressively polling for changes or blocking the UI, a lightweight `watcher.py` detects file modifications and pushes them as events to a Kafka topic. 
* **Why KRaft?** KRaft mode eliminates the need for Apache ZooKeeper, replacing it with an internal consensus protocol. This significantly simplifies deployment, reduces memory overhead, and makes the streaming architecture modern and robust.

### 3. Llama.cpp (Local AI Engine)
The AI brain of the application is powered by **Llama.cpp**.
* **Why Llama.cpp?** Sending proprietary, highly-sensitive source code to cloud APIs (like OpenAI) is a major security risk for many enterprises. Llama.cpp allows us to run state-of-the-art open-source LLMs entirely locally. It is highly optimized for inference on consumer hardware, meaning developers get blazing-fast AI assistance without compromising their IP.

### 4. FastAPI & Vis.js (The Engine & Interface)
* **FastAPI** serves as the backend orchestration layer. It exposes endpoints for the frontend, queries Memgraph for the RAG context, and streams responses from the local LLM.
* **Vis.js** powers the interactive frontend dashboard, providing developers with a beautiful, real-time node/edge visualization of their codebase structure that updates the moment they save a file.

---

## ⚙️ How It Works (The Data Flow)

1. **Write Code**: You edit Python files inside the `target_code/` directory.
2. **Watch & Produce**: `watcher.py` (using `watchdog`) detects the file save and produces a Kafka message containing the file path and event type.
3. **Consume & Analyze**: `consumer.py` consumes the Kafka event, reads the file, and uses Python's built-in `ast` (Abstract Syntax Tree) module to parse the code. It extracts classes, functions, and their calls.
4. **Graph Insertion**: The consumer writes these entities into Memgraph, creating nodes (e.g., `Function`, `File`) and edges (e.g., `DECLARES`, `CALLS`).
5. **Visualize**: The frontend periodically polls the FastAPI `/api/graph` endpoint and dynamically updates the Vis.js network graph, filtering out noise (like standard library built-ins) to show a clean architectural map.
6. **Graph RAG Chat**: When you ask a question in the UI, FastAPI queries Memgraph to retrieve the structural context (e.g., "What relies on X?"). It prepends this deterministic context to your prompt and sends it to the local Llama.cpp server. The AI streams back a structurally-aware answer.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Apache Kafka (configured for KRaft mode)
- Memgraph (can be run via Docker: `docker run -p 7687:7687 memgraph/memgraph`)
- Llama.cpp server running locally on port `8080` (or update `LLAMA_SERVER_URL` in `.env`)

### Installation

1. **Clone and Install Dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Start Infrastructure Services**
   Ensure Kafka, Memgraph, and your Llama.cpp server are running in the background.

3. **Run the Ingestion Pipeline**
   In a separate terminal, start the Kafka consumer to listen for codebase changes:
   ```bash
   python consumer.py
   ```

4. **Run the File Watcher**
   In another terminal, start the watcher to monitor the `target_code/` directory:
   ```bash
   python watcher.py
   ```

5. **Start the FastAPI Application**
   Finally, run the backend server and UI:
   ```bash
   python app.py
   ```

6. **Access the Dashboard**
   Open your browser and navigate to `http://127.0.0.1:8000`. You will see the live graph and the Graph RAG chat interface!

---

## 💡 General Usefulness

For modern software teams, Necora Graph RAG provides unparalleled value:
* **Onboarding:** New engineers can instantly visualize how the architecture connects without reading thousands of lines of code.
* **Impact Analysis:** Before modifying a core database utility, developers can visually and conversationally verify exactly which downstream endpoints will be affected.
* **Privacy-First AI:** Complete, localized intelligence without leaking source code to external cloud providers.
* **Living Documentation:** The graph is never out of date. The moment a developer hits `CMD+S` to save a file, the architecture diagram and the AI's understanding update instantly.
