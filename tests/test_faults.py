from harness import faults
from harness.reset import FOCUSER_POSITION


class FakeApi:
    def __init__(self):
        self.calls, self.camera_connected = [], True

    def info(self, device):
        if device == "focuser":
            return {"Position": FOCUSER_POSITION, "IsMoving": False}
        return {"Connected": self.camera_connected}

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "equipment/camera/disconnect":
            self.camera_connected = False
        if path == "equipment/focuser/move":
            self.position = params["position"]


def test_defocus_moves_the_focuser_out_and_expects_no_device_down():
    api = FakeApi()
    api.info = lambda device: {"Position": getattr(api, "position", FOCUSER_POSITION), "IsMoving": False}
    assert faults.inject("defocus", api) == ()
    assert api.position == FOCUSER_POSITION - faults.DEFOCUS_STEPS


def test_camera_offline_disconnects_the_camera_and_says_so():
    api = FakeApi()
    assert faults.inject("camera_offline", api) == ("camera",)
    assert api.calls == [("equipment/camera/disconnect", {})] and not api.camera_connected
