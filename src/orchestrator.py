import json
import logging
from datetime import date, timedelta, datetime
from pathlib import Path

from .config import Config
from .weather.interface import WeatherProvider, DayForecast
from .growatt.client import GrowattClient
from .calculator.engine import calculate_charge, is_winter
from .calculator.profiles import build_solar_profile
from .calculator.feedback import compute_feedback_adjustment, apply_decay
from .db.queries import (
    upsert_decision, get_decision, get_actuals, insert_actuals,
    get_recent_adjustments, insert_adjustment, get_actuals_range
)

logger = logging.getLogger(__name__)


def _get_historical_data(conn, target_date: date, window_weeks: int = 2) -> tuple[list[float], list[float], list[float]]:
    start = target_date - timedelta(weeks=window_weeks)
    end = target_date - timedelta(days=1)
    rows = get_actuals_range(conn, start, end)
    consumption = [row["total_consumption_kwh"] for row in rows]
    generation = [row["total_solar_generation_kwh"] for row in rows]
    grid_import = [row["grid_import_kwh"] for row in rows]
    return consumption, generation, grid_import


def _get_feedback_state(conn, config: Config, today_weather: str, tomorrow_weather: str) -> int:
    today = date.today()
    actuals = get_actuals(conn, today)
    if actuals is None:
        return 0

    recent = get_recent_adjustments(conn, days=7)
    previous_cumulative = sum(
        r["amount"] if r["direction"] == "up" else -r["amount"]
        for r in recent
    )
    previous_cumulative = apply_decay(previous_cumulative, config.feedback.decay_per_day_pct)

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=actuals["grid_import_kwh"],
        today_surplus_export_kwh=actuals["grid_export_kwh"],
        today_weather=today_weather,
        tomorrow_weather=tomorrow_weather,
        previous_cumulative=previous_cumulative,
    )

    if adj != 0:
        insert_adjustment(
            conn, today,
            direction="up" if adj > 0 else "down",
            amount=abs(adj),
            trigger="grid_draw" if adj > 0 else "surplus_export",
            prev_weather=today_weather,
            tomorrow_forecast=tomorrow_weather,
            grid_draw=actuals["grid_import_kwh"],
            surplus_export=actuals["grid_export_kwh"],
        )

    return adj


def _backfill_actuals(conn, growatt_client: GrowattClient, config: Config, target_date: date) -> None:
    today = target_date - timedelta(days=1)
    existing = get_actuals(conn, today)
    if existing:
        return

    try:
        hourly = growatt_client.get_hourly_data(today)
        daily = growatt_client.get_daily_data(today)

        grid_import_expensive = 0.0
        grid_export_total = 0.0
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
            grid_export_total += sys_out

        grid_import_kwh = grid_import_expensive / 12
        grid_export_kwh = grid_export_total / 12

        insert_actuals(
            conn, today,
            solar_gen=daily.get("total_solar_kwh", 0),
            consumption=daily.get("total_load_kwh", 0),
            grid_import=grid_import_kwh,
            grid_export=grid_export_kwh,
            peak_solar_hour=peak_solar_hour,
            min_soc=None, max_soc=None,
        )
        logger.info(f"Backfilled actuals for {today}")
    except Exception as e:
        logger.warning(f"Failed to backfill actuals for {today}: {e}")


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
    if result.get("feedback_adjustment", 0) != 0:
        lines.extend([
            f"## Feedback Adjustment",
            f"",
            f"- Adjustment: {result['feedback_adjustment']:+d}%",
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
    feedback_adj = 0
    current_soc = None

    # Backfill yesterday's actuals
    _backfill_actuals(conn, growatt_client, config, target_date)

    # Read current SOC once
    try:
        current_soc = growatt_client.get_current_soc()
    except Exception as e:
        logger.warning(f"Failed to read SOC: {e}")

    # Winter override
    if is_winter(target_date, config):
        charge_level = 100
        reason = "Winter override: charging to 100%"
        base_level = 100
    elif config.manual_override is not None:
        charge_level = config.manual_override
        reason = f"Manual override: {charge_level}%"
        base_level = charge_level
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
            base_level = 90
        else:
            today_decision = get_decision(conn, date.today())
            today_weather = today_decision["forecast_summary"] if today_decision else "cloudy"
            feedback_adj = _get_feedback_state(conn, config, today_weather, forecast.condition)

            consumption, generation, hist_grid_import = _get_historical_data(conn, target_date)
            solar_profile = None  # Built from cached hourly data when available

            calc_result = calculate_charge(
                config=config, forecast=forecast, current_soc=current_soc or 0,
                historical_consumption=consumption, historical_generation=generation,
                feedback_adjustment=feedback_adj, solar_profile=solar_profile,
                historical_grid_import=hist_grid_import,
            )
            charge_level = calc_result.charge_level
            base_level = calc_result.base_level
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
        base_charge_level=base_level,
        feedback_adjustment=feedback_adj,
        adjustment_reason=reason,
        current_soc=current_soc,
        month=target_date.month,
        weather_provider=config.weather.provider,
    )

    result = {
        "success": len(errors) == 0,
        "charge_level": charge_level,
        "base_level": base_level,
        "feedback_adjustment": feedback_adj,
        "reason": reason,
        "target_date": str(target_date),
        "timestamp": timestamp,
        "errors": errors,
    }

    _write_last_updated(project_root, result, forecast)
    return result
