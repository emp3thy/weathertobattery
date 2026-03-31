import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from ..config import Config
from ..weather.interface import DayForecast
from ..db.queries import (
    get_recent_expensive_consumption,
    get_generation_by_weather,
    get_generation_by_weather_wide,
    get_generation_by_condition,
    get_generation_by_month,
)


def solar_day_length(latitude_degrees: float, target_date: date) -> float:
    """Calculate hours of sunlight from latitude and date.

    Uses the astronomical sunrise equation with atmospheric refraction
    correction. Accurate to within ~5 minutes at UK latitudes.
    """
    lat_rad = math.radians(latitude_degrees)
    day_of_year = target_date.timetuple().tm_yday

    declination_rad = math.asin(
        math.sin(math.radians(23.44))
        * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    )

    correction_rad = math.radians(-0.8333)
    cos_hour_angle = (
        (math.sin(correction_rad) - math.sin(lat_rad) * math.sin(declination_rad))
        / (math.cos(lat_rad) * math.cos(declination_rad))
    )

    if cos_hour_angle >= 1.0:
        return 0.0
    if cos_hour_angle <= -1.0:
        return 24.0

    hour_angle = math.acos(cos_hour_angle)
    return (24.0 / math.pi) * hour_angle


@dataclass
class ChargeResult:
    charge_level: int
    reason: str


def _estimate_consumption(conn: sqlite3.Connection) -> tuple[float, str]:
    expensive = get_recent_expensive_consumption(conn, days=7)
    if len(expensive) >= 3:
        avg = sum(expensive) / len(expensive)
        return avg, f"expensive consumption avg ({len(expensive)} days): {avg:.3f}kWh"

    # Fallback: total consumption from recent 7 actuals rows
    cursor = conn.execute(
        "SELECT total_consumption_kwh FROM actuals ORDER BY date DESC LIMIT 7"
    )
    rows = [row[0] for row in cursor.fetchall()]
    if rows:
        avg = sum(rows) / len(rows)
        return avg, f"total consumption fallback ({len(rows)} days): {avg:.3f}kWh"

    return 0.0, "no consumption data"


def _percentile_25(values: list[float]) -> float:
    s = sorted(values)
    idx = int(len(s) * 0.25)
    return s[idx]


def _estimate_generation(
    conn: sqlite3.Connection, month: int, condition: str
) -> tuple[float, str]:
    results = get_generation_by_weather(conn, month, condition)
    if len(results) >= 5:
        p25 = _percentile_25(results)
        return p25, f"generation P25 by month+condition ({len(results)} days): {p25:.3f}kWh"

    results = get_generation_by_weather_wide(conn, month, condition)
    if len(results) >= 5:
        p25 = _percentile_25(results)
        return p25, f"generation P25 by month±1+condition ({len(results)} days): {p25:.3f}kWh"

    results = get_generation_by_condition(conn, condition)
    if len(results) >= 5:
        p25 = _percentile_25(results)
        return p25, f"generation P25 by condition only ({len(results)} days): {p25:.3f}kWh"

    results = get_generation_by_month(conn, month)
    if results:
        p25 = _percentile_25(results)
        return p25, f"generation P25 by month only ({len(results)} days): {p25:.3f}kWh"

    return 0.0, "no historical data"


def calculate_charge(
    config: Config,
    forecast: DayForecast,
    current_soc: int,
    conn: sqlite3.Connection,
) -> ChargeResult:
    # Manual override
    if config.manual_override is not None:
        return ChargeResult(
            charge_level=config.manual_override,
            reason="Manual override applied",
        )

    month = forecast.date.month
    condition = forecast.condition

    expected_consumption, consumption_source = _estimate_consumption(conn)
    expected_generation, generation_source = _estimate_generation(conn, month, condition)

    usable_capacity_kwh = config.battery.usable_capacity_kwh
    current_soc_kwh = (current_soc / 100) * usable_capacity_kwh

    gap_kwh = expected_consumption - expected_generation - current_soc_kwh
    charge_pct = (gap_kwh / usable_capacity_kwh) * 100
    charge_level = int(max(0, min(100, round(charge_pct))))

    reason_parts = [
        f"Consumption: {expected_consumption:.3f}kWh ({consumption_source})",
        f"Generation: {expected_generation:.3f}kWh ({generation_source})",
        f"Current SOC: {current_soc}% ({current_soc_kwh:.3f}kWh)",
        f"Gap: {gap_kwh:.3f}kWh",
        f"Charge level: {charge_level}%",
    ]
    if "total consumption fallback" in consumption_source:
        reason_parts.append("Note: using total consumption as fallback (no expensive_consumption_kwh data)")

    return ChargeResult(
        charge_level=charge_level,
        reason=". ".join(reason_parts),
    )
