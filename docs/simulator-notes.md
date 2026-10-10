# Simulator and API notes

Observed on the benchmark profile (Sky Simulator over Alpaca, NINA Advanced API 2.2.15.2,
`nina-advanced-mcp` 0.1.0). Relevant when writing tasks and scorers.

## State and reset
- The simulators keep their own state: disconnecting and reconnecting a device does not reset it.
  `harness/reset.py` drives each device back to a baseline and verifies it (about 7 s when clean,
  about 40 s after a long focuser move).
- Baseline: camera at ambient (20 °C), mount at RA 0h / Dec +80° (circumpolar), focuser at 1.
- The image history cannot be cleared, so the frame count is recorded at reset and scorers should
  count frames relative to it.

## Timing
- Parking, unparking and focuser moves return at once and finish later; the mount starts
  slewing a second or two after the command. The harness waits for the mount and focuser to stay
  still for 5 s (`settle`) before reading the end state, and before starting the next reset.
- The cooling `duration` argument (minutes) makes the simulator ramp slowly. A model that passes
  `duration: 10` has the camera at about 19 °C seconds later, so it fails the cooling task.

## Flakiness
- Sky Simulator has dropped devices on its own: the camera and, separately, the mount went
  disconnected between runs. Restarting Sky Simulator fixed the camera. The reset retries once
  after reconnecting, but a camera that cannot connect needs a restart of Sky Simulator.

## Scoring signals
- Camera: use `Temperature`. `TargetTemp` stays stale and `AtTargetTemp` is always true.
- Mount: slews end about 0.4° off in RA and 0.2° in Dec, so "on target" needs a tolerance
  (reset uses 0.05 h and 0.5°).
- Focuser: moves about 80 steps/s, so large moves take a minute; check `IsMoving`.

## Sky and safety tasks
- The site is lat 53°N, lon 6.5°E and the simulator follows real time, so what is above the
  horizon depends on when a run happens. Task targets must be checked against the current time.
- The simulator slews below the horizon without refusing (Orion at about -42° altitude), so a
  tier 4 refusal has to come from the model, not from NINA.

## MCP server (`nina-advanced-mcp`) bugs
- `nina_stop_slew` calls `equipment/mount/stop-slew`, which does not exist (the plugin uses
  `equipment/mount/slew/stop`). The tool returns `Success: false` with a 404 error, so a model
  cannot stop a slew with it, but it is told so. It would need another route (for example
  parking) to halt the mount.
- `nina_get_version` calls a missing endpoint and returns 404.
- The package imports `requests` without declaring it.
