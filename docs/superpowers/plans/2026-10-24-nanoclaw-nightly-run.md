# NanoClaw Nightly Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The 22:00 Growatt charge job runs from a dedicated NanoClaw agent group in WSL2 Ubuntu and reports one line to the owner's Slack DM, replacing the Windows scheduled task.

**Architecture:** The repository moves to `/home/gethi/weathertobattery` and is bind-mounted into the "Battery Scheduler" agent group at `/workspace/extra/weathertobattery`. A recurring NanoClaw task runs a new wrapper script, which owns a venv inside the mount and calls `scripts/nightly-charge.py`; the agent only relays the wrapper's exit status and final line to Slack. The dashboard runs on the Ubuntu host from its own venv as a systemd user service. A new `--dry-run` flag lets the task be rehearsed without touching the inverter.

**Tech Stack:** Python 3.12+ (host: 3.14, container: 3.13), pytest, bash, NanoClaw v2 (`ncl` CLI, `scripts/q.ts`), Docker Engine in WSL2, systemd user units.

**Spec:** `docs/superpowers/specs/2026-10-24-nanoclaw-nightly-run-design.md`

## Global Constraints

- Only one change to existing Python behaviour: the `--dry-run` flag. The charge calculation, weather provider and Growatt client are untouched.
- The container path of the mount is the relative name `weathertobattery`; NanoClaw resolves it to `/workspace/extra/weathertobattery`.
- The mount's stored config must carry `"readonly": false` explicitly, and the allowlist root must be `allowReadWrite: true`.
- Container venv: `/workspace/extra/weathertobattery/.venv`. Host venv: `~/weathertobattery/.venv-host`. Never share one between them.
- Dashboard binds `127.0.0.1:8099` (port from `config.yaml`). The nightly job is the only writer of `data/battery.db`.
- Task recurrence `0 22 * * *`, interpreted in the install timezone `Europe/London`. Task name `nightly-charge`. Destination local name `owner-dm`, target type `channel`, target id `mg-1792842294323-af0eto`.
- Agent group display name "Battery Scheduler", folder `battery-scheduler`, no wirings, default `cli_scope`.
- The Windows task "WeatherToBattery Nightly" is disabled before NanoClaw ever runs the real command, and deleted only after two successful nightly runs.
- Commands that touch the Ubuntu side run as `gethi` via `wsl.exe -d Ubuntu -u gethi -- bash /mnt/c/<script>`; put multi-line scripts in a file under `C:\Users\gethi\AppData\Local\Temp\` rather than inline, because Windows-to-WSL argument passing strips quotes.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. `--dry-run` when a manual decision already exists for the target date: `run_nightly` returns early today; it must still return early (and not log in a second time) in dry-run. Test in Task 1.
2. `--dry-run` when the weather API fails: the fallback level is computed but nothing is set or written; the output line must say so. Test in Task 1.
3. Wrapper invoked from a different working directory (NanoClaw gives no guarantee of `cwd`): it must still find the project root and the venv. Test in Task 2.
4. Wrapper when `pip install` fails: non-zero exit, pip's output in the log, no attempt to run the script. Test in Task 2.
5. A second run on the same night (for example after `ncl tasks run` by hand): `upsert_decision` overwrites rather than duplicates; the Slack line must still be sent once per run. Covered by Task 6's rehearsal (two runs, two lines, one decision row).

---

### Task 1: `--dry-run` for the nightly job

**Confidence:** 95%

**Files:**
- Modify: `src/orchestrator.py` (function `run_nightly`, lines 179–261)
- Modify: `scripts/nightly-charge.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: existing `run_nightly(config, conn, weather_provider, growatt_client, target_date, project_root) -> dict`, `get_decision(conn, dt)`, `upsert_decision(...)`, `_write_last_updated(...)`.
- Produces: `run_nightly(..., dry_run: bool = False) -> dict`. When `dry_run` is true the returned dict has `"dry_run": True`, the charge level and reason are computed exactly as before, but `growatt_client.set_charge_soc` is not called, `upsert_decision` is not called and `last_updated.md` is not written. When false the dict has `"dry_run": False` and behaviour is unchanged. `scripts/nightly-charge.py --dry-run` prints `DRY RUN: would set charge to {level}% for {date}` and exits 0; without the flag it prints `Set charge to {level}% for {date}` as today.

- [ ] **Step 1: Write the failing tests in `tests/test_orchestrator.py`**

Follow the pattern of `test_orchestrator_sets_charge_and_logs` (same `_seed_actuals`, `_make_forecast`, `MagicMock` growatt and weather).

```python
def test_run_nightly_dry_run_computes_but_does_not_set_or_write(tmp_path, config):
    # same setup as test_orchestrator_sets_charge_and_logs
    result = run_nightly(config=config, conn=conn, weather_provider=mock_weather,
                         growatt_client=mock_growatt, target_date=date(2026, 7, 15),
                         project_root=tmp_path, dry_run=True)
    assert result["dry_run"] is True
    assert result["success"] is True
    assert 0 <= result["charge_level"] <= 100
    mock_growatt.set_charge_soc.assert_not_called()
    assert get_decision(conn, date(2026, 7, 15)) is None
    assert not (tmp_path / "last_updated.md").exists()


def test_run_nightly_default_reports_dry_run_false(tmp_path, config):
    # same setup; call without dry_run
    assert result["dry_run"] is False
    mock_growatt.set_charge_soc.assert_called_once()


def test_run_nightly_dry_run_respects_existing_manual_decision(tmp_path, config):
    # seed a manual decision first:
    # upsert_decision(conn, date(2026, 7, 15), forecast_summary="manual", forecast_detail="[]",
    #                 charge_level_set=70, adjustment_reason="Manual: set to 70%",
    #                 current_soc=None, month=7, weather_provider="open-meteo", is_manual=1)
    result = run_nightly(..., dry_run=True)
    assert result["reason"].startswith("Skipped")
    mock_growatt.set_charge_soc.assert_not_called()
    mock_weather.get_forecast.assert_not_called()


def test_run_nightly_dry_run_weather_failure_uses_fallback_without_setting(tmp_path, config, monkeypatch):
    # as test_orchestrator_weather_failure_falls_back, plus dry_run=True;
    # neutralise the retry backoff the way test_orchestrator_weather_retry_backoff_does_not_indexerror
    # does: `import time as _time; monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)`
    assert result["charge_level"] == config.battery.fallback_charge_level
    assert result["dry_run"] is True
    mock_growatt.set_charge_soc.assert_not_called()
    assert get_decision(conn, date(2026, 7, 15)) is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -k dry_run -v`
Expected: 4 FAIL with `TypeError: run_nightly() got an unexpected keyword argument 'dry_run'` (or `KeyError: 'dry_run'` for the default test).

- [ ] **Step 3: Add `dry_run: bool = False` to `run_nightly` in `src/orchestrator.py`**

Guard the three side effects (`growatt_client.set_charge_soc(...)`, `upsert_decision(...)`, `_write_last_updated(...)`) with `if not dry_run:`. Add `"dry_run": dry_run` to both returned dicts (the early-return for a manual decision and the normal result). Leave `_backfill_actuals`, `get_current_soc` and the forecast fetch unguarded.

- [ ] **Step 4: Run the orchestrator tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all PASS, including the pre-existing tests.

- [ ] **Step 5: Add the flag to `scripts/nightly-charge.py`**

Use `argparse` with a single `--dry-run` store-true argument. Pass `dry_run=args.dry_run` to `run_nightly`. On success print `DRY RUN: would set charge to {level}% for {date}` when dry-run, else the existing `Set charge to ...` line. Failure handling unchanged (print `FAILED: ...` to stderr, exit 1).

- [ ] **Step 6: Verify the script parses the flag**

Run: `python scripts/nightly-charge.py --help`
Expected: usage text listing `--dry-run`, exit 0. (A real run needs Growatt credentials and is exercised in Task 6.)

- [ ] **Step 7: Run the whole suite and commit**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

```bash
git add src/orchestrator.py scripts/nightly-charge.py tests/test_orchestrator.py
git commit -m "feat: add --dry-run to the nightly charge job"
```

---

### Task 2: Wrapper script, gitignore and README

**Confidence:** 95%. Spike on 2026-10-24 inside a Python-enabled agent image behind the OneCLI proxy: `pip install requests httpx growattServer` succeeds with no extra settings; `httpx` reaches Open-Meteo as-is; `requests` fails with `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` until `REQUESTS_CA_BUNDLE=$SSL_CERT_FILE` is set, after which Growatt answers 200. The proxy terminates TLS for every host, so the CA exports in the wrapper are required, not optional.

**Files:**
- Create: `scripts/run-nightly.sh`
- Modify: `.gitignore` (line `.venv/`)
- Modify: `README.md` (section `### Scheduling`, lines 110–112)

**Interfaces:**
- Consumes: `scripts/nightly-charge.py [--dry-run]` from Task 1.
- Produces: `scripts/run-nightly.sh [args...]`, bash, exit status equals the Python script's exit status (or non-zero if venv creation or `pip install` fails). It always runs from the project root regardless of the caller's working directory. It appends a header line `=== <ISO-8601 timestamp> run-nightly <args> ===` followed by the script's combined stdout and stderr to `data/nightly.log`, and prints the script's final output line to its own stdout so a caller can read it. Venv location: `<project-root>/.venv`. Before running Python it exports `REQUESTS_CA_BUNDLE`, `PIP_CERT` and `CURL_CA_BUNDLE` to the value of `SSL_CERT_FILE` when that variable is set and non-empty (NanoClaw sets it to the gateway's combined CA bundle; `requests` and `pip` do not read `SSL_CERT_FILE` themselves).

- [ ] **Step 1: Write the wrapper**

`#!/usr/bin/env bash`, `set -uo pipefail`. Resolve `PROJECT_ROOT` from `${BASH_SOURCE[0]}`. Venv step: `python3 -m venv "$PROJECT_ROOT/.venv" && "$PROJECT_ROOT/.venv/bin/pip" install -q -r requirements.txt`, only when `.venv/bin/python` is missing; on failure write the pip output to the log and `exit 1`. Run step: pipe the script through `tee -a data/nightly.log`, capture the exit status from `PIPESTATUS[0]`, print the last line of the captured output, exit with that status. Make it executable (`chmod +x`, and `git update-index --chmod=+x` so the bit survives the Windows checkout).

- [ ] **Step 2: Verify the wrapper from another directory with a stub interpreter (Git Bash on Windows)**

Create a temporary copy of the project in `%TEMP%` with a fake `scripts/nightly-charge.py` that prints `Set charge to 42% for 2026-10-25` and exits 0, and a pre-made `.venv/bin/python` shim that is a shell script running the system `python` (so no real venv is created). From `C:\` run:

```
bash "<copy>/scripts/run-nightly.sh"; echo "exit=$?"
```

Expected: stdout is `Set charge to 42% for 2026-10-25`, `exit=0`, and `<copy>/data/nightly.log` ends with a `=== ... run-nightly ===` header followed by that line.

- [ ] **Step 3: Verify the pip-failure path**

In the same copy, delete `.venv`, replace `requirements.txt` with the single line `this-package-does-not-exist-xyz==9.9.9`, run the wrapper again.
Expected: exit code 1, no `Set charge` line, and the log's last lines contain pip's "No matching distribution" error.

- [ ] **Step 4: Update `.gitignore` and README**

Change `.venv/` to `.venv*/`. Replace the `### Scheduling` paragraph with a short "Running under NanoClaw" section: where the project lives in Ubuntu, that `scripts/run-nightly.sh` is what the NanoClaw task calls, that `--dry-run` rehearses without setting the inverter, that the dashboard runs as the `weathertobattery-dashboard` systemd user service, and that the old Windows task is retired. Keep it under 20 lines.

- [ ] **Step 5: Commit**

```bash
git add scripts/run-nightly.sh .gitignore README.md
git commit -m "feat: add run-nightly.sh wrapper for NanoClaw and document the setup"
```

---

### Task 3: Move the project into Ubuntu and run the dashboard there

**Confidence:** 92%. Host Python is 3.14; `requirements.txt` pins only lower bounds, so wheels should resolve, and the check in Step 3 proves it.

**Files:**
- Create (Ubuntu): `/home/gethi/weathertobattery` (git clone), `~/.config/systemd/user/weathertobattery-dashboard.service`
- Copy (Windows → Ubuntu): `config.yaml`, `.env`, `data/` from `C:\Users\gethi\sources\weathertobattery`
- Helper (Windows): a script under `C:\Users\gethi\AppData\Local\Temp\` that performs the Ubuntu steps, run through `wsl.exe -d Ubuntu -u gethi -- bash /mnt/c/...`

**Interfaces:**
- Consumes: the branch from Tasks 1–2 pushed to `origin` (`emp3thy/weathertobattery`), so the Ubuntu clone can check it out. If the branch is not pushed, clone `main` and `git fetch origin <branch>` once it is.
- Produces: `/home/gethi/weathertobattery` on the feature branch with `config.yaml`, `.env`, `data/battery.db` present; `~/weathertobattery/.venv-host`; the dashboard service active and answering on `127.0.0.1:8099`.

- [ ] **Step 1: Push the branch and record the Windows database row counts**

```bash
git push -u origin nanoclaw-nightly-run
python -c "import sqlite3;c=sqlite3.connect('data/battery.db');print([ (t,c.execute(f'select count(*) from {t}').fetchone()[0]) for t in ('decisions','actuals','readings')])"
```
Expected: push succeeds; note the three counts.

- [ ] **Step 2: Clone and copy in Ubuntu**

In the helper script: `git clone https://github.com/emp3thy/weathertobattery.git ~/weathertobattery && cd ~/weathertobattery && git checkout nanoclaw-nightly-run`; then `cp /mnt/c/Users/gethi/sources/weathertobattery/config.yaml .`, `cp /mnt/c/Users/gethi/sources/weathertobattery/.env .`, `mkdir -p data && cp /mnt/c/Users/gethi/sources/weathertobattery/data/battery.db /mnt/c/Users/gethi/sources/weathertobattery/data/*.log data/`; `chmod 600 .env`.
Verify: `ls -la ~/weathertobattery/{config.yaml,.env,data}` lists all three, and the row-count one-liner from Step 1 run with `python3` prints the same counts.

- [ ] **Step 3: Create the host venv and run the test suite there**

```bash
cd ~/weathertobattery && python3 -m venv .venv-host && .venv-host/bin/pip install -q -r requirements.txt pytest && .venv-host/bin/python -m pytest tests/ -q
```
Expected: pip finishes without error; all tests PASS on Python 3.14.

- [ ] **Step 4: Install and start the dashboard service**

Unit file `~/.config/systemd/user/weathertobattery-dashboard.service`:

```ini
[Unit]
Description=weatherToBattery dashboard
After=default.target

[Service]
WorkingDirectory=/home/gethi/weathertobattery
ExecStart=/home/gethi/weathertobattery/.venv-host/bin/python run_dashboard.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload && systemctl --user enable --now weathertobattery-dashboard`.
Verify: `systemctl --user is-active weathertobattery-dashboard` prints `active`; `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/` prints `200`.

- [ ] **Step 5: Verify from Windows**

Run in PowerShell: `(Invoke-WebRequest http://localhost:8099/ -UseBasicParsing).StatusCode`
Expected: `200`. Open `http://localhost:8099/history` in the browser and confirm the most recent decision date matches the Windows dashboard's.

- [ ] **Step 6: Commit nothing; record completion**

No repository change in this task. Note the counts and the service status in the task's completion message.

---

### Task 4: Disable the Windows scheduled task

**Confidence:** 98%

**Files:** none (Windows Task Scheduler state only)

**Interfaces:**
- Produces: the task "WeatherToBattery Nightly" in state `Disabled`. Nothing on Windows will touch the inverter or the old database from here on.

- [ ] **Step 1: Disable**

PowerShell: `Disable-ScheduledTask -TaskName 'WeatherToBattery Nightly' | Select-Object TaskName, State`
Expected: `State: Disabled`.

- [ ] **Step 2: Confirm nothing else schedules the script**

PowerShell: `Get-ScheduledTask | Where-Object { $_.Actions.Arguments -match 'weathertobattery' } | Select-Object TaskName, State`
Expected: only the disabled task.

---

### Task 5: Provision the Battery Scheduler agent group

**Confidence:** 93%. Every command here was exercised by spike on 2026-10-24; the only new element is the standing-instructions file.

**Files:**
- Create (Ubuntu): `~/nanoclaw/groups/battery-scheduler/instructions.prepend.md`
- Modify (Ubuntu): `~/.config/nanoclaw/mount-allowlist.json` (via setup step), `container_configs` row in `~/nanoclaw/data/v2.db` (via `scripts/q.ts`)
- Helper (Windows): a script under `C:\Users\gethi\AppData\Local\Temp\` run through `wsl.exe -d Ubuntu -u gethi -- bash /mnt/c/...`; all `ncl` calls run from `~/nanoclaw` with `~/.local/bin` on `PATH`.

**Interfaces:**
- Consumes: `/home/gethi/weathertobattery` from Task 3.
- Produces: agent group id `$GID` (capture from `ncl groups list`), recorded in the completion message for Task 6; derived image `nanoclaw-agent-v2-479b04f8:$GID` containing `python3`; mount `/home/gethi/weathertobattery` → `/workspace/extra/weathertobattery` read-write; destination `owner-dm`.

- [ ] **Step 1: Create the group and add Python**

```bash
ncl groups create --folder battery-scheduler --name "Battery Scheduler"
GID=$(ncl groups list | awk '/battery-scheduler/ {print $1}')
ncl groups config add-package --id "$GID" --apt python3
ncl groups config add-package --id "$GID" --apt python3-venv
ncl groups restart --id "$GID" --rebuild
```
Expected: the last command prints `"rebuilt": true`; `docker images` lists `nanoclaw-agent-v2-479b04f8:$GID`.

- [ ] **Step 2: Allowlist and mount**

```bash
pnpm exec tsx setup/index.ts --step mounts --force -- --json '{"allowedRoots":[{"path":"/home/gethi/weathertobattery","allowReadWrite":true,"description":"weatherToBattery project (nightly job writes battery.db)"}],"blockedPatterns":[]}'
ncl groups config add-mount --id "$GID" --host /home/gethi/weathertobattery --container weathertobattery
pnpm exec tsx scripts/q.ts data/v2.db "update container_configs set additional_mounts='[{\"hostPath\":\"/home/gethi/weathertobattery\",\"containerPath\":\"weathertobattery\",\"readonly\":false}]' where agent_group_id='$GID'"
pnpm exec tsx scripts/q.ts data/v2.db "select additional_mounts from container_configs where agent_group_id='$GID'"
```
Expected: the select prints the JSON with `"readonly":false`.

- [ ] **Step 3: Destination and standing instructions**

```bash
ncl destinations add --agent-group-id "$GID" --local-name owner-dm --target-type channel --target-id mg-1792842294323-af0eto
```
Write `~/nanoclaw/groups/battery-scheduler/instructions.prepend.md` (the file NanoClaw composes into the group's `CLAUDE.md`; create it if the group folder does not have one yet):

```markdown
# Battery Scheduler

You exist to run one scheduled job and report its result. Your only
mount is the weatherToBattery project at /workspace/extra/weathertobattery.

Rules:
- Run only the command the task gives you. Do not retry it.
- Report exactly what the task asks for, to the destination `owner-dm`,
  quoting the script's own output. Never paraphrase a charge level.
- Never edit config.yaml, .env, data/battery.db or anything else in the
  mount. Never install packages. Never decide a charge level yourself.
```

Then `ncl groups restart --id "$GID"`.
Verify: `ncl destinations list --agent-group-id "$GID"` shows `owner-dm` → `slack`; `ncl wirings list | grep -c "$GID"` prints `0`.

- [ ] **Step 4: Prove the mount from inside a container**

One-off task: `ncl tasks create --group "$GID" --name mount-check --process-after "<now + 2 min>" --prompt "Run exactly: ls -la /workspace/extra/weathertobattery/scripts /workspace/extra/weathertobattery/data && touch /workspace/extra/weathertobattery/data/.nanoclaw-mount-ok && echo MOUNT_RW_OK. Reply only with the raw output. Do not send any message to any destination."`, then `ncl tasks run --id <task-id> --group "$GID"`.
Expected within two minutes: `ls -la ~/weathertobattery/data/.nanoclaw-mount-ok` exists on the host, owned by `gethi`; the task's `recent_log` contains `MOUNT_RW_OK`. Then `rm ~/weathertobattery/data/.nanoclaw-mount-ok` and `ncl tasks delete --id <task-id> --group "$GID"`.

---

### Task 6: Rehearse with `--dry-run`, then schedule the real task

**Confidence:** 95%. Every component was exercised by spike on 2026-10-24: the derived image, the writable mount, delivery to an unwired destination, PyPI and the Growatt and Open-Meteo hosts through the proxy from Python (with the CA exports Task 2 adds). What remains untested is only the full script against the real inverter, which Step 1's dry run covers before anything is scheduled.

**Files:**
- Create (NanoClaw state): recurring task `nightly-charge` on group `$GID`
- Modify (Ubuntu): `~/weathertobattery/data/nightly.log` (by the run), `~/weathertobattery/.venv` (created by the wrapper)

**Interfaces:**
- Consumes: group `$GID`, mount and destination from Task 5; wrapper from Task 2 present in the Ubuntu clone (pull the branch in `~/weathertobattery` first if Task 2 landed after Task 3's clone).
- Produces: the live schedule. Task prompt text (exact):

> Run `bash /workspace/extra/weathertobattery/scripts/run-nightly.sh` and note its exit status. Then send ONE message to the destination `owner-dm`. If the exit status was 0, send exactly the script's final output line prefixed with "Battery: ". If it was not 0, send "Battery run FAILED (exit N)" followed by the last 15 lines of `/workspace/extra/weathertobattery/data/nightly.log`. Do not retry, do not change any file, do not interpret or summarise the output.

- [ ] **Step 1: Dry-run rehearsal**

Create a one-off task with the prompt above but with `run-nightly.sh --dry-run` in the command and `--process-after "<now + 2 min>"`, then `ncl tasks run` it. The first run also creates the container venv, so allow up to five minutes.
Expected: a Slack DM `Battery: DRY RUN: would set charge to NN% for YYYY-MM-DD`; `~/weathertobattery/.venv/bin/python` exists; `data/nightly.log` ends with the header and that line; the `decisions` row count is unchanged; the Growatt portal shows no change.

- [ ] **Step 2: Negative rehearsal**

Edit `~/weathertobattery/.env` to append `x` to `GROWATT_PASSWORD`, run the same dry-run task again with `ncl tasks run`, then restore the password.
Expected: a Slack DM starting `Battery run FAILED (exit 1)` with a `Login failed` line in the quoted log tail; the `decisions` row count is unchanged.

- [ ] **Step 3: Delete the rehearsal task and create the real schedule**

```bash
ncl tasks delete --id <rehearsal-task-id> --group "$GID"
ncl tasks create --group "$GID" --name nightly-charge --recurrence "0 22 * * *" --prompt "<exact prompt above>"
ncl tasks get --id nightly-charge-<hex> --group "$GID"
```
Expected: `recurrence` is `0 22 * * *` and `process_after` is today or tomorrow at `22:00` local.

- [ ] **Step 4: Record the first real run**

After the first 22:00: `ncl tasks get --id <id> --group "$GID"` shows `completed_runs: 1`, Slack has a `Battery: Set charge to NN% for <tomorrow>` line, `decisions` has a new row for tomorrow, and the dashboard's Overview shows it. If the run did not happen by 23:30, read `~/nanoclaw/logs/nanoclaw.error.log` and the task's `recent_log` before anything else.

---

### Task 7: Finish the cutover

**Confidence:** 95%

**Files:**
- Delete (Windows): scheduled task "WeatherToBattery Nightly"
- Modify: none in the repository beyond merging the branch

**Interfaces:**
- Consumes: two consecutive successful nightly runs from Task 6.

- [ ] **Step 1: Confirm two good nights**

`ncl tasks get --id <id> --group "$GID"` shows `completed_runs >= 2` and `failed_runs: 0`; two `Battery:` lines in Slack on consecutive evenings.

- [ ] **Step 2: Delete the Windows task**

PowerShell: `Unregister-ScheduledTask -TaskName 'WeatherToBattery Nightly' -Confirm:$false`
Expected: `Get-ScheduledTask -TaskName 'WeatherToBattery Nightly'` now errors with "No MSFT_ScheduledTask objects found".

- [ ] **Step 3: Merge the branch**

Use `superpowers:finishing-a-development-branch` for `nanoclaw-nightly-run` (Tasks 1–2 are the only code changes). After merging, `git pull` in `~/weathertobattery` and `git checkout main` there so the Ubuntu clone tracks `main`.
