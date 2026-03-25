from ..config import Config

WEATHER_ORDER = {"sunny": 0, "cloudy": 1, "rainy": 2}


def _weather_same_or_worse(today: str, tomorrow: str) -> bool:
    return WEATHER_ORDER.get(tomorrow, 1) >= WEATHER_ORDER.get(today, 1)


def _weather_same_or_better(today: str, tomorrow: str) -> bool:
    return WEATHER_ORDER.get(tomorrow, 1) <= WEATHER_ORDER.get(today, 1)


def apply_decay(cumulative: int, decay_rate: int) -> int:
    if cumulative > 0:
        return max(0, cumulative - decay_rate)
    elif cumulative < 0:
        return min(0, cumulative + decay_rate)
    return 0


def compute_feedback_adjustment(
    config: Config,
    today_grid_import_kwh: float,
    today_surplus_export_kwh: float,
    today_weather: str,
    tomorrow_weather: str,
    previous_cumulative: int,
) -> int:
    usable = config.battery.usable_capacity_kwh
    max_per_night = config.feedback.max_per_night_pct
    max_cumulative = config.feedback.max_cumulative_pct

    adjustment = 0

    # Undercharged: grid import during expensive hours
    if today_grid_import_kwh > 0.5 and _weather_same_or_worse(today_weather, tomorrow_weather):
        raw = int((today_grid_import_kwh / usable) * 100)
        adjustment = min(raw, max_per_night)

    # Overcharged: surplus export while battery was full
    elif today_surplus_export_kwh > 0.5 and _weather_same_or_better(today_weather, tomorrow_weather):
        raw = int((today_surplus_export_kwh / usable) * 100)
        adjustment = -min(raw, max_per_night)

    # Clamp to cumulative cap
    new_cumulative = previous_cumulative + adjustment
    if new_cumulative > max_cumulative:
        adjustment = max_cumulative - previous_cumulative
    elif new_cumulative < -max_cumulative:
        adjustment = -max_cumulative - previous_cumulative

    return adjustment
