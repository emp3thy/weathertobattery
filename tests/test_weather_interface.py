from src.weather.interface import HourlyForecast, bucket_condition

def test_bucket_sunny():
    hours = [HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                            precipitation_probability_pct=5, temperature_c=20) for h in range(7, 18)]
    assert bucket_condition(hours) == "sunny"

def test_bucket_cloudy():
    hours = [HourlyForecast(hour=h, cloud_cover_pct=55, solar_radiation_wm2=200,
                            precipitation_probability_pct=10, temperature_c=15) for h in range(7, 18)]
    assert bucket_condition(hours) == "cloudy"

def test_bucket_rainy():
    hours = []
    for h in range(7, 18):
        precip = 70 if h < 13 else 10
        hours.append(HourlyForecast(hour=h, cloud_cover_pct=80, solar_radiation_wm2=50,
                                    precipitation_probability_pct=precip, temperature_c=12))
    assert bucket_condition(hours) == "rainy"

def test_bucket_heavy_cloud_no_rain_is_cloudy():
    hours = [HourlyForecast(hour=h, cloud_cover_pct=85, solar_radiation_wm2=100,
                            precipitation_probability_pct=15, temperature_c=14) for h in range(7, 18)]
    assert bucket_condition(hours) == "cloudy"
