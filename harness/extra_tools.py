"""MCP server = nina-advanced-mcp plus the tools it lacks.

The upstream server has no autofocus and no centring tool, although the Advanced API plugin offers
both (`/equipment/focuser/auto-focus`, and `center=true` on `/equipment/mount/slew`). This adds
them to the upstream server object, written in the same style as its other tools (a pydantic model that the
`tool()` decorator publishes as flat arguments). Both wait for the operation to finish, with their own long
timeout: the upstream client gives up after 10 s, which a real autofocus or centre never meets.

Start it with: python -c "from harness.extra_tools import mcp; mcp.run()"
"""
import asyncio
import os
import time
from typing import Any

import aiohttp
import nina_advanced_mcp
from nina_advanced_mcp import create_error_response, mcp, tool
from pydantic import BaseModel, Field

from harness.coords import j2000_to_jnow, separation_deg

AUTOFOCUS_TIMEOUT_S = 300
CENTER_TIMEOUT_S = 300
WAIT_MAX_S = 300  # the longest wait any model has made and finished (qwen, tier 5); see nina_wait
POLL_S = 2
CENTERED_WITHIN_DEG = 0.05  # 3 arc-minutes


def _base() -> str:
    return f"http://{os.environ.get('NINA_HOST', 'localhost')}:{os.environ.get('NINA_PORT', '1888')}/v2/api"


def _describe(e: Exception) -> str:
    # A bare TimeoutError has an empty message, which tells a model nothing.
    if isinstance(e, TimeoutError):
        return "Timed out waiting for NINA to finish; the operation may still be running"
    return str(e) or type(e).__name__


async def _get(path: str, params: dict | None = None, timeout: float = 30) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(f"{_base()}/{path}", params=params) as response:
            return await response.json()


async def _degrees_from_target(ra_deg: float, dec_deg: float) -> float | None:
    """How far the mount is from a J2000 target, or None if it is moving or cannot be read."""
    info = (await _get("equipment/mount/info")).get("Response") or {}
    if info.get("Slewing") or info.get("RightAscension") is None:
        return None
    target_ra, target_dec = j2000_to_jnow(ra_deg, dec_deg)  # mount info is in JNOW
    return separation_deg(info["RightAscension"] * 15, info["Declination"], target_ra, target_dec)


class AutofocusInput(BaseModel):
    cancel: bool = Field(default=False, description="Cancel a running autofocus instead of starting one")
    wait_for_completion: bool = Field(default=True, description="Wait for the autofocus to finish and return its result")


class CenterMountInput(BaseModel):
    ra: float = Field(description="Right Ascension of the target in hours")
    dec: float = Field(description="Declination of the target in degrees")
    wait_for_completion: bool = Field(default=True, description="Wait for the slew and centring to finish")
    allow_below_horizon: bool = Field(default=False, description="Slew even if the target is below the horizon. Off by default: a slew to a target below the horizon is refused, with the reason.")


async def _last_autofocus_timestamp() -> str | None:
    try:
        body = await _get("equipment/focuser/last-af")
    except Exception:
        return None
    response = body.get("Response")
    return response.get("Timestamp") if isinstance(response, dict) else None


@tool()
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
        return create_error_response("NINAFocuserError", _describe(e), {})


@tool()
async def nina_center_mount(input: CenterMountInput) -> dict[str, Any]:
    """Slew the mount to coordinates and centre on them using NINA's plate solver.

    Unlike nina_slew_mount, this plate-solves after the slew and corrects the pointing until the
    target is centred.

    Args:
        input: CenterMountInput containing:
            ra: Right Ascension of the target in hours
            dec: Declination of the target in degrees
            wait_for_completion: Optional, wait for the slew and centring to finish (default true)
            allow_below_horizon: Optional, centre even if the target is below the horizon (default false: refused)

    Returns:
        Dict containing the success status and a message.
    """
    # Same checks as nina_slew_mount. Without them 42.44 "hours" wraps to 18.4 h and is reported as centred.
    if not 0 <= input.ra < 24:
        return create_error_response("NINAMountError", "Right Ascension must be between 0 and 24 hours", {"StatusCode": 400})
    if not -90 <= input.dec <= 90:
        return create_error_response("NINAMountError", "Declination must be between -90 and +90 degrees", {"StatusCode": 400})
    try:
        # The same refusal as nina_slew_mount, when the installed server has it (the fork's horizon check).
        # If the mount's info cannot be read the centre goes ahead, as the slew does.
        below_horizon_message = getattr(nina_advanced_mcp, "below_horizon_message", None)
        if below_horizon_message and not input.allow_below_horizon:
            try:
                info = (await _get("equipment/mount/info")).get("Response") or {}
            except Exception:
                info = {}
            reason = below_horizon_message(input.ra, input.dec, info)
            if reason:
                return create_error_response("NINAMountError", f"Not slewing: {reason} Set allow_below_horizon to override.", {"StatusCode": 400})
        params = {"ra": input.ra * 15, "dec": input.dec, "center": "true",
                  "waitForResult": str(input.wait_for_completion).lower()}
        result = await _get("equipment/mount/slew", params, timeout=CENTER_TIMEOUT_S)
        if result.get("Success"):
            return {"Success": True, "Message": f"Mount slew and centre: {result.get('Response')}", "Details": result, "Type": "NINA_API"}
        if input.wait_for_completion:
            # The plugin reports "Slew failed" for a centre that worked: it checks a status NINA only
            # sets when it runs the instruction itself. So judge by where the mount ended up.
            off = await _degrees_from_target(input.ra * 15, input.dec)
            if off is not None and off <= CENTERED_WITHIN_DEG:
                return {"Success": True,
                        "Message": f"Mount is centred on the target ({off:.3f}° away). The plugin reported '{result.get('Response')}' but the mount position confirms the centre.",
                        "Details": result, "Type": "NINA_API"}
        return create_error_response("NINAMountError", result.get("Error") or str(result.get("Response")), result)
    except Exception as e:
        return create_error_response("NINAMountError", _describe(e), {})


_sleep = asyncio.sleep  # a name the tests can replace


@tool()
async def nina_wait(seconds: float) -> dict[str, Any]:
    """Wait for a specified duration in seconds, at most 300.

    Replaces the upstream tool, which waits for as long as it is asked: one model sat in it for over 15 minutes and
    held up everything behind it. A longer request is shortened, and the reply says so. What was asked for and what
    was waited both come back in Details, so the run log has them.

    Args:
        seconds: Duration to wait in seconds (can be fractional), up to 300

    Returns:
        Dict containing the success status, a message, and the requested and waited seconds.
    """
    if seconds < 0:
        return create_error_response("InvalidParameter", "Wait duration cannot be negative", {"StatusCode": 400})
    waited = min(seconds, WAIT_MAX_S)
    await _sleep(waited)
    message = f"Waited for {waited:g} seconds"
    if waited < seconds:
        message += f" (you asked for {seconds:g}; the longest wait is {WAIT_MAX_S} seconds)"
    return {"Success": True, "Message": message, "Details": {"requested_seconds": seconds, "waited_seconds": waited}, "Type": "NINA_API"}


if __name__ == "__main__":
    mcp.run()
