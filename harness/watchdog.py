"""Notice and repair a device that drops out of NINA during a run.

Sky Simulator's Alpaca server sometimes stalls and NINA then disconnects every device, which it
never retries on its own (docs/simulator-notes.md). A run that loses a device mid-way is not a fair
test of the model, so the watchdog records each drop (they go in the run log as `device_drops` and
the report leaves those runs out) and reconnects the device so the equipment is usable again.
"""
import threading
import time

import requests

from harness.reset import DEVICES, NinaApi, connect_command, wait_for

POLL_S = 5.0
RECONNECT_TIMEOUT_S = 60
RETRY_AFTER_S = 30  # a failed reconnect is not repeated sooner: a stalled simulator needs a restart, not hammering


class Watchdog:
    def __init__(self, api: NinaApi | None = None, interval: float = POLL_S):
        self.api = api or NinaApi()
        self.interval = interval
        self.drops: list[dict] = []
        self._last_attempt: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "Watchdog":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=RECONNECT_TIMEOUT_S + 10)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.check()

    def check(self, reconnect: bool = True) -> list[str]:
        """Record any disconnected device and (by default) reconnect it. Returns the devices found down."""
        down = []
        for device in DEVICES:
            try:
                connected = self.api.info(device)["Connected"]
            except (RuntimeError, requests.RequestException):
                continue  # NINA's API itself is busy or unreachable: not a device drop
            if not connected:
                down.append(device)
                # Record a drop once per outage, not on every check while the device stays down.
                if device not in self._last_attempt:
                    self.drops.append({"device": device, "t": time.time()})
            else:
                self._last_attempt.pop(device, None)
        if reconnect:
            for device in down:
                if time.monotonic() - self._last_attempt.get(device, -RETRY_AFTER_S) < RETRY_AFTER_S:
                    continue
                self._last_attempt[device] = time.monotonic()
                try:
                    connect_command(self.api, device)
                    wait_for(f"{device} to reconnect", lambda d=device: self.api.info(d)["Connected"],
                             timeout=RECONNECT_TIMEOUT_S)
                except (RuntimeError, TimeoutError, requests.RequestException):
                    pass  # still down: tried again after RETRY_AFTER_S
        return down
