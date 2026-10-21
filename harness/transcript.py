"""Read a run log as a story, for judging the model's choices by eye.

    python -m harness.transcript runs/20261021T190947Z_tier5_heart_narrowband_openai.jsonl [more logs]

Prints the task, what the model said and called (with arguments and the start of each result), the reply, and
what ended up on the equipment: the frames' filters and exposures and where the camera pointed.
"""
import argparse
import json
from pathlib import Path

RESULT_CHARS = 160


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def one_line(value, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def transcript(events: list[dict], result_chars: int = RESULT_CHARS) -> str:
    start = next(e for e in events if e["kind"] == "start")
    end = next((e for e in events if e["kind"] == "end"), None)
    out = [f"# {start['task']} ({start['model']})", f"Prompt: {start['prompt']}"]
    system = start.get("system_prompt")
    if system and "No one is available" in system:
        out.append("System note: nobody can answer questions; use best judgement and list the choices")
    if end:
        verdict = "PASSED" if end["passed"] else "FAILED: " + "; ".join(end["failures"])
        out.append(f"Result: {verdict}" + (f" | unsafe calls: {', '.join(end['unsafe_calls'])}" if end["unsafe_calls"] else ""))
    else:
        out.append("Result: no end record (the run crashed or was stopped)")
    out.append("")
    for e in events:
        if e["kind"] == "model" and e.get("content"):
            out.append(f"[step {e['step']}] says: {one_line(e['content'], 400)}")
        elif e["kind"] == "tool_call":
            args = json.dumps(e["args"], ensure_ascii=False) if e["args"] else ""
            flag = " (error)" if e.get("is_error") else ""
            out.append(f"[step {e['step']}] {e['tool']} {args}{flag}\n    -> {one_line(e['result'], result_chars)}")
    if end:
        state = end["state"]
        frames = state.get("frames")
        out += ["", "On the equipment at the end:"]
        if frames is not None:
            out.append(f"  {len(frames)} new frame(s): " + (", ".join(f"{f['filter']} {f['exposure_s']} s" for f in frames) or "none"))
        if state.get("sky_ra_deg") is not None:
            out.append(f"  camera points at RA {state['sky_ra_deg']:.3f}°, Dec {state['sky_dec_deg']:.3f}° (plate solve, J2000)")
        out += ["", "Final reply:", end["final"] or "(none)"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--result-chars", type=int, default=RESULT_CHARS, help="how much of each tool result to show")
    args = ap.parse_args()
    print(("\n\n" + "=" * 72 + "\n\n").join(transcript(load(p), args.result_chars) for p in args.logs))


if __name__ == "__main__":
    main()
