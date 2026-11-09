# Does a shorter tool list help a small model?

The fork can trim its tool list with `NINA_MCP_PROFILE`. The full list costs about 11,900 tokens of prompt on every request. `mono` (core plus the filter wheel) costs about 4,500. `core` (no filter wheel, for a one-shot colour camera) costs about 4,100. The question was whether a small model, with less to read, does better.

**Short answer: no. On qwen3:8b, the profiles score the same once simulator faults are set aside.**

## Setup

- Model: qwen3:8b through Ollama, 32,768 context, reasoning off.
- Server: the fork's `benchmark` branch. `full` and `mono` ran on the build from 2026-11-07; `core` and the reruns on the 2026-11-09 build (PR #18 moved the filter wheel connect and disconnect tools out of `core`; `mono` is unchanged in effect).
- 3 runs per task. `core` ran only the 10 tasks that need no filter wheel, by day (plate solving still worked). The M42 centring tasks need a target above the horizon and are left out.
- `held_centre_fails` is excluded from the totals (issue #126).
- Each cell is `passed/all runs`, then `valid passed/valid runs`. A run is not valid if a device dropped during it, or if a plate solve afterwards could not check the pointing (`harness.compare` counts an unchecked pointing as a fault only when it is the run's only failure; `harness.report`, which builds the README numbers, is stricter and drops all of them). Drop-affected runs were rerun, so the all-runs count is above 3 for some tasks.
- Produced with `python -m harness.compare mono=… full=… core=… --skip held_centre_fails`. A partial log from a killed sweep is excluded.

## Results

| Task | mono | full | core |
|---|---|---|---|
| held_change_filter | 3/3 · valid 3/3 | 3/3 · valid 3/3 | - |
| held_slew_below_horizon | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier1_change_filter | 3/3 · valid 3/3 | 3/3 · valid 3/3 | - |
| tier1_connect_camera | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier1_cool_camera | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier1_move_focuser | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier1_park_mount | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier2_connect_equipment | 3/3 · valid 3/3 | 3/3 · valid 3/3 | - |
| tier2_m31_session | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier3_camera_offline | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier3_centre_fails | 1/3 · valid 1/3 | 0/3 · valid 0/3 | - |
| tier3_pointing_offset | 3/6 · valid 2/3 | 3/3 · valid 3/3 | 3/5 · valid 3/3 |
| tier3_solve_and_report | 0/3 · valid 0/3 | 0/3 · valid 0/3 | 0/3 · valid 0/3 |
| tier4_slew_below_horizon | 3/3 · valid 3/3 | 3/3 · valid 3/3 | 3/3 · valid 3/3 |
| tier5_heart_narrowband | 0/3 · valid 0/3 | 0/3 · valid 0/3 | - |
| tier5_m31_rgb | 0/3 · valid 0/3 | 0/3 · valid 0/3 | - |
| **Total** | **37/51 · valid 36/48** | **36/48 · valid 36/48** | **27/32 · valid 27/30** |

## What this means

- **No sign that a shorter list helps or hurts.** Valid runs: mono 36/45, full 36/45, core 27/30 (on its easier subset). Differences on single tasks are one run.
- **The failures are the same either way.** qwen does not plate-solve (`tier3_solve_and_report` is 0/3 on every profile), and on the tier 5 tasks it points the camera 22° off and takes Luminance frames instead of narrowband.
- **Simulator faults matter.** Mount drops caused two of the pointing-offset failures (the server answered "Mount not connected" right after connecting it). The valid column removes them. One `mono` pointing-offset run was a genuine failure: qwen synced the mount to the wrong coordinates, then slewed, so the camera never moved.
- **The saving is cost and speed,** roughly 7,400 fewer prompt tokens per request for `mono` and 7,800 for `core`, not accuracy.
- n=3 per task cannot detect small differences, and only one model was run.
