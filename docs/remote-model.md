# Running a larger model on a rented GPU

The Mac handles qwen3:8b but struggles with anything bigger, and running models there slows everything else down. The harness
only needs an OpenAI-compatible endpoint, so the model can run on a rented GPU while the harness, the MCP server and the simulator
stay where they are. Only the model's requests travel to the GPU.

Model: `qwen3.6:35b` on Ollama (a mixture-of-experts model, about 3B parameters active, 24 GB download, advertises tool support).
Check its [Ollama page](https://registry.ollama.ai/library/qwen3.6:35b) before you pay. Reports of its tool calling are mixed.

## 1. Rent the GPU (RunPod)

- A 48 GB card (A40, L40S or RTX A6000). The weights take 24 GB and the 32,768-token context needs room on top; a 24 GB card is too tight.
- Image: `ollama/ollama`. Expose no HTTP port; use the SSH tunnel below.
- Set the pod's environment to `OLLAMA_CONTEXT_LENGTH=32768`, as on the Mac. The tool list is about 12,000 tokens, so the default context truncates it.
- Add your SSH public key in RunPod's settings.
- Cost is per hour while the pod runs, even idle. **Stop or delete the pod when the runs finish.**

## 2. Pull the model on the pod

```
ssh -p <port> root@<pod-ip>
OLLAMA_CONTEXT_LENGTH=32768 ollama serve &    # skip if the image already runs it
ollama pull qwen3.6:35b
```

## 3. Tunnel from the Mac

Stop the local Ollama first, or use another local port as below:

```
ssh -N -L 11435:localhost:11434 -p <port> root@<pod-ip>
```

An SSH tunnel keeps the endpoint off the public internet. Ollama has no login of its own, so do not open its port.

## 4. Run the benchmark

```
export OLLAMA_BASE_URL=http://localhost:11435/v1 OLLAMA_MODEL=qwen3.6:35b
mkdir -p runs-qwen36 && cd runs-qwen36
PYTHONPATH=<repo> python -m harness.batch --providers ollama --repeats 3
```

Log files record the model name, so they are kept apart from qwen3:8b by name. Use a separate runs folder (add it to `.gitignore`).
Set `NINA_MCP_PROFILE` (`full`, `mono` or `core`) to repeat the profile comparison. `held_centre_fails` needs M42 above the horizon
(after about 22:45 UTC in November; see [issue #126](https://github.com/sergiomarrocoli/NINA-MCP-model-benchmarking/issues/126)).

Reasoning is switched off by the provider (`reasoning_effort: none`), like the other models. Qwen3.6 can think before every reply; if the
runs show long delays or empty replies, check that the setting reached the model.

## 5. Compare

```
python -m harness.compare qwen3-8b=runs-mono/runs qwen3-6-35b=runs-qwen36/runs --skip held_centre_fails
```

## What this does and does not show

- It shows what a larger open-weight model gains from the same MCP, on weights you could in principle host at a site.
- It does not show it would run on-site hardware. A 35B model at 4-bit needs about 24 GB of GPU memory.
- One run of 17 tasks × 3 takes a few hours, so budget a few dollars for the pod.
