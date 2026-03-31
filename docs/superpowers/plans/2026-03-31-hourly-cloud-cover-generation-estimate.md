# Hourly Cloud-Cover Generation Estimate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the condition-bucket generation estimate with an hourly cloud-cover model that scales historical max generation by per-hour cloud cover percentages.

**Architecture:** A new `solar_day_length()` utility computes day length from latitude + date using the astronomical sunrise equation. A new `_estimate_generation_hourly()` function in the calculator looks up the month's max generation day, normalises it to kWh/solar-hour, then walks the forecast's hourly cloud cover to produce a cloud-adjusted estimate. Two new DB queries support the max-generation lookup.

**Tech Stack:** Python, SQLite, math stdlib

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/calculator/engine.py` | Modify | Add `solar_day_length()`, replace `_estimate_generation()` with `_estimate_generation_hourly()`, update `calculate_charge()` call |
| `src/db/queries.py` | Modify | Add `get_max_generation_for_month()` and `get_max_generation_for_adjacent_months()` |
| `tests/test_calculator.py` | Modify | Rewrite generation tests for new hourly model, add `solar_day_length` tests |

---

### Task 1: Add `solar_day_length` function with tests

**Files:**
- Modify: `src/calculator/engine.py`
- Modify: `tests/test_calculator.py`

- [ ] **Step 1: Write the failing tests for `solar_day_length`**

Add to `tests/test_calculator.py`:

```python
import math
from datetime import date


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calculator.py::test_solar_day_length_summer_solstice_london tests/test_calculator.py::test_solar_day_length_winter_solstice_london tests/test_calculator.py::test_solar_day_length_equinox tests/test_calculator.py::test_solar_day_length_equator_stable -v`

Expected: FAIL with `ImportError: cannot import name 'solar_day_length'`

- [ ] **Step 3: Implement `solar_day_length` in `src/calculator/engine.py`**

Add at top of file (after existing imports):

```python
import math


def solar_day_length(latitude_degrees: float, target_date: date) -> float:
    """Calculate hours of sunlight from latitude and date.

    Uses the astronomical sunrise equation with atmospheric refraction
    correction. Accurate to within ~5 minutes at UK latitudes.
    """
    lat_rad = math.radians(latitude_degrees)
    day_of_year = target_date.timetuple().tm_yday

    declination_rad = math.asin(
        math.sin(math.radians(23.44))
        * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    )

    correction_rad = math.radians(-0.8333)
    cos_hour_angle = (
        (math.sin(correction_rad) - math.sin(lat_rad) * math.sin(declination_rad))
        / (math.cos(lat_rad) * math.cos(declination_rad))
    )

    if cos_hour_angle >= 1.0:
        return 0.0
    if cos_hour_angle <= -1.0:
        return 24.0

    hour_angle = math.acos(cos_hour_angle)
    return (24.0 / math.pi) * hour_angle
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calculator.py::test_solar_day_length_summer_solstice_london tests/test_calculator.py::test_solar_day_length_winter_solstice_london tests/test_calculator.py::test_solar_day_length_equinox tests/test_calculator.py::test_solar_day_length_equator_stable -v`

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: add solar_day_length astronomical calculation"
```

---

### Task 2: Add DB queries for max generation lookup

**Files:**
- Modify: `src/db/queries.py`
- Modify: `tests/test_calculator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_calculator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calculator.py::test_get_max_generation_for_month tests/test_calculator.py::test_get_max_generation_for_month_no_data tests/test_calculator.py::test_get_max_generation_for_adjacent_months tests/test_calculator.py::test_get_max_generation_for_adjacent_months_wraps_december -v`

Expected: FAIL with `ImportError: cannot import name 'get_max_generation_for_month'`

- [ ] **Step 3: Implement queries in `src/db/queries.py`**

Add at the end of the file:

```python
def get_max_generation_for_month(conn: sqlite3.Connection, month: int) -> tuple[float, str] | None:
    """Return (max_generation_kwh, date_str) for the best generation day in a month."""
    cursor = conn.execute(
        """SELECT total_solar_generation_kwh, date FROM actuals
           WHERE CAST(strftime('%m', date) AS INTEGER) = ?
           ORDER BY total_solar_generation_kwh DESC LIMIT 1""",
        (month,))
    row = cursor.fetchone()
    if row is None:
        return None
    return (row[0], row[1])


def get_max_generation_for_adjacent_months(conn: sqlite3.Connection, month: int) -> tuple[float, str] | None:
    """Return (max_generation_kwh, date_str) for the best generation day in month +/- 1."""
    months = [(month - 2) % 12 + 1, month % 12 + 1]
    placeholders = ",".join("?" * len(months))
    cursor = conn.execute(
        f"""SELECT total_solar_generation_kwh, date FROM actuals
            WHERE CAST(strftime('%m', date) AS INTEGER) IN ({placeholders})
            ORDER BY total_solar_generation_kwh DESC LIMIT 1""",
        tuple(months))
    row = cursor.fetchone()
    if row is None:
        return None
    return (row[0], row[1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calculator.py::test_get_max_generation_for_month tests/test_calculator.py::test_get_max_generation_for_month_no_data tests/test_calculator.py::test_get_max_generation_for_adjacent_months tests/test_calculator.py::test_get_max_generation_for_adjacent_months_wraps_december -v`

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/db/queries.py tests/test_calculator.py
git commit -m "feat: add max generation queries for month and adjacent months"
```

---

### Task 3: Replace `_estimate_generation` with `_estimate_generation_hourly`

**Files:**
- Modify: `src/calculator/engine.py`
- Modify: `tests/test_calculator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_calculator.py`:

```python
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
    """100% cloud all day should return 0."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 34.0, 25.0, 30.0, 28.0])
    cloud_hours = [(h, 100) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    assert gen_kwh == 0.0


def test_estimate_generation_hourly_half_cloud(tmp_path, config):
    """50% cloud all day should return ~half of max."""
    from src.calculator.engine import _estimate_generation_hourly
    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="sunny", values=[20.0, 34.0, 25.0, 30.0, 28.0])
    cloud_hours = [(h, 50) for h in range(6, 18)]
    forecast = _make_forecast_with_cloud(date(2026, 3, 15), cloud_hours)
    gen_kwh, source = _estimate_generation_hourly(conn, 3, forecast, 51.5)
    # Should be roughly half of the clear-sky estimate
    assert 13.0 <= gen_kwh <= 20.0


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calculator.py::test_estimate_generation_hourly_clear_sky tests/test_calculator.py::test_estimate_generation_hourly_full_cloud tests/test_calculator.py::test_estimate_generation_hourly_half_cloud tests/test_calculator.py::test_estimate_generation_hourly_mixed_cloud tests/test_calculator.py::test_estimate_generation_hourly_fallback_adjacent_month tests/test_calculator.py::test_estimate_generation_hourly_no_data -v`

Expected: FAIL with `ImportError: cannot import name '_estimate_generation_hourly'`

- [ ] **Step 3: Implement `_estimate_generation_hourly` in `src/calculator/engine.py`**

Replace the existing `_estimate_generation` function with:

```python
def _estimate_generation_hourly(
    conn: sqlite3.Connection, month: int, forecast: DayForecast, latitude: float
) -> tuple[float, str]:
    result = get_max_generation_for_month(conn, month)
    source_label = "max"
    if result is None:
        result = get_max_generation_for_adjacent_months(conn, month)
        source_label = "adjacent month max"
    if result is None:
        return 0.0, "no historical generation data"

    max_gen_kwh, max_gen_date_str = result
    max_gen_date = date.fromisoformat(max_gen_date_str)

    max_day_solar_hours = solar_day_length(latitude, max_gen_date)
    if max_day_solar_hours <= 0:
        return 0.0, "no solar hours on max generation day"

    kwh_per_solar_hour = max_gen_kwh / max_day_solar_hours

    estimated = sum(
        kwh_per_solar_hour * (100 - h.cloud_cover_pct) / 100
        for h in forecast.hourly
    )

    forecast_solar_hours = len(forecast.hourly)
    description = (
        f"{source_label} {max_gen_kwh:.1f}kWh on {max_gen_date_str}, "
        f"{max_day_solar_hours:.1f} solar hrs, "
        f"cloud-adjusted from {forecast_solar_hours} forecast hrs"
    )
    return estimated, description
```

Add `get_max_generation_for_month` and `get_max_generation_for_adjacent_months` to the existing import from `..db.queries` at the top of `src/calculator/engine.py`.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_calculator.py::test_estimate_generation_hourly_clear_sky tests/test_calculator.py::test_estimate_generation_hourly_full_cloud tests/test_calculator.py::test_estimate_generation_hourly_half_cloud tests/test_calculator.py::test_estimate_generation_hourly_mixed_cloud tests/test_calculator.py::test_estimate_generation_hourly_fallback_adjacent_month tests/test_calculator.py::test_estimate_generation_hourly_no_data -v`

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: add hourly cloud-cover generation estimate function"
```

---

### Task 4: Wire `_estimate_generation_hourly` into `calculate_charge` and update existing tests

**Files:**
- Modify: `src/calculator/engine.py`
- Modify: `tests/test_calculator.py`

- [ ] **Step 1: Update `calculate_charge` to call `_estimate_generation_hourly`**

In `src/calculator/engine.py`, change the `calculate_charge` function. Replace:

```python
    month = forecast.date.month
    condition = forecast.condition

    expected_consumption, consumption_source = _estimate_consumption(conn)
    expected_generation, generation_source = _estimate_generation(conn, month, condition)
```

with:

```python
    month = forecast.date.month

    expected_consumption, consumption_source = _estimate_consumption(conn)
    expected_generation, generation_source = _estimate_generation_hourly(
        conn, month, forecast, config.location.latitude
    )
```

- [ ] **Step 2: Update the reason string format**

In `calculate_charge`, update the generation reason part to use the new source description. Replace:

```python
        f"Generation: {expected_generation:.3f}kWh ({generation_source})",
```

with:

```python
        f"Generation: {expected_generation:.3f}kWh ({generation_source})",
```

No change needed — the format string is the same, but the `generation_source` content is now the new descriptive string from `_estimate_generation_hourly`.

- [ ] **Step 3: Update existing tests that relied on condition-based generation**

The existing tests use `_populate_generation` which inserts rows with a specific `weather_condition`. The new estimator ignores condition and uses max generation for the month. Update the following tests:

In `test_sunny_day_good_generation_charges_low`: The test populates month=6 with values `[30.0, 31.0, 29.0, 30.5, 28.5, 32.0]` — max is 32.0. With the `_make_forecast` helper creating 15 hours of 20% cloud, the generation estimate will be roughly `32.0 * (80/100) * (forecast_hours / max_day_hours)`. This should still exceed the 8 kWh consumption, so the assertion `charge_level <= 20` should hold. No change needed.

In `test_cloudy_day_poor_generation_charges_high`: Populates month=3 with values `[2.0, 1.5, 2.5, 1.8, 2.2, 2.0]` — max is 2.5. With 20% cloud the estimate will be ~2.0 kWh. Consumption is 20 kWh. Should still charge high. No change needed.

In `test_winter_day_no_winter_override`: Populates month=12 with `[1.0, 0.8, 1.2, 0.9, 1.1, 1.0]` — max is 1.2. With 20% cloud and short winter days, estimate will be very low. Should still charge high. No change needed.

In `test_falls_back_to_wider_month_window`: This test checks for `"month±1"` in the reason string. Update the assertion to match the new source format:

```python
    # Old: assert "month±1" in result.reason or "month" in result.reason
    # New: the source string will say "max" (if month 6 has data) or "adjacent" (if not)
    assert result.charge_level <= 30
```

The test populates month=6 with 2 values `[25.0, 26.0]` — `get_max_generation_for_month` will find month=6 data (max 26.0), so it won't fall back. Remove the condition-specific assertion since it no longer applies. Replace the assertion with:

```python
    assert "max" in result.reason.lower() or "adjacent" in result.reason.lower()
    assert result.charge_level <= 30
```

In `test_charge_clamped_to_zero_with_massive_generation`: Max is 100.0, cloud 20%, so estimate will be very high. Should still clamp to 0. No change needed.

- [ ] **Step 4: Run all calculator tests**

Run: `pytest tests/test_calculator.py -v`

Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: wire hourly cloud-cover estimate into calculate_charge"
```

---

### Task 5: Clean up unused code and run full test suite

**Files:**
- Modify: `src/calculator/engine.py`

- [ ] **Step 1: Remove the old `_estimate_generation` function**

Delete the entire `_estimate_generation` function from `src/calculator/engine.py` (the one that takes `conn, month, condition`).

Also remove imports that were only used by the old function. Check if `get_generation_by_weather`, `get_generation_by_weather_wide`, `get_generation_by_condition`, `get_generation_by_month` are still imported at the top of the file. If so, remove those imports (the functions remain in `queries.py` but the calculator no longer uses them).

Remove the old `_percentile_25` function if it's no longer used anywhere in the file.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`

Expected: All tests PASSED

- [ ] **Step 3: Commit**

```bash
git add src/calculator/engine.py
git commit -m "refactor: remove unused condition-based generation estimate"
```
