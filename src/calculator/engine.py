from dataclasses import dataclass
from datetime import date
from ..config import Config
from ..weather.interface import DayForecast


@dataclass
class ChargeResult:
    charge_level: int
    base_level: int
    feedback_adjustment: int
    reason: str


def is_winter(target_date: date, config: Config) -> bool:
    month_day = (target_date.month, target_date.day)
    start_parts = config.winter_override.start.split("-")
    end_parts = config.winter_override.end.split("-")
    start = (int(start_parts[0]), int(start_parts[1]))
    end = (int(end_parts[0]), int(end_parts[1]))
    # Winter wraps around year end: Oct 25 -> Feb 28
    if start > end:
        return month_day >= start or month_day <= end
    return start <= month_day <= end


def _bootstrap_level(target_date: date, forecast: DayForecast, config: Config) -> int:
    if is_winter(target_date, config):
        return config.bootstrap.winter_pct
    if forecast.condition == "sunny" and target_date.month in (5, 6, 7, 8, 9):
        return config.bootstrap.sunny_summer_pct
    return config.bootstrap.spring_autumn_pct


def calculate_charge(
    config: Config,
    forecast: DayForecast,
    current_soc: int,
    historical_consumption: list[float],
    historical_generation: list[float],
    feedback_adjustment: int,
    solar_profile: dict[int, float] | None = None,
) -> ChargeResult:
    target_date = forecast.date

    # Manual override
    if config.manual_override is not None:
        return ChargeResult(
            charge_level=config.manual_override,
            base_level=config.manual_override,
            feedback_adjustment=0,
            reason="Manual override applied"
        )

    # Winter override
    if is_winter(target_date, config):
        return ChargeResult(
            charge_level=100, base_level=100, feedback_adjustment=0,
            reason="Winter override: charging to 100%"
        )

    # Bootstrap if insufficient historical data
    if len(historical_consumption) < 5 or len(historical_generation) < 5:
        level = _bootstrap_level(target_date, forecast, config)
        return ChargeResult(
            charge_level=level, base_level=level, feedback_adjustment=0,
            reason=f"Bootstrap estimate (insufficient historical data): {level}%"
        )

    # Formula-based calculation
    avg_consumption = sum(historical_consumption) / len(historical_consumption)
    avg_generation = sum(historical_generation) / len(historical_generation)

    # Calculate expected generation from weighted forecast using solar profile
    if forecast.hourly and solar_profile:
        from .profiles import weight_forecast
        weighted = weight_forecast(forecast.hourly, solar_profile)
        total_weighted = sum(weighted.values())
        clear_sky_weighted = sum(
            800 * solar_profile.get(h.hour, 0) for h in forecast.hourly
        )
        if clear_sky_weighted > 0:
            gen_ratio = total_weighted / clear_sky_weighted
        else:
            gen_ratio = 0.5
        expected_gen = avg_generation * gen_ratio
    else:
        condition_factor = {"sunny": 1.1, "cloudy": 0.7, "rainy": 0.3}
        expected_gen = avg_generation * condition_factor.get(forecast.condition, 0.7)

    current_soc_kwh = (current_soc / 100) * config.battery.usable_capacity_kwh
    shortfall = avg_consumption - expected_gen - current_soc_kwh

    usable = config.battery.usable_capacity_kwh
    base_level = int(max(0, min(100, (shortfall / usable) * 100)))

    # Apply feedback
    adjusted = base_level + feedback_adjustment
    charge_level = int(max(config.battery.charge_floor_pct, min(100, adjusted)))

    reason_parts = [
        f"Expected consumption: {avg_consumption:.1f}kWh",
        f"Expected generation: {expected_gen:.1f}kWh",
        f"Current SOC: {current_soc}% ({current_soc_kwh:.1f}kWh)",
        f"Shortfall: {shortfall:.1f}kWh",
        f"Base charge: {base_level}%",
    ]
    if feedback_adjustment != 0:
        reason_parts.append(f"Feedback adjustment: {feedback_adjustment:+d}%")

    return ChargeResult(
        charge_level=charge_level,
        base_level=base_level,
        feedback_adjustment=feedback_adjustment,
        reason=". ".join(reason_parts)
    )
