from src.weather.interface import HourlyForecast


def build_solar_profile(daily_hourly_data: list[dict[str, float]]) -> dict[int, float]:
    """Build an hourly weighting profile from historical generation data.

    Args:
        daily_hourly_data: List of dicts mapping "HH:MM" -> generation_kw for each day.

    Returns:
        Dict mapping hour (int) -> normalised weight (0-1, summing to ~1.0).
    """
    totals: dict[int, float] = {}
    counts: dict[int, int] = {}

    for day_data in daily_hourly_data:
        for time_str, gen in day_data.items():
            hour = int(time_str.split(":")[0])
            totals[hour] = totals.get(hour, 0.0) + float(gen)
            counts[hour] = counts.get(hour, 0) + 1

    averages = {h: totals[h] / counts[h] for h in totals if counts[h] > 0}

    total = sum(averages.values())
    if total == 0:
        n = len(averages) or 1
        return {h: 1.0 / n for h in averages}

    return {h: avg / total for h, avg in averages.items()}


def weight_forecast(solar_hours: list[HourlyForecast],
                    profile: dict[int, float]) -> dict[int, float]:
    """Weight forecast solar radiation by the productivity profile.

    Returns:
        Dict mapping hour -> weighted effective radiation.
    """
    result = {}
    for h in solar_hours:
        weight = profile.get(h.hour, 0.0)
        result[h.hour] = h.solar_radiation_wm2 * weight
    return result
