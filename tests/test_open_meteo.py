from datetime import date, time
from unittest.mock import patch, MagicMock

MOCK_RESPONSE = {
    "hourly": {
        "time": [f"2026-03-26T{h:02d}:00" for h in range(24)],
        "cloud_cover": [90]*6 + [30, 25, 20, 15, 20, 25, 30, 35, 40, 50, 60, 70] + [90]*6,
        "shortwave_radiation": [0]*6 + [50, 200, 400, 500, 450, 400, 350, 300, 200, 100, 30, 0] + [0]*6,
        "precipitation_probability": [10]*24,
        "temperature_2m": [8]*6 + [10, 12, 14, 16, 17, 18, 18, 17, 16, 14, 12, 10] + [8]*6,
    },
    "daily": {"sunrise": ["2026-03-26T06:05"], "sunset": ["2026-03-26T18:25"]}
}

def test_open_meteo_returns_day_forecast():
    from src.weather.open_meteo import OpenMeteoProvider
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    with patch("src.weather.open_meteo.requests.get", return_value=mock_resp):
        provider = OpenMeteoProvider()
        forecast = provider.get_forecast(51.4067, 0.0481, date(2026, 3, 26), "Europe/London")
    assert forecast.date == date(2026, 3, 26)
    assert forecast.sunrise == time(6, 5)
    assert forecast.sunset == time(18, 25)
    assert len(forecast.hourly) > 0
    assert all(6 <= h.hour <= 18 for h in forecast.hourly)
    assert forecast.condition in ("sunny", "cloudy", "rainy")
