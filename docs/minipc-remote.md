# Restarting Sky Simulator and NINA from the Mac

Sky Simulator freezes or crashes during autofocus (see `simulator-notes.md`), and only a restart on
the mini PC brings it back. This lets the harness do that over SSH, with a key that can run three
fixed commands and nothing else.

| Command | What it does on the mini PC |
| --- | --- |
| `status` | Reports whether `sky_simulator` and `NINA` are running (start time, memory, responding) and whether Windows servicing is active |
| `restart-sim` | Closes Sky Simulator (kills it after 10 s) and starts it again |
| `restart-nina` | The same for NINA |

Connecting the equipment needs no setup: the reset reconnects the camera, mount and focuser itself.

## One-time setup

1. **Key (Mac).** `ssh-keygen -t ed25519 -N "" -f ~/.ssh/nina_minipc` makes a dedicated key; do not
   reuse your personal one. Print the public half with `cat ~/.ssh/nina_minipc.pub`.
2. **Copy `scripts/minipc/` to the mini PC** (clone the repo there, or copy the three `.ps1` files).
3. **Run the setup (mini PC).** With Sky Simulator and NINA running and you logged in, open an
   elevated PowerShell in that folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1 -PublicKey "ssh-ed25519 AAAA... mcp-nina-benchmarking restart key"
   ```
   It installs the OpenSSH Server (local subnet only), copies the scripts to `C:\nina-control`,
   records where the two apps live, registers the two restart tasks and authorises the key.
   Pass `-User`, `-SkySimulatorPath` or `-NinaPath` if the defaults are wrong.
4. **Enable it (Mac).** Add `MINIPC_SSH_USER=<the Windows user>` to `.env`, then:
   ```
   .venv/bin/python -m harness.minipc status
   .venv/bin/python -m harness.minipc restart-sim
   ```
   Check on the mini PC that Sky Simulator closed and reopened **with a window** (see below).

Once `MINIPC_SSH_USER` is set, `harness.reset` restarts Sky Simulator when a reset has failed twice,
then tries once more. Unset it to turn that off.

## Things to know
- **The mini PC must be logged in.** The apps are GUI programs, and a process started straight from
  SSH has no desktop. The restart runs through a scheduled task in the logged-on user's session, so
  with nobody logged in it will not work. For an unattended rig, set Windows to log in automatically.
- **A restart during a run ruins that run.** The hook only fires in the reset, between runs.
- **After a Sky Simulator restart, devices are disconnected** and the focuser is back at 1; the
  reset reconnects them and drives the focuser to the baseline, which can take several minutes.
- **What the key can do.** `authorized_keys` forces `nina-control.ps1`, with `restrict` (no shell,
  no forwarding). It runs only the three commands above and refuses anything else. The SSH port is
  open to the local subnet only. The scripts live in `C:\nina-control`; `log.txt` there records
  each restart.
- **Undo.** Delete the key line from `C:\ProgramData\ssh\administrators_authorized_keys` (or
  `~\.ssh\authorized_keys`), `Stop-Service sshd; Set-Service sshd -StartupType Disabled`, and
  `Unregister-ScheduledTask NinaCtl-RestartSim, NinaCtl-RestartNina`.

## Not yet verified
The PowerShell scripts were written on a Mac and have not been run on Windows. Expect to fix small
things on first use; the Python side is covered by `tests/test_minipc.py`.
