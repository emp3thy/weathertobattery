# Morning Gap Floor

## Problem

The current calculator compares total daily consumption vs total daily generation. On sunny days this produces a charge level of 0%, ignoring the timing mismatch: cheap rates end at 05:30 but meaningful solar generation doesn't start until ~08:00-09:00. During this 2.5-3.5 hour window, an empty battery means buying from the grid at 30p/kWh.

## Solution

Add a **morning floor** — a minimum charge level that covers consumption from cheap rate end until solar generation is strong enough to sustain the house, plus a configurable buffer for usage spikes.

```
charge_level = max(existing_gap_calc, morning_floor)
```

The existing whole-day gap calculation remains unchanged. The morning floor acts as a minimum that kicks in on sunny days when the daily calculation would otherwise say 0%.

## Morning Floor Calculation

1. **Hourly consumption estimate**: `expected_consumption / expensive_hours` where expensive_hours = 24 minus the cheap window duration (currently 6 hours for 23:30-05:30, so 18 expensive hours).

2. **Find when solar covers load**: Iterate forecast hours from `cheap_end` onward. For each hour, estimate generation using `kwh_per_solar_hour * (100 - cloud_cover_pct) / 100` (same formula as `_estimate_generation_hourly`). The first hour where estimated generation >= hourly consumption is the "solar sustains load" hour.

3. **Morning floor kWh**: `hourly_consumption * gap_hours + morning_buffer_kwh`, where gap_hours is the number of whole hours from `ceil(cheap_end)` to the solar-sustains-load hour. For cheap_end at 05:30, this rounds up to hour 6, so gap hours are counted from 06:00. The 05:30-06:00 half-hour is small enough to absorb into the buffer.

4. **Convert to charge %**: `(morning_floor_kwh / usable_capacity_kwh) * 100`

5. **Apply**: `charge_level = max(existing_gap_pct, morning_floor_pct)`

## Example: Tomorrow (2026-04-06)

- Cheap end: 05:30, sunrise: 06:23, sunny forecast
- Hourly consumption: 26.7 kWh / 18 hrs = ~1.5 kWh/hr
- Solar covers load at ~08:00 (3 gap hours including the 05:30-06:00 partial)
- Morning floor: 1.5 * 3 + 2.0 buffer = 6.5 kWh
- Usable capacity: 11.97 kWh
- Morning floor %: 6.5 / 11.97 * 100 = ~54%
- Existing gap calc: 0%
- Final charge level: max(0%, 54%) = **54%**

## Config Change

New field under `battery` in `config.yaml`:

```yaml
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  fallback_charge_level: 90
  morning_buffer_kwh: 2.0
```

Defaults to 2.0 kWh if not specified.

## Code Changes

### `src/config.py`

- Add `morning_buffer_kwh: float = 2.0` to `BatteryConfig`

### `src/calculator/engine.py`

- New function `_morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)` implementing the calculation above
- Modify `calculate_charge` to compute the morning floor and take `max(existing, morning_floor)`
- Update the reason string to indicate when the morning floor is the binding constraint

### `config.yaml` / `config.example.yaml`

- Add `morning_buffer_kwh: 2.0` under `battery`

## Testing

- **Sunny day**: existing gap = 0%, morning floor = ~54% -> morning floor wins
- **Cloudy day**: existing gap = 60%, morning floor = 30% -> existing gap wins
- **Solar starts early**: cheap_end at 05:30, strong solar by 06:00 -> small morning floor
- **No forecast data**: morning floor returns 0 (fallback, no hourly data to evaluate)
- **Edge case**: all forecast hours have 100% cloud cover -> solar never covers load, morning floor covers until sunset, but existing gap calc would be larger anyway

## Reason String

When morning floor is the binding constraint, the reason includes:

```
Morning floor: X.XXXkWh (Y gap hours + Z buffer). Charge level: N%
```

Appended to the existing consumption/generation/SOC breakdown.
