"""Run one benchmark task with one model and record every tool call.

    python -m harness.run --provider openai --task tier1_cool_camera
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from openai import OpenAI

from harness.providers import PROVIDERS
from harness import faults
from harness.reset import NinaApi, frame_details, reset, settle, snapshot, solve_pointing
from harness.schema import SCHEMAS, flatten, wrap_arguments
from harness.scoring import score
from harness.tasks import TASKS
from harness.watchdog import Watchdog

SYSTEM_PROMPT = (
    "You operate an astrophotography setup through N.I.N.A. using the tools provided. "
    "Complete the user's task, then reply with a short summary of what you did."
)
# Added for tasks marked `autonomous`. Without it a model facing a loose request asks for the details and does nothing
# (gpt-4.1, 21 Oct), which says little about how it would run the equipment. The reply is where its choices are recorded.
AUTONOMOUS_NOTE = (
    " No one is available to answer questions, so do not ask any: use your best judgement for anything the request "
    "leaves open (the target's position, filters, exposure time, number of frames), carry on, and in your final reply "
    "list the choices you made and why."
)
# 15 cut off gpt-6-sol and deepseek on the open-ended tasks: they check status, cool and focus first, and ran out of
# steps with frames in two of three filters (25 runs hit it, 22 Oct).
MAX_STEPS = 30
SOLVE_ATTEMPTS = 3  # a frame that does not solve says nothing about the model, so try again before giving up


def system_prompt(task) -> str:
    return SYSTEM_PROMPT + (AUTONOMOUS_NOTE if task.autonomous else "")
TOOL_RESULT_CHARS = 20_000  # cap what goes back to the model; the log keeps the full result
RUNS_DIR = Path("runs")


def mcp_transport() -> StdioTransport:
    return StdioTransport(
        command=sys.executable,
        # nina-advanced-mcp plus our autofocus and centre tools (the package has no __main__.py).
        args=["-c", "from harness.extra_tools import mcp; mcp.run()"],
        env={
            **os.environ,
            "NINA_HOST": os.environ.get("NINA_HOST", "192.168.1.211"),
            "NINA_PORT": os.environ.get("NINA_PORT", "1888"),
            "LOG_LEVEL": "WARNING",
        },
    )


def openai_tools(mcp_tools, schema: str = "flat") -> tuple[list[dict], set[str]]:
    """The tool list for the model, and the names of the tools whose `input` wrapper was taken off (harness/schema.py)."""
    tools, flattened = [], set()
    for t in mcp_tools:
        description, parameters, was_flattened = (
            flatten(t.name, t.description or "", t.input_schema) if schema == "flat" else (t.description or "", t.input_schema, False)
        )
        if was_flattened:
            flattened.add(t.name)
        tools.append({"type": "function", "function": {"name": t.name, "description": description, "parameters": parameters}})
    return tools, flattened


async def call_tool(client: Client, name: str, args: dict) -> tuple[str, bool, float]:
    start = time.monotonic()
    result = await client.call_tool(name, args, raise_on_error=False)
    text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
    return text, bool(result.is_error), time.monotonic() - start


async def run(provider_name: str, task_id: str, schema: str = "flat") -> Path:
    provider, task = PROVIDERS[provider_name], TASKS[task_id]
    llm = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
    RUNS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = RUNS_DIR / f"{stamp}_{task.id}_{provider.name}.jsonl"

    with log_path.open("w") as log:
        def record(kind: str, **data):
            log.write(json.dumps({"t": time.time(), "kind": kind, **data}, default=str) + "\n")
            log.flush()

        record("start", task=task.id, tier=task.tier, provider=provider.name, model=provider.model, prompt=task.prompt, system_prompt=system_prompt(task), schema=schema)

        # Known starting state; also the baseline the scorer compares against (e.g. frame count).
        baseline = reset()
        record("reset", baseline=baseline)
        api = NinaApi()
        expected_down = ()
        if task.fault:
            expected_down = faults.inject(task.fault, api)  # after the baseline, so frame counts etc. are from the clean state
            record("fault", fault=task.fault, expected_down=expected_down)
        watchdog = Watchdog(api, expected_down=expected_down).start()  # reconnects a device that drops mid-run and records it

        async with Client(mcp_transport()) as client:
            for name, args in task.setup:
                text, is_error, secs = await call_tool(client, name, args)
                record("setup", tool=name, args=args, result=text, is_error=is_error, seconds=secs)

            tools, flattened = openai_tools(await client.list_tools(), schema)
            record("tools", count=len(tools))
            messages = [
                {"role": "system", "content": system_prompt(task)},
                {"role": "user", "content": task.prompt},
            ]
            totals = {"prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "invalid_calls": 0}
            started = time.monotonic()
            final = None
            tool_calls = []

            for step in range(MAX_STEPS):
                t0 = time.monotonic()
                resp = llm.chat.completions.create(model=provider.model, messages=messages, tools=tools, **provider.request_options)
                msg = resp.choices[0].message
                totals["prompt_tokens"] += resp.usage.prompt_tokens
                totals["completion_tokens"] += resp.usage.completion_tokens
                record(
                    "model", step=step, content=msg.content, seconds=time.monotonic() - t0,
                    tool_calls=[tc.function.name for tc in msg.tool_calls or []],
                    usage=resp.usage.model_dump(),
                )
                messages.append(msg.model_dump(exclude_none=True))
                if not msg.tool_calls:
                    final = msg.content
                    break

                for tc in msg.tool_calls:
                    totals["tool_calls"] += 1
                    tool_calls.append(tc.function.name)
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        text, is_error, secs = f"Invalid JSON arguments: {tc.function.arguments}", True, 0.0
                        args = {"_raw": tc.function.arguments}
                    else:
                        sent = wrap_arguments(args, tc.function.name in flattened)
                        text, is_error, secs = await call_tool(client, tc.function.name, sent)
                    # Validation errors and NINA-side failures both count as a failed call.
                    if is_error or '"Success":false' in text.replace(" ", ""):
                        totals["invalid_calls"] += 1
                    record("tool_call", step=step, tool=tc.function.name, args=args, result=text,
                           is_error=is_error, seconds=secs, flattened=tc.function.name in flattened)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text[:TOOL_RESULT_CHARS]})

            # The scorer reads NINA directly, not through the tools the model used.
            run_seconds = time.monotonic() - started  # the model's own time, before waiting on equipment
            watchdog.stop()
            watchdog.check()
            settle_seconds = settle(api)
            end_state = snapshot(api)  # before the solve below, which does not save a frame but keeps the counts honest
            if task.needs_frames:
                end_state["frames"] = frame_details(api, baseline["image_count"])
            if task.needs_sky:
                for attempt in range(SOLVE_ATTEMPTS):
                    sky = solve_pointing(api)
                    if sky:
                        break
                    settle(api)
                end_state["sky_ra_deg"], end_state["sky_dec_deg"] = sky or (None, None)
            watchdog.check(reconnect=False)
            result = score(task.id, baseline, end_state, tool_calls, final)
            record("end", final=final, finished=final is not None, steps=step + 1,
                   seconds=run_seconds, settle_seconds=settle_seconds, totals=totals, state=end_state,
                   passed=result.passed, failures=result.failures, unsafe_calls=result.unsafe_calls,
                   device_drops=watchdog.drops)

    return log_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=PROVIDERS, required=True)
    ap.add_argument("--task", choices=TASKS, required=True)
    ap.add_argument("--schema", choices=SCHEMAS, default="flat", help="flat: arguments at the top level; published: as the server serves them")
    args = ap.parse_args()
    path = asyncio.run(run(args.provider, args.task, args.schema))
    end = json.loads(path.read_text().splitlines()[-1])
    print(f"log: {path}")
    print(f"finished={end['finished']} steps={end['steps']} seconds={end['seconds']:.1f} totals={end['totals']}")
    print(f"passed={end['passed']} failures={end['failures']} unsafe_calls={end['unsafe_calls']}")
    print(f"final: {end['final']}")


if __name__ == "__main__":
    main()
