import pytest
from datetime import date
from pathlib import Path


def test_init_db_creates_tables(tmp_path):
    from src.db.schema import init_db
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "actuals" in tables
    assert "adjustments" in tables
    assert "decisions" in tables
    conn.close()


def test_upsert_decision(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, get_decision
    conn = init_db(tmp_path / "test.db")
    upsert_decision(conn, date(2026, 3, 25), "sunny", "{}", 60, 55, 5,
                    "feedback +5", 10, 3, "open_meteo")
    upsert_decision(conn, date(2026, 3, 25), "cloudy", "{}", 75, 70, 5,
                    "revised", 10, 3, "open_meteo")
    row = get_decision(conn, date(2026, 3, 25))
    assert row["charge_level_set"] == 75
    assert row["forecast_summary"] == "cloudy"
    conn.close()


def test_insert_and_get_actuals(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 25), 20.5, 25.0, 5.0, 2.0,
                   "10:00", 15, 95)
    row = get_actuals(conn, date(2026, 3, 25))
    assert row["total_solar_generation_kwh"] == 20.5
    assert row["grid_import_kwh"] == 5.0
    conn.close()


def test_insert_adjustment(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_adjustment, get_recent_adjustments
    conn = init_db(tmp_path / "test.db")
    insert_adjustment(conn, date(2026, 3, 25), "up", 10, "grid_draw",
                      "cloudy", "cloudy", 3.5, 0.0)
    rows = get_recent_adjustments(conn, days=7, reference_date=date(2026, 3, 25))
    assert len(rows) == 1
    assert rows[0]["direction"] == "up"
    conn.close()


def test_get_historical_daily_data(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals_range
    conn = init_db(tmp_path / "test.db")
    for day in range(1, 8):
        insert_actuals(conn, date(2026, 3, day), 15.0 + day, 25.0, 5.0,
                       1.0, "10:00", 20, 95)
    rows = get_actuals_range(conn, date(2026, 3, 3), date(2026, 3, 6))
    assert len(rows) == 4
    conn.close()


def test_new_columns_exist_after_init_db(tmp_path):
    from src.db.schema import init_db
    conn = init_db(tmp_path / "test.db")
    cursor = conn.execute("PRAGMA table_info(actuals)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "weather_condition" in columns
    assert "expensive_consumption_kwh" in columns
    conn.close()


def test_migration_adds_columns_to_existing_db(tmp_path):
    """Verify _migrate adds columns to a DB created without them."""
    import sqlite3 as _sqlite3
    from src.db.schema import init_db, _migrate
    db_path = tmp_path / "legacy.db"
    # Create a DB with the old schema (no new columns)
    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    conn.execute("""CREATE TABLE actuals (
        date TEXT PRIMARY KEY,
        total_solar_generation_kwh REAL NOT NULL,
        total_consumption_kwh REAL NOT NULL,
        grid_import_kwh REAL NOT NULL,
        grid_export_kwh REAL NOT NULL,
        peak_solar_hour TEXT,
        battery_min_soc INTEGER,
        battery_max_soc INTEGER
    )""")
    conn.commit()
    # Confirm new columns are absent
    cursor = conn.execute("PRAGMA table_info(actuals)")
    cols_before = {row[1] for row in cursor.fetchall()}
    assert "weather_condition" not in cols_before
    assert "expensive_consumption_kwh" not in cols_before
    # Run migration
    _migrate(conn)
    cursor = conn.execute("PRAGMA table_info(actuals)")
    cols_after = {row[1] for row in cursor.fetchall()}
    assert "weather_condition" in cols_after
    assert "expensive_consumption_kwh" in cols_after
    conn.close()


def test_insert_actuals_with_new_params(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 1), 20.0, 25.0, 5.0, 2.0,
                   "10:00", 15, 95,
                   weather_condition="sunny",
                   expensive_consumption_kwh=3.5)
    row = get_actuals(conn, date(2026, 3, 1))
    assert row["weather_condition"] == "sunny"
    assert row["expensive_consumption_kwh"] == 3.5
    conn.close()


def test_insert_actuals_new_params_default_none(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals
    conn = init_db(tmp_path / "test.db")
    # Existing callers don't pass the new kwargs — must not break
    insert_actuals(conn, date(2026, 3, 1), 20.0, 25.0, 5.0, 2.0,
                   "10:00", 15, 95)
    row = get_actuals(conn, date(2026, 3, 1))
    assert row["weather_condition"] is None
    assert row["expensive_consumption_kwh"] is None
    conn.close()


def test_get_generation_by_weather(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_weather
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 1), 10.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 3, 2), 12.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 3, 3),  5.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    result = get_generation_by_weather(conn, month=3, condition="sunny")
    assert sorted(result) == [10.0, 12.0]
    result_cloudy = get_generation_by_weather(conn, month=3, condition="cloudy")
    assert result_cloudy == [5.0]
    # No match for a different month
    result_feb = get_generation_by_weather(conn, month=2, condition="sunny")
    assert result_feb == []
    conn.close()


def test_get_generation_by_weather_wide(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_weather_wide
    conn = init_db(tmp_path / "test.db")
    # Month 3 (March): adjacent months are 2 and 4
    insert_actuals(conn, date(2026, 2, 15), 8.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 3, 10), 10.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 4, 5), 11.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 5, 1), 15.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    result = get_generation_by_weather_wide(conn, month=3, condition="sunny")
    # Feb, Mar, Apr should be included; May should not
    assert sorted(result) == [8.0, 10.0, 11.0]
    conn.close()


def test_get_generation_by_weather_wide_year_wrap(tmp_path):
    """Month 1 (Jan): adjacent months should be 12 and 2."""
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_weather_wide
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2025, 12, 20), 3.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 1, 10), 4.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 2, 5), 5.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 3, 1), 9.0, 25.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    result = get_generation_by_weather_wide(conn, month=1, condition="cloudy")
    assert sorted(result) == [3.0, 4.0, 5.0]
    conn.close()


def test_get_generation_by_condition(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_condition
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 1, 1), 5.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="overcast")
    insert_actuals(conn, date(2026, 6, 1), 18.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="overcast")
    insert_actuals(conn, date(2026, 7, 1), 20.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    result = get_generation_by_condition(conn, "overcast")
    assert sorted(result) == [5.0, 18.0]
    result_none = get_generation_by_condition(conn, "rainy")
    assert result_none == []
    conn.close()


def test_get_generation_by_month(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_generation_by_month
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 1), 10.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    insert_actuals(conn, date(2026, 3, 2), 12.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="cloudy")
    insert_actuals(conn, date(2026, 4, 1), 14.0, 20.0, 5.0, 1.0, None, None, None, weather_condition="sunny")
    result = get_generation_by_month(conn, month=3)
    assert sorted(result) == [10.0, 12.0]
    result_empty = get_generation_by_month(conn, month=5)
    assert result_empty == []
    conn.close()


def test_get_recent_expensive_consumption(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_recent_expensive_consumption
    conn = init_db(tmp_path / "test.db")
    # Insert 5 rows with expensive_consumption_kwh and 2 without
    for day in range(1, 6):
        insert_actuals(conn, date(2026, 3, day), 10.0, 20.0, 5.0, 1.0, None, None, None,
                       expensive_consumption_kwh=float(day))
    insert_actuals(conn, date(2026, 3, 6), 10.0, 20.0, 5.0, 1.0, None, None, None)
    insert_actuals(conn, date(2026, 3, 7), 10.0, 20.0, 5.0, 1.0, None, None, None)
    # Default days=7, but only 5 rows have the value
    result = get_recent_expensive_consumption(conn)
    assert len(result) == 5
    # Results are ordered DESC by date, so most recent first
    assert result[0] == 5.0
    assert result[-1] == 1.0
    # Limit to 3
    result3 = get_recent_expensive_consumption(conn, days=3)
    assert len(result3) == 3
    assert result3[0] == 5.0
    conn.close()
