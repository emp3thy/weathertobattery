# Running the nightly charge job from NanoClaw

**Date:** 2026-10-24
**Status:** approved in conversation, awaiting written review

## Summary

Move the nightly Growatt charge calculation from a Windows scheduled task to a
NanoClaw agent group running inside the WSL2 Ubuntu instance. The job keeps its
code, configuration, credentials and history; what changes is who starts it,
where its files live, and how its result reaches the owner (a Slack direct
message instead of a log file nobody reads).

This is the first of two NanoClaw automations. It is deliberately small so that
it proves the shared pattern — dedicated agent group, mounted folder, recurring
task, Slack report — before the inbox-processing automation reuses it.

## Goals

- The charge level is set every night at 22:00 Europe/London by NanoClaw, with
  no Windows scheduled task involved.
- The owner sees one Slack line per night: the charge level set, or a failure
  with enough context to act on.
- Decision history, actuals and readings in `data/battery.db` survive the move
  and keep accumulating in one place.
- The dashboard keeps working in a Windows browser at `http://localhost:8099`.
- The Growatt login never leaves the mounted project folder; it is not pasted
  into prompts, task text or NanoClaw configuration.

## Non-goals

- Any change to the charge calculation, weather provider or Growatt client.
- Interactive control of the job through chat ("set tonight's charge to 60%").
  That is a later feature, if wanted at all.
- Moving the Growatt credentials behind the OneCLI proxy. The login is a form
  POST that the proxy cannot inject into, so the credentials stay in `.env`
  inside the container's mount. The owner accepted this on 2026-10-24.
- Keeping the Windows copy of `battery.db` in sync. After cutover the Ubuntu
  copy is the only live one.

## Current state (verified 2026-10-24)

- Windows scheduled task "WeatherToBattery Nightly" runs
  `python scripts\nightly-charge.py` at 22:00 daily from
  `C:\Users\gethi\sources\weathertobattery`, appending to `data\nightly.log`.
- `data/battery.db` is a 2.8 MB SQLite file with tables `decisions`,
  `actuals`, `readings`. `data/` also holds `nightly.log` and `backfill.log`.
- `run_dashboard.py` serves FastAPI via uvicorn on `127.0.0.1:8099` (port from
  `config.yaml`), reading the same database.
- Credentials: `.env` with `GROWATT_USERNAME`, `GROWATT_PASSWORD`,
  `GROWATT_PLANT_ID`, `GROWATT_DEVICE_SN`. Location values may also come from
  `LOCATION_*` env vars; `config.yaml` holds the rest.
- `scripts/nightly-charge.py` has no dry-run option: every run logs in and
  sets the charge level.
- NanoClaw v2 runs in WSL2 Ubuntu 26.04 at `/home/gethi/nanoclaw` as a systemd
  user service, with Docker Engine, the OneCLI gateway bound to the Docker
  bridge (`172.17.0.1`), and a Slack DM wired to the "Dr Claw" agent group.
- Agent containers use the pinned hardened image, which has no Python. From a
  container, `server.growatt.com`, `api.open-meteo.com` and `pypi.org` all
  answer through the proxy (pass-through hosts).

## Design

### 1. Runtime layout

**Agent group.** A new agent group, display name "Battery Scheduler", folder
`battery-scheduler`, created with `ncl groups create`. It is not wired to any
messaging group, so it never receives chat and wakes only for its task. Its
`cli_scope` stays at the default `group`.

**Project location.** The repository is cloned to `/home/gethi/weathertobattery`
in Ubuntu from the GitHub remote. The three untracked, machine-specific items
are copied across once from the Windows checkout: `config.yaml`, `.env` and
`data/` (database and logs). The Windows checkout remains the place to edit
code; changes flow through git (`git pull` in Ubuntu).

**Mount.** `/home/gethi/weathertobattery` is added to the NanoClaw mount
allowlist (`~/.config/nanoclaw/mount-allowlist.json`) as `allowReadWrite:
true`, and attached to the Battery Scheduler group as an additional mount at
`/workspace/weathertobattery`. The default `blockedPatterns` list matches path
names only, so `.env` inside the folder is not blocked.

**Python in the image.** The group's container config gets `python3` and
`python3-venv` via `ncl groups config add-package --apt`. NanoClaw builds a
derived image for this group on top of the pinned hardened image; the hardened
image itself is untouched (see `docs/hardened-image.md` in NanoClaw: apt and
npm packages work as a derived image).

**Python dependencies.** A virtual environment at
`/workspace/weathertobattery/.venv`, created on first run from
`requirements.txt`. Because it lives in the mounted folder it persists across
container restarts and image rebuilds. A venv is bound to the absolute path and
Python build it was created with, and the container's Python is not the host's,
so the dashboard on the Ubuntu host uses its own venv at
`~/weathertobattery/.venv-host`, created once by hand from the same
`requirements.txt`. The folder's `.gitignore` gains `.venv*/`.

**Wrapper script.** New file `scripts/run-nightly.sh` in the repository:

1. `cd` to the project root (its own parent directory).
2. If `.venv/bin/python` is missing, create the venv and `pip install -r
   requirements.txt`. A failure here exits non-zero with the pip output.
3. Run `.venv/bin/python scripts/nightly-charge.py "$@"`, appending stdout and
   stderr to `data/nightly.log` with a timestamp header, while also echoing the
   script's final line to its own stdout.
4. Exit with the script's exit status.

It is plain POSIX shell with no dependencies beyond `python3`, so the same
file runs in the container and on the Ubuntu host.

**Dry-run flag.** `scripts/nightly-charge.py` gains `--dry-run`: it performs
every step including the Growatt login and the calculation, prints the charge
level it would set, but does not call the set-charge endpoint and does not
write a `decisions` row. This exists so the task can be rehearsed in daylight
without touching the inverter. It is the only change to existing code.

### 2. Schedule and reporting

**Task.** One recurring NanoClaw task on the Battery Scheduler group, created
with `ncl tasks create`, recurrence `0 22 * * *`. NanoClaw interprets cron in
the install timezone, which is `Europe/London` in `.env` (`TZ`), so the run
follows British clock changes. The task name is `nightly-charge`.

**Prompt.** The task prompt is fixed text, roughly:

> Run `bash /workspace/weathertobattery/scripts/run-nightly.sh`. Then send one
> message to the owner's Slack DM. If the exit status was 0, send exactly the
> script's final output line prefixed with "Battery:". If it was not 0, send
> "Battery run FAILED (exit N)" followed by the last 15 lines of
> `/workspace/weathertobattery/data/nightly.log`. Do not retry, do not change
> any file, do not interpret or summarise the output.

**Destination.** The owner's Slack DM (`slack:D0CBYSNNB3N`) is added as a
destination of the Battery Scheduler group with `ncl destinations add`, so the
agent can send there without being wired to receive from it.

**What the agent does not do.** It never edits `config.yaml`, `.env` or the
database, never installs packages beyond the wrapper's venv step, and never
decides the charge level. The group's `CLAUDE.md` says so explicitly.

### 3. Dashboard

A systemd user unit `weathertobattery-dashboard.service` in Ubuntu runs
`~/weathertobattery/.venv-host/bin/python run_dashboard.py` from the project
directory, `Restart=on-failure`, enabled so that it starts with the user
session (lingering is already enabled for `gethi` by NanoClaw's setup). It
binds to `127.0.0.1:8099` as today; WSL forwards loopback ports, so the
Windows browser reaches it at `http://localhost:8099`.

The dashboard only reads the database. The nightly job is the only writer.
There is no concurrent-writer case to design for.

### 4. Failure handling

| Failure | Behaviour |
|---|---|
| Script fails (Growatt login, API error, config error) | Wrapper exits non-zero. Agent posts "Battery run FAILED" with the log tail. No automatic retry. The script's existing weather fallback already covers an Open-Meteo outage, so a reported failure is a real problem. |
| Container, image or gateway unavailable at 22:00 | NanoClaw's host sweep retries waking the task on its next pass, so a short outage delays the run. The task's run log (`ncl tasks get`) shows whether it ran. |
| Venv missing or broken | Wrapper recreates it from `requirements.txt` through the proxy (PyPI passes through). If that fails, it is reported as a script failure. |
| Agent misreports | The prompt restricts the agent to quoting the exit status and the script's own output. `data/nightly.log` and `battery.db` remain the source of truth. |
| Ubuntu instance not running | Out of scope for this spec: the WSL keepalive task and `vmIdleTimeout` set up on 2026-10-24 keep it running; if it is down, nothing in NanoClaw runs and the dashboard is down too, which is itself the signal. |

### 5. Cutover from the Windows task

1. Clone the repo in Ubuntu, copy `config.yaml`, `.env` and `data/`, create
   the host venv (`.venv-host`), start the dashboard service, and confirm the
   dashboard shows the existing history. The container venv is created by the
   wrapper on the first task run.
2. Disable (do not delete) the Windows task "WeatherToBattery Nightly" so the
   two copies cannot both act on the inverter.
3. Create the agent group, mount, packages, destination and task.
4. Rehearse in daylight: `ncl tasks run` with the prompt temporarily pointing
   at `run-nightly.sh --dry-run`. Confirm the Slack message, then switch the
   task prompt back to the real command.
5. Watch the first two real nightly runs in Slack and in the dashboard.
6. Delete the Windows task.

### 6. Testing

- **Wrapper, by hand in the container:** fresh venv creation; reuse of an
  existing venv; a deliberately broken `requirements.txt` producing a non-zero
  exit with pip output in the log.
- **Dry-run flag:** `nightly-charge.py --dry-run` logs in, computes, prints the
  level, writes no `decisions` row and makes no set-charge call. Verified by
  row count before and after and by the Growatt portal showing no change.
- **Acceptance:** a forced task run (`ncl tasks run`) produces the Slack line,
  a new `decisions` row, and the expected charge level in the Growatt portal.
- **Negative:** temporarily corrupt `GROWATT_PASSWORD` in `.env`, force a run,
  confirm the Slack failure message and no new `decisions` row, restore.
- **Schedule:** after the first real night, `ncl tasks get nightly-charge`
  shows the run at 22:00 local and the next run scheduled for the following
  day.

## Files touched

In this repository:

- `scripts/run-nightly.sh` — new wrapper.
- `scripts/nightly-charge.py` — add `--dry-run`.
- `src/orchestrator.py` and/or `src/growatt/client.py` — whatever minimal hook
  `--dry-run` needs to skip the set-charge call and the `decisions` insert.
- `.gitignore` — add `.venv*/`.
- `README.md` — a short "Running under NanoClaw" section.

Outside this repository (configuration, not code): NanoClaw mount allowlist,
agent group, container config, destination, task; one systemd user unit for
the dashboard; the Windows scheduled task disabled then deleted.

## Assumptions

Status: **verified** (checked today), **measured** (observed in operation), or
**unverified**. Each line says what it costs if wrong.

- NanoClaw's apt package mechanism produces a working derived image on top of
  the pinned hardened image, including `python3-venv`. **Unverified** (the
  mechanism is documented; it has not been exercised on this install). If
  wrong: fall back to a locally built agent image with Python baked in, which
  this install already has (`nanoclaw-agent-v2-479b04f8:latest`); that costs
  the switch from hardened to local image for this group only.
- Agent containers reach `server.growatt.com`, `api.open-meteo.com` and
  `pypi.org` through the OneCLI proxy without credentials. **Verified** by
  probe from a container today (HTTP 200 on all three). If wrong later (for
  example a proxy policy change): the run fails loudly and is reported.
- A bind mount from the mount allowlist is writable by the container user, so
  the job can write `battery.db`, the log and the venv. **Unverified** on this
  install. If wrong: ownership fix on the host folder (`chown`/`chmod`) or
  running the venv in the group workspace instead; small.
- `ncl tasks create` accepts a five-field cron recurrence and runs it in the
  install timezone. **Verified** from NanoClaw source
  (`validateRecurrence` uses cron-parser with the install `TIMEZONE`).
- A group that is not wired to any messaging group can still deliver to a
  registered destination. **Unverified**; the `destinations` resource exists
  for exactly this, but it has not been exercised here. If wrong: wire the
  group to the Slack DM with an engage mode that ignores inbound, which is
  noisier but works.
- SQLite over a Docker bind mount of a native ext4 path is reliable.
  **Verified** in general (it is the normal Docker case); the unreliable case
  is `/mnt/c`, which this design avoids.
- Loopback ports in WSL are reachable from the Windows browser as localhost.
  **Measured** earlier today for other services on this machine.
- The Windows task is the only other thing that writes to `battery.db`.
  **Verified** by inspecting the scheduled tasks; no other job references the
  folder.
- `--dry-run` can skip the set-charge call and the decisions insert without
  restructuring the orchestrator. **Unverified** until the code is read in
  detail; if awkward, the fallback is a `GROWATT_DRY_RUN=1` environment check
  inside the Growatt client, which is cruder but equivalent for the test.
