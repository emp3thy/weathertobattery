# Cost-Optimised Charge Calculator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current charge calculator with a data-driven model that uses weather-matched historical generation, expensive-hours consumption, and removes the feedback loop and winter override.

**Architecture:** Five sequential tasks: (1) schema migration adding weather_condition and expensive_consumption_kwh columns, (2) historical weather backfill script using Open-Meteo archive API, (3) new calculator engine using consumption-minus-generation gap, (4) updated orchestrator removing feedback/winter/bootstrap paths, (5) cleanup of dead code and config. Each task builds on the previous and produces a working, testable state.

**Tech Stack:** Python 3.12, SQLite, Open-Meteo archive API, pytest, existing growattServer library.

---

### Task 1: Schema migration — add weather_condition and expensive_consumption_kwh columns

**Files:**
- Modify: `src/db/schema.py`
- Modify: `src/db/queries.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing test for new columns**

Add to `tests/test_db.py`:

```python
def test_actuals_has_weather_and_expensive_consumption_columns(tmp_path):
    from src.db.schema import init_db
    conn = init_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO actuals (date, total_solar_generation_kwh, total_consumption_kwh, "
        "grid_import_kwh, grid_export_kwh, weather_condition, expensive_consumption_kwh) "
        "VALUES ('2026-03-26', 20.0, 30.0, 5.0, 2.0, 'sunny', 18.5)"
    )
    row = conn.execute("SELECT weather_condition, expensive_consumption_kwh FROM actuals WHERE date='2026-03-26'").fetchone()
    assert row["weather_condition"] == "sunny"
    assert row["expensive_consumption_kwh"] == 18.5
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py::test_actuals_has_weather_and_expensive_consumption_columns -v`
Expected: FAIL — column does not exist.

- [ ] **Step 3: Add columns to schema**

In `src/db/schema.py`, update the `actuals` CREATE TABLE to add the two new columns:

```python
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    date TEXT PRIMARY KEY,
    forecast_summary TEXT NOT NULL,
    forecast_detail TEXT NOT NULL,
    charge_level_set INTEGER NOT NULL,
    base_charge_level INTEGER NOT NULL,
    feedback_adjustment INTEGER NOT NULL DEFAULT 0,
    adjustment_reason TEXT,
    current_soc_at_decision INTEGER,
    month INTEGER NOT NULL,
    weather_provider_used TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actuals (
    date TEXT PRIMARY KEY,
    total_solar_generation_kwh REAL NOT NULL,
    total_consumption_kwh REAL NOT NULL,
    grid_import_kwh REAL NOT NULL,
    grid_export_kwh REAL NOT NULL,
    peak_solar_hour TEXT,
    battery_min_soc INTEGER,
    battery_max_soc INTEGER,
    weather_condition TEXT,
    expensive_consumption_kwh REAL
);

CREATE TABLE IF NOT EXISTS adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('up', 'down')),
    amount INTEGER NOT NULL,
    trigger TEXT NOT NULL CHECK(trigger IN ('grid_draw', 'surplus_export')),
    previous_day_weather TEXT,
    tomorrow_forecast TEXT,
    grid_draw_kwh REAL,
    surplus_export_kwh REAL
);
"""
```

Also add a migration function to handle the existing database (new columns won't exist on the live DB). Add to `schema.py`:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that may not exist on older databases."""
    cursor = conn.execute("PRAGMA table_info(actuals)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "weather_condition" not in existing_cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN weather_condition TEXT")
    if "expensive_consumption_kwh" not in existing_cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN expensive_consumption_kwh REAL")
    conn.commit()
```

Call `_migrate(conn)` at the end of `init_db`, after `executescript(SCHEMA_SQL)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db.py::test_actuals_has_weather_and_expensive_consumption_columns -v`
Expected: PASS

- [ ] **Step 5: Write failing test for updated insert_actuals**

Add to `tests/test_db.py`:

```python
def test_insert_actuals_with_weather_and_expensive_consumption(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 26), 20.0, 30.0, 5.0, 2.0,
                   "10:00", 15, 95, weather_condition="sunny",
                   expensive_consumption_kwh=18.5)
    row = get_actuals(conn, date(2026, 3, 26))
    assert row["weather_condition"] == "sunny"
    assert row["expensive_consumption_kwh"] == 18.5
    conn.close()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py::test_insert_actuals_with_weather_and_expensive_consumption -v`
Expected: FAIL — `insert_actuals` doesn't accept the new parameters.

- [ ] **Step 7: Update insert_actuals to accept new columns**

In `src/db/queries.py`, update `insert_actuals`:

```python
def insert_actuals(conn: sqlite3.Connection, dt: date,
                   solar_gen: float, consumption: float,
                   grid_import: float, grid_export: float,
                   peak_solar_hour: str | None, min_soc: int | None,
                   max_soc: int | None, weather_condition: str | None = None,
                   expensive_consumption_kwh: float | None = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO actuals (date, total_solar_generation_kwh,
            total_consumption_kwh, grid_import_kwh, grid_export_kwh,
            peak_solar_hour, battery_min_soc, battery_max_soc,
            weather_condition, expensive_consumption_kwh)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(dt), solar_gen, consumption, grid_import, grid_export,
          peak_solar_hour, min_soc, max_soc, weather_condition,
          expensive_consumption_kwh))
    conn.commit()
```

Also add a new query function for the calculator:

```python
def get_generation_by_weather(conn: sqlite3.Connection, month: int,
                               condition: str) -> list[float]:
    """Get solar generation for days matching a weather condition in a given month."""
    cursor = conn.execute(
        "SELECT total_solar_generation_kwh FROM actuals "
        "WHERE CAST(strftime('%m', date) AS INTEGER) = ? AND weather_condition = ? "
        "ORDER BY date DESC",
        (month, condition))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_weather_wide(conn: sqlite3.Connection, month: int,
                                    condition: str) -> list[float]:
    """Get solar generation for days matching condition in month +/- 1."""
    months = [(month - 2) % 12 + 1, month, month % 12 + 1]
    placeholders = ",".join("?" * len(months))
    cursor = conn.execute(
        f"SELECT total_solar_generation_kwh FROM actuals "
        f"WHERE CAST(strftime('%m', date) AS INTEGER) IN ({placeholders}) "
        f"AND weather_condition = ? ORDER BY date DESC",
        (*months, condition))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_condition(conn: sqlite3.Connection,
                                 condition: str) -> list[float]:
    """Get solar generation for all days matching a weather condition."""
    cursor = conn.execute(
        "SELECT total_solar_generation_kwh FROM actuals "
        "WHERE weather_condition = ? ORDER BY date DESC",
        (condition,))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_month(conn: sqlite3.Connection,
                             month: int) -> list[float]:
    """Get solar generation for all days in a given month (any weather)."""
    cursor = conn.execute(
        "SELECT total_solar_generation_kwh FROM actuals "
        "WHERE CAST(strftime('%m', date) AS INTEGER) = ? ORDER BY date DESC",
        (month,))
    return [row[0] for row in cursor.fetchall()]


def get_recent_expensive_consumption(conn: sqlite3.Connection,
                                      days: int = 7) -> list[float]:
    """Get expensive-hours consumption for the most recent N days that have it."""
    cursor = conn.execute(
        "SELECT expensive_consumption_kwh FROM actuals "
        "WHERE expensive_consumption_kwh IS NOT NULL "
        "ORDER BY date DESC LIMIT ?",
        (days,))
    return [row[0] for row in cursor.fetchall()]
```

- [ ] **Step 8: Run all test_db tests**

Run: `python -m pytest tests/test_db.py -v`
Expected: All PASS

- [ ] **Step 9: Write tests for new query functions**

Add to `tests/test_db.py`:

```python
def test_get_generation_by_weather(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_weather
    conn = init_db(tmp_path / "test.db")
    # March sunny days
    insert_actuals(conn, date(2026, 3, 10), 25.0, 30.0, 5.0, 3.0,
                   None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 3, 12), 28.0, 30.0, 5.0, 4.0,
                   None, None, None, weather_condition="sunny")
    # March cloudy day
    insert_actuals(conn, date(2026, 3, 11), 12.0, 30.0, 8.0, 0.5,
                   None, None, None, weather_condition="cloudy")
    # April sunny day (different month)
    insert_actuals(conn, date(2026, 4, 5), 30.0, 28.0, 3.0, 5.0,
                   None, None, None, weather_condition="sunny")

    result = get_generation_by_weather(conn, 3, "sunny")
    assert len(result) == 2
    assert 25.0 in result
    assert 28.0 in result
    conn.close()


def test_get_generation_by_weather_wide(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_weather_wide
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 2, 15), 15.0, 30.0, 8.0, 1.0,
                   None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 3, 15), 12.0, 30.0, 9.0, 0.5,
                   None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 4, 15), 18.0, 28.0, 6.0, 1.5,
                   None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 6, 15), 8.0, 25.0, 10.0, 0.0,
                   None, None, None, weather_condition="cloudy")

    result = get_generation_by_weather_wide(conn, 3, "cloudy")
    assert len(result) == 3  # Feb, Mar, Apr — not June
    conn.close()


def test_get_recent_expensive_consumption(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_recent_expensive_consumption
    conn = init_db(tmp_path / "test.db")
    # Some days with expensive consumption, some without
    insert_actuals(conn, date(2026, 3, 20), 20.0, 30.0, 5.0, 2.0,
                   None, None, None, expensive_consumption_kwh=22.0)
    insert_actuals(conn, date(2026, 3, 21), 18.0, 28.0, 6.0, 1.0,
                   None, None, None, expensive_consumption_kwh=20.5)
    insert_actuals(conn, date(2026, 3, 22), 15.0, 25.0, 8.0, 0.5,
                   None, None, None)  # No expensive consumption data

    result = get_recent_expensive_consumption(conn, days=7)
    assert len(result) == 2
    assert result[0] == 20.5  # Most recent first
    assert result[1] == 22.0
    conn.close()
```

- [ ] **Step 10: Run new query tests**

Run: `python -m pytest tests/test_db.py -v`
Expected: All PASS

- [ ] **Step 11: Commit**

```bash
git add src/db/schema.py src/db/queries.py tests/test_db.py
git commit -m "feat: add weather_condition and expensive_consumption_kwh to actuals schema"
```

---

### Task 2: Historical weather backfill script

**Files:**
- Create: `src/weather/historical.py`
- Create: `scripts/backfill_weather.py`
- Create: `tests/test_historical_weather.py`

- [ ] **Step 1: Write failing test for historical weather classification**

Create `tests/test_historical_weather.py`:

```python
import pytest
from datetime import date


def test_classify_day_sunny():
    from src.weather.historical import classify_day
    # Low cloud cover, no precipitation
    hourly_cloud = [10, 15, 20, 25, 15, 10, 20, 15, 10, 20, 25, 15]
    hourly_precip = [0.0] * 12
    result = classify_day(hourly_cloud, hourly_precip)
    assert result == "sunny"


def test_classify_day_rainy():
    from src.weather.historical import classify_day
    hourly_cloud = [80, 90, 95, 85, 90, 80, 85, 90, 95, 80, 85, 90]
    hourly_precip = [2.0, 3.0, 1.5, 0.5, 2.0, 3.5, 1.0, 2.0, 0.0, 1.5, 2.0, 3.0]
    result = classify_day(hourly_cloud, hourly_precip)
    assert result == "rainy"


def test_classify_day_cloudy():
    from src.weather.historical import classify_day
    hourly_cloud = [50, 60, 55, 45, 50, 65, 40, 55, 60, 50, 45, 55]
    hourly_precip = [0.0] * 12
    result = classify_day(hourly_cloud, hourly_precip)
    assert result == "cloudy"


def test_fetch_historical_weather_builds_url():
    from src.weather.historical import build_archive_url
    url = build_archive_url(51.4067, 0.0481, date(2025, 6, 1), date(2025, 6, 30), "Europe/London")
    assert "archive-api.open-meteo.com" in url
    assert "start_date=2025-06-01" in url
    assert "end_date=2025-06-30" in url
    assert "cloud_cover" in url
    assert "precipitation" in url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_historical_weather.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement historical weather module**

Create `src/weather/historical.py`:

```python
import requests
from datetime import date, timedelta

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def build_archive_url(lat: float, lon: float, start: date, end: date, timezone: str) -> str:
    params = (
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly=cloud_cover,precipitation"
        f"&daily=sunrise,sunset"
        f"&timezone={timezone}"
    )
    return f"{ARCHIVE_URL}?{params}"


def classify_day(hourly_cloud: list[float], hourly_precip: list[float]) -> str:
    """Classify a day as sunny/cloudy/rainy using the same logic as forecast bucketing.

    Args:
        hourly_cloud: Cloud cover % for each solar hour of the day.
        hourly_precip: Precipitation mm for each solar hour of the day.
    """
    if not hourly_cloud:
        return "cloudy"

    avg_cloud = sum(hourly_cloud) / len(hourly_cloud)
    rainy_hours = sum(1 for p in hourly_precip if p > 0.1)
    rainy_fraction = rainy_hours / len(hourly_precip)

    if rainy_fraction >= 0.5:
        return "rainy"
    if avg_cloud < 30:
        return "sunny"
    return "cloudy"


def fetch_historical_weather(lat: float, lon: float, start: date, end: date,
                              timezone: str) -> dict[str, str]:
    """Fetch historical weather and classify each day.

    Returns:
        Dict mapping date string (YYYY-MM-DD) to condition (sunny/cloudy/rainy).
    """
    url = build_archive_url(lat, lon, start, end, timezone)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    hourly = data["hourly"]
    daily = data["daily"]
    times = hourly["time"]
    clouds = hourly["cloud_cover"]
    precips = hourly["precipitation"]

    # Parse sunrise/sunset per day
    sunrises = {s[:10]: int(s[11:13]) for s in daily["sunrise"]}
    sunsets = {s[:10]: int(s[11:13]) for s in daily["sunset"]}

    # Group hourly data by date, filtered to solar hours
    days: dict[str, tuple[list[float], list[float]]] = {}
    for i, time_str in enumerate(times):
        day_str = time_str[:10]
        hour = int(time_str[11:13])
        sunrise_h = sunrises.get(day_str, 6)
        sunset_h = sunsets.get(day_str, 20)
        if hour < sunrise_h or hour > sunset_h:
            continue
        if day_str not in days:
            days[day_str] = ([], [])
        days[day_str][0].append(clouds[i] if clouds[i] is not None else 50)
        days[day_str][1].append(precips[i] if precips[i] is not None else 0)

    return {day_str: classify_day(c, p) for day_str, (c, p) in days.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_historical_weather.py -v`
Expected: All PASS

- [ ] **Step 5: Write the backfill script**

Create `scripts/backfill_weather.py`:

```python
"""Backfill weather_condition on historical actuals rows.

Usage: python scripts/backfill_weather.py

Fetches historical weather from Open-Meteo archive API in monthly chunks
and updates the weather_condition column on existing actuals rows.
"""
import sys
import time
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.schema import init_db
from src.weather.historical import fetch_historical_weather
from src.config import load_config


def backfill(db_path: Path, config_path: Path) -> None:
    config = load_config(config_path)
    conn = init_db(db_path)

    # Find dates that need weather backfill
    cursor = conn.execute(
        "SELECT date FROM actuals WHERE weather_condition IS NULL ORDER BY date"
    )
    dates_to_fill = [row[0] for row in cursor.fetchall()]

    if not dates_to_fill:
        print("No rows need weather backfill.")
        return

    print(f"Found {len(dates_to_fill)} rows needing weather data.")
    first = date.fromisoformat(dates_to_fill[0])
    last = date.fromisoformat(dates_to_fill[-1])

    # Fetch in monthly chunks to stay within API limits
    chunk_start = first.replace(day=1)
    updated = 0

    while chunk_start <= last:
        # End of month
        if chunk_start.month == 12:
            chunk_end = chunk_start.replace(year=chunk_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            chunk_end = chunk_start.replace(month=chunk_start.month + 1, day=1) - timedelta(days=1)
        chunk_end = min(chunk_end, last)

        print(f"  Fetching {chunk_start} to {chunk_end}...", end=" ", flush=True)
        try:
            conditions = fetch_historical_weather(
                config.location.latitude, config.location.longitude,
                chunk_start, chunk_end, config.location.timezone
            )
            for day_str, condition in conditions.items():
                conn.execute(
                    "UPDATE actuals SET weather_condition = ? WHERE date = ? AND weather_condition IS NULL",
                    (condition, day_str)
                )
                updated += 1
            conn.commit()
            print(f"{len(conditions)} days classified.")
        except Exception as e:
            print(f"FAILED: {e}")

        # Next month
        if chunk_start.month == 12:
            chunk_start = chunk_start.replace(year=chunk_start.year + 1, month=1, day=1)
        else:
            chunk_start = chunk_start.replace(month=chunk_start.month + 1, day=1)

        # Rate limit: 1 second between requests
        time.sleep(1)

    print(f"Done. Updated {updated} rows.")
    conn.close()


if __name__ == "__main__":
    backfill(Path("data/battery.db"), Path("config.yaml"))
```

- [ ] **Step 6: Run the classification tests again to confirm**

Run: `python -m pytest tests/test_historical_weather.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/weather/historical.py scripts/backfill_weather.py tests/test_historical_weather.py
git commit -m "feat: historical weather backfill via Open-Meteo archive API"
```

---

### Task 3: New charge calculator

**Files:**
- Modify: `src/calculator/engine.py`
- Rewrite: `tests/test_calculator.py`

- [ ] **Step 1: Write failing tests for the new calculator**

Rewrite `tests/test_calculator.py`:

```python
import pytest
import sqlite3
from datetime import date, time
from src.weather.interface import DayForecast, HourlyForecast


def _make_forecast(target_date, condition="sunny", temp=22, cloud=20, radiation=500):
    return DayForecast(
        date=target_date, sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=cloud, solar_radiation_wm2=radiation,
                            precipitation_probability_pct=5, temperature_c=temp)
            for h in range(6, 21)
        ],
        condition=condition, max_temperature_c=temp
    )


def _make_db(tmp_path):
    from src.db.schema import init_db
    return init_db(tmp_path / "test.db")


def _populate_generation(conn, month, condition, values):
    """Insert actuals rows with given generation values for a month/condition."""
    from src.db.queries import insert_actuals
    for i, val in enumerate(values, 1):
        insert_actuals(conn, date(2025, month, min(i, 28)), val, 30.0, 5.0, 2.0,
                       None, None, None, weather_condition=condition)


def _populate_expensive_consumption(conn, values):
    """Insert recent actuals rows with expensive consumption."""
    from src.db.queries import insert_actuals
    for i, val in enumerate(values):
        insert_actuals(conn, date(2026, 3, 20 + i), 20.0, 30.0, 5.0, 2.0,
                       None, None, None, expensive_consumption_kwh=val)


def test_manual_override(tmp_path, config):
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML.replace("manual_override: null", "manual_override: 85"))
    config = load_config(config_file)
    conn = _make_db(tmp_path)
    forecast = _make_forecast(date(2026, 6, 15))
    result = calculate_charge(config=config, forecast=forecast, current_soc=20, conn=conn)
    assert result.charge_level == 85
    assert "manual" in result.reason.lower()
    conn.close()


def test_sunny_day_with_good_generation_charges_low(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Historical: sunny March days generate ~30 kWh
    _populate_generation(conn, 3, "sunny", [28.0, 30.0, 32.0, 29.0, 31.0])
    # Recent expensive consumption: ~20 kWh
    _populate_expensive_consumption(conn, [20.0, 19.5, 21.0, 20.5])
    forecast = _make_forecast(date(2026, 3, 27), condition="sunny")
    # Current SOC 50% = ~6 kWh in battery
    result = calculate_charge(config=config, forecast=forecast, current_soc=50, conn=conn)
    # Expected gen ~30, consumption ~20, SOC 6 kWh => gap = 20 - 30 - 6 = negative => low charge
    assert result.charge_level <= 30
    conn.close()


def test_cloudy_day_with_low_generation_charges_high(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Historical: cloudy March days generate ~12 kWh
    _populate_generation(conn, 3, "cloudy", [11.0, 13.0, 12.0, 12.5, 11.5])
    # Recent expensive consumption: ~25 kWh
    _populate_expensive_consumption(conn, [25.0, 24.5, 26.0, 25.5])
    forecast = _make_forecast(date(2026, 3, 27), condition="cloudy", cloud=60, radiation=200)
    result = calculate_charge(config=config, forecast=forecast, current_soc=10, conn=conn)
    # Expected gen ~12, consumption ~25, SOC 1.2 kWh => gap = 25 - 12 - 1.2 = 11.8 kWh => ~99%
    assert result.charge_level >= 80
    conn.close()


def test_winter_day_uses_data_not_override(tmp_path, config):
    """Winter days should use the data-driven model, not a blanket 100%."""
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Historical: cloudy December days generate ~3 kWh
    _populate_generation(conn, 12, "cloudy", [2.5, 3.0, 3.5, 2.0, 4.0])
    _populate_expensive_consumption(conn, [18.0, 17.5, 19.0, 18.5])
    forecast = _make_forecast(date(2026, 12, 15), condition="cloudy", cloud=70, radiation=50)
    result = calculate_charge(config=config, forecast=forecast, current_soc=10, conn=conn)
    # gap = 18 - 3 - 1.2 = 13.8 => 100% (naturally high, no override needed)
    assert result.charge_level >= 90
    assert "winter" not in result.reason.lower()
    conn.close()


def test_falls_back_to_wider_month_window(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Only 2 sunny March days (below threshold of 5)
    _populate_generation(conn, 3, "sunny", [28.0, 30.0])
    # But plenty of sunny Feb and Apr days
    from src.db.queries import insert_actuals
    for i, val in enumerate([25.0, 27.0, 26.0, 28.0, 24.0], 1):
        insert_actuals(conn, date(2025, 2, i), val, 30.0, 5.0, 3.0,
                       None, None, None, weather_condition="sunny")
    _populate_expensive_consumption(conn, [20.0, 19.5, 21.0, 20.5])
    forecast = _make_forecast(date(2026, 3, 27), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast, current_soc=50, conn=conn)
    # Should find data from wider window and produce a reasonable result
    assert 0 <= result.charge_level <= 100
    conn.close()


def test_falls_back_to_total_consumption_when_no_expensive(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    _populate_generation(conn, 3, "cloudy", [12.0, 13.0, 11.0, 12.5, 11.5])
    # Insert rows with total_consumption but no expensive_consumption
    from src.db.queries import insert_actuals
    for i in range(5):
        insert_actuals(conn, date(2026, 3, 20 + i), 15.0, 28.0, 6.0, 1.0,
                       None, None, None)
    forecast = _make_forecast(date(2026, 3, 27), condition="cloudy", cloud=55)
    result = calculate_charge(config=config, forecast=forecast, current_soc=20, conn=conn)
    assert 0 <= result.charge_level <= 100
    assert "total consumption" in result.reason.lower()
    conn.close()


def test_charge_clamped_to_0_100(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Sunny days with massive generation => negative gap
    _populate_generation(conn, 7, "sunny", [40.0, 42.0, 38.0, 41.0, 39.0])
    _populate_expensive_consumption(conn, [15.0, 14.0, 16.0, 15.5])
    forecast = _make_forecast(date(2026, 7, 15), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast, current_soc=80, conn=conn)
    assert result.charge_level >= 0
    assert result.charge_level <= 100
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: FAIL — new `calculate_charge` signature doesn't exist yet.

- [ ] **Step 3: Implement the new calculator**

Rewrite `src/calculator/engine.py`:

```python
from dataclasses import dataclass
from datetime import date
import sqlite3

from ..config import Config
from ..weather.interface import DayForecast
from ..db.queries import (
    get_generation_by_weather, get_generation_by_weather_wide,
    get_generation_by_condition, get_generation_by_month,
    get_recent_expensive_consumption,
)


@dataclass
class ChargeResult:
    charge_level: int
    reason: str


def _estimate_generation(conn: sqlite3.Connection, month: int,
                          condition: str) -> tuple[float, str]:
    """Estimate expected solar generation from weather-matched historical data.

    Tries progressively wider searches:
    1. Same month + same condition (need >= 5 days)
    2. Adjacent months + same condition (need >= 5 days)
    3. Any month + same condition (need >= 5 days)
    4. Same month, any condition (last resort)

    Returns (avg_generation_kwh, description of source).
    """
    # 1. Same month, same condition
    vals = get_generation_by_weather(conn, month, condition)
    if len(vals) >= 5:
        avg = sum(vals) / len(vals)
        return avg, f"{condition} days in month {month} ({len(vals)} days, avg {avg:.1f}kWh)"

    # 2. Adjacent months, same condition
    vals = get_generation_by_weather_wide(conn, month, condition)
    if len(vals) >= 5:
        avg = sum(vals) / len(vals)
        return avg, f"{condition} days in months {(month-2)%12+1}-{month%12+1} ({len(vals)} days, avg {avg:.1f}kWh)"

    # 3. Any month, same condition
    vals = get_generation_by_condition(conn, condition)
    if len(vals) >= 5:
        avg = sum(vals) / len(vals)
        return avg, f"{condition} days any month ({len(vals)} days, avg {avg:.1f}kWh)"

    # 4. Same month, any condition
    vals = get_generation_by_month(conn, month)
    if vals:
        avg = sum(vals) / len(vals)
        return avg, f"all days in month {month} ({len(vals)} days, avg {avg:.1f}kWh)"

    return 0.0, "no historical data"


def _estimate_consumption(conn: sqlite3.Connection) -> tuple[float, str]:
    """Estimate expected expensive-hours consumption.

    Uses recent expensive_consumption_kwh if available (>= 3 days),
    otherwise falls back to total_consumption_kwh.
    """
    vals = get_recent_expensive_consumption(conn, days=7)
    if len(vals) >= 3:
        avg = sum(vals) / len(vals)
        return avg, f"expensive-hours avg ({len(vals)} days, avg {avg:.1f}kWh)"

    # Fallback: total consumption from recent rows
    cursor = conn.execute(
        "SELECT total_consumption_kwh FROM actuals "
        "ORDER BY date DESC LIMIT 7"
    )
    vals = [row[0] for row in cursor.fetchall()]
    if vals:
        avg = sum(vals) / len(vals)
        return avg, f"total consumption fallback ({len(vals)} days, avg {avg:.1f}kWh)"

    return 0.0, "no consumption data"


def calculate_charge(
    config: Config,
    forecast: DayForecast,
    current_soc: int,
    conn: sqlite3.Connection,
) -> ChargeResult:
    target_date = forecast.date

    # Manual override
    if config.manual_override is not None:
        return ChargeResult(
            charge_level=config.manual_override,
            reason="Manual override applied"
        )

    # Estimate consumption during expensive hours
    expected_consumption, consumption_source = _estimate_consumption(conn)

    # Estimate generation from weather-matched historical data
    expected_generation, generation_source = _estimate_generation(
        conn, target_date.month, forecast.condition
    )

    # Current battery energy
    current_soc_kwh = (current_soc / 100) * config.battery.usable_capacity_kwh

    # Gap = what the battery needs to cover
    gap_kwh = expected_consumption - expected_generation - current_soc_kwh

    # Convert to charge percentage
    usable = config.battery.usable_capacity_kwh
    if usable > 0:
        charge_pct = (gap_kwh / usable) * 100
    else:
        charge_pct = 100

    charge_level = int(max(0, min(100, charge_pct)))

    reason_parts = [
        f"Expected consumption: {expected_consumption:.1f}kWh ({consumption_source})",
        f"Expected generation: {expected_generation:.1f}kWh ({generation_source})",
        f"Current SOC: {current_soc}% ({current_soc_kwh:.1f}kWh)",
        f"Gap: {gap_kwh:.1f}kWh",
        f"Charge level: {charge_level}%",
    ]
    if "total consumption" in consumption_source:
        reason_parts.append("Note: using total consumption fallback (no expensive-hours data)")

    return ChargeResult(
        charge_level=charge_level,
        reason=". ".join(reason_parts)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: replace calculator with consumption-minus-generation model"
```

---

### Task 4: Update orchestrator — remove feedback, winter override, bootstrap

**Files:**
- Modify: `src/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write new orchestrator tests**

Rewrite `tests/test_orchestrator.py`:

```python
import pytest
from unittest.mock import MagicMock
from datetime import date, time


def _make_forecast(target_date, condition="sunny"):
    from src.weather.interface import DayForecast, HourlyForecast
    return DayForecast(
        date=target_date, sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                            precipitation_probability_pct=5, temperature_c=22)
            for h in range(6, 21)
        ],
        condition=condition, max_temperature_c=22
    )


def _seed_actuals(conn):
    """Seed enough historical data for the calculator to work."""
    from src.db.queries import insert_actuals
    for i in range(1, 15):
        insert_actuals(conn, date(2026, 7, i), 35.0, 25.0, 3.0, 5.0,
                       "12:00", 20, 95, weather_condition="sunny",
                       expensive_consumption_kwh=20.0)


def test_orchestrator_sets_charge_and_logs(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    forecast = _make_forecast(date(2026, 7, 15))
    mock_weather = MagicMock()
    mock_weather.get_forecast.return_value = forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 15
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["success"] is True
    assert 0 <= result["charge_level"] <= 100
    mock_growatt.set_charge_soc.assert_called_once()

    from src.db.queries import get_decision
    decision = get_decision(conn, date(2026, 7, 15))
    assert decision is not None
    assert decision["charge_level_set"] == result["charge_level"]

    assert (tmp_path / "last_updated.md").exists()
    conn.close()


def test_orchestrator_weather_failure_falls_back(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    mock_weather = MagicMock()
    mock_weather.get_forecast.side_effect = Exception("API down")

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 20
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["charge_level"] == 90
    assert "unavailable" in result["reason"].lower() or "fallback" in result["reason"].lower()
    conn.close()


def test_orchestrator_backfills_expensive_consumption(tmp_path, config):
    """Verify backfill calculates expensive consumption from 5-min data."""
    from src.orchestrator import run_nightly
    from src.db.schema import init_db
    from src.db.queries import get_actuals

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    forecast = _make_forecast(date(2026, 7, 16))
    mock_weather = MagicMock()
    mock_weather.get_forecast.return_value = forecast

    # Simulate 5-min data: sysOut (load) values for a full day
    hourly_data = {}
    for h in range(24):
        for m in range(0, 60, 5):
            time_str = f"{h:02d}:{m:02d}"
            hourly_data[time_str] = {
                "ppv": "1.0", "sysOut": "2.0", "userLoad": "0.5", "pacToUser": "0.3"
            }

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 30
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = hourly_data
    mock_growatt.get_daily_data.return_value = {
        "total_solar_kwh": 20.0, "total_load_kwh": 25.0, "total_grid_import_kwh": 5.0,
    }

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 16),
        project_root=tmp_path,
    )

    # Check yesterday (July 15) was backfilled with expensive consumption
    actual = get_actuals(conn, date(2026, 7, 15))
    assert actual is not None
    assert actual["expensive_consumption_kwh"] is not None
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — orchestrator still has old interface.

- [ ] **Step 3: Rewrite the orchestrator**

Replace `src/orchestrator.py`:

```python
import json
import logging
from datetime import date, timedelta, datetime
from pathlib import Path

from .config import Config
from .weather.interface import WeatherProvider, DayForecast
from .growatt.client import GrowattClient
from .calculator.engine import calculate_charge
from .db.queries import (
    upsert_decision, get_decision, get_actuals, insert_actuals
)

logger = logging.getLogger(__name__)


def _backfill_actuals(conn, growatt_client: GrowattClient, config: Config,
                      target_date: date) -> None:
    """Backfill yesterday's actuals including expensive-hours consumption."""
    yesterday = target_date - timedelta(days=1)
    existing = get_actuals(conn, yesterday)
    if existing:
        return

    try:
        hourly = growatt_client.get_hourly_data(yesterday)
        daily = growatt_client.get_daily_data(yesterday)

        grid_import_expensive = 0.0
        grid_export_total = 0.0
        expensive_consumption = 0.0
        peak_solar_hour = None
        peak_solar_val = 0.0

        for time_str in sorted(hourly.keys()):
            values = hourly[time_str]
            if not isinstance(values, dict):
                continue
            hour = int(time_str.split(":")[0])
            minute = int(time_str.split(":")[1])
            ppv = float(values.get("ppv", 0))
            pac_to_user = float(values.get("pacToUser", 0))
            sys_out = float(values.get("sysOut", 0))

            if ppv > peak_solar_val:
                peak_solar_val = ppv
                peak_solar_hour = time_str

            is_expensive = (hour > 5 or (hour == 5 and minute >= 30)) and \
                           (hour < 23 or (hour == 23 and minute <= 30))
            if is_expensive:
                grid_import_expensive += pac_to_user
                expensive_consumption += sys_out
            grid_export_total += sys_out

        grid_import_kwh = grid_import_expensive / 12
        grid_export_kwh = grid_export_total / 12
        expensive_consumption_kwh = expensive_consumption / 12

        # Get weather condition from the decision record for yesterday
        decision = get_decision(conn, yesterday)
        weather_condition = decision["forecast_summary"] if decision else None

        insert_actuals(
            conn, yesterday,
            solar_gen=daily.get("total_solar_kwh", 0),
            consumption=daily.get("total_load_kwh", 0),
            grid_import=grid_import_kwh,
            grid_export=grid_export_kwh,
            peak_solar_hour=peak_solar_hour,
            min_soc=None, max_soc=None,
            weather_condition=weather_condition,
            expensive_consumption_kwh=expensive_consumption_kwh,
        )
        logger.info(f"Backfilled actuals for {yesterday}")
    except Exception as e:
        logger.warning(f"Failed to backfill actuals for {yesterday}: {e}")


def _clear_manual_override(config_path: Path) -> None:
    import yaml
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    raw["manual_override"] = None
    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)


def _write_last_updated(path: Path, result: dict, forecast: DayForecast | None) -> None:
    lines = [
        f"# Battery Charge Update",
        f"",
        f"**Run time:** {result['timestamp']}",
        f"**Date setting for:** {result['target_date']}",
        f"**Charge level set:** {result['charge_level']}%",
        f"",
        f"## Reason",
        f"",
        result["reason"],
        f"",
    ]
    if forecast:
        lines.extend([
            f"## Tomorrow's Forecast",
            f"",
            f"- Condition: {forecast.condition}",
            f"- Sunrise: {forecast.sunrise}",
            f"- Sunset: {forecast.sunset}",
            f"- Max temperature: {forecast.max_temperature_c}C",
            f"- Solar hours: {len(forecast.hourly)}",
            f"",
        ])
    if result.get("errors"):
        lines.extend([
            f"## Errors",
            f"",
            *[f"- {e}" for e in result["errors"]],
            f"",
        ])
    (path / "last_updated.md").write_text("\n".join(lines))


def run_nightly(
    config: Config, conn, weather_provider: WeatherProvider,
    growatt_client: GrowattClient, target_date: date, project_root: Path,
) -> dict:
    timestamp = datetime.now().isoformat()
    errors = []
    forecast = None
    current_soc = None

    # Backfill yesterday's actuals
    _backfill_actuals(conn, growatt_client, config, target_date)

    # Read current SOC
    try:
        current_soc = growatt_client.get_current_soc()
    except Exception as e:
        logger.warning(f"Failed to read SOC: {e}")

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
                    time_module.sleep([5, 15][attempt])

        if forecast is None:
            charge_level = 90
            reason = "Weather API unavailable — fallback to 90%"
        else:
            calc_result = calculate_charge(
                config=config, forecast=forecast,
                current_soc=current_soc or 0, conn=conn,
            )
            charge_level = calc_result.charge_level
            reason = calc_result.reason

    # Set on Growatt
    try:
        growatt_client.set_charge_soc(charge_level)
    except Exception as e:
        logger.error(f"Failed to set charge: {e}")
        errors.append(f"Failed to set charge: {e}")

    # Log decision
    forecast_detail = json.dumps(
        [{"hour": h.hour, "cloud": h.cloud_cover_pct,
          "radiation": h.solar_radiation_wm2, "precip": h.precipitation_probability_pct}
         for h in forecast.hourly] if forecast else []
    )
    upsert_decision(
        conn, target_date,
        forecast_summary=forecast.condition if forecast else "unknown",
        forecast_detail=forecast_detail,
        charge_level_set=charge_level,
        base_charge_level=charge_level,
        feedback_adjustment=0,
        adjustment_reason=reason,
        current_soc=current_soc,
        month=target_date.month,
        weather_provider=config.weather.provider,
    )

    result = {
        "success": len(errors) == 0,
        "charge_level": charge_level,
        "reason": reason,
        "target_date": str(target_date),
        "timestamp": timestamp,
        "errors": errors,
    }

    _write_last_updated(project_root, result, forecast)
    return result
```

- [ ] **Step 4: Run orchestrator tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 5: Run all tests to check nothing else broke**

Run: `python -m pytest -v`
Expected: Some old tests may fail (feedback tests, old calculator tests) — that's expected and handled in Task 5.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: update orchestrator for new calculator, remove feedback/winter paths"
```

---

### Task 5: Remove dead code and update config

**Files:**
- Delete: `src/calculator/feedback.py`
- Delete: `tests/test_feedback.py`
- Modify: `src/config.py`
- Modify: `tests/conftest.py`
- Modify: `config.yaml`
- Modify: `src/dashboard/app.py`

- [ ] **Step 1: Delete feedback module and its tests**

```bash
rm src/calculator/feedback.py tests/test_feedback.py
```

- [ ] **Step 2: Remove unused imports from calculator __init__**

Check `src/calculator/__init__.py` for any re-exports of feedback. If it imports from feedback, remove those lines.

- [ ] **Step 3: Remove FeedbackConfig, BootstrapConfig, WinterOverrideConfig from config**

Update `src/config.py` — remove the three dataclasses and their references:

```python
from dataclasses import dataclass
from pathlib import Path
import yaml


class ConfigValidationError(Exception):
    pass


@dataclass
class LocationConfig:
    latitude: float
    longitude: float
    timezone: str


@dataclass
class GrowattConfig:
    username: str
    password: str
    plant_id: str
    device_sn: str
    server_url: str


@dataclass
class BatteryConfig:
    total_capacity_kwh: float
    usable_fraction: float

    @property
    def usable_capacity_kwh(self) -> float:
        return self.total_capacity_kwh * self.usable_fraction


@dataclass
class WeatherConfig:
    provider: str


@dataclass
class RatesConfig:
    cheap_pence_per_kwh: float
    expensive_pence_per_kwh: float
    export_pence_per_kwh: float
    cheap_start: str
    cheap_end: str


@dataclass
class DashboardConfig:
    port: int


@dataclass
class Config:
    location: LocationConfig
    growatt: GrowattConfig
    battery: BatteryConfig
    weather: WeatherConfig
    rates: RatesConfig
    dashboard: DashboardConfig
    manual_override: int | None


def _validate(cfg: Config) -> None:
    if cfg.battery.total_capacity_kwh <= 0:
        raise ConfigValidationError("total_capacity_kwh must be positive")
    if not (0 < cfg.battery.usable_fraction <= 1):
        raise ConfigValidationError("usable_fraction must be between 0 and 1")
    if cfg.manual_override is not None and not (0 <= cfg.manual_override <= 100):
        raise ConfigValidationError("manual_override must be 0-100 or null")


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    battery_raw = raw["battery"]
    # charge_floor_pct may still be in old configs — ignore it
    battery_raw.pop("charge_floor_pct", None)

    cfg = Config(
        location=LocationConfig(**raw["location"]),
        growatt=GrowattConfig(**raw["growatt"]),
        battery=BatteryConfig(**battery_raw),
        weather=WeatherConfig(**raw["weather"]),
        rates=RatesConfig(**raw["rates"]),
        dashboard=DashboardConfig(**raw["dashboard"]),
        manual_override=raw.get("manual_override"),
    )
    _validate(cfg)
    return cfg
```

- [ ] **Step 4: Update test config fixture**

Update `tests/conftest.py`:

```python
import pytest
from pathlib import Path

VALID_CONFIG_YAML = """
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test_user"
  password: "test_pass"
  plant_id: "123"
  device_sn: "ABC123"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
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
"""

@pytest.fixture
def config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML)
    from src.config import load_config
    return load_config(config_file)
```

- [ ] **Step 5: Update config.yaml — remove dead sections**

Update `config.yaml` to remove `winter_override`, `feedback`, `bootstrap`, and `charge_floor_pct`:

```yaml
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "Stevens BR1"
  password: "Growattsucks01!"
  plant_id: "1368210"
  device_sn: "WPDACDB05J"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
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

- [ ] **Step 6: Update test_config.py if it references removed fields**

Check `tests/test_config.py` and remove any assertions about `feedback`, `bootstrap`, `winter_override`, or `charge_floor_pct`.

- [ ] **Step 7: Update dashboard app.py — remove feedback references**

In `src/dashboard/app.py`, the savings and history pages reference `feedback_adjustment`. Update the history query to stop referencing it (it will still be in the decisions table but always 0 going forward). No template changes needed if they gracefully handle zero values.

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest -v`
Expected: All PASS. If any tests reference deleted code (feedback, winter override, bootstrap, charge_floor_pct), fix them.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: remove feedback loop, winter override, bootstrap, and charge_floor_pct"
```

---

### Task 6: Run the backfill

This is a manual step — not code, but required to populate the data.

- [ ] **Step 1: Run the backfill script**

```bash
python scripts/backfill_weather.py
```

Expected: Output showing monthly chunks being fetched, ~1,174 rows updated. Takes a few minutes due to rate limiting.

- [ ] **Step 2: Verify the backfill**

```bash
python -c "
from pathlib import Path
from src.db.schema import init_db

conn = init_db(Path('data/battery.db'))
total = conn.execute('SELECT COUNT(*) FROM actuals').fetchone()[0]
filled = conn.execute('SELECT COUNT(*) FROM actuals WHERE weather_condition IS NOT NULL').fetchone()[0]
print(f'Total actuals: {total}, with weather: {filled}, missing: {total - filled}')

# Sample distribution
for cond in ['sunny', 'cloudy', 'rainy']:
    count = conn.execute('SELECT COUNT(*) FROM actuals WHERE weather_condition = ?', (cond,)).fetchone()[0]
    print(f'  {cond}: {count} days')
conn.close()
"
```

- [ ] **Step 3: Spot-check generation by weather**

```bash
python -c "
from pathlib import Path
from src.db.schema import init_db

conn = init_db(Path('data/battery.db'))
for month in [1, 3, 6, 9, 12]:
    for cond in ['sunny', 'cloudy', 'rainy']:
        cursor = conn.execute(
            'SELECT AVG(total_solar_generation_kwh), COUNT(*) FROM actuals '
            'WHERE CAST(strftime(\'%%m\', date) AS INTEGER) = ? AND weather_condition = ?',
            (month, cond))
        row = cursor.fetchone()
        if row[1] > 0:
            print(f'Month {month:2d} {cond:6s}: avg={row[0]:.1f}kWh, n={row[1]}')
conn.close()
"
```

This gives us the data to evaluate the cost bias approach in a future session.

- [ ] **Step 4: Commit database**

No code to commit — the database is in `.gitignore`. But verify the backfill persisted:

```bash
python -c "
from pathlib import Path
from src.db.schema import init_db
conn = init_db(Path('data/battery.db'))
row = conn.execute('SELECT COUNT(*) FROM actuals WHERE weather_condition IS NOT NULL').fetchone()
print(f'Weather-tagged rows: {row[0]}')
conn.close()
"
```
