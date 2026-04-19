# Morning Gap Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the battery always charges enough to cover morning consumption between cheap rate end (05:30) and when solar generation can sustain the house, plus a configurable buffer.

**Architecture:** Add a `_morning_floor_kwh` function to the calculator engine that uses hourly forecast radiation data to find when solar covers load, then calculates the kWh needed to bridge the gap. The existing `calculate_charge` takes `max(existing_gap, morning_floor)`. New `morning_buffer_kwh` config field under `battery`.

**Tech Stack:** Python 3.12, SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-04-07-morning-gap-floor-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/config.py` | Modify | Add `morning_buffer_kwh` field to `BatteryConfig` |
| `src/calculator/engine.py` | Modify | Add `_morning_floor_kwh` function, update `calculate_charge` |
| `tests/conftest.py` | Modify | Add `morning_buffer_kwh` to test config YAML |
| `tests/test_calculator.py` | Modify | Add morning floor tests |
| `config.yaml` | Modify | Add `morning_buffer_kwh: 2.0` |
| `config.example.yaml` | Modify | Add `morning_buffer_kwh: 2.0` |

---

### Task 1: Add `morning_buffer_kwh` to config

**Files:**
- Modify: `src/config.py:30-36` (`BatteryConfig` dataclass)
- Modify: `tests/conftest.py:5-28` (`VALID_CONFIG_YAML`)
- Modify: `config.yaml`
- Modify: `config.example.yaml`

- [ ] **Step 1: Add field to BatteryConfig**

In `src/config.py`, add `morning_buffer_kwh` to `BatteryConfig`:

```python
@dataclass
class BatteryConfig:
    total_capacity_kwh: float
    usable_fraction: float
    fallback_charge_level: int = 90
    morning_buffer_kwh: float = 2.0

    @property
    def usable_capacity_kwh(self) -> float:
        return self.total_capacity_kwh * self.usable_fraction
```

- [ ] **Step 2: Update test config YAML**

In `tests/conftest.py`, add `morning_buffer_kwh` to `VALID_CONFIG_YAML` under `battery`:

```yaml
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  morning_buffer_kwh: 2.0
```

- [ ] **Step 3: Update config.yaml**

Add `morning_buffer_kwh: 2.0` under `battery` in `config.yaml`.

- [ ] **Step 4: Update config.example.yaml**

Add `morning_buffer_kwh: 2.0` under `battery` in `config.example.yaml`.

- [ ] **Step 5: Run existing tests to confirm nothing broke**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: All 21 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/conftest.py config.yaml config.example.yaml
git commit -m "feat: add morning_buffer_kwh config field"
```

---

### Task 2: Add `_morning_floor_kwh` function with tests

**Files:**
- Modify: `src/calculator/engine.py` (add `_morning_floor_kwh`)
- Modify: `tests/test_calculator.py` (add morning floor unit tests)

- [ ] **Step 1: Write failing test — sunny day morning floor**

Add to `tests/test_calculator.py`:

```python
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
    # Hourly data: low radiation until hour 8, then strong
    # Consumption ~1.1 kWh/hr (20 kWh / 18 expensive hrs)
    hourly_data = [
        (6, 10, 50),    # 6am: weak solar
        (7, 10, 100),   # 7am: still weak
        (8, 10, 400),   # 8am: strong — generation should exceed consumption here
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
    expected_consumption = 20.0  # 20 kWh total expensive consumption
    kwh_per_solar_hour = 35.0 / solar_day_length(51.4067, date(2025, 4, 2))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # Gap hours: 06, 07 = 2 hours. Hourly consumption: 20/18 = 1.11 kWh.
    # Floor = 2 * 1.11 + 2.0 buffer = ~4.2 kWh
    assert 3.0 <= result <= 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calculator.py::test_morning_floor_sunny_day -v`
Expected: FAIL — `_morning_floor_kwh` not defined.

- [ ] **Step 3: Implement `_morning_floor_kwh`**

Add to `src/calculator/engine.py` after `_estimate_generation_hourly`:

```python
def _morning_floor_kwh(
    config: Config,
    forecast: DayForecast,
    expected_consumption: float,
    kwh_per_solar_hour: float,
) -> float:
    """Calculate minimum kWh needed to bridge cheap-rate end to solar-covers-load.

    Returns the kWh the battery needs to cover morning consumption from
    cheap_end until hourly solar generation exceeds hourly consumption,
    plus the configured morning buffer.
    """
    if not forecast.hourly or kwh_per_solar_hour <= 0:
        return 0.0

    # Parse cheap_end hour (round up partial hours: 05:30 -> hour 6)
    end_h, end_m = (int(x) for x in config.rates.cheap_end.split(":"))
    first_expensive_hour = end_h + (1 if end_m > 0 else 0)

    # Expensive hours in the day (for hourly consumption estimate)
    start_h, start_m = (int(x) for x in config.rates.cheap_start.split(":"))
    cheap_start_t = start_h * 60 + start_m
    cheap_end_t = end_h * 60 + end_m
    if cheap_start_t > cheap_end_t:
        cheap_duration_mins = (24 * 60 - cheap_start_t) + cheap_end_t
    else:
        cheap_duration_mins = cheap_end_t - cheap_start_t
    expensive_hours = (24 * 60 - cheap_duration_mins) / 60

    if expensive_hours <= 0:
        return 0.0

    hourly_consumption = expected_consumption / expensive_hours

    # Find first forecast hour >= first_expensive_hour where generation covers load
    gap_hours = 0
    solar_covers_load_found = False
    for h_forecast in sorted(forecast.hourly, key=lambda h: h.hour):
        if h_forecast.hour < first_expensive_hour:
            continue
        hour_gen = kwh_per_solar_hour * (100 - h_forecast.cloud_cover_pct) / 100
        if hour_gen >= hourly_consumption:
            solar_covers_load_found = True
            break
        gap_hours += 1

    if not solar_covers_load_found and gap_hours == 0:
        return 0.0

    return hourly_consumption * gap_hours + config.battery.morning_buffer_kwh
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_morning_floor_sunny_day -v`
Expected: PASS

- [ ] **Step 5: Write failing test — cloudy day (solar never covers load)**

Add to `tests/test_calculator.py`:

```python
def test_morning_floor_cloudy_day(tmp_path, config):
    """Cloudy day: solar never covers load, morning floor spans all forecast hours."""
    from src.calculator.engine import _morning_floor_kwh
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=4, condition="cloudy",
                         values=[5.0, 6.0, 4.0, 5.5, 4.5])
    # All hours have heavy cloud, weak radiation
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
    kwh_per_solar_hour = 6.0 / solar_day_length(51.4067, date(2025, 4, 3))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # Generation per hour is tiny (kwh_per_solar_hour ~0.44 * 10-20% clear = ~0.04-0.09)
    # which is well below hourly consumption of 1.11 kWh
    # All 12 forecast hours from hour 6 onward are gap hours
    # Floor = 12 * 1.11 + 2.0 = ~15.3 kWh
    assert result > 10.0
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_morning_floor_cloudy_day -v`
Expected: PASS (implementation already handles this case — gap_hours counts all hours with no break).

- [ ] **Step 7: Write failing test — no forecast data**

Add to `tests/test_calculator.py`:

```python
def test_morning_floor_no_forecast_data(tmp_path, config):
    """No hourly forecast data returns 0."""
    from src.calculator.engine import _morning_floor_kwh
    forecast = DayForecast(
        date=date(2026, 4, 15), sunrise=time(6, 0), sunset=time(20, 0),
        hourly=[], condition="sunny", max_temperature_c=15.0
    )
    result = _morning_floor_kwh(config, forecast, 20.0, 2.5)
    assert result == 0.0
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_morning_floor_no_forecast_data -v`
Expected: PASS

- [ ] **Step 9: Write failing test — solar covers load at first hour**

Add to `tests/test_calculator.py`:

```python
def test_morning_floor_solar_covers_load_immediately(tmp_path, config):
    """Solar covers load at first expensive hour — floor is just the buffer."""
    from src.calculator.engine import _morning_floor_kwh
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=6, condition="sunny",
                         values=[40.0, 42.0, 38.0, 41.0, 39.0])
    # Strong radiation from hour 6 onward
    hourly_data = [
        (6, 5, 600),
        (7, 5, 700),
        (8, 5, 800),
        (9, 5, 850),
        (10, 5, 900),
    ]
    forecast = _make_forecast_with_radiation(date(2026, 6, 15), hourly_data)
    expected_consumption = 20.0
    kwh_per_solar_hour = 42.0 / solar_day_length(51.4067, date(2025, 6, 1))

    result = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    # kwh_per_solar_hour ~2.6, at 95% clear = ~2.47, vs hourly consumption 1.11
    # Solar covers load at hour 6 immediately, gap_hours = 0
    # Floor = 0 * 1.11 + 2.0 = 2.0 (just the buffer)
    assert result == config.battery.morning_buffer_kwh
```

- [ ] **Step 10: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_morning_floor_solar_covers_load_immediately -v`
Expected: PASS

- [ ] **Step 11: Run all tests**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: All 25 tests pass (21 existing + 4 new).

- [ ] **Step 12: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: add _morning_floor_kwh function with tests"
```

---

### Task 3: Integrate morning floor into `calculate_charge`

**Files:**
- Modify: `src/calculator/engine.py:101-141` (`calculate_charge`)
- Modify: `tests/test_calculator.py` (add integration tests)

- [ ] **Step 1: Write failing test — sunny day charge level uses morning floor**

Add to `tests/test_calculator.py`:

```python
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
                              current_soc=50, conn=conn)
    # Daily gap would be negative (generation >> consumption with 50% SOC)
    # But morning floor should set a minimum > 0
    assert result.charge_level > 0
    assert "morning floor" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calculator.py::test_sunny_day_uses_morning_floor -v`
Expected: FAIL — "morning floor" not in reason.

- [ ] **Step 3: Update `calculate_charge` to apply morning floor**

In `src/calculator/engine.py`, modify `calculate_charge`. After the existing gap calculation (line ~126) and before the reason assembly, add the morning floor logic. Replace the section from `gap_kwh = ...` to the end of the function:

```python
    gap_kwh = expected_consumption - expected_generation - current_soc_kwh
    charge_pct = (gap_kwh / usable_capacity_kwh) * 100

    # Morning floor: ensure enough charge to bridge cheap-rate end to solar
    # Needs kwh_per_solar_hour from generation estimate
    result = get_max_generation_for_month(conn, month)
    if result is None:
        result = get_max_generation_for_adjacent_months(conn, month)
    if result is not None:
        max_gen_kwh, max_gen_date_str = result
        max_gen_date = date.fromisoformat(max_gen_date_str)
        max_day_solar_hours = solar_day_length(config.location.latitude, max_gen_date)
        if max_day_solar_hours > 0:
            kwh_per_solar_hour = max_gen_kwh / max_day_solar_hours
        else:
            kwh_per_solar_hour = 0.0
    else:
        kwh_per_solar_hour = 0.0

    morning_kwh = _morning_floor_kwh(config, forecast, expected_consumption, kwh_per_solar_hour)
    morning_pct = (morning_kwh / usable_capacity_kwh) * 100

    if morning_pct > charge_pct:
        charge_level = int(max(0, min(100, round(morning_pct))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh (binding)"
    else:
        charge_level = int(max(0, min(100, round(charge_pct))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh"

    reason_parts = [
        f"Consumption: {expected_consumption:.3f}kWh ({consumption_source})",
        f"Generation: {expected_generation:.3f}kWh ({generation_source})",
        f"Current SOC: {current_soc}% ({current_soc_kwh:.3f}kWh)",
        f"Gap: {gap_kwh:.3f}kWh",
        morning_floor_note,
        f"Charge level: {charge_level}%",
    ]
    if "total consumption fallback" in consumption_source:
        reason_parts.append("Note: using total consumption as fallback (no expensive_consumption_kwh data)")

    return ChargeResult(
        charge_level=charge_level,
        reason=". ".join(reason_parts),
    )
```

Note: the `kwh_per_solar_hour` lookup duplicates logic from `_estimate_generation_hourly`. This is acceptable — extracting it would change that function's signature and break existing callers for no real benefit.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_sunny_day_uses_morning_floor -v`
Expected: PASS

- [ ] **Step 5: Write failing test — cloudy day, daily gap wins over morning floor**

Add to `tests/test_calculator.py`:

```python
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
                              current_soc=10, conn=conn)
    # Daily gap should be large (consumption >> generation)
    assert result.charge_level >= 70
    # Morning floor should not be the binding constraint
    assert "morning floor" in result.reason.lower()
    assert "(binding)" not in result.reason.lower()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_calculator.py::test_cloudy_day_daily_gap_wins -v`
Expected: PASS

- [ ] **Step 7: Run all tests to confirm nothing broke**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: All 27 tests pass (21 existing + 4 morning floor unit + 2 integration).

- [ ] **Step 8: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: integrate morning floor into calculate_charge"
```

---

### Task 4: Verify with real scenario and run charge

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass.

- [ ] **Step 2: Dry-run with real config to check output**

Run:
```bash
python -c "
from datetime import date, timedelta
from pathlib import Path
from src.config import load_config
from src.db.schema import init_db
from src.weather.open_meteo import OpenMeteoProvider
from src.calculator.engine import calculate_charge

config = load_config(Path('config.yaml'))
conn = init_db(Path('data/battery.db'))
weather = OpenMeteoProvider()
tomorrow = date.today() + timedelta(days=1)
forecast = weather.get_forecast(
    config.location.latitude, config.location.longitude,
    tomorrow, config.location.timezone
)
result = calculate_charge(config=config, forecast=forecast, current_soc=10, conn=conn)
print(f'Charge level: {result.charge_level}%')
print(f'Reason: {result.reason}')
"
```

Expected: On a sunny day, charge level should be non-zero (morning floor binding). On a cloudy day, daily gap should be larger.

- [ ] **Step 3: Run the full nightly charge**

Run: `/charge-battery`

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: morning gap floor ensures battery covers pre-solar hours"
```
