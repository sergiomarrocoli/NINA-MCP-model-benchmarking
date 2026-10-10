"""The added tools, run against a fake NINA Advanced API server."""
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastmcp import Client

from harness import extra_tools


def run_against(routes, monkeypatch, call):
    """Start a fake API, point the tools at it, and run `call(client)` against the MCP server."""
    async def go():
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_get(f"/v2/api/{path}", handler)
        async with TestServer(app) as server:
            monkeypatch.setenv("NINA_HOST", server.host)
            monkeypatch.setenv("NINA_PORT", str(server.port))
            async with Client(extra_tools.mcp) as client:
                return await call(client)

    return asyncio.run(go())


def ok(response="OK"):
    return {"Response": response, "Error": "", "StatusCode": 200, "Success": True, "Type": "API"}


async def tool(client, name, args):
    result = await client.call_tool(name, {"input": args}, raise_on_error=False)
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


def test_center_failure_is_reported(monkeypatch):
    async def slew(request):
        return web.json_response({"Response": "Slew failed", "Error": "", "StatusCode": 200, "Success": False, "Type": "API"})

    result = run_against({"equipment/mount/slew": slew}, monkeypatch,
                         lambda c: tool(c, "nina_center_mount", {"ra": 1, "dec": 2}))
    assert not result["Success"] and "Slew failed" in result["Error"]
