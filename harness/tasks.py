"""Benchmark tasks. `setup` calls run before the model sees the task, to put NINA in a known state."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    id: str
    tier: int
    prompt: str
    setup: list[tuple[str, dict]] = field(default_factory=list)


CONNECT = [("nina_connect", {"input": {}})]

TASKS = {
    t.id: t
    for t in [
        Task(
            id="tier1_cool_camera",
            tier=1,
            prompt="Cool the camera to -10 °C.",
            setup=CONNECT + [("nina_connect_camera", {"input": {}})],
        ),
    ]
}
