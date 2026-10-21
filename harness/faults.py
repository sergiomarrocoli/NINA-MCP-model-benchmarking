"""Failures injected after the reset, for the tier 3 recovery tasks (what works is in docs/simulator-notes.md).

Each fault leaves the equipment in a broken state and returns the devices that are meant to stay
down, so the watchdog does not repair them or count them as drops. The next reset undoes both:
it moves the focuser back and reconnects every device.
"""
from collections.abc import Callable

from harness.reset import FOCUSER_POSITION, MOUNT_DEC, MOUNT_RA_DEG, NinaApi, move_focuser, wait_for

# Best focus is 25000. Centring worked 300 steps out and never finished 700 steps out.
DEFOCUS_STEPS = 1000
# A sync 2° off in Dec (at the baseline, Dec +83°, an RA offset of 2° is only 0.24° on the sky).
POINTING_OFFSET_DEG = 2.0


def defocus(api: NinaApi) -> tuple[str, ...]:
    """Plate solving fails when out of focus, so centring never completes."""
    move_focuser(api, FOCUSER_POSITION - DEFOCUS_STEPS)
    return ()


def disconnect(api: NinaApi, *devices: str) -> tuple[str, ...]:
    for device in devices:
        api.get(f"equipment/{device}/disconnect")
    for device in devices:
        wait_for(f"{device} to disconnect", lambda device=device: not api.info(device)["Connected"])
    return devices


def camera_offline(api: NinaApi) -> tuple[str, ...]:
    """The camera answers every call with 'Camera not connected' until the model reconnects it."""
    return disconnect(api, "camera")


def all_offline(api: NinaApi) -> tuple[str, ...]:
    """Every device starts disconnected, and each has to be connected by the model."""
    return disconnect(api, "camera", "mount", "focuser", "filterwheel")


def pointing_offset(api: NinaApi) -> tuple[str, ...]:
    """The mount is synced to the wrong place: it reports the sky it points at shifted by 2°, so a slew lands 2° off.

    Only a plate solve shows it (docs/simulator-notes.md). The reset repairs it, so it does not outlast the run.
    """
    api.get("equipment/mount/sync", ra=MOUNT_RA_DEG, dec=MOUNT_DEC - POINTING_OFFSET_DEG)  # J2000 degrees
    return ()


FAULTS: dict[str, Callable[[NinaApi], tuple[str, ...]]] = {
    "defocus": defocus, "camera_offline": camera_offline, "all_offline": all_offline, "pointing_offset": pointing_offset,
}


def inject(fault: str, api: NinaApi) -> tuple[str, ...]:
    return FAULTS[fault](api)
