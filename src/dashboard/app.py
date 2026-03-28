# src/dashboard/app.py
import sqlite3
import statistics
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Battery Charge Dashboard")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def fmt3(value):
        """Format a number to 3 decimal places. Pass through non-numeric values."""
        if value is None:
            return "-"
        try:
            return f"{float(value):.3f}"
        except (ValueError, TypeError):
            return value

    templates.env.filters["f3"] = fmt3

    def get_conn():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        conn = get_conn()
        cursor = conn.execute(
            "SELECT * FROM decisions ORDER BY date DESC LIMIT 1")
        decision = cursor.fetchone()
        cursor = conn.execute(
            "SELECT * FROM actuals ORDER BY date DESC LIMIT 1")
        actual = cursor.fetchone()
        conn.close()
        return templates.TemplateResponse("overview.html", {
            "request": request, "decision": decision, "actual": actual
        })

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request):
        conn = get_conn()
        decisions = conn.execute(
            "SELECT d.*, a.total_solar_generation_kwh, a.grid_import_kwh, a.grid_export_kwh "
            "FROM decisions d LEFT JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC LIMIT 90"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("history.html", {
            "request": request, "decisions": decisions
        })

    @app.get("/accuracy", response_class=HTMLResponse)
    def accuracy(request: Request):
        conn = get_conn()
        raw = conn.execute(
            "SELECT d.date, d.forecast_summary, d.charge_level_set, "
            "a.total_solar_generation_kwh, a.expensive_grid_import_kwh, "
            "a.expensive_grid_export_kwh, a.weather_condition, "
            "a.expensive_consumption_kwh, a.expensive_solar_kwh, "
            "a.expensive_battery_discharge_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC LIMIT 90"
        ).fetchall()
        rows = []
        for r in raw:
            dt, forecast, charge, actual_solar, grid_import, grid_export, actual_weather, consumption, exp_solar, exp_battery = r
            month = int(dt.split("-")[1])
            # Calculate what P25 estimate would have been for the forecast condition
            est_vals = conn.execute(
                "SELECT total_solar_generation_kwh FROM actuals "
                "WHERE CAST(strftime('%m', date) AS INTEGER) = ? "
                "AND weather_condition = ? AND date < ? "
                "ORDER BY total_solar_generation_kwh",
                (month, forecast, dt)
            ).fetchall()
            if len(est_vals) >= 5:
                idx = int(len(est_vals) * 0.25)
                estimated_solar = round(est_vals[idx][0], 1)
            else:
                estimated_solar = None
            rows.append({
                "date": dt,
                "forecast": forecast,
                "actual_weather": actual_weather,
                "charge": charge,
                "estimated_solar": estimated_solar,
                "actual_solar": round(actual_solar, 1) if actual_solar else None,
                "consumption": round(consumption, 1) if consumption else None,
                "grid_import": round(grid_import, 1) if grid_import else None,
                "grid_export": round(grid_export, 1) if grid_export else None,
                "import_cost": round(grid_import * 0.30, 2) if grid_import else None,
                "export_cost": round(grid_export * 0.07, 2) if grid_export else None,
                "exp_solar": round(exp_solar, 1) if exp_solar else None,
                "exp_battery": round(exp_battery, 1) if exp_battery else None,
            })
        conn.close()
        return templates.TemplateResponse("accuracy.html", {
            "request": request, "rows": rows
        })

    @app.get("/savings", response_class=HTMLResponse)
    def savings(request: Request):
        conn = get_conn()
        rows = conn.execute(
            "SELECT d.date, d.charge_level_set, "
            "a.total_solar_generation_kwh, a.total_consumption_kwh, "
            "a.grid_import_kwh, a.grid_export_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC"
        ).fetchall()
        conn.close()
        return templates.TemplateResponse("savings.html", {
            "request": request, "rows": rows
        })

    @app.get("/solar-profile", response_class=HTMLResponse)
    def solar_profile(request: Request):
        conn = get_conn()
        # Daily generation for last 90 days
        daily = conn.execute(
            "SELECT date, total_solar_generation_kwh FROM actuals "
            "ORDER BY date DESC LIMIT 90"
        ).fetchall()
        daily = list(reversed(daily))  # chronological order

        # Monthly averages by hour — from hourly_profiles table if available
        hourly_profile = conn.execute(
            "SELECT hour, avg_generation FROM hourly_profiles ORDER BY hour"
        ).fetchall() if _table_exists(conn, "hourly_profiles") else []

        conn.close()
        return templates.TemplateResponse("solar_profile.html", {
            "request": request,
            "daily": daily,
            "hourly_profile": hourly_profile,
        })

    @app.get("/generation-stats", response_class=HTMLResponse)
    def generation_stats(request: Request):
        conn = get_conn()
        rows = []
        for month in range(1, 13):
            for cond in ['sunny', 'cloudy', 'rainy']:
                cursor = conn.execute(
                    "SELECT total_solar_generation_kwh FROM actuals "
                    "WHERE CAST(strftime('%m', date) AS INTEGER) = ? "
                    "AND weather_condition = ? "
                    "ORDER BY total_solar_generation_kwh",
                    (month, cond))
                vals = [r[0] for r in cursor.fetchall()]
                if len(vals) < 3:
                    continue
                n = len(vals)
                rows.append({
                    "month": month,
                    "condition": cond,
                    "n": n,
                    "avg": round(statistics.mean(vals), 1),
                    "median": round(statistics.median(vals), 1),
                    "stdev": round(statistics.stdev(vals), 1),
                    "p25": round(vals[int(n * 0.25)], 1),
                    "p75": round(vals[int(n * 0.75)], 1),
                    "min": round(min(vals), 1),
                    "max": round(max(vals), 1),
                })
        conn.close()
        return templates.TemplateResponse("generation_stats.html", {
            "request": request, "rows": rows
        })

    def _table_exists(conn, table_name: str) -> bool:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,))
        return cursor.fetchone() is not None

    return app
