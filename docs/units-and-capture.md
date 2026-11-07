# Units, clearer errors and a repeat count: before and after

qwen3:8b, the weakest model in the benchmark, failed the two M31 imaging tasks and the filter-change task. The logs
showed three causes, and each is a way the server asked the model to guess. Each was fixed in the MCP server (the
[fork](https://github.com/sergiomarrocoli/Nina_advanced_api_mcp)), not in the model or the prompt.

| Cause seen in the logs | Fix in the server | Fork PR |
|---|---|---|
| The prompt gives M31's right ascension as "00h 42m 44s". qwen read it as 42.44, an angle outside the 0 to 24 hour range, and the first fix's hint sent the mount about 24° off. | `nina_slew_mount` and `nina_center_mount` take `ra` (hours), `ra_degrees` or `ra_hms` ("00h 42m 44s"), refuse an out-of-range `ra` and name the other two, and do not guess. | [#8](https://github.com/sergiomarrocoli/Nina_advanced_api_mcp/pull/8) |
| Changing the filter to Red by number failed in all 5 baseline runs. | `nina_change_filter` takes `filter_name` as well as `filter_id`, and an unknown name or id returns the real filters. | #8 |
| qwen asked for `count: 5` in 19 of 26 capture calls. The tool has no such argument, and the raw pydantic error did not say what to do. | The unknown-argument error lists the tool's real arguments and says a call does one thing, so call it again. | [#10](https://github.com/sergiomarrocoli/Nina_advanced_api_mcp/pull/10) |
| "Take 5 exposures" has no matching argument, so the model keeps asking for one. | `nina_capture_image` takes an optional `count` (1 to 20) and repeats the exposure. | [#12](https://github.com/sergiomarrocoli/Nina_advanced_api_mcp/pull/12) |

## Results

Passes out of 5 runs; the "v1 server" column is the baseline in the README (the pointing offset had 8 runs). Ollama ran
at a 32,768-token context, which the 7,000-token tool list needs.

| Task | v1 server | RA units and filter names | + `ra_hms` | + clearer errors | + `count` |
|---|---|---|---|---|---|
| Change filter to Red (`tier1_change_filter`) | 0/5 | 5/5 | | | |
| Change filter to Green, held out (`held_change_filter`) | 5/5 | 5/5 | | | |
| M31 session (`tier2_m31_session`) | 0/5 | 0/5 | 1/5 | 2/5 | **3/5** |
| Pointing offset (`tier3_pointing_offset`) | 1/8 | 0/5 | 0/5 | 1/5 | **5/5** |

Empty cells were not rerun.

## What this shows, and what it does not

- **Each failure had a different cause, and a server change fixed it.** Hours against degrees, an id against a name, and
  a missing repeat count all come from the tool, not from reasoning. After the RA change, no run ended tens of degrees
  from M31.
- **A clearer error was not enough for qwen.** It cut rejected `count` calls from 18 to 7 and stopped the retry loop, but
  most runs still gave up after the first rejection. In one run it wrote that `count` was not valid and then planned to
  use `count`. The argument it expected is what fixed it: all 10 runs in the last column called `count: 5` once.
- **The remaining 2 failures are the simulator, not the model.** The camera returned "no response from device" at frame 3
  of 5 in one run and frame 2 of 5 in the other. The tool stopped there and reported how many frames were taken.
  Other queues have left out runs for the same device drops; these two are kept in because they ran to the end.
- **The `count` argument is a choice.** It makes the tool easier for weak models, so a result with it is not comparable
  with the v1 numbers in the README, which still describe the pinned v1 server.
- **One model, small samples.** qwen3:8b only, five runs per cell, and the stronger models were not rerun. Pass rates
  of 3/5 against 1/5 are suggestive, not a measured effect. The run logs are kept outside `runs/`, so the README
  charts and totals still show the baseline.
