import requests

from harness import watchdog

from harness.watchdog import Watchdog


class FakeApi:
    def __init__(self, connected=("camera", "mount", "focuser", "filterwheel"), fail=False, stubborn=False):
        self.connected = set(connected)
        self.fail = fail
        self.stubborn = stubborn  # a stalled simulator: connect calls are accepted but nothing connects
        self.connects = []

    def info(self, device):
        if self.fail:
            raise requests.ReadTimeout("busy")
        return {"Connected": device in self.connected}

    def get(self, path, **params):
        self.connects.append(path)
        self.params = params
        if not self.stubborn:
            self.connected.add(path.split("/")[1])


def test_healthy_equipment_records_nothing():
    wd = Watchdog(FakeApi(), interval=0)
    assert wd.check() == [] and wd.drops == []


def test_dropped_device_is_recorded_and_reconnected():
    api = FakeApi(connected=("camera", "mount", "filterwheel"))
    wd = Watchdog(api, interval=0)
    assert wd.check() == ["focuser"]
    assert [d["device"] for d in wd.drops] == ["focuser"]
    assert api.connects == ["equipment/focuser/connect"] and "focuser" in api.connected
    assert wd.check() == []  # repaired, so not recorded twice


def test_check_can_record_without_touching_the_equipment():
    api = FakeApi(connected=("camera",))
    wd = Watchdog(api, interval=0)
    assert wd.check(reconnect=False) == ["mount", "focuser", "filterwheel"] and api.connects == []


def test_an_unreachable_api_is_not_counted_as_a_device_drop():
    wd = Watchdog(FakeApi(fail=True), interval=0)
    assert wd.check() == [] and wd.drops == []


def test_background_loop_catches_a_drop_and_stops_cleanly():
    api = FakeApi(connected=("camera", "mount", "filterwheel"))
    wd = Watchdog(api, interval=0.01).start()
    for _ in range(200):
        if wd.drops:
            break
        import time
        time.sleep(0.01)
    wd.stop()
    assert wd.drops and "focuser" in api.connected and not wd._thread.is_alive()


def test_a_device_that_stays_down_is_recorded_once_and_not_hammered(monkeypatch):
    def give_up(*args, **kwargs):
        raise TimeoutError("still down")

    monkeypatch.setattr(watchdog, "wait_for", give_up)
    api = FakeApi(connected=("camera", "mount", "filterwheel"), stubborn=True)
    wd = Watchdog(api, interval=0)
    for _ in range(4):
        assert wd.check() == ["focuser"]
    assert len(wd.drops) == 1 and api.connects == ["equipment/focuser/connect"]


def test_a_second_outage_after_recovery_is_a_second_drop():
    api = FakeApi(connected=("camera", "mount", "filterwheel"))
    wd = Watchdog(api, interval=0)
    wd.check()
    wd.check()  # sees it connected again
    api.connected.discard("focuser")
    wd.check()
    assert [d["device"] for d in wd.drops] == ["focuser", "focuser"]


def test_reconnect_uses_the_configured_id(monkeypatch):
    monkeypatch.setenv("NINA_FOCUSER_ID", "ASCOM.AlpacaDynamic1.Focuser")
    api = FakeApi(connected=("camera", "mount", "filterwheel"))
    Watchdog(api, interval=0).check()
    assert api.params == {"to": "ASCOM.AlpacaDynamic1.Focuser"}


def test_a_device_a_fault_took_down_is_left_alone_until_it_comes_back():
    api = FakeApi(connected=("mount", "focuser", "filterwheel"))
    wd = Watchdog(api, interval=0, expected_down=("camera",))
    assert wd.check() == [] and wd.drops == [] and api.connects == []
    api.connected.add("camera")  # the model reconnected it
    assert wd.check() == [] and wd.expected_down == set()
    api.connected.discard("camera")  # now a real drop
    assert wd.check() == ["camera"] and [d["device"] for d in wd.drops] == ["camera"]


def test_a_device_the_model_disconnected_is_left_alone_and_not_a_drop():
    api = FakeApi(connected=("mount", "focuser", "filterwheel"))
    wd = Watchdog(api, interval=0)
    wd.model_disconnected("nina_disconnect_camera")
    assert wd.check() == [] and wd.drops == [] and api.connects == []


def test_nina_disconnect_leaves_every_device_alone():
    wd = Watchdog(FakeApi(connected=()), interval=0)
    wd.model_disconnected("nina_disconnect")
    assert wd.check() == [] and wd.drops == []


def test_a_device_the_model_connects_again_is_watched_again():
    api = FakeApi(connected=("mount", "focuser", "filterwheel"))
    wd = Watchdog(api, interval=0)
    wd.model_disconnected("nina_disconnect_camera")
    api.connected.add("camera")
    wd.check()
    api.connected.discard("camera")
    assert wd.check() == ["camera"]
