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

        total_solar = 0.0
        total_consumption = 0.0
        total_grid_import = 0.0
        total_grid_export = 0.0
        expensive_consumption = 0.0
        expensive_grid_import = 0.0
        expensive_grid_export = 0.0
        expensive_solar = 0.0
        expensive_battery_discharge = 0.0
        peak_solar_hour = None
        peak_solar_val = 0.0

        for time_str in sorted(hourly.keys()):
            values = hourly[time_str]
            if not isinstance(values, dict):
                continue
            hour = int(time_str.split(":")[0])
            minute = int(time_str.split(":")[1])
            # Field mapping:
            #   ppv        = solar generation (kW)
            #   sysOut     = total house consumption (kW)
            #   userLoad   = export to grid (kW)
            #   pacToUser  = battery discharge to house (kW)
            # Grid import is derived: max(0, sysOut - ppv - pacToUser)
            ppv = float(values.get("ppv", 0))
            sys_out = float(values.get("sysOut", 0))
            user_load = float(values.get("userLoad", 0))
            pac_to_user = float(values.get("pacToUser", 0))

            grid_import = max(0, sys_out - ppv - pac_to_user)

            total_solar += ppv
            total_consumption += sys_out
            total_grid_import += grid_import
            total_grid_export += user_load

            if ppv > peak_solar_val:
                peak_solar_val = ppv
                peak_solar_hour = time_str

            is_expensive = config.rates.is_expensive(hour, minute)
            if is_expensive:
                expensive_consumption += sys_out
                expensive_grid_import += grid_import
                expensive_grid_export += user_load
                expensive_solar += ppv
                expensive_battery_discharge += pac_to_user

        # Each reading is a 5-minute snapshot in kW; divide by 12 to get kWh
        solar_gen_kwh = total_solar / 12
        consumption_kwh = total_consumption / 12
        grid_import_kwh = total_grid_import / 12
        grid_export_kwh = total_grid_export / 12
        expensive_consumption_kwh = expensive_consumption / 12
        expensive_grid_import_kwh = expensive_grid_import / 12
        expensive_grid_export_kwh = expensive_grid_export / 12
        expensive_solar_kwh = expensive_solar / 12
        expensive_battery_discharge_kwh = expensive_battery_discharge / 12

        # Get weather condition from the decision record for yesterday
        decision = get_decision(conn, yesterday)
        weather_condition = decision["forecast_summary"] if decision else None

        insert_actuals(
            conn, yesterday,
            solar_gen=solar_gen_kwh,
            consumption=consumption_kwh,
            grid_import=grid_import_kwh,
            grid_export=grid_export_kwh,
            peak_solar_hour=peak_solar_hour,
            min_soc=None, max_soc=None,
            weather_condition=weather_condition,
            expensive_consumption_kwh=expensive_consumption_kwh,
            expensive_grid_import_kwh=expensive_grid_import_kwh,
            expensive_grid_export_kwh=expensive_grid_export_kwh,
            expensive_solar_kwh=expensive_solar_kwh,
            expensive_battery_discharge_kwh=expensive_battery_discharge_kwh,
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
            charge_level = config.battery.fallback_charge_level
            reason = f"Weather API unavailable — fallback to {charge_level}%"
        else:
            calc_result = calculate_charge(
                config=config, forecast=forecast, conn=conn,
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
