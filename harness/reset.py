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
import json
import os
import time

import requests

from harness import minipc
from harness.coords import j2000_to_jnow, separation_deg

CAMERA_TEMP = 20.0       # ambient, reached by warming
MOUNT_RA_DEG = 20.0      # RA 1h20m, Dec +83° (J2000): circumpolar at the simulated site (lat 53°N), so always above the
MOUNT_DEC = 83.0         # horizon and away from any task target, and a field that plate solves every time (about 130 stars;
                         # the previous baseline, RA 0 Dec +80°, gave about 60 stars and often failed to solve)
# Best focus in Sky Simulator is at 25000. Out of focus, plate solving (and so centring) fails;
# the simulator boots at position 1. The focuser moves about 80 steps/s, so the first reset after
# a Sky Simulator restart takes about 5 minutes; after that resets are quick unless a task moved it far.
FOCUSER_POSITION = 25000
FILTER_BASELINE = 0       # Luminance; the simulated wheel has 7 filters (Luminance, Red, Green, Blue, H-alpha, SII, O3)
# Slack for the mount's reported position (JNOW), compared with the J2000 target converted to JNOW; the slew itself lands within 0.01°.
MOUNT_RA_TOL_HOURS = 0.05
MOUNT_DEC_TOL_DEG = 0.5
TIMEOUT_S = 600
STILL_FOR_S = 5          # how long equipment must stay still before its state counts as final
# Every focuser step makes Sky Simulator render an image (about 80 steps/s), so a long move is
# one long burst of renders. Move in pieces, each waited for.
FOCUSER_CHUNK = 2000
# The mount can report a position it is not at: after a sync with the wrong coordinates the sky stays put and the
# readout shifts, and every later slew lands off target (docs/simulator-notes.md). Only a plate solve shows it.
SOLVE_EXPOSURE_S = 3
SOLVE_TIMEOUT_S = 150
POINTING_TOLERANCE_DEG = 0.05  # the simulated mount lands within 0.01° of a target


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


DEVICES = ("camera", "mount", "focuser", "filterwheel")
# Which NINA device to use for each, as set in .env (NINA_CAMERA_ID, ...). Unset means whichever NINA has
# selected. Use the ASCOM entries (ASCOM.AlpacaDynamic1.Camera, ...Telescope, ...Focuser): NINA's own
# Alpaca client drops the devices after about 4 minutes, and the ASCOM route does not.
DEVICE_ID_ENV = {"camera": "NINA_CAMERA_ID", "mount": "NINA_MOUNT_ID", "focuser": "NINA_FOCUSER_ID",
                 "filterwheel": "NINA_FILTERWHEEL_ID", "guider": "NINA_GUIDER_ID"}
# The guider (PHD2, a separate app on the mini PC) is only used when NINA_GUIDER_ID is set, so a run that
# does not need guiding does not depend on PHD2 being up.
GUIDING_STATES = ("Guiding", "Calibrating")


def wanted_id(device: str) -> str | None:
    return os.environ.get(DEVICE_ID_ENV[device]) or None


def devices() -> tuple[str, ...]:
    """The devices to keep connected: the four simulators, and the guider if one is configured."""
    return DEVICES + (("guider",) if wanted_id("guider") else ())


def connect_command(api: NinaApi, device: str) -> None:
    """Ask NINA to connect `device`, to the configured id if there is one (does not wait)."""
    wanted = wanted_id(device)
    try:
        api.get(f"equipment/{device}/connect", **({"to": wanted} if wanted else {}))
    except RuntimeError as e:
        if device == "guider":
            raise RuntimeError(f"{e} (is PHD2 running, with Tools > Enable Server on?)") from e
        raise


def ensure_connected(api: NinaApi) -> list[str]:
    """Connect each device to the configured id. Returns the devices that had to be (re)connected."""
    reconnected = []
    for device in devices():
        info, wanted = api.info(device), wanted_id(device)
        if info["Connected"] and (wanted is None or info.get("DeviceId") == wanted):
            continue
        if info["Connected"]:  # connected to a different device than the one wanted
            api.get(f"equipment/{device}/disconnect")
            wait_for(f"{device} to disconnect", lambda d=device: not api.info(d)["Connected"])
        connect_command(api, device)
        wait_for(f"{device} to connect", lambda d=device: api.info(d)["Connected"])
        reconnected.append(device)
    return reconnected


def reset_guider(api: NinaApi) -> None:
    """Stop guiding or calibrating and forget the calibration, so a task starts from an unguided, uncalibrated guider."""
    if "guider" not in devices():
        return
    api.get("equipment/guider/stop")
    wait_for("guider to stop", lambda: api.info("guider")["State"] not in GUIDING_STATES)
    api.get("equipment/guider/clear-calibration")


def filter_at(api: NinaApi, filter_id: int) -> bool:
    info = api.info("filterwheel")
    return not info["IsMoving"] and (info.get("SelectedFilter") or {}).get("Id") == filter_id


def change_filter(api: NinaApi, filter_id: int) -> None:
    api.get("equipment/filterwheel/change-filter", filterId=filter_id)
    wait_for(f"filter wheel to reach filter {filter_id}", lambda: filter_at(api, filter_id))


def move_focuser(api: NinaApi, target: int) -> None:
    """Move the focuser to `target` in pieces of FOCUSER_CHUNK steps, waiting for each to finish."""
    position = api.info("focuser")["Position"]
    while position != target:
        goal = position + max(-FOCUSER_CHUNK, min(FOCUSER_CHUNK, target - position))
        api.get("equipment/focuser/move", position=goal)
        wait_for(
            f"focuser to reach {goal}",
            lambda g=goal: not api.info("focuser")["IsMoving"] and api.info("focuser")["Position"] == g,
        )
        position = goal


def wait_for(what: str, check, timeout: float = TIMEOUT_S, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(interval)
    raise TimeoutError(f"reset: timed out waiting for {what}")


def reset(api: NinaApi | None = None, attempts: int = 2) -> dict:
    """Reset camera, mount and focuser, verify the result and return the baseline state.

    The simulated devices occasionally drop their connection mid-reset, so a failed attempt is
    retried (reconnecting first) before giving up. If the mini PC can be reached over SSH
    (MINIPC_SSH_USER, see harness/minipc.py), Sky Simulator is restarted and the reset tried once more.
    """
    api = api or NinaApi()
    for attempt in range(1, attempts + 1):
        try:
            return _reset_once(api)
        except (RuntimeError, TimeoutError, requests.RequestException) as e:
            if attempt < attempts:
                print(f"reset attempt {attempt} failed ({e}); retrying")
                continue
            if not minipc.enabled():
                raise
            print(f"reset attempt {attempt} failed ({e})")
    minipc.restart_simulator()
    return _reset_once(api)


def _reset_once(api: NinaApi) -> dict:

    # A previous run may have left the mount parking or the focuser moving; let that finish first.
    settle(api)

    ensure_connected(api)

    # Guider: stop it before the mount moves, as guiding and calibrating send pulses to the mount.
    reset_guider(api)

    # Camera: stop any exposure and cooling, then warm back to ambient.
    api.get("equipment/camera/abort-exposure")
    api.get("equipment/camera/cool", cancel="true")
    api.get("equipment/camera/warm", minutes=0)
    wait_for("camera to reach ambient", lambda: abs(api.info("camera")["Temperature"] - CAMERA_TEMP) <= 1)

    # Mount: stop motion, unpark and slew to the baseline position.
    api.get("equipment/mount/slew/stop")
    api.get("equipment/mount/unpark")
    wait_for("mount to unpark", lambda: not api.info("mount")["AtPark"])
    slew_to_baseline(api)

    # Focuser: move to the baseline and wait for it to stop.
    move_focuser(api, FOCUSER_POSITION)

    # Filter wheel: back to the baseline filter.
    if not filter_at(api, FILTER_BASELINE):
        change_filter(api, FILTER_BASELINE)

    # Mount pointing: a plate solve needs the camera and a focused sky, so this comes last.
    fix_pointing(api)

    return verify(api)


def slew_to_baseline(api: NinaApi) -> None:
    api.get("equipment/mount/slew", ra=MOUNT_RA_DEG, dec=MOUNT_DEC, waitForResult="true")
    wait_for("mount to stop slewing", lambda: not api.info("mount")["Slewing"])


def solve_frame(api: NinaApi) -> tuple[tuple[float, float] | None, str]:
    """Take a short plate-solved frame that is not saved. Returns the J2000 degrees the camera points at, or None and why."""
    try:
        r = requests.get(
            f"{api.base}/equipment/camera/capture", timeout=SOLVE_TIMEOUT_S,
            params={"duration": SOLVE_EXPOSURE_S, "solve": "true", "save": "false", "omitImage": "true", "waitForResult": "true"},
        ).json()
    except (requests.RequestException, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"
    solved = (r.get("Response") or {}).get("PlateSolveResult") if isinstance(r.get("Response"), dict) else None
    coords = (solved or {}).get("Coordinates") or {}
    if (solved or {}).get("Success") and "RADegrees" in coords and "Dec" in coords:
        return (coords["RADegrees"], coords["Dec"]), ""
    return None, str(r.get("Error") or json.dumps(r)[:300])


def solve_pointing(api: NinaApi) -> tuple[float, float] | None:
    """Where the camera really points (J2000 degrees), or None if the frame did not solve."""
    return solve_frame(api)[0]


def pointing_error_deg(api: NinaApi) -> float:
    """How far the mount's reported position is from where the camera really points. Raises if the frame did not solve."""
    sky, problem = solve_frame(api)
    if sky is None:
        raise RuntimeError(f"could not plate solve to check where the mount is pointing: {problem}")
    ra, dec = j2000_to_jnow(*sky)  # the mount reports JNOW
    mount = api.info("mount")
    return separation_deg(mount["RightAscension"] * 15, mount["Declination"], ra, dec)


def fix_pointing(api: NinaApi) -> None:
    """Make the mount's readout match the sky: a mount synced to the wrong place is synced back by plate solving."""
    settle(api)  # a frame taken just after a slew has trailed stars and does not solve
    error = pointing_error_deg(api)
    if error <= POINTING_TOLERANCE_DEG:
        return
    print(f"mount reports a position {error:.2f}° from where it points; syncing it")
    api.get("equipment/mount/sync")  # no coordinates: NINA plate solves and syncs
    slew_to_baseline(api)
    settle(api)
    error = pointing_error_deg(api)
    if error > POINTING_TOLERANCE_DEG:
        raise RuntimeError(f"mount still {error:.2f}° from where it points after a sync")


def settle(api: NinaApi, timeout: float = TIMEOUT_S) -> float:
    """Wait until the mount, focuser and filter wheel have stayed still for STILL_FOR_S. Returns seconds waited.

    Parking and focuser moves return at once and finish later, and the simulators start moving a
    second or two after the command. A single "not moving" reading is therefore not enough, so the
    equipment must be still for a continuous window before the end state counts as final.
    """
    start = time.monotonic()
    still_since = None
    while time.monotonic() - start < timeout:
        moving = api.info("mount")["Slewing"] or api.info("focuser")["IsMoving"] or api.info("filterwheel")["IsMoving"]
        now = time.monotonic()
        if moving:
            still_since = None
        elif still_since is None:
            still_since = now
        elif now - still_since >= STILL_FOR_S:
            return now - start
        time.sleep(1)
    raise TimeoutError("settle: equipment kept moving")


def snapshot(api: NinaApi) -> dict:
    """Read the state the scorer cares about, straight from NINA."""
    camera, mount, focuser = api.info("camera"), api.info("mount"), api.info("focuser")
    wheel = api.info("filterwheel")
    filter_now = wheel.get("SelectedFilter") or {}
    return {
        "camera_connected": camera["Connected"],
        "camera_temperature": camera.get("Temperature"),
        "camera_cooler_on": camera.get("CoolerOn"),
        "mount_connected": mount["Connected"],
        "mount_ra_hours": mount["RightAscension"],
        "mount_dec_deg": mount["Declination"],
        "mount_tracking": mount["TrackingEnabled"],
        "mount_parked": mount["AtPark"],
        "mount_slewing": mount["Slewing"],
        "focuser_connected": focuser["Connected"],
        "focuser_position": focuser["Position"],
        "focuser_moving": focuser["IsMoving"],
        "filterwheel_connected": wheel["Connected"],
        "filter_id": filter_now.get("Id"),
        "filter_name": filter_now.get("Name"),
        "filterwheel_moving": wheel["IsMoving"],
        "image_count": api.get("image-history", count="true"),
        **({"guider_state": api.info("guider")["State"]} if "guider" in devices() else {}),
    }


def verify(api: NinaApi) -> dict:
    """Check the baseline holds and return a snapshot (including the frame count to score against)."""
    camera, mount, focuser = api.info("camera"), api.info("mount"), api.info("focuser")
    wheel = api.info("filterwheel")
    problems = []
    if not (camera["Connected"] and mount["Connected"] and focuser["Connected"] and wheel["Connected"]):
        problems.append("a device is not connected")
    if "guider" in devices():
        guider = api.info("guider")
        if not guider["Connected"] or guider["State"] in GUIDING_STATES:
            problems.append(f"guider {'not connected' if not guider['Connected'] else guider['State']}")
    if abs(camera["Temperature"] - CAMERA_TEMP) > 1:
        problems.append(f"camera temperature {camera['Temperature']}")
    ra_jnow, dec_jnow = j2000_to_jnow(MOUNT_RA_DEG, MOUNT_DEC)  # the mount reports JNOW; the baseline is J2000
    ra_error = abs(mount["RightAscension"] - ra_jnow / 15)
    if min(ra_error, 24 - ra_error) > MOUNT_RA_TOL_HOURS or abs(mount["Declination"] - dec_jnow) > MOUNT_DEC_TOL_DEG:
        problems.append(f"mount at RA {mount['RightAscension']} Dec {mount['Declination']}")
    if mount["AtPark"] or mount["Slewing"]:
        problems.append("mount parked or slewing")
    if focuser["Position"] != FOCUSER_POSITION or focuser["IsMoving"]:
        problems.append(f"focuser at {focuser['Position']}")
    if not filter_at(api, FILTER_BASELINE):
        problems.append(f"filter wheel at {(wheel.get('SelectedFilter') or {}).get('Name')}")
    if problems:
        raise RuntimeError("reset failed verification: " + "; ".join(problems))

    return snapshot(api)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    start = time.monotonic()
    print(reset())
    print(f"reset took {time.monotonic() - start:.1f}s")
