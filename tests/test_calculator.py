import pytest
from datetime import date, time
from src.weather.interface import DayForecast, HourlyForecast


def _make_forecast(target_date, condition="sunny", temp=22, cloud=20, radiation=500):
    return DayForecast(
        date=target_date, sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=cloud, solar_radiation_wm2=radiation,
                            precipitation_probability_pct=5, temperature_c=temp)
            for h in range(6, 21)
        ],
        condition=condition, max_temperature_c=temp
    )


def test_winter_override_returns_100(config):
    from src.calculator.engine import calculate_charge
    forecast = _make_forecast(date(2026, 12, 15))
    result = calculate_charge(config=config, forecast=forecast, current_soc=10,
                              historical_consumption=[], historical_generation=[],
                              feedback_adjustment=0)
    assert result.charge_level == 100
    assert "winter" in result.reason.lower()


def test_manual_override(tmp_path):
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML.replace("manual_override: null", "manual_override: 85"))
    config = load_config(config_file)
    forecast = _make_forecast(date(2026, 6, 15))
    result = calculate_charge(config=config, forecast=forecast, current_soc=20,
                              historical_consumption=[], historical_generation=[],
                              feedback_adjustment=0)
    assert result.charge_level == 85
    assert "manual" in result.reason.lower()


def test_bootstrap_sunny_summer(config):
    from src.calculator.engine import calculate_charge
    forecast = _make_forecast(date(2026, 7, 15))
    result = calculate_charge(config=config, forecast=forecast, current_soc=10,
                              historical_consumption=[], historical_generation=[],
                              feedback_adjustment=0)
    assert result.charge_level == config.bootstrap.sunny_summer_pct


def test_charge_floor_enforced(config):
    from src.calculator.engine import calculate_charge
    forecast = _make_forecast(date(2026, 7, 15), radiation=800, temp=28)
    result = calculate_charge(config=config, forecast=forecast, current_soc=50,
                              historical_consumption=[15.0, 14.0, 16.0, 15.0, 14.0],
                              historical_generation=[38.0, 40.0, 35.0, 42.0, 39.0],
                              feedback_adjustment=-10)
    assert result.charge_level >= config.battery.charge_floor_pct


def test_feedback_adjustment_applied(config):
    from src.calculator.engine import calculate_charge
    forecast = _make_forecast(date(2026, 5, 15), condition="cloudy", cloud=40, radiation=350, temp=18)
    result_no_adj = calculate_charge(config=config, forecast=forecast, current_soc=20,
                                     historical_consumption=[25.0]*5,
                                     historical_generation=[20.0]*5,
                                     feedback_adjustment=0)
    result_with_adj = calculate_charge(config=config, forecast=forecast, current_soc=20,
                                       historical_consumption=[25.0]*5,
                                       historical_generation=[20.0]*5,
                                       feedback_adjustment=10)
    assert result_with_adj.charge_level == result_no_adj.charge_level + 10
