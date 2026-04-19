# Savings Page Redesign

## Problem

The current savings page calculates "charge avoided" as `(100 - charge_level) / 100 * capacity` which is meaningless. It doesn't reflect actual costs or savings.

## Design

### Data Sources

Per-day data comes from joining `decisions` and `actuals` tables:
- `decisions`: `charge_level_set`, `current_soc_at_decision`
- `actuals`: `total_consumption_kwh`, `grid_import_kwh`, `grid_export_kwh`, `expensive_battery_discharge_kwh`
- `config.rates`: `cheap_pence_per_kwh`, `expensive_pence_per_kwh`
- `config.battery`: `usable_capacity_kwh`

### Per-Day Calculations

All rates come from config, never hardcoded.

**Cheap charge cost:**
```
charged_kwh = max(0, charge_level_set - current_soc_at_decision) / 100 * usable_capacity_kwh
cheap_charge_cost_pence = charged_kwh * cheap_pence_per_kwh
```

Note: `current_soc_at_decision` may be NULL for older records. When NULL, assume `charged_kwh = charge_level_set / 100 * usable_capacity_kwh` (conservative — assumes battery was empty).

**Export waste:**
```
export_waste_pence = grid_export_kwh * cheap_pence_per_kwh
```

**Expensive grid cost:**
```
grid_cost_pence = grid_import_kwh * expensive_pence_per_kwh
```

**No-solar saving** (vs buying all consumption at peak rate):
```
baseline_pence = total_consumption_kwh * expensive_pence_per_kwh
actual_cost_pence = grid_cost_pence + cheap_charge_cost_pence
no_solar_saving_pence = baseline_pence - actual_cost_pence
```

**Battery value** (net value of having a battery):
```
net_rate = expensive_pence_per_kwh - cheap_pence_per_kwh
battery_value_pence = expensive_battery_discharge_kwh * net_rate - export_waste_pence
```

### Layout

**Three summary cards** at the top of the page:
- **Today/Yesterday** (most recent day with actuals)
- **This Month** (sum of current month)
- **All Time** (sum of all data)

Each card displays:
- No-solar saving (in pounds)
- Battery value (in pounds)
- Actual grid cost (in pounds)

**Chart:** Line graph showing daily battery value (pence) over the last 90 days. Single line, date on x-axis, pence on y-axis.

**No per-day table.** The chart covers the trend view. The history page has raw daily data for drill-down.

### Chart Implementation

Use Chart.js loaded from CDN (already a common choice for simple dashboards, no build step needed). Render a `<canvas>` element, pass the daily battery value data as JSON from the backend.

### Code Changes

**Backend (`src/dashboard/app.py`):**
- Rewrite the `/savings` endpoint to query `decisions JOIN actuals`, compute all metrics per day, aggregate into daily/monthly/all-time summaries, and pass daily battery value series for the chart
- Pass `config.rates` values to the template for display

**Template (`src/dashboard/templates/savings.html`):**
- Replace the current template entirely
- Three summary cards with the metrics above
- Chart.js line chart for 90-day battery value trend

### Edge Cases

- Days with NULL `current_soc_at_decision`: assume SOC was 0 (conservative)
- Days with NULL `expensive_battery_discharge_kwh`: treat as 0
- Days with no actuals: skip (JOIN already handles this)
- Negative battery value (export waste exceeds discharge value): display as negative — this is useful feedback

### Testing

- Test the per-day calculation logic with known values (e.g., April 8 data)
- Test aggregation (monthly/all-time sums)
- Test NULL handling for older records
