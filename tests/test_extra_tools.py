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
