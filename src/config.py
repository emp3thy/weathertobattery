from dataclasses import dataclass
from pathlib import Path
import yaml


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
    charge_floor_pct: int

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


@dataclass
class WinterOverrideConfig:
    start: str
    end: str


@dataclass
class FeedbackConfig:
    max_per_night_pct: int
    max_cumulative_pct: int
    decay_per_day_pct: int


@dataclass
class BootstrapConfig:
    spring_autumn_pct: int
    sunny_summer_pct: int
    winter_pct: int


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
    winter_override: WinterOverrideConfig
    feedback: FeedbackConfig
    bootstrap: BootstrapConfig
    dashboard: DashboardConfig
    manual_override: int | None


def _validate(cfg: Config) -> None:
    if not (0 <= cfg.battery.charge_floor_pct <= 100):
        raise ConfigValidationError(
            f"charge_floor_pct must be 0-100, got {cfg.battery.charge_floor_pct}"
        )
    if cfg.battery.total_capacity_kwh <= 0:
        raise ConfigValidationError("total_capacity_kwh must be positive")
    if not (0 < cfg.battery.usable_fraction <= 1):
        raise ConfigValidationError("usable_fraction must be between 0 and 1")
    if cfg.manual_override is not None and not (0 <= cfg.manual_override <= 100):
        raise ConfigValidationError("manual_override must be 0-100 or null")


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    cfg = Config(
        location=LocationConfig(**raw["location"]),
        growatt=GrowattConfig(**raw["growatt"]),
        battery=BatteryConfig(**raw["battery"]),
        weather=WeatherConfig(**raw["weather"]),
        rates=RatesConfig(**raw["rates"]),
        winter_override=WinterOverrideConfig(**raw["winter_override"]),
        feedback=FeedbackConfig(**raw["feedback"]),
        bootstrap=BootstrapConfig(**raw["bootstrap"]),
        dashboard=DashboardConfig(**raw["dashboard"]),
        manual_override=raw.get("manual_override"),
    )
    _validate(cfg)
    return cfg
