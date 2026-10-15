import pytest

from harness import reset
from harness.watchdog import Watchdog


class GuiderApi:
    """NINA with a guider: stopping takes a poll or two to show, clearing forgets the calibration."""

    def __init__(self, state="Guiding", connected=True, connect_fails=False):
        self.state = state
        self.connected = {"camera", "mount", "focuser", "filterwheel"} | ({"guider"} if connected else set())
        self.connect_fails = connect_fails
        self.calibrated = True
        self.calls = []
        self.stopping = False
        self.stopping_polls = 0

    def info(self, device):
        if device == "guider":
            if self.stopping:
                self.stopping_polls += 1
                if self.stopping_polls > 1:
                    self.state, self.stopping = "Stopped", False
            return {"Connected": "guider" in self.connected, "DeviceId": "PHD2_Single", "State": self.state}
        return {"Connected": device in self.connected, "DeviceId": None}

    def get(self, path, **params):
        self.calls.append(path)
        device = path.split("/")[1]
        if path.endswith("/connect"):
            if self.connect_fails:
                raise RuntimeError(f"{path}: Failed to connect")
            self.connected.add(device)
        elif path == "equipment/guider/stop":
            self.stopping = True  # still reports the old state for a poll or two
        elif path == "equipment/guider/clear-calibration":
            self.calibrated = False
        return {}


@pytest.fixture(autouse=True)
def guider_configured(monkeypatch):
    monkeypatch.setenv("NINA_GUIDER_ID", "PHD2_Single")
    monkeypatch.setattr(reset.time, "sleep", lambda s: None)


def test_the_guider_is_only_used_when_it_is_configured(monkeypatch):
    assert reset.devices() == (*reset.DEVICES, "guider")
    monkeypatch.delenv("NINA_GUIDER_ID")
    assert reset.devices() == reset.DEVICES
    api = GuiderApi()
    reset.reset_guider(api)
    assert api.calls == []  # a run without a guider never touches PHD2


@pytest.mark.parametrize("state", ["Guiding", "Calibrating"])
def test_reset_stops_guiding_and_clears_the_calibration(state):
    api = GuiderApi(state=state)
    reset.reset_guider(api)
    assert api.state == "Stopped" and not api.calibrated
    assert api.calls.index("equipment/guider/stop") < api.calls.index("equipment/guider/clear-calibration")


def test_reset_connects_a_guider_that_is_down():
    api = GuiderApi(state="Stopped", connected=False)
    assert reset.ensure_connected(api) == ["guider"]
    assert "guider" in api.connected


def test_a_guider_that_will_not_connect_says_to_check_phd2():
    with pytest.raises(RuntimeError, match="PHD2 running"):
        reset.ensure_connected(GuiderApi(connected=False, connect_fails=True))


def _ready(api):
    """Give GuiderApi the extra fields verify and snapshot read from the other devices."""
    real = api.info

    def info(device):
        base = real(device)
        if device == "camera":
            base.update({"Temperature": reset.CAMERA_TEMP, "CoolerOn": False})
        if device == "mount":
            ra, dec = reset.j2000_to_jnow(reset.MOUNT_RA_DEG, reset.MOUNT_DEC)
            base.update({"RightAscension": ra / 15, "Declination": dec, "TrackingEnabled": True, "AtPark": False, "Slewing": False})
        if device == "focuser":
            base.update({"Position": reset.FOCUSER_POSITION, "IsMoving": False})
        if device == "filterwheel":
            base.update({"IsMoving": False, "SelectedFilter": {"Id": reset.FILTER_BASELINE, "Name": "Luminance"}})
        return base

    api.info = info
    original = api.get
    api.get = lambda path, **p: 0 if path == "image-history" else original(path, **p)
    return api


def test_verify_fails_while_the_guider_is_still_guiding():
    with pytest.raises(RuntimeError, match="guider Guiding"):
        reset.verify(_ready(GuiderApi(state="Guiding")))


def test_verify_fails_when_the_guider_is_not_connected():
    with pytest.raises(RuntimeError, match="guider not connected"):
        reset.verify(_ready(GuiderApi(state="Stopped", connected=False)))


def test_verify_passes_and_the_snapshot_records_the_guider_state():
    assert reset.verify(_ready(GuiderApi(state="Stopped")))["guider_state"] == "Stopped"


def test_the_watchdog_reconnects_a_dropped_guider():
    api = GuiderApi(state="Stopped", connected=False)
    wd = Watchdog(api, interval=0)
    assert wd.check() == ["guider"] and [d["device"] for d in wd.drops] == ["guider"]
    assert "guider" in api.connected
