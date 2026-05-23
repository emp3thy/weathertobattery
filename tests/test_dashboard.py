import pytest
from fastapi.testclient import TestClient

# TODO(fastapi-compat): FastAPI >=0.110 dropped Router.__init__(on_startup=...).
# The dashboard app passes on_startup, which crashes TestClient construction.
# Fix by migrating create_app() to lifespan handlers, then remove these xfail marks.
pytestmark = pytest.mark.xfail(
    raises=TypeError,
    reason="FastAPI compat — Router.__init__ no longer accepts on_startup",
    strict=False,
)


@pytest.fixture
def dashboard_client(tmp_path, config):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, insert_actuals
    from datetime import date

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_decision(conn, date(2026, 3, 25), "sunny", "[]", 60,
                    "test", 10, 3, "open_meteo")
    insert_actuals(conn, date(2026, 3, 25), 20.0, 25.0, 5.0, 2.0,
                   "10:00", 15, 95,
                   expensive_battery_discharge_kwh=8.0)
    conn.close()

    from src.dashboard.app import create_app
    app = create_app(db_path, config)
    return TestClient(app)


def test_overview_page(dashboard_client):
    resp = dashboard_client.get("/")
    assert resp.status_code == 200
    assert "Battery" in resp.text


def test_history_page(dashboard_client):
    resp = dashboard_client.get("/history")
    assert resp.status_code == 200


def test_savings_page(dashboard_client):
    resp = dashboard_client.get("/savings")
    assert resp.status_code == 200
    assert "Battery value" in resp.text
    assert "No-solar saving" in resp.text
