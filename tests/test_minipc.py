import subprocess

import pytest
import requests

from harness import minipc, reset


def fake_ssh(monkeypatch, returncode=0, stdout="{}", stderr=""):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    monkeypatch.setattr(minipc.subprocess, "run", run)
    return calls


def test_disabled_without_user(monkeypatch):
    monkeypatch.delenv("MINIPC_SSH_USER", raising=False)
    assert not minipc.enabled()
    with pytest.raises(RuntimeError, match="MINIPC_SSH_USER"):
        minipc.run("status")


def test_run_sends_one_allowed_command_with_the_key(monkeypatch):
    monkeypatch.setenv("MINIPC_SSH_USER", "sergio")
    monkeypatch.setenv("NINA_HOST", "192.168.1.211")
    monkeypatch.setenv("MINIPC_SSH_KEY", "/keys/nina")
    calls = fake_ssh(monkeypatch, stdout='{"ok":true}\n')
    assert minipc.run("restart-sim") == '{"ok":true}'
    args = calls[0]
    assert args[0] == "ssh" and args[-2:] == ["sergio@192.168.1.211", "restart-sim"]
    assert args[args.index("-i") + 1] == "/keys/nina" and "BatchMode=yes" in args


def test_run_refuses_commands_outside_the_allowed_three(monkeypatch):
    monkeypatch.setenv("MINIPC_SSH_USER", "sergio")
    calls = fake_ssh(monkeypatch)
    with pytest.raises(ValueError):
        minipc.run("shutdown /s")
    assert not calls


def test_run_reports_ssh_failure(monkeypatch):
    monkeypatch.setenv("MINIPC_SSH_USER", "sergio")
    fake_ssh(monkeypatch, returncode=255, stderr="Permission denied")
    with pytest.raises(RuntimeError, match="Permission denied"):
        minipc.run("status")


def failing_reset(monkeypatch):
    attempts = []

    def once(api):
        attempts.append(1)
        if len(attempts) < 3 or not restarts:
            raise TimeoutError("reset: timed out waiting for camera to connect")
        return {"ok": True}

    restarts = []
    monkeypatch.setattr(reset, "_reset_once", once)
    monkeypatch.setattr(reset.minipc, "restart_simulator", lambda: restarts.append(1))
    return attempts, restarts


def test_reset_restarts_the_simulator_after_two_failures_when_enabled(monkeypatch):
    monkeypatch.setenv("MINIPC_SSH_USER", "sergio")
    attempts, restarts = failing_reset(monkeypatch)
    assert reset.reset(api=object()) == {"ok": True}
    assert len(attempts) == 3 and len(restarts) == 1


def test_reset_gives_up_without_restarting_when_disabled(monkeypatch):
    monkeypatch.delenv("MINIPC_SSH_USER", raising=False)
    attempts, restarts = failing_reset(monkeypatch)
    with pytest.raises(TimeoutError):
        reset.reset(api=object())
    assert len(attempts) == 2 and not restarts


def test_reset_treats_a_request_timeout_as_a_failed_attempt(monkeypatch):
    monkeypatch.delenv("MINIPC_SSH_USER", raising=False)
    outcomes = iter([requests.ReadTimeout("slew timed out"), {"ok": True}])

    def once(api):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(reset, "_reset_once", once)
    assert reset.reset(api=object()) == {"ok": True}
