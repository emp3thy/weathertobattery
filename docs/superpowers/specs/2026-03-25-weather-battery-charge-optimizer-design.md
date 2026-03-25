# Weather-to-Battery Charge Optimizer

## Overview

A system that optimizes overnight battery charging for a Growatt battery system by analyzing weather forecasts and historical usage data. The goal: minimize unnecessary overnight charging (at 7p/kWh) while ensuring enough stored energy to avoid pulling from the grid during expensive hours (30p/kWh). Cheap rate is 11:30PM-5:30AM; all other hours are expensive.

## Location & Hardware

- Location: London (51.4067, 0.0481)
- Battery: 13.3kWh total, ~12kWh usable (90%)
- Daily consumption: ~25kWh
- Solar: panels favour morning generation; peak production profile derived from Growatt historical data
- Pool heater: mid-May to September, 10AM-3/4PM, 6kWh/hour (24-36kWh per session)
- Good summer day generation: ~40kWh

## Architecture

Five components plus two Claude Code skills:

### 1. Weather Provider

Abstract interface for fetching tomorrow's forecast. First implementation: Open-Meteo (free, no API key).

**Input:** latitude, longitude, date

**Output:** standardised forecast object:
- Hourly breakdown (sunrise to sunset only): cloud cover %, solar radiation (W/m2), precipitation probability
- Sunrise and sunset times
- Overall condition bucket: sunny / cloudy / rainy

**Bucketing logic** (applied to solar hours only):
- Sunny: average cloud cover < 30%, minimal precipitation
- Cloudy: average cloud cover 30-70%, or >70% with no rain
- Rainy: precipitation probability > 50% for at least 50% of solar hours

Hourly data is weighted by the solar productivity profile (see Calculator) so that weather during peak production hours has more influence than weather during low-production hours.

The interface is abstracted so providers can be swapped (e.g., Met Office, OpenWeatherMap) by implementing the same output shape.

### 2. Growatt Client

Wraps the `growattServer` Python library. Authentication method to be validated during implementation — the library typically uses username/password login. If the personal API token from the ShineServer portal is not directly supported by the library, we will either: (a) use username/password stored securely in config, or (b) implement direct HTTP calls using the token. Authentication approach will be confirmed in the first implementation task.

**Reads:**
- Device info (model, serial, capacity)
- Historical daily/hourly generation and consumption
- Historical grid import/export
- Current battery state of charge
- Current charge level target

**Writes:**
- Set overnight charge target percentage

**Error handling:**
- API down: retry up to 3 times with exponential backoff (5s, 15s, 45s). If all retries fail, log failure and skip that night (can't set battery if API is down)
- Auth failure: log and alert

**Data caching:** Historical data cached in SQLite to avoid re-fetching.

### 3. Charge Calculator

Formula-based from the start, using Growatt historical data. No lookup table.

**Calculation:**
1. Pull historical data for similar days: same month (within a 4-week window centred on tomorrow's date), matching weather bucket (sunny/cloudy/rainy), minimum 5 days required. If fewer than 5 matching days exist, widen to 6-week window, then fall back to month-level averages regardless of weather.
2. Build solar productivity profile: which hours of the day panels produce most, per month/season (derived from Growatt historical hourly generation)
3. Weight tomorrow's hourly forecast by the productivity profile — cloud cover during peak production hours matters more
4. Calculate expected solar yield from weighted forecast
5. Calculate expected consumption from historical averages for this type of day. Pool heater days are classified separately (see Pool Heater section) — only compare against historical days with similar pool heater usage.
6. Read current battery SOC from Growatt. Shortfall = expected consumption - expected solar yield - current battery SOC (converted to kWh)
7. Charge level = shortfall as percentage of usable battery capacity
8. Clamp between floor (30%) and 100%

**First-year bootstrap:** If insufficient historical data exists (new install or early days), fall back to a conservative estimate: charge to 80% in spring/autumn, 60% on sunny summer days, 100% in winter. These bootstrap values are replaced as real data accumulates.

**Feedback loop (bidirectional):**

Each evening, pull the most recent completed solar day's actuals. At 10PM, today's solar day is complete (even in summer, sunset in London is before 9:30PM). So "yesterday" means the day that just ended (today's date).

- **Undercharged:** Grid import during expensive hours means we needed more charge. If tomorrow's forecast is the same or worse than today's, increase charge level proportionally to the grid draw.
- **Overcharged:** Battery hit 100% and exported surplus to grid for free (energy we paid 7p to store). If tomorrow's forecast is the same or better than today's, decrease charge level proportionally to the surplus export.

**Adjustment caps:** Individual feedback adjustments are capped at +/- 15 percentage points per night. Cumulative adjustments from the feedback loop are capped at +/- 25 percentage points from the base calculation. Adjustments decay by 5 percentage points per day if the triggering condition does not recur (i.e., if the system stops over/undercharging, the adjustment gradually returns to zero).

**Pool heater season (mid-May to September):**
Pool heater days are identified explicitly. A day is classified as a "pool heater day" if:
- It falls within the configured pool heater season (default: 15 May - 30 September)
- AND the forecast temperature exceeds a configurable threshold (default: 18C) — since the heater runs when it's warm enough to swim

Historical consumption data is split into pool-heater-on and pool-heater-off cohorts. The calculator selects the appropriate cohort based on whether tomorrow is expected to be a pool heater day. This prevents averaging across fundamentally different usage patterns (25kWh normal day vs 50kWh+ pool heater day).

**Winter override (25 October to end of February):**
Charge to 100% always. Solar yield is negligible and not worth optimizing. Start/end dates configurable in `config.yaml`.

**Fallback:** If weather API is unavailable (after 3 retries with exponential backoff), default to 90% charge and log the failure.

**Manual override:** A `manual_override` field in config.yaml allows forcing a specific charge level for the next run. The orchestrator checks this before running the calculator. After applying, it clears the override and logs that it was used. The `/charge-battery` skill can also accept an override parameter.

**Idempotency:** If the skill runs multiple times on the same evening, it overwrites the previous decision for that date (upsert to the decisions table). Only one decision per date is stored.

### 4. Data Store

SQLite database (`data/battery.db`).

**Tables:**

**decisions** — one row per night:
- date, forecast_summary, forecast_detail (hourly solar radiation, cloud cover), charge_level_set (%), base_charge_level (% before feedback adjustment), feedback_adjustment (%), adjustment_reason, current_soc_at_decision (%), month, weather_provider_used

**actuals** — one row per day, backfilled the following evening:
- date, total_solar_generation_kwh, total_consumption_kwh, grid_import_kwh (expensive hours only), grid_export_kwh (while battery full), peak_solar_hour, battery_min_soc (%), battery_max_soc (%)

**adjustments** — log of feedback adjustments:
- date, direction (up/down), amount (%), trigger (grid_draw/surplus_export), previous_day_weather, tomorrow_forecast, grid_draw_kwh, surplus_export_kwh

**config** — tuneable parameters:
- floor percentage, adjustment step sizes, location, pool heater season dates

### 5. Dashboard

Lightweight FastAPI web app, served locally on localhost.

**Pages:**

- **Overview** — tonight's charge decision, tomorrow's forecast, yesterday's actual vs predicted
- **History** — table/chart of past decisions with date, forecast, charge set, actual generation, grid import, grid export. Filterable by date range and month.
- **Forecast Accuracy** — weather forecast vs actual solar generation
- **Cost Savings** — estimated money saved vs charging to 100% every night: battery charge avoided (kWh at 7p), grid import during expensive hours (kWh at 30p), surplus exported for free (wasted at 7p)
- **Solar Profile** — hourly productivity curve by month, built from Growatt data

**Tech:** FastAPI backend, HTML templates, Chart.js for charts. Reads from SQLite only.

### 6. Skills

**`/charge-battery`**
- Runs the full nightly logic: fetch forecast, calculate charge, set on Growatt, log to SQLite, write `last_updated.md`
- Outputs a plain-language summary of what it did and why
- Invoked nightly at 10PM via Windows Task Scheduler + Claude Code with pre-injected prompt
- Can be run manually at any time

**`/battery-dashboard`**
- Starts the FastAPI server if not already running
- Opens the dashboard in the browser
- Can answer questions about the data by reading SQLite and `last_updated.md`

### 7. last_updated.md

Rewritten completely each run. Contains:
- Date/time of run
- Tomorrow's forecast summary (solar hours breakdown)
- Historical comparison used (similar days referenced)
- Charge level set and reasoning
- Yesterday's feedback (over/undercharged, any adjustment made)
- Any errors or warnings

Read by the skill to provide plain-language explanations.

## Project Structure

```
weatherToBattery/
├── src/
│   ├── weather/          # Weather provider interface + Open-Meteo implementation
│   ├── growatt/           # Growatt API client
│   ├── calculator/        # Charge calculation logic
│   ├── dashboard/         # FastAPI app, templates, static assets
│   ├── db/                # SQLite schema, queries, migrations
│   └── orchestrator.py    # Ties it all together
├── data/
│   └── battery.db         # SQLite database
├── config.yaml            # Location, credentials ref, tuneable params
├── last_updated.md        # Rewritten each run
├── skills/
│   ├── charge-battery.md
│   └── battery-dashboard.md
├── docs/
│   └── superpowers/specs/ # This design doc
└── tests/
```

## Key Rates

- Cheap rate: 7p/kWh (11:30PM - 5:30AM)
- Expensive rate: 30p/kWh (all other hours)
- Export rate: configurable, default 0p/kWh (set in config.yaml — some tariffs pay 4-15p/kWh via SEG or Octopus Outgoing)

## Configuration

Stored in `config.yaml`:
- Location (lat/long)
- Growatt API token reference (and/or username/password, depending on auth method validation)
- Battery capacity and usable percentage
- Charge floor percentage (default 30%)
- Feedback adjustment caps (per-night max, cumulative max, decay rate)
- Pool heater season dates and temperature threshold
- Cheap/expensive rate times and costs
- Export rate (default 0p/kWh)
- Winter override start/end dates
- Weather provider selection
- Dashboard port
- Manual override charge level (optional, cleared after use)

**Validation:** Config values are validated on load. Invalid values (e.g., floor < 0 or > 100, negative capacity) cause the run to abort with a clear error message.
