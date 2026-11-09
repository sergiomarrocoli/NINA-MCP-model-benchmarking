# Does a shorter tool list help a small model?

The fork can trim its tool list with `NINA_MCP_PROFILE`. The full list costs about 11,900 tokens of prompt on every request. The `mono` profile costs about 4,500. The question was whether a small model, with less to read, does better.

**Short answer: no. On qwen2.5:7b, the two profiles scored identically.**

## Setup

- Model: qwen2.5:7b through Ollama, 32,768 context, reasoning off.
- Server: the fork's `benchmark` branch, with the harness arm from PR #125.
- 17 tasks, 3 runs each, once per profile (`mono`, then `full`).
- `held_centre_fails` is left out of the totals. Its target can be below the horizon at some hours, so it does not always test centring (issue #126).
- One partial log from a sweep killed before a reboot is excluded.

## Results

| Task | mono | full |
|---|---|---|
| held_change_filter | 3/3 | 3/3 |
| held_slew_below_horizon | 3/3 | 3/3 |
| tier1_change_filter | 3/3 | 3/3 |
| tier1_connect_camera | 3/3 | 3/3 |
| tier1_cool_camera | 3/3 | 3/3 |
| tier1_move_focuser | 3/3 | 3/3 |
| tier1_park_mount | 3/3 | 3/3 |
| tier2_connect_equipment | 3/3 | 3/3 |
| tier2_m31_session | 3/3 | 3/3 |
| tier3_camera_offline | 3/3 | 3/3 |
| tier3_centre_fails | 1/3 | 0/3 |
| tier3_pointing_offset | 2/3 | 3/3 |
| tier3_solve_and_report | 0/3 | 0/3 |
| tier4_slew_below_horizon | 3/3 | 3/3 |
| tier5_heart_narrowband | 0/3 | 0/3 |
| tier5_m31_rgb | 0/3 | 0/3 |
| **Total** | **36/48** | **36/48** |

(`tier3_centre_fails` and `tier3_pointing_offset` differ by one run each, in opposite directions, which is within run-to-run noise at n=3. Two of the `mono` pointing-offset runs had simulator device drops.)

## What this means

- Easy and mid tasks pass at the same rate either way, so the trimmed list loses nothing there.
- The failures are the same in both: qwen does not plate-solve, does not report a failed centre, and on the tier 5 tasks it points the camera 22° off and takes Luminance frames instead of narrowband.
- At this size the bottleneck is the model's behaviour, not the length of the tool list.
- The saving is real but is about cost and speed (roughly 7,400 fewer prompt tokens per request), not accuracy.
- n=3 per task cannot detect small differences. Other models were not run.
