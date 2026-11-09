from harness.compare import cell, load, table
from tests.test_report import write_run


def test_cell_counts_all_and_valid_runs(tmp_path):
    write_run(tmp_path / "a.jsonl", passed=True)
    write_run(tmp_path / "b.jsonl", passed=False, drops=[{"device": "mount", "t": 1.0}])
    write_run(tmp_path / "c.jsonl", passed=True)
    runs = load(tmp_path)["tier1_cool_camera"]
    assert cell(runs) == "2/3 · valid 2/2"


def test_unfinished_logs_and_excluded_names_are_ignored(tmp_path):
    write_run(tmp_path / "a.jsonl")
    write_run(tmp_path / "partial.jsonl", ended=False)
    write_run(tmp_path / "old_run.jsonl")
    assert len(load(tmp_path, exclude=("old_run",))["tier1_cool_camera"]) == 1


def test_table_skips_tasks_and_totals_each_folder(tmp_path):
    (tmp_path / "x").mkdir()
    write_run(tmp_path / "x" / "a.jsonl", task="tier1_cool_camera")
    write_run(tmp_path / "x" / "b.jsonl", task="held_centre_fails", passed=False, tier=5)
    out = table({"x": load(tmp_path / "x")}, skip=("held_centre_fails",))
    assert "held_centre_fails" not in out
    assert "**1/1 · valid 1/1**" in out


def test_unchecked_pointing_is_valid_when_the_run_also_missed_other_requirements(tmp_path):
    only = ["could not plate solve to check where the camera points"]
    write_run(tmp_path / "a.jsonl", passed=False, failures=only)
    write_run(tmp_path / "b.jsonl", passed=False, failures=only + ["0 red frames, wanted 1"])
    runs = load(tmp_path)["tier1_cool_camera"]
    assert cell(runs) == "0/2 · valid 0/1"
