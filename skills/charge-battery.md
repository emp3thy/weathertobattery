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
