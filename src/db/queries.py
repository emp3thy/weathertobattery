import sqlite3
from datetime import date, timedelta


def upsert_decision(conn: sqlite3.Connection, dt: date, forecast_summary: str,
                    forecast_detail: str, charge_level_set: int,
                    base_charge_level: int, feedback_adjustment: int,
                    adjustment_reason: str | None, current_soc: int | None,
                    month: int, weather_provider: str) -> None:
    conn.execute("""
        INSERT INTO decisions (date, forecast_summary, forecast_detail,
            charge_level_set, base_charge_level, feedback_adjustment,
            adjustment_reason, current_soc_at_decision, month,
            weather_provider_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            forecast_summary=excluded.forecast_summary,
            forecast_detail=excluded.forecast_detail,
            charge_level_set=excluded.charge_level_set,
            base_charge_level=excluded.base_charge_level,
            feedback_adjustment=excluded.feedback_adjustment,
            adjustment_reason=excluded.adjustment_reason,
            current_soc_at_decision=excluded.current_soc_at_decision,
            month=excluded.month,
            weather_provider_used=excluded.weather_provider_used
    """, (str(dt), forecast_summary, forecast_detail, charge_level_set,
          base_charge_level, feedback_adjustment, adjustment_reason,
          current_soc, month, weather_provider))
    conn.commit()


def get_decision(conn: sqlite3.Connection, dt: date) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM decisions WHERE date = ?", (str(dt),))
    return cursor.fetchone()


def insert_actuals(conn: sqlite3.Connection, dt: date,
                   solar_gen: float, consumption: float,
                   grid_import: float, grid_export: float,
                   peak_solar_hour: str | None, min_soc: int | None,
                   max_soc: int | None, *,
                   weather_condition: str | None = None,
                   expensive_consumption_kwh: float | None = None,
                   expensive_grid_import_kwh: float | None = None,
                   expensive_grid_export_kwh: float | None = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO actuals (date, total_solar_generation_kwh,
            total_consumption_kwh, grid_import_kwh, grid_export_kwh,
            peak_solar_hour, battery_min_soc, battery_max_soc,
            weather_condition, expensive_consumption_kwh,
            expensive_grid_import_kwh, expensive_grid_export_kwh)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(dt), solar_gen, consumption, grid_import, grid_export,
          peak_solar_hour, min_soc, max_soc,
          weather_condition, expensive_consumption_kwh,
          expensive_grid_import_kwh, expensive_grid_export_kwh))
    conn.commit()


def get_actuals(conn: sqlite3.Connection, dt: date) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM actuals WHERE date = ?", (str(dt),))
    return cursor.fetchone()


def get_actuals_range(conn: sqlite3.Connection, start: date,
                      end: date) -> list[sqlite3.Row]:
    cursor = conn.execute(
        "SELECT * FROM actuals WHERE date >= ? AND date <= ? ORDER BY date",
        (str(start), str(end)))
    return cursor.fetchall()


def insert_adjustment(conn: sqlite3.Connection, dt: date, direction: str,
                      amount: int, trigger: str, prev_weather: str | None,
                      tomorrow_forecast: str | None, grid_draw: float,
                      surplus_export: float) -> None:
    conn.execute("""
        INSERT INTO adjustments (date, direction, amount, trigger,
            previous_day_weather, tomorrow_forecast, grid_draw_kwh,
            surplus_export_kwh)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(dt), direction, amount, trigger, prev_weather,
          tomorrow_forecast, grid_draw, surplus_export))
    conn.commit()


def get_recent_adjustments(conn: sqlite3.Connection,
                           days: int = 7, reference_date: date | None = None) -> list[sqlite3.Row]:
    ref = reference_date or date.today()
    cutoff = str(ref - timedelta(days=days))
    cursor = conn.execute(
        "SELECT * FROM adjustments WHERE date >= ? ORDER BY date DESC",
        (cutoff,))
    return cursor.fetchall()


def get_all_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM decisions ORDER BY date DESC")
    return cursor.fetchall()


def get_all_actuals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM actuals ORDER BY date DESC")
    return cursor.fetchall()


def get_generation_by_weather(conn: sqlite3.Connection, month: int, condition: str) -> list[float]:
    """Get solar generation for days matching a weather condition in a given month."""
    cursor = conn.execute(
        """SELECT total_solar_generation_kwh FROM actuals
           WHERE CAST(strftime('%m', date) AS INTEGER) = ?
           AND weather_condition = ?
           ORDER BY date DESC""",
        (month, condition))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_weather_wide(conn: sqlite3.Connection, month: int, condition: str) -> list[float]:
    """Get solar generation for days matching condition in month +/- 1."""
    months = [(month - 2) % 12 + 1, month, month % 12 + 1]
    placeholders = ",".join("?" * len(months))
    cursor = conn.execute(
        f"""SELECT total_solar_generation_kwh FROM actuals
            WHERE CAST(strftime('%m', date) AS INTEGER) IN ({placeholders})
            AND weather_condition = ?
            ORDER BY date DESC""",
        (*months, condition))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_condition(conn: sqlite3.Connection, condition: str) -> list[float]:
    """Get solar generation for all days matching a weather condition."""
    cursor = conn.execute(
        "SELECT total_solar_generation_kwh FROM actuals WHERE weather_condition = ? ORDER BY date DESC",
        (condition,))
    return [row[0] for row in cursor.fetchall()]


def get_generation_by_month(conn: sqlite3.Connection, month: int) -> list[float]:
    """Get solar generation for all days in a given month (any weather)."""
    cursor = conn.execute(
        """SELECT total_solar_generation_kwh FROM actuals
           WHERE CAST(strftime('%m', date) AS INTEGER) = ?
           ORDER BY date DESC""",
        (month,))
    return [row[0] for row in cursor.fetchall()]


def get_recent_expensive_consumption(conn: sqlite3.Connection, days: int = 7) -> list[float]:
    """Get expensive-hours consumption for the most recent N days that have it."""
    cursor = conn.execute(
        """SELECT expensive_consumption_kwh FROM actuals
           WHERE expensive_consumption_kwh IS NOT NULL
           ORDER BY date DESC LIMIT ?""",
        (days,))
    return [row[0] for row in cursor.fetchall()]
