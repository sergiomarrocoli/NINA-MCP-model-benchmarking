"""The added tools, run against a fake NINA Advanced API server."""
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastmcp import Client

import nina_advanced_mcp
from harness import extra_tools


def run_against(routes, monkeypatch, call):
    """Start a fake API, point the tools at it, and run `call(client)` against the MCP server."""
    async def go():
        app = web.Application()
        async def api_root(request):  # the server's own connection check
            return web.json_response(ok())

        app.router.add_get("/v2/api", api_root)
        for path, handler in routes.items():
            app.router.add_get(f"/v2/api/{path}", handler)
        async with TestServer(app) as server:
            monkeypatch.setenv("NINA_HOST", server.host)
            monkeypatch.setenv("NINA_PORT", str(server.port))
            monkeypatch.setattr(nina_advanced_mcp, "nina_client", None)  # the server caches its client, host and port included
            async with Client(extra_tools.mcp) as client:
                return await call(client)

    return asyncio.run(go())


def ok(response="OK"):
    return {"Response": response, "Error": "", "StatusCode": 200, "Success": True, "Type": "API"}


async def tool(client, name, args):
    result = await client.call_tool(name, args, raise_on_error=False)
    return json.loads(result.content[0].text)


def test_both_tools_are_registered(monkeypatch):
    names = run_against({}, monkeypatch, lambda c: c.list_tools())
    assert {"nina_autofocus", "nina_center_mount"} <= {t.name for t in names}
    assert "nina_slew_mount" in {t.name for t in names}  # upstream tools are still there


def test_autofocus_waits_for_a_new_result(monkeypatch):
    monkeypatch.setattr(extra_tools, "POLL_S", 0.05)
    state = {"timestamp": "old", "polls": 0, "started": 0}

    async def last_af(request):
        state["polls"] += 1
        if state["started"] and state["polls"] > 3:
            state["timestamp"] = "new"  # the autofocus finishes a few polls after it starts
        return web.json_response(ok({"Timestamp": state["timestamp"], "Temperature": 7.5,
                                     "CalculatedFocusPoint": {"Position": 4321.0, "Value": 2.1, "Error": 0}}))

    async def auto_focus(request):
        state["started"] += 1
        return web.json_response(ok("Autofocus started"))

    result = run_against({"equipment/focuser/last-af": last_af, "equipment/focuser/auto-focus": auto_focus},
                         monkeypatch, lambda c: tool(c, "nina_autofocus", {}))
    assert result["Success"] and "4321" in result["Message"]
    assert result["Details"]["Timestamp"] == "new"


def test_autofocus_that_never_finishes_is_an_error(monkeypatch):
    monkeypatch.setattr(extra_tools, "POLL_S", 0.05)
    monkeypatch.setattr(extra_tools, "AUTOFOCUS_TIMEOUT_S", 0.3)

    async def last_af(request):
        return web.json_response(ok({"Timestamp": "same"}))

    async def auto_focus(request):
        return web.json_response(ok("Autofocus started"))

    result = run_against({"equipment/focuser/last-af": last_af, "equipment/focuser/auto-focus": auto_focus},
                         monkeypatch, lambda c: tool(c, "nina_autofocus", {}))
    assert not result["Success"] and "No autofocus result" in result["Error"]


def test_autofocus_without_a_focuser_is_an_error(monkeypatch):
    async def last_af(request):
        return web.json_response(ok({}))

    async def auto_focus(request):
        return web.json_response({"Response": "", "Error": "Focuser not connected", "StatusCode": 409,
                                  "Success": False, "Type": "API"})

    result = run_against({"equipment/focuser/last-af": last_af, "equipment/focuser/auto-focus": auto_focus},
                         monkeypatch, lambda c: tool(c, "nina_autofocus", {}))
    assert not result["Success"] and result["Error"] == "Focuser not connected"


def test_autofocus_without_waiting_returns_at_once(monkeypatch):
    async def last_af(request):
        return web.json_response(ok({"Timestamp": "t"}))

    async def auto_focus(request):
        return web.json_response(ok("Autofocus started"))

    result = run_against({"equipment/focuser/last-af": last_af, "equipment/focuser/auto-focus": auto_focus},
                         monkeypatch, lambda c: tool(c, "nina_autofocus", {"wait_for_completion": False}))
    assert result["Success"] and result["Message"] == "Autofocus started"


def test_cancel_sends_cancel_true(monkeypatch):
    seen = {}

    async def auto_focus(request):
        seen.update(request.query)
        return web.json_response(ok("Autofocus canceled"))

    result = run_against({"equipment/focuser/auto-focus": auto_focus}, monkeypatch,
                         lambda c: tool(c, "nina_autofocus", {"cancel": True}))
    assert seen == {"cancel": "true"} and result["Success"]


def test_center_converts_ra_hours_to_degrees_and_asks_for_centring(monkeypatch):
    seen = {}

    async def slew(request):
        seen.update(request.query)
        return web.json_response(ok("Slew finished"))

    result = run_against({"equipment/mount/slew": slew}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra": 0.712, "dec": 41.27}))
    assert float(seen["ra"]) == pytest.approx(10.68) and float(seen["dec"]) == pytest.approx(41.27)
    assert seen["center"] == "true" and seen["waitForResult"] == "true"
    assert result["Success"] and "Slew finished" in result["Message"]


FAILED = {"Response": "Slew failed", "Error": "", "StatusCode": 200, "Success": False, "Type": "API"}


def mount_info(ra_hours, dec, slewing=False):
    async def handler(request):
        return web.json_response(ok({"RightAscension": ra_hours, "Declination": dec, "Slewing": slewing}))

    return handler


def test_center_failure_is_reported_when_the_mount_is_elsewhere(monkeypatch):
    async def slew(request):
        return web.json_response(FAILED)

    result = run_against({"equipment/mount/slew": slew, "equipment/mount/info": mount_info(5.0, -5.0)}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra": 0.712, "dec": 41.27}))
    assert not result["Success"] and "Slew failed" in result["Error"]


def test_center_that_the_plugin_calls_failed_but_left_the_mount_on_target_is_a_success(monkeypatch):
    # NINA's own log showed the solve succeeding with zero offset; M31's JNOW position in 2026 is
    # about RA 0.737 h, Dec +41.42. The plugin still said "Slew failed".
    async def slew(request):
        return web.json_response(FAILED)

    from datetime import datetime, timezone

    from harness.coords import j2000_to_jnow

    ra, dec = j2000_to_jnow(0.712 * 15, 41.27)
    result = run_against({"equipment/mount/slew": slew, "equipment/mount/info": mount_info(ra / 15, dec)}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra": 0.712, "dec": 41.27}))
    assert result["Success"] and "centred" in result["Message"]


def test_center_is_not_reported_as_success_while_the_mount_is_still_slewing(monkeypatch):
    async def slew(request):
        return web.json_response(FAILED)

    from harness.coords import j2000_to_jnow

    ra, dec = j2000_to_jnow(0.712 * 15, 41.27)
    result = run_against({"equipment/mount/slew": slew, "equipment/mount/info": mount_info(ra / 15, dec, slewing=True)},
                         monkeypatch, lambda c: tool(c, "nina_center_mount", {"ra": 0.712, "dec": 41.27}))
    assert not result["Success"]


def test_a_timeout_gets_a_readable_error(monkeypatch):
    import asyncio as aio

    async def slew(request):
        await aio.sleep(5)
        return web.json_response(ok())

    monkeypatch.setattr(extra_tools, "CENTER_TIMEOUT_S", 0.2)
    result = run_against({"equipment/mount/slew": slew}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra": 1, "dec": 2}))
    assert not result["Success"] and "Timed out" in result["Error"]


@pytest.mark.parametrize("ra, dec", [(42.44, 41.27), (-1, 41.27), (24, 41.27), (0.7, 91)])
def test_centre_rejects_coordinates_out_of_range_instead_of_wrapping_them(monkeypatch, ra, dec):
    called = []

    async def slew(request):
        called.append(1)
        return web.json_response(ok())

    result = run_against({"equipment/mount/slew": slew}, monkeypatch, lambda c: tool(c, "nina_center_mount", {"ra": ra, "dec": dec}))
    # "must be between" from the old checks, "out of range" or "must be" from the fork's clearer ones
    assert not result["Success"] and any(w in result["Error"] for w in ("must be between", "out of range", "must be")) and not called


def test_wait_is_capped_and_says_what_was_asked_and_what_was_waited(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(extra_tools, "_sleep", fake_sleep)
    long = run_against({}, monkeypatch, lambda c: tool(c, "nina_wait", {"seconds": 3600}))
    short = run_against({}, monkeypatch, lambda c: tool(c, "nina_wait", {"seconds": 12.5}))
    assert slept == [300, 12.5]
    assert long["Success"] and long["Details"] == {"requested_seconds": 3600, "waited_seconds": 300}
    assert "you asked for 3600" in long["Message"] and "300 seconds" in long["Message"]
    assert short["Details"] == {"requested_seconds": 12.5, "waited_seconds": 12.5} and "asked" not in short["Message"]


def test_wait_rejects_a_negative_duration(monkeypatch):
    result = run_against({}, monkeypatch, lambda c: tool(c, "nina_wait", {"seconds": -1}))
    assert not result["Success"] and "negative" in result["Error"]


def test_the_server_has_one_nina_wait_and_it_is_ours(monkeypatch):
    names = [t.name for t in run_against({}, monkeypatch, lambda c: c.list_tools())]
    assert names.count("nina_wait") == 1
    desc = next(t.description for t in run_against({}, monkeypatch, lambda c: c.list_tools()) if t.name == "nina_wait")
    assert "at most 300" in desc


# --- nina_capture_image (the fork's, installed from its benchmark branch): waits, and only reports a frame that was really saved ---


@pytest.fixture
def quick_capture(monkeypatch):
    monkeypatch.setattr(nina_advanced_mcp, "CAPTURE_RETRY_PAUSE_S", 0)
    monkeypatch.setattr(nina_advanced_mcp, "CAPTURE_SAVE_WAIT_S", 0.2)


class FakeCamera:
    """Image history plus a capture endpoint whose behaviour per call is given by `script`."""

    def __init__(self, script=("saved",)):
        self.frames, self.calls, self.script = 0, 0, list(script)

    async def history(self, request):
        return web.json_response(ok(self.frames))

    async def capture(self, request):
        action = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        self.last_query = dict(request.query)
        if action == "saved":
            self.frames += 1
            return web.json_response(ok(""))
        if action == "unknown":      # the plugin's own wait failing, saving nothing
            return web.json_response({"Response": "", "Error": "Unknown error", "StatusCode": 500, "Success": False})
        if action == "claims":       # says success but saves nothing
            return web.json_response(ok(""))

    def routes(self):
        return {"image-history": self.history, "equipment/camera/capture": self.capture}


def capture(camera, monkeypatch, **args):
    return run_against(camera.routes(), monkeypatch, lambda c: tool(c, "nina_capture_image", args))


def test_capture_waits_for_the_saved_frame(monkeypatch, quick_capture):
    camera = FakeCamera()
    result = capture(camera, monkeypatch, duration=5)
    assert result["Success"] and result["Message"] == "Image captured successfully"
    assert camera.frames == 1 and camera.calls == 1
    assert camera.last_query["waitForResult"] == "true" and camera.last_query["duration"] == "5.0"


def test_capture_tries_again_when_the_plugin_saves_nothing(monkeypatch, quick_capture):
    camera = FakeCamera(["unknown", "saved"])
    result = capture(camera, monkeypatch, duration=5)
    assert result["Success"] and camera.calls == 2 and camera.frames == 1


def test_capture_does_not_trust_a_success_without_a_new_frame(monkeypatch, quick_capture):
    camera = FakeCamera(["claims"])
    result = capture(camera, monkeypatch, duration=5)
    assert not result["Success"] and "No image was saved after 3 attempts" in result["Error"]
    assert camera.calls == 3 and camera.frames == 0


def test_capture_reports_the_failure_when_every_attempt_fails(monkeypatch, quick_capture):
    camera = FakeCamera(["unknown"])
    result = capture(camera, monkeypatch, duration=5)
    assert not result["Success"] and "no response from device" in result["Error"]  # the server's wording for "Unknown error"


def test_five_captures_in_a_row_give_five_frames_even_when_some_fail(monkeypatch, quick_capture):
    # The 4 frames problem: some captures fail at random; each successful call must still mean one frame.
    camera = FakeCamera(["saved", "unknown", "saved", "saved", "unknown", "saved", "saved"])

    async def five(client):
        return [await tool(client, "nina_capture_image", {"duration": 5}) for _ in range(5)]

    results = run_against(camera.routes(), monkeypatch, five)
    assert all(r["Success"] for r in results) and camera.frames == 5


SITE = {"SiteLatitude": 53, "SiderealTime": 22.1, "RightAscension": 1.4, "Declination": 83.1, "Slewing": False}


def centre_below_horizon(monkeypatch, args, with_check=True):
    slewed = []

    async def slew(request):
        slewed.append(dict(request.query))
        return web.json_response(ok("Slew finished"))

    async def info(request):
        return web.json_response(ok(SITE))

    if with_check:  # the installed server may not have the check; fake one that refuses everything south of -30
        monkeypatch.setattr(nina_advanced_mcp, "below_horizon_message",
                            lambda ra, dec, info: "The target is below the horizon." if dec < -30 else None, raising=False)
    else:
        monkeypatch.delattr(nina_advanced_mcp, "below_horizon_message", raising=False)
    result = run_against({"equipment/mount/slew": slew, "equipment/mount/info": info}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", args))
    return result, slewed


def test_centre_refuses_a_target_below_the_horizon_and_never_slews(monkeypatch):
    result, slewed = centre_below_horizon(monkeypatch, {"ra": 14.66, "dec": -60.8})
    assert not result["Success"] and "Not slewing" in result["Error"] and slewed == []


def test_centre_has_no_override_argument():
    assert "allow_below_horizon" not in extra_tools.CenterMountInput.model_fields


def test_centre_without_the_servers_horizon_check_goes_ahead(monkeypatch):
    result, slewed = centre_below_horizon(monkeypatch, {"ra": 14.66, "dec": -60.8}, with_check=False)
    assert result["Success"] and len(slewed) == 1


def test_centre_takes_ra_in_degrees(monkeypatch):
    seen = {}

    async def slew(request):
        seen.update(request.query)
        return web.json_response(ok("Slew finished"))

    result = run_against({"equipment/mount/slew": slew}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra_degrees": 10.68, "dec": 41.27}))
    assert float(seen["ra"]) == pytest.approx(10.68) and result["Success"]


def test_centre_needs_some_ra(monkeypatch):
    result = run_against({}, monkeypatch, lambda c: tool(c, "nina_center_mount", {"dec": 41.27}))
    assert not result["Success"] and "Right Ascension" in result["Error"]


def test_centre_with_ra_in_degrees_given_as_hours_is_refused(monkeypatch):
    result = run_against({}, monkeypatch, lambda c: tool(c, "nina_center_mount", {"ra": 42.44, "dec": 41.27}))
    assert not result["Success"] and ("Right Ascension" in result["Error"] or "HOURS" in result["Error"])
