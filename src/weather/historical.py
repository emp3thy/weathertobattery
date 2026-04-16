import requests
from datetime import date, datetime
from urllib.parse import urlencode

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def build_archive_url(lat: float, lon: float, start: date, end: date, timezone: str) -> str:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": str(start),
        "end_date": str(end),
        "timezone": timezone,
        "hourly": "cloud_cover,precipitation",
        "daily": "sunrise,sunset",
    }
    return f"{ARCHIVE_URL}?{urlencode(params)}"


def classify_day(hourly_cloud: list[float], hourly_precip: list[float]) -> str:
    if not hourly_cloud:
        return "cloudy"
    total = len(hourly_cloud)
    avg_cloud = sum(hourly_cloud) / total
    rainy_hours = sum(1 for p in hourly_precip if p > 0.1)
    rainy_fraction = rainy_hours / total
    if rainy_fraction >= 0.5:
        return "rainy"
    if avg_cloud < 30:
        return "sunny"
    return "cloudy"


def fetch_historical_weather(
    lat: float, lon: float, start: date, end: date, timezone: str
) -> dict[str, str]:
    url = build_archive_url(lat, lon, start, end, timezone)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Parse daily sunrise/sunset keyed by date string
    daily_times: dict[str, tuple[datetime, datetime]] = {}
    for i, day_str in enumerate(data["daily"]["time"]):
        sunrise_dt = datetime.fromisoformat(data["daily"]["sunrise"][i])
        sunset_dt = datetime.fromisoformat(data["daily"]["sunset"][i])
        daily_times[day_str] = (sunrise_dt, sunset_dt)

    # Group hourly data by date, filtered to solar hours
    hourly_cloud_by_day: dict[str, list[float]] = {}
    hourly_precip_by_day: dict[str, list[float]] = {}

    for i, time_str in enumerate(data["hourly"]["time"]):
        dt = datetime.fromisoformat(time_str)
        day_str = str(dt.date())
        if day_str not in daily_times:
            continue
        sunrise_dt, sunset_dt = daily_times[day_str]
        if dt < sunrise_dt or dt > sunset_dt:
            continue
        hourly_cloud_by_day.setdefault(day_str, []).append(data["hourly"]["cloud_cover"][i])
        hourly_precip_by_day.setdefault(day_str, []).append(data["hourly"]["precipitation"][i])

    result: dict[str, str] = {}
    for day_str in daily_times:
        cloud = hourly_cloud_by_day.get(day_str, [])
        precip = hourly_precip_by_day.get(day_str, [])
        result[day_str] = classify_day(cloud, precip)

    return result
