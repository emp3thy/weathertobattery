---
name: battery-dashboard
description: Launch the battery charge dashboard in the browser to view historical decisions, forecast accuracy, and cost savings.
---

# Battery Dashboard

Start the local dashboard web app and open it in the browser.

## Steps

1. Start the FastAPI server (it reads the port from `config.yaml`, default 8099). Run this in the background:

```bash
cd C:\Users\gethi\sources\weathertobattery
python run_dashboard.py
```

   If `curl -sf http://127.0.0.1:8099` already responds, the dashboard is running; skip this step.

2. Open the browser:

```bash
start http://127.0.0.1:8099
```

3. Tell the user the dashboard is available at http://127.0.0.1:8099

## Answering Questions

If the user asks questions about the battery data, read from `last_updated.md` and query the SQLite database at `data/battery.db` to provide answers.
