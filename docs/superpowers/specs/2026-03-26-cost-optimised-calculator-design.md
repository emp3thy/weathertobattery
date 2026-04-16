# Cost-Optimised Charge Calculator

## Problem

The current calculator estimates expected grid import and tries to charge exactly enough to cover it. This has two flaws:

1. **No cost asymmetry.** Undercharging costs 30p/kWh (expensive grid import); overcharging costs 7p/kWh (wasted cheap-rate charging). The system should bias toward overcharging since it's ~4x cheaper to be wrong in that direction.
2. **Weak generation forecasting.** Generation estimates use historical average scaled by a coarse weather factor (sunny=1.1x, cloudy=0.7x, rainy=0.3x). We have 3+ years of daily generation data but no weather recorded against it, so we can't say "on sunny March days I generate X kWh".
3. **Wrong consumption metric.** The system uses total daily consumption (all 24 hours) and grid import filtered to expensive hours. It should use consumption during expensive hours only (05:30-23:30), since cheap-hours consumption is irrelevant to the battery decision.

## Solution

### Phase 1: Historical weather backfill

Add weather data to the existing 1,174 days of actuals (2023-01-01 to present).

**Schema change:** Add `weather_condition TEXT` column to the `actuals` table. Values: sunny, cloudy, rainy (matching existing forecast buckets).

**Backfill process:**
- Use Open-Meteo's historical weather API (free, no key required) to fetch daily weather for each date in the actuals table
- Apply the same bucketing logic used for forecasts (cloud cover, precipitation probability) to classify each day
- Update each actuals row with the derived condition

**Also add:** `expensive_consumption_kwh REAL` column to actuals. For dates within the 91-day 5-minute data window, calculate consumption during 05:30-23:30 from interval data. For older dates, leave NULL — we accept that accurate expensive-hours consumption is only available going forward.

### Phase 2: New calculator

Replace the current `calculate_charge` function in `src/calculator/engine.py`.

**Step 1 — Estimate consumption:**
Average `expensive_consumption_kwh` over the past 7 days. If fewer than 3 days have this value, fall back to `total_consumption_kwh` average (less accurate but better than nothing).

**Step 2 — Estimate generation:**
Look up historical generation for days matching:
- Same weather condition as tomorrow's forecast
- Same month as tomorrow

If >= 5 matching days exist, use their average generation. If fewer, widen to adjacent months (month +/- 1). If still insufficient, fall back to same-condition any-month. Last resort: monthly average regardless of weather.

**Step 3 — Calculate gap:**
`gap = expected_consumption - expected_generation - current_soc_kwh`

This is the energy (kWh) the battery needs to provide tomorrow. Negative gap means solar alone covers demand.

**Step 4 — Convert to charge level:**
`charge_pct = (gap / usable_capacity_kwh) * 100`

Clamp to 0-100%.

**Step 5 — Cost bias (deferred):**
The cost asymmetry (30p undercharge vs 7p overcharge) means we should add a buffer. The size of that buffer depends on how much generation and consumption vary within a weather bucket. Once we have the historical weather data populated, we can examine the variance and decide whether to use:
- A percentile-based approach (charge to the ~81st percentile of expected demand)
- A fixed buffer derived from observed standard deviation
- Something simpler if the variance turns out to be small

This decision is deferred until after Phase 1 is complete and we can inspect the data.

### Phase 3: Remove dead code

- **Remove feedback loop:** `src/calculator/feedback.py` and all references in the orchestrator. The feedback loop was compensating for the weak model — with weather-matched historical data, it's redundant.
- **Remove winter override:** The data-driven model should naturally charge high on short cloudy winter days. No special case needed.
- **Remove bootstrap logic:** With 3+ years of backfilled data, the insufficient-data path is no longer needed. If somehow there are zero matching days (shouldn't happen), the monthly average fallback handles it.
- **Remove adjustments table:** No longer needed without the feedback loop.
- **Remove feedback config:** `feedback` section from config.yaml and Config dataclass.
- **Remove winter_override config:** Same.
- **Remove charge_floor_pct:** The model decides the charge level; no artificial floor.

### Phase 4: Update backfill process

The nightly `_backfill_actuals` in the orchestrator needs to:
1. Calculate `expensive_consumption_kwh` from 5-minute interval data (sum consumption during 05:30-23:30, divide by 12 for kWh)
2. Store the forecast condition from the decision record as `weather_condition` on the actuals row (the forecast for that day was already logged)

### Phase 5: Update dashboard and last_updated.md

- Update the overview page to show the new reasoning (consumption estimate, generation estimate by weather match, gap)
- Remove feedback-related display elements
- Update `last_updated.md` template to reflect the new calculation steps

## What stays the same

- Growatt client (read/write API)
- Weather provider interface and Open-Meteo implementation
- Manual override mechanism
- Nightly scheduling (10PM via Task Scheduler)
- Dashboard infrastructure (FastAPI, Chart.js, SQLite)
- Weather API failure fallback (charge to 90%)

## Data flow

```
Nightly run (10PM):
1. Backfill yesterday's actuals + weather condition
2. Fetch tomorrow's forecast from Open-Meteo
3. Query: avg expensive-hours consumption (past 7 days)
4. Query: avg generation on {same condition, same month} days
5. gap = consumption - generation - current_soc
6. charge_pct = gap / usable_capacity * 100 (clamped 0-100)
7. Set charge on Growatt
8. Log decision to SQLite
9. Write last_updated.md
```

## Open questions

1. **Cost bias implementation** — deferred until we can see variance in weather-matched generation data
2. **Export rate** — currently assumed 0p/kWh. If the user starts getting paid for export (SEG, Octopus Outgoing), the overcharge cost drops and the bias calculation changes. Config already has an export_rate field for this.
