# Hourly Readings Capture Design

**Date:** 2026-10-03
**Status:** Approved (in chat, 2026-10-03)

## Problem

The nightly run already fetches a full day of 5-minute readings from Growatt, but keeps only daily totals. Growatt retains roughly three months of 5-minute data: on 2026-10-03 the oldest day available was 2026-07-04, and each day another day of July expires. The planned replacement for the charge calculator (an hourly battery simulation, see the brainstorm of 2026-10-03) needs intra-day history: load by hour of day, solar by hour of day, and the 3 kW charge cap behaviour, none of which can be recovered from daily totals. This capture must start before the design of the simulation is finished.

## Solution

Store the raw 5-minute readings as Growatt returns them, in a new `readings` table, and have the existing per-day backfill write them alongside the daily totals. The backfill script that walks back through Growatt history is re-run to populate the 91 days already in the database.

Raw readings are stored rather than hourly sums because the data cannot be re-fetched once it expires, and because grid import is derived with a `max(0, ...)` that is non-linear, so hourly sums would lose information the simulation may want. Volume is 288 rows a day, about 105,000 a year, which is trivial for SQLite.

## Changes

### Schema (`src/db/schema.py`)

Add to `SCHEMA_SQL`, after the `actuals` table:

```sql
CREATE TABLE IF NOT EXISTS readings (
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    ppv_kw REAL NOT NULL,
    sys_out_kw REAL NOT NULL,
    user_load_kw REAL NOT NULL,
    pac_to_user_kw REAL NOT NULL,
    PRIMARY KEY (date, time)
);
```

`date` is `YYYY-MM-DD`, `time` is `HH:MM` exactly as Growatt keys it. The four values are the Growatt fields `ppv`, `sysOut`, `userLoad`, `pacToUser`, in kW, converted to float. No migration function change is needed: `CREATE TABLE IF NOT EXISTS` runs on every `init_db`.

### Queries (`src/db/queries.py`)

- `insert_readings(conn, dt: date, hourly: dict) -> None`. Iterates `hourly` in key order, skips entries whose value is not a dict (Growatt includes non-reading keys), converts each of the four fields with `float(value.get(field) or 0)` so a missing or null field stores as 0.0, and writes with `INSERT OR REPLACE` so re-running for the same day is idempotent. Commits once at the end.
- `has_readings(conn, dt: date) -> bool`. True when at least one row exists for the date.

### Orchestrator (`src/orchestrator.py`)

`backfill_actuals_for_day(conn, growatt_client, config, day) -> bool` changes from "skip if daily totals exist" to:

1. If the day has daily totals and has readings, return `False` without calling Growatt.
2. Fetch the day's 5-minute data once. If no entry is a dict, raise `ValueError` as today.
3. If the day has no readings, call `insert_readings`.
4. If the day has no daily totals, compute and insert them exactly as today.
5. Return `True`.

The nightly wrapper `_backfill_actuals` is unchanged and still passes yesterday (the last complete day), so readings are never stored for a day still in progress.

### Backfill script (`scripts/backfill_actuals.py`)

No code change. Its "already present" count now reflects days with both totals and readings. Re-running it after this change fills readings for the 91 existing days.

## Testing

- Schema: `readings` has exactly the six columns above.
- Queries: a sample dict with three readings and one non-dict entry stores three rows with the converted values; inserting the same day twice leaves three rows; `has_readings` is false before and true after insert, and false for another date.
- Orchestrator, with a mocked Growatt client returning a sample dict: a day with existing totals and no readings gets readings stored and totals untouched; a day with neither gets both; a day with both returns `False` and the mock is never called; an empty dict still raises `ValueError`.
- Live verification: run `python scripts\backfill_actuals.py`, then confirm every `actuals` date has readings and the row count per day is near 288.

## Out of scope

Reading from the table (the simulation), the dashboard, and any change to the daily totals calculation.
