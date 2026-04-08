def compute_daily_savings(
    row: dict,
    usable_capacity_kwh: float,
    cheap_rate: float,
    expensive_rate: float,
) -> dict:
    """Compute daily savings metrics from a joined decision+actuals row.

    All cost/saving values are in pence.
    """
    charge_set = row["charge_level_set"] or 0
    current_soc = row.get("current_soc_at_decision")
    if current_soc is None:
        soc_before = 0
    else:
        soc_before = current_soc

    charged_kwh = max(0, (charge_set - soc_before) / 100 * usable_capacity_kwh)
    cheap_charge_cost_pence = charged_kwh * cheap_rate

    grid_export = row["grid_export_kwh"] or 0
    export_waste_pence = grid_export * cheap_rate

    grid_import = row["grid_import_kwh"] or 0
    grid_cost_pence = grid_import * expensive_rate

    total_consumption = row["total_consumption_kwh"] or 0
    no_solar_baseline_pence = total_consumption * expensive_rate
    actual_cost_pence = grid_cost_pence + cheap_charge_cost_pence
    no_solar_saving_pence = no_solar_baseline_pence - actual_cost_pence

    battery_discharge = row.get("expensive_battery_discharge_kwh") or 0
    net_rate = expensive_rate - cheap_rate
    battery_value_pence = battery_discharge * net_rate - export_waste_pence

    return {
        "charged_kwh": charged_kwh,
        "cheap_charge_cost_pence": cheap_charge_cost_pence,
        "export_waste_pence": export_waste_pence,
        "grid_cost_pence": grid_cost_pence,
        "no_solar_saving_pence": no_solar_saving_pence,
        "battery_value_pence": battery_value_pence,
        "actual_cost_pence": actual_cost_pence,
    }
