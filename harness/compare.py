"""Compare runs from several folders side by side, with and without the runs hit by equipment faults.

    python -m harness.compare mono=runs-mono/runs full=runs-full/runs core=runs-core/runs

Each cell is `passed/all runs`, then `valid passed/valid runs` once the runs the report leaves out are removed:
a device that dropped during the run, or a plate solve that could not check the pointing afterwards
(see `harness.report.load_run`). Logs with no end record, such as one from a killed sweep, are ignored.
"""
import argparse
from collections import defaultdict
from pathlib import Path

from harness.report import load_run


def load(folder: Path, exclude: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    by_task = defaultdict(list)
    for path in sorted(folder.glob("*.jsonl")):
        if any(x in path.name for x in exclude):
            continue
        if run := load_run(path):
            by_task[run["task"]].append(run)
    return by_task


def cell(runs: list[dict]) -> str:
    if not runs:
        return "-"
    valid = [r for r in runs if not r["device_drops"]]
    return f"{sum(r['passed'] for r in runs)}/{len(runs)} · valid {sum(r['passed'] for r in valid)}/{len(valid)}"


def table(folders: dict[str, dict[str, list[dict]]], skip: tuple[str, ...] = ()) -> str:
    tasks = sorted({t for f in folders.values() for t in f} - set(skip))
    lines = ["| Task | " + " | ".join(folders) + " |", "|---|" + "---|" * len(folders)]
    for task in tasks:
        lines.append(f"| {task} | " + " | ".join(cell(f.get(task, [])) for f in folders.values()) + " |")
    totals = []
    for f in folders.values():
        runs = [r for t, rs in f.items() if t not in skip for r in rs]
        valid = [r for r in runs if not r["device_drops"]]
        totals.append(f"**{sum(r['passed'] for r in runs)}/{len(runs)} · valid {sum(r['passed'] for r in valid)}/{len(valid)}**")
    lines.append("| **Total** | " + " | ".join(totals) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", help="label=path to a folder of run logs")
    ap.add_argument("--skip", nargs="*", default=[], help="task ids left out of the table and totals")
    ap.add_argument("--exclude", nargs="*", default=[], help="log file name fragments to ignore")
    args = ap.parse_args()
    folders = {}
    for item in args.folders:
        label, _, path = item.partition("=")
        folders[label] = load(Path(path), tuple(args.exclude))
    print(table(folders, tuple(args.skip)))


if __name__ == "__main__":
    main()
