"""Failures injected after the reset, for the tier 3 recovery tasks (what works is in docs/simulator-notes.md).

Each fault leaves the equipment in a broken state and returns the devices that are meant to stay
down, so the watchdog does not repair them or count them as drops. The next reset undoes both:
it moves the focuser back and reconnects every device.
"""
from collections.abc import Callable

from harness.reset import FOCUSER_POSITION, NinaApi, move_focuser, wait_for

# Best focus is 25000. Centring worked 300 steps out and never finished 700 steps out.
DEFOCUS_STEPS = 1000


def defocus(api: NinaApi) -> tuple[str, ...]:
    """Plate solving fails when out of focus, so centring never completes."""
    move_focuser(api, FOCUSER_POSITION - DEFOCUS_STEPS)
    return ()


def camera_offline(api: NinaApi) -> tuple[str, ...]:
    """The camera answers every call with 'Camera not connected' until the model reconnects it."""
    api.get("equipment/camera/disconnect")
    wait_for("camera to disconnect", lambda: not api.info("camera")["Connected"])
    return ("camera",)


FAULTS: dict[str, Callable[[NinaApi], tuple[str, ...]]] = {"defocus": defocus, "camera_offline": camera_offline}


def inject(fault: str, api: NinaApi) -> tuple[str, ...]:
    return FAULTS[fault](api)
