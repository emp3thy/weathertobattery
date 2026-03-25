# Weather-to-Battery Charge Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a system that sets Growatt battery overnight charge level based on weather forecasts and historical usage data, minimizing unnecessary charging costs.

**Architecture:** Five modules (weather provider, Growatt client, charge calculator, SQLite data store, FastAPI dashboard) tied together by an orchestrator. Two Claude Code skills provide the user interface. The system runs nightly at 10PM.

**Tech Stack:** Python 3.12, growattServer library, Open-Meteo API, SQLite, FastAPI, Chart.js, Jinja2 templates.

**Spec:** `docs/superpowers/specs/2026-03-25-weather-battery-charge-optimizer-design.md`

---

## File Structure

```
weatherToBattery/
├── src/
│   ├── __init__.py
│   ├── config.py                    # Config loading, validation, dataclass
│   ├── weather/
│   │   ├── __init__.py
│   │   ├── interface.py             # WeatherForecast dataclass, WeatherProvider ABC
│   │   └── open_meteo.py            # Open-Meteo implementation
│   ├── growatt/
│   │   ├── __init__.py
│   │   └── client.py                # Login, read data, set charge SOC
│   ├── calculator/
│   │   ├── __init__.py
│   │   ├── profiles.py              # Solar productivity profile builder
│   │   ├── engine.py                # Core charge calculation
│   │   └── feedback.py              # Bidirectional feedback loop
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.py                # Table creation, migrations
│   │   └── queries.py               # All DB read/write operations
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI app, routes
│   │   ├── templates/
│   │   │   ├── base.html            # Shared layout
│   │   │   ├── overview.html        # Tonight's decision
│   │   │   ├── history.html         # Past decisions table/chart
│   │   │   ├── accuracy.html        # Forecast vs actual
│   │   │   ├── savings.html         # Cost savings
│   │   │   └── solar_profile.html   # Hourly productivity curves
│   │   └── static/
│   │       └── style.css            # Dashboard styles
│   └── orchestrator.py              # Main entry point, ties everything together
├── data/                            # Created at runtime
├── config.yaml                      # User configuration
├── config.example.yaml              # Template config with comments
├── last_updated.md                  # Rewritten each run
├── skills/
│   ├── charge-battery.md            # Claude Code skill
│   └── battery-dashboard.md         # Claude Code skill
├── requirements.txt                 # Python dependencies
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures
│   ├── test_config.py
│   ├── test_weather_interface.py
│   ├── test_open_meteo.py
│   ├── test_growatt_client.py
│   ├── test_db.py
│   ├── test_profiles.py
│   ├── test_calculator.py
│   ├── test_feedback.py
│   ├── test_orchestrator.py
│   └── test_dashboard.py
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

---

### Task 1: Project Setup and Configuration

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `config.example.yaml`
- Create: `config.yaml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
growattServer>=2.0.0
requests>=2.31.0
fastapi>=0.110.0
uvicorn>=0.29.0
jinja2>=3.1.0
pyyaml>=6.0
python-dateutil>=2.9.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install successfully.

- [ ] **Step 3: Create config.example.yaml**

```yaml
# Weather-to-Battery Charge Optimizer Configuration

location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"

growatt:
  username: "your_username"
  password: "your_password"
  plant_id: "your_plant_id"
  device_sn: "your_device_sn"
  server_url: "https://server.growatt.com/"

battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  charge_floor_pct: 30

weather:
  provider: "open_meteo"

rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"

pool_heater:
  season_start: "05-15"  # MM-DD
  season_end: "09-30"
  temperature_threshold_c: 18
  power_kw: 6

winter_override:
  start: "10-25"  # MM-DD
  end: "02-28"

feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5

bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100

dashboard:
  port: 8099

# Set to a number (0-100) to force a specific charge level on next run.
# Cleared automatically after use.
manual_override: null
```

- [ ] **Step 4: Create config.yaml with real credentials**

Copy `config.example.yaml` to `config.yaml` and fill in:
- `growatt.username`: `"Stevens BR1"`
- `growatt.password`: `"Growattsucks01!"`
- `growatt.plant_id`: `"1368210"`
- `growatt.device_sn`: `"WPDACDB05J"`

Add `config.yaml` to `.gitignore`.

- [ ] **Step 5: Create .gitignore**

```
config.yaml
data/
__pycache__/
*.pyc
.pytest_cache/
last_updated.md
*.egg-info/
.venv/
```

- [ ] **Step 6: Write failing test for config loading**

```python
# tests/test_config.py
import pytest
from pathlib import Path

def test_load_config_returns_dataclass(tmp_path):
    """Config loader returns a typed Config object from a YAML file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test_user"
  password: "test_pass"
  plant_id: "123"
  device_sn: "ABC123"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  charge_floor_pct: 30
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
pool_heater:
  season_start: "05-15"
  season_end: "09-30"
  temperature_threshold_c: 18
  power_kw: 6
winter_override:
  start: "10-25"
  end: "02-28"
feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5
bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.location.latitude == 51.4067
    assert cfg.growatt.username == "test_user"
    assert cfg.battery.usable_capacity_kwh == pytest.approx(11.97)
    assert cfg.manual_override is None


def test_config_validation_rejects_bad_floor(tmp_path):
    """Config rejects charge_floor_pct outside 0-100."""
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
  charge_floor_pct: 150
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
pool_heater:
  season_start: "05-15"
  season_end: "09-30"
  temperature_threshold_c: 18
  power_kw: 6
winter_override:
  start: "10-25"
  end: "02-28"
feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5
bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config, ConfigValidationError
    with pytest.raises(ConfigValidationError):
        load_config(config_file)
```

- [ ] **Step 7: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 8: Implement config module**

Create `src/__init__.py` (empty), `tests/__init__.py` (empty), and `src/config.py`:

```python
# src/config.py
from dataclasses import dataclass
from pathlib import Path
import yaml


class ConfigValidationError(Exception):
    pass


@dataclass
class LocationConfig:
    latitude: float
    longitude: float
    timezone: str


@dataclass
class GrowattConfig:
    username: str
    password: str
    plant_id: str
    device_sn: str
    server_url: str


@dataclass
class BatteryConfig:
    total_capacity_kwh: float
    usable_fraction: float
    charge_floor_pct: int

    @property
    def usable_capacity_kwh(self) -> float:
        return self.total_capacity_kwh * self.usable_fraction


@dataclass
class WeatherConfig:
    provider: str


@dataclass
class RatesConfig:
    cheap_pence_per_kwh: float
    expensive_pence_per_kwh: float
    export_pence_per_kwh: float
    cheap_start: str
    cheap_end: str


@dataclass
class PoolHeaterConfig:
    season_start: str
    season_end: str
    temperature_threshold_c: float
    power_kw: float


@dataclass
class WinterOverrideConfig:
    start: str
    end: str


@dataclass
class FeedbackConfig:
    max_per_night_pct: int
    max_cumulative_pct: int
    decay_per_day_pct: int


@dataclass
class BootstrapConfig:
    spring_autumn_pct: int
    sunny_summer_pct: int
    winter_pct: int


@dataclass
class DashboardConfig:
    port: int


@dataclass
class Config:
    location: LocationConfig
    growatt: GrowattConfig
    battery: BatteryConfig
    weather: WeatherConfig
    rates: RatesConfig
    pool_heater: PoolHeaterConfig
    winter_override: WinterOverrideConfig
    feedback: FeedbackConfig
    bootstrap: BootstrapConfig
    dashboard: DashboardConfig
    manual_override: int | None


def _validate(cfg: Config) -> None:
    if not (0 <= cfg.battery.charge_floor_pct <= 100):
        raise ConfigValidationError(
            f"charge_floor_pct must be 0-100, got {cfg.battery.charge_floor_pct}"
        )
    if cfg.battery.total_capacity_kwh <= 0:
        raise ConfigValidationError("total_capacity_kwh must be positive")
    if not (0 < cfg.battery.usable_fraction <= 1):
        raise ConfigValidationError("usable_fraction must be between 0 and 1")
    if cfg.manual_override is not None and not (0 <= cfg.manual_override <= 100):
        raise ConfigValidationError("manual_override must be 0-100 or null")


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    cfg = Config(
        location=LocationConfig(**raw["location"]),
        growatt=GrowattConfig(**raw["growatt"]),
        battery=BatteryConfig(**raw["battery"]),
        weather=WeatherConfig(**raw["weather"]),
        rates=RatesConfig(**raw["rates"]),
        pool_heater=PoolHeaterConfig(**raw["pool_heater"]),
        winter_override=WinterOverrideConfig(**raw["winter_override"]),
        feedback=FeedbackConfig(**raw["feedback"]),
        bootstrap=BootstrapConfig(**raw["bootstrap"]),
        dashboard=DashboardConfig(**raw["dashboard"]),
        manual_override=raw.get("manual_override"),
    )
    _validate(cfg)
    return cfg
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 10: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
import pytest
from pathlib import Path

VALID_CONFIG_YAML = """
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test_user"
  password: "test_pass"
  plant_id: "123"
  device_sn: "ABC123"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  charge_floor_pct: 30
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
pool_heater:
  season_start: "05-15"
  season_end: "09-30"
  temperature_threshold_c: 18
  power_kw: 6
winter_override:
  start: "10-25"
  end: "02-28"
feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5
bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100
dashboard:
  port: 8099
manual_override: null
"""

@pytest.fixture
def config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML)
    from src.config import load_config
    return load_config(config_file)
```

- [ ] **Step 11: Commit**

```bash
git add requirements.txt .gitignore config.example.yaml src/__init__.py src/config.py tests/__init__.py tests/conftest.py tests/test_config.py
git commit -m "feat: project setup with config loading and validation"
```

---

### Task 2: Database Schema and Queries

**Files:**
- Create: `src/db/__init__.py`
- Create: `src/db/schema.py`
- Create: `src/db/queries.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for database**

```python
# tests/test_db.py
import pytest
from datetime import date
from pathlib import Path


def test_init_db_creates_tables(tmp_path):
    """init_db creates all required tables."""
    from src.db.schema import init_db
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "actuals" in tables
    assert "adjustments" in tables
    assert "decisions" in tables
    conn.close()


def test_upsert_decision(tmp_path):
    """Inserting a decision for the same date overwrites the previous one."""
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, get_decision
    conn = init_db(tmp_path / "test.db")
    upsert_decision(conn, date(2026, 3, 25), "sunny", "{}", 60, 55, 5,
                    "feedback +5", 10, 3, "open_meteo")
    upsert_decision(conn, date(2026, 3, 25), "cloudy", "{}", 75, 70, 5,
                    "revised", 10, 3, "open_meteo")
    row = get_decision(conn, date(2026, 3, 25))
    assert row["charge_level_set"] == 75
    assert row["forecast_summary"] == "cloudy"
    conn.close()


def test_insert_and_get_actuals(tmp_path):
    """Actuals can be inserted and retrieved by date."""
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals
    conn = init_db(tmp_path / "test.db")
    insert_actuals(conn, date(2026, 3, 25), 20.5, 25.0, 5.0, 2.0,
                   "10:00", 15, 95)
    row = get_actuals(conn, date(2026, 3, 25))
    assert row["total_solar_generation_kwh"] == 20.5
    assert row["grid_import_kwh"] == 5.0
    conn.close()


def test_insert_adjustment(tmp_path):
    """Adjustments are logged correctly."""
    from src.db.schema import init_db
    from src.db.queries import insert_adjustment, get_recent_adjustments
    conn = init_db(tmp_path / "test.db")
    insert_adjustment(conn, date(2026, 3, 25), "up", 10, "grid_draw",
                      "cloudy", "cloudy", 3.5, 0.0)
    rows = get_recent_adjustments(conn, days=7)
    assert len(rows) == 1
    assert rows[0]["direction"] == "up"
    conn.close()


def test_get_historical_daily_data(tmp_path):
    """Can retrieve actuals for a date range."""
    from src.db.schema import init_db
    from src.db.queries import insert_actuals, get_actuals_range
    conn = init_db(tmp_path / "test.db")
    for day in range(1, 8):
        insert_actuals(conn, date(2026, 3, day), 15.0 + day, 25.0, 5.0,
                       1.0, "10:00", 20, 95)
    rows = get_actuals_range(conn, date(2026, 3, 3), date(2026, 3, 6))
    assert len(rows) == 4
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db'`

- [ ] **Step 3: Implement schema.py**

```python
# src/db/schema.py
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    date TEXT PRIMARY KEY,
    forecast_summary TEXT NOT NULL,
    forecast_detail TEXT NOT NULL,
    charge_level_set INTEGER NOT NULL,
    base_charge_level INTEGER NOT NULL,
    feedback_adjustment INTEGER NOT NULL DEFAULT 0,
    adjustment_reason TEXT,
    current_soc_at_decision INTEGER,
    month INTEGER NOT NULL,
    weather_provider_used TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actuals (
    date TEXT PRIMARY KEY,
    total_solar_generation_kwh REAL NOT NULL,
    total_consumption_kwh REAL NOT NULL,
    grid_import_kwh REAL NOT NULL,
    grid_export_kwh REAL NOT NULL,
    peak_solar_hour TEXT,
    battery_min_soc INTEGER,
    battery_max_soc INTEGER
);

CREATE TABLE IF NOT EXISTS adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('up', 'down')),
    amount INTEGER NOT NULL,
    trigger TEXT NOT NULL CHECK(trigger IN ('grid_draw', 'surplus_export')),
    previous_day_weather TEXT,
    tomorrow_forecast TEXT,
    grid_draw_kwh REAL,
    surplus_export_kwh REAL
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
```

- [ ] **Step 4: Implement queries.py**

```python
# src/db/queries.py
import sqlite3
from datetime import date, timedelta


def upsert_decision(conn: sqlite3.Connection, dt: date, forecast_summary: str,
                    forecast_detail: str, charge_level_set: int,
                    base_charge_level: int, feedback_adjustment: int,
                    adjustment_reason: str | None, current_soc: int | None,
                    month: int, weather_provider: str) -> None:
    conn.execute("""
        INSERT INTO decisions (date, forecast_summary, forecast_detail,
            charge_level_set, base_charge_level, feedback_adjustment,
            adjustment_reason, current_soc_at_decision, month,
            weather_provider_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            forecast_summary=excluded.forecast_summary,
            forecast_detail=excluded.forecast_detail,
            charge_level_set=excluded.charge_level_set,
            base_charge_level=excluded.base_charge_level,
            feedback_adjustment=excluded.feedback_adjustment,
            adjustment_reason=excluded.adjustment_reason,
            current_soc_at_decision=excluded.current_soc_at_decision,
            month=excluded.month,
            weather_provider_used=excluded.weather_provider_used
    """, (str(dt), forecast_summary, forecast_detail, charge_level_set,
          base_charge_level, feedback_adjustment, adjustment_reason,
          current_soc, month, weather_provider))
    conn.commit()


def get_decision(conn: sqlite3.Connection, dt: date) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM decisions WHERE date = ?", (str(dt),))
    return cursor.fetchone()


def insert_actuals(conn: sqlite3.Connection, dt: date,
                   solar_gen: float, consumption: float,
                   grid_import: float, grid_export: float,
                   peak_solar_hour: str | None, min_soc: int | None,
                   max_soc: int | None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO actuals (date, total_solar_generation_kwh,
            total_consumption_kwh, grid_import_kwh, grid_export_kwh,
            peak_solar_hour, battery_min_soc, battery_max_soc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(dt), solar_gen, consumption, grid_import, grid_export,
          peak_solar_hour, min_soc, max_soc))
    conn.commit()


def get_actuals(conn: sqlite3.Connection, dt: date) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM actuals WHERE date = ?", (str(dt),))
    return cursor.fetchone()


def get_actuals_range(conn: sqlite3.Connection, start: date,
                      end: date) -> list[sqlite3.Row]:
    cursor = conn.execute(
        "SELECT * FROM actuals WHERE date >= ? AND date <= ? ORDER BY date",
        (str(start), str(end)))
    return cursor.fetchall()


def insert_adjustment(conn: sqlite3.Connection, dt: date, direction: str,
                      amount: int, trigger: str, prev_weather: str | None,
                      tomorrow_forecast: str | None, grid_draw: float,
                      surplus_export: float) -> None:
    conn.execute("""
        INSERT INTO adjustments (date, direction, amount, trigger,
            previous_day_weather, tomorrow_forecast, grid_draw_kwh,
            surplus_export_kwh)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(dt), direction, amount, trigger, prev_weather,
          tomorrow_forecast, grid_draw, surplus_export))
    conn.commit()


def get_recent_adjustments(conn: sqlite3.Connection,
                           days: int = 7) -> list[sqlite3.Row]:
    cutoff = str(date.today() - timedelta(days=days))
    cursor = conn.execute(
        "SELECT * FROM adjustments WHERE date >= ? ORDER BY date DESC",
        (cutoff,))
    return cursor.fetchall()


def get_all_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM decisions ORDER BY date DESC")
    return cursor.fetchall()


def get_all_actuals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM actuals ORDER BY date DESC")
    return cursor.fetchall()
```

- [ ] **Step 5: Create `src/db/__init__.py`** (empty file)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add src/db/ tests/test_db.py
git commit -m "feat: SQLite database schema and query layer"
```

---

### Task 3: Weather Provider Interface and Open-Meteo Implementation

**Files:**
- Create: `src/weather/__init__.py`
- Create: `src/weather/interface.py`
- Create: `src/weather/open_meteo.py`
- Create: `tests/test_weather_interface.py`
- Create: `tests/test_open_meteo.py`

- [ ] **Step 1: Write failing tests for weather interface and bucketing**

```python
# tests/test_weather_interface.py
from datetime import time
from src.weather.interface import HourlyForecast, DayForecast, bucket_condition


def test_bucket_sunny():
    """Low cloud cover and no rain = sunny."""
    hours = [
        HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                        precipitation_probability_pct=5, temperature_c=20)
        for h in range(7, 18)
    ]
    assert bucket_condition(hours) == "sunny"


def test_bucket_cloudy():
    """Medium cloud cover = cloudy."""
    hours = [
        HourlyForecast(hour=h, cloud_cover_pct=55, solar_radiation_wm2=200,
                        precipitation_probability_pct=10, temperature_c=15)
        for h in range(7, 18)
    ]
    assert bucket_condition(hours) == "cloudy"


def test_bucket_rainy():
    """High precipitation probability for >50% of hours = rainy."""
    hours = []
    for h in range(7, 18):
        precip = 70 if h < 13 else 10  # 6 of 11 hours rainy (>50%)
        hours.append(
            HourlyForecast(hour=h, cloud_cover_pct=80,
                            solar_radiation_wm2=50,
                            precipitation_probability_pct=precip,
                            temperature_c=12)
        )
    assert bucket_condition(hours) == "rainy"


def test_bucket_heavy_cloud_no_rain_is_cloudy():
    """>70% cloud but no rain is cloudy, not rainy."""
    hours = [
        HourlyForecast(hour=h, cloud_cover_pct=85, solar_radiation_wm2=100,
                        precipitation_probability_pct=15, temperature_c=14)
        for h in range(7, 18)
    ]
    assert bucket_condition(hours) == "cloudy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_weather_interface.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement weather interface**

```python
# src/weather/interface.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, time


@dataclass
class HourlyForecast:
    hour: int
    cloud_cover_pct: float
    solar_radiation_wm2: float
    precipitation_probability_pct: float
    temperature_c: float


@dataclass
class DayForecast:
    date: date
    sunrise: time
    sunset: time
    hourly: list[HourlyForecast]  # solar hours only
    condition: str  # sunny / cloudy / rainy
    max_temperature_c: float


def bucket_condition(solar_hours: list[HourlyForecast]) -> str:
    if not solar_hours:
        return "cloudy"

    avg_cloud = sum(h.cloud_cover_pct for h in solar_hours) / len(solar_hours)
    rainy_hours = sum(
        1 for h in solar_hours if h.precipitation_probability_pct > 50
    )
    rainy_fraction = rainy_hours / len(solar_hours)

    if rainy_fraction >= 0.5:
        return "rainy"
    if avg_cloud < 30:
        return "sunny"
    return "cloudy"


class WeatherProvider(ABC):
    @abstractmethod
    def get_forecast(self, lat: float, lon: float, target_date: date,
                     timezone: str) -> DayForecast:
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_weather_interface.py -v`
Expected: 4 passed

- [ ] **Step 5: Write failing test for Open-Meteo provider**

```python
# tests/test_open_meteo.py
import json
import pytest
from datetime import date, time
from unittest.mock import patch, MagicMock


MOCK_RESPONSE = {
    "hourly": {
        "time": [f"2026-03-26T{h:02d}:00" for h in range(24)],
        "cloud_cover": [90]*6 + [30, 25, 20, 15, 20, 25, 30, 35, 40, 50, 60, 70] + [90]*6,
        "shortwave_radiation": [0]*6 + [50, 200, 400, 500, 450, 400, 350, 300, 200, 100, 30, 0] + [0]*6,
        "precipitation_probability": [10]*24,
        "temperature_2m": [8]*6 + [10, 12, 14, 16, 17, 18, 18, 17, 16, 14, 12, 10] + [8]*6,
    },
    "daily": {
        "sunrise": ["2026-03-26T06:05"],
        "sunset": ["2026-03-26T18:25"],
    }
}


def test_open_meteo_returns_day_forecast():
    """Open-Meteo provider returns a well-formed DayForecast."""
    from src.weather.open_meteo import OpenMeteoProvider

    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("src.weather.open_meteo.requests.get", return_value=mock_resp):
        provider = OpenMeteoProvider()
        forecast = provider.get_forecast(51.4067, 0.0481,
                                         date(2026, 3, 26), "Europe/London")

    assert forecast.date == date(2026, 3, 26)
    assert forecast.sunrise == time(6, 5)
    assert forecast.sunset == time(18, 25)
    assert len(forecast.hourly) > 0
    assert all(6 <= h.hour <= 18 for h in forecast.hourly)
    assert forecast.condition in ("sunny", "cloudy", "rainy")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_open_meteo.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 7: Implement Open-Meteo provider**

```python
# src/weather/open_meteo.py
import requests
from datetime import date, time, datetime
from .interface import WeatherProvider, DayForecast, HourlyForecast, bucket_condition

API_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoProvider(WeatherProvider):
    def get_forecast(self, lat: float, lon: float, target_date: date,
                     timezone: str) -> DayForecast:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "shortwave_radiation,cloud_cover,precipitation_probability,temperature_2m",
            "daily": "sunrise,sunset",
            "timezone": timezone,
            "start_date": str(target_date),
            "end_date": str(target_date),
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        sunrise_str = data["daily"]["sunrise"][0]
        sunset_str = data["daily"]["sunset"][0]
        sunrise = datetime.fromisoformat(sunrise_str).time()
        sunset = datetime.fromisoformat(sunset_str).time()

        hourly_data = data["hourly"]
        solar_hours = []
        max_temp = -999.0

        for i, time_str in enumerate(hourly_data["time"]):
            hour = datetime.fromisoformat(time_str).hour
            temp = hourly_data["temperature_2m"][i]
            if temp > max_temp:
                max_temp = temp
            if hour < sunrise.hour or hour > sunset.hour:
                continue
            solar_hours.append(HourlyForecast(
                hour=hour,
                cloud_cover_pct=hourly_data["cloud_cover"][i],
                solar_radiation_wm2=hourly_data["shortwave_radiation"][i],
                precipitation_probability_pct=hourly_data["precipitation_probability"][i],
                temperature_c=temp,
            ))

        condition = bucket_condition(solar_hours)

        return DayForecast(
            date=target_date,
            sunrise=sunrise,
            sunset=sunset,
            hourly=solar_hours,
            condition=condition,
            max_temperature_c=max_temp,
        )
```

- [ ] **Step 8: Create `src/weather/__init__.py`** (empty file)

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_weather_interface.py tests/test_open_meteo.py -v`
Expected: 5 passed

- [ ] **Step 10: Commit**

```bash
git add src/weather/ tests/test_weather_interface.py tests/test_open_meteo.py
git commit -m "feat: weather provider interface with Open-Meteo implementation"
```

---

### Task 4: Growatt Client

**Files:**
- Create: `src/growatt/__init__.py`
- Create: `src/growatt/client.py`
- Create: `tests/test_growatt_client.py`

- [ ] **Step 1: Write failing tests for Growatt client**

```python
# tests/test_growatt_client.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import date


def test_login_sets_session(config):
    """Successful login returns a logged-in client."""
    from src.growatt.client import GrowattClient

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}

    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()

    assert client.logged_in
    mock_api.session.headers.update.assert_called_once()


def test_get_daily_data(config):
    """get_daily_data returns parsed dashboard data."""
    from src.growatt.client import GrowattClient

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_api.dashboard_data.return_value = {
        "chartData": {
            "ppv": ["10.5", "20.3"],
            "sysOut": ["5.0", "3.0"],
            "pacToUser": ["2.0", "1.5"],
            "userLoad": ["1.0", "0.5"],
        },
        "photovoltaic": "30.8kWh",
        "elocalLoad": "50.0kWh",
        "etouser": "8.0kWh",
    }

    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        data = client.get_daily_data(date(2026, 3, 1))

    assert data["total_solar_kwh"] == pytest.approx(30.8)


def test_set_charge_soc(config):
    """set_charge_soc posts correct params to tcpSet.do."""
    from src.growatt.client import GrowattClient

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"msg": "inv_set_success", "success": True}
    mock_api.session.post.return_value = mock_resp

    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        result = client.set_charge_soc(75)

    assert result is True
    call_args = mock_api.session.post.call_args
    posted_data = call_args[1].get("data") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["data"]
    assert posted_data["param2"] == "75"


def test_get_current_soc(config):
    """get_current_soc returns battery SOC from device list."""
    from src.growatt.client import GrowattClient

    mock_api = MagicMock()
    mock_api.login.return_value = {"success": True, "data": [{"plantId": "123"}]}
    mock_api.device_list.return_value = [
        {"deviceSn": "ABC123", "capacity": "45%"}
    ]

    with patch("src.growatt.client.growattServer.GrowattApi", return_value=mock_api):
        client = GrowattClient(config.growatt)
        client.login()
        soc = client.get_current_soc()

    assert soc == 45
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_growatt_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Growatt client**

```python
# src/growatt/client.py
import growattServer
import logging
import time as time_module
from datetime import date
from ..config import GrowattConfig

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class GrowattError(Exception):
    pass


class GrowattClient:
    def __init__(self, config: GrowattConfig):
        self.config = config
        self._api = growattServer.GrowattApi()
        self._api.session.headers.update({"User-Agent": USER_AGENT})
        self._api.server_url = config.server_url
        self.logged_in = False

    def login(self) -> None:
        result = self._api.login(self.config.username, self.config.password)
        if not result.get("success"):
            raise GrowattError(f"Login failed: {result.get('error', 'unknown')}")
        self.logged_in = True
        logger.info("Growatt login successful")

    def _retry(self, func, retries=3, backoff=(5, 15, 45)):
        for attempt in range(retries):
            try:
                return func()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                logger.warning(f"Attempt {attempt+1} failed: {e}. Retrying in {wait}s")
                time_module.sleep(wait)

    def get_daily_data(self, month_date: date) -> dict:
        raw = self._api.dashboard_data(
            self.config.plant_id,
            growattServer.Timespan.day,
            month_date
        )
        total_solar = float(raw.get("photovoltaic", "0kWh").replace("kWh", ""))
        total_load = float(raw.get("elocalLoad", "0kWh").replace("kWh", ""))
        total_grid_import = float(raw.get("etouser", "0kWh").replace("kWh", ""))
        return {
            "total_solar_kwh": total_solar,
            "total_load_kwh": total_load,
            "total_grid_import_kwh": total_grid_import,
            "chart_data": raw.get("chartData", {}),
        }

    def get_hourly_data(self, target_date: date) -> dict:
        raw = self._api.dashboard_data(
            self.config.plant_id,
            growattServer.Timespan.hour,
            target_date
        )
        return raw.get("chartData", {})

    def get_current_soc(self) -> int:
        devices = self._api.device_list(self.config.plant_id)
        for dev in devices:
            if dev.get("deviceSn") == self.config.device_sn:
                cap_str = dev.get("capacity", "0%").replace("%", "")
                return int(cap_str)
        raise GrowattError(f"Device {self.config.device_sn} not found")

    def set_charge_soc(self, soc_pct: int) -> bool:
        soc_pct = max(0, min(100, soc_pct))

        def _do_set():
            resp = self._api.session.post(
                f"{self.config.server_url}tcpSet.do",
                data={
                    "action": "spaSet",
                    "serialNum": self.config.device_sn,
                    "type": "spa_ac_charge_time_period",
                    "param1": "100",
                    "param2": str(soc_pct),
                    "param3": "23",
                    "param4": "30",
                    "param5": "23",
                    "param6": "59",
                    "param7": "1",
                    "param8": "00",
                    "param9": "00",
                    "param10": "05",
                    "param11": "30",
                    "param12": "1",
                    "param13": "00",
                    "param14": "00",
                    "param15": "00",
                    "param16": "00",
                    "param17": "0",
                }
            )
            result = resp.json()
            if not result.get("success"):
                raise GrowattError(f"Set charge failed: {result.get('msg')}")
            return True

        return self._retry(_do_set)
```

- [ ] **Step 4: Create `src/growatt/__init__.py`** (empty file)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_growatt_client.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/growatt/ tests/test_growatt_client.py
git commit -m "feat: Growatt client with login, data reads, and charge SOC write"
```

---

### Task 5: Solar Productivity Profile Builder

**Files:**
- Create: `src/calculator/__init__.py`
- Create: `src/calculator/profiles.py`
- Create: `tests/test_profiles.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_profiles.py
from src.calculator.profiles import build_solar_profile, weight_forecast


def test_build_solar_profile_from_hourly_data():
    """Profile assigns higher weight to hours with more generation."""
    # Simulated hourly generation data: morning-heavy
    daily_hourly_data = [
        # day 1
        {"07:00": 0.5, "08:00": 1.5, "09:00": 3.0, "10:00": 4.0,
         "11:00": 3.5, "12:00": 2.5, "13:00": 2.0, "14:00": 1.5,
         "15:00": 1.0, "16:00": 0.5},
        # day 2 (similar pattern)
        {"07:00": 0.4, "08:00": 1.4, "09:00": 2.8, "10:00": 3.8,
         "11:00": 3.3, "12:00": 2.3, "13:00": 1.8, "14:00": 1.3,
         "15:00": 0.8, "16:00": 0.3},
    ]
    profile = build_solar_profile(daily_hourly_data)
    # 10:00 should have higher weight than 16:00
    assert profile[10] > profile[16]
    # Weights should sum to roughly 1.0
    assert abs(sum(profile.values()) - 1.0) < 0.01


def test_weight_forecast_amplifies_peak_hours():
    """Weighting forecast by profile makes peak-hour weather more important."""
    from src.weather.interface import HourlyForecast

    profile = {8: 0.1, 9: 0.2, 10: 0.3, 11: 0.2, 12: 0.1, 13: 0.1}
    hours = [
        HourlyForecast(hour=h, cloud_cover_pct=50, solar_radiation_wm2=300,
                        precipitation_probability_pct=10, temperature_c=15)
        for h in [8, 9, 10, 11, 12, 13]
    ]
    weighted = weight_forecast(hours, profile)
    # Hour 10 has weight 0.3, so its effective radiation should be highest
    assert weighted[10] > weighted[8]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: FAIL

- [ ] **Step 3: Implement profiles module**

```python
# src/calculator/profiles.py
from src.weather.interface import HourlyForecast


def build_solar_profile(daily_hourly_data: list[dict[str, float]]) -> dict[int, float]:
    """Build an hourly weighting profile from historical generation data.

    Args:
        daily_hourly_data: List of dicts mapping "HH:MM" -> generation_kw for each day.

    Returns:
        Dict mapping hour (int) -> normalised weight (0-1, summing to ~1.0).
    """
    totals: dict[int, float] = {}
    counts: dict[int, int] = {}

    for day_data in daily_hourly_data:
        for time_str, gen in day_data.items():
            hour = int(time_str.split(":")[0])
            totals[hour] = totals.get(hour, 0.0) + float(gen)
            counts[hour] = counts.get(hour, 0) + 1

    averages = {h: totals[h] / counts[h] for h in totals if counts[h] > 0}

    total = sum(averages.values())
    if total == 0:
        # No generation data — equal weights
        n = len(averages) or 1
        return {h: 1.0 / n for h in averages}

    return {h: avg / total for h, avg in averages.items()}


def weight_forecast(solar_hours: list[HourlyForecast],
                    profile: dict[int, float]) -> dict[int, float]:
    """Weight forecast solar radiation by the productivity profile.

    Returns:
        Dict mapping hour -> weighted effective radiation.
    """
    result = {}
    for h in solar_hours:
        weight = profile.get(h.hour, 0.0)
        result[h.hour] = h.solar_radiation_wm2 * weight
    return result
```

- [ ] **Step 4: Create `src/calculator/__init__.py`** (empty file)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/calculator/ tests/test_profiles.py
git commit -m "feat: solar productivity profile builder with forecast weighting"
```

---

### Task 6: Charge Calculator Engine

**Files:**
- Create: `src/calculator/engine.py`
- Create: `tests/test_calculator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_calculator.py
import pytest
from datetime import date


def test_winter_override_returns_100(config):
    """Dates within the winter override period always return 100%."""
    from src.calculator.engine import calculate_charge
    from src.weather.interface import DayForecast, HourlyForecast
    from datetime import time

    forecast = DayForecast(
        date=date(2026, 12, 15), sunrise=time(8, 0), sunset=time(16, 0),
        hourly=[], condition="sunny", max_temperature_c=5
    )
    result = calculate_charge(
        config=config, forecast=forecast, current_soc=10,
        historical_consumption=[], historical_generation=[],
        feedback_adjustment=0
    )
    assert result.charge_level == 100
    assert "winter" in result.reason.lower()


def test_manual_override(tmp_path):
    """Manual override in config takes precedence."""
    from src.calculator.engine import calculate_charge
    from src.weather.interface import DayForecast, HourlyForecast
    from src.config import load_config
    from datetime import time
    from tests.conftest import VALID_CONFIG_YAML

    config_file = tmp_path / "config.yaml"
    config_file.write_text(VALID_CONFIG_YAML.replace(
        "manual_override: null", "manual_override: 85"))
    config = load_config(config_file)

    forecast = DayForecast(
        date=date(2026, 6, 15), sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[], condition="sunny", max_temperature_c=25
    )
    result = calculate_charge(
        config=config, forecast=forecast, current_soc=20,
        historical_consumption=[], historical_generation=[],
        feedback_adjustment=0
    )
    assert result.charge_level == 85
    assert "manual" in result.reason.lower()


def test_bootstrap_sunny_summer(config):
    """With no historical data, sunny summer day uses bootstrap value."""
    from src.calculator.engine import calculate_charge
    from src.weather.interface import DayForecast, HourlyForecast
    from datetime import time

    forecast = DayForecast(
        date=date(2026, 7, 15), sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=15, solar_radiation_wm2=600,
                            precipitation_probability_pct=5, temperature_c=25)
            for h in range(6, 21)
        ],
        condition="sunny", max_temperature_c=25
    )
    result = calculate_charge(
        config=config, forecast=forecast, current_soc=10,
        historical_consumption=[], historical_generation=[],
        feedback_adjustment=0
    )
    assert result.charge_level == config.bootstrap.sunny_summer_pct


def test_charge_floor_enforced(config):
    """Charge level never goes below the configured floor."""
    from src.calculator.engine import calculate_charge
    from src.weather.interface import DayForecast, HourlyForecast
    from datetime import time

    forecast = DayForecast(
        date=date(2026, 7, 15), sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=10, solar_radiation_wm2=800,
                            precipitation_probability_pct=0, temperature_c=28)
            for h in range(6, 21)
        ],
        condition="sunny", max_temperature_c=28
    )
    # High generation, low consumption, high current SOC -> calc might go below floor
    result = calculate_charge(
        config=config, forecast=forecast, current_soc=50,
        historical_consumption=[15.0, 14.0, 16.0, 15.0, 14.0],
        historical_generation=[38.0, 40.0, 35.0, 42.0, 39.0],
        feedback_adjustment=-10
    )
    assert result.charge_level >= config.battery.charge_floor_pct


def test_feedback_adjustment_applied(config):
    """Positive feedback adjustment increases the charge level."""
    from src.calculator.engine import calculate_charge
    from src.weather.interface import DayForecast, HourlyForecast
    from datetime import time

    forecast = DayForecast(
        date=date(2026, 5, 15), sunrise=time(5, 30), sunset=time(20, 30),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=40, solar_radiation_wm2=350,
                            precipitation_probability_pct=20, temperature_c=18)
            for h in range(6, 21)
        ],
        condition="cloudy", max_temperature_c=18
    )
    result_no_adj = calculate_charge(
        config=config, forecast=forecast, current_soc=20,
        historical_consumption=[25.0]*5,
        historical_generation=[20.0]*5,
        feedback_adjustment=0
    )
    result_with_adj = calculate_charge(
        config=config, forecast=forecast, current_soc=20,
        historical_consumption=[25.0]*5,
        historical_generation=[20.0]*5,
        feedback_adjustment=10
    )
    assert result_with_adj.charge_level == result_no_adj.charge_level + 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement calculator engine**

```python
# src/calculator/engine.py
from dataclasses import dataclass
from datetime import date
from ..config import Config
from ..weather.interface import DayForecast


@dataclass
class ChargeResult:
    charge_level: int
    base_level: int
    feedback_adjustment: int
    reason: str


def _is_winter(target_date: date, config: Config) -> bool:
    month_day = (target_date.month, target_date.day)
    start_parts = config.winter_override.start.split("-")
    end_parts = config.winter_override.end.split("-")
    start = (int(start_parts[0]), int(start_parts[1]))
    end = (int(end_parts[0]), int(end_parts[1]))
    # Winter wraps around year end: Oct 25 -> Feb 28
    if start > end:
        return month_day >= start or month_day <= end
    return start <= month_day <= end


def _is_pool_heater_day(target_date: date, forecast: DayForecast,
                        config: Config) -> bool:
    start_parts = config.pool_heater.season_start.split("-")
    end_parts = config.pool_heater.season_end.split("-")
    start = (int(start_parts[0]), int(start_parts[1]))
    end = (int(end_parts[0]), int(end_parts[1]))
    month_day = (target_date.month, target_date.day)
    in_season = start <= month_day <= end
    warm_enough = forecast.max_temperature_c >= config.pool_heater.temperature_threshold_c
    return in_season and warm_enough


def _bootstrap_level(target_date: date, forecast: DayForecast,
                     config: Config) -> int:
    if _is_winter(target_date, config):
        return config.bootstrap.winter_pct
    if forecast.condition == "sunny" and target_date.month in (5, 6, 7, 8, 9):
        return config.bootstrap.sunny_summer_pct
    return config.bootstrap.spring_autumn_pct


def calculate_charge(
    config: Config,
    forecast: DayForecast,
    current_soc: int,
    historical_consumption: list[float],
    historical_generation: list[float],
    feedback_adjustment: int,
) -> ChargeResult:
    target_date = forecast.date

    # Manual override
    if config.manual_override is not None:
        return ChargeResult(
            charge_level=config.manual_override,
            base_level=config.manual_override,
            feedback_adjustment=0,
            reason="Manual override applied"
        )

    # Winter override
    if _is_winter(target_date, config):
        return ChargeResult(
            charge_level=100, base_level=100, feedback_adjustment=0,
            reason="Winter override: charging to 100%"
        )

    # Bootstrap if insufficient data
    if len(historical_consumption) < 5 or len(historical_generation) < 5:
        level = _bootstrap_level(target_date, forecast, config)
        return ChargeResult(
            charge_level=level, base_level=level, feedback_adjustment=0,
            reason=f"Bootstrap estimate (insufficient historical data): {level}%"
        )

    # Formula-based calculation
    avg_consumption = sum(historical_consumption) / len(historical_consumption)
    avg_generation = sum(historical_generation) / len(historical_generation)

    # Scale generation by weather condition relative to historical
    condition_factor = {"sunny": 1.1, "cloudy": 0.7, "rainy": 0.3}
    expected_gen = avg_generation * condition_factor.get(forecast.condition, 0.7)

    # Account for pool heater
    if _is_pool_heater_day(target_date, forecast, config):
        # Pool heater adds significant load
        pool_hours = 5  # roughly 10AM-3PM
        avg_consumption += config.pool_heater.power_kw * pool_hours * 0.5

    current_soc_kwh = (current_soc / 100) * config.battery.usable_capacity_kwh
    shortfall = avg_consumption - expected_gen - current_soc_kwh

    usable = config.battery.usable_capacity_kwh
    base_level = int(max(0, min(100, (shortfall / usable) * 100)))

    # Apply feedback
    adjusted = base_level + feedback_adjustment
    # Clamp
    charge_level = int(max(config.battery.charge_floor_pct, min(100, adjusted)))

    reason_parts = [
        f"Expected consumption: {avg_consumption:.1f}kWh",
        f"Expected generation: {expected_gen:.1f}kWh",
        f"Current SOC: {current_soc}% ({current_soc_kwh:.1f}kWh)",
        f"Shortfall: {shortfall:.1f}kWh",
        f"Base charge: {base_level}%",
    ]
    if feedback_adjustment != 0:
        reason_parts.append(f"Feedback adjustment: {feedback_adjustment:+d}%")

    return ChargeResult(
        charge_level=charge_level,
        base_level=base_level,
        feedback_adjustment=feedback_adjustment,
        reason=". ".join(reason_parts)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_calculator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/calculator/engine.py tests/test_calculator.py
git commit -m "feat: charge calculator with winter/manual override, bootstrap, and formula"
```

---

### Task 7: Feedback Loop

**Files:**
- Create: `src/calculator/feedback.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feedback.py
import pytest
from datetime import date


def test_undercharged_same_weather_adjusts_up(config):
    """Grid draw during expensive hours + same/worse weather = increase charge."""
    from src.calculator.feedback import compute_feedback_adjustment

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=4.0,
        today_surplus_export_kwh=0.0,
        today_weather="cloudy",
        tomorrow_weather="cloudy",
        previous_cumulative=0,
    )
    assert adj > 0
    assert adj <= config.feedback.max_per_night_pct


def test_overcharged_same_weather_adjusts_down(config):
    """Surplus export + same/better weather = decrease charge."""
    from src.calculator.feedback import compute_feedback_adjustment

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=0.0,
        today_surplus_export_kwh=5.0,
        today_weather="cloudy",
        tomorrow_weather="sunny",
        previous_cumulative=0,
    )
    assert adj < 0
    assert abs(adj) <= config.feedback.max_per_night_pct


def test_cumulative_cap(config):
    """Adjustment is capped at cumulative maximum."""
    from src.calculator.feedback import compute_feedback_adjustment

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=10.0,
        today_surplus_export_kwh=0.0,
        today_weather="rainy",
        tomorrow_weather="rainy",
        previous_cumulative=20,  # already near cap of 25
    )
    assert adj <= 5  # can only add 5 more to reach cap of 25


def test_decay_reduces_cumulative(config):
    """Decay reduces existing adjustment toward zero."""
    from src.calculator.feedback import apply_decay

    decayed = apply_decay(15, config.feedback.decay_per_day_pct)
    assert decayed == 10  # 15 - 5 = 10


def test_no_adjustment_when_weather_improves_after_undercharge(config):
    """If undercharged but tomorrow is better, no upward adjustment."""
    from src.calculator.feedback import compute_feedback_adjustment

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=5.0,
        today_surplus_export_kwh=0.0,
        today_weather="rainy",
        tomorrow_weather="sunny",
        previous_cumulative=0,
    )
    assert adj == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_feedback.py -v`
Expected: FAIL

- [ ] **Step 3: Implement feedback module**

```python
# src/calculator/feedback.py
from ..config import Config

WEATHER_ORDER = {"sunny": 0, "cloudy": 1, "rainy": 2}


def _weather_same_or_worse(today: str, tomorrow: str) -> bool:
    return WEATHER_ORDER.get(tomorrow, 1) >= WEATHER_ORDER.get(today, 1)


def _weather_same_or_better(today: str, tomorrow: str) -> bool:
    return WEATHER_ORDER.get(tomorrow, 1) <= WEATHER_ORDER.get(today, 1)


def apply_decay(cumulative: int, decay_rate: int) -> int:
    if cumulative > 0:
        return max(0, cumulative - decay_rate)
    elif cumulative < 0:
        return min(0, cumulative + decay_rate)
    return 0


def compute_feedback_adjustment(
    config: Config,
    today_grid_import_kwh: float,
    today_surplus_export_kwh: float,
    today_weather: str,
    tomorrow_weather: str,
    previous_cumulative: int,
) -> int:
    usable = config.battery.usable_capacity_kwh
    max_per_night = config.feedback.max_per_night_pct
    max_cumulative = config.feedback.max_cumulative_pct

    adjustment = 0

    # Undercharged: grid import during expensive hours
    if today_grid_import_kwh > 0.5 and _weather_same_or_worse(today_weather, tomorrow_weather):
        raw = int((today_grid_import_kwh / usable) * 100)
        adjustment = min(raw, max_per_night)

    # Overcharged: surplus export while battery was full
    elif today_surplus_export_kwh > 0.5 and _weather_same_or_better(today_weather, tomorrow_weather):
        raw = int((today_surplus_export_kwh / usable) * 100)
        adjustment = -min(raw, max_per_night)

    # Clamp to cumulative cap
    new_cumulative = previous_cumulative + adjustment
    if new_cumulative > max_cumulative:
        adjustment = max_cumulative - previous_cumulative
    elif new_cumulative < -max_cumulative:
        adjustment = -max_cumulative - previous_cumulative

    return adjustment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_feedback.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/calculator/feedback.py tests/test_feedback.py
git commit -m "feat: bidirectional feedback loop with caps and decay"
```

---

### Task 8: Orchestrator

**Files:**
- Create: `src/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_orchestrator.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, time


def test_orchestrator_sets_charge_and_logs(tmp_path, config):
    """Full run: fetches forecast, calculates charge, sets on Growatt, logs to DB."""
    from src.orchestrator import run_nightly
    from src.weather.interface import DayForecast, HourlyForecast
    from src.db.schema import init_db

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    forecast = DayForecast(
        date=date(2026, 7, 15), sunrise=time(5, 0), sunset=time(21, 0),
        hourly=[
            HourlyForecast(hour=h, cloud_cover_pct=20, solar_radiation_wm2=500,
                            precipitation_probability_pct=5, temperature_c=22)
            for h in range(6, 21)
        ],
        condition="sunny", max_temperature_c=22
    )

    mock_weather = MagicMock()
    mock_weather.get_forecast.return_value = forecast

    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 15
    mock_growatt.set_charge_soc.return_value = True

    result = run_nightly(
        config=config,
        conn=conn,
        weather_provider=mock_weather,
        growatt_client=mock_growatt,
        target_date=date(2026, 7, 15),
        project_root=tmp_path,
    )

    assert result["success"] is True
    assert 30 <= result["charge_level"] <= 100
    mock_growatt.set_charge_soc.assert_called_once()

    # Verify decision was logged
    from src.db.queries import get_decision
    decision = get_decision(conn, date(2026, 7, 15))
    assert decision is not None
    assert decision["charge_level_set"] == result["charge_level"]

    # Verify last_updated.md was written
    assert (tmp_path / "last_updated.md").exists()
    conn.close()


def test_orchestrator_winter_skips_weather(tmp_path, config):
    """Winter override doesn't call weather API."""
    from src.orchestrator import run_nightly
    from src.db.schema import init_db

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    mock_weather = MagicMock()
    mock_growatt = MagicMock()
    mock_growatt.get_current_soc.return_value = 10
    mock_growatt.set_charge_soc.return_value = True

    result = run_nightly(
        config=config,
        conn=conn,
        weather_provider=mock_weather,
        growatt_client=mock_growatt,
        target_date=date(2026, 12, 15),
        project_root=tmp_path,
    )

    assert result["charge_level"] == 100
    mock_weather.get_forecast.assert_not_called()
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement orchestrator**

```python
# src/orchestrator.py
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from .config import Config
from .weather.interface import WeatherProvider, DayForecast, HourlyForecast
from .growatt.client import GrowattClient
from .calculator.engine import calculate_charge, _is_winter
from .calculator.feedback import compute_feedback_adjustment, apply_decay
from .db.queries import (
    upsert_decision, get_decision, get_actuals, insert_actuals,
    get_recent_adjustments, insert_adjustment, get_actuals_range
)

logger = logging.getLogger(__name__)


def _get_historical_data(conn, target_date: date,
                         window_weeks: int = 2) -> tuple[list[float], list[float]]:
    start = target_date - timedelta(weeks=window_weeks)
    end = target_date - timedelta(days=1)
    rows = get_actuals_range(conn, start, end)
    consumption = [row["total_consumption_kwh"] for row in rows]
    generation = [row["total_solar_generation_kwh"] for row in rows]
    return consumption, generation


def _get_feedback_state(conn, config: Config, today_weather: str,
                        tomorrow_weather: str) -> int:
    today = date.today()
    actuals = get_actuals(conn, today)
    if actuals is None:
        return 0

    recent = get_recent_adjustments(conn, days=7)
    previous_cumulative = sum(
        r["amount"] if r["direction"] == "up" else -r["amount"]
        for r in recent
    )
    previous_cumulative = apply_decay(previous_cumulative,
                                       config.feedback.decay_per_day_pct)

    adj = compute_feedback_adjustment(
        config=config,
        today_grid_import_kwh=actuals["grid_import_kwh"],
        today_surplus_export_kwh=actuals["grid_export_kwh"],
        today_weather=today_weather,
        tomorrow_weather=tomorrow_weather,
        previous_cumulative=previous_cumulative,
    )

    if adj != 0:
        insert_adjustment(
            conn, today,
            direction="up" if adj > 0 else "down",
            amount=abs(adj),
            trigger="grid_draw" if adj > 0 else "surplus_export",
            prev_weather=today_weather,
            tomorrow_forecast=tomorrow_weather,
            grid_draw=actuals["grid_import_kwh"],
            surplus_export=actuals["grid_export_kwh"],
        )

    return adj


def _write_last_updated(path: Path, result: dict, forecast: DayForecast | None) -> None:
    lines = [
        f"# Battery Charge Update",
        f"",
        f"**Run time:** {result['timestamp']}",
        f"**Date setting for:** {result['target_date']}",
        f"**Charge level set:** {result['charge_level']}%",
        f"",
        f"## Reason",
        f"",
        result["reason"],
        f"",
    ]
    if forecast:
        lines.extend([
            f"## Tomorrow's Forecast",
            f"",
            f"- Condition: {forecast.condition}",
            f"- Sunrise: {forecast.sunrise}",
            f"- Sunset: {forecast.sunset}",
            f"- Max temperature: {forecast.max_temperature_c}C",
            f"- Solar hours: {len(forecast.hourly)}",
            f"",
        ])
    if result.get("feedback_adjustment", 0) != 0:
        lines.extend([
            f"## Feedback Adjustment",
            f"",
            f"- Adjustment: {result['feedback_adjustment']:+d}%",
            f"",
        ])
    if result.get("errors"):
        lines.extend([
            f"## Errors",
            f"",
            *[f"- {e}" for e in result["errors"]],
            f"",
        ])

    (path / "last_updated.md").write_text("\n".join(lines))


def run_nightly(
    config: Config,
    conn,
    weather_provider: WeatherProvider,
    growatt_client: GrowattClient,
    target_date: date,
    project_root: Path,
) -> dict:
    from datetime import datetime
    timestamp = datetime.now().isoformat()
    errors = []
    forecast = None
    feedback_adj = 0

    # Winter override — skip weather entirely
    if _is_winter(target_date, config):
        charge_level = 100
        reason = "Winter override: charging to 100%"
        base_level = 100
    elif config.manual_override is not None:
        charge_level = config.manual_override
        reason = f"Manual override: {charge_level}%"
        base_level = charge_level
    else:
        # Fetch forecast
        try:
            forecast = weather_provider.get_forecast(
                config.location.latitude, config.location.longitude,
                target_date, config.location.timezone
            )
        except Exception as e:
            logger.error(f"Weather API failed: {e}")
            errors.append(f"Weather API failed: {e}")
            charge_level = 90
            reason = "Weather API unavailable — fallback to 90%"
            base_level = 90
            forecast = None

        if forecast:
            # Get today's decision for feedback
            today_decision = get_decision(conn, date.today())
            today_weather = today_decision["forecast_summary"] if today_decision else "cloudy"
            feedback_adj = _get_feedback_state(conn, config, today_weather,
                                                forecast.condition)

            current_soc = growatt_client.get_current_soc()
            consumption, generation = _get_historical_data(conn, target_date)

            calc_result = calculate_charge(
                config=config, forecast=forecast, current_soc=current_soc,
                historical_consumption=consumption,
                historical_generation=generation,
                feedback_adjustment=feedback_adj,
            )
            charge_level = calc_result.charge_level
            base_level = calc_result.base_level
            reason = calc_result.reason

    # Set on Growatt
    try:
        growatt_client.set_charge_soc(charge_level)
    except Exception as e:
        logger.error(f"Failed to set charge: {e}")
        errors.append(f"Failed to set charge: {e}")

    # Log decision
    forecast_detail = json.dumps(
        [{"hour": h.hour, "cloud": h.cloud_cover_pct,
          "radiation": h.solar_radiation_wm2, "precip": h.precipitation_probability_pct}
         for h in forecast.hourly] if forecast else []
    )
    upsert_decision(
        conn, target_date,
        forecast_summary=forecast.condition if forecast else "unknown",
        forecast_detail=forecast_detail,
        charge_level_set=charge_level,
        base_charge_level=base_level,
        feedback_adjustment=feedback_adj,
        adjustment_reason=reason,
        current_soc=growatt_client.get_current_soc() if forecast else None,
        month=target_date.month,
        weather_provider=config.weather.provider,
    )

    result = {
        "success": len(errors) == 0,
        "charge_level": charge_level,
        "base_level": base_level,
        "feedback_adjustment": feedback_adj,
        "reason": reason,
        "target_date": str(target_date),
        "timestamp": timestamp,
        "errors": errors,
    }

    _write_last_updated(project_root, result, forecast)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator ties together forecast, calculator, Growatt, and DB"
```

---

### Task 9: Dashboard

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/app.py`
- Create: `src/dashboard/templates/base.html`
- Create: `src/dashboard/templates/overview.html`
- Create: `src/dashboard/templates/history.html`
- Create: `src/dashboard/templates/accuracy.html`
- Create: `src/dashboard/templates/savings.html`
- Create: `src/dashboard/templates/solar_profile.html`
- Create: `src/dashboard/static/style.css`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_dashboard.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dashboard_client(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, insert_actuals
    from datetime import date

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_decision(conn, date(2026, 3, 25), "sunny", "[]", 60, 55, 5,
                    "test", 10, 3, "open_meteo")
    insert_actuals(conn, date(2026, 3, 24), 20.0, 25.0, 5.0, 2.0,
                   "10:00", 15, 95)
    conn.close()

    from src.dashboard.app import create_app
    app = create_app(db_path)
    return TestClient(app)


def test_overview_page(dashboard_client):
    resp = dashboard_client.get("/")
    assert resp.status_code == 200
    assert "Battery" in resp.text


def test_history_page(dashboard_client):
    resp = dashboard_client.get("/history")
    assert resp.status_code == 200


def test_savings_page(dashboard_client):
    resp = dashboard_client.get("/savings")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: FAIL

- [ ] **Step 3: Implement dashboard app**

Create `src/dashboard/app.py`:

```python
# src/dashboard/app.py
import sqlite3
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Battery Charge Dashboard")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def get_conn():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        conn = get_conn()
        cursor = conn.execute(
            "SELECT * FROM decisions ORDER BY date DESC LIMIT 1")
        decision = cursor.fetchone()
        cursor = conn.execute(
            "SELECT * FROM actuals ORDER BY date DESC LIMIT 1")
        actual = cursor.fetchone()
        conn.close()
        return templates.TemplateResponse("overview.html", {
            "request": request, "decision": decision, "actual": actual
        })

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request):
        conn = get_conn()
        decisions = conn.execute(
            "SELECT d.*, a.total_solar_generation_kwh, a.grid_import_kwh, a.grid_export_kwh "
            "FROM decisions d LEFT JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC LIMIT 90"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("history.html", {
            "request": request, "decisions": decisions
        })

    @app.get("/accuracy", response_class=HTMLResponse)
    def accuracy(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT d.date, d.forecast_summary, d.charge_level_set, "
            "a.total_solar_generation_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC LIMIT 90"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("accuracy.html", {
            "request": request, "rows": rows
        })

    @app.get("/savings", response_class=HTMLResponse)
    def savings(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT d.date, d.charge_level_set, "
            "a.total_solar_generation_kwh, a.total_consumption_kwh, "
            "a.grid_import_kwh, a.grid_export_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("savings.html", {
            "request": request, "rows": rows
        })

    @app.get("/solar-profile", response_class=HTMLResponse)
    def solar_profile(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM actuals ORDER BY date DESC LIMIT 90"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("solar_profile.html", {
            "request": request, "rows": rows
        })

    return app
```

- [ ] **Step 4: Create templates**

Create `src/dashboard/templates/base.html`:
```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{% block title %}Battery Dashboard{% endblock %}</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <nav>
        <a href="/">Overview</a>
        <a href="/history">History</a>
        <a href="/accuracy">Forecast Accuracy</a>
        <a href="/savings">Cost Savings</a>
        <a href="/solar-profile">Solar Profile</a>
    </nav>
    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

Create `src/dashboard/templates/overview.html`:
```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - Overview{% endblock %}
{% block content %}
<h1>Battery Charge Overview</h1>
{% if decision %}
<div class="card">
    <h2>Latest Decision</h2>
    <p><strong>Date:</strong> {{ decision["date"] }}</p>
    <p><strong>Charge Level Set:</strong> {{ decision["charge_level_set"] }}%</p>
    <p><strong>Forecast:</strong> {{ decision["forecast_summary"] }}</p>
    <p><strong>Reason:</strong> {{ decision["adjustment_reason"] }}</p>
</div>
{% else %}
<p>No decisions recorded yet.</p>
{% endif %}
{% if actual %}
<div class="card">
    <h2>Latest Actuals</h2>
    <p><strong>Date:</strong> {{ actual["date"] }}</p>
    <p><strong>Solar Generation:</strong> {{ actual["total_solar_generation_kwh"] }} kWh</p>
    <p><strong>Consumption:</strong> {{ actual["total_consumption_kwh"] }} kWh</p>
    <p><strong>Grid Import:</strong> {{ actual["grid_import_kwh"] }} kWh</p>
    <p><strong>Grid Export:</strong> {{ actual["grid_export_kwh"] }} kWh</p>
</div>
{% endif %}
{% endblock %}
```

Create `src/dashboard/templates/history.html`:
```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - History{% endblock %}
{% block content %}
<h1>Decision History</h1>
<table>
    <thead>
        <tr>
            <th>Date</th><th>Forecast</th><th>Charge Set</th>
            <th>Solar (kWh)</th><th>Grid Import (kWh)</th><th>Grid Export (kWh)</th>
        </tr>
    </thead>
    <tbody>
    {% for row in decisions %}
        <tr>
            <td>{{ row["date"] }}</td>
            <td>{{ row["forecast_summary"] }}</td>
            <td>{{ row["charge_level_set"] }}%</td>
            <td>{{ row["total_solar_generation_kwh"] or "-" }}</td>
            <td>{{ row["grid_import_kwh"] or "-" }}</td>
            <td>{{ row["grid_export_kwh"] or "-" }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endblock %}
```

Create `src/dashboard/templates/accuracy.html`:
```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - Forecast Accuracy{% endblock %}
{% block content %}
<h1>Forecast Accuracy</h1>
<canvas id="accuracyChart"></canvas>
<script>
const data = {{ rows | list | tojson }};
const labels = data.map(r => r[0]);
const actual = data.map(r => r[3]);
new Chart(document.getElementById('accuracyChart'), {
    type: 'bar',
    data: {
        labels: labels,
        datasets: [{
            label: 'Actual Solar (kWh)',
            data: actual,
            backgroundColor: '#f59e0b'
        }]
    }
});
</script>
{% endblock %}
```

Create `src/dashboard/templates/savings.html`:
```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - Cost Savings{% endblock %}
{% block content %}
<h1>Cost Savings</h1>
{% set ns = namespace(total_saved=0, total_grid_cost=0, total_wasted=0) %}
{% for row in rows %}
    {% set charge_avoided = (100 - row["charge_level_set"]) / 100 * 11.97 %}
    {% set ns.total_saved = ns.total_saved + charge_avoided * 7 %}
    {% set ns.total_grid_cost = ns.total_grid_cost + (row["grid_import_kwh"] or 0) * 30 %}
    {% set ns.total_wasted = ns.total_wasted + (row["grid_export_kwh"] or 0) * 7 %}
{% endfor %}
<div class="card">
    <h2>Totals</h2>
    <p><strong>Charging saved:</strong> {{ "%.0f" | format(ns.total_saved) }}p (charge avoided at 7p/kWh)</p>
    <p><strong>Grid import cost:</strong> {{ "%.0f" | format(ns.total_grid_cost) }}p (at 30p/kWh)</p>
    <p><strong>Wasted export:</strong> {{ "%.0f" | format(ns.total_wasted) }}p (paid 7p to store, exported free)</p>
    <p><strong>Net benefit:</strong> {{ "%.0f" | format(ns.total_saved - ns.total_wasted) }}p</p>
</div>
<table>
    <thead>
        <tr><th>Date</th><th>Charge Set</th><th>Solar</th><th>Consumption</th><th>Grid Import</th><th>Grid Export</th></tr>
    </thead>
    <tbody>
    {% for row in rows %}
        <tr>
            <td>{{ row["date"] }}</td>
            <td>{{ row["charge_level_set"] }}%</td>
            <td>{{ row["total_solar_generation_kwh"] }} kWh</td>
            <td>{{ row["total_consumption_kwh"] }} kWh</td>
            <td>{{ row["grid_import_kwh"] }} kWh</td>
            <td>{{ row["grid_export_kwh"] }} kWh</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endblock %}
```

Create `src/dashboard/templates/solar_profile.html`:
```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - Solar Profile{% endblock %}
{% block content %}
<h1>Solar Profile</h1>
<p>Solar productivity profile is built from historical Growatt data. This page will show hourly generation curves once enough data is collected.</p>
<canvas id="profileChart"></canvas>
{% endblock %}
```

Create `src/dashboard/static/style.css`:
```css
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f5f5f5; color: #1a1a1a; }
nav { background: #1a1a1a; padding: 12px 24px; display: flex; gap: 20px; }
nav a { color: #fff; text-decoration: none; font-size: 14px; }
nav a:hover { text-decoration: underline; }
main { max-width: 1000px; margin: 24px auto; padding: 0 20px; }
h1 { margin-top: 0; }
.card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }
th { background: #f0f0f0; font-weight: 600; font-size: 13px; }
td { font-size: 14px; }
canvas { max-width: 100%; margin: 20px 0; }
```

Create `src/dashboard/__init__.py` (empty file).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/ tests/test_dashboard.py
git commit -m "feat: FastAPI dashboard with overview, history, accuracy, savings pages"
```

---

### Task 10: Claude Code Skills

**Files:**
- Create: `skills/charge-battery.md`
- Create: `skills/battery-dashboard.md`

- [ ] **Step 1: Create charge-battery skill**

```markdown
---
name: charge-battery
description: Check tomorrow's weather forecast and set the Growatt battery charge level for overnight charging. Run this nightly at 10PM or manually any time.
---

# Charge Battery

Set the optimal overnight battery charge level based on tomorrow's weather forecast and historical usage data.

## Steps

1. Read `last_updated.md` in the project root to check when this was last run.
2. Run the orchestrator:

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
from datetime import date, timedelta
from pathlib import Path
from src.config import load_config
from src.db.schema import init_db
from src.weather.open_meteo import OpenMeteoProvider
from src.growatt.client import GrowattClient
from src.orchestrator import run_nightly

config = load_config(Path('config.yaml'))
conn = init_db(Path('data/battery.db'))
weather = OpenMeteoProvider()
growatt = GrowattClient(config.growatt)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_nightly(config, conn, weather, growatt, tomorrow, Path('.'))
conn.close()
print(result)
"
```

3. Read `last_updated.md` and summarise what happened to the user in plain language.

## Override

If the user specifies a charge level (e.g., "charge battery to 80%"), set `manual_override: 80` in `config.yaml` before running, then clear it after.
```

- [ ] **Step 2: Create battery-dashboard skill**

```markdown
---
name: battery-dashboard
description: Launch the battery charge dashboard in the browser to view historical decisions, forecast accuracy, and cost savings.
---

# Battery Dashboard

Start the local dashboard web app and open it in the browser.

## Steps

1. Start the FastAPI server:

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
import uvicorn
from pathlib import Path
from src.dashboard.app import create_app
app = create_app(Path('data/battery.db'))
uvicorn.run(app, host='127.0.0.1', port=8099)
" &
```

2. Open the browser:

```bash
start http://127.0.0.1:8099
```

3. Tell the user the dashboard is available at http://127.0.0.1:8099

## Answering Questions

If the user asks questions about the battery data, read from `last_updated.md` and query the SQLite database at `data/battery.db` to provide answers.
```

- [ ] **Step 3: Commit**

```bash
git add skills/
git commit -m "feat: Claude Code skills for charge-battery and battery-dashboard"
```

---

### Task 11: Integration Test and End-to-End Verification

**Files:**
- Modify: `tests/test_orchestrator.py` (add integration test)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Manual end-to-end test with real APIs**

Run the orchestrator against real Growatt and Open-Meteo APIs:

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
from datetime import date, timedelta
from pathlib import Path
from src.config import load_config
from src.db.schema import init_db
from src.weather.open_meteo import OpenMeteoProvider
from src.growatt.client import GrowattClient
from src.orchestrator import run_nightly

config = load_config(Path('config.yaml'))
conn = init_db(Path('data/battery.db'))
weather = OpenMeteoProvider()
growatt = GrowattClient(config.growatt)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_nightly(config, conn, weather, growatt, tomorrow, Path('.'))
conn.close()
print('Success:', result['success'])
print('Charge level:', result['charge_level'])
print('Reason:', result['reason'])
"
```

Expected: Charge level is set on the Growatt. `last_updated.md` is written. Decision is in the database.

- [ ] **Step 3: Verify dashboard works**

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
import uvicorn
from pathlib import Path
from src.dashboard.app import create_app
app = create_app(Path('data/battery.db'))
uvicorn.run(app, host='127.0.0.1', port=8099)
"
```

Open http://127.0.0.1:8099 and verify all pages load.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: integration tested and verified end-to-end"
```

---

### Task 12: Scheduling Setup

- [ ] **Step 1: Create a batch file for nightly scheduling**

Create `scripts/nightly-charge.bat`:

```bat
@echo off
cd /d C:\Users\gethi\source\weatherToBattery
claude -p "Run /charge-battery for tomorrow" --allowedTools "Bash,Read,Edit,Write"
```

- [ ] **Step 2: Register with Windows Task Scheduler**

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\gethi\source\weatherToBattery\scripts\nightly-charge.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 10:00PM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "WeatherToBattery" -Action $action -Trigger $trigger -Settings $settings -Description "Set battery charge based on weather forecast"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/
git commit -m "feat: nightly scheduling via Windows Task Scheduler"
```

- [ ] **Step 4: Clean up temporary files**

Remove `serve_spec.py` (the temporary spec viewer):

```bash
git rm serve_spec.py
git commit -m "chore: remove temporary spec viewer"
```
