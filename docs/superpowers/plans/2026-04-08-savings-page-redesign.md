# Savings Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken savings page with correct cost calculations showing no-solar savings, battery value, and a 90-day chart.

**Architecture:** Add a `compute_daily_savings` helper function that takes a joined decision+actuals row and config rates, returns a dict of computed metrics. The `/savings` endpoint aggregates these into daily/monthly/all-time summaries and a chart series. The template renders three summary cards and a Chart.js line graph.

**Tech Stack:** Python, FastAPI, Jinja2, Chart.js (already loaded in base.html), SQLite

**Spec:** `docs/superpowers/specs/2026-04-08-savings-page-redesign.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/dashboard/savings.py` | Create | `compute_daily_savings()` pure function |
| `tests/test_savings.py` | Create | Unit tests for savings calculation logic |
| `src/dashboard/app.py` | Modify | Rewrite `/savings` endpoint |
| `src/dashboard/templates/savings.html` | Modify | New template with cards + chart |
| `tests/test_dashboard.py` | Modify | Update savings page integration test |

---

### Task 1: Create `compute_daily_savings` function with tests

**Files:**
- Create: `src/dashboard/savings.py`
- Create: `tests/test_savings.py`

- [ ] **Step 1: Write failing test for basic sunny day savings**

Create `tests/test_savings.py`:

```python
from src.dashboard.savings import compute_daily_savings


def test_basic_sunny_day():
    """April 8 real data: charged from 10% to 29%, generated 34.75 kWh."""
    row = {
        "charge_level_set": 29,
        "current_soc_at_decision": 10,
        "total_consumption_kwh": 35.8,
        "grid_import_kwh": 4.033,
        "grid_export_kwh": 1.042,
        "expensive_battery_discharge_kwh": 8.908,
    }
    result = compute_daily_savings(
        row,
        usable_capacity_kwh=11.97,
        cheap_rate=7.0,
        expensive_rate=30.0,
    )
    # Charged: (29 - 10) / 100 * 11.97 = 2.274 kWh
    assert abs(result["charged_kwh"] - 2.274) < 0.01
    # Cheap charge cost: 2.274 * 7 = 15.92p
    assert abs(result["cheap_charge_cost_pence"] - 15.92) < 0.1
    # Export waste: 1.042 * 7 = 7.29p
    assert abs(result["export_waste_pence"] - 7.29) < 0.1
    # Grid cost: 4.033 * 30 = 121.0p
    assert abs(result["grid_cost_pence"] - 121.0) < 0.1
    # No-solar baseline: 35.8 * 30 = 1074p
    # Actual cost: 121.0 + 15.92 = 136.92p
    # No-solar saving: 1074 - 136.92 = 937.08p
    assert abs(result["no_solar_saving_pence"] - 937.08) < 0.2
    # Battery value: 8.908 * (30-7) - 1.042 * 7 = 204.88 - 7.29 = 197.59p
    assert abs(result["battery_value_pence"] - 197.59) < 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_savings.py::test_basic_sunny_day -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `compute_daily_savings`**

Create `src/dashboard/savings.py`:

```python
def compute_daily_savings(
    row: dict,
    usable_capacity_kwh: float,
    cheap_rate: float,
    expensive_rate: float,
) -> dict:
    """Compute daily savings metrics from a joined decision+actuals row.

    All cost/saving values are in pence.
    """
    charge_set = row["charge_level_set"] or 0
    current_soc = row.get("current_soc_at_decision")
    if current_soc is None:
        soc_before = 0
    else:
        soc_before = current_soc

    charged_kwh = max(0, (charge_set - soc_before) / 100 * usable_capacity_kwh)
    cheap_charge_cost_pence = charged_kwh * cheap_rate

    grid_export = row["grid_export_kwh"] or 0
    export_waste_pence = grid_export * cheap_rate

    grid_import = row["grid_import_kwh"] or 0
    grid_cost_pence = grid_import * expensive_rate

    total_consumption = row["total_consumption_kwh"] or 0
    no_solar_baseline_pence = total_consumption * expensive_rate
    actual_cost_pence = grid_cost_pence + cheap_charge_cost_pence
    no_solar_saving_pence = no_solar_baseline_pence - actual_cost_pence

    battery_discharge = row.get("expensive_battery_discharge_kwh") or 0
    net_rate = expensive_rate - cheap_rate
    battery_value_pence = battery_discharge * net_rate - export_waste_pence

    return {
        "charged_kwh": charged_kwh,
        "cheap_charge_cost_pence": cheap_charge_cost_pence,
        "export_waste_pence": export_waste_pence,
        "grid_cost_pence": grid_cost_pence,
        "no_solar_saving_pence": no_solar_saving_pence,
        "battery_value_pence": battery_value_pence,
        "actual_cost_pence": actual_cost_pence,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_savings.py::test_basic_sunny_day -v`
Expected: PASS

- [ ] **Step 5: Write test for SOC higher than charge target (no charging)**

Add to `tests/test_savings.py`:

```python
def test_soc_higher_than_target():
    """SOC already above target — no charging happens."""
    row = {
        "charge_level_set": 29,
        "current_soc_at_decision": 47,
        "total_consumption_kwh": 35.8,
        "grid_import_kwh": 4.0,
        "grid_export_kwh": 1.0,
        "expensive_battery_discharge_kwh": 9.0,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    assert result["charged_kwh"] == 0
    assert result["cheap_charge_cost_pence"] == 0
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_savings.py::test_soc_higher_than_target -v`
Expected: PASS

- [ ] **Step 7: Write test for NULL current_soc (old records)**

Add to `tests/test_savings.py`:

```python
def test_null_soc_assumes_zero():
    """Old records with no SOC data — assume battery was empty (conservative)."""
    row = {
        "charge_level_set": 60,
        "current_soc_at_decision": None,
        "total_consumption_kwh": 20.0,
        "grid_import_kwh": 3.0,
        "grid_export_kwh": 0.5,
        "expensive_battery_discharge_kwh": 5.0,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    # Charged: 60/100 * 11.97 = 7.182 kWh (assumes SOC was 0)
    assert abs(result["charged_kwh"] - 7.182) < 0.01
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_savings.py::test_null_soc_assumes_zero -v`
Expected: PASS

- [ ] **Step 9: Write test for NULL battery discharge (old records)**

Add to `tests/test_savings.py`:

```python
def test_null_battery_discharge():
    """Old records missing battery discharge data — treat as 0."""
    row = {
        "charge_level_set": 50,
        "current_soc_at_decision": 10,
        "total_consumption_kwh": 20.0,
        "grid_import_kwh": 5.0,
        "grid_export_kwh": 1.0,
        "expensive_battery_discharge_kwh": None,
    }
    result = compute_daily_savings(
        row, usable_capacity_kwh=11.97, cheap_rate=7.0, expensive_rate=30.0,
    )
    # Battery value: 0 * 23 - 1.0 * 7 = -7.0p (only export waste)
    assert abs(result["battery_value_pence"] - (-7.0)) < 0.01
```

- [ ] **Step 10: Run all savings tests**

Run: `python -m pytest tests/test_savings.py -v`
Expected: All 4 tests pass.

- [ ] **Step 11: Commit**

```bash
git add src/dashboard/savings.py tests/test_savings.py
git commit -m "feat: add compute_daily_savings function with tests"
```

---

### Task 2: Rewrite `/savings` endpoint

**Files:**
- Modify: `src/dashboard/app.py:113-126` (the `savings` function)

- [ ] **Step 1: Rewrite the savings endpoint**

Replace the `savings` function in `src/dashboard/app.py` (lines 113-126) with:

```python
    @app.get("/savings", response_class=HTMLResponse)
    def savings(request: Request):
        from .savings import compute_daily_savings
        from datetime import datetime

        conn = get_conn()
        rows = conn.execute(
            "SELECT d.date, d.charge_level_set, d.current_soc_at_decision, "
            "a.total_consumption_kwh, a.grid_import_kwh, a.grid_export_kwh, "
            "a.expensive_battery_discharge_kwh "
            "FROM decisions d JOIN actuals a ON d.date = a.date "
            "ORDER BY d.date DESC"
        ).fetchall()
        conn.close()

        cheap_rate = config.rates.cheap_pence_per_kwh
        expensive_rate = config.rates.expensive_pence_per_kwh
        usable = config.battery.usable_capacity_kwh

        daily = []
        for r in rows:
            row_dict = {
                "charge_level_set": r["charge_level_set"],
                "current_soc_at_decision": r["current_soc_at_decision"],
                "total_consumption_kwh": r["total_consumption_kwh"],
                "grid_import_kwh": r["grid_import_kwh"],
                "grid_export_kwh": r["grid_export_kwh"],
                "expensive_battery_discharge_kwh": r["expensive_battery_discharge_kwh"],
            }
            metrics = compute_daily_savings(row_dict, usable, cheap_rate, expensive_rate)
            metrics["date"] = r["date"]
            daily.append(metrics)

        # Aggregate into periods
        now_month = datetime.now().strftime("%Y-%m")

        def aggregate(items):
            return {
                "no_solar_saving": sum(d["no_solar_saving_pence"] for d in items) / 100,
                "battery_value": sum(d["battery_value_pence"] for d in items) / 100,
                "actual_cost": sum(d["actual_cost_pence"] for d in items) / 100,
                "days": len(items),
            }

        latest = aggregate(daily[:1]) if daily else None
        monthly = aggregate([d for d in daily if d["date"].startswith(now_month)])
        all_time = aggregate(daily)

        # Chart data: last 90 days in chronological order
        chart_days = list(reversed(daily[:90]))
        chart_labels = [d["date"] for d in chart_days]
        chart_values = [round(d["battery_value_pence"], 1) for d in chart_days]

        return templates.TemplateResponse("savings.html", {
            "request": request,
            "latest": latest,
            "monthly": monthly,
            "all_time": all_time,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "cheap_rate": cheap_rate,
            "expensive_rate": expensive_rate,
        })
```

- [ ] **Step 2: Run existing dashboard test to check it still loads**

Run: `python -m pytest tests/test_dashboard.py::test_savings_page -v`
Expected: May fail due to missing template changes — that's fine, Task 3 will fix it.

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/app.py
git commit -m "feat: rewrite savings endpoint with correct calculations"
```

---

### Task 3: Rewrite savings template

**Files:**
- Modify: `src/dashboard/templates/savings.html`

- [ ] **Step 1: Replace savings.html entirely**

Write `src/dashboard/templates/savings.html`:

```html
{% extends "base.html" %}
{% block title %}Battery Dashboard - Cost Savings{% endblock %}
{% block content %}
<h1>Cost Savings</h1>
<p style="font-size: 13px; color: #666;">Rates: cheap {{ cheap_rate }}p/kWh, expensive {{ expensive_rate }}p/kWh</p>

<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px;">
    {% for period, label in [(latest, "Latest Day"), (monthly, "This Month"), (all_time, "All Time")] %}
    <div class="card">
        <h3 style="margin-top: 0; font-size: 14px; color: #666;">{{ label }}{% if period %} ({{ period.days }} day{{ "s" if period.days != 1 }}){% endif %}</h3>
        {% if period %}
        <p><strong>No-solar saving:</strong> &pound;{{ "%.2f"|format(period.no_solar_saving) }}</p>
        <p><strong>Battery value:</strong> &pound;{{ "%.2f"|format(period.battery_value) }}</p>
        <p><strong>Actual grid cost:</strong> &pound;{{ "%.2f"|format(period.actual_cost) }}</p>
        {% else %}
        <p>No data</p>
        {% endif %}
    </div>
    {% endfor %}
</div>

<div class="card">
    <h2 style="margin-top: 0;">Daily Battery Value (last 90 days)</h2>
    <canvas id="batteryChart"></canvas>
</div>

<script>
    const ctx = document.getElementById('batteryChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: {{ chart_labels | tojson }},
            datasets: [{
                label: 'Battery value (pence)',
                data: {{ chart_values | tojson }},
                borderColor: '#2563eb',
                backgroundColor: 'rgba(37, 99, 235, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    title: { display: true, text: 'Pence' },
                    beginAtZero: true,
                },
                x: {
                    ticks: { maxTicksToShow: 15 }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
</script>
{% endblock %}
```

- [ ] **Step 2: Run dashboard test**

Run: `python -m pytest tests/test_dashboard.py::test_savings_page -v`
Expected: PASS (page loads with 200 status).

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/templates/savings.html
git commit -m "feat: rewrite savings template with cards and chart"
```

---

### Task 4: Update dashboard integration test

**Files:**
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Update test fixture to include full actuals data**

The current `dashboard_client` fixture inserts actuals without `expensive_battery_discharge_kwh`. Update it to include the new fields and insert a matching decision+actuals pair on the same date so the JOIN works for the savings page.

Replace the `dashboard_client` fixture in `tests/test_dashboard.py`:

```python
@pytest.fixture
def dashboard_client(tmp_path):
    from src.db.schema import init_db
    from src.db.queries import upsert_decision, insert_actuals
    from datetime import date

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_decision(conn, date(2026, 3, 25), "sunny", "[]", 60, 55, 5,
                    "test", 10, 3, "open_meteo")
    insert_actuals(conn, date(2026, 3, 25), 20.0, 25.0, 5.0, 2.0,
                   "10:00", 15, 95,
                   expensive_battery_discharge_kwh=8.0)
    conn.close()

    from src.config import load_config
    from src.dashboard.app import create_app
    from pathlib import Path
    config = load_config(Path(__file__).parent.parent / "config.yaml")
    app = create_app(db_path, config)
    return TestClient(app)
```

- [ ] **Step 2: Update savings test to check for new content**

Replace `test_savings_page` in `tests/test_dashboard.py`:

```python
def test_savings_page(dashboard_client):
    resp = dashboard_client.get("/savings")
    assert resp.status_code == 200
    assert "Battery value" in resp.text
    assert "No-solar saving" in resp.text
```

- [ ] **Step 3: Run all dashboard tests**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: All pass.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_dashboard.py
git commit -m "test: update dashboard fixture and savings test"
```
