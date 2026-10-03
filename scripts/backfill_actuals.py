"""Backfill the actuals table from Growatt's historical 5-minute data.

Growatt keeps roughly the last few months of 5-minute data. This walks back
day by day from yesterday, storing each day that has readings and stopping
after a run of consecutive empty days. Safe to re-run: existing rows are kept.

Usage:
    python scripts\backfill_actuals.py            # walk back up to 200 days
    python scripts\backfill_actuals.py 60         # walk back up to 60 days

Run scripts\backfill_weather.py afterwards to fill in weather conditions.
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.db.schema import init_db
from src.growatt.client import GrowattClient
from src.orchestrator import backfill_actuals_for_day

MAX_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
STOP_AFTER_EMPTY = 5


def main() -> None:
    config = load_config(project_root / "config.yaml")
    conn = init_db(project_root / "data" / "battery.db")
    growatt = GrowattClient(config.growatt, rates=config.rates)
    growatt.login()

    added = skipped = empty = 0
    consecutive_empty = 0
    day = date.today() - timedelta(days=1)
    for _ in range(MAX_DAYS):
        try:
            if backfill_actuals_for_day(conn, growatt, config, day):
                added += 1
                consecutive_empty = 0
                print(f"{day}: stored")
            else:
                skipped += 1
                consecutive_empty = 0
        except ValueError:
            empty += 1
            consecutive_empty += 1
            print(f"{day}: no data")
            if consecutive_empty >= STOP_AFTER_EMPTY:
                print(f"{STOP_AFTER_EMPTY} empty days in a row; assuming end of Growatt history.")
                break
        except Exception as e:
            print(f"{day}: ERROR {e}", file=sys.stderr)
        day -= timedelta(days=1)
        time.sleep(0.5)

    conn.close()
    print(f"Done. Added {added}, already present {skipped}, no data {empty}.")


if __name__ == "__main__":
    main()
