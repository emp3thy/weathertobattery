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
