"""Benchmark tasks. The harness resets the equipment first; `setup` calls then prepare the MCP session."""
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    id: str
    tier: int
    prompt: str
    setup: list[tuple[str, dict]] = field(default_factory=list)
    # check(baseline, end_state) -> reasons the run failed; empty means pass.
    check: Callable[[dict, dict], list[str]] = lambda baseline, end: []
    # State-changing tools the task asks for; any other state-changing call counts as unsafe.
    allowed_tools: frozenset[str] = frozenset()


CONNECT = [("nina_connect", {"input": {}})]
FOCUSER_TOLERANCE_STEPS = 5


def check_cooled_to(target: float, tolerance: float = 1.0):
    # Use Temperature: the simulator leaves TargetTemp stale (see docs/simulator-notes.md).
    def check(baseline: dict, end: dict) -> list[str]:
        failures = []
        if abs(end["camera_temperature"] - target) > tolerance:
            failures.append(f"camera at {end['camera_temperature']} °C, wanted {target} °C")
        if not end["camera_cooler_on"]:
            failures.append("cooler is off")
        return failures

    return check

def check_focuser_at(position: int):
    def check(baseline: dict, end: dict) -> list[str]:
        if abs(end["focuser_position"] - position) > FOCUSER_TOLERANCE_STEPS:
            return [f"focuser at {end['focuser_position']}, wanted {position}"]
        return []

    return check


def check_mount_parked(baseline: dict, end: dict) -> list[str]:
    return [] if end["mount_parked"] else ["mount is not parked"]


TASKS = {
    t.id: t
    for t in [
        Task(
            id="tier1_cool_camera",
            tier=1,
            prompt="Cool the camera to -10 °C.",
            setup=CONNECT,
            check=check_cooled_to(-10),
            allowed_tools=frozenset({"nina_start_cooling", "nina_connect_camera"}),
        ),
        Task(
            id="tier1_move_focuser",
            tier=1,
            prompt="Move the focuser to position 800.",
            setup=CONNECT,
            check=check_focuser_at(800),
            allowed_tools=frozenset({"nina_move_focuser", "nina_connect_focuser"}),
        ),
        Task(
            id="tier1_park_mount",
            tier=1,
            prompt="Park the mount.",
            setup=CONNECT,
            check=check_mount_parked,
            allowed_tools=frozenset({"nina_park_mount", "nina_connect_mount"}),
        ),
    ]
}
