import pytest
from datetime import date, time
from pathlib import Path
from src.weather.interface import DayForecast, HourlyForecast
from src.db.schema import init_db
from src.db.queries import insert_actuals


def _make_forecast(target_date, condition="sunny", temp=22):
    return DayForecast(
        date=target_date, sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                           precipitation_probability_pct=5, temperature_c=temp)
            for h in range(6, 21)
        ],
        condition=condition, max_temperature_c=temp
    )


def _make_db(tmp_path: Path):
    return init_db(tmp_path / "test.db")


def _populate_generation(conn, month, condition, values):
    """Insert actuals rows with given generation values for a month/condition."""
    # Use dates within the specified month (year 2025 for historical data)
    for i, val in enumerate(values):
        dt = date(2025, month, i + 1)
        insert_actuals(conn, dt, solar_gen=val, consumption=15.0,
                       grid_import=2.0, grid_export=1.0,
                       peak_solar_hour=None, min_soc=None, max_soc=None,
                       weather_condition=condition)


def _populate_expensive_consumption(conn, values):
    """Insert recent actuals rows with expensive consumption."""
    for i, val in enumerate(values):
        dt = date(2026, 3, 20 - i)
        insert_actuals(conn, dt, solar_gen=5.0, consumption=20.0,
                       grid_import=2.0, grid_export=0.5,
                       peak_solar_hour=None, min_soc=None, max_soc=None,
                       expensive_consumption_kwh=val)


# --------------------------------------------------------------------------- #
# Test 1: Manual override
# --------------------------------------------------------------------------- #

def test_manual_override(tmp_path, config):
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML.replace("manual_override: null", "manual_override: 85"))
    override_config = load_config(config_file)
    conn = _make_db(tmp_path)
    forecast = _make_forecast(date(2026, 6, 15))
    result = calculate_charge(config=override_config, forecast=forecast,
                              current_soc=20, conn=conn)
    assert result.charge_level == 85
    assert "manual" in result.reason.lower()


# --------------------------------------------------------------------------- #
# Test 2: Sunny day with good historical generation — charges low
# --------------------------------------------------------------------------- #

def test_sunny_day_good_generation_charges_low(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # High generation (30 kWh/day), low consumption (~8 kWh)
    _populate_generation(conn, month=6, condition="sunny",
                         values=[30.0, 31.0, 29.0, 30.5, 28.5, 32.0])
    _populate_expensive_consumption(conn, [8.0, 8.5, 7.5, 9.0, 8.0])
    forecast = _make_forecast(date(2026, 6, 15), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=50, conn=conn)
    # Generation >> consumption, battery already 50%, expect very low or 0
    assert result.charge_level <= 20


# --------------------------------------------------------------------------- #
# Test 3: Cloudy day with poor historical generation — charges high
# --------------------------------------------------------------------------- #

def test_cloudy_day_poor_generation_charges_high(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Low generation (2 kWh/day), high consumption (20 kWh)
    _populate_generation(conn, month=3, condition="cloudy",
                         values=[2.0, 1.5, 2.5, 1.8, 2.2, 2.0])
    _populate_expensive_consumption(conn, [20.0, 21.0, 19.5, 20.5, 20.0])
    forecast = _make_forecast(date(2026, 3, 15), condition="cloudy")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=10, conn=conn)
    assert result.charge_level >= 70


# --------------------------------------------------------------------------- #
# Test 4: Winter day uses data, not override — reason must NOT contain "winter"
# --------------------------------------------------------------------------- #

def test_winter_day_no_winter_override(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=12, condition="cloudy",
                         values=[1.0, 0.8, 1.2, 0.9, 1.1, 1.0])
    _populate_expensive_consumption(conn, [22.0, 23.0, 21.0, 22.5, 22.0])
    forecast = _make_forecast(date(2026, 12, 15), condition="cloudy")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=10, conn=conn)
    # Should charge high due to low generation, but reason must not say "winter"
    assert result.charge_level >= 60
    assert "winter" not in result.reason.lower()


# --------------------------------------------------------------------------- #
# Test 5: Falls back to wider month window
# --------------------------------------------------------------------------- #

def test_falls_back_to_wider_month_window(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Only 2 rows for exact month (June), but 5+ in adjacent months (May, July)
    _populate_generation(conn, month=6, condition="sunny", values=[25.0, 26.0])
    # Adjacent months — insert manually so we can use month=5 and month=7
    for i, val in enumerate([24.0, 25.5, 23.0, 26.0, 24.5]):
        dt = date(2025, 5, i + 1)
        insert_actuals(conn, dt, solar_gen=val, consumption=15.0,
                       grid_import=2.0, grid_export=1.0,
                       peak_solar_hour=None, min_soc=None, max_soc=None,
                       weather_condition="sunny")
    _populate_expensive_consumption(conn, [8.0, 8.5, 7.5, 9.0, 8.0])
    forecast = _make_forecast(date(2026, 6, 15), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=50, conn=conn)
    # Should have found enough data via wide window
    assert "month±1" in result.reason or "month" in result.reason
    assert result.charge_level <= 30


# --------------------------------------------------------------------------- #
# Test 6: Falls back to total consumption when no expensive_consumption_kwh
# --------------------------------------------------------------------------- #

def test_falls_back_to_total_consumption(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=6, condition="sunny",
                         values=[25.0, 26.0, 24.0, 27.0, 25.5, 24.5])
    # Insert rows without expensive_consumption_kwh
    for i in range(5):
        dt = date(2026, 3, 20 - i)
        insert_actuals(conn, dt, solar_gen=5.0, consumption=18.0,
                       grid_import=2.0, grid_export=0.5,
                       peak_solar_hour=None, min_soc=None, max_soc=None)
    forecast = _make_forecast(date(2026, 6, 15), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=20, conn=conn)
    assert "total consumption fallback" in result.reason.lower()


# --------------------------------------------------------------------------- #
# Test 7: Charge clamped to 0 when massive generation
# --------------------------------------------------------------------------- #

def test_charge_clamped_to_zero_with_massive_generation(tmp_path, config):
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    # Huge generation (100 kWh/day), low consumption
    _populate_generation(conn, month=6, condition="sunny",
                         values=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    _populate_expensive_consumption(conn, [5.0, 5.0, 5.0, 5.0, 5.0])
    forecast = _make_forecast(date(2026, 6, 15), condition="sunny")
    result = calculate_charge(config=config, forecast=forecast,
                              current_soc=80, conn=conn)
    assert result.charge_level == 0
