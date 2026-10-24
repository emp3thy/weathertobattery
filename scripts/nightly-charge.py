"""Run nightly battery charge calculation and set on Growatt inverter.

Usage: nightly-charge.py [--dry-run]

--dry-run performs every step, including the Growatt login and the
calculation, but does not set the inverter or record a decision.
"""
import argparse
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

parser = argparse.ArgumentParser(description="Set tonight's Growatt charge level from tomorrow's forecast.")
parser.add_argument("--dry-run", action="store_true",
                    help="compute and report the charge level without setting the inverter or recording a decision")
args = parser.parse_args()

config = load_config(project_root / "config.yaml")
conn = init_db(project_root / "data" / "battery.db")
weather = OpenMeteoProvider()
growatt = GrowattClient(config.growatt, rates=config.rates)
growatt.login()
tomorrow = date.today() + timedelta(days=1)
result = run_nightly(config, conn, weather, growatt, tomorrow, project_root, dry_run=args.dry_run)
conn.close()

if result["success"]:
    if args.dry_run:
        print(f"DRY RUN: would set charge to {result['charge_level']}% for {result['target_date']}")
    else:
        print(f"Set charge to {result['charge_level']}% for {result['target_date']}")
else:
    print(f"FAILED: {result['errors']}", file=sys.stderr)
    sys.exit(1)
