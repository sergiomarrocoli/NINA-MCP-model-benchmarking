"""MCP server = nina-advanced-mcp plus the tools it lacks.

The upstream server has no autofocus and no centring tool, although the Advanced API plugin offers
both (`/equipment/focuser/auto-focus`, and `center=true` on `/equipment/mount/slew`). This adds
them to the upstream server object, written in the same style as its other tools (arguments wrapped
in `input`). Both wait for the operation to finish, with their own long timeout: the upstream
client gives up after 10 s, which a real autofocus or centre never meets.

Start it with: python -c "from harness.extra_tools import mcp; mcp.run()"
"""
import asyncio
import os
import time
from typing import Any

import aiohttp
from nina_advanced_mcp import create_error_response, mcp
from pydantic import BaseModel, Field

AUTOFOCUS_TIMEOUT_S = 300
CENTER_TIMEOUT_S = 300
POLL_S = 2


def _base() -> str:
    return f"http://{os.environ.get('NINA_HOST', 'localhost')}:{os.environ.get('NINA_PORT', '1888')}/v2/api"


async def _get(path: str, params: dict | None = None, timeout: float = 30) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(f"{_base()}/{path}", params=params) as response:
            return await response.json()


class AutofocusInput(BaseModel):
    cancel: bool = Field(default=False, description="Cancel a running autofocus instead of starting one")
    wait_for_completion: bool = Field(default=True, description="Wait for the autofocus to finish and return its result")


class CenterMountInput(BaseModel):
    ra: float = Field(description="Right Ascension of the target in hours")
    dec: float = Field(description="Declination of the target in degrees")
    wait_for_completion: bool = Field(default=True, description="Wait for the slew and centring to finish")


async def _last_autofocus_timestamp() -> str | None:
    try:
        body = await _get("equipment/focuser/last-af")
    except Exception:
        return None
    response = body.get("Response")
    return response.get("Timestamp") if isinstance(response, dict) else None


@mcp.tool()
async def nina_autofocus(input: AutofocusInput) -> dict[str, Any]:
    """Run NINA's autofocus routine on the connected focuser and camera, or cancel a running one.

    Args:
        input: AutofocusInput containing:
            cancel: Optional, cancel a running autofocus instead of starting one
            wait_for_completion: Optional, wait until the autofocus has finished (default true)

    Returns:
        Dict containing the success status, a message and, once finished, the calculated focus position.
    """
    try:
        if input.cancel:
            result = await _get("equipment/focuser/auto-focus", {"cancel": "true"})
            return {"Success": bool(result.get("Success")), "Message": result.get("Response") or result.get("Error"),
                    "Details": result, "Type": "NINA_API"}

        before = await _last_autofocus_timestamp()
        started = await _get("equipment/focuser/auto-focus")
        if not started.get("Success"):
            return create_error_response("NINAFocuserError", started.get("Error") or "Autofocus did not start", started)
        if not input.wait_for_completion:
            return {"Success": True, "Message": "Autofocus started", "Details": started, "Type": "NINA_API"}

        deadline = time.monotonic() + AUTOFOCUS_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_S)
            now = await _last_autofocus_timestamp()
            if now is not None and now != before:
                last = (await _get("equipment/focuser/last-af")).get("Response", {})
                point = (last.get("CalculatedFocusPoint") or {}).get("Position")
                return {"Success": True, "Message": f"Autofocus finished; calculated focus position {point}",
                        "Details": {"CalculatedFocusPosition": point, "Timestamp": now, "Temperature": last.get("Temperature")},
                        "Type": "NINA_API"}
        return create_error_response("NINAFocuserError", f"No autofocus result after {AUTOFOCUS_TIMEOUT_S} s; it may have failed", {})
    except Exception as e:
        return create_error_response("NINAFocuserError", str(e), {})


@mcp.tool()
async def nina_center_mount(input: CenterMountInput) -> dict[str, Any]:
    """Slew the mount to coordinates and centre on them using NINA's plate solver.

    Unlike nina_slew_mount, this plate-solves after the slew and corrects the pointing until the
    target is centred.

    Args:
        input: CenterMountInput containing:
            ra: Right Ascension of the target in hours
            dec: Declination of the target in degrees
            wait_for_completion: Optional, wait for the slew and centring to finish (default true)

    Returns:
        Dict containing the success status and a message.
    """
    try:
        params = {"ra": input.ra * 15, "dec": input.dec, "center": "true",
                  "waitForResult": str(input.wait_for_completion).lower()}
        result = await _get("equipment/mount/slew", params, timeout=CENTER_TIMEOUT_S)
        if not result.get("Success"):
            return create_error_response("NINAMountError", result.get("Error") or str(result.get("Response")), result)
        return {"Success": True, "Message": f"Mount slew and centre: {result.get('Response')}", "Details": result, "Type": "NINA_API"}
    except Exception as e:
        return create_error_response("NINAMountError", str(e), {})


if __name__ == "__main__":
    mcp.run()
