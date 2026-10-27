"""Aggregate run logs into per-model, per-task metrics.

    python -m harness.report            # markdown table to stdout
    python -m harness.report --json     # the same numbers as JSON

Only runs that reached an `end` record count; runs that crashed (for example because the
simulators were down) are not model failures and are left out.
"""
import argparse
import json
import re
import sys
from datetime import date
from collections import defaultdict
from pathlib import Path
from statistics import mean

from harness.charts import CHARTS_DIR, write_charts
from harness.pricing import cost, is_estimated
from harness.scoring import score
from harness.watchdog import POLL_S
from harness.tasks import PASS_CONDITIONS, TASKS, display_order, start_condition, tier_name

RUNS_DIR = Path("runs")
README = Path("README.md")
RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
TASKS_START = "<!-- tasks:start -->"
TASKS_END = "<!-- tasks:end -->"
DETAILS_START = "<!-- details:start -->"
DETAILS_END = "<!-- details:end -->"


def equipment_drops(events: list[dict], end: dict) -> list[dict]:
    """The logged drops that were not the model's own doing. Before the watchdog learned to tell, a device the model
    disconnected itself (qwen3:8b does, at the end of imaging runs) was logged as a drop and the run left out."""
    disconnects = [(e["t"], e["tool"]) for e in events
                   if e["kind"] == "tool_call" and e.get("tool", "").startswith("nina_disconnect")
                   and '"Success":false' not in e.get("result", "").replace(" ", "")]
    drops = end.get("device_drops", [])
    return [d for d in drops
            if not any(t <= d["t"] + POLL_S and tool in ("nina_disconnect", f"nina_disconnect_{d['device']}")
                       for t, tool in disconnects)]


def rescored(events: list[dict], start: dict, end: dict) -> tuple[bool, list[str], int]:
    """(passed, failures, unsafe calls) from the scorer as it is now, so a fix to the scorer also corrects the runs
    already logged. A log the scorer cannot read (an old task, a log without a baseline) keeps its recorded verdict."""
    try:
        baseline = next(e["baseline"] for e in events if e["kind"] == "reset")
        calls = [e for e in events if e["kind"] == "tool_call"]
        result = score(start["task"], baseline, end["state"], [c["tool"] for c in calls], end.get("final"), calls)
    except (StopIteration, KeyError):
        return end["passed"], end.get("failures", []), len(end["unsafe_calls"])
    return result.passed, result.failures, len(result.unsafe_calls)


def load_run(path: Path) -> dict | None:
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    start = next((e for e in events if e["kind"] == "start"), None)
    end = next((e for e in events if e["kind"] == "end"), None)
    if start is None or end is None:
        return None
    totals = end["totals"]
    passed, failures, unsafe = rescored(events, start, end)
    # The run's token total does not separate the ones served from the provider's cache; each model call does.
    details = [((e.get("usage") or {}).get("prompt_tokens_details") or {}) for e in events if e["kind"] == "model"]
    cached = sum(d.get("cached_tokens") or 0 for d in details)
    written = sum(d.get("cache_write_tokens") or 0 for d in details)
    return {
        "model": start["model"],
        "provider": start["provider"],
        "task": start["task"],
        "tier": start["tier"],
        "passed": passed,
        "finished": end["finished"],
        "tool_calls": totals["tool_calls"],
        "invalid_calls": totals["invalid_calls"],
        "unsafe_calls": unsafe,
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "cost": cost(start["model"], totals["prompt_tokens"], totals["completion_tokens"], cached, written),
        "seconds": end["seconds"],
        # A device that dropped during the run makes it an equipment fault, not a model result.
        # A plate solve that failed after the run left the pointing unchecked, which is equipment too.
        "device_drops": len(equipment_drops(events, end)) + any("could not plate solve" in f for f in failures),
        # Runs before the schema option used the published tools.
        "schema": start.get("schema", "published"),
    }


def load_runs(runs_dir: Path, schema: str) -> tuple[list[dict], int, list[dict]]:
    """The runs that count: (runs, how many were left out for a device drop, runs made with another schema)."""
    loaded = [r for p in sorted(runs_dir.glob("*.jsonl")) if (r := load_run(p))]
    other_schema = [r for r in loaded if r["schema"] != schema]
    loaded = [r for r in loaded if r["schema"] == schema]  # flat and published runs are not comparable
    runs = [r for r in loaded if not r["device_drops"]]
    return runs, len(loaded) - len(runs), other_schema


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
        lines.append("\n`~` cost is an estimate for a model with no listed price. Cached input tokens are priced at the cached rate.")
    lines.append("Tool calls, invalid calls, tokens and time are per-run means; unsafe calls are totals.")
    return "\n".join(lines)


def overall(rows: list[dict]) -> str:
    """One line per model: passes over runs across every task."""
    totals = defaultdict(lambda: [0, 0])
    for r in rows:
        totals[r["model"]][0] += r["passes"]
        totals[r["model"]][1] += r["runs"]
    return "\n".join(f"- **{m}**: {p}/{n} runs passed ({p / n:.0%})" for m, (p, n) in sorted(totals.items()))


def images_markdown(drawn: dict[str, str], charts_dir: Path) -> str:
    """Just the chart images: the per-model radar plots, the cost and unsafe-calls panels, and the per-task grid."""
    rel = charts_dir.as_posix()
    return "\n\n".join(f"![{title}]({rel}/{drawn[key]})" for key, title in (
        ("radar", "Pass rate by task type, one plot per model"),
        ("summary", "Cost, and invalid and unsafe calls"),
        ("overview", "Pass rate by task")) if key in drawn)


def task_list_markdown(rows: list[dict]) -> str:
    """Every task with its type and full prompt (the grid cuts long prompts short). Tasks with no runs are marked."""
    ran = {r["task"] for r in rows}
    return "\n".join(f"- `{task_id}` ({tier_name(TASKS[task_id].tier)}){'' if task_id in ran else ', not run yet'}: {TASKS[task_id].prompt}"
                     for task_id in display_order())


def tasks_table() -> str:
    """Every task, in chart order: its prompt, how it starts, and what the scorer checks. Built from the task definitions."""
    cell = lambda x: x.replace("|", "\\|")
    rows = [f"| `{t}` | {tier_name(TASKS[t].tier)} | {cell(TASKS[t].prompt)} | {cell(start_condition(TASKS[t]))} | {cell(PASS_CONDITIONS[t])} |"
            for t in display_order()]
    return "\n".join(["| Task | Type | Prompt | Starts with | Passes if |", "| --- | --- | --- | --- | --- |", *rows])


def charts_markdown(rows: list[dict], drawn: dict[str, str], charts_dir: Path) -> str:
    """The chart images, then every task with its type and full prompt."""
    return "\n\n".join(part for part in (images_markdown(drawn, charts_dir), task_list_markdown(rows)) if part)


def update_readme(path: Path, rows: list[dict], runs: int, excluded: int = 0, charts_dir: Path | None = None) -> None:
    """Replace the generated blocks in the README, between their markers.

    The results block holds only the chart images. If the README also has a details block, the written numbers, the task
    prompts and the full tables go there. Without one, everything goes in the results block.
    """
    text = path.read_text()
    block = re.compile(re.escape(RESULTS_START) + r".*?" + re.escape(RESULTS_END), re.S)
    if not block.search(text):
        raise SystemExit(f"{path} has no {RESULTS_START} ... {RESULTS_END} block")
    details_block = re.compile(re.escape(DETAILS_START) + r".*?" + re.escape(DETAILS_END), re.S)
    split = bool(details_block.search(text)) and charts_dir is not None
    left_out = f" ({excluded} more left out: a device dropped during the run)" if excluded else ""
    stamp = (f"_Updated {date.today().isoformat()} from {runs} runs{left_out}. "
             f"Regenerate with `python -m harness.report --update-readme`._\n\n")
    if charts_dir is None:
        results = f"{RESULTS_START}\n{stamp}{markdown(rows)}\n{RESULTS_END}"
        details = None
    elif not rows:
        results = f"{RESULTS_START}\n{stamp}_No results yet._\n{RESULTS_END}"
        details = f"{DETAILS_START}\n_No results yet._\n{DETAILS_END}"
    else:
        drawn = write_charts(rows, charts_dir)
        if split:
            results = f"{RESULTS_START}\n{images_markdown(drawn, charts_dir)}\n{RESULTS_END}"
            details = (f"{DETAILS_START}\n{stamp}### Overall\n\n{overall(rows)}\n\n### The tasks\n\n{task_list_markdown(rows)}\n\n"
                       f"<details><summary>All numbers</summary>\n\n{markdown(rows)}\n\n</details>\n{DETAILS_END}")
        else:
            results = (f"{RESULTS_START}\n{stamp}### Overall\n\n{overall(rows)}\n\n### By task\n\n{charts_markdown(rows, drawn, charts_dir)}\n\n"
                       f"<details><summary>All numbers</summary>\n\n{markdown(rows)}\n\n</details>\n{RESULTS_END}")
            details = None
    text = block.sub(lambda _: results, text)
    if split:
        text = details_block.sub(lambda _: details, text)
    tasks_block = re.compile(re.escape(TASKS_START) + r".*?" + re.escape(TASKS_END), re.S)
    if tasks_block.search(text):
        text = tasks_block.sub(lambda _: f"{TASKS_START}\n{tasks_table()}\n{TASKS_END}", text)
    path.write_text(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--schema", choices=("flat", "published"), default="flat", help="report only runs made with these tool schemas")
    ap.add_argument("--update-readme", action="store_true", help=f"rewrite the results block in {README}")
    args = ap.parse_args()
    runs, excluded, other_schema = load_runs(args.runs_dir, args.schema)
    if other_schema:
        print(f"{len(other_schema)} run(s) left out: made with {other_schema[0]['schema']} schemas, not {args.schema}", file=sys.stderr)
    rows = aggregate(runs)
    if args.update_readme:
        update_readme(README, rows, len(runs), excluded, CHARTS_DIR)
        print(f"updated {README} from {len(runs)} runs ({excluded} left out for device drops)")
        return
    if excluded:
        print(f"{excluded} run(s) left out: a device dropped during the run", file=sys.stderr)
    print(json.dumps(rows, indent=2) if args.json else markdown(rows))


if __name__ == "__main__":
    main()
