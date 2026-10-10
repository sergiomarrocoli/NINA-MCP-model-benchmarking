"""Aggregate run logs into per-model, per-task metrics.

    python -m harness.report            # markdown table to stdout
    python -m harness.report --json     # the same numbers as JSON

Only runs that reached an `end` record count; runs that crashed (for example because the
simulators were down) are not model failures and are left out.
"""
import argparse
import json
import re
from datetime import date
from collections import defaultdict
from pathlib import Path
from statistics import mean

from harness.pricing import cost, is_estimated

RUNS_DIR = Path("runs")
README = Path("README.md")
RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"


def load_run(path: Path) -> dict | None:
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    start = next((e for e in events if e["kind"] == "start"), None)
    end = next((e for e in events if e["kind"] == "end"), None)
    if start is None or end is None:
        return None
    totals = end["totals"]
    return {
        "model": start["model"],
        "provider": start["provider"],
        "task": start["task"],
        "tier": start["tier"],
        "passed": end["passed"],
        "finished": end["finished"],
        "tool_calls": totals["tool_calls"],
        "invalid_calls": totals["invalid_calls"],
        "unsafe_calls": len(end["unsafe_calls"]),
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "cost": cost(start["model"], totals["prompt_tokens"], totals["completion_tokens"]),
        "seconds": end["seconds"],
    }


def aggregate(runs: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in runs:
        groups[(r["model"], r["task"])].append(r)
    rows = []
    for (model, task), rs in sorted(groups.items(), key=lambda kv: (kv[1][0]["tier"], kv[0][1], kv[0][0])):
        costs = [r["cost"] for r in rs if r["cost"] is not None]
        rows.append({
            "model": model,
            "task": task,
            "tier": rs[0]["tier"],
            "runs": len(rs),
            "passes": sum(r["passed"] for r in rs),
            "pass_rate": sum(r["passed"] for r in rs) / len(rs),
            "unfinished": sum(not r["finished"] for r in rs),
            "tool_calls": mean(r["tool_calls"] for r in rs),
            "invalid_calls": mean(r["invalid_calls"] for r in rs),
            "unsafe_calls": sum(r["unsafe_calls"] for r in rs),
            "prompt_tokens": mean(r["prompt_tokens"] for r in rs),
            "completion_tokens": mean(r["completion_tokens"] for r in rs),
            "cost": mean(costs) if costs else None,
            "cost_estimated": is_estimated(model),
            "seconds": mean(r["seconds"] for r in rs),
        })
    return rows


def cost_text(row: dict) -> str:
    if row["cost"] is None:
        return "n/a"
    return f"{'~' if row['cost_estimated'] else ''}${row['cost']:.4f}"


# One matrix row per metric: (label, how to show it for a model's aggregated row).
METRICS = [
    ("Runs", lambda r: str(r["runs"])),
    ("Pass rate", lambda r: f"{r['passes']}/{r['runs']} ({r['pass_rate']:.0%})"),
    ("Tool calls", lambda r: f"{r['tool_calls']:.1f}"),
    ("Invalid calls", lambda r: f"{r['invalid_calls']:.1f}"),
    ("Unsafe calls", lambda r: str(r["unsafe_calls"])),
    ("Tokens in / out", lambda r: f"{r['prompt_tokens']:.0f} / {r['completion_tokens']:.0f}"),
    ("Cost per run", cost_text),
    ("Time", lambda r: f"{r['seconds']:.1f}s"),
]


def markdown(rows: list[dict]) -> str:
    """A matrix: models along the top, each task's metrics down the side."""
    models = sorted({r["model"] for r in rows})
    by_key = {(r["task"], r["model"]): r for r in rows}
    tasks = list(dict.fromkeys(r["task"] for r in rows))  # rows are already ordered by tier, then task
    lines = ["| Task | Metric | " + " | ".join(models) + " |", "| --- | --- | " + " | ".join("---" for _ in models) + " |"]
    for task in tasks:
        for i, (label, show) in enumerate(METRICS):
            cells = [show(by_key[task, m]) if (task, m) in by_key else "–" for m in models]
            lines.append(f"| {f'**{task}**' if i == 0 else ''} | {label} | " + " | ".join(cells) + " |")
    if any(r["cost_estimated"] for r in rows):
        lines.append("\n`~` cost is an estimate for a model with no listed price. Costs are upper bounds (no cached-token discount).")
    lines.append("Tool calls, invalid calls, tokens and time are per-run means; unsafe calls are totals.")
    return "\n".join(lines)


def update_readme(path: Path, rows: list[dict], runs: int) -> None:
    """Replace the results block in the README, between the results markers."""
    text = path.read_text()
    block = re.compile(re.escape(RESULTS_START) + r".*?" + re.escape(RESULTS_END), re.S)
    if not block.search(text):
        raise SystemExit(f"{path} has no {RESULTS_START} ... {RESULTS_END} block")
    body = (f"{RESULTS_START}\n_Updated {date.today().isoformat()} from {runs} runs. "
            f"Regenerate with `python -m harness.report --update-readme`._\n\n{markdown(rows)}\n{RESULTS_END}")
    path.write_text(block.sub(lambda _: body, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-readme", action="store_true", help=f"rewrite the results block in {README}")
    args = ap.parse_args()
    runs = [r for p in sorted(args.runs_dir.glob("*.jsonl")) if (r := load_run(p))]
    rows = aggregate(runs)
    if args.update_readme:
        update_readme(README, rows, len(runs))
        print(f"updated {README} from {len(runs)} runs")
        return
    print(json.dumps(rows, indent=2) if args.json else markdown(rows))


if __name__ == "__main__":
    main()
