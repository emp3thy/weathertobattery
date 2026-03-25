import requests
from datetime import date, time, datetime
from .interface import WeatherProvider, DayForecast, HourlyForecast, bucket_condition

API_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoProvider(WeatherProvider):
    def get_forecast(self, lat: float, lon: float, target_date: date, timezone: str) -> DayForecast:
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "shortwave_radiation,cloud_cover,precipitation_probability,temperature_2m",
            "daily": "sunrise,sunset",
            "timezone": timezone,
            "start_date": str(target_date), "end_date": str(target_date),
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        sunrise_str = data["daily"]["sunrise"][0]
        sunset_str = data["daily"]["sunset"][0]
        sunrise = datetime.fromisoformat(sunrise_str).time()
        sunset = datetime.fromisoformat(sunset_str).time()

        hourly_data = data["hourly"]
        solar_hours = []
        max_temp = -999.0

        for i, time_str in enumerate(hourly_data["time"]):
            hour = datetime.fromisoformat(time_str).hour
            temp = hourly_data["temperature_2m"][i]
            if temp > max_temp:
                max_temp = temp
            if hour < sunrise.hour or hour > sunset.hour:
                continue
            solar_hours.append(HourlyForecast(
                hour=hour,
                cloud_cover_pct=hourly_data["cloud_cover"][i],
                solar_radiation_wm2=hourly_data["shortwave_radiation"][i],
                precipitation_probability_pct=hourly_data["precipitation_probability"][i],
                temperature_c=temp,
            ))

        condition = bucket_condition(solar_hours)
        return DayForecast(date=target_date, sunrise=sunrise, sunset=sunset,
                           hourly=solar_hours, condition=condition, max_temperature_c=max_temp)
