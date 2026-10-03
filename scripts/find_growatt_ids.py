"""Print the plant ID and device serial numbers for the Growatt account in .env.

Usage: fill GROWATT_USERNAME and GROWATT_PASSWORD in .env, then run
    python scripts\find_growatt_ids.py
and copy the printed values into GROWATT_PLANT_ID and GROWATT_DEVICE_SN.
"""
import os
import sys
from pathlib import Path

import growattServer
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

username = os.environ.get("GROWATT_USERNAME")
password = os.environ.get("GROWATT_PASSWORD")
if not username or not password:
    print("Set GROWATT_USERNAME and GROWATT_PASSWORD in .env first.", file=sys.stderr)
    sys.exit(1)

api = growattServer.GrowattApi()
api.session.headers.update(
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
)
login = api.login(username, password)
if not login.get("success"):
    print(f"Login failed: {login.get('error', 'unknown')}", file=sys.stderr)
    sys.exit(1)

plants = api.plant_list(login["user"]["id"])
for plant in plants.get("data", []):
    plant_id = plant.get("plantId")
    print(f"GROWATT_PLANT_ID={plant_id}   ({plant.get('plantName')})")
    for dev in api.device_list(plant_id):
        print(f"GROWATT_DEVICE_SN={dev.get('deviceSn')}   "
              f"(type={dev.get('deviceType')}, capacity={dev.get('capacity')})")
