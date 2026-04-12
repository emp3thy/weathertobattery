# Min SOC Offset Design

**Date:** 2026-04-12
**Status:** Approved

## Problem

The Growatt inverter stops discharging the battery at 10% reported SOC. This is a configurable safety floor to protect battery longevity. The current calculator treats reported SOC at face value, meaning:

- 10% reported SOC is treated as 1.2 kWh available, when it's actually 0 kWh usable
- A charge target of 17% only provides 7% of usable power (the 10–17% range)

## Solution

Add a `min_soc_pct` config field to `BatteryConfig` (default 10). Offset both the input SOC reading and the output charge target by this value.

## Changes

### Config (`config.py`, `config.example.yaml`)

- Add `min_soc_pct: int = 10` to `BatteryConfig`
- Document in `config.example.yaml`

### Calculator (`engine.py`)

Two adjustments in `calculate_charge`:

1. **Input offset** — subtract `min_soc_pct` from reported SOC before using it:
   ```
   effective_soc = max(0, current_soc - min_soc_pct)
   current_soc_kwh = (effective_soc / 100) * usable_capacity_kwh
   ```

2. **Output offset** — add `min_soc_pct` to calculated charge level before sending to inverter:
   ```
   charge_level = calculated_level + min_soc_pct
   ```
   Clamped to 0–100 as before.

The morning floor calculation works in kWh and flows through the same output offset, so it needs no separate change.

### Savings (`savings.py`)

No change needed. The `charged_kwh` calculation uses `(charge_set - soc_before)`, where both values include the dead zone. The difference is still correct.

### Tests

- Update existing test fixtures to account for the +10 offset in expected charge levels
- Add a test verifying min_soc_pct is applied to both input SOC and output charge level
