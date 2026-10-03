# Hourly Readings Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Growatt's raw 5-minute readings in a new `readings` table, written by the existing per-day backfill, and populate it for the 91 days already in the database before they expire from Growatt.

**Architecture:** One new SQLite table alongside `actuals`, two query helpers, and a change to `backfill_actuals_for_day` so it fetches a day once and stores readings and daily totals independently. The nightly run and the history backfill script both go through that function, so neither needs changes.

**Tech Stack:** Python 3.12+, sqlite3, pytest, `unittest.mock.MagicMock` for the Growatt client.

**Spec:** `docs/superpowers/specs/2026-10-03-hourly-readings-capture-design.md`

## Global Constraints

- Follow the existing query style in `src/db/queries.py`: plain `conn.execute` with `?` parameters, `conn.commit()` at the end of each writer.
- `readings.date` is `YYYY-MM-DD` (`str(dt)`), `readings.time` is Growatt's key unchanged (`HH:MM`).
- Field conversion is `float(value.get(field) or 0)` for `ppv`, `sysOut`, `userLoad`, `pacToUser`.
- Run the whole suite with `python -m pytest tests/ -q` before every commit; 82 tests pass on the branch today (79 passed, 3 xpassed).
- Branch: `feat/hourly-readings` (already created, based on `main`).

## Review Focus

- A Growatt reading with a null field (`{"ppv": None, ...}`) must store 0.0, not crash. Pinned in Task 2.
- A day whose Growatt response has entries but none are dicts must raise `ValueError` and store nothing. Pinned in Task 3.
- A day with daily totals but no readings (every one of the 91 backfilled days) must get readings stored and its totals left untouched. Pinned in Task 3.
- A day with both must not call Growatt at all, so the nightly run stays one request. Pinned in Task 3.
- Re-running the live backfill script must leave the existing `actuals` rows unchanged. Pinned in Task 4.

---

### Task 1: `readings` table

**Confidence:** 98%. A six-column table following the existing `CREATE TABLE IF NOT EXISTS` pattern; nothing unknown.

**Files:**
- Modify: `src/db/schema.py` (the `SCHEMA_SQL` string, after the `actuals` table)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: table `readings(date TEXT, time TEXT, ppv_kw REAL, sys_out_kw REAL, user_load_kw REAL, pac_to_user_kw REAL, PRIMARY KEY (date, time))`, all columns `NOT NULL`.

- [ ] **Step 1: Write the failing test**

```python
def test_init_db_creates_readings_table(tmp_path):
    from src.db.schema import init_db
    conn = init_db(tmp_path / "test.db")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(readings)").fetchall()}
    assert columns == {"date", "time", "ppv_kw", "sys_out_kw", "user_load_kw", "pac_to_user_kw"}
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py::test_init_db_creates_readings_table -q`
Expected: FAIL with `AssertionError` (the column set is empty).

- [ ] **Step 3: Add the `CREATE TABLE IF NOT EXISTS readings` statement from the spec to `SCHEMA_SQL`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/db/schema.py tests/test_db.py
git commit -m "feat: add readings table for raw 5-minute Growatt data"
```

---

### Task 2: `insert_readings` and `has_readings`

**Confidence:** 95%. The Growatt payload shape is known from live data (string kW values keyed by `HH:MM`, plus non-dict keys), and the conversion rule is pinned by test.

**Files:**
- Modify: `src/db/queries.py` (append after `get_actuals_range`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: table `readings` from Task 1.
- Produces: `insert_readings(conn: sqlite3.Connection, dt: date, hourly: dict) -> None` and `has_readings(conn: sqlite3.Connection, dt: date) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def _sample_hourly():
    return {
        "00:00": {"ppv": "0", "sysOut": "0.5", "userLoad": "0", "pacToUser": "0.5"},
        "00:05": {"ppv": None, "sysOut": "0.6", "userLoad": "0", "pacToUser": "0.6"},
        "12:00": {"ppv": "3.2", "sysOut": "1.1", "userLoad": "0.4"},
        "summary": "not a reading",
    }


def test_insert_readings_stores_each_five_minute_reading(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_readings
    conn = init_db(tmp_path / "test.db")
    insert_readings(conn, date(2026, 10, 2), _sample_hourly())
    rows = conn.execute(
        "SELECT time, ppv_kw, sys_out_kw, user_load_kw, pac_to_user_kw "
        "FROM readings WHERE date = '2026-10-02' ORDER BY time").fetchall()
    assert [tuple(r) for r in rows] == [
        ("00:00", 0.0, 0.5, 0.0, 0.5),
        ("00:05", 0.0, 0.6, 0.0, 0.6),   # null ppv stored as 0.0
        ("12:00", 3.2, 1.1, 0.4, 0.0),   # missing pacToUser stored as 0.0
    ]
    conn.close()


def test_insert_readings_twice_is_idempotent(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_readings
    conn = init_db(tmp_path / "test.db")
    insert_readings(conn, date(2026, 10, 2), _sample_hourly())
    insert_readings(conn, date(2026, 10, 2), _sample_hourly())
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 3
    conn.close()


def test_has_readings_reports_presence_for_a_day(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_readings, has_readings
    conn = init_db(tmp_path / "test.db")
    assert has_readings(conn, date(2026, 10, 2)) is False
    insert_readings(conn, date(2026, 10, 2), _sample_hourly())
    assert has_readings(conn, date(2026, 10, 2)) is True
    assert has_readings(conn, date(2026, 10, 3)) is False
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -q -k readings`
Expected: 3 FAIL with `ImportError: cannot import name 'insert_readings'`.

- [ ] **Step 3: Implement both functions in `src/db/queries.py`**

`insert_readings`: iterate `sorted(hourly.items())`, skip values that are not dicts, build one tuple per reading using the Global Constraints conversion, write with `INSERT OR REPLACE INTO readings (date, time, ppv_kw, sys_out_kw, user_load_kw, pac_to_user_kw)` via `conn.executemany`, then `conn.commit()`.

`has_readings`: `SELECT 1 FROM readings WHERE date = ? LIMIT 1`, return `fetchone() is not None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/db/queries.py tests/test_db.py
git commit -m "feat: insert_readings and has_readings queries"
```

---

### Task 3: Backfill stores readings alongside daily totals

**Confidence:** 90%. Restructures an existing function with eight tests around it; the only uncertainty is whether the pre-existing `test_nightly_skips_when_manual_already_set` still passes unchanged, which Step 4 checks.

**Files:**
- Modify: `src/orchestrator.py` (`backfill_actuals_for_day`, currently lines 27-123; the import block at line 10)
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `insert_readings`, `has_readings` from Task 2; existing `get_actuals`, `insert_actuals`.
- Produces: `backfill_actuals_for_day(conn, growatt_client, config, day: date) -> bool` with the five-step behaviour from the spec. Signature unchanged, so `_backfill_actuals` and `scripts/backfill_actuals.py` need no edits.

- [ ] **Step 1: Write the failing tests**

Add a module-level helper and four tests. `config` is the existing fixture from `tests/conftest.py`.

```python
def _growatt_with(hourly):
    client = MagicMock()
    client.get_hourly_data.return_value = hourly
    return client


def _two_readings():
    return {
        "08:00": {"ppv": "1.0", "sysOut": "0.5", "userLoad": "0", "pacToUser": "0"},
        "20:00": {"ppv": "0", "sysOut": "1.2", "userLoad": "0", "pacToUser": "1.2"},
    }


def test_backfill_stores_readings_for_day_with_existing_totals(tmp_path, config):
    from src.orchestrator import backfill_actuals_for_day
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals, has_readings
    conn = init_db(tmp_path / "test.db")
    day = date(2026, 7, 10)
    insert_actuals(conn, day, 35.0, 25.0, 3.0, 5.0, "12:00", 20, 95)
    assert backfill_actuals_for_day(conn, _growatt_with(_two_readings()), config, day) is True
    assert has_readings(conn, day) is True
    assert get_actuals(conn, day)["total_solar_generation_kwh"] == 35.0  # totals untouched
    conn.close()


def test_backfill_stores_totals_and_readings_for_new_day(tmp_path, config):
    from src.orchestrator import backfill_actuals_for_day
    from src.db.schema import init_db
    from src.db.queries import get_actuals, has_readings
    conn = init_db(tmp_path / "test.db")
    day = date(2026, 7, 10)
    assert backfill_actuals_for_day(conn, _growatt_with(_two_readings()), config, day) is True
    assert has_readings(conn, day) is True
    assert get_actuals(conn, day)["total_solar_generation_kwh"] == pytest.approx(1.0 / 12)
    conn.close()


def test_backfill_skips_growatt_when_day_is_complete(tmp_path, config):
    from src.orchestrator import backfill_actuals_for_day
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, insert_readings
    conn = init_db(tmp_path / "test.db")
    day = date(2026, 7, 10)
    insert_actuals(conn, day, 35.0, 25.0, 3.0, 5.0, "12:00", 20, 95)
    insert_readings(conn, day, _two_readings())
    client = _growatt_with(_two_readings())
    assert backfill_actuals_for_day(conn, client, config, day) is False
    client.get_hourly_data.assert_not_called()
    conn.close()


def test_backfill_raises_and_stores_nothing_when_no_readings(tmp_path, config):
    from src.orchestrator import backfill_actuals_for_day
    from src.db.schema import init_db
    from src.db.queries import has_readings, get_actuals
    conn = init_db(tmp_path / "test.db")
    day = date(2026, 7, 10)
    with pytest.raises(ValueError):
        backfill_actuals_for_day(conn, _growatt_with({"summary": "x"}), config, day)
    assert has_readings(conn, day) is False
    assert get_actuals(conn, day) is None
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -q -k backfill`
Expected: the first and third tests FAIL (`False` returned, or `get_hourly_data` called); the second and fourth PASS already. That is correct: they pin behaviour that must survive the change.

- [ ] **Step 3: Restructure `backfill_actuals_for_day` to the spec's five steps**

Import `insert_readings` and `has_readings` alongside the existing query imports. Compute `existing = get_actuals(conn, day)` and `readings_present = has_readings(conn, day)` up front; return `False` when both are truthy. After the fetch and the empty check, call `insert_readings` when readings are absent, and wrap the existing totals computation in `if existing is None:`. Rename the local `yesterday` to `day` while there, since the function no longer refers to yesterday.

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `python -m pytest tests/ -q`
Expected: all pass, including `test_nightly_skips_when_manual_already_set`, which still expects `get_hourly_data` to be called for an empty database.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: backfill stores raw readings alongside daily totals"
```

---

### Task 4: Populate readings for existing history

**Confidence:** 85%. Depends on the live Growatt API: 91 calls succeeded earlier today, but retention moves daily, so the oldest day may have expired and the `no data` count may differ from the expected line. The daily-totals check is the real pass criterion.

**Files:**
- None modified. Runs `scripts/backfill_actuals.py` against `data/battery.db`.

**Interfaces:**
- Consumes: Task 3's `backfill_actuals_for_day` via the unchanged script.

- [ ] **Step 1: Record the current daily totals so the run can be checked against them**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('data/battery.db'); print(c.execute('select count(*), round(sum(total_solar_generation_kwh),3), round(sum(expensive_consumption_kwh),3) from actuals').fetchone())"
```
Expected: `(91, <solar sum>, <consumption sum>)`. Note the three values.

- [ ] **Step 2: Run the backfill**

Run: `python scripts\backfill_actuals.py`
Expected: ends with `Done. Added 91, already present 0, no data 5.` and takes a few minutes. The `Added` count is 91 because the function now returns `True` when it stores readings for a day that already had totals.

- [ ] **Step 3: Verify readings landed and totals are unchanged**

Run:
```bash
python -c "import sqlite3; c=sqlite3.connect('data/battery.db'); print(c.execute('select count(distinct date), min(date), max(date), count(*) from readings').fetchone()); print(c.execute('select count(*) from actuals a where not exists (select 1 from readings r where r.date=a.date)').fetchone()); print(c.execute('select count(*), round(sum(total_solar_generation_kwh),3), round(sum(expensive_consumption_kwh),3) from actuals').fetchone())"
```
Expected: first line `(91, '2026-07-04', '2026-10-02', N)` with N between 26000 and 26208; second line `(0,)`; third line identical to Step 1.

- [ ] **Step 4: Confirm a second run is a no-op**

Run: `python scripts\backfill_actuals.py 3`
Expected: `Done. Added 0, already present 3, no data 0.`

No commit: the database is gitignored.
