"""Restart Sky Simulator or NINA on the mini PC over SSH.

    python -m harness.minipc status | restart-sim | restart-nina

Off unless MINIPC_SSH_USER is set. The key only runs three fixed commands on the mini PC (see
scripts/minipc/setup.ps1 and docs/minipc-remote.md), so a leaked key cannot open a shell there.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

COMMANDS = ("status", "restart-sim", "restart-nina")
DEFAULT_KEY = "~/.ssh/nina_minipc"
SIM_BOOT_S = 30  # Sky Simulator needs a moment before NINA can talk to it again


def enabled() -> bool:
    return bool(os.environ.get("MINIPC_SSH_USER"))


def run(command: str, timeout: float = 60) -> str:
    """Run one of the allowed commands on the mini PC and return its output."""
    if command not in COMMANDS:
        raise ValueError(f"{command!r} is not one of {COMMANDS}")
    user = os.environ.get("MINIPC_SSH_USER")
    if not user:
        raise RuntimeError("MINIPC_SSH_USER is not set (see .env.example)")
    host = os.environ.get("NINA_HOST", "localhost")
    key = Path(os.environ.get("MINIPC_SSH_KEY", DEFAULT_KEY)).expanduser()
    result = subprocess.run(
        ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
         "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", command],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh {command} failed ({result.returncode}): {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def api_up(timeout: float = 5) -> bool:
    base = f"http://{os.environ.get('NINA_HOST', 'localhost')}:{os.environ.get('NINA_PORT', '1888')}/v2/api"
    try:
        return requests.get(f"{base}/version", timeout=timeout).ok
    except requests.RequestException:
        return False


def wait_for_api(timeout: float = 240) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if api_up():
            return
        time.sleep(3)
    raise TimeoutError("NINA's API did not come back after the restart")


def restart_simulator() -> None:
    """Restart Sky Simulator. NINA keeps running but loses its devices; the reset reconnects them."""
    print("restarting Sky Simulator on the mini PC")
    run("restart-sim")
    time.sleep(SIM_BOOT_S)
    wait_for_api()


def restart_nina() -> None:
    print("restarting NINA on the mini PC")
    run("restart-nina")
    time.sleep(10)
    wait_for_api()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "restart-sim":
        restart_simulator()
    elif cmd == "restart-nina":
        restart_nina()
    else:
        print(run(cmd))
