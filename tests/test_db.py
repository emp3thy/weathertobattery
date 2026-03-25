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
    rows = get_recent_adjustments(conn, days=7)
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
