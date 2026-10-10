"""Aggregate run logs into per-model, per-task metrics.

    python -m harness.report            # markdown table to stdout
    python -m harness.report --json     # the same numbers as JSON

Only runs that reached an `end` record count; runs that crashed (for example because the
simulators were down) are not model failures and are left out.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from harness.pricing import cost, is_estimated

RUNS_DIR = Path("runs")


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


def markdown(rows: list[dict]) -> str:
    head = ("| Task | Model | Runs | Pass rate | Tool calls | Invalid | Unsafe | Tokens in/out | Cost/run | Time |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    lines = [head]
    for r in rows:
        cost_text = "n/a" if r["cost"] is None else f"{'~' if r['cost_estimated'] else ''}${r['cost']:.4f}"
        lines.append(
            f"| {r['task']} | {r['model']} | {r['runs']} | {r['passes']}/{r['runs']} ({r['pass_rate']:.0%}) "
            f"| {r['tool_calls']:.1f} | {r['invalid_calls']:.1f} | {r['unsafe_calls']} "
            f"| {r['prompt_tokens']:.0f} / {r['completion_tokens']:.0f} | {cost_text} | {r['seconds']:.1f}s |"
        )
    if any(r["cost_estimated"] for r in rows):
        lines.append("\n`~` cost is an estimate for a model with no listed price. Costs are upper bounds (no cached-token discount).")
    lines.append("Tool calls, invalid calls, tokens and time are per-run means; unsafe calls are totals.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    runs = [r for p in sorted(args.runs_dir.glob("*.jsonl")) if (r := load_run(p))]
    rows = aggregate(runs)
    print(json.dumps(rows, indent=2) if args.json else markdown(rows))


if __name__ == "__main__":
    main()
