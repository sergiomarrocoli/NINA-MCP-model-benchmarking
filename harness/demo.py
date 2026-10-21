"""A preview of the results section built from made-up numbers, so the shape of the analysis can be judged before
there are real results.

    python -m harness.demo              # rewrite the preview block in the README and docs/charts-demo/

Nothing here is a measurement. The pass rates are invented, every chart carries a DUMMY DATA stamp, and the preview
sits in its own block, apart from the real results. It also adds the vague end-to-end tasks (#70) when the benchmark
does not have them yet, so the preview shows where those results will go.
"""
import argparse
import random
from contextlib import contextmanager
from pathlib import Path

from harness import report
from harness.pricing import cost
from harness.tasks import TASKS, Task

DEMO_START = "<!-- demo:start -->"
DEMO_END = "<!-- demo:end -->"
DEMO_CHARTS_DIR = Path("docs/charts-demo")
WATERMARK = "DUMMY DATA"
REPEATS = 5

# Invented pass rate per model for the first tier and the drop per tier after it. Chosen so the charts show a spread.
MODELS = {"gpt-4.1": (0.95, 0.12), "deepseek-chat": (0.85, 0.16), "qwen3:8b": (0.65, 0.18)}
MODELS_RANK = {m: i for i, m in enumerate(MODELS, 1)}  # 1 = the strongest invented model; the weaker ones make more unsafe calls
# The vague end-to-end tasks (#70), with their real prompts. They are only added here when the benchmark does not have
# them yet, so the preview shows where they will go.
VAGUE_TASKS = [
    Task(id="tier5_m31_rgb", tier=5, prompt="I want RGB frames of M31."),
    Task(id="tier5_heart_narrowband", tier=5, prompt="I want 5 minute narrowband frames of the Heart Nebula."),
]


def missing_tasks() -> list[Task]:
    return [t for t in VAGUE_TASKS if t.id not in TASKS]


@contextmanager
def with_vague_tasks():
    added = missing_tasks()
    TASKS.update({t.id: t for t in added})
    try:
        yield
    finally:
        for t in added:
            del TASKS[t.id]


def fake_runs(seed: int = 7) -> list[dict]:
    """Run records in the shape `report.load_run` returns, with invented outcomes."""
    rng = random.Random(seed)
    runs = []
    for model, (base, drop) in MODELS.items():
        for task in TASKS.values():
            rate = max(0.0, base - drop * (task.tier - 1))
            for _ in range(REPEATS):
                prompt_tokens = rng.randint(9_000, 30_000) * task.tier
                runs.append({
                    "model": model, "provider": "demo", "task": task.id, "tier": task.tier,
                    "passed": rng.random() < rate, "finished": True,
                    "tool_calls": rng.randint(2, 6) * task.tier, "invalid_calls": rng.randint(0, 2),
                    "unsafe_calls": int(rng.random() < 0.04 * (4 - MODELS_RANK[model])), "prompt_tokens": prompt_tokens, "completion_tokens": rng.randint(100, 600),
                    "cost": cost(model, prompt_tokens, 300), "seconds": rng.uniform(5, 40) * task.tier,
                    "device_drops": 0, "schema": "flat",
                })
    return runs


def update_preview(readme: Path = report.README, charts_dir: Path = DEMO_CHARTS_DIR) -> int:
    banner = ("> **Dummy data.** Everything in this section is invented, to show the analysis the real results will get. "
              "It is not a measurement of any model.")
    if missing := missing_tasks():
        banner += f" The task{'s' if len(missing) > 1 else ''} {' and '.join(f'`{t.id}`' for t in missing)} {'are' if len(missing) > 1 else 'is'} not in the benchmark yet (#70)."
    banner += "\n\n"
    with with_vague_tasks():
        runs = fake_runs()
        report.update_readme(readme, report.aggregate(runs), len(runs), charts_dir=charts_dir,
                             markers=(DEMO_START, DEMO_END), banner=banner, watermark=WATERMARK,
                             regenerate="python -m harness.demo")
    return len(runs)


def main():
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    n = update_preview()
    print(f"wrote the dummy-data preview ({n} invented runs) to {report.README} and {DEMO_CHARTS_DIR}")


if __name__ == "__main__":
    main()
