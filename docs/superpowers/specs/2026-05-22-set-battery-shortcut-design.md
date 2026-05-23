# Set-Battery Shortcut Design

**Date:** 2026-05-22
**Status:** Approved

## Problem

The current way to force a specific charge level requires editing `config.yaml` (setting `manual_override`), running the full nightly orchestrator (which fetches weather, runs the calculator, backfills yesterday's actuals, reads current SOC), then letting the orchestrator auto-clear the override. For ad-hoc situations like "I need a full charge for 10AM tomorrow because of pool heating," this round-trip is too heavy. The user wants a single shortcut: say a percentage, have the battery set.

## Solution

Add a thin manual path alongside the existing nightly path. A new orchestrator function `run_manual(level, ...)` logs in to Growatt, sets the charge level, writes a decision row to the database tagged as manual, and updates `last_updated.md`. A new Claude skill `set-battery` invokes it. The nightly run learns to skip dates that already have a manual decision row. The existing `manual_override` config mechanism is removed.

## Changes

### Database schema (`src/db/schema.py`)

Add an `is_manual` column to the `decisions` table:

```sql
ALTER TABLE decisions ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0;
```

Added inline in `_migrate()`, following the existing `ALTER TABLE` pattern. Existing rows default to `0`.

### Queries (`src/db/queries.py`)

`upsert_decision` gains an `is_manual: int = 0` parameter (default 0 so existing callers — `run_nightly` — need no change). `get_decision` already returns a `Row` whose mapping reflects all columns; no code change needed there.

### Orchestrator (`src/orchestrator.py`)

**Remove:**
- The `if config.manual_override is not None:` branch inside `run_nightly`.
- The `_clear_manual_override(config_path)` helper.

**Add a skip check at the top of `run_nightly`** (after `_backfill_actuals`, before `get_current_soc`):

```python
existing = get_decision(conn, target_date)
if existing and existing["is_manual"] == 1:
    logger.info(f"Skipping {target_date} — manual setting already in place")
    return {
        "success": True,
        "charge_level": existing["charge_level_set"],
        "reason": f"Skipped — manual already set ({existing['charge_level_set']}%)",
        "target_date": str(target_date),
        "timestamp": datetime.now().isoformat(),
        "errors": [],
    }
```

The skip happens after the actuals backfill (which is about yesterday and remains useful) and before any work targeting the decision date. `last_updated.md` is not rewritten on skip — the existing manual entry stays visible.

**Add a new function `run_manual`:**

```python
def run_manual(
    config: Config, conn, growatt_client: GrowattClient,
    level: int, target_date: date, project_root: Path,
) -> dict:
    timestamp = datetime.now().isoformat()
    errors = []

    try:
        growatt_client.set_charge_soc(level)
    except Exception as e:
        logger.error(f"Failed to set charge: {e}")
        errors.append(f"Failed to set charge: {e}")
        return {
            "success": False,
            "charge_level": None,
            "reason": f"Manual set to {level}% failed",
            "target_date": str(target_date),
            "timestamp": timestamp,
            "errors": errors,
        }

    reason = f"Manual: set to {level}%"
    try:
        upsert_decision(
            conn, target_date,
            forecast_summary="manual",
            forecast_detail="[]",
            charge_level_set=level,
            adjustment_reason=reason,
            current_soc=None,
            month=target_date.month,
            weather_provider="manual",
            is_manual=1,
        )
    except Exception as e:
        logger.error(f"Failed to log decision: {e}")
        errors.append(f"Failed to log decision: {e}")

    result = {
        "success": len(errors) == 0,
        "charge_level": level,
        "reason": reason,
        "target_date": str(target_date),
        "timestamp": timestamp,
        "errors": errors,
    }

    _write_last_updated(project_root, result, forecast=None)
    return result
```

Failure semantics:
- Hardware set fails → no DB row, no `last_updated.md` write, returns `success=False`.
- Hardware set succeeds, DB write fails → `last_updated.md` is still written (reflects reality that the battery *was* set), `success=False`, error in `errors` list.
- DB write succeeds, `last_updated.md` write fails → propagates (the write helper raises on filesystem failure; that's existing behaviour).

### Config (`src/config.py`, `config.yaml`, `config.example.yaml`)

- Remove `manual_override` field from `Config`.
- Remove `manual_override: null` line from `config.yaml` and `config.example.yaml`.

### Skill: `~/.claude/skills/set-battery/SKILL.md` (new)

Frontmatter:

```yaml
---
name: set-battery
description: Set the Growatt battery charge level for tomorrow to a specific percentage, bypassing the weather-based calculator. Use when the user says "set battery to N%", "set the battery to N", "force tomorrow's charge to N%", or similar direct-set phrasing.
---
```

Body steps:
1. Parse the percentage from the user's message. If the parsed value is not an integer in `1..100`, ask the user for a valid percentage and stop.
2. Run:
   ```bash
   python -c "
   from datetime import date, timedelta
   from pathlib import Path
   from src.config import load_config
   from src.db.schema import init_db
   from src.growatt.client import GrowattClient
   from src.orchestrator import run_manual

   LEVEL = $1
   config = load_config(Path('config.yaml'))
   conn = init_db(Path('data/battery.db'))
   growatt = GrowattClient(config.growatt, rates=config.rates)
   growatt.login()
   tomorrow = date.today() + timedelta(days=1)
   result = run_manual(config, conn, growatt, LEVEL, tomorrow, Path('.'))
   conn.close()
   print(result)
   "
   ```
3. Read `last_updated.md` and summarise: "Battery set to N% for tomorrow YYYY-MM-DD. The nightly calculator will skip this date."

### Skill: `~/.claude/skills/charge-battery/SKILL.md` (update)

Replace the existing `## Override` section with a single line:

> For a manual override, use the `set-battery` skill instead.

## Testing

New tests in `tests/test_orchestrator.py`. They follow the existing pattern (pytest, `MagicMock` for Growatt, `tmp_path` for the DB and project root).

**1. `test_run_manual_sets_charge_and_logs_decision`**
- Call `run_manual(config, conn, mock_growatt, 80, tomorrow, tmp_path)`.
- Assert `mock_growatt.set_charge_soc.assert_called_once_with(80)`.
- Assert `get_decision(conn, tomorrow)["charge_level_set"] == 80`, `["is_manual"] == 1`, `["adjustment_reason"] == "Manual: set to 80%"`.
- Assert `last_updated.md` exists and contains `"Charge level set: 80%"`.
- Assert `mock_growatt.get_hourly_data` was NOT called and `mock_growatt.get_current_soc` was NOT called — proves we skipped the heavy path.

**2. `test_nightly_skips_when_manual_already_set`**
- Pre-insert a decision row for `target_date` with `is_manual=1`, `charge_level_set=75`.
- Run `run_nightly` with `mock_weather` and `mock_growatt`.
- Assert `mock_weather.get_forecast` was NOT called.
- Assert `mock_growatt.set_charge_soc` was NOT called.
- Assert `result["charge_level"] == 75` and `"skipped" in result["reason"].lower()`.
- Assert `mock_growatt.get_hourly_data` WAS called — actuals backfill is independent and still runs.

**3. `test_run_manual_hardware_failure_does_not_write_db`**
- `mock_growatt.set_charge_soc.side_effect = GrowattError("boom")`.
- Call `run_manual(..., 80, ...)`.
- Assert `get_decision(conn, tomorrow) is None`.
- Assert `result["success"] is False` and the error message appears in `result["errors"]`.
- Assert `last_updated.md` is unchanged (compare against a sentinel written beforehand).

**4. `test_run_manual_second_call_overwrites_first`**
- Call `run_manual(..., 50, ...)` then `run_manual(..., 90, ...)` for the same date.
- Assert the final decision row has `charge_level_set == 90` and `is_manual == 1`.

## Out of scope

- A "clear manual marker" command to hand a date back to the calculator. Re-invoking `set-battery` with a different level is the only override mechanism in v1.
- Setting today's charge (the shortcut always targets tomorrow, matching the nightly run).
- Concurrency safety between a manual call and the nightly cron firing simultaneously. SQLite WAL plus the PRIMARY KEY upsert handle this acceptably; in practice the two are never invoked together.
- Unit testing the SKILL.md file. Skill content is markdown that drives Claude's natural-language behaviour; correctness is verified manually.
- Unit testing the schema migration. The migration follows the same one-line ALTER pattern used for all other column additions and is not separately tested elsewhere.
