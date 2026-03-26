import sqlite3
from pathlib import Path

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


def _migrate(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(actuals)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "weather_condition" not in existing_columns:
        conn.execute("ALTER TABLE actuals ADD COLUMN weather_condition TEXT")
    if "expensive_consumption_kwh" not in existing_columns:
        conn.execute("ALTER TABLE actuals ADD COLUMN expensive_consumption_kwh REAL")
    conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    _migrate(conn)
    return conn
