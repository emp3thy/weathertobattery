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
  charge_floor_pct: 30
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
winter_override:
  start: "10-25"
  end: "02-28"
feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5
bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100
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


def test_config_validation_rejects_bad_floor(tmp_path):
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
  charge_floor_pct: 150
weather:
  provider: "open_meteo"
rates:
  cheap_pence_per_kwh: 7
  expensive_pence_per_kwh: 30
  export_pence_per_kwh: 0
  cheap_start: "23:30"
  cheap_end: "05:30"
winter_override:
  start: "10-25"
  end: "02-28"
feedback:
  max_per_night_pct: 15
  max_cumulative_pct: 25
  decay_per_day_pct: 5
bootstrap:
  spring_autumn_pct: 80
  sunny_summer_pct: 60
  winter_pct: 100
dashboard:
  port: 8099
manual_override: null
""")
    from src.config import load_config, ConfigValidationError
    with pytest.raises(ConfigValidationError):
        load_config(config_file)
