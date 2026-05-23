# Set-Battery Shortcut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast "set the battery to N%" path that bypasses the weather-based calculator, and remove the existing `manual_override` config mechanism.

**Architecture:** A new `run_manual()` function in `src/orchestrator.py` logs in to Growatt (caller's responsibility), sets the charge level, writes a decision row tagged as manual (new `is_manual` column on the `decisions` table), and updates `last_updated.md`. The nightly `run_nightly()` checks for an existing manual decision on the target date and skips if found. The existing `manual_override` field in `Config`, the orchestrator's manual-override branch, the calculator's manual-override branch, and the related test are all removed.

**Tech Stack:** Python 3.11+, sqlite3 (WAL mode), pytest with `unittest.mock.MagicMock`, PyYAML.

**Spec:** `docs/superpowers/specs/2026-05-22-set-battery-shortcut-design.md`

---

## Confidence ratings

Each step is rated for execution confidence (probability that following the step verbatim succeeds without rework). All steps in this plan are ≥92%. The three steps initially below 95% were lifted in-place:

| Step | Original | Lifted | Lift applied |
|---|---|---|---|
| Task 6 Step 1 (skip test) | 90% | 95% | Annotated test setup to make the backfill side-effect explicit and confirmed `mock_growatt.get_hourly_data.return_value = {}` is sufficient. |
| Task 7 Step 3 (orchestrator restructure) | 92% | 96% | Replaced narrative diff with an exact pre/post code block including correct indent levels. |
| Task 8 Step 1 (skill `$1` placeholder) | 90% | 95% | Replaced `$1` with explicit `<PERCENTAGE>` placeholder + instruction for Claude to substitute the literal integer. |

## Assumptions

**Real concerns (require user decision):** *none — all design choices were locked during brainstorming.*

**Verified-safe (checked at plan-write time):**
- `ALTER TABLE … ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0` is valid on existing SQLite rows (the DEFAULT clause is what permits NOT NULL on an ALTER).
- Growatt retry behaviour: `set_charge_soc` already retries 3× with `(5,15,45)` backoff inside `GrowattClient._retry`; the manual path inherits this without change.
- All imports referenced in test code (`run_manual`, `run_nightly`, `upsert_decision`, `get_decision`, `GrowattError`, `init_db`) exist in the cited modules — verified by grep.
- `_write_last_updated(path, result, forecast=None)` signature matches the call in `run_manual`.
- `sqlite3.Row["column_name"]` dict-style access is already used elsewhere in the codebase (`get_decision`, `_backfill_actuals`).

**Minor accepted:**
- Skill content is duplicated in `skills/` and `.claude/commands/` — matches the existing pattern for `charge-battery` and `battery-dashboard`.
- `manual_override` is removed in a single PR rather than soft-deprecated (user explicitly approved).
- No "clear manual marker" command in v1 — re-invoking `set-battery` with a new value is the only override.
- Skill-picker disambiguation between `charge-battery` and `set-battery` relies on the description text alone; mitigated by making `set-battery`'s description explicitly say "bypassing the weather-based calculator" and listing trigger phrases.

---

## File Structure

**Modified:**
- `src/db/schema.py` — add `is_manual` column ALTER in `_migrate()`
- `src/db/queries.py` — extend `upsert_decision` with `is_manual` parameter
- `src/orchestrator.py` — add `run_manual()`, add skip check in `run_nightly()`, remove `manual_override` branch, remove `_clear_manual_override()`
- `src/config.py` — remove `manual_override` field and validation
- `src/calculator/engine.py` — remove manual-override early-return
- `config.yaml`, `config.example.yaml` — remove `manual_override: null` line
- `tests/conftest.py` — remove `manual_override: null` from `VALID_CONFIG_YAML`
- `tests/test_config.py` — remove `manual_override`-related assertions and yaml lines
- `tests/test_calculator.py` — delete `test_manual_override`
- `tests/test_orchestrator.py` — add four new tests for `run_manual` and the nightly skip
- `skills/charge-battery.md`, `.claude/commands/charge-battery.md` — replace `## Override` section
- `README.md` — remove `manual_override` row from config table

**Created:**
- `skills/set-battery.md`, `.claude/commands/set-battery.md` — identical new skill file in both locations

---

## Task 1: Add `is_manual` column to `decisions` table

**Files:**
- Modify: `src/db/schema.py:36-60`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_decisions_has_is_manual_column_with_default_zero(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    # Insert a row using the *existing* signature (no is_manual parameter yet).
    # The column must exist and default to 0.
    upsert_decision(
        conn, date(2026, 5, 23),
        forecast_summary="sunny",
        forecast_detail="[]",
        charge_level_set=50,
        adjustment_reason="test",
        current_soc=20,
        month=5,
        weather_provider="open_meteo",
    )
    row = conn.execute(
        "SELECT is_manual FROM decisions WHERE date = ?",
        ("2026-05-23",),
    ).fetchone()
    assert row is not None
    assert row[0] == 0
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_db.py::test_decisions_has_is_manual_column_with_default_zero -v`

Expected: FAIL with `sqlite3.OperationalError: no such column: is_manual`.

- [ ] **Step 3: Add the ALTER in `_migrate()`**

In `src/db/schema.py`, inside `_migrate()`, after the existing `decisions_cols` block (around line 55, after the `base_charge_level` drop), add:

```python
    if "is_manual" not in decisions_cols:
        conn.execute(
            "ALTER TABLE decisions ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_db.py::test_decisions_has_is_manual_column_with_default_zero -v`

Expected: PASS.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest -x`

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/db/schema.py tests/test_db.py
git commit -m "feat: add is_manual column to decisions table"
```

---

## Task 2: Extend `upsert_decision` to accept `is_manual`

**Files:**
- Modify: `src/db/queries.py:5-24`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_upsert_decision_stores_is_manual_flag(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, get_decision
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    upsert_decision(
        conn, date(2026, 5, 23),
        forecast_summary="manual",
        forecast_detail="[]",
        charge_level_set=80,
        adjustment_reason="Manual: set to 80%",
        current_soc=None,
        month=5,
        weather_provider="manual",
        is_manual=1,
    )
    row = get_decision(conn, date(2026, 5, 23))
    assert row["is_manual"] == 1
    assert row["charge_level_set"] == 80
    assert row["adjustment_reason"] == "Manual: set to 80%"
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_db.py::test_upsert_decision_stores_is_manual_flag -v`

Expected: FAIL with `TypeError: upsert_decision() got an unexpected keyword argument 'is_manual'`.

- [ ] **Step 3: Update `upsert_decision`**

Replace the body of `src/db/queries.py:5-24` with:

```python
def upsert_decision(conn: sqlite3.Connection, dt: date, forecast_summary: str,
                    forecast_detail: str, charge_level_set: int,
                    adjustment_reason: str | None, current_soc: int | None,
                    month: int, weather_provider: str,
                    is_manual: int = 0) -> None:
    conn.execute("""
        INSERT INTO decisions (date, forecast_summary, forecast_detail,
            charge_level_set, adjustment_reason, current_soc_at_decision, month,
            weather_provider_used, is_manual)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            forecast_summary=excluded.forecast_summary,
            forecast_detail=excluded.forecast_detail,
            charge_level_set=excluded.charge_level_set,
            adjustment_reason=excluded.adjustment_reason,
            current_soc_at_decision=excluded.current_soc_at_decision,
            month=excluded.month,
            weather_provider_used=excluded.weather_provider_used,
            is_manual=excluded.is_manual
    """, (str(dt), forecast_summary, forecast_detail, charge_level_set,
          adjustment_reason, current_soc, month, weather_provider, is_manual))
    conn.commit()
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest tests/test_db.py::test_upsert_decision_stores_is_manual_flag -v`

Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -x`

Expected: all tests pass (default `is_manual=0` keeps existing callers compatible).

- [ ] **Step 6: Commit**

```bash
git add src/db/queries.py tests/test_db.py
git commit -m "feat: extend upsert_decision with is_manual parameter"
```

---

## Task 3: Implement `run_manual()` happy path

**Files:**
- Modify: `src/orchestrator.py` (add new function near the bottom)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_run_manual_sets_charge_and_logs_decision(tmp_path, config):
    from src.orchestrator import run_manual
    from src.db.schema import init_db
    from src.db.queries import get_decision
    from unittest.mock import MagicMock
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    mock_growatt = MagicMock()
    mock_growatt.set_charge_soc.return_value = True

    target = date(2026, 5, 23)
    result = run_manual(
        config=config, conn=conn, growatt_client=mock_growatt,
        level=80, target_date=target, project_root=tmp_path,
    )

    assert result["success"] is True
    assert result["charge_level"] == 80
    assert result["target_date"] == "2026-05-23"

    mock_growatt.set_charge_soc.assert_called_once_with(80)
    # Heavy path skipped:
    mock_growatt.get_hourly_data.assert_not_called()
    mock_growatt.get_current_soc.assert_not_called()

    decision = get_decision(conn, target)
    assert decision is not None
    assert decision["charge_level_set"] == 80
    assert decision["is_manual"] == 1
    assert decision["adjustment_reason"] == "Manual: set to 80%"
    assert decision["forecast_summary"] == "manual"

    last_updated = (tmp_path / "last_updated.md").read_text()
    assert "Charge level set: 80%" in last_updated
    assert "Manual: set to 80%" in last_updated
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_run_manual_sets_charge_and_logs_decision -v`

Expected: FAIL with `ImportError: cannot import name 'run_manual' from 'src.orchestrator'`.

- [ ] **Step 3: Implement `run_manual()`**

In `src/orchestrator.py`, add at the bottom of the file (after `run_nightly`):

```python
def run_manual(
    config: Config, conn, growatt_client: GrowattClient,
    level: int, target_date: date, project_root: Path,
) -> dict:
    timestamp = datetime.now().isoformat()
    errors = []

    growatt_client.set_charge_soc(level)

    reason = f"Manual: set to {level}%"
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

    result = {
        "success": True,
        "charge_level": level,
        "reason": reason,
        "target_date": str(target_date),
        "timestamp": timestamp,
        "errors": errors,
    }

    _write_last_updated(project_root, result, forecast=None)
    return result
```

(This is the minimal happy-path version. Task 4 will add the error-handling for hardware failure.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_orchestrator.py::test_run_manual_sets_charge_and_logs_decision -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add run_manual happy path"
```

---

## Task 4: Add error handling to `run_manual()` for hardware failure

**Files:**
- Modify: `src/orchestrator.py` (the `run_manual` function added in Task 3)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_run_manual_hardware_failure_does_not_write_db(tmp_path, config):
    from src.orchestrator import run_manual
    from src.db.schema import init_db
    from src.db.queries import get_decision
    from src.growatt.client import GrowattError
    from unittest.mock import MagicMock
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    # Pre-write last_updated.md so we can detect whether it was overwritten.
    sentinel = "SENTINEL — must not be overwritten on failure\n"
    (tmp_path / "last_updated.md").write_text(sentinel)

    mock_growatt = MagicMock()
    mock_growatt.set_charge_soc.side_effect = GrowattError("boom")

    target = date(2026, 5, 23)
    result = run_manual(
        config=config, conn=conn, growatt_client=mock_growatt,
        level=80, target_date=target, project_root=tmp_path,
    )

    assert result["success"] is False
    assert any("boom" in e for e in result["errors"])

    assert get_decision(conn, target) is None
    assert (tmp_path / "last_updated.md").read_text() == sentinel
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_run_manual_hardware_failure_does_not_write_db -v`

Expected: FAIL — the unhandled `GrowattError` propagates out of `run_manual`.

- [ ] **Step 3: Add the try/except + early return**

Replace the body of `run_manual` in `src/orchestrator.py` with:

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

Also, add this import at the top of `src/orchestrator.py` if it isn't already there:

```python
from .db.queries import (
    upsert_decision, get_decision, get_actuals, insert_actuals
)
```

(`upsert_decision` is already imported in the existing file; the line above is the existing one. No change needed if so.)

- [ ] **Step 4: Run both run_manual tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -k run_manual -v`

Expected: both `test_run_manual_sets_charge_and_logs_decision` and `test_run_manual_hardware_failure_does_not_write_db` PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: handle hardware failure in run_manual without writing DB"
```

---

## Task 5: Verify `run_manual()` overwrites previous manual decision

**Files:**
- Test: `tests/test_orchestrator.py` (no production code changes — this captures upsert behaviour)

- [ ] **Step 1: Write the test**

Add to `tests/test_orchestrator.py`:

```python
def test_run_manual_second_call_overwrites_first(tmp_path, config):
    from src.orchestrator import run_manual
    from src.db.schema import init_db
    from src.db.queries import get_decision
    from unittest.mock import MagicMock
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    mock_growatt = MagicMock()
    target = date(2026, 5, 23)

    run_manual(config=config, conn=conn, growatt_client=mock_growatt,
               level=50, target_date=target, project_root=tmp_path)
    run_manual(config=config, conn=conn, growatt_client=mock_growatt,
               level=90, target_date=target, project_root=tmp_path)

    decision = get_decision(conn, target)
    assert decision["charge_level_set"] == 90
    assert decision["is_manual"] == 1
    assert decision["adjustment_reason"] == "Manual: set to 90%"
    # Both calls hit the hardware in order:
    assert mock_growatt.set_charge_soc.call_args_list == [
        ((50,),), ((90,),)
    ]
    conn.close()
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_orchestrator.py::test_run_manual_second_call_overwrites_first -v`

Expected: PASS (upsert via `ON CONFLICT(date) DO UPDATE` handles overwrite naturally).

- [ ] **Step 3: Commit**

```bash
git add tests/test_orchestrator.py
git commit -m "test: verify run_manual second call overwrites first"
```

---

## Task 6: Skip `run_nightly()` when manual decision exists for target date

**Files:**
- Modify: `src/orchestrator.py:154-170` (top of `run_nightly`, after `_backfill_actuals`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_nightly_skips_when_manual_already_set(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db
    from src.db.queries import upsert_decision
    from unittest.mock import MagicMock
    from datetime import date

    conn = init_db(tmp_path / "test.db")
    target = date(2026, 5, 23)
    # Pre-insert a manual decision for the target date.
    upsert_decision(
        conn, target,
        forecast_summary="manual",
        forecast_detail="[]",
        charge_level_set=75,
        adjustment_reason="Manual: set to 75%",
        current_soc=None,
        month=5,
        weather_provider="manual",
        is_manual=1,
    )

    mock_weather = MagicMock()
    mock_growatt = MagicMock()
    # The actuals table is empty for this tmp_path DB, so _backfill_actuals
    # WILL invoke get_hourly_data(yesterday). Return {} so the backfill loop
    # iterates over nothing and the test stays focused on the skip behaviour.
    mock_growatt.get_hourly_data.return_value = {}
    mock_growatt.get_current_soc.return_value = 30

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=target,
        project_root=tmp_path,
    )

    assert result["success"] is True
    assert result["charge_level"] == 75
    assert "skipped" in result["reason"].lower()
    # Heavy paths NOT taken:
    mock_weather.get_forecast.assert_not_called()
    mock_growatt.set_charge_soc.assert_not_called()
    # Backfill IS still attempted (it's about yesterday, not the target date):
    mock_growatt.get_hourly_data.assert_called()
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_nightly_skips_when_manual_already_set -v`

Expected: FAIL — `run_nightly` currently does not check for an existing manual row, so it will call `get_forecast` and/or `set_charge_soc`.

- [ ] **Step 3: Add the skip check in `run_nightly`**

In `src/orchestrator.py`, inside `run_nightly`, after the call to `_backfill_actuals(conn, growatt_client, config, target_date)` and before the SOC read block (`try: current_soc = growatt_client.get_current_soc()`), insert:

```python
    # Skip if a manual decision is already in place for the target date.
    existing = get_decision(conn, target_date)
    if existing and existing["is_manual"] == 1:
        logger.info(f"Skipping {target_date} — manual setting already in place")
        return {
            "success": True,
            "charge_level": existing["charge_level_set"],
            "reason": f"Skipped — manual already set ({existing['charge_level_set']}%)",
            "target_date": str(target_date),
            "timestamp": timestamp,
            "errors": [],
        }
```

(`get_decision` is already imported at the top of `src/orchestrator.py`.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_orchestrator.py::test_nightly_skips_when_manual_already_set -v`

Expected: PASS.

- [ ] **Step 5: Run all orchestrator tests**

Run: `pytest tests/test_orchestrator.py -v`

Expected: all PASS, including the existing `test_orchestrator_sets_charge_and_logs` (which uses a fresh DB with no pre-inserted manual row, so the skip branch is bypassed).

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: skip nightly when manual decision already set"
```

---

## Task 7: Remove the `manual_override` mechanism entirely

This task removes the old override path now that `run_manual` + `is_manual` cover the use case. Multiple files change together.

**Files:**
- Modify: `src/config.py:74-92` (Config dataclass + `_validate` + `load_config`)
- Modify: `src/calculator/engine.py:170-180` (remove early-return branch)
- Modify: `src/orchestrator.py` (remove manual-override branch in `run_nightly`, remove `_clear_manual_override`)
- Modify: `config.yaml` (remove `manual_override: null` line)
- Modify: `config.example.yaml` (remove `manual_override: null` line)
- Modify: `tests/conftest.py:28` (remove `manual_override: null` from `VALID_CONFIG_YAML`)
- Modify: `tests/test_config.py:29, 36, 66, 100` (remove `manual_override: null` lines and the related assertion)
- Modify: `tests/test_calculator.py:60-72` (delete `test_manual_override`)
- Modify: `README.md:64` (remove `manual_override` row from the config table)

- [ ] **Step 1: Remove `manual_override` from `Config` dataclass and validation**

In `src/config.py`:

Remove this line from the `Config` dataclass (line 81):
```python
    manual_override: int | None
```

Remove this validation block from `_validate` (lines 89-90):
```python
    if cfg.manual_override is not None and not (0 <= cfg.manual_override <= 100):
        raise ConfigValidationError("manual_override must be 0-100 or null")
```

Remove this line from `load_config` (line 121):
```python
        manual_override=raw.get("manual_override"),
```

- [ ] **Step 2: Remove the manual-override branch from the calculator**

In `src/calculator/engine.py`, remove lines 175-180:

```python
    # Manual override
    if config.manual_override is not None:
        return ChargeResult(
            charge_level=config.manual_override,
            reason="Manual override applied",
        )

```

- [ ] **Step 3: Remove the manual-override path and helper from the orchestrator**

In `src/orchestrator.py`:

Delete the `_clear_manual_override` function entirely (lines 111-117):

```python
def _clear_manual_override(config_path: Path) -> None:
    import yaml
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    raw["manual_override"] = None
    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)
```

Inside `run_nightly`, replace this block:

```python
    # Manual override
    if config.manual_override is not None:
        charge_level = config.manual_override
        reason = f"Manual override: {charge_level}%"
        try:
            _clear_manual_override(project_root / "config.yaml")
        except Exception as e:
            logger.warning(f"Failed to clear manual override: {e}")
    else:
        # Fetch forecast with retry
        _BACKOFF = (5, 15, 45)
        for attempt in range(3):
            try:
                forecast = weather_provider.get_forecast(
                    config.location.latitude, config.location.longitude,
                    target_date, config.location.timezone
                )
                break
            except Exception as e:
                if attempt == 2:
                    logger.error(f"Weather API failed after 3 retries: {e}")
                    errors.append(f"Weather API failed: {e}")
                    forecast = None
                else:
                    import time as time_module
                    time_module.sleep(_BACKOFF[attempt])

        if forecast is None:
            charge_level = config.battery.fallback_charge_level
            reason = f"Weather API unavailable — fallback to {charge_level}%"
        else:
            calc_result = calculate_charge(
                config=config, forecast=forecast, conn=conn,
            )
            charge_level = calc_result.charge_level
            reason = calc_result.reason
```

with:

```python
    # Fetch forecast with retry
    _BACKOFF = (5, 15, 45)
    for attempt in range(3):
        try:
            forecast = weather_provider.get_forecast(
                config.location.latitude, config.location.longitude,
                target_date, config.location.timezone
            )
            break
        except Exception as e:
            if attempt == 2:
                logger.error(f"Weather API failed after 3 retries: {e}")
                errors.append(f"Weather API failed: {e}")
                forecast = None
            else:
                import time as time_module
                time_module.sleep(_BACKOFF[attempt])

    if forecast is None:
        charge_level = config.battery.fallback_charge_level
        reason = f"Weather API unavailable — fallback to {charge_level}%"
    else:
        calc_result = calculate_charge(
            config=config, forecast=forecast, conn=conn,
        )
        charge_level = calc_result.charge_level
        reason = calc_result.reason
```

- [ ] **Step 4: Remove `manual_override: null` from `config.yaml` and `config.example.yaml`**

In both files, delete the line:
```yaml
manual_override: null
```

- [ ] **Step 5: Remove `manual_override` from test fixtures**

In `tests/conftest.py`, remove line 28 (`manual_override: null`) from `VALID_CONFIG_YAML`.

In `tests/test_config.py`:
- Remove `manual_override: null` lines at the four occurrences (use `Grep` to find them; remove the line, not surrounding lines).
- Remove the assertion `assert cfg.manual_override is None` (line 36).

- [ ] **Step 6: Delete `test_manual_override` from the calculator tests**

In `tests/test_calculator.py`, delete the entire `test_manual_override` function (lines 60-72):

```python
def test_manual_override(tmp_path, config):
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML.replace("manual_override: null", "manual_override: 85"))
    override_config = load_config(config_file)
    conn = _make_db(tmp_path)
    forecast = _make_forecast(date(2026, 6, 15))
    result = calculate_charge(config=override_config, forecast=forecast,
                              conn=conn)
    assert result.charge_level == 85
    assert "manual" in result.reason.lower()
```

- [ ] **Step 7: Update README**

In `README.md`, remove line 64:
```
| | `manual_override` | Set to 0-100 to force a specific charge level once, then auto-clears |
```

- [ ] **Step 8: Run the full test suite**

Run: `pytest -v`

Expected: all tests pass. If a test references `cfg.manual_override` or `manual_override:` in an inline YAML, fix it now (remove the reference). Re-grep to confirm nothing in `tests/` or `src/` still references `manual_override`:

```bash
grep -rn manual_override src tests config.yaml config.example.yaml README.md
```

Expected output: empty.

- [ ] **Step 9: Commit**

```bash
git add src/config.py src/calculator/engine.py src/orchestrator.py config.yaml config.example.yaml tests/conftest.py tests/test_config.py tests/test_calculator.py README.md
git commit -m "refactor: remove manual_override config mechanism, replaced by run_manual"
```

---

## Task 8: Create the `set-battery` skill files

**Files:**
- Create: `skills/set-battery.md`
- Create: `.claude/commands/set-battery.md`

- [ ] **Step 1: Write the skill content**

Both files get identical content. Write to `skills/set-battery.md`:

```markdown
---
name: set-battery
description: Set the Growatt battery charge level for tomorrow to a specific percentage, bypassing the weather-based calculator. Use when the user says "set battery to N%", "set the battery to N", "force tomorrow's charge to N%", or similar direct-set phrasing.
---

# Set Battery

Set tomorrow's Growatt battery charge level to a specific percentage. Skips the weather-based calculator entirely. The nightly run will detect this manual setting and skip recomputing for the same date.

## Steps

1. Parse the percentage from the user's message. The value MUST be an integer in the range `1..100`. If you cannot parse a percentage in that range, ask the user for one and stop.

2. Run the shortcut:

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
from datetime import date, timedelta
from pathlib import Path
from src.config import load_config
from src.db.schema import init_db
from src.growatt.client import GrowattClient
from src.orchestrator import run_manual

LEVEL = <PERCENTAGE>
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

Replace the `<PERCENTAGE>` placeholder with the integer you parsed from the user's message (no quotes, no `%` sign — just the bare number, e.g. `LEVEL = 80`).

3. Read `last_updated.md` and summarise in plain language: "Battery set to N% for tomorrow YYYY-MM-DD. The nightly calculator will skip this date."

4. If `result["success"]` is `False`, surface the errors from `result["errors"]` to the user instead of claiming success.
```

- [ ] **Step 2: Copy to `.claude/commands/set-battery.md`**

Both locations need the same content. Either copy the file, or create both manually with identical text.

```bash
cp skills/set-battery.md .claude/commands/set-battery.md
```

- [ ] **Step 3: Commit**

```bash
git add skills/set-battery.md .claude/commands/set-battery.md
git commit -m "feat: add set-battery skill for manual charge level shortcut"
```

---

## Task 9: Update `charge-battery` skill files to point at `set-battery`

**Files:**
- Modify: `skills/charge-battery.md` (the `## Override` section at the bottom)
- Modify: `.claude/commands/charge-battery.md` (same section)

- [ ] **Step 1: Replace the `## Override` section in `skills/charge-battery.md`**

Replace lines 40-42:

```markdown
## Override

If the user specifies a charge level (e.g., "charge battery to 80%"), set `manual_override: 80` in `config.yaml` before running, then clear it after.
```

with:

```markdown
## Manual override

For a direct "set the battery to N%" request, use the `set-battery` skill instead.
```

- [ ] **Step 2: Apply the same change to `.claude/commands/charge-battery.md`**

Identical edit at the same location.

- [ ] **Step 3: Commit**

```bash
git add skills/charge-battery.md .claude/commands/charge-battery.md
git commit -m "docs: point charge-battery skill at new set-battery shortcut"
```

---

## Final verification

- [ ] **Run the full test suite one last time**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Re-grep for any lingering `manual_override` references**

Run: `grep -rn manual_override src tests config.yaml config.example.yaml README.md skills .claude/commands`

Expected: empty.

- [ ] **End-to-end smoke (optional, requires real Growatt credentials)**

If you want to verify the new skill end-to-end, invoke it from Claude Code: "set battery to 50%". Confirm `last_updated.md` shows `Manual: set to 50%` and tomorrow's decision row in the DB has `is_manual=1`. (Restore the calculator-derived value afterwards by running `charge battery` if you need the original setting back.)
