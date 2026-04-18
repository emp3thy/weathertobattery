import pytest
from pathlib import Path

def test_load_config_returns_dataclass(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test_user"
  password: "test_pass"
  plant_id: "123"
  device_sn: "ABC123"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.location.latitude == 51.4067
    assert cfg.growatt.username == "test_user"
    assert cfg.battery.usable_capacity_kwh == pytest.approx(11.97)
    assert cfg.manual_override is None


def test_config_loads_min_soc_pct(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test"
  password: "test"
  plant_id: "123"
  device_sn: "ABC"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
  min_soc_pct: 15
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.battery.min_soc_pct == 15


def test_config_defaults_min_soc_pct(tmp_path):
    """Config without min_soc_pct should default to 10."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
location:
  latitude: 51.4067
  longitude: 0.0481
  timezone: "Europe/London"
growatt:
  username: "test"
  password: "test"
  plant_id: "123"
  device_sn: "ABC"
  server_url: "https://server.growatt.com/"
battery:
  total_capacity_kwh: 13.3
  usable_fraction: 0.90
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config
    cfg = load_config(config_file)
    assert cfg.battery.min_soc_pct == 10
