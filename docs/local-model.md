# Local model and runner (#18)

**Starting choice: `qwen3:8b` through Ollama, with thinking turned off.** The harness already sends
`reasoning_effort: "none"` to Ollama (`harness/providers.py`). Set `OLLAMA_MODEL=qwen3:8b` in `.env`.

The Mac is an M1 with 16 GB, so models above about 9 GB (14B and up, `gpt-oss:20b`) would swap with a long
prompt and are out. The tool list alone is about 8,000 tokens (105 tools), so every run starts with an 8k-token prompt.

## What was tried (14 Oct, `tier1_move_focuser`, Ollama 0.40.2)
| Model | Real tool calls | Seconds per step | Result |
| --- | --- | --- | --- |
| `qwen3:8b`, thinking on | yes | 80 to 170 (400 to 1,200 thinking tokens a step) | 5 steps, never recovered; the run did not finish |
| `qwen3:8b`, thinking off | yes | about 16 (the first step about 90, prefilling the 8k prompt; later steps reuse it) | 15 calls, all invalid, no final answer |
| `qwen2.5:7b` | yes | about 10 | 6 invalid calls, then gave up in text |
| `llama3.1:8b` | **no**: wrote the call out as text | 100 for its one step | Ollama did not parse it as a call, so nothing ran |

- **Thinking off is the big win for speed**: about 8 times faster per step, and the answers were no worse.
  It is an Ollama setting on the OpenAI-compatible endpoint (`reasoning_effort: "none"`); `think: false` was
  ignored there.
- **qwen3:8b is the only one of the three that both makes real tool calls and has a thinking switch**, so it is the
  starting point. `llama3.1:8b` is out for now: its calls never reach the tool.
- **Every model failed the same way**: each sent `{"position": 25500}`, but the tools take
  `{"input": {"position": 25500}}` (the `nina-advanced-mcp` schema wraps every call in `input`). The error text
  says "Missing required argument ... input", which none of them acted on, where gpt-4.1 fixed it on its second
  try. So a local model's Tier 1 score will mostly measure that one habit. It is a real finding about the tool
  list, not a harness fault, but it hides everything else a small model might be able to do.
- **Runner**: Ollama is enough. Its first step is slow because of the prefill, not the runner, and `llama.cpp`
  or MLX would not change what the model sends. Not tried: an MLX server, which can be faster on Apple silicon.

## Not decided here
Whether to flatten the tool schemas (take `input` out) for every model, or leave them as the server publishes
them. Flattening would be the same for all models, but it changes the tool list under test, which is what
experiment 2 (#14) varies. The raw logs of these runs are in `runs/archive/local-model-bakeoff`, not in any report.
