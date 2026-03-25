from src.calculator.profiles import build_solar_profile, weight_forecast


def test_build_solar_profile_from_hourly_data():
    """Profile assigns higher weight to hours with more generation."""
    daily_hourly_data = [
        {"07:00": 0.5, "08:00": 1.5, "09:00": 3.0, "10:00": 4.0,
         "11:00": 3.5, "12:00": 2.5, "13:00": 2.0, "14:00": 1.5,
         "15:00": 1.0, "16:00": 0.5},
        {"07:00": 0.4, "08:00": 1.4, "09:00": 2.8, "10:00": 3.8,
         "11:00": 3.3, "12:00": 2.3, "13:00": 1.8, "14:00": 1.3,
         "15:00": 0.8, "16:00": 0.3},
    ]
    profile = build_solar_profile(daily_hourly_data)
    assert profile[10] > profile[16]
    assert abs(sum(profile.values()) - 1.0) < 0.01


def test_weight_forecast_amplifies_peak_hours():
    """Weighting forecast by profile makes peak-hour weather more important."""
    from src.weather.interface import HourlyForecast
    profile = {8: 0.1, 9: 0.2, 10: 0.3, 11: 0.2, 12: 0.1, 13: 0.1}
    hours = [
        HourlyForecast(hour=h, cloud_cover_pct=50, solar_radiation_wm2=300,
                        precipitation_probability_pct=10, temperature_c=15)
        for h in [8, 9, 10, 11, 12, 13]
    ]
    weighted = weight_forecast(hours, profile)
    assert weighted[10] > weighted[8]
