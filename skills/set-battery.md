---
name: set-battery
description: Set the Growatt battery charge level for tomorrow to a specific percentage, bypassing the weather-based calculator. Use when the user says "set battery to N%", "set the battery to N", "force tomorrow's charge to N%", or similar direct-set phrasing.
---

# Set Battery

Set tomorrow's Growatt battery charge level to a specific percentage. Skips the weather-based calculator entirely. The nightly run will detect this manual setting and skip recomputing for the same date.

## Steps

1. Parse the percentage from the user's message. The value MUST be an integer in the range `1..100`. If you cannot parse a percentage in that range, ask the user for one and stop.

2. Run the shortcut:

```bash
cd C:\Users\gethi\source\weatherToBattery
python -c "
from datetime import date, timedelta
from pathlib import Path
from src.config import load_config
from src.db.schema import init_db
from src.growatt.client import GrowattClient
from src.orchestrator import run_manual

LEVEL = <PERCENTAGE>
config = load_config(Path('config.yaml'))
conn = init_db(Path('data/battery.db'))
growatt = GrowattClient(config.growatt, rates=config.rates)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_manual(config, conn, growatt, LEVEL, tomorrow, Path('.'))
conn.close()
print(result)
"
```

Replace the `<PERCENTAGE>` placeholder with the integer you parsed from the user's message (no quotes, no `%` sign — just the bare number, e.g. `LEVEL = 80`).

3. Read `last_updated.md` and summarise in plain language: "Battery set to N% for tomorrow YYYY-MM-DD. The nightly calculator will skip this date."

4. If `result["success"]` is `False`, surface the errors from `result["errors"]` to the user instead of claiming success.
