# Dead Code Cleanup and Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove vestigial schema/code left behind by the calculator redesign, and fix a cluster of latent bugs in the Growatt client and orchestrator.

**Architecture:** Two-phase cleanup. Phase A removes dead tables, columns, parameters, and query helpers — all items that have no runtime effect but clutter the schema and signatures. Phase B fixes hidden bugs: Growatt charge window is hardcoded (ignores config tariff times), `calculate_charge` does a duplicate generation lookup, orchestrator retry backoff indexes out of bounds on the last attempt, and Growatt read methods lack the retry wrapper that `set_charge_soc` already has.

**Tech Stack:** Python 3.12+, SQLite (≥3.35 for `ALTER TABLE DROP COLUMN`), pytest, FastAPI dashboard (unchanged).

**Scope:** Does NOT include the cost-bias percentile rework (deferred from calculator redesign), the weather-classifier consolidation (items #3/#4 from review), or observability improvements — those are recorded separately in better-memory.

---

## File Map

**Modify:**
- `src/db/schema.py` — drop `adjustments` table; drop `base_charge_level` and `feedback_adjustment` columns
- `src/db/queries.py` — remove `insert_adjustment`, `get_recent_adjustments`, `get_generation_by_weather`, `get_generation_by_weather_wide`, `get_generation_by_condition`, `get_generation_by_month`; simplify `upsert_decision` signature
- `src/orchestrator.py` — update `upsert_decision` call, fix retry backoff tuple
- `src/calculator/engine.py` — remove `current_soc` parameter; consolidate `kwh_per_solar_hour` lookup
- `src/growatt/client.py` — derive charge periods from config rates; wrap `login`, `get_current_soc`, `get_hourly_data` in `_retry`
- `src/config.py` — remove `charge_floor_pct` pop shim
- `config.example.yaml` — add `morning_buffer_kwh`, `min_soc_pct`, `cloud_floor_pct`
- `config.yaml` — add the same keys with user's current values (user file, verify before changing)
- `tests/test_db.py` — remove dead-query tests; update `test_upsert_decision` and `test_init_db_creates_tables`
- `tests/test_calculator.py` — drop `current_soc=` kwarg from all calls
- `tests/test_orchestrator.py` — no change expected (uses config-level injection)
- `tests/test_growatt_client.py` — extend for new charge-window logic and retry coverage

**Delete:** none.

---

## Pre-flight (do once before starting)

- [ ] **Step 0.1: Verify SQLite version supports DROP COLUMN**

Run:
```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```
Expected: `3.35.0` or higher. If lower, stop and escalate — the column-drop migration will need the rebuild-rename pattern instead.

- [ ] **Step 0.2: Verify baseline tests pass**

Run:
```bash
python -m pytest tests/ -q
```
Expected: all 74 tests pass.

- [ ] **Step 0.3: Back up the live database**

Run:
```bash
cp data/battery.db data/battery.db.bak-2026-04-18
```
Expected: backup file created. Confirm with `ls -la data/*.db*`.

- [ ] **Step 0.4: Confirm `adjustments` table is empty in the live DB**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('data/battery.db'); print(c.execute('SELECT COUNT(*) FROM adjustments').fetchone())"
```
Expected: `(0,)`. If non-zero, escalate — plan assumes the table was never written to.

---

## Phase A — Dead Code Cleanup

### Task 1: Drop the `adjustments` table

**Files:**
- Modify: `src/db/schema.py:35-45` (remove CREATE) and `src/db/schema.py:49-65` (add drop in `_migrate`)
- Modify: `src/db/queries.py:77-98` (remove `insert_adjustment`, `get_recent_adjustments`)
- Modify: `tests/test_db.py:46-55` (delete `test_insert_adjustment`)
- Modify: `tests/test_db.py:6-17` (update `test_init_db_creates_tables`)

- [ ] **Step 1.1: Write the failing test for drop-on-init**

Replace `tests/test_db.py:6-17` with:
```python
def test_init_db_creates_tables(tmp_path):
    from src.db.schema import init_db
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "actuals" in tables
    assert "decisions" in tables
    assert "adjustments" not in tables
    conn.close()
```

Delete `tests/test_db.py:46-55` (the whole `test_insert_adjustment` function).

- [ ] **Step 1.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_db.py::test_init_db_creates_tables tests/test_db.py::test_insert_adjustment -v`
Expected: `test_init_db_creates_tables` FAILS with `assert "adjustments" not in tables`. `test_insert_adjustment` ERRORS as "not found" (it's deleted).

- [ ] **Step 1.3: Remove the CREATE from schema.py**

In `src/db/schema.py`, delete lines 35-45 (the entire `CREATE TABLE IF NOT EXISTS adjustments (...)` block including its trailing blank line).

- [ ] **Step 1.4: Add the drop to `_migrate`**

In `src/db/schema.py:49-65`, update `_migrate` to also drop the legacy table. Add right before `conn.commit()` at the end:
```python
    # Drop legacy adjustments table (never written to after feedback-loop removal)
    conn.execute("DROP TABLE IF EXISTS adjustments")
```

- [ ] **Step 1.5: Remove `insert_adjustment` and `get_recent_adjustments` from queries.py**

In `src/db/queries.py`, delete lines 77-98 (both functions including the blank lines between them). Also remove `from datetime import ..., timedelta` at line 2 if `timedelta` is no longer used — grep first:
```bash
python -m grep -n "timedelta" src/db/queries.py
```
If no remaining uses, change line 2 from `from datetime import date, timedelta` to `from datetime import date`.

- [ ] **Step 1.6: Run tests to confirm they now pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: all remaining db tests pass.

- [ ] **Step 1.7: Commit**

```bash
git add src/db/schema.py src/db/queries.py tests/test_db.py
git commit -m "refactor: drop unused adjustments table and its query helpers"
```

---

### Task 2: Drop `base_charge_level` and `feedback_adjustment` columns

**Files:**
- Modify: `src/db/schema.py:5-16` (remove columns from CREATE) and `_migrate` (add drop-column logic)
- Modify: `src/db/queries.py:5-29` (simplify `upsert_decision` signature and SQL)
- Modify: `src/orchestrator.py:222-233` (remove the two kwargs from the call)
- Modify: `tests/test_db.py:20-32` (update `test_upsert_decision` to new signature)

- [ ] **Step 2.1: Write the failing test for the new decisions schema**

Add to `tests/test_db.py` after `test_init_db_creates_tables`:
```python
def test_decisions_table_has_no_legacy_columns(tmp_path):
    from src.db.schema import init_db
    conn = init_db(tmp_path / "test.db")
    cursor = conn.execute("PRAGMA table_info(decisions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "base_charge_level" not in columns
    assert "feedback_adjustment" not in columns
    assert "charge_level_set" in columns
    conn.close()
```

Replace `tests/test_db.py:20-32` (the whole `test_upsert_decision` function) with:
```python
def test_upsert_decision(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, get_decision
    conn = init_db(tmp_path / "test.db")
    upsert_decision(conn, date(2026, 3, 25), "sunny", "{}", 60,
                    "initial", 10, 3, "open_meteo")
    upsert_decision(conn, date(2026, 3, 25), "cloudy", "{}", 75,
                    "revised", 10, 3, "open_meteo")
    row = get_decision(conn, date(2026, 3, 25))
    assert row["charge_level_set"] == 75
    assert row["forecast_summary"] == "cloudy"
    assert row["adjustment_reason"] == "revised"
    conn.close()
```

- [ ] **Step 2.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_db.py::test_decisions_table_has_no_legacy_columns tests/test_db.py::test_upsert_decision -v`
Expected: `test_decisions_table_has_no_legacy_columns` FAILS on `assert "base_charge_level" not in columns`. `test_upsert_decision` FAILS with TypeError (wrong arg count).

- [ ] **Step 2.3: Update the CREATE in schema.py**

In `src/db/schema.py:5-16`, replace the `decisions` CREATE block with:
```python
CREATE TABLE IF NOT EXISTS decisions (
    date TEXT PRIMARY KEY,
    forecast_summary TEXT NOT NULL,
    forecast_detail TEXT NOT NULL,
    charge_level_set INTEGER NOT NULL,
    adjustment_reason TEXT,
    current_soc_at_decision INTEGER,
    month INTEGER NOT NULL,
    weather_provider_used TEXT NOT NULL
);
```
Leave the `actuals` CREATE and any trailing semicolons intact.

- [ ] **Step 2.4: Extend `_migrate` to drop the legacy columns**

In `src/db/schema.py`, update `_migrate` — add the following block **after** the `actuals` ALTER statements and **before** the `DROP TABLE IF EXISTS adjustments` you added in Task 1:
```python
    cursor = conn.execute("PRAGMA table_info(decisions)")
    decisions_cols = {row[1] for row in cursor.fetchall()}
    if "feedback_adjustment" in decisions_cols:
        conn.execute("ALTER TABLE decisions DROP COLUMN feedback_adjustment")
    if "base_charge_level" in decisions_cols:
        conn.execute("ALTER TABLE decisions DROP COLUMN base_charge_level")
```

- [ ] **Step 2.5: Simplify `upsert_decision` in queries.py**

Replace `src/db/queries.py:5-29` (the whole `upsert_decision` function) with:
```python
def upsert_decision(conn: sqlite3.Connection, dt: date, forecast_summary: str,
                    forecast_detail: str, charge_level_set: int,
                    adjustment_reason: str | None, current_soc: int | None,
                    month: int, weather_provider: str) -> None:
    conn.execute("""
        INSERT INTO decisions (date, forecast_summary, forecast_detail,
            charge_level_set, adjustment_reason, current_soc_at_decision, month,
            weather_provider_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            forecast_summary=excluded.forecast_summary,
            forecast_detail=excluded.forecast_detail,
            charge_level_set=excluded.charge_level_set,
            adjustment_reason=excluded.adjustment_reason,
            current_soc_at_decision=excluded.current_soc_at_decision,
            month=excluded.month,
            weather_provider_used=excluded.weather_provider_used
    """, (str(dt), forecast_summary, forecast_detail, charge_level_set,
          adjustment_reason, current_soc, month, weather_provider))
    conn.commit()
```

- [ ] **Step 2.6: Update the orchestrator call site**

In `src/orchestrator.py`, replace lines 222-233 (the `upsert_decision(...)` call) with:
```python
    upsert_decision(
        conn, target_date,
        forecast_summary=forecast.condition if forecast else "unknown",
        forecast_detail=forecast_detail,
        charge_level_set=charge_level,
        adjustment_reason=reason,
        current_soc=current_soc,
        month=target_date.month,
        weather_provider=config.weather.provider,
    )
```

- [ ] **Step 2.7: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. If the dashboard query in `src/dashboard/app.py:55` fails on the `d.*` selector, no action needed — it auto-adapts.

- [ ] **Step 2.8: Manually verify live DB migrates cleanly**

Run:
```bash
python -c "from pathlib import Path; from src.db.schema import init_db; init_db(Path('data/battery.db'))"
python -c "import sqlite3; c=sqlite3.connect('data/battery.db'); print([r[1] for r in c.execute('PRAGMA table_info(decisions)').fetchall()])"
```
Expected: the second command output does NOT contain `base_charge_level` or `feedback_adjustment`. Contains `charge_level_set`.

- [ ] **Step 2.9: Commit**

```bash
git add src/db/schema.py src/db/queries.py src/orchestrator.py tests/test_db.py
git commit -m "refactor: drop base_charge_level and feedback_adjustment columns"
```

---

### Task 3: Remove unused `current_soc` parameter from `calculate_charge`

**Files:**
- Modify: `src/calculator/engine.py:164-231` (drop the parameter and its use in the reason string)
- Modify: `src/orchestrator.py:202-206` (drop the kwarg at the call site)
- Modify: `tests/test_calculator.py` — every call to `calculate_charge(...)` that passes `current_soc=...`

- [ ] **Step 3.1: Write the failing test**

Add to `tests/test_calculator.py` after the `test_manual_override` function:
```python
def test_calculate_charge_has_no_current_soc_param(tmp_path, config):
    """Signature hygiene: current_soc was removed in commit 8d340cb but left as a dead param."""
    import inspect
    from src.calculator.engine import calculate_charge
    params = inspect.signature(calculate_charge).parameters
    assert "current_soc" not in params
```

- [ ] **Step 3.2: Run the test to confirm it fails**

Run: `python -m pytest tests/test_calculator.py::test_calculate_charge_has_no_current_soc_param -v`
Expected: FAIL with `assert "current_soc" not in params`.

- [ ] **Step 3.3: Remove the parameter from `calculate_charge`**

In `src/calculator/engine.py`, replace lines 164-169 (function signature) with:
```python
def calculate_charge(
    config: Config,
    forecast: DayForecast,
    conn: sqlite3.Connection,
) -> ChargeResult:
```

In the same function, delete line 220 (`f"Current SOC: {current_soc}%",` inside `reason_parts`).

- [ ] **Step 3.4: Update the orchestrator call**

In `src/orchestrator.py`, replace lines 202-206 with:
```python
            calc_result = calculate_charge(
                config=config, forecast=forecast, conn=conn,
            )
```

- [ ] **Step 3.5: Update tests**

In `tests/test_calculator.py`, remove every `current_soc=...,` kwarg from calls to `calculate_charge(...)`. Occurrences to fix: lines 60-61, 78-79, 97-98, 113-114, 138-139, 161-162, 178-179, 516-517, 550-553, 575-576. (Use search-replace: find `,\s*current_soc=\d+` and delete.)

Also grep for other direct callers:
```bash
python -m grep -rn "calculate_charge" --include="*.py" .
```
Expected callers: `src/orchestrator.py` (done), `src/calculator/engine.py` (definition), `tests/test_calculator.py` (in progress). No others.

- [ ] **Step 3.6: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass including the new `test_calculate_charge_has_no_current_soc_param`.

- [ ] **Step 3.7: Commit**

```bash
git add src/calculator/engine.py src/orchestrator.py tests/test_calculator.py
git commit -m "refactor: drop unused current_soc parameter from calculate_charge"
```

---

### Task 4: Remove unused generation query helpers

**Files:**
- Modify: `src/db/queries.py:111-150` (delete four functions)
- Modify: `tests/test_db.py` — delete four tests

- [ ] **Step 4.1: Confirm no production callers**

Run:
```bash
python -m grep -rn "get_generation_by_weather\|get_generation_by_condition\|get_generation_by_month" --include="*.py" src/ scripts/
```
Expected: no matches outside `src/db/queries.py` itself. If any match appears in `src/` or `scripts/`, stop and escalate — the helper is still used.

- [ ] **Step 4.2: Delete the functions**

In `src/db/queries.py`, delete lines 111-150 (the four functions `get_generation_by_weather`, `get_generation_by_weather_wide`, `get_generation_by_condition`, `get_generation_by_month` and the blank lines between them).

- [ ] **Step 4.3: Delete the corresponding tests**

In `tests/test_db.py`, delete:
- `test_get_generation_by_weather` (approx lines 140-154)
- `test_get_generation_by_weather_wide` (approx lines 157-169)
- `test_get_generation_by_weather_wide_year_wrap` (approx lines 172-183)
- `test_get_generation_by_condition` (approx lines 186-197)
- `test_get_generation_by_month` (approx lines 200-211)

- [ ] **Step 4.4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: all remaining tests pass; total count reduced by 5.

- [ ] **Step 4.5: Commit**

```bash
git add src/db/queries.py tests/test_db.py
git commit -m "refactor: remove unused generation-by-weather query helpers"
```

---

## Phase B — Hidden Bug Fixes

### Task 5: Derive Growatt charge window from config

**Files:**
- Modify: `src/growatt/client.py:60-79` (add helper, refactor `set_charge_soc`)
- Modify: `tests/test_growatt_client.py:34-48` (extend `test_set_charge_soc`, add wrap/no-wrap cases)

**Design:** The inverter POST takes three (start_h, start_m, end_h, end_m, enabled) period slots. We derive slot 1 and slot 2 from `config.rates.cheap_start` and `cheap_end`. If the window wraps midnight (start > end, e.g. 23:30→05:30) we split into two slots; otherwise one slot is enabled and slot 2 is zeroed and disabled. Slot 3 is always disabled.

- [ ] **Step 5.1: Write the failing tests**

Replace `tests/test_growatt_client.py:34-48` (the `test_set_charge_soc` function) with:
```python
def _post_params(mock_api):
    call_args = mock_api.session.post.call_args
    return call_args[1]["data"] if "data" in call_args[1] else call_args[0][1]


def test_set_charge_soc_uses_configured_wrap_window(config):
    """Cheap window 23:30-05:30 wraps midnight: slot1=23:30-23:59, slot2=00:00-05:30."""
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        assert client.set_charge_soc(75) is True
    data = _post_params(mock_api)
    assert data["param2"] == "75"
    assert (data["param3"], data["param4"]) == ("23", "30")
    assert (data["param5"], data["param6"]) == ("23", "59")
    assert data["param7"] == "1"
    assert (data["param8"], data["param9"]) == ("00", "00")
    assert (data["param10"], data["param11"]) == ("05", "30")
    assert data["param12"] == "1"
    assert data["param17"] == "0"


def test_set_charge_soc_non_wrapping_window(tmp_path):
    """Cheap window 01:00-05:00 (no wrap): slot1 uses it, slot2 disabled."""
    from src.growatt.client import GrowattClient
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        VALID_CONFIG_YAML
        .replace('cheap_start: "23:30"', 'cheap_start: "01:00"')
        .replace('cheap_end: "05:30"', 'cheap_end: "05:00"')
    )
    cfg = load_config(cfg_path)

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp
    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(cfg.growatt, rates=cfg.rates)
        client.login()
        client.set_charge_soc(60)
    data = _post_params(mock_api)
    assert (data["param3"], data["param4"]) == ("01", "00")
    assert (data["param5"], data["param6"]) == ("05", "00")
    assert data["param7"] == "1"
    assert data["param12"] == "0"
```

Also update the existing `test_get_hourly_data`, `test_login_sets_session`, `test_get_current_soc` if they currently construct `GrowattClient(config.growatt)` — leave them alone for now; we'll make `rates` optional with a safe default.

- [ ] **Step 5.2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_growatt_client.py -v`
Expected: two new tests FAIL (no `rates` constructor param yet); other tests still pass.

- [ ] **Step 5.3: Add the helper and wire it in**

In `src/growatt/client.py`, update the imports at the top:
```python
import growattServer
import logging
import time as time_module
from datetime import date
from ..config import GrowattConfig, RatesConfig
```

Replace the whole `GrowattClient.__init__` and `set_charge_soc` block (lines 16-79) with:
```python
class GrowattClient:
    def __init__(self, config: GrowattConfig, rates: RatesConfig | None = None):
        self.config = config
        self.rates = rates
        self._api = growattServer.GrowattApi()
        self._api.session.headers.update({"User-Agent": USER_AGENT})
        self._api.server_url = config.server_url
        self.logged_in = False

    def login(self) -> None:
        result = self._api.login(self.config.username, self.config.password)
        if not result.get("success"):
            raise GrowattError(f"Login failed: {result.get('error', 'unknown')}")
        self.logged_in = True
        logger.info("Growatt login successful")

    def _retry(self, func, retries=3, backoff=(5, 15, 45)):
        for attempt in range(retries):
            try:
                return func()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                logger.warning(f"Attempt {attempt+1} failed: {e}. Retrying in {wait}s")
                time_module.sleep(wait)

    def get_hourly_data(self, target_date: date) -> dict:
        raw = self._api.dashboard_data(
            self.config.plant_id, growattServer.Timespan.hour, target_date
        )
        return raw.get("chartData", {})

    def get_current_soc(self) -> int:
        devices = self._api.device_list(self.config.plant_id)
        for dev in devices:
            if dev.get("deviceSn") == self.config.device_sn:
                cap_str = dev.get("capacity", "0%").replace("%", "")
                return int(cap_str)
        raise GrowattError(f"Device {self.config.device_sn} not found")

    def _charge_periods(self) -> list[tuple[int, int, int, int]]:
        """Return up to 2 (start_h, start_m, end_h, end_m) ranges matching the
        configured cheap window. Windows wrapping midnight split at 23:59/00:00.
        Falls back to the historical hardcoded 23:30-05:30 window when rates
        are not provided (preserves legacy callers)."""
        if self.rates is None:
            return [(23, 30, 23, 59), (0, 0, 5, 30)]
        sh, sm = (int(x) for x in self.rates.cheap_start.split(":"))
        eh, em = (int(x) for x in self.rates.cheap_end.split(":"))
        if (sh, sm) < (eh, em):
            return [(sh, sm, eh, em)]
        return [(sh, sm, 23, 59), (0, 0, eh, em)]

    def set_charge_soc(self, soc_pct: int) -> bool:
        soc_pct = max(0, min(100, soc_pct))
        periods = self._charge_periods()
        slot1 = periods[0]
        slot2 = periods[1] if len(periods) > 1 else (0, 0, 0, 0)
        slot1_on = "1"
        slot2_on = "1" if len(periods) > 1 else "0"

        def _fmt(n: int) -> str:
            return f"{n:02d}"

        def _do_set():
            resp = self._api.session.post(
                f"{self.config.server_url}tcpSet.do",
                data={
                    "action": "spaSet",
                    "serialNum": self.config.device_sn,
                    "type": "spa_ac_charge_time_period",
                    "param1": "100", "param2": str(soc_pct),
                    "param3": _fmt(slot1[0]), "param4": _fmt(slot1[1]),
                    "param5": _fmt(slot1[2]), "param6": _fmt(slot1[3]),
                    "param7": slot1_on,
                    "param8": _fmt(slot2[0]), "param9": _fmt(slot2[1]),
                    "param10": _fmt(slot2[2]), "param11": _fmt(slot2[3]),
                    "param12": slot2_on,
                    "param13": "00", "param14": "00",
                    "param15": "00", "param16": "00", "param17": "0",
                }
            )
            result = resp.json()
            if not result.get("success"):
                raise GrowattError(f"Set charge failed: {result.get('msg')}")
            return True
        return self._retry(_do_set)
```

- [ ] **Step 5.4: Pass rates from the orchestrator's client construction**

In `scripts/nightly-charge.py:18`, change:
```python
growatt = GrowattClient(config.growatt)
```
to:
```python
growatt = GrowattClient(config.growatt, rates=config.rates)
```

Also update the inline example in `README.md:82` (the usage snippet) to pass `rates=config.rates`. Keep README formatting consistent with surrounding code.

- [ ] **Step 5.5: Run all tests**

Run: `python -m pytest tests/ -q`
Expected: all pass, including the two new wrap/no-wrap cases.

- [ ] **Step 5.6: Commit**

```bash
git add src/growatt/client.py scripts/nightly-charge.py README.md tests/test_growatt_client.py
git commit -m "fix: derive Growatt charge window from config rates instead of hardcoding"
```

---

### Task 6: Consolidate duplicate generation lookup in `calculate_charge`

**Files:**
- Modify: `src/calculator/engine.py:76-108` (return `kwh_per_solar_hour` from `_estimate_generation_hourly`)
- Modify: `src/calculator/engine.py:164-231` (use the returned value instead of re-querying)

- [ ] **Step 6.1: Write the failing test**

Add to `tests/test_calculator.py` after the existing `_estimate_generation_hourly` tests:
```python
def test_estimate_generation_hourly_returns_kwh_per_solar_hour(tmp_path):
    """Helper returns (total_kwh, kwh_per_solar_hour, source) so the caller
    doesn't re-query the DB."""
    from src.calculator.engine import _estimate_generation_hourly
    from src.db.schema import init_db
    from src.db.queries import insert_actuals

    conn = init_db(tmp_path / "test.db")
    _populate_generation(conn, month=3, condition="sunny",
                         values=[20.0, 34.0, 25.0, 30.0, 28.0])
    cloud_hours = [(h, 0) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    total, per_hour, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    assert total > 0
    assert per_hour > 0
    assert "max" in source.lower()
```

- [ ] **Step 6.2: Run to confirm it fails**

Run: `python -m pytest tests/test_calculator.py::test_estimate_generation_hourly_returns_kwh_per_solar_hour -v`
Expected: FAIL with `ValueError: not enough values to unpack`.

- [ ] **Step 6.3: Update `_estimate_generation_hourly`**

In `src/calculator/engine.py`, replace the function body signature and return statements. Change the return type from `tuple[float, str]` to `tuple[float, float, str]` and return `kwh_per_solar_hour` alongside the total:
```python
def _estimate_generation_hourly(
    conn: sqlite3.Connection, month: int, forecast: DayForecast, latitude: float,
    cloud_floor: float = 0.25,
) -> tuple[float, float, str]:
    result = get_max_generation_for_month(conn, month)
    source_label = "max"
    if result is None:
        result = get_max_generation_for_adjacent_months(conn, month)
        source_label = "adjacent month max"
    if result is None:
        return 0.0, 0.0, "no historical generation data"

    max_gen_kwh, max_gen_date_str = result
    max_gen_date = date.fromisoformat(max_gen_date_str)

    max_day_solar_hours = solar_day_length(latitude, max_gen_date)
    if max_day_solar_hours <= 0:
        return 0.0, 0.0, "no solar hours on max generation day"

    kwh_per_solar_hour = max_gen_kwh / max_day_solar_hours

    estimated = sum(
        kwh_per_solar_hour * _cloud_factor(h.cloud_cover_pct, cloud_floor)
        for h in forecast.hourly
    )

    forecast_solar_hours = len(forecast.hourly)
    description = (
        f"{source_label} {max_gen_kwh:.1f}kWh on {max_gen_date_str}, "
        f"{max_day_solar_hours:.1f} solar hrs, "
        f"cloud-adjusted from {forecast_solar_hours} forecast hrs"
    )
    return estimated, kwh_per_solar_hour, description
```

- [ ] **Step 6.4: Update `calculate_charge` to use the returned value**

In `src/calculator/engine.py`, replace the body of `calculate_charge` from the line `expected_generation, generation_source = _estimate_generation_hourly(...)` (approximately line 182) down to and including the block that re-queries `get_max_generation_for_month` (approximately lines 193-205). The new body from the generation call through the morning-floor block should read:
```python
    expected_consumption, consumption_source = _estimate_consumption(conn)
    expected_generation, kwh_per_solar_hour, generation_source = _estimate_generation_hourly(
        conn, month, forecast, config.location.latitude, cloud_floor
    )

    usable_capacity_kwh = config.battery.usable_capacity_kwh
    min_soc = config.battery.min_soc_pct

    gap_kwh = expected_consumption - expected_generation
    charge_pct = (gap_kwh / usable_capacity_kwh) * 100

    morning_kwh = _morning_floor_kwh(
        config, forecast, expected_consumption, kwh_per_solar_hour, cloud_floor
    )
    morning_pct = (morning_kwh / usable_capacity_kwh) * 100
```

Also remove the now-unused imports: at the top of `src/calculator/engine.py`, change `from ..db.queries import (get_recent_expensive_consumption, get_max_generation_for_month, get_max_generation_for_adjacent_months)` to `from ..db.queries import (get_recent_expensive_consumption, get_max_generation_for_month, get_max_generation_for_adjacent_months)` — verify these two `get_max_generation_*` imports are still used **inside** `_estimate_generation_hourly` (they are), so keep them.

- [ ] **Step 6.5: Update other callers of the helper**

Grep for `_estimate_generation_hourly` callers:
```bash
python -m grep -rn "_estimate_generation_hourly" --include="*.py" .
```
Expected results: definition + `calculate_charge` (done) + tests in `tests/test_calculator.py`. The tests unpack 2 values (`gen_kwh, source = ...`); update every such unpack to `gen_kwh, _, source = ...`. Affected lines in `tests/test_calculator.py`: approximately 292, 305, 307, 319, 335, 336, 349, 360.

- [ ] **Step 6.6: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. Calculator behavior unchanged (same math, fewer DB queries).

- [ ] **Step 6.7: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "refactor: return kwh_per_solar_hour from _estimate_generation_hourly to avoid duplicate DB lookup"
```

---

### Task 7: Fix orchestrator retry backoff

**Files:**
- Modify: `src/orchestrator.py:181-197` (replace fragile 2-element indexing with a tuple that matches retry count)

- [ ] **Step 7.1: Write the failing test**

Add to `tests/test_orchestrator.py`:
```python
def test_orchestrator_weather_retry_backoff_does_not_indexerror(tmp_path, config, monkeypatch):
    """Regression: backoff schedule must not IndexError if the loop ever expands."""
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    call_count = {"n": 0}

    def flaky_forecast(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("transient")
        return _make_forecast(date(2026, 7, 15))

    mock_weather = MagicMock()
    mock_weather.get_forecast.side_effect = flaky_forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 20
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    # Speed up the retry by replacing the sleep used inside run_nightly
    import src.orchestrator as orch
    monkeypatch.setattr(orch, "time", __import__("time"))

    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )
    assert result["success"] is True
    assert call_count["n"] == 3
```

- [ ] **Step 7.2: Run to confirm baseline behavior**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: the new test may already pass because attempt 2 currently short-circuits before the `[5, 15][attempt]` index — but the test exists to lock the retry schedule's shape for future changes. If it passes, that's fine; proceed with the refactor.

- [ ] **Step 7.3: Replace the inline backoff list with a named tuple**

In `src/orchestrator.py:181-197`, replace the weather retry block:
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
```

Note: `_BACKOFF` has 3 entries so the index is safe for all attempt values; the final slot is never consumed because attempt==2 branches out.

- [ ] **Step 7.4: Run tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all pass including the new test.

- [ ] **Step 7.5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "fix: make orchestrator weather-retry backoff tolerant of future loop changes"
```

---

### Task 8: Extend `_retry` coverage to Growatt read methods

**Files:**
- Modify: `src/growatt/client.py` (wrap `login`, `get_current_soc`, `get_hourly_data`)
- Modify: `tests/test_growatt_client.py` (add a retry test)

- [ ] **Step 8.1: Write the failing test**

Add to `tests/test_growatt_client.py`:
```python
def test_get_current_soc_retries_on_transient_failure(config, monkeypatch):
    """Transient failures on get_current_soc should retry rather than bubble up."""
    from src.growatt.client import GrowattClient
    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    calls = {"n": 0}

    def flaky_device_list(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return [{"deviceSn": config.growatt.device_sn, "capacity": "42%"}]

    mock_api.device_list.side_effect = flaky_device_list

    # Neutralize sleep inside _retry
    import src.growatt.client as gc
    monkeypatch.setattr(gc.time_module, "sleep", lambda *a, **k: None)

    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        soc = client.get_current_soc()
    assert soc == 42
    assert calls["n"] == 2
```

- [ ] **Step 8.2: Run to confirm it fails**

Run: `python -m pytest tests/test_growatt_client.py::test_get_current_soc_retries_on_transient_failure -v`
Expected: FAIL with `RuntimeError: transient` (no retry currently applied).

- [ ] **Step 8.3: Wrap read methods in `_retry`**

In `src/growatt/client.py`, update:

**`login`** (the call body):
```python
    def login(self) -> None:
        def _do_login():
            result = self._api.login(self.config.username, self.config.password)
            if not result.get("success"):
                raise GrowattError(f"Login failed: {result.get('error', 'unknown')}")
            return result
        self._retry(_do_login)
        self.logged_in = True
        logger.info("Growatt login successful")
```

**`get_hourly_data`:**
```python
    def get_hourly_data(self, target_date: date) -> dict:
        def _do():
            raw = self._api.dashboard_data(
                self.config.plant_id, growattServer.Timespan.hour, target_date
            )
            return raw.get("chartData", {})
        return self._retry(_do)
```

**`get_current_soc`:**
```python
    def get_current_soc(self) -> int:
        def _do():
            devices = self._api.device_list(self.config.plant_id)
            for dev in devices:
                if dev.get("deviceSn") == self.config.device_sn:
                    cap_str = dev.get("capacity", "0%").replace("%", "")
                    return int(cap_str)
            raise GrowattError(f"Device {self.config.device_sn} not found")
        return self._retry(_do)
```

- [ ] **Step 8.4: Run tests**

Run: `python -m pytest tests/test_growatt_client.py -v`
Expected: all pass including the new retry test.

- [ ] **Step 8.5: Commit**

```bash
git add src/growatt/client.py tests/test_growatt_client.py
git commit -m "fix: add retry to Growatt login, get_current_soc, get_hourly_data"
```

---

### Task 9: Add missing keys to `config.example.yaml`

**Files:**
- Modify: `config.example.yaml`

- [ ] **Step 9.1: Update the example**

Replace `config.example.yaml` with:
```yaml
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "your_username"
  password: "your_password"
  plant_id: "your_plant_id"
  device_sn: "your_device_sn"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  fallback_charge_level: 90
  morning_buffer_kwh: 2.0
  min_soc_pct: 10
  cloud_floor_pct: 25.0
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
```

- [ ] **Step 9.2: Ask the user before touching `config.yaml`**

`config.yaml` is the user's live configuration. Do NOT modify it automatically. Surface a diff and ask whether to add the three missing keys (`morning_buffer_kwh`, `min_soc_pct`, `cloud_floor_pct`) at their defaults or at custom values.

- [ ] **Step 9.3: Run sanity check**

Run: `python -c "from pathlib import Path; from src.config import load_config; print(load_config(Path('config.example.yaml')))"`
Expected: prints a `Config(...)` instance without errors. (A placeholder username/password is fine; `load_config` doesn't validate secrets.)

- [ ] **Step 9.4: Commit**

```bash
git add config.example.yaml
git commit -m "docs: expose morning_buffer_kwh, min_soc_pct, cloud_floor_pct in config.example.yaml"
```

---

### Task 10: Remove `charge_floor_pct` back-compat shim

**Files:**
- Modify: `src/config.py:102-104` (delete the pop)

- [ ] **Step 10.1: Confirm no live config uses it**

Run:
```bash
python -m grep -n "charge_floor_pct" config.yaml config.example.yaml
```
Expected: no matches. If `config.yaml` still has it, delete the line from the user's file manually first (ask first — it's the user's config).

- [ ] **Step 10.2: Remove the pop**

In `src/config.py`, delete lines 102-104 (the comment `# charge_floor_pct may still be in old configs — ignore it` and the `battery_raw.pop(...)` line).

- [ ] **Step 10.3: Run tests**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 10.4: Commit**

```bash
git add src/config.py
git commit -m "refactor: remove obsolete charge_floor_pct back-compat shim"
```

---

## Post-flight

- [ ] **Step F.1: Full suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass. Count should be roughly 74 − 5 (deleted dead-query tests) − 1 (deleted `test_insert_adjustment`) + 4 (new tests) = 72 tests.

- [ ] **Step F.2: Smoke-test the nightly script against the live DB**

Run: `python scripts/nightly-charge.py`
Expected: one of
- sets a charge level and writes `last_updated.md` (production path), or
- if run outside charging time, still logs a decision for tomorrow.

If it errors, roll back the live DB from the backup: `cp data/battery.db.bak-2026-04-18 data/battery.db`.

- [ ] **Step F.3: Smoke-test the dashboard**

Run: `python run_dashboard.py` (in background) then open `http://127.0.0.1:8099` and click through `/`, `/history`, `/accuracy`, `/savings`. Each page should render without SQL errors. Stop the server afterwards.

- [ ] **Step F.4: Record the outcome in better-memory**

Write a `memory_observe` entry summarising which tasks landed and any deviations from the plan (component `orchestrator`, theme `refactor`, outcome `success`).

---

## Self-Review checklist (completed inline)

- **Spec coverage:** all six items of #1 and all six items of #2 from the review are addressed (adjustments table, base/feedback cols, current_soc param, dead query helpers, charge window, duplicate lookup, backoff bug, retries, config.yaml/example, charge_floor_pct shim).
- **Placeholder scan:** no TODO/TBD/"similar to above" — every code block is complete.
- **Type consistency:** `_estimate_generation_hourly` return type is updated consistently at its definition (Task 6.3), its caller in `calculate_charge` (Task 6.4), and all test unpackings (Task 6.5). `GrowattClient.__init__` gains an optional `rates` kwarg; callers in `scripts/nightly-charge.py` and README are updated (Task 5.4); existing tests that pass only `config.growatt` continue to work via the `rates=None` default.
