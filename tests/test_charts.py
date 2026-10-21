from xml.dom import minidom

from harness.charts import calls_panel, cost_panel, overview_chart, radar_panel, summary_chart, tier_scores, write_charts, colours
from harness.report import RESULTS_END, RESULTS_START, aggregate, load_run, update_readme
from harness.tasks import TASKS
from tests.test_report import write_run


def rows_for(tmp_path, spec):
    """spec: (model, task, passed) per run."""
    runs = [load_run(write_run(tmp_path / f"{i}.jsonl", model=m, task=t, passed=p, tier=TASKS[t].tier))
            for i, (m, t, p) in enumerate(spec)]
    return aggregate(runs)


FOUR_TIERS = ["tier1_cool_camera", "tier2_m31_session", "tier3_centre_fails", "tier4_slew_below_horizon"]


def test_overview_cell_has_the_prompt_the_counts_and_not_run(tmp_path):
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True), ("a", "tier1_cool_camera", False), ("b", "tier1_cool_camera", True)])
    out = overview_chart(rows, ["a", "b", "c"], colours(["a", "b", "c"]))
    minidom.parseString(out)
    assert TASKS["tier1_cool_camera"].prompt in out and "tier1_cool_camera" in out
    assert "50%" in out and "100%" in out and "n=2" in out and "n=1" in out
    assert "not run" in out  # model c has no runs


def test_prompt_is_escaped_and_long_prompts_are_cut_with_an_ellipsis(tmp_path, monkeypatch):
    task = TASKS["tier1_cool_camera"].__class__(id="tier1_cool_camera", tier=1, prompt='Cool <b> & "hold" ' + "word " * 60)
    monkeypatch.setitem(TASKS, "tier1_cool_camera", task)
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True)])
    out = overview_chart(rows, ["a"], colours(["a"]))
    minidom.parseString(out)
    assert "…" in out and "&lt;b&gt;" in out


def test_tier_scores_pool_runs_across_tasks(tmp_path):
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True), ("a", "tier1_park_mount", False), ("a", "tier1_park_mount", True)])
    assert tier_scores(rows) == {"a": {1: (2, 3)}}


def panel_text(panel):
    body, _, _ = panel
    return "\n".join(body)


def test_radar_needs_three_types_and_skips_a_model_missing_one(tmp_path):
    two = rows_for(tmp_path, [("a", t, True) for t in FOUR_TIERS[:2]])
    assert radar_panel(two, ["a"], colours(["a"])) is None
    spec = [(m, t, True) for m in "ab" for t in FOUR_TIERS] + [("c", FOUR_TIERS[0], True)]
    rows = rows_for(tmp_path, spec)
    out = panel_text(radar_panel(rows, ["a", "b", "c"], colours(["a", "b", "c"])))
    assert out.count('fill-opacity="0.15"') == 2 and "No polygon for c" in out
    assert "Safety" in out and "tier4" not in out  # axes carry the type names


def test_cost_panel_totals_runs_per_model_and_marks_unpriced_and_estimated(tmp_path):
    def row(model, **kw):
        return {"model": model, "runs": 4, "cost": 0.25, "cost_estimated": False, "invalid_calls": 0, "unsafe_calls": 0, **kw}
    rows = [row("a"), row("a", cost=0.5), row("b", cost_estimated=True), row("c", cost=None), row("c")]
    out = panel_text(cost_panel(rows, ["a", "b", "c", "d"], colours(list("abcd"))))
    assert "$3.00" in out          # a: 4 x 0.25 + 4 x 0.5
    assert "~$1.00" in out         # b: estimated price, marked
    assert "no price" in out       # c: one run unpriced, so no partial total
    assert "not run" in out        # d


def test_calls_panel_pools_means_by_runs_and_unsafe_by_total(tmp_path):
    rows = [{"model": "a", "runs": 1, "invalid_calls": 4.0, "unsafe_calls": 0},
            {"model": "a", "runs": 3, "invalid_calls": 0.0, "unsafe_calls": 1}]
    out = panel_text(calls_panel(rows, ["a"], colours(["a"])))
    assert ">1.0<" in out and ">0.2<" in out  # invalid 4 / 4 runs = 1.0; unsafe 1 / 4 runs = 0.25 shown as 0.2


def test_summary_is_valid_svg_with_all_three_panels(tmp_path):
    rows = rows_for(tmp_path, [("a", t, True) for t in FOUR_TIERS])
    out = summary_chart(rows, ["a"], colours(["a"]))
    minidom.parseString(out)
    assert out.count("<svg x=") == 3 and summary_chart([], [], {}) is None


def test_write_charts_writes_the_summary_and_the_grid_and_removes_stale_files(tmp_path):
    out = tmp_path / "charts"
    out.mkdir()
    (out / "tier4_slew_below_horizon.svg").write_text("stale")
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True)])
    assert write_charts(rows, out) == {"summary": "summary.svg", "overview": "overview.svg"}
    assert sorted(p.name for p in out.glob("*.svg")) == ["overview.svg", "summary.svg"]
    rows = rows_for(tmp_path, [("a", t, True) for t in FOUR_TIERS])


def test_readme_gets_prompts_charts_and_not_run_notes(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{RESULTS_START}\nSTALE\n{RESULTS_END}\noutro\n")
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True)])
    update_readme(readme, rows, 1, charts_dir=tmp_path / "charts")
    text = readme.read_text()
    assert text.startswith("intro\n") and text.endswith("outro\n") and "STALE" not in text
    assert f"`tier1_cool_camera` (single command): {TASKS['tier1_cool_camera'].prompt}" in text and "overview.svg" in text
    assert "**a**: 1/1 runs passed (100%)" in text
    assert text.count(", not run yet:") == len(TASKS) - 1


def test_readme_with_no_runs_says_so(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"{RESULTS_START}\nold\n{RESULTS_END}\n")
    update_readme(readme, [], 0, charts_dir=tmp_path / "charts")
    assert "_No results yet._" in readme.read_text()


def test_demo_preview_is_stamped_apart_from_the_real_results_and_leaves_tasks_alone(tmp_path):
    from harness import demo
    from harness.report import RESULTS_END, RESULTS_START
    readme = tmp_path / "README.md"
    readme.write_text(f"{RESULTS_START}\nREAL\n{RESULTS_END}\n{demo.DEMO_START}\n{demo.DEMO_END}\n")
    tasks_before = set(TASKS)
    demo.update_preview(readme, tmp_path / "charts")
    text = readme.read_text()
    assert set(TASKS) == tasks_before  # the invented task does not leak out
    assert f"{RESULTS_START}\nREAL\n{RESULTS_END}" in text
    assert "**Dummy data.**" in text and "demo" in text.split(demo.DEMO_START)[1]
    assert all("DUMMY DATA" in p.read_text() for p in (tmp_path / "charts").glob("*.svg"))
    assert "tier5_heart_narrowband" in (tmp_path / "charts" / "overview.svg").read_text()


def test_overview_has_every_task_with_runs_in_a_grid_and_names_each_task(tmp_path):
    spec = [("a", t, True) for t in FOUR_TIERS + ["tier1_park_mount", "tier1_move_focuser"]]
    out = overview_chart(rows_for(tmp_path, spec), ["a"], colours(["a"]), columns=3)
    minidom.parseString(out)
    assert out.count("<svg x=") == 6  # one nested chart per task
    assert all(t in out for t in FOUR_TIERS)
    assert overview_chart([], [], {}) is None


def test_display_order_puts_simple_tasks_first_and_the_m31_tasks_last():
    from harness.tasks import display_order
    order = display_order()
    assert sorted(order) == sorted(TASKS)
    m31 = [t for t in order if "M31" in TASKS[t].prompt]
    assert order[-len(m31):] == m31                       # all the M31 tasks, together, at the end
    rest = order[:-len(m31)]
    assert [TASKS[t].tier for t in rest] == sorted(TASKS[t].tier for t in rest)  # tier order within each group
    assert [TASKS[t].tier for t in m31] == sorted(TASKS[t].tier for t in m31)
    assert order[0].startswith("tier1_")
