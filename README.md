# weatherToBattery

Automatically sets the overnight charge level on a Growatt battery based on tomorrow's weather forecast and historical usage data. The goal is to charge only what you need from cheap-rate electricity, letting solar cover the rest.

## How it works

Each evening the system:

1. Fetches tomorrow's hourly weather forecast from Open-Meteo
2. Estimates solar generation using your historical best output, scaled by forecast cloud cover with a diffuse radiation floor (panels still produce ~25% output at 100% cloud)
3. Estimates consumption from your recent expensive-period usage
4. Calculates the gap between consumption and expected generation
5. Applies a morning floor -- enough charge to bridge from cheap-rate end until solar covers the load
6. Sets the battery charge level on your Growatt inverter via the Growatt API

A local dashboard shows historical decisions, forecast accuracy, and cost savings.

## Requirements

- Python 3.12+
- A Growatt inverter with API access
- A time-of-use electricity tariff (cheap overnight rate)

## Setup

1. Clone the repo and install dependencies:

```
git clone https://github.com/emp3thy/weathertobattery.git
cd weathertobattery
pip install -r requirements.txt
```

2. Copy the example config and edit it:

```
cp config.example.yaml config.yaml
```

3. Create a `.env` file with your Growatt credentials:

```
GROWATT_USERNAME=your_username
GROWATT_PASSWORD=your_password
GROWATT_PLANT_ID=your_plant_id
GROWATT_DEVICE_SN=your_device_sn
```

## Configuration

Edit `config.yaml`:

| Section | Key | Description |
|---------|-----|-------------|
| `location` | `latitude`, `longitude`, `timezone` | Your location for weather and solar calculations |
| `battery` | `total_capacity_kwh` | Total battery capacity |
| `battery` | `usable_fraction` | Usable fraction (e.g. 0.90 for 90%) |
| `battery` | `min_soc_pct` | Minimum state of charge to maintain (default 10%) |
| `battery` | `cloud_floor_pct` | Minimum % of clear-sky output at 100% cloud (default 25%) |
| `battery` | `morning_buffer_kwh` | Extra kWh buffer for the morning gap (default 2.0) |
| `battery` | `fallback_charge_level` | Charge level when weather API is unavailable (default 90%) |
| `rates` | `cheap_start`, `cheap_end` | Your cheap-rate window (e.g. 23:30 to 05:30) |
| `rates` | `cheap_pence_per_kwh`, `expensive_pence_per_kwh` | Tariff rates for savings calculation |
| `dashboard` | `port` | Local dashboard port (default 8099) |
| | `manual_override` | Set to 0-100 to force a specific charge level once, then auto-clears |

## Usage

### Set tonight's charge level

```
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
growatt = GrowattClient(config.growatt, rates=config.rates)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_nightly(config, conn, weather, growatt, tomorrow, Path('.'))
conn.close()
print(result)
"
```

Or use the batch file for scheduled runs:

```
scripts\nightly-charge.bat
```

### View the dashboard

```
python run_dashboard.py
```

Then open http://127.0.0.1:8099. Pages include:

- **Overview** -- today's decision and current state
- **History** -- past decisions and outcomes
- **Accuracy** -- estimated vs actual solar generation
- **Savings** -- cost savings from smart charging vs always charging to 100%

### Scheduling

Set up a nightly task (e.g. Windows Task Scheduler or cron) to run the charge script around 10 PM, before your cheap rate starts.

## Data

All data is stored in `data/battery.db` (SQLite). The database is created automatically on first run and tracks:

- **decisions** -- what charge level was set and why
- **actuals** -- real solar generation, consumption, and grid usage (backfilled daily from Growatt)

## Tests

```
pip install pytest httpx
python -m pytest tests/
```
