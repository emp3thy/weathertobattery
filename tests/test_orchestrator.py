import pytest
from unittest.mock import MagicMock
from datetime import date, time


def _make_forecast(target_date, condition="sunny"):
    from src.weather.interface import DayForecast, HourlyForecast
    return DayForecast(
        date=target_date, sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                            precipitation_probability_pct=5, temperature_c=22)
            for h in range(6, 21)
        ],
        condition=condition, max_temperature_c=22
    )


def _seed_actuals(conn):
    """Seed enough historical data for the calculator to work."""
    from src.db.queries import insert_actuals
    for i in range(1, 15):
        insert_actuals(conn, date(2026, 7, i), 35.0, 25.0, 3.0, 5.0,
                       "12:00", 20, 95, weather_condition="sunny",
                       expensive_consumption_kwh=20.0)


def test_orchestrator_sets_charge_and_logs(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    forecast = _make_forecast(date(2026, 7, 15))
    mock_weather = MagicMock()
    mock_weather.get_forecast.return_value = forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 15
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["success"] is True
    assert 0 <= result["charge_level"] <= 100
    mock_growatt.set_charge_soc.assert_called_once()

    from src.db.queries import get_decision
    decision = get_decision(conn, date(2026, 7, 15))
    assert decision is not None
    assert decision["charge_level_set"] == result["charge_level"]

    assert (tmp_path / "last_updated.md").exists()
    conn.close()


def test_orchestrator_weather_failure_falls_back(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    mock_weather = MagicMock()
    mock_weather.get_forecast.side_effect = Exception("API down")

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 20
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["charge_level"] == 90
    assert "unavailable" in result["reason"].lower() or "fallback" in result["reason"].lower()
    conn.close()


def test_orchestrator_weather_retry_backoff_does_not_indexerror(tmp_path, config, monkeypatch):
    """Regression: backoff schedule must not IndexError if the loop ever expands."""
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    conn = init_db(tmp_path / "test.db")
    _seed_actuals(conn)

    call_count = {"n": 0}

    def flaky_forecast(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("transient")
        return _make_forecast(date(2026, 7, 15))

    mock_weather = MagicMock()
    mock_weather.get_forecast.side_effect = flaky_forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 20
    mock_growatt.set_charge_soc.return_value = True
    mock_growatt.get_hourly_data.return_value = {}

    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )
    assert result["success"] is True
    assert call_count["n"] == 3
