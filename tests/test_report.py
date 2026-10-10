import json

import pytest

from harness.pricing import cost, is_estimated
from harness.report import aggregate, load_run, markdown


def write_run(path, *, model="gpt-4.1", task="tier1_cool_camera", passed=True, tools=1, invalid=0,
              prompt=10_000, completion=50, seconds=5.0, unsafe=(), finished=True, ended=True):
    events = [{"kind": "start", "task": task, "tier": 1, "provider": "openai", "model": model}]
    if ended:
        events.append({"kind": "end", "passed": passed, "finished": finished, "seconds": seconds,
                       "unsafe_calls": list(unsafe),
                       "totals": {"tool_calls": tools, "invalid_calls": invalid,
                                  "prompt_tokens": prompt, "completion_tokens": completion}})
    path.write_text("\n".join(json.dumps(e) for e in events))
    return path


def test_cost_uses_per_million_rates():
    assert cost("gpt-4.1", 1_000_000, 1_000_000) == pytest.approx(10.0)
    assert cost("gpt-4.1", 10_000, 50) == pytest.approx(0.0204)


def test_unknown_model_has_no_cost():
    assert cost("some-local-model", 1000, 1000) is None
    assert not is_estimated("some-local-model")


def test_stand_in_price_is_flagged_as_estimate():
    assert is_estimated("deepseek-chat") and not is_estimated("gpt-4.1")


def test_pass_rate_and_means(tmp_path):
    runs = [
        load_run(write_run(tmp_path / "a.jsonl", passed=True, tools=1, seconds=4)),
        load_run(write_run(tmp_path / "b.jsonl", passed=False, tools=5, invalid=4, seconds=8)),
    ]
    (row,) = aggregate(runs)
    assert (row["runs"], row["passes"], row["pass_rate"]) == (2, 1, 0.5)
    assert row["tool_calls"] == 3 and row["invalid_calls"] == 2 and row["seconds"] == 6


def test_unsafe_calls_are_summed_across_runs(tmp_path):
    runs = [
        load_run(write_run(tmp_path / "a.jsonl", unsafe=["nina_slew_mount", "nina_move_focuser"])),
        load_run(write_run(tmp_path / "b.jsonl", unsafe=["nina_slew_mount"])),
    ]
    assert aggregate(runs)[0]["unsafe_calls"] == 3


def test_models_and_tasks_are_grouped_separately(tmp_path):
    runs = [
        load_run(write_run(tmp_path / "a.jsonl", model="gpt-4.1")),
        load_run(write_run(tmp_path / "b.jsonl", model="deepseek-chat")),
        load_run(write_run(tmp_path / "c.jsonl", task="tier1_park_mount")),
    ]
    assert len(aggregate(runs)) == 3


def test_crashed_run_without_end_record_is_skipped(tmp_path):
    assert load_run(write_run(tmp_path / "a.jsonl", ended=False)) is None


def test_unfinished_run_counts_as_a_run_and_is_marked(tmp_path):
    run = load_run(write_run(tmp_path / "a.jsonl", passed=False, finished=False))
    (row,) = aggregate([run])
    assert row["runs"] == 1 and row["unfinished"] == 1


def test_markdown_marks_estimated_cost(tmp_path):
    runs = [load_run(write_run(tmp_path / "a.jsonl", model="deepseek-chat"))]
    text = markdown(aggregate(runs))
    assert "~$" in text and "estimate" in text
