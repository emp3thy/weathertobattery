from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, time


@dataclass
class HourlyForecast:
    hour: int
    cloud_cover_pct: float
    solar_radiation_wm2: float
    precipitation_probability_pct: float
    temperature_c: float


@dataclass
class DayForecast:
    date: date
    sunrise: time
    sunset: time
    hourly: list[HourlyForecast]
    condition: str
    max_temperature_c: float


def bucket_condition(solar_hours: list[HourlyForecast]) -> str:
    if not solar_hours:
        return "cloudy"
    avg_cloud = sum(h.cloud_cover_pct for h in solar_hours) / len(solar_hours)
    rainy_hours = sum(1 for h in solar_hours if h.precipitation_probability_pct > 50)
    rainy_fraction = rainy_hours / len(solar_hours)
    if rainy_fraction >= 0.5:
        return "rainy"
    if avg_cloud < 30:
        return "sunny"
    return "cloudy"


class WeatherProvider(ABC):
    @abstractmethod
    def get_forecast(self, lat: float, lon: float, target_date: date, timezone: str) -> DayForecast:
        ...
