# Local Llama.cpp Server Setup (Bazzite + AMD ROCm GPU/CPU)

Since you are running **Bazzite** (a container-focused, immutable Fedora-based OS) with an **AMD GPU and CPU**, the cleanest and most performance-optimized way to run `llama.cpp` is using **Docker or Podman** with AMD ROCm passthrough. This avoids layering packages on your host system.

---

## 1. Recommended Models (GGUF)

For Graph RAG dependency extraction, the LLM needs to be strong at instruction-following and structured output (JSON). The following are recommended:

| Model | Size | RAM/VRAM Req. | Recommendation |
| :--- | :--- | :--- | :--- |
| **Qwen-2.5-7B-Instruct (Q4_K_M)** | ~4.7 GB | 8GB+ | **Recommended.** Highly capable at code understanding, JSON extraction, and extremely fast. |
| **Llama-3-8B-Instruct (Q4_K_M)** | ~4.9 GB | 8GB+ | Great general-purpose model, solid instruction following. |
| **Phi-3-mini-4k-instruct (Q4_K_M)** | ~2.2 GB | 4GB+ | Super lightweight. Good for lower VRAM, but slightly less robust at complex JSON schema compliance. |

### How to Download the Model
We will store GGUF models in a local directory `models/`. Download Qwen-2.5-7B-Instruct via `curl` or `wget`:

```bash
mkdir -p /home/naaz/code/Necora_assesment/models
cd /home/naaz/code/Necora_assesment/models

# Download Qwen-2.5-7B-Instruct GGUF
curl -L -o qwen2.5-7b-instruct-q4_k_m.gguf https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf
```

---

## 2. Running llama.cpp with AMD GPU Acceleration on Bazzite

Llama.cpp provides official container images built with **ROCm (HIP)** support for AMD GPUs. 

### Prerequisites for AMD GPU on Bazzite
To expose your AMD GPU to Docker/Podman containers, the container engine needs access to the render and KFD devices:
*   `/dev/kfd` (AMD kernel interface for compute)
*   `/dev/dri` (Direct Rendering Infrastructure, contains `/dev/dri/renderD128`)

### Running the Container via Podman / Docker

On Bazzite, you can run `llama.cpp` server directly with the following command (which passes your AMD GPU devices):

```bash
docker run -d --name llama-server \
  --device=/dev/kfd \
  --device=/dev/dri \
  --security-opt label=disable \
  -v /home/naaz/code/Necora_assesment/models:/models:z \
  -p 8080:8080 \
  ghcr.io/ggerganov/llama.cpp:server-rocm \
  -m /models/qwen2.5-7b-instruct-q4_k_m.gguf \
  -c 4096 \
  --host 0.0.0.0 \
  --port 8080 \
  -ngl 99
```

### Explaining the Parameters:
*   `--device=/dev/kfd --device=/dev/dri`: Exposes your AMD GPU to the container.
*   `--security-opt label=disable`: Required on Fedora/Bazzite (SELinux) to allow the container to access graphics devices without security context issues.
*   `-v ...:/models:z`: Mounts your local models directory. The `:z` flag is critical on Bazzite/SELinux for correct file sharing permissions.
*   `-ngl 99` (`--n-gpu-layers`): Offloads all 99 model layers to the GPU. If your GPU runs out of VRAM, you can lower this number (e.g. `-ngl 32`) to split layers between the CPU and GPU.
*   `-c 4096`: Sets the context window to 4096 tokens (plenty for code extraction).

### Testing the Server
Once running, check if it responds using a simple curl command:
```bash
curl http://localhost:8080/v1/models
```
It should return JSON showing the model is loaded. You can access the built-in llama.cpp web UI by visiting `http://localhost:8080` in your browser.
