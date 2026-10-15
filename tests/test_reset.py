import pytest

from harness import reset
from harness.coords import j2000_to_jnow


class FakeApi:
    """Just enough of NinaApi: a focuser that reaches any commanded position at once, and devices."""

    def __init__(self, position=1, connected=("camera", "mount", "focuser", "filterwheel")):
        self.position = position
        self.filter = 0
        self.connected = set(connected)
        self.ids = {d: "direct-alpaca" for d in connected}
        self.calls = []

    def info(self, device):
        if device == "filterwheel":
            return {"Connected": "filterwheel" in self.connected, "DeviceId": self.ids.get(device), "IsMoving": False,
                    "SelectedFilter": {"Id": self.filter, "Name": f"filter {self.filter}"}}
        if device == "focuser":
            return {"Connected": "focuser" in self.connected, "Position": self.position, "IsMoving": False}
        return {"Connected": device in self.connected, "DeviceId": self.ids.get(device)}

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "equipment/focuser/move":
            self.position = int(params["position"])
        elif path == "equipment/filterwheel/change-filter":
            self.filter = int(params["filterId"])
        elif path.endswith("/connect"):
            self.connected.add(path.split("/")[1])
            self.ids[path.split("/")[1]] = params.get("to", "direct-alpaca")
        elif path.endswith("/disconnect"):
            self.connected.discard(path.split("/")[1])
        return {}

    def moves(self):
        return [p["position"] for path, p in self.calls if path == "equipment/focuser/move"]

    def connects(self):
        return [(path.split("/")[1], p.get("to")) for path, p in self.calls if path.endswith("/connect")]


def test_long_focuser_move_is_made_in_chunks():
    api = FakeApi(position=1)
    reset.move_focuser(api, 5000)
    assert api.moves() == [2001, 4001, 5000] and api.position == 5000


def test_focuser_chunks_work_downwards_and_skip_a_move_already_there():
    api = FakeApi(position=5000)
    reset.move_focuser(api, 1)
    assert api.moves() == [3000, 1000, 1]
    there = FakeApi(position=7)
    reset.move_focuser(there, 7)
    assert there.moves() == []


def test_short_move_is_a_single_command():
    api = FakeApi(position=25000)
    reset.move_focuser(api, 25500)
    assert api.moves() == [25500]


def test_ensure_connected_connects_only_what_is_down():
    api = FakeApi(connected=("camera",))
    assert reset.ensure_connected(api) == ["mount", "focuser", "filterwheel"]
    assert reset.ensure_connected(api) == []
    assert api.connected == {"camera", "mount", "focuser", "filterwheel"}


def test_ensure_connected_uses_the_configured_ids(monkeypatch):
    monkeypatch.setenv("NINA_CAMERA_ID", "ASCOM.AlpacaDynamic1.Camera")
    monkeypatch.setenv("NINA_MOUNT_ID", "ASCOM.AlpacaDynamic1.Telescope")
    monkeypatch.setenv("NINA_FOCUSER_ID", "ASCOM.AlpacaDynamic1.Focuser")
    monkeypatch.setenv("NINA_FILTERWHEEL_ID", "ASCOM.AlpacaDynamic1.FilterWheel")
    api = FakeApi(connected=())
    assert reset.ensure_connected(api) == ["camera", "mount", "focuser", "filterwheel"]
    assert api.connects() == [("camera", "ASCOM.AlpacaDynamic1.Camera"), ("mount", "ASCOM.AlpacaDynamic1.Telescope"),
                              ("focuser", "ASCOM.AlpacaDynamic1.Focuser"),
                              ("filterwheel", "ASCOM.AlpacaDynamic1.FilterWheel")]


def test_a_device_connected_to_the_wrong_id_is_switched(monkeypatch):
    monkeypatch.setenv("NINA_CAMERA_ID", "ASCOM.AlpacaDynamic1.Camera")
    api = FakeApi()  # everything connected through the direct Alpaca route
    assert reset.ensure_connected(api) == ["camera"]
    assert api.ids["camera"] == "ASCOM.AlpacaDynamic1.Camera" and api.ids["mount"] == "direct-alpaca"
    assert reset.ensure_connected(api) == []  # already right: left alone


def test_without_configured_ids_the_selected_device_is_connected_as_before(monkeypatch):
    for name in reset.DEVICE_ID_ENV.values():
        monkeypatch.delenv(name, raising=False)
    api = FakeApi(connected=("camera",))
    reset.ensure_connected(api)
    assert api.connects() == [("mount", None), ("focuser", None), ("filterwheel", None)]


def test_change_filter_waits_for_the_wheel_to_arrive():
    api = FakeApi()
    assert reset.filter_at(api, 0) and not reset.filter_at(api, 3)
    reset.change_filter(api, 3)
    assert api.filter == 3 and reset.filter_at(api, 3)
    assert ("equipment/filterwheel/change-filter", {"filterId": 3}) in api.calls


def test_snapshot_reads_the_filter():
    api = FakeApi()
    api.filter = 1

    def info(device, real=api.info):
        base = real(device)
        if device == "camera":
            base.update({"Temperature": 20, "CoolerOn": False})
        if device == "mount":
            base.update({"RightAscension": reset.MOUNT_RA_DEG / 15, "Declination": reset.MOUNT_DEC, "TrackingEnabled": True, "AtPark": False, "Slewing": False})
        return base

    api.info = info
    original_get = api.get
    api.get = lambda path, **p: 7 if path == "image-history" else original_get(path, **p)
    state = reset.snapshot(api)
    assert state["filter_id"] == 1 and state["filter_name"] == "filter 1" and state["filterwheel_connected"]
    assert state["filterwheel_moving"] is False


# --- pointing: the mount's readout against a plate solve -------------------------------------------

SKY = (reset.MOUNT_RA_DEG, reset.MOUNT_DEC)  # where the camera points, J2000 degrees
_jnow = j2000_to_jnow(*SKY)
ALIGNED = (_jnow[0] / 15, _jnow[1])           # what a correctly synced mount reports: JNOW, RA in hours


class PointingApi(FakeApi):
    """A mount that reports (reported_ra_hours, reported_dec) and a sky the solver reads as `sky` (J2000 degrees)."""

    def __init__(self, reported=ALIGNED):
        super().__init__(position=reset.FOCUSER_POSITION)
        self.reported = reported

    def info(self, device):
        if device == "mount":
            return {"Connected": True, "RightAscension": self.reported[0], "Declination": self.reported[1], "Slewing": False}
        return super().info(device)

    def get(self, path, **params):
        if path == "equipment/mount/sync":
            self.reported = ALIGNED  # solved and synced: the readout now matches the sky
        return super().get(path, **params)


def solving(monkeypatch, api, sky=SKY):
    monkeypatch.setattr(reset, "solve_frame", lambda a: (sky, "" if sky else "no stars"))
    monkeypatch.setattr(reset, "slew_to_baseline", lambda a: None)
    monkeypatch.setattr(reset, "settle", lambda a: 0.0)


def test_pointing_that_matches_the_sky_is_left_alone(monkeypatch):
    api = PointingApi()
    solving(monkeypatch, api)
    reset.fix_pointing(api)
    assert [p for p, _ in api.calls if p == "equipment/mount/sync"] == []


def test_a_mount_that_reports_the_wrong_place_is_synced_by_plate_solving(monkeypatch):
    api = PointingApi(reported=(ALIGNED[0] + 2.0 / 15, ALIGNED[1]))  # reads 2° off in RA
    solving(monkeypatch, api)
    reset.fix_pointing(api)
    assert [p for p, _ in api.calls if p == "equipment/mount/sync"] == ["equipment/mount/sync"]
    assert [params for p, params in api.calls if p == "equipment/mount/sync"] == [{}]  # no coordinates: solve and sync


def test_pointing_that_cannot_be_solved_fails_the_reset(monkeypatch):
    api = PointingApi()
    solving(monkeypatch, api, sky=None)
    with pytest.raises(RuntimeError, match="could not plate solve"):
        reset.fix_pointing(api)


def test_pointing_that_a_sync_does_not_fix_fails_the_reset(monkeypatch):
    api = PointingApi(reported=(ALIGNED[0] + 2.0 / 15, ALIGNED[1]))
    api.get = lambda path, **params: {}  # the sync does nothing
    solving(monkeypatch, api)
    with pytest.raises(RuntimeError, match="after a sync"):
        reset.fix_pointing(api)
