from harness import reset


class FakeApi:
    """Just enough of NinaApi: a focuser that reaches any commanded position at once, and devices."""

    def __init__(self, position=1, connected=("camera", "mount", "focuser")):
        self.position = position
        self.connected = set(connected)
        self.calls = []

    def info(self, device):
        if device == "focuser":
            return {"Connected": "focuser" in self.connected, "Position": self.position, "IsMoving": False}
        return {"Connected": device in self.connected}

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "equipment/focuser/move":
            self.position = int(params["position"])
        elif path.endswith("/connect"):
            self.connected.add(path.split("/")[1])
        elif path.endswith("/disconnect"):
            self.connected.discard(path.split("/")[1])
        return {}

    def moves(self):
        return [p["position"] for path, p in self.calls if path == "equipment/focuser/move"]


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
    assert reset.ensure_connected(api) == ["mount", "focuser"]
    assert reset.ensure_connected(api) == []
    assert api.connected == {"camera", "mount", "focuser"}
