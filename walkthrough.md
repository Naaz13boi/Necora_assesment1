# Walkthrough: Codebase Dependency Graph RAG Application

We have implemented a complete, local codebase dependency analyzer and Graph RAG query system. The project is created under the directory `/home/naaz/code/Necora_assesment`.

Here is a guide to starting the application, running your first code updates, and interacting with the Graph RAG chatbot.

---

## 1. Project Directory Structure

Your workspace contains the following files:
*   [docker-compose.yml](file:///home/naaz/code/Necora_assesment/docker-compose.yml): Launches local Kafka (KRaft mode) and Memgraph Platform (Database + Web Lab visualizer).
*   [requirements.txt](file:///home/naaz/code/Necora_assesment/requirements.txt): Python dependencies for the pipeline and web server.
*   [llama_setup.md](file:///home/naaz/code/Necora_assesment/llama_setup.md): Comprehensive instructions for downloading the **Qwen-2.5-7B-Instruct** GGUF model and running the `llama.cpp` container with AMD GPU (ROCm) hardware acceleration on Bazzite.
*   [watcher.py](file:///home/naaz/code/Necora_assesment/watcher.py): Python watchdog script monitoring changes in the target directory and publishing events to Kafka.
*   [consumer.py](file:///home/naaz/code/Necora_assesment/consumer.py): Kafka consumer that extracts python code structures (AST) and sends functions to `llama.cpp` to pull semantic metadata (database tables, external API integrations), saving everything to Memgraph.
*   [app.py](file:///home/naaz/code/Necora_assesment/app.py): FastAPI server serving the interactive Vis.js visualizer and the Graph RAG streaming chat interface.
*   [static/](file:///home/naaz/code/Necora_assesment/static/): Web frontend assets (HTML, CSS, JS) implementing a glassmorphic dark-mode dashboard.
*   [target_code/](file:///home/naaz/code/Necora_assesment/target_code/): A sandbox directory containing mock python modules (`database.py`, `auth.py`, `payment.py`) representing a real database-linked payment codebase to show dependency tracing immediately.

---

## 2. Step-by-Step Launch Instructions

Follow these steps to run the application locally:

### Step A: Boot the Infrastructure
Run Docker Compose to start Kafka KRaft and Memgraph:
```bash
cd /home/naaz/code/Necora_assesment
docker compose up -d
```
*   Verify that **Memgraph Lab** is accessible at `http://localhost:3000`.
*   Ensure Kafka is healthy by checking the compose logs if needed.

### Step B: Download Model & Run Llama.cpp
Follow the setup commands in [llama_setup.md](file:///home/naaz/code/Necora_assesment/llama_setup.md) to download the recommended model and spin up the AMD-accelerated `llama-server` container on Bazzite.
Ensure that the server is responding on `http://localhost:8080`.

### Step C: Install Python Dependencies & Start Ingestion
Create a virtual environment (optional but recommended) and install python requirements:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In two separate terminals, run the consumer and the watcher:
```bash
# Terminal 1: Run the Kafka consumer to process code changes and build the graph
python consumer.py

# Terminal 2: Run the watcher to track edits in target_code/
python watcher.py
```
*   *Note:* The watcher will detect the initial files in `target_code/` when you first make edits/saves to them, publishing them to the Kafka queue.

### Step D: Start the Web Dashboard
In a third terminal, run the FastAPI backend:
```bash
python app.py
```
*   Open your web browser and go to `http://localhost:8000`.
*   You will see a glassmorphic dashboard with your codebase graph loaded.

---

## 3. How to Test the System

1.  **Trigger live indexing:** Open [target_code/payment.py](file:///home/naaz/code/Necora_assesment/target_code/payment.py) or write a new python file under `target_code/` and save it.
    *   Watch the `watcher.py` terminal print a dispatched event message.
    *   Watch the `consumer.py` terminal print AST analysis, print requests sent to the local `llama.cpp` server, and confirm saving records to Memgraph.
    *   Click **Reload Graph** in the web dashboard, and notice the new nodes/dependencies render in real time.
2.  **Interact with Graph RAG:** Open the right panel and ask questions like:
    *   *"What database tables are accessed in the codebase?"*
    *   *"Which functions call external API endpoints?"*
    *   *"If I modify table 'users', which files and functions will be affected?"*
    *   *Notice that the response streams word-by-word, referencing structural paths (like `payment.py` depending on `database.py` and accessing the `users` table) that standard vector search would fail to link together.*
