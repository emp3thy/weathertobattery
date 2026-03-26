# src/dashboard/app.py
import sqlite3
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
        rows = conn.execute(
            "SELECT d.date, d.forecast_summary, d.charge_level_set, "
            "a.total_solar_generation_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC LIMIT 90"
        ).fetchall()
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

    def _table_exists(conn, table_name: str) -> bool:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,))
        return cursor.fetchone() is not None

    return app
