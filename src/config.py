from dataclasses import dataclass
from pathlib import Path
import os
import yaml
from dotenv import load_dotenv


class ConfigValidationError(Exception):
    pass


@dataclass
class LocationConfig:
    latitude: float
    longitude: float
    timezone: str


@dataclass
class GrowattConfig:
    username: str
    password: str
    plant_id: str
    device_sn: str
    server_url: str


@dataclass
class BatteryConfig:
    total_capacity_kwh: float
    usable_fraction: float
    fallback_charge_level: int = 90
    morning_buffer_kwh: float = 2.0
    min_soc_pct: int = 10

    @property
    def usable_capacity_kwh(self) -> float:
        return self.total_capacity_kwh * self.usable_fraction


@dataclass
class WeatherConfig:
    provider: str


@dataclass
class RatesConfig:
    cheap_pence_per_kwh: float
    expensive_pence_per_kwh: float
    export_pence_per_kwh: float
    cheap_start: str
    cheap_end: str

    def is_expensive(self, hour: int, minute: int) -> bool:
        """Return True if the given time falls outside the cheap window."""
        end_h, end_m = (int(x) for x in self.cheap_end.split(":"))
        start_h, start_m = (int(x) for x in self.cheap_start.split(":"))
        t = hour * 60 + minute
        cheap_end_t = end_h * 60 + end_m
        cheap_start_t = start_h * 60 + start_m
        # Cheap window wraps midnight (e.g. 23:30 -> 05:30)
        if cheap_start_t > cheap_end_t:
            return t >= cheap_end_t and t < cheap_start_t
        else:
            return t < cheap_start_t or t >= cheap_end_t


@dataclass
class DashboardConfig:
    port: int


@dataclass
class Config:
    location: LocationConfig
    growatt: GrowattConfig
    battery: BatteryConfig
    weather: WeatherConfig
    rates: RatesConfig
    dashboard: DashboardConfig
    manual_override: int | None


def _validate(cfg: Config) -> None:
    if cfg.battery.total_capacity_kwh <= 0:
        raise ConfigValidationError("total_capacity_kwh must be positive")
    if not (0 < cfg.battery.usable_fraction <= 1):
        raise ConfigValidationError("usable_fraction must be between 0 and 1")
    if cfg.manual_override is not None and not (0 <= cfg.manual_override <= 100):
        raise ConfigValidationError("manual_override must be 0-100 or null")
    if not (0 <= cfg.battery.min_soc_pct < 100):
        raise ConfigValidationError("min_soc_pct must be between 0 and 99")


def load_config(path: Path) -> Config:
    load_dotenv(path.parent / ".env")

    with open(path) as f:
        raw = yaml.safe_load(f)

    battery_raw = raw["battery"]
    # charge_floor_pct may still be in old configs — ignore it
    battery_raw.pop("charge_floor_pct", None)

    growatt_raw = raw["growatt"]
    growatt_raw["username"] = os.environ.get("GROWATT_USERNAME", growatt_raw["username"])
    growatt_raw["password"] = os.environ.get("GROWATT_PASSWORD", growatt_raw["password"])
    growatt_raw["plant_id"] = os.environ.get("GROWATT_PLANT_ID", growatt_raw["plant_id"])
    growatt_raw["device_sn"] = os.environ.get("GROWATT_DEVICE_SN", growatt_raw["device_sn"])

    location_raw = raw["location"]
    location_raw["latitude"] = float(os.environ.get("LOCATION_LATITUDE") or location_raw["latitude"])
    location_raw["longitude"] = float(os.environ.get("LOCATION_LONGITUDE") or location_raw["longitude"])
    location_raw["timezone"] = os.environ.get("LOCATION_TIMEZONE", location_raw["timezone"])

    cfg = Config(
        location=LocationConfig(**location_raw),
        growatt=GrowattConfig(**growatt_raw),
        battery=BatteryConfig(**battery_raw),
        weather=WeatherConfig(**raw["weather"]),
        rates=RatesConfig(**raw["rates"]),
        dashboard=DashboardConfig(**raw["dashboard"]),
        manual_override=raw.get("manual_override"),
    )
    _validate(cfg)
    return cfg
