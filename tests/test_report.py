import json

import pytest

from harness.pricing import cost, is_estimated
from harness.report import aggregate, load_run, markdown


def write_run(path, *, model="gpt-4.1", task="tier1_cool_camera", passed=True, tools=1, invalid=0,
              prompt=10_000, completion=50, seconds=5.0, unsafe=(), finished=True, ended=True, drops=(), schema="flat", tier=1, failures=()):
    events = [{"kind": "start", "task": task, "tier": tier, "provider": "openai", "model": model}]
    if schema:
        events[0]["schema"] = schema
    if ended:
        events.append({"kind": "end", "passed": passed, "finished": finished, "seconds": seconds,
                       "unsafe_calls": list(unsafe), "device_drops": list(drops), "failures": list(failures),
                       "totals": {"tool_calls": tools, "invalid_calls": invalid,
                                  "prompt_tokens": prompt, "completion_tokens": completion}})
    path.write_text("\n".join(json.dumps(e) for e in events))
    return path


def test_cost_uses_per_million_rates():
    assert cost("gpt-4.1", 1_000_000, 1_000_000) == pytest.approx(10.0)
    assert cost("gpt-4.1", 10_000, 50) == pytest.approx(0.0204)


def test_cached_input_is_priced_at_the_cached_rate_where_one_is_known():
    # 1M prompt tokens, 900k of them cached: 100k at $2 + 900k at $0.50
    assert cost("gpt-4.1", 1_000_000, 0, cached_tokens=900_000) == pytest.approx(0.2 + 0.45)
    assert cost("gpt-6-sol", 1_000_000, 0, cached_tokens=900_000) == pytest.approx(0.2 + 0.18)
    assert cost("deepseek-chat", 1_000_000, 0, cached_tokens=900_000) == pytest.approx(0.03 + 0.0054)
    # a model with no cached rate prices cached tokens as uncached
    assert cost("qwen3:8b", 1_000_000, 0, cached_tokens=900_000) == 0


def test_load_run_prices_the_cached_tokens_the_model_calls_report(tmp_path):
    path = write_run(tmp_path / "a.jsonl", prompt=10_000, completion=0)
    events = [json.loads(l) for l in path.read_text().splitlines()]
    events.insert(1, {"kind": "model", "usage": {"prompt_tokens": 10_000, "prompt_tokens_details": {"cached_tokens": 9_000}}})
    path.write_text("\n".join(json.dumps(e) for e in events))
    assert load_run(path)["cost"] == pytest.approx(0.002 + 0.0045)


def test_deepseek_pro_is_priced_with_its_cached_rate():
    assert cost("deepseek-v4-pro", 1_000_000, 1_000_000, cached_tokens=1_000_000) == pytest.approx(0.044 + 3.96)
    assert not is_estimated("deepseek-v4-pro")


def test_deepseek_pro_runs_with_thinking_off(monkeypatch):
    from harness.providers import PROVIDERS

    monkeypatch.setenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
    pro = PROVIDERS["deepseek-pro"]
    assert pro.model == "deepseek-v4-pro" and pro.request_options == {"extra_body": {"thinking": {"type": "disabled"}}}


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


def test_run_with_a_device_drop_is_flagged_and_old_logs_have_none(tmp_path):
    assert load_run(write_run(tmp_path / "a.jsonl", drops=[{"device": "focuser", "t": 1.0}]))["device_drops"] == 1
    old = tmp_path / "old.jsonl"  # logged before drops were recorded: no device_drops key
    old.write_text("\n".join(json.dumps(e) for e in [
        {"kind": "start", "task": "t", "tier": 1, "provider": "p", "model": "m"},
        {"kind": "end", "passed": True, "finished": True, "seconds": 1, "unsafe_calls": [],
         "totals": {"tool_calls": 1, "invalid_calls": 0, "prompt_tokens": 1, "completion_tokens": 1}}]))
    assert load_run(old)["device_drops"] == 0


def test_main_leaves_out_runs_with_drops_and_says_so(tmp_path, capsys, monkeypatch):
    from harness import report

    write_run(tmp_path / "a.jsonl", passed=True)
    write_run(tmp_path / "b.jsonl", passed=False, drops=[{"device": "mount", "t": 1.0}])
    monkeypatch.setattr("sys.argv", ["report", "--runs-dir", str(tmp_path)])
    report.main()
    out = capsys.readouterr()
    assert "1/1 (100%)" in out.out and "1 run(s) left out" in out.err


def test_a_run_the_scorer_could_not_check_is_left_out_like_a_device_drop(tmp_path):
    run = load_run(write_run(tmp_path / "a.jsonl", passed=False, failures=["could not plate solve to check where the camera points"]))
    assert run["device_drops"] == 1
    assert load_run(write_run(tmp_path / "b.jsonl", passed=False, failures=["0 blue frames, wanted 1"]))["device_drops"] == 0


def test_a_readme_with_a_details_block_gets_only_the_images_in_the_results_block(tmp_path):
    from harness.report import DETAILS_END, DETAILS_START, RESULTS_END, RESULTS_START, update_readme
    readme = tmp_path / "README.md"
    readme.write_text(f"{RESULTS_START}\nSTALE\n{RESULTS_END}\nmiddle\n{DETAILS_START}\nSTALE\n{DETAILS_END}\n")
    rows = aggregate([load_run(write_run(tmp_path / f"{i}.jsonl", task=t, tier=1)) for i, t in enumerate(("tier1_cool_camera", "tier1_park_mount", "tier1_move_focuser"))])
    update_readme(readme, rows, 3, charts_dir=tmp_path / "charts")
    text = readme.read_text()
    results = text[text.index(RESULTS_START):text.index(RESULTS_END)]
    details = text[text.index(DETAILS_START):text.index(DETAILS_END)]
    assert "overview.svg" in results and "runs passed" not in results and "Cool the camera" not in results and "Updated" not in results
    assert "STALE" not in text and "runs passed" in details and "`tier1_cool_camera`" in details and "All numbers" in details


def test_the_task_table_covers_every_task_in_chart_order_and_says_how_each_starts_and_passes():
    from harness.report import tasks_table
    from harness.tasks import PASS_CONDITIONS, TASKS, display_order, start_condition
    assert set(PASS_CONDITIONS) == set(TASKS)
    lines = tasks_table().splitlines()
    assert lines[0].startswith("| Task | Type | Prompt | Starts with | Passes if |") and len(lines) == 2 + len(TASKS)
    assert [line.split("`")[1] for line in lines[2:]] == display_order()
    assert "1000 steps out of focus" in start_condition(TASKS["tier3_centre_fails"])
    assert "2° off" in start_condition(TASKS["tier3_pointing_offset"])
    assert "best judgement" in start_condition(TASKS["tier5_m31_rgb"]) and "best judgement" not in start_condition(TASKS["tier1_park_mount"])


def test_update_readme_refreshes_a_tasks_block(tmp_path):
    from harness.report import TASKS_END, TASKS_START, RESULTS_END, RESULTS_START, update_readme
    readme = tmp_path / "README.md"
    readme.write_text(f"{RESULTS_START}\nx\n{RESULTS_END}\n{TASKS_START}\nSTALE\n{TASKS_END}\n")
    update_readme(readme, [], 0)
    text = readme.read_text()
    assert "STALE" not in text and "`tier1_park_mount`" in text and "| Task | Type | Prompt | Starts with | Passes if |" in text


def test_load_run_reads_the_schema_and_older_runs_count_as_published(tmp_path):
    assert load_run(write_run(tmp_path / "old.jsonl", schema=None))["schema"] == "published"
    assert load_run(write_run(tmp_path / "new.jsonl"))["schema"] == "flat"


def test_main_reports_one_schema_at_a_time(tmp_path, capsys, monkeypatch):
    from harness import report

    write_run(tmp_path / "a.jsonl", passed=True)
    write_run(tmp_path / "b.jsonl", passed=False, schema="published")
    monkeypatch.setattr("sys.argv", ["report", "--runs-dir", str(tmp_path)])
    report.main()
    out = capsys.readouterr()
    assert "1/1 (100%)" in out.out and "left out: made with published schemas" in out.err


# --- a device the model disconnected itself is not a drop ---

def log_with_calls(path, calls, drops):
    events = [{"kind": "start", "task": "t", "tier": 1, "provider": "ollama", "model": "qwen3:8b", "schema": "flat"}]
    events += [{"kind": "tool_call", "tool": tool, "t": t, "result": result} for t, tool, result in calls]
    events.append({"kind": "end", "passed": False, "finished": True, "seconds": 1, "unsafe_calls": [], "failures": [],
                   "device_drops": drops, "totals": {"tool_calls": len(calls), "invalid_calls": 0, "prompt_tokens": 1, "completion_tokens": 1}})
    path.write_text("\n".join(json.dumps(e) for e in events))
    return path


def test_a_drop_right_after_the_model_disconnected_that_device_does_not_count(tmp_path):
    path = log_with_calls(tmp_path / "a.jsonl", [(100.0, "nina_disconnect_camera", '{"Success":true}')],
                          [{"device": "camera", "t": 102.0}])
    assert load_run(path)["device_drops"] == 0


def test_nina_disconnect_covers_every_device(tmp_path):
    path = log_with_calls(tmp_path / "a.jsonl", [(100.0, "nina_disconnect", '{"Success":true}')],
                          [{"device": "mount", "t": 101.0}, {"device": "focuser", "t": 101.0}])
    assert load_run(path)["device_drops"] == 0


def test_a_drop_of_another_device_still_counts(tmp_path):
    path = log_with_calls(tmp_path / "a.jsonl", [(100.0, "nina_disconnect_camera", '{"Success":true}')],
                          [{"device": "camera", "t": 101.0}, {"device": "mount", "t": 101.0}])
    assert load_run(path)["device_drops"] == 1


def test_a_drop_before_the_disconnect_or_after_a_failed_one_still_counts(tmp_path):
    early = log_with_calls(tmp_path / "a.jsonl", [(200.0, "nina_disconnect_camera", '{"Success":true}')], [{"device": "camera", "t": 100.0}])
    failed = log_with_calls(tmp_path / "b.jsonl", [(100.0, "nina_disconnect_camera", '{"Success": false}')], [{"device": "camera", "t": 101.0}])
    assert load_run(early)["device_drops"] == 1 and load_run(failed)["device_drops"] == 1
