"""Backfill weather_condition for actuals rows where it is NULL.

Fetches historical weather from Open-Meteo archive API in monthly chunks
and updates the actuals table. Designed to be run once (or re-run safely).
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Allow running from project root: python scripts/backfill_weather.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db.schema import init_db
from src.weather.historical import fetch_historical_weather


def _month_chunks(dates: list[str]) -> list[tuple[date, date]]:
    """Group a sorted list of YYYY-MM-DD strings into (start, end) month ranges."""
    if not dates:
        return []
    chunks: list[tuple[date, date]] = []
    current_start = date.fromisoformat(dates[0])
    current_month = (current_start.year, current_start.month)

    for ds in dates[1:]:
        d = date.fromisoformat(ds)
        if (d.year, d.month) != current_month:
            # End of previous month chunk — end is last day of that month
            # find the last date in the previous month
            chunks.append((current_start, date.fromisoformat(dates[dates.index(ds) - 1])))
            current_start = d
            current_month = (d.year, d.month)

    # Final chunk
    chunks.append((current_start, date.fromisoformat(dates[-1])))
    return chunks


def main() -> None:
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    cfg = load_config(config_path)

    db_path = Path(__file__).resolve().parent.parent / "data" / "battery.db"
    conn = init_db(db_path)

    # Find actuals rows where weather_condition IS NULL
    cursor = conn.execute(
        "SELECT date FROM actuals WHERE weather_condition IS NULL ORDER BY date"
    )
    rows = [row[0] for row in cursor.fetchall()]

    if not rows:
        print("No actuals rows with missing weather_condition. Nothing to do.")
        return

    print(f"Found {len(rows)} rows needing weather backfill.")

    lat = cfg.location.latitude
    lon = cfg.location.longitude
    timezone = cfg.location.timezone

    # Group into monthly chunks to stay within API limits
    chunks = _month_chunks(rows)
    print(f"Processing {len(chunks)} monthly chunk(s).")

    total_updated = 0

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        print(f"  Chunk {i}/{len(chunks)}: {chunk_start} to {chunk_end} ...", end=" ", flush=True)
        try:
            conditions = fetch_historical_weather(lat, lon, chunk_start, chunk_end, timezone)
        except Exception as e:
            print(f"ERROR: {e}")
            time.sleep(1)
            continue

        updated = 0
        for day_str, condition in conditions.items():
            if day_str in rows:
                conn.execute(
                    "UPDATE actuals SET weather_condition = ? WHERE date = ?",
                    (condition, day_str),
                )
                updated += 1

        conn.commit()
        total_updated += updated
        print(f"updated {updated} row(s).")

        if i < len(chunks):
            time.sleep(1)

    print(f"Done. Total rows updated: {total_updated}.")


if __name__ == "__main__":
    main()
