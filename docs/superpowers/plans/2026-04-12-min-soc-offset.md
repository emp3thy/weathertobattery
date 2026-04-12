# Min SOC Offset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account for the inverter's 10% discharge cutoff so charge calculations reflect actual usable energy.

**Architecture:** Add `min_soc_pct` (default 10) to `BatteryConfig`. Subtract it from reported SOC before calculations, add it to the output charge level before sending to the inverter. Existing tests updated to expect the +10 offset.

**Tech Stack:** Python, pytest

---

### Task 1: Add `min_soc_pct` to config

**Files:**
- Modify: `src/config.py:29-37`
- Modify: `config.example.yaml:12-15`
- Modify: `tests/conftest.py:17-18`
- Modify: `tests/test_config.py:36`

- [ ] **Step 1: Write failing test for min_soc_pct config loading**

Add to `tests/test_config.py` after the existing `test_load_config_returns_dataclass`:

```python
def test_config_loads_min_soc_pct(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test"
  password: "test"
  plant_id: "123"
  device_sn: "ABC"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  min_soc_pct: 15
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.battery.min_soc_pct == 15


def test_config_defaults_min_soc_pct(tmp_path):
    """Config without min_soc_pct should default to 10."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test"
  password: "test"
  plant_id: "123"
  device_sn: "ABC"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.battery.min_soc_pct == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py::test_config_loads_min_soc_pct tests/test_config.py::test_config_defaults_min_soc_pct -v`
Expected: FAIL — `BatteryConfig` has no `min_soc_pct` field

- [ ] **Step 3: Add `min_soc_pct` to BatteryConfig**

In `src/config.py`, change `BatteryConfig`:

```python
@dataclass
class BatteryConfig:
    total_capacity_kwh: float
    usable_fraction: float
    fallback_charge_level: int = 90
    morning_buffer_kwh: float = 2.0
    min_soc_pct: int = 10

    @property
    def usable_capacity_kwh(self) -> float:
        return self.total_capacity_kwh * self.usable_fraction
```

- [ ] **Step 4: Add validation for min_soc_pct**

In `src/config.py`, add to `_validate`:

```python
if not (0 <= cfg.battery.min_soc_pct < 100):
    raise ConfigValidationError("min_soc_pct must be between 0 and 99")
```

- [ ] **Step 5: Update config.example.yaml**

Add `min_soc_pct: 10` to the battery section:

```yaml
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  fallback_charge_level: 90
  morning_buffer_kwh: 2.0
  min_soc_pct: 10
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/config.py config.example.yaml tests/test_config.py
git commit -m "feat: add min_soc_pct to BatteryConfig (default 10)"
```

---

### Task 2: Apply min_soc_pct offset in calculator

**Files:**
- Modify: `src/calculator/engine.py:153-218`
- Test: `tests/test_calculator.py`

- [ ] **Step 1: Write failing test for min_soc_pct offset**

Add to `tests/test_calculator.py`:

```python
def test_min_soc_offset_applied(tmp_path):
    """Charge level is offset by min_soc_pct: input SOC adjusted down, output adjusted up."""
    from src.calculator.engine import calculate_charge
    from src.config import load_config
    from tests.conftest import VALID_CONFIG_YAML

    # Use min_soc_pct=10 (the default from conftest)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML)
    config = load_config(config_file)
    assert config.battery.min_soc_pct == 10

    conn = _make_db(tmp_path)
    _populate_generation(conn, month=3, condition="cloudy",
                         values=[2.0, 1.5, 2.5, 1.8, 2.2, 2.0])
    _populate_expensive_consumption(conn, [20.0, 21.0, 19.5, 20.5, 20.0])
    forecast = _make_forecast(date(2026, 3, 15), condition="cloudy")

    # With min_soc_pct=0, reported SOC=10 means 10% usable
    # With min_soc_pct=10, reported SOC=10 means 0% usable — should charge more
    config_zero = load_config(config_file)

    # Create a config with min_soc_pct=0 for comparison
    config_file_zero = tmp_path / "config_zero.yaml"
    config_file_zero.write_text(VALID_CONFIG_YAML.replace(
        "morning_buffer_kwh: 2.0",
        "morning_buffer_kwh: 2.0\n  min_soc_pct: 0"
    ))
    config_zero = load_config(config_file_zero)

    result_with_offset = calculate_charge(config=config, forecast=forecast,
                                          current_soc=20, conn=conn)
    result_without_offset = calculate_charge(config=config_zero, forecast=forecast,
                                             current_soc=20, conn=conn)

    # With offset: effective SOC is 10%, output gets +10
    # Without offset: effective SOC is 20%, output gets +0
    # Net effect: with offset should be higher by roughly 20 (10 from lower input + 10 from output bump)
    assert result_with_offset.charge_level > result_without_offset.charge_level
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calculator.py::test_min_soc_offset_applied -v`
Expected: FAIL — both configs produce the same result (offset not applied yet)

- [ ] **Step 3: Apply the offset in calculate_charge**

In `src/calculator/engine.py`, modify `calculate_charge`. Change lines 173-177 to:

```python
    usable_capacity_kwh = config.battery.usable_capacity_kwh
    min_soc = config.battery.min_soc_pct
    effective_soc = max(0, current_soc - min_soc)
    current_soc_kwh = (effective_soc / 100) * usable_capacity_kwh
```

Then change lines 197-202 (the charge_level assignments) to add the offset:

```python
    if morning_pct > charge_pct:
        charge_level = int(max(0, min(100, round(morning_pct + min_soc))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh (binding)"
    else:
        charge_level = int(max(0, min(100, round(charge_pct + min_soc))))
        morning_floor_note = f"Morning floor: {morning_kwh:.3f}kWh"
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest tests/test_calculator.py::test_min_soc_offset_applied -v`
Expected: PASS

- [ ] **Step 5: Run all calculator tests and fix any broken assertions**

Run: `pytest tests/test_calculator.py -v`

Several existing tests will need updated assertions because charge levels are now +10 higher:

- `test_sunny_day_good_generation_charges_low`: change `assert result.charge_level <= 20` to `assert result.charge_level <= 30`
- `test_charge_clamped_to_zero_with_massive_generation`: the morning floor minimum is now `morning_floor_pct + 10`. Update:
  ```python
  morning_floor_pct = int(round(config.battery.morning_buffer_kwh / config.battery.usable_capacity_kwh * 100)) + config.battery.min_soc_pct
  assert result.charge_level == morning_floor_pct
  ```
- `test_falls_back_to_wider_month_window`: change `assert result.charge_level <= 30` to `assert result.charge_level <= 40`
- Other tests with `>=` thresholds (like `>= 70`, `>= 60`) should still pass since the offset only increases charge levels.

Run tests after each fix to confirm.

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: apply min_soc_pct offset to charge calculations"
```

---

### Task 3: Update conftest and remaining test fixtures

**Files:**
- Modify: `tests/conftest.py:17-18`

- [ ] **Step 1: Verify conftest config gets default min_soc_pct**

The `VALID_CONFIG_YAML` in conftest doesn't include `min_soc_pct`, so it will use the default of 10. This is correct — tests should exercise the default behavior. No change needed unless tests from Task 2 revealed otherwise.

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 2: Commit (if any changes were needed)**

```bash
git add tests/conftest.py
git commit -m "test: update conftest for min_soc_pct default"
```

Skip this commit if no conftest changes were needed.
