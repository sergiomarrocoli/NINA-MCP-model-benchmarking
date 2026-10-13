import pytest

from harness.reset import DEVICE_ID_ENV


@pytest.fixture(autouse=True)
def no_configured_device_ids(monkeypatch):
    """The harness loads .env, which may name the ASCOM devices; tests must not depend on that."""
    for name in DEVICE_ID_ENV.values():
        monkeypatch.delenv(name, raising=False)
