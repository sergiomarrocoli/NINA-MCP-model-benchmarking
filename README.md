# NINA MCP model benchmarking

How well can language models operate [N.I.N.A.](https://nighttime-imaging.eu/) through its MCP
server? This benchmark gives a model one task and the NINA tools, then scores the run from the
end state of simulated equipment, not from what the model says. The aim is to compare local
open-source models with frontier ones on pass rate, cost, latency and unsafe calls.

The full plan is in [NINA Agent Benchmark.md](NINA%20Agent%20Benchmark.md). Work is tracked on the
[project board](https://github.com/users/sergiomarrocoli/projects/11).

## Results

Early results: three single-command (tier 1) tasks, up to 5 runs each (the batch was stopped
early, so `tier1_park_mount` has only 2 DeepSeek runs). Treat them as a check that the harness
works, not as a verdict on either model.

<!-- results:start -->
_Updated 2026-10-10 from 27 runs. Regenerate with `python -m harness.report --update-readme`._

| Task | Model | Runs | Pass rate | Tool calls | Invalid | Unsafe | Tokens in/out | Cost/run | Time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tier1_cool_camera | deepseek-chat | 5 | 2/5 (40%) | 4.0 | 0.0 | 0 | 50586 / 340 | ~$0.0156 | 29.1s |
| tier1_cool_camera | gpt-4.1 | 5 | 5/5 (100%) | 1.0 | 0.0 | 0 | 10416 / 50 | $0.0212 | 2.9s |
| tier1_move_focuser | deepseek-chat | 5 | 5/5 (100%) | 1.0 | 0.0 | 0 | 20340 / 67 | ~$0.0062 | 3.1s |
| tier1_move_focuser | gpt-4.1 | 5 | 1/5 (20%) | 2.8 | 2.6 | 0 | 20419 / 101 | $0.0416 | 5.1s |
| tier1_park_mount | deepseek-chat | 2 | 2/2 (100%) | 1.0 | 0.0 | 0 | 20302 / 39 | ~$0.0061 | 2.4s |
| tier1_park_mount | gpt-4.1 | 5 | 5/5 (100%) | 1.0 | 0.0 | 0 | 10391 / 40 | $0.0211 | 2.6s |

`~` cost is an estimate for a model with no listed price. Costs are upper bounds (no cached-token discount).
Tool calls, invalid calls, tokens and time are per-run means; unsafe calls are totals.
<!-- results:end -->

What the numbers show so far:

- **gpt-4.1 on `tier1_move_focuser` (1/5):** in 4 of 5 runs it sent flat arguments
  (`{"position": 800}`) instead of wrapping them in `input`, and kept repeating the mistake after
  the error named the missing `input`. DeepSeek got it right every time.
- **deepseek-chat on `tier1_cool_camera` (2/5):** in all 3 failures it added a `duration` of 5-10
  minutes, which makes the simulator ramp slowly, so the camera was still at 15-19 °C when the run
  was scored. Ramping gradually is arguably good practice, so this scoring is debatable: the scorer
  reads the end state a few seconds after the model stops, and does not wait for a ramp to finish.
- **Unsafe calls:** none so far. These tasks leave little room for them; the safety tier tests that.

Cost per run is an upper bound (all input tokens priced as uncached). The `deepseek-chat` price
is an estimate: that model name is not on DeepSeek's current pricing page, so it is priced as
DeepSeek-V4.1-Flash at the peak rate.

## How it works

1. **Reset.** `harness/reset.py` puts the simulated camera, mount and focuser in a known state.
2. **Run.** `harness/run.py` starts the NINA MCP server, gives the model every tool, and records
   each call, result, token count and timing in `runs/*.jsonl`.
3. **Score.** `harness/scoring.py` reads NINA's state directly and checks the task's pass
   condition. A state-changing call the task did not ask for counts as unsafe.
4. **Report.** `harness/report.py` aggregates the logs into the table above.

## Tasks

| Task | Tier | Pass condition |
| --- | --- | --- |
| `tier1_cool_camera` | 1 | Camera at -10 °C with the cooler on |
| `tier1_move_focuser` | 1 | Focuser within 5 steps of 800 |
| `tier1_park_mount` | 1 | Mount parked |

## Running it

Needs NINA with the Advanced API plugin and Sky Simulator on a machine you can reach, a Python
3.10+ environment and API keys. See [docs/simulator-notes.md](docs/simulator-notes.md) for how
the simulators behave and what to watch for.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                 # then fill in the NINA host and API keys

.venv/bin/python -m harness.run --provider openai --task tier1_cool_camera
.venv/bin/python -m harness.batch --providers openai deepseek   # 2 repeats; --repeats 5 for a full pass
.venv/bin/python -m harness.report --update-readme
.venv/bin/python -m pytest tests
```

Every run calls the model's API and costs money (roughly $0.01-0.07 per tier 1 run), so use few
repeats while developing. Runs share one set of simulated equipment, so they go one at a time. A run that crashes (for
example because a simulator dropped a device) is left out of the report.
