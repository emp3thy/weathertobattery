import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from ..config import Config
from ..weather.interface import DayForecast
from ..db.queries import (
    get_recent_expensive_consumption,
    get_max_generation_for_month,
    get_max_generation_for_adjacent_months,
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


def _estimate_generation_hourly(
    conn: sqlite3.Connection, month: int, forecast: DayForecast, latitude: float
) -> tuple[float, str]:
    result = get_max_generation_for_month(conn, month)
    source_label = "max"
    if result is None:
        result = get_max_generation_for_adjacent_months(conn, month)
        source_label = "adjacent month max"
    if result is None:
        return 0.0, "no historical generation data"

    max_gen_kwh, max_gen_date_str = result
    max_gen_date = date.fromisoformat(max_gen_date_str)

    max_day_solar_hours = solar_day_length(latitude, max_gen_date)
    if max_day_solar_hours <= 0:
        return 0.0, "no solar hours on max generation day"

    kwh_per_solar_hour = max_gen_kwh / max_day_solar_hours

    estimated = sum(
        kwh_per_solar_hour * (100 - h.cloud_cover_pct) / 100
        for h in forecast.hourly
    )

    forecast_solar_hours = len(forecast.hourly)
    description = (
        f"{source_label} {max_gen_kwh:.1f}kWh on {max_gen_date_str}, "
        f"{max_day_solar_hours:.1f} solar hrs, "
        f"cloud-adjusted from {forecast_solar_hours} forecast hrs"
    )
    return estimated, description


def _morning_floor_kwh(
    config: Config,
    forecast: DayForecast,
    expected_consumption: float,
    kwh_per_solar_hour: float,
) -> float:
    """Calculate minimum kWh needed to bridge cheap-rate end to solar-covers-load.

    Returns the kWh the battery needs to cover morning consumption from
    cheap_end until hourly solar generation exceeds hourly consumption,
    plus the configured morning buffer.
    """
    if not forecast.hourly or kwh_per_solar_hour <= 0:
        return 0.0

    # Parse cheap_end hour (round up partial hours: 05:30 -> hour 6)
    end_h, end_m = (int(x) for x in config.rates.cheap_end.split(":"))
    first_expensive_hour = end_h + (1 if end_m > 0 else 0)

    # Expensive hours in the day (for hourly consumption estimate)
    start_h, start_m = (int(x) for x in config.rates.cheap_start.split(":"))
    cheap_start_t = start_h * 60 + start_m
    cheap_end_t = end_h * 60 + end_m
    if cheap_start_t > cheap_end_t:
        cheap_duration_mins = (24 * 60 - cheap_start_t) + cheap_end_t
    else:
        cheap_duration_mins = cheap_end_t - cheap_start_t
    expensive_hours = (24 * 60 - cheap_duration_mins) / 60

    if expensive_hours <= 0:
        return 0.0

    hourly_consumption = expected_consumption / expensive_hours

    # Find first forecast hour >= first_expensive_hour where generation covers load
    gap_hours = 0
    solar_covers_load_found = False
    for h_forecast in sorted(forecast.hourly, key=lambda h: h.hour):
        if h_forecast.hour < first_expensive_hour:
            continue
        hour_gen = kwh_per_solar_hour * (100 - h_forecast.cloud_cover_pct) / 100
        if hour_gen >= hourly_consumption:
            solar_covers_load_found = True
            break
        gap_hours += 1

    if not solar_covers_load_found and gap_hours == 0:
        return 0.0

    return hourly_consumption * gap_hours + config.battery.morning_buffer_kwh


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

    expected_consumption, consumption_source = _estimate_consumption(conn)
    expected_generation, generation_source = _estimate_generation_hourly(
        conn, month, forecast, config.location.latitude
    )

    usable_capacity_kwh = config.battery.usable_capacity_kwh
    min_soc = config.battery.min_soc_pct
    effective_soc = max(0, current_soc - min_soc)
    current_soc_kwh = (effective_soc / 100) * usable_capacity_kwh

    gap_kwh = expected_consumption - expected_generation - current_soc_kwh
    charge_pct = (gap_kwh / usable_capacity_kwh) * 100

    # Morning floor: ensure enough charge to bridge cheap-rate end to solar
    result = get_max_generation_for_month(conn, month)
    if result is None:
        result = get_max_generation_for_adjacent_months(conn, month)
    if result is not None:
        max_gen_kwh, max_gen_date_str = result
        max_gen_date = date.fromisoformat(max_gen_date_str)
        max_day_solar_hours = solar_day_length(config.location.latitude, max_gen_date)
        if max_day_solar_hours > 0:
            kwh_per_solar_hour = max_gen_kwh / max_day_solar_hours
        else:
            kwh_per_solar_hour = 0.0
    else:
        kwh_per_solar_hour = 0.0

    morning_kwh = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    morning_pct = (morning_kwh / usable_capacity_kwh) * 100

    if morning_pct > charge_pct:
        charge_level = int(max(0, min(100, round(morning_pct + min_soc))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh (binding)"
    else:
        charge_level = int(max(0, min(100, round(charge_pct + min_soc))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh"

    reason_parts = [
        f"Consumption: {expected_consumption:.3f}kWh ({consumption_source})",
        f"Generation: {expected_generation:.3f}kWh ({generation_source})",
        f"Current SOC: {current_soc}% (effective {effective_soc}%, {current_soc_kwh:.3f}kWh usable)",
        f"Gap: {gap_kwh:.3f}kWh",
        morning_floor_note,
        f"Charge level: {charge_level}%",
    ]
    if "total consumption fallback" in consumption_source:
        reason_parts.append("Note: using total consumption as fallback (no expensive_consumption_kwh data)")

    return ChargeResult(
        charge_level=charge_level,
        reason=". ".join(reason_parts),
    )
