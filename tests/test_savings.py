from src.dashboard.savings import compute_daily_savings


def test_basic_sunny_day():
    """April 8 real data: charged from 10% to 29%, generated 34.75 kWh."""
    row = {
        "charge_level_set": 29,
        "current_soc_at_decision": 10,
        "total_consumption_kwh": 35.8,
        "grid_import_kwh": 4.033,
        "grid_export_kwh": 1.042,
        "expensive_battery_discharge_kwh": 8.908,
    }
    result = compute_daily_savings(
        row,
        usable_capacity_kwh=11.97,
        cheap_rate=7.0,
        expensive_rate=30.0,
    )
    # Charged: (29 - 10) / 100 * 11.97 = 2.274 kWh
    assert abs(result["charged_kwh"] - 2.274) < 0.01
    # Cheap charge cost: 2.274 * 7 = 15.92p
    assert abs(result["cheap_charge_cost_pence"] - 15.92) < 0.1
    # Export waste: 1.042 * 7 = 7.29p
    assert abs(result["export_waste_pence"] - 7.29) < 0.1
    # Grid cost: 4.033 * 30 = 121.0p
    assert abs(result["grid_cost_pence"] - 121.0) < 0.1
    # No-solar baseline: 35.8 * 30 = 1074p
    # Actual cost: 121.0 + 15.92 = 136.92p
    # No-solar saving: 1074 - 136.92 = 937.08p
    assert abs(result["no_solar_saving_pence"] - 937.08) < 0.2
    # Battery value: 8.908 * (30-7) - 1.042 * 7 = 204.88 - 7.29 = 197.59p
    assert abs(result["battery_value_pence"] - 197.59) < 0.2


def test_soc_higher_than_target():
    """SOC already above target — no charging happens."""
    row = {
        "charge_level_set": 29,
        "current_soc_at_decision": 47,
        "total_consumption_kwh": 35.8,
        "grid_import_kwh": 4.0,
        "grid_export_kwh": 1.0,
        "expensive_battery_discharge_kwh": 9.0,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    assert result["charged_kwh"] == 0
    assert result["cheap_charge_cost_pence"] == 0


def test_null_soc_assumes_zero():
    """Old records with no SOC data — assume battery was empty (conservative)."""
    row = {
        "charge_level_set": 60,
        "current_soc_at_decision": None,
        "total_consumption_kwh": 20.0,
        "grid_import_kwh": 3.0,
        "grid_export_kwh": 0.5,
        "expensive_battery_discharge_kwh": 5.0,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    # Charged: 60/100 * 11.97 = 7.182 kWh (assumes SOC was 0)
    assert abs(result["charged_kwh"] - 7.182) < 0.01


def test_null_battery_discharge():
    """Old records missing battery discharge data — treat as 0."""
    row = {
        "charge_level_set": 50,
        "current_soc_at_decision": 10,
        "total_consumption_kwh": 20.0,
        "grid_import_kwh": 5.0,
        "grid_export_kwh": 1.0,
        "expensive_battery_discharge_kwh": None,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    # Battery value: 0 * 23 - 1.0 * 7 = -7.0p (only export waste)
    assert abs(result["battery_value_pence"] - (-7.0)) < 0.01
