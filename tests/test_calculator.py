import math
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

def test_calculate_charge_has_no_current_soc_param(tmp_path, config):
    """Signature hygiene: current_soc was removed from the gap calc in commit
    8d340cb but left as a dead parameter."""
    import inspect
    from src.calculator.engine import calculate_charge
    params = inspect.signature(calculate_charge).parameters
    assert "current_soc" not in params


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
                              conn=conn)
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
                              conn=conn)
    # Generation >> consumption, battery already 50%, expect very low or 0
    # (+10 from min_soc_pct offset)
    assert result.charge_level <= 30


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
                              conn=conn)
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
                              conn=conn)
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
                              conn=conn)
    # Should have found enough data via wide window
    assert "max" in result.reason.lower() or "adjacent" in result.reason.lower()
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
                              conn=conn)
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
                              conn=conn)
    # Gap is hugely negative, but morning floor (buffer only, solar covers load
    # immediately) sets the minimum. Daily gap is not binding.
    morning_floor_pct = int(round(config.battery.morning_buffer_kwh / config.battery.usable_capacity_kwh * 100)) + config.battery.min_soc_pct
    assert result.charge_level == morning_floor_pct
    assert "(binding)" in result.reason


# --------------------------------------------------------------------------- #
# Test solar_day_length
# --------------------------------------------------------------------------- #

def test_solar_day_length_summer_solstice_london():
    from src.calculator.engine import solar_day_length
    # London (51.5N) summer solstice — expect ~16.5 hours
    hours = solar_day_length(51.5, date(2026, 6, 21))
    assert 16.0 <= hours <= 17.0


def test_solar_day_length_winter_solstice_london():
    from src.calculator.engine import solar_day_length
    # London (51.5N) winter solstice — expect ~8 hours
    hours = solar_day_length(51.5, date(2026, 12, 21))
    assert 7.5 <= hours <= 8.5


def test_solar_day_length_equinox():
    from src.calculator.engine import solar_day_length
    # Equinox — expect ~12 hours at any mid-latitude
    hours = solar_day_length(51.5, date(2026, 3, 20))
    assert 11.5 <= hours <= 12.5


def test_solar_day_length_equator_stable():
    from src.calculator.engine import solar_day_length
    # Equator — always ~12 hours
    summer = solar_day_length(0.0, date(2026, 6, 21))
    winter = solar_day_length(0.0, date(2026, 12, 21))
    assert abs(summer - winter) < 1.0
    assert 11.5 <= summer <= 12.5


def test_get_max_generation_for_month(tmp_path):
    from src.db.queries import get_max_generation_for_month
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="sunny", values=[10.0, 25.0, 15.0, 20.0, 5.0])
    result = get_max_generation_for_month(conn, 3)
    assert result is not None
    max_kwh, max_date = result
    assert max_kwh == 25.0
    assert max_date == "2025-03-02"


def test_get_max_generation_for_month_no_data(tmp_path):
    from src.db.queries import get_max_generation_for_month
    conn = _make_db(tmp_path)
    result = get_max_generation_for_month(conn, 3)
    assert result is None


def test_get_max_generation_for_adjacent_months(tmp_path):
    from src.db.queries import get_max_generation_for_adjacent_months
    conn = _make_db(tmp_path)
    # No data for month 4, but data in month 3 and 5
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 30.0])
    _populate_generation(conn, month=5, condition="sunny", values=[35.0, 28.0])
    result = get_max_generation_for_adjacent_months(conn, 4)
    assert result is not None
    max_kwh, max_date = result
    assert max_kwh == 35.0
    assert max_date == "2025-05-01"


def test_get_max_generation_for_adjacent_months_wraps_december(tmp_path):
    from src.db.queries import get_max_generation_for_adjacent_months
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=1, condition="cloudy", values=[8.0, 12.0])
    _populate_generation(conn, month=11, condition="cloudy", values=[10.0, 9.0])
    result = get_max_generation_for_adjacent_months(conn, 12)
    assert result is not None
    max_kwh, max_date = result
    assert max_kwh == 12.0


# --------------------------------------------------------------------------- #
# Tests for _estimate_generation_hourly
# --------------------------------------------------------------------------- #

def _make_forecast_with_cloud(target_date, hourly_cloud_pcts):
    """Create a forecast with specific per-hour cloud cover percentages.

    hourly_cloud_pcts: list of (hour, cloud_pct) tuples for daylight hours.
    """
    hourly = [
        HourlyForecast(hour=h, cloud_cover_pct=cloud, solar_radiation_wm2=500,
                       precipitation_probability_pct=0, temperature_c=15.0)
        for h, cloud in hourly_cloud_pcts
    ]
    return DayForecast(
        date=target_date, sunrise=time(6, 0), sunset=time(18, 0),
        hourly=hourly, condition="cloudy", max_temperature_c=15.0
    )


def test_estimate_generation_hourly_clear_sky(tmp_path, config):
    """0% cloud all day should return close to max generation, scaled by solar hours ratio."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    # Max day in March: 34.0 kWh
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 34.0, 25.0, 30.0, 28.0])
    # 12 hours of 0% cloud
    cloud_hours = [(h, 0) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    # Should be close to 34 kWh (may differ slightly due to solar hours ratio)
    assert 30.0 <= gen_kwh <= 38.0
    assert "max" in source.lower()


def test_estimate_generation_hourly_full_cloud(tmp_path, config):
    """100% cloud all day should return ~25% of clear-sky (diffuse radiation floor)."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 34.0, 25.0, 30.0, 28.0])
    cloud_hours = [(h, 100) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    clear_sky, _ = _estimate_generation_hourly(conn, 3,
        _make_forecast_with_cloud(date(2026, 3, 15), [(h, 0) for h in range(6, 18)]),
        51.5)
    assert 0.2 * clear_sky <= gen_kwh <= 0.3 * clear_sky


def test_estimate_generation_hourly_half_cloud(tmp_path, config):
    """50% cloud all day should return ~half of max."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 34.0, 25.0, 30.0, 28.0])
    cloud_hours = [(h, 50) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    # With 25% floor, 50% cloud gives: 0.25 + 0.75*0.5 = 0.625 of clear-sky
    assert 18.0 <= gen_kwh <= 28.0


def test_estimate_generation_hourly_mixed_cloud(tmp_path, config):
    """Clear morning, cloudy afternoon should generate more than cloudy morning, clear afternoon."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=6, condition="sunny", values=[40.0, 45.0, 42.0, 44.0, 43.0])
    # Clear morning (6-12), cloudy afternoon (12-18)
    cloud_am_clear = [(h, 0) for h in range(6, 12)] + [(h, 100) for h in range(12, 18)]
    # Cloudy morning (6-12), clear afternoon (12-18)
    cloud_pm_clear = [(h, 100) for h in range(6, 12)] + [(h, 0) for h in range(12, 18)]
    forecast_am = _make_forecast_with_cloud(date(2026, 6, 15), cloud_am_clear)
    forecast_pm = _make_forecast_with_cloud(date(2026, 6, 15), cloud_pm_clear)
    gen_am, _ = _estimate_generation_hourly(conn, 6, forecast_am, 51.5)
    gen_pm, _ = _estimate_generation_hourly(conn, 6, forecast_pm, 51.5)
    # Both should be ~half, and roughly equal (uniform kwh per hour model)
    assert abs(gen_am - gen_pm) < 2.0


def test_estimate_generation_hourly_fallback_adjacent_month(tmp_path, config):
    """Falls back to adjacent month when target month has no data."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    # No data for month 4, but month 3 has data
    _populate_generation(conn, month=3, condition="sunny", values=[30.0, 34.0, 28.0, 32.0, 29.0])
    cloud_hours = [(h, 0) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 4, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 4, forecast, 51.5)
    assert gen_kwh > 0.0
    assert "adjacent" in source.lower()


def test_estimate_generation_hourly_no_data(tmp_path, config):
    """Returns 0 when no historical data exists."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    cloud_hours = [(h, 0) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    assert gen_kwh == 0.0
    assert "no" in source.lower()


# --------------------------------------------------------------------------- #
# Tests for _morning_floor_kwh
# --------------------------------------------------------------------------- #

def _make_forecast_with_radiation(target_date, hourly_data):
    """Create a forecast with specific per-hour cloud cover and radiation.

    hourly_data: list of (hour, cloud_pct, radiation_wm2) tuples.
    """
    hourly = [
        HourlyForecast(hour=h, cloud_cover_pct=cloud, solar_radiation_wm2=rad,
                       precipitation_probability_pct=0, temperature_c=15.0)
        for h, cloud, rad in hourly_data
    ]
    return DayForecast(
        date=target_date, sunrise=time(6, 0), sunset=time(20, 0),
        hourly=hourly, condition="sunny", max_temperature_c=15.0
    )


def test_morning_floor_sunny_day(tmp_path, config):
    """Sunny day: solar covers load by ~8am, morning floor covers 06:00-08:00 + buffer."""
    from src.calculator.engine import _morning_floor_kwh
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=4, condition="sunny",
                         values=[30.0, 35.0, 32.0, 34.0, 31.0])
    hourly_data = [
        (6, 65, 50),    # 6am: heavy cloud, weak solar
        (7, 65, 100),   # 7am: still heavy cloud
        (8, 10, 400),   # 8am: mostly clear — generation should exceed consumption here
        (9, 10, 600),
        (10, 5, 700),
        (11, 5, 800),
        (12, 5, 850),
        (13, 5, 800),
        (14, 10, 700),
        (15, 10, 600),
        (16, 15, 400),
        (17, 20, 200),
        (18, 30, 80),
        (19, 50, 20),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 4, 15), hourly_data)
    expected_consumption = 20.0
    from src.calculator.engine import solar_day_length
    kwh_per_solar_hour = 35.0 / solar_day_length(51.4067, date(2025, 4, 2))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # With diffuse radiation floor, solar covers load from hour 7 onwards.
    # Gap is 1 hour (06) or 0 hours + 2.0 buffer
    assert 2.0 <= result <= 4.0


def test_morning_floor_cloudy_day(tmp_path, config):
    """Cloudy day: solar never covers load, morning floor spans all forecast hours."""
    from src.calculator.engine import _morning_floor_kwh
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=4, condition="cloudy",
                         values=[5.0, 6.0, 4.0, 5.5, 4.5])
    hourly_data = [
        (6, 90, 30),
        (7, 90, 50),
        (8, 85, 80),
        (9, 85, 100),
        (10, 80, 120),
        (11, 80, 130),
        (12, 85, 120),
        (13, 85, 100),
        (14, 90, 80),
        (15, 90, 50),
        (16, 95, 30),
        (17, 95, 10),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 4, 15), hourly_data)
    expected_consumption = 20.0
    from src.calculator.engine import solar_day_length
    kwh_per_solar_hour = 6.0 / solar_day_length(51.4067, date(2025, 4, 3))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # Generation per hour is tiny (kwh_per_solar_hour ~0.44 * 10-20% clear = ~0.04-0.09)
    # which is well below hourly consumption of 1.11 kWh
    # All 12 forecast hours from hour 6 onward are gap hours
    # Floor = 12 * 1.11 + 2.0 = ~15.3 kWh
    assert result > 10.0


def test_morning_floor_no_forecast_data(tmp_path, config):
    """No hourly forecast data returns 0."""
    from src.calculator.engine import _morning_floor_kwh
    forecast = DayForecast(
        date=date(2026, 4, 15), sunrise=time(6, 0), sunset=time(20, 0),
        hourly=[], condition="sunny", max_temperature_c=15.0
    )
    result = _morning_floor_kwh(config, forecast, 20.0, 2.5)
    assert result == 0.0


def test_morning_floor_solar_covers_load_immediately(tmp_path, config):
    """Solar covers load at first expensive hour — floor is just the buffer."""
    from src.calculator.engine import _morning_floor_kwh
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=6, condition="sunny",
                         values=[40.0, 42.0, 38.0, 41.0, 39.0])
    hourly_data = [
        (6, 5, 600),
        (7, 5, 700),
        (8, 5, 800),
        (9, 5, 850),
        (10, 5, 900),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 6, 15), hourly_data)
    expected_consumption = 20.0
    from src.calculator.engine import solar_day_length
    kwh_per_solar_hour = 42.0 / solar_day_length(51.4067, date(2025, 6, 1))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # kwh_per_solar_hour ~2.6, at 95% clear = ~2.47, vs hourly consumption 1.11
    # Solar covers load at hour 6 immediately, gap_hours = 0
    # Floor = 0 * 1.11 + 2.0 = 2.0 (just the buffer)
    assert result == config.battery.morning_buffer_kwh


# --------------------------------------------------------------------------- #
# Tests for morning floor integration in calculate_charge
# --------------------------------------------------------------------------- #

def test_sunny_day_uses_morning_floor(tmp_path, config):
    """Sunny day: daily gap says 0%, but morning floor ensures minimum charge."""
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=4, condition="sunny",
                         values=[30.0, 35.0, 32.0, 34.0, 31.0])
    _populate_expensive_consumption(conn, [18.0, 19.0, 17.0, 18.5, 17.5])
    # Low radiation until hour 8, then strong
    hourly_data = [
        (6, 10, 50),
        (7, 10, 100),
        (8, 10, 400),
        (9, 10, 600),
        (10, 5, 700),
        (11, 5, 800),
        (12, 5, 850),
        (13, 5, 800),
        (14, 10, 700),
        (15, 10, 600),
        (16, 15, 400),
        (17, 20, 200),
        (18, 30, 80),
        (19, 50, 20),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 4, 15), hourly_data)
    result = calculate_charge(config=config, forecast=forecast,
                              conn=conn)
    # Daily gap would be negative (generation >> consumption with 50% SOC)
    # But morning floor should set a minimum > 0
    assert result.charge_level > 0
    assert "morning floor" in result.reason.lower()


def test_min_soc_offset_applied(tmp_path):
    """Charge level is offset by min_soc_pct: input SOC adjusted down, output adjusted up."""
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML

    # Use min_soc_pct=10 (the default from conftest)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML)
    config = load_config(config_file)
    assert config.battery.min_soc_pct == 10

    conn = _make_db(tmp_path)
    _populate_generation(conn, month=6, condition="sunny",
                         values=[25.0, 26.0, 24.0, 27.0, 25.5, 24.5])
    _populate_expensive_consumption(conn, [12.0, 13.0, 11.5, 12.5, 12.0])
    forecast = _make_forecast(date(2026, 6, 15), condition="sunny")

    # Create a config with min_soc_pct=0 for comparison
    config_file_zero = tmp_path / "config_zero.yaml"
    config_file_zero.write_text(VALID_CONFIG_YAML.replace(
        "morning_buffer_kwh: 2.0",
        "morning_buffer_kwh: 2.0\n  min_soc_pct: 0"
    ))
    config_zero = load_config(config_file_zero)

    result_with_offset = calculate_charge(config=config, forecast=forecast,
                                          conn=conn)
    result_without_offset = calculate_charge(config=config_zero, forecast=forecast,
                                             conn=conn)

    # With min_soc=10: effective SOC = 50-10 = 40%, output += 10
    # With min_soc=0:  effective SOC = 50-0  = 50%, output += 0
    # Net effect: with offset should be higher (less available SOC AND higher target)
    assert result_with_offset.charge_level > result_without_offset.charge_level


def test_cloudy_day_daily_gap_wins(tmp_path, config):
    """Cloudy day: daily gap is larger than morning floor, daily gap wins."""
    from src.calculator.engine import calculate_charge
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="cloudy",
                         values=[2.0, 1.5, 2.5, 1.8, 2.2, 2.0])
    _populate_expensive_consumption(conn, [20.0, 21.0, 19.5, 20.5, 20.0])
    # All cloudy, weak radiation
    hourly_data = [
        (6, 90, 30), (7, 90, 50), (8, 85, 80), (9, 85, 100),
        (10, 80, 120), (11, 80, 130), (12, 85, 120), (13, 85, 100),
        (14, 90, 80), (15, 90, 50),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 3, 15), hourly_data)
    result = calculate_charge(config=config, forecast=forecast,
                              conn=conn)
    # Daily gap should be large (consumption >> generation)
    assert result.charge_level >= 70
    # Morning floor should not be the binding constraint
    assert "morning floor" in result.reason.lower()
    assert "(binding)" not in result.reason.lower()
