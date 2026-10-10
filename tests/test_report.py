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


def test_update_readme_replaces_only_the_results_block(tmp_path):
    from harness.report import RESULTS_END, RESULTS_START, update_readme

    readme = tmp_path / "README.md"
    readme.write_text(f"# Title\n\nintro\n\n{RESULTS_START}\nold results\n{RESULTS_END}\n\n## After\nkeep me\n")
    runs = [load_run(write_run(tmp_path / "a.jsonl"))]
    update_readme(readme, aggregate(runs), len(runs))
    text = readme.read_text()
    assert "old results" not in text and "tier1_cool_camera" in text and "from 1 runs" in text
    assert text.startswith("# Title\n\nintro") and text.rstrip().endswith("keep me")
    update_readme(readme, aggregate(runs), len(runs))  # idempotent
    assert text.count(RESULTS_START) == 1 and readme.read_text().count(RESULTS_START) == 1


def test_update_readme_needs_markers(tmp_path):
    from harness.report import update_readme

    readme = tmp_path / "README.md"
    readme.write_text("# no markers\n")
    with pytest.raises(SystemExit):
        update_readme(readme, [], 0)


def test_markdown_is_a_matrix_with_models_along_the_top(tmp_path):
    runs = [
        load_run(write_run(tmp_path / "a.jsonl", model="gpt-4.1", passed=True)),
        load_run(write_run(tmp_path / "b.jsonl", model="deepseek-chat", passed=False)),
        load_run(write_run(tmp_path / "c.jsonl", model="gpt-4.1", task="tier1_park_mount")),
    ]
    lines = markdown(aggregate(runs)).splitlines()
    assert lines[0] == "| Task | Metric | deepseek-chat | gpt-4.1 |"
    pass_row = next(l for l in lines if "Pass rate" in l and "tier1" not in l)
    assert "0/1 (0%)" in pass_row and "1/1 (100%)" in pass_row
    park_pass = [l for l in lines if "Pass rate" in l][1]
    assert park_pass.split("|")[3].strip() == "–"  # deepseek-chat has no run for the second task
