from datetime import date
from unittest.mock import patch, MagicMock

from src.weather.historical import classify_day, build_archive_url, fetch_historical_weather


# --- classify_day tests ---

def test_classify_day_sunny():
    cloud = [10.0, 15.0, 20.0, 10.0, 5.0]   # avg = 12, well below 30
    precip = [0.0, 0.0, 0.0, 0.0, 0.0]
    assert classify_day(cloud, precip) == "sunny"


def test_classify_day_rainy():
    cloud = [90.0, 95.0, 85.0, 90.0, 88.0, 92.0]
    precip = [0.5, 1.2, 0.8, 0.3, 0.9, 0.0]  # 5/6 hours rainy -> fraction >= 0.5
    assert classify_day(cloud, precip) == "rainy"


def test_classify_day_cloudy():
    cloud = [60.0, 70.0, 65.0, 55.0]   # avg = 62.5, above 30
    precip = [0.0, 0.0, 0.0, 0.0]      # no rain
    assert classify_day(cloud, precip) == "cloudy"


def test_classify_day_empty_returns_cloudy():
    assert classify_day([], []) == "cloudy"


def test_classify_day_boundary_rainy_fraction_exactly_half():
    # 2 rainy out of 4 = 0.5 -> should be rainy
    cloud = [80.0, 80.0, 80.0, 80.0]
    precip = [0.5, 0.5, 0.0, 0.0]
    assert classify_day(cloud, precip) == "rainy"


def test_classify_day_just_below_rainy_threshold():
    # 1 rainy out of 4 = 0.25 -> not rainy; avg cloud 70 -> cloudy
    cloud = [70.0, 70.0, 70.0, 70.0]
    precip = [0.5, 0.0, 0.0, 0.0]
    assert classify_day(cloud, precip) == "cloudy"


# --- build_archive_url tests ---

def test_build_archive_url_contains_base():
    url = build_archive_url(51.4, 0.05, date(2024, 1, 1), date(2024, 1, 31), "Europe/London")
    assert url.startswith("https://archive-api.open-meteo.com/v1/archive?")


def test_build_archive_url_has_expected_params():
    url = build_archive_url(51.4067, 0.0481, date(2024, 3, 1), date(2024, 3, 31), "Europe/London")
    assert "latitude=51.4067" in url
    assert "longitude=0.0481" in url
    assert "start_date=2024-03-01" in url
    assert "end_date=2024-03-31" in url
    assert "timezone=Europe%2FLondon" in url
    assert "cloud_cover" in url
    assert "precipitation" in url
    assert "sunrise" in url
    assert "sunset" in url


# --- fetch_historical_weather integration (mocked) ---

MOCK_ARCHIVE_RESPONSE = {
    "daily": {
        "time": ["2024-06-01", "2024-06-02"],
        "sunrise": ["2024-06-01T04:48", "2024-06-02T04:47"],
        "sunset": ["2024-06-01T21:15", "2024-06-02T21:16"],
    },
    "hourly": {
        "time": [
            # Day 1: sunny hours (between 04:48 and 21:15)
            f"2024-06-01T{h:02d}:00" for h in range(24)
        ] + [
            # Day 2: rainy hours
            f"2024-06-02T{h:02d}:00" for h in range(24)
        ],
        "cloud_cover": (
            [0] * 24 +   # day 1: clear
            [90] * 24    # day 2: overcast
        ),
        "precipitation": (
            [0.0] * 24 +                    # day 1: no rain
            [0.5] * 15 + [0.0] * 9         # day 2: rain for first 15 hours (covers solar window)
        ),
    },
}


def test_fetch_historical_weather_classifies_days():
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_ARCHIVE_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("src.weather.historical.requests.get", return_value=mock_resp):
        result = fetch_historical_weather(
            51.4067, 0.0481,
            date(2024, 6, 1), date(2024, 6, 2),
            "Europe/London"
        )

    assert "2024-06-01" in result
    assert "2024-06-02" in result
    # Day 1: low cloud, no precip -> sunny
    assert result["2024-06-01"] == "sunny"
    # Day 2: high cloud, lots of rain -> rainy
    assert result["2024-06-02"] == "rainy"
