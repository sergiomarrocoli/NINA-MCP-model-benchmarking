"""Run every task for every provider several times.

    python -m harness.batch --providers openai deepseek --repeats 5
    python -m harness.batch --providers openai --tasks tier1_park_mount --repeats 2

Runs are sequential, since all of them share one set of simulated equipment. A run that crashes
(simulators down, reset failing) is reported and skipped; it is not a model failure.
"""
import argparse
import asyncio
import json

from harness.providers import PROVIDERS
from harness.run import run
from harness.tasks import TASKS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", nargs="+", choices=PROVIDERS, required=True)
    ap.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    crashed = 0
    for task in args.tasks:
        for provider in args.providers:
            for i in range(1, args.repeats + 1):
                label = f"{task} / {provider} / {i} of {args.repeats}"
                try:
                    path = asyncio.run(run(provider, task))
                except (Exception, SystemExit) as e:
                    crashed += 1
                    print(f"{label}: CRASHED ({type(e).__name__}: {e})")
                    continue
                end = json.loads(path.read_text().splitlines()[-1])
                print(f"{label}: {'pass' if end['passed'] else 'FAIL'} {end['failures']}")
    if crashed:
        print(f"{crashed} run(s) crashed and are not in the report")


if __name__ == "__main__":
    main()
