"""Put the simulated equipment in a known state before each run.

Talks to the NINA Advanced API directly rather than through the model-facing MCP tools, so a
reset does not depend on the tool layer under test. The simulators keep their own state
(reconnecting does not reset them), so every device is driven back to the baseline below.

Simulator quirks this works around:
- Camera `TargetTemp` stays stale and `AtTargetTemp` is always true; `Temperature` is the
  reliable signal. Warming returns it to ambient (20 °C).
- The focuser moves about 80 steps/s, so waiting for it is the slow part of a reset.
- The image history cannot be cleared, so the frame count is recorded as a baseline instead.
"""
import os
import time

import requests

CAMERA_TEMP = 20.0       # ambient, reached by warming
MOUNT_RA_DEG = 0.0       # RA 0h, Dec +80°: circumpolar at the simulated site (lat 53°N),
MOUNT_DEC = 80.0         # always above the horizon and away from any task target
FOCUSER_POSITION = 1     # position the simulator boots at
# The simulated mount lands a little off its target (about 0.4° in RA, 0.2° in Dec observed).
MOUNT_RA_TOL_HOURS = 0.05
MOUNT_DEC_TOL_DEG = 0.5
TIMEOUT_S = 180


class NinaApi:
    def __init__(self, host: str | None = None, port: str | None = None):
        host = host or os.environ.get("NINA_HOST", "192.168.1.211")
        port = port or os.environ.get("NINA_PORT", "1888")
        self.base = f"http://{host}:{port}/v2/api"

    def get(self, path: str, **params):
        r = requests.get(f"{self.base}/{path}", params=params or None, timeout=60)
        r.raise_for_status()
        body = r.json()
        if not body.get("Success", False):
            raise RuntimeError(f"{path}: {body.get('Error') or body}")
        return body["Response"]

    def info(self, device: str) -> dict:
        return self.get(f"equipment/{device}/info")


def wait_for(what: str, check, timeout: float = TIMEOUT_S, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(interval)
    raise TimeoutError(f"reset: timed out waiting for {what}")


def reset(api: NinaApi | None = None) -> dict:
    """Reset camera, mount and focuser, verify the result and return the baseline state."""
    api = api or NinaApi()

    for device in ("camera", "mount", "focuser"):
        if not api.info(device)["Connected"]:
            api.get(f"equipment/{device}/connect")
            wait_for(f"{device} to connect", lambda d=device: api.info(d)["Connected"])

    # Camera: stop any exposure and cooling, then warm back to ambient.
    api.get("equipment/camera/abort-exposure")
    api.get("equipment/camera/cool", cancel="true")
    api.get("equipment/camera/warm", minutes=0)
    wait_for("camera to reach ambient", lambda: abs(api.info("camera")["Temperature"] - CAMERA_TEMP) <= 1)

    # Mount: stop motion, unpark and slew to the baseline position.
    api.get("equipment/mount/slew/stop")
    api.get("equipment/mount/unpark")
    api.get("equipment/mount/slew", ra=MOUNT_RA_DEG, dec=MOUNT_DEC, waitForResult="true")
    wait_for("mount to stop slewing", lambda: not api.info("mount")["Slewing"])

    # Focuser: move to the baseline and wait for it to stop.
    api.get("equipment/focuser/move", position=FOCUSER_POSITION)
    wait_for(
        "focuser to settle",
        lambda: not api.info("focuser")["IsMoving"] and api.info("focuser")["Position"] == FOCUSER_POSITION,
    )

    return verify(api)


def verify(api: NinaApi) -> dict:
    """Check the baseline holds and return a snapshot (including the frame count to score against)."""
    camera, mount, focuser = api.info("camera"), api.info("mount"), api.info("focuser")
    problems = []
    if not (camera["Connected"] and mount["Connected"] and focuser["Connected"]):
        problems.append("a device is not connected")
    if abs(camera["Temperature"] - CAMERA_TEMP) > 1:
        problems.append(f"camera temperature {camera['Temperature']}")
    ra_error = abs(mount["RightAscension"] - MOUNT_RA_DEG / 15)
    if min(ra_error, 24 - ra_error) > MOUNT_RA_TOL_HOURS or abs(mount["Declination"] - MOUNT_DEC) > MOUNT_DEC_TOL_DEG:
        problems.append(f"mount at RA {mount['RightAscension']} Dec {mount['Declination']}")
    if mount["AtPark"] or mount["Slewing"]:
        problems.append("mount parked or slewing")
    if focuser["Position"] != FOCUSER_POSITION or focuser["IsMoving"]:
        problems.append(f"focuser at {focuser['Position']}")
    if problems:
        raise RuntimeError("reset failed verification: " + "; ".join(problems))

    return {
        "camera_temperature": camera["Temperature"],
        "mount_ra_hours": mount["RightAscension"],
        "mount_dec_deg": mount["Declination"],
        "mount_tracking": mount["TrackingEnabled"],
        "focuser_position": focuser["Position"],
        "image_count": api.get("image-history", count="true"),
    }


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    start = time.monotonic()
    print(reset())
    print(f"reset took {time.monotonic() - start:.1f}s")
