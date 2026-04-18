"""Run nightly battery charge calculation and set on Growatt inverter."""
import sys
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.db.schema import init_db
from src.weather.open_meteo import OpenMeteoProvider
from src.growatt.client import GrowattClient
from src.orchestrator import run_nightly

config = load_config(project_root / "config.yaml")
conn = init_db(project_root / "data" / "battery.db")
weather = OpenMeteoProvider()
growatt = GrowattClient(config.growatt)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_nightly(config, conn, weather, growatt, tomorrow, project_root)
conn.close()

if result["success"]:
    print(f"Set charge to {result['charge_level']}% for {result['target_date']}")
else:
    print(f"FAILED: {result['errors']}", file=sys.stderr)
    sys.exit(1)
