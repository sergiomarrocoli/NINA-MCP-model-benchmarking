"""MCP server = nina-advanced-mcp plus the tools it lacks.

The upstream server has no autofocus and no centring tool, although the Advanced API plugin offers
both (`/equipment/focuser/auto-focus`, and `center=true` on `/equipment/mount/slew`). This adds
them to the upstream server object, written in the same style as its other tools (arguments wrapped
in `input`). Both wait for the operation to finish, with their own long timeout: the upstream
client gives up after 10 s, which a real autofocus or centre never meets.

It also replaces `nina_capture_image`. Upstream, with `download=False`, starts the exposure, returns
at once with "Image captured successfully" and does not check that an image was saved; a second call
made while the camera is still busy fails at random ("Camera currently exposing") and the plugin's
own wait sometimes fails with "Unknown error" and saves nothing. The replacement takes the same
arguments, waits, and only reports success once the frame count in NINA's image history has gone up.

Start it with: python -c "from harness.extra_tools import mcp; mcp.run()"
"""
import asyncio
import os
import time
from typing import Any

import aiohttp
from nina_advanced_mcp import CameraCaptureInput, create_error_response, mcp
from nina_advanced_mcp import nina_capture_image as _upstream_capture_image
from pydantic import BaseModel, Field

from harness.coords import j2000_to_jnow, separation_deg

AUTOFOCUS_TIMEOUT_S = 300
CENTER_TIMEOUT_S = 300
POLL_S = 2
CENTERED_WITHIN_DEG = 0.05  # 3 arc-minutes
CAPTURE_ATTEMPTS = 3        # a capture that saves nothing is tried again this many times in all
CAPTURE_RETRY_PAUSE_S = 2
CAPTURE_SAVE_WAIT_S = 6     # after NINA says it is done, how long to wait for the frame to be listed


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
        return create_error_response("NINAFocuserError", _describe(e), {})


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


if __name__ == "__main__":
    mcp.run()


async def _image_count() -> int | None:
    try:
        count = (await _get("image-history", {"count": "true"})).get("Response")
    except Exception:
        return None
    return count if isinstance(count, int) else None


async def _wait_for_new_frame(before: int) -> bool:
    deadline = time.monotonic() + CAPTURE_SAVE_WAIT_S
    while True:
        count = await _image_count()
        if count is not None and count > before:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_S / 4)


@mcp.tool()
async def nina_capture_image(input: CameraCaptureInput) -> dict[str, Any]:
    """Capture an image with NINA astronomy software and wait until it has been saved.

    With download=False (the default) one image is taken and saved by NINA in full resolution. The call
    returns once the image is saved, so the next capture can be started straight away; a successful
    call means one new image. If the camera is busy or the capture saves nothing it is tried again, and
    an error is returned if it still fails.

    With download=True the image is also downloaded and can be resized and compressed for preview
    (resize, size, quality).

    Args:
        input: CameraCaptureInput containing:
            duration: Optional, exposure time in seconds
            gain: Optional, camera gain
            download: Optional, also download the image (default false)
            resize, size, quality: Optional, preview settings used with download
            solve: Optional, plate solve the image

    Returns:
        Dict containing the success status and a message.
    """
    if input.download:
        return await _upstream_capture_image(input)
    try:
        params = {"save": "true", "omitImage": "true", "waitForResult": "true"}
        if input.duration is not None:
            params["duration"] = str(input.duration)
        if input.gain is not None:
            params["gain"] = str(input.gain)
        if input.solve is not None:
            params["solve"] = str(input.solve).lower()
        timeout = (input.duration or 0) + 60 + (120 if input.solve else 0)

        problem = "no new image appeared in NINA's image history"
        for attempt in range(CAPTURE_ATTEMPTS):
            if attempt:
                await asyncio.sleep(CAPTURE_RETRY_PAUSE_S)
            before = await _image_count()
            result = await _get("equipment/camera/capture", params, timeout=timeout)
            if before is None:  # cannot count frames: trust NINA's own answer
                if result.get("Success"):
                    return {"Success": True, "Message": "Image captured and saved", "Type": "NINA_API"}
            elif await _wait_for_new_frame(before):
                return {"Success": True, "Message": "Image captured and saved", "Type": "NINA_API"}
            problem = result.get("Error") or problem
        return create_error_response(
            "NINACameraError", f"No image was saved after {CAPTURE_ATTEMPTS} attempts: {problem}", {})
    except Exception as e:
        return create_error_response("NINACameraError", _describe(e), {})
