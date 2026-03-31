# Hourly Cloud-Cover Generation Estimate

Replace the condition-bucket generation estimate with an hourly cloud-cover model that uses historical max generation and per-hour cloud cover percentages to produce a more accurate daily generation forecast.

## Problem

The current system classifies each day as "cloudy", "sunny", or "rainy" and looks up historical P25 generation for that bucket. This is too coarse: a day with clear mornings and cloudy afternoons gets the same estimate as a fully overcast day. Both are labelled "cloudy" and produce the same 10.7 kWh estimate, when actual generation can differ by 2x.

## Design

### 1. New generation estimate function

Replace `_estimate_generation(conn, month, condition)` in `calculator/engine.py` with `_estimate_generation_hourly(conn, month, forecast, latitude)`:

1. Query actuals for the max `total_solar_generation_kwh` in the target month, returning `(max_gen_kwh, max_gen_date)`.
2. Calculate solar hours on that historical max day using the astronomical day-length formula with `latitude` and `max_gen_date`.
3. Derive `kwh_per_solar_hour = max_gen_kwh / solar_hours_on_max_day`.
4. Walk `forecast.hourly` from sunrise to sunset. For each hour: `kwh_per_solar_hour * (100 - cloud_cover_pct) / 100`.
5. Sum all hourly values to produce the estimated generation for the day.

**Fallback cascade:**
- If no actuals for the target month: use month +/- 1 max, scaled by the ratio of solar hours (target month's forecast solar hours / adjacent month max day's solar hours).
- If no actuals at all: return 0.0.

### 2. Astronomical day-length calculation

A pure-Python function using the standard solar declination / hour-angle model:

- Input: `latitude_degrees: float, target_date: date`
- Output: `solar_hours: float` (decimal hours)
- Formula: solar declination from day-of-year, hour angle from latitude + declination, day length = `(24/pi) * hour_angle`
- Includes atmospheric refraction correction (-0.8333 degrees) to align with published sunrise/sunset times
- Accuracy: within ~5 minutes at 51.5N year-round
- No external dependencies (math stdlib only)

### 3. DB query changes

New queries in `db/queries.py`:

- `get_max_generation_for_month(conn, month)` - returns `(max_gen_kwh, date_str)` from actuals for the given month
- `get_max_generation_for_adjacent_months(conn, month)` - same but for month +/- 1

Existing condition-based queries (`get_generation_by_weather`, `get_generation_by_weather_wide`, `get_generation_by_condition`, `get_generation_by_month`) remain in place. They are no longer used by the calculator but may be referenced by the dashboard or useful for future analysis.

### 4. Calculator signature changes

`calculate_charge` already receives the full `DayForecast` (which contains hourly data) and `Config` (which has `location.latitude`). The internal call changes from:

```python
_estimate_generation(conn, month, condition)
```

to:

```python
_estimate_generation_hourly(conn, month, forecast, config.location.latitude)
```

### 5. Orchestrator and output

No changes to the orchestrator. The `reason` string output from the calculator will change to reflect the new methodology, e.g.:

```
Generation: 18.2kWh (max 34.2kWh on 2026-03-26, 12.5 solar hrs, cloud-adjusted from 12.8 forecast hrs)
```

`last_updated.md` picks this up automatically since it writes the reason string.

### 6. What stays unchanged

- `condition` field on `DayForecast` and `bucket_condition()` function - still used for `forecast_summary` in decisions table and `weather_condition` in actuals
- Consumption estimation - unchanged
- SOC reading, Growatt integration, dashboard - unchanged

## Files to modify

- `src/calculator/engine.py` - replace `_estimate_generation`, add `solar_day_length`, update `calculate_charge` signature
- `src/db/queries.py` - add two new query functions
- `tests/test_calculator.py` (or equivalent) - update tests for new estimation logic
