# NINA MCP model benchmarking

How well can language models operate [N.I.N.A.](https://nighttime-imaging.eu/) through its MCP
server? This benchmark gives a model one task and the NINA tools, then scores the run from the
end state of simulated equipment, not from what the model says. The aim is to compare local
open-source models with frontier ones on pass rate, cost, latency and unsafe calls.

The full plan is in [NINA Agent Benchmark.md](NINA%20Agent%20Benchmark.md). Work is tracked on the
[project board](https://github.com/users/sergiomarrocoli/projects/11).

## Results

Early results: three single-command (tier 1) tasks, a small number of runs each. Treat them as
a check that the harness works, not as a verdict on either model.

<!-- results:start -->
_No results yet._
<!-- results:end -->

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
.venv/bin/python -m harness.batch --providers openai deepseek --repeats 5
.venv/bin/python -m harness.report --update-readme
.venv/bin/python -m pytest tests
```

Runs share one set of simulated equipment, so they go one at a time. A run that crashes (for
example because a simulator dropped a device) is left out of the report.
