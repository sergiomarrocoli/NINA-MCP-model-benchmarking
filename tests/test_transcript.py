from harness.run import AUTONOMOUS_NOTE, SYSTEM_PROMPT, system_prompt
from harness.tasks import TASKS
from harness.transcript import transcript


def test_only_autonomous_tasks_get_the_judgement_note():
    assert system_prompt(TASKS["tier1_cool_camera"]) == SYSTEM_PROMPT
    for task_id in ("tier5_m31_rgb", "tier5_heart_narrowband"):
        assert system_prompt(TASKS[task_id]) == SYSTEM_PROMPT + AUTONOMOUS_NOTE
    assert "do not ask any" in AUTONOMOUS_NOTE and "list the choices" in AUTONOMOUS_NOTE
    assert not TASKS["tier4_slew_below_horizon"].autonomous  # asking is the right answer there


def test_transcript_shows_calls_what_ended_up_on_disk_and_the_reply():
    events = [
        {"kind": "start", "task": "tier5_m31_rgb", "model": "m", "prompt": "I want RGB frames of M31.", "system_prompt": SYSTEM_PROMPT + AUTONOMOUS_NOTE},
        {"kind": "model", "step": 0, "content": "Slewing first.", "tool_calls": ["nina_slew_mount"]},
        {"kind": "tool_call", "step": 0, "tool": "nina_slew_mount", "args": {"ra": 0.7, "dec": 41.3}, "result": '{"Success":true}', "is_error": False},
        {"kind": "tool_call", "step": 1, "tool": "nina_capture_image", "args": {"duration": 30}, "result": "boom", "is_error": True},
        {"kind": "end", "passed": False, "failures": ["0 blue frames, wanted 1"], "unsafe_calls": [], "final": "Took red and green.",
         "state": {"frames": [{"filter": "Red", "exposure_s": 30}, {"filter": "Green", "exposure_s": 30}], "sky_ra_deg": 10.7, "sky_dec_deg": 41.3}},
    ]
    out = transcript(events)
    assert "nobody can answer questions" in out and "FAILED: 0 blue frames, wanted 1" in out
    assert '[step 0] nina_slew_mount {"ra": 0.7, "dec": 41.3}' in out and "(error)" in out
    assert "2 new frame(s): Red 30 s, Green 30 s" in out and "RA 10.700°" in out and "Took red and green." in out


def test_transcript_of_a_crashed_run_says_so():
    events = [{"kind": "start", "task": "t", "model": "m", "prompt": "p"}]
    assert "no end record" in transcript(events)
