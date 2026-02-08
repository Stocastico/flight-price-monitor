"""Configuration loading and validation for the flight monitor."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def _interpolate_env_vars(value: str, lenient: bool = False) -> str:
    """Replace ${VAR_NAME} with the value of the environment variable.

    If lenient=True, unset variables are replaced with empty strings
    instead of raising ValueError. This is used for optional config sections.
    """

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            if lenient:
                return ""
            raise ValueError(f"Environment variable {var_name} is not set")
        return env_val

    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _walk_and_interpolate(obj: object, lenient: bool = False) -> object:
    """Recursively interpolate env vars in all string values."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj, lenient=lenient)
    if isinstance(obj, dict):
        # Use lenient mode for optional/disabled notification sections
        optional_keys = ("email", "telegram")
        for key in optional_keys:
            if key in obj and isinstance(obj.get(key), dict):
                enabled = obj[key].get("enabled", False)
                section_lenient = True if not enabled else lenient
                obj[key] = _walk_and_interpolate(obj[key], lenient=section_lenient)
        return {
            k: _walk_and_interpolate(v, lenient=lenient)
            if k not in optional_keys
            else obj[k]
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_walk_and_interpolate(item, lenient=lenient) for item in obj]
    return obj


class OriginConfig(BaseModel):
    code: str
    city: str = ""


class DestinationConfig(BaseModel):
    name: str
    airports: list[str]


class KiwiCredentials(BaseModel):
    api_key: str


class AmadeusCredentials(BaseModel):
    client_id: str
    client_secret: str


class CredentialsConfig(BaseModel):
    kiwi: KiwiCredentials | None = None
    amadeus: AmadeusCredentials | None = None


class SearchConfig(BaseModel):
    date_range_days: int = 90
    currency: str = "EUR"
    adults: int = 1
    flight_type: str = "oneway"
    max_results_per_route: int = 50


class FiltersConfig(BaseModel):
    prefer_direct: bool = True
    max_stops: int = 1
    max_duration_minutes: int = 600
    departure_time_earliest: str = "06:00"
    departure_time_latest: str = "22:00"
    allowed_airlines: list[str] = Field(default_factory=list)
    excluded_airlines: list[str] = Field(default_factory=list)
    cabin_bag_only: bool = False


class AnalysisConfig(BaseModel):
    deal_threshold_pct: float = 25.0
    min_history_count: int = 3
    stats_lookback_days: int | None = None  # None = use all history


class StorageConfig(BaseModel):
    db_path: str = "~/.flight_monitor/prices.db"


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    sender: str = ""
    password: str = ""
    recipients: list[str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class ReportingConfig(BaseModel):
    format: str = "console"
    html_output_path: str = "/tmp/flight_deals_report.html"
    email: EmailConfig = Field(default_factory=EmailConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class AppConfig(BaseModel):
    provider: str = "kiwi"
    credentials: CredentialsConfig
    origins: list[OriginConfig]
    destinations: list[DestinationConfig]
    search: SearchConfig = Field(default_factory=SearchConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)


def load_config(path: str | Path) -> AppConfig:
    """Load and validate configuration from a YAML file."""
    path = Path(path).expanduser()
    with open(path) as f:
        raw = yaml.safe_load(f)

    resolved = _walk_and_interpolate(raw)
    if not isinstance(resolved, dict):
        raise ValueError("Configuration file must contain a YAML mapping")
    return AppConfig(**resolved)
