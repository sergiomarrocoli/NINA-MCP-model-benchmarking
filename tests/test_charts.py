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


def test_summary_is_the_cost_and_calls_panels_only(tmp_path):
    rows = rows_for(tmp_path, [("a", t, True) for t in FOUR_TIERS])
    out = summary_chart(rows, ["a"], colours(["a"]))
    minidom.parseString(out)
    assert out.count("<svg x=") == 2 and "Total cost of all runs" in out and "Invalid and unsafe calls per run" in out
    assert "Pass rate by task type" not in out and summary_chart([], [], {}) is None


def test_the_radar_chart_has_one_plot_per_model_each_titled_with_its_name(tmp_path):
    from harness.charts import radar_chart
    rows = rows_for(tmp_path, [(m, t, True) for m in ("a", "b", "c") for t in FOUR_TIERS])
    out = radar_chart(rows, ["a", "b", "c"], colours(["a", "b", "c"]))
    minidom.parseString(out)
    assert out.count("<svg x=") == 3 and out.count("<polygon points") >= 3 * 4 + 3  # rings per plot, and a polygon for each
    assert all(f">{m}</text>" in out for m in "abc")
    assert radar_chart([], [], {}) is None


def test_a_model_missing_a_task_type_gets_dots_and_a_note_not_a_polygon(tmp_path):
    from harness.charts import radar_panel
    rows = rows_for(tmp_path, [("a", t, True) for t in FOUR_TIERS] + [("b", t, True) for t in FOUR_TIERS[:2]])
    out = panel_text(radar_panel(rows, ["b"], colours(["a", "b"]), title="b"))
    assert "<circle" in out and "No polygon: not run on" in out


def test_write_charts_writes_the_summary_and_the_grid_and_removes_stale_files(tmp_path):
    out = tmp_path / "charts"
    out.mkdir()
    (out / "tier4_slew_below_horizon.svg").write_text("stale")
    rows = rows_for(tmp_path, [("a", "tier1_cool_camera", True)])
    assert write_charts(rows, out) == {"summary": "summary.svg", "overview": "overview.svg"}  # one task: too few types for a radar
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


def test_overview_has_every_task_with_runs_in_a_grid_and_names_each_task(tmp_path):
    spec = [("a", t, True) for t in FOUR_TIERS + ["tier1_park_mount", "tier1_move_focuser"]]
    out = overview_chart(rows_for(tmp_path, spec), ["a"], colours(["a"]), columns=3)
    minidom.parseString(out)
    assert out.count("<svg x=") == 6  # one nested chart per task
    assert all(t in out for t in FOUR_TIERS)
    assert overview_chart([], [], {}) is None


def test_overview_is_two_charts_to_a_row_by_default_and_the_cells_are_wider(tmp_path):
    import re
    spec = [("a", t, True) for t in FOUR_TIERS + ["tier1_park_mount", "tier1_move_focuser"]]
    rows = rows_for(tmp_path, spec)
    two, three = overview_chart(rows, ["a"], colours(["a"])), overview_chart(rows, ["a"], colours(["a"]), columns=3)
    xs = lambda out: sorted({float(x) for x in re.findall(r'<svg x="([\d.]+)" y=', out)})
    assert len(xs(two)) == 2 and len(xs(three)) == 3
    width = lambda out: int(re.search(r'width="(\d+)"', out).group(1))
    assert abs(width(two) - width(three)) < 80  # about the same total width, so the image does not shrink in the README


def test_models_are_charted_in_the_chosen_order_and_unknown_ones_go_last():
    from harness.charts import model_order
    names = ["gpt-6-sol", "claude-opus-5-5", "zeta", "qwen3:8b", "gpt-4.1", "claude-haiku-5-5", "alpha", "deepseek-chat",
             "claude-sonnet-5-5", "deepseek-v4-pro"]
    assert model_order(names) == ["qwen3:8b", "deepseek-chat", "deepseek-v4-pro", "claude-haiku-5-5", "claude-sonnet-5-5",
                                  "claude-opus-5-5", "gpt-4.1", "gpt-6-sol", "alpha", "zeta"]


def test_each_model_keeps_its_colour_whichever_models_are_in_the_chart():
    names = ["qwen3:8b", "deepseek-chat", "deepseek-v4-pro", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "gpt-4.1", "gpt-6-sol"]
    assert colours(names)["claude-haiku-5-5"] == "#0072B2" and colours(names)["gpt-6-sol"] == "#F0E442"


def test_eight_models_get_eight_different_colours():
    names = ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5", "deepseek-chat", "deepseek-v4-pro", "gpt-4.1", "gpt-6-sol", "qwen3:8b"]
    assert len(set(colours(names).values())) == 8


def test_model_names_are_broken_at_a_hyphen_when_one_line_will_not_fit():
    from harness.charts import label_mode, split_name
    assert split_name("claude-sonnet-5-5") == ["claude-", "sonnet-5-5"]
    assert split_name("deepseek-v4-pro") == ["deepseek-", "v4-pro"]
    assert split_name("qwen3:8b") == ["qwen3:", "8b"] and split_name("gpt") == ["gpt"]
    names = ["claude-sonnet-5-5", "gpt-4.1"]
    assert label_mode(names, 120) == "one" and label_mode(names, 65) == "two" and label_mode(names, 40) == "rotated"


def test_in_two_line_mode_only_the_names_that_do_not_fit_are_broken():
    from harness.charts import model_labels
    body = []
    model_labels(body, ["claude-sonnet-5-5", "gpt-4.1"], [30, 100], 10, "two", slot=65)
    texts = [t for t in body if t.startswith("<text")]
    assert len(texts) == 3  # claude-sonnet-5-5 in two lines, gpt-4.1 in one
    assert any(">gpt-4.1<" in t for t in texts) and any(">claude-<" in t for t in texts)


def test_with_many_models_every_chart_stays_valid_svg_and_the_names_fit_on_two_lines(tmp_path):
    from harness.charts import radar_chart
    names = ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5", "deepseek-chat", "deepseek-v4-pro", "gpt-4.1", "gpt-6-sol", "qwen3:8b"]
    spec = [(m, t, True) for m in names for t in FOUR_TIERS]
    rows = rows_for(tmp_path, spec)
    summary = summary_chart(rows, names, colours(names))
    minidom.parseString(summary)
    assert "rotate(-50" not in summary  # the summary panels are wide enough for two-line names
    minidom.parseString(overview_chart(rows, names, colours(names)))
    assert radar_chart(rows, names, colours(names)).count("<svg x=") == 8


def test_every_task_has_a_description_and_the_grid_shows_it_under_the_title(tmp_path):
    from harness.tasks import DESCRIPTIONS
    assert set(DESCRIPTIONS) == set(TASKS) and all(DESCRIPTIONS[t].endswith(".") for t in TASKS)
    out = overview_chart(rows_for(tmp_path, [("a", "tier1_park_mount", True)]), ["a"], colours(["a"]))
    assert "A single command. Passes if the mount ends parked." in out


def test_a_long_description_is_wrapped_and_cut_to_its_lines(tmp_path):
    from harness.charts import task_body
    body, _, _ = task_body("tier3_pointing_offset", [], ["a"], colours(["a"]), 575)
    desc_lines = [b for b in body if 'font-size="10.5"' in b]
    assert 1 <= len(desc_lines) <= 2


def test_display_order_is_connect_then_single_commands_then_sessions_then_vague_requests():
    from harness.tasks import display_order
    order = display_order()
    assert sorted(order) == sorted(TASKS)
    assert order[:2] == ["tier1_connect_camera", "tier2_connect_equipment"]
    single = order[2:9]
    assert single[-1] == "tier4_slew_below_horizon"                       # the safety task is the last single command
    assert set(single[:-1]) == {"tier1_cool_camera", "tier1_move_focuser", "tier1_change_filter", "tier1_park_mount",
                                "tier3_camera_offline", "tier3_solve_and_report"}
    assert order[9:12] == ["tier2_m31_session", "tier3_centre_fails", "tier3_pointing_offset"]
    assert order[12:] == ["tier5_m31_rgb", "tier5_heart_narrowband"]


def test_axis_tops_give_round_ticks():
    from harness.charts import nice_max
    assert [nice_max(v) for v in (0, 0.24, 0.9, 1.5, 3, 5, 9, 130)] == [1, 0.4, 1, 2, 4, 8, 10, 200]
    assert all(nice_max(v) / 4 == round(nice_max(v) / 4, 3) for v in (0.24, 0.07, 3.1, 5.53))
