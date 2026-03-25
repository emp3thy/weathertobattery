import pytest
from unittest.mock import patch, MagicMock
from datetime import date, time


def test_orchestrator_sets_charge_and_logs(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.weather.interface import DayForecast, HourlyForecast
    from src.db.schema import init_db

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    forecast = DayForecast(
        date=date(2026, 7, 15), sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                            precipitation_probability_pct=5, temperature_c=22)
            for h in range(6, 21)
        ],
        condition="sunny", max_temperature_c=22
    )

    mock_weather = MagicMock()
    mock_weather.get_forecast.return_value = forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 15
    mock_growatt.set_charge_soc.return_value = True

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["success"] is True
    assert 30 <= result["charge_level"] <= 100
    mock_growatt.set_charge_soc.assert_called_once()

    from src.db.queries import get_decision
    decision = get_decision(conn, date(2026, 7, 15))
    assert decision is not None
    assert decision["charge_level_set"] == result["charge_level"]

    assert (tmp_path / "last_updated.md").exists()
    conn.close()


def test_orchestrator_winter_skips_weather(tmp_path, config):
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    mock_weather = MagicMock()
    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 10
    mock_growatt.set_charge_soc.return_value = True

    result = run_nightly(
        config=config, conn=conn, weather_provider=mock_weather,
        growatt_client=mock_growatt, target_date=date(2026, 12, 15),
        project_root=tmp_path,
    )

    assert result["charge_level"] == 100
    mock_weather.get_forecast.assert_not_called()
    conn.close()
