"""Tests for configuration loading and validation."""

from __future__ import annotations

import os

import pytest

from flight_monitor.config import (
    AppConfig,
    CredentialsConfig,
    DestinationConfig,
    EmailConfig,
    FiltersConfig,
    KiwiCredentials,
    OriginConfig,
    SearchConfig,
    StorageConfig,
    _interpolate_env_vars,
    _walk_and_interpolate,
    load_config,
)


class TestEnvVarInterpolation:
    def test_interpolates_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "secret123")
        result = _interpolate_env_vars("${TEST_KEY}")
        assert result == "secret123"

    def test_interpolates_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "5432")
        result = _interpolate_env_vars("${HOST}:${PORT}")
        assert result == "localhost:5432"

    def test_raises_on_missing_var(self):
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_XYZ"):
            _interpolate_env_vars("${NONEXISTENT_VAR_XYZ}")

    def test_no_interpolation_needed(self):
        result = _interpolate_env_vars("plain-string")
        assert result == "plain-string"

    def test_lenient_mode_returns_empty_for_missing(self):
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        result = _interpolate_env_vars("${NONEXISTENT_VAR_XYZ}", lenient=True)
        assert result == ""

    def test_partial_string_with_env_var(self, monkeypatch):
        monkeypatch.setenv("DB_NAME", "flights")
        result = _interpolate_env_vars("postgres://localhost/${DB_NAME}")
        assert result == "postgres://localhost/flights"

    def test_empty_string(self):
        assert _interpolate_env_vars("") == ""

    def test_lenient_with_mixed_set_and_unset(self, monkeypatch):
        monkeypatch.setenv("SET_VAR", "hello")
        os.environ.pop("UNSET_VAR_XYZ", None)
        result = _interpolate_env_vars("${SET_VAR}:${UNSET_VAR_XYZ}", lenient=True)
        assert result == "hello:"

    def test_env_var_with_special_chars(self, monkeypatch):
        monkeypatch.setenv("SPECIAL_VAR", "p@ssw0rd!#$")
        result = _interpolate_env_vars("${SPECIAL_VAR}")
        assert result == "p@ssw0rd!#$"


class TestWalkAndInterpolate:
    def test_interpolates_string(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "value")
        result = _walk_and_interpolate("${MY_VAR}")
        assert result == "value"

    def test_interpolates_dict(self, monkeypatch):
        monkeypatch.setenv("KEY1", "val1")
        result = _walk_and_interpolate({"a": "${KEY1}", "b": "plain"})
        assert result == {"a": "val1", "b": "plain"}

    def test_interpolates_list(self, monkeypatch):
        monkeypatch.setenv("ITEM", "resolved")
        result = _walk_and_interpolate(["${ITEM}", "static"])
        assert result == ["resolved", "static"]

    def test_passthrough_for_non_string_non_collection(self):
        assert _walk_and_interpolate(42) == 42
        assert _walk_and_interpolate(3.14) == 3.14
        assert _walk_and_interpolate(True) is True
        assert _walk_and_interpolate(None) is None

    def test_nested_dict_with_list(self, monkeypatch):
        monkeypatch.setenv("VAL", "x")
        result = _walk_and_interpolate({"outer": {"inner": ["${VAL}"]}})
        assert result == {"outer": {"inner": ["x"]}}

    def test_disabled_email_section_uses_lenient(self, monkeypatch):
        os.environ.pop("SMTP_PASS_XYZ", None)
        data = {
            "email": {
                "enabled": False,
                "password": "${SMTP_PASS_XYZ}",
            },
            "other": "plain",
        }
        result = _walk_and_interpolate(data)
        assert result["email"]["password"] == ""
        assert result["other"] == "plain"

    def test_enabled_email_section_is_strict(self, monkeypatch):
        os.environ.pop("SMTP_PASS_XYZ", None)
        data = {
            "email": {
                "enabled": True,
                "password": "${SMTP_PASS_XYZ}",
            }
        }
        with pytest.raises(ValueError, match="SMTP_PASS_XYZ"):
            _walk_and_interpolate(data)

    def test_email_enabled_with_set_vars(self, monkeypatch):
        monkeypatch.setenv("SMTP_PASS", "secret")
        data = {
            "email": {
                "enabled": True,
                "password": "${SMTP_PASS}",
            }
        }
        result = _walk_and_interpolate(data)
        assert result["email"]["password"] == "secret"


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "test-key-123")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
provider: kiwi
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
    city: Bilbao
destinations:
  - name: Berlin
    airports: [BER]
"""
        )
        config = load_config(config_file)
        assert config.provider == "kiwi"
        assert config.credentials.kiwi is not None
        assert config.credentials.kiwi.api_key == "test-key-123"
        assert len(config.origins) == 1
        assert config.origins[0].code == "BIO"
        assert len(config.destinations) == 1
        assert config.destinations[0].airports == ["BER"]

    def test_uses_defaults_for_optional_sections(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
"""
        )
        config = load_config(config_file)
        assert config.search.date_range_days == 90
        assert config.filters.max_duration_minutes == 600
        assert config.analysis.deal_threshold_pct == 25.0
        assert config.reporting.format == "console"

    def test_raises_on_missing_required_field(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "key"
origins:
  - code: BIO
"""
        )
        with pytest.raises((ValueError, TypeError)):
            load_config(config_file)

    def test_disabled_email_ignores_unset_env_vars(self, tmp_path, monkeypatch):
        """Config with disabled email should not fail on unset SMTP_PASSWORD."""
        monkeypatch.setenv("KIWI_API_KEY", "key")
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
reporting:
  format: console
  email:
    enabled: false
    password: "${SMTP_PASSWORD}"
"""
        )
        config = load_config(config_file)
        assert config.reporting.email.enabled is False
        assert config.reporting.email.password == ""

    def test_raises_on_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_raises_on_non_mapping_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("just a scalar string\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(config_file)

    def test_loads_multiple_origins_and_destinations(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
    city: Bilbao
  - code: EAS
    city: San Sebastián
  - code: VIT
    city: Vitoria
destinations:
  - name: Berlin
    airports: [BER]
  - name: London
    airports: [LHR, LGW, STN]
  - name: New York
    airports: [JFK, EWR]
"""
        )
        config = load_config(config_file)
        assert len(config.origins) == 3
        assert len(config.destinations) == 3
        assert config.destinations[1].airports == ["LHR", "LGW", "STN"]

    def test_loads_custom_search_params(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
search:
  date_range_days: 60
  currency: USD
  adults: 2
  max_results_per_route: 100
"""
        )
        config = load_config(config_file)
        assert config.search.date_range_days == 60
        assert config.search.currency == "USD"
        assert config.search.adults == 2
        assert config.search.max_results_per_route == 100

    def test_loads_custom_filters(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
filters:
  prefer_direct: false
  max_stops: 2
  max_duration_minutes: 480
  departure_time_earliest: "07:00"
  departure_time_latest: "20:00"
  allowed_airlines: ["VY", "FR"]
  excluded_airlines: ["U2"]
"""
        )
        config = load_config(config_file)
        assert config.filters.prefer_direct is False
        assert config.filters.max_stops == 2
        assert config.filters.max_duration_minutes == 480
        assert config.filters.allowed_airlines == ["VY", "FR"]
        assert config.filters.excluded_airlines == ["U2"]

    def test_loads_custom_storage_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        db_path = str(tmp_path / "custom.db")
        config_file.write_text(
            f"""
credentials:
  kiwi:
    api_key: "${{KIWI_API_KEY}}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
storage:
  db_path: "{db_path}"
"""
        )
        config = load_config(config_file)
        assert config.storage.db_path == db_path

    def test_loads_html_reporting_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIWI_API_KEY", "key")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
reporting:
  format: html
  html_output_path: /tmp/my_report.html
"""
        )
        config = load_config(config_file)
        assert config.reporting.format == "html"
        assert config.reporting.html_output_path == "/tmp/my_report.html"


class TestAppConfig:
    def test_config_with_all_fields(self, sample_config: AppConfig):
        assert sample_config.provider == "kiwi"
        assert len(sample_config.origins) == 2
        assert len(sample_config.destinations) == 2

    def test_config_defaults(self):
        config = AppConfig(
            credentials=CredentialsConfig(kiwi=KiwiCredentials(api_key="k")),
            origins=[OriginConfig(code="BIO")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
        )
        assert config.provider == "kiwi"
        assert config.search.date_range_days == 90
        assert config.filters.max_stops == 1
        assert config.analysis.deal_threshold_pct == 25.0
        assert config.storage.db_path == "~/.flight_monitor/prices.db"
        assert config.reporting.format == "console"

    def test_email_config_defaults(self):
        email = EmailConfig()
        assert email.enabled is False
        assert email.smtp_port == 587
        assert email.recipients == []

    def test_filters_config_defaults(self):
        fc = FiltersConfig()
        assert fc.prefer_direct is True
        assert fc.max_stops == 1
        assert fc.max_duration_minutes == 600
        assert fc.departure_time_earliest == "06:00"
        assert fc.departure_time_latest == "22:00"
        assert fc.allowed_airlines == []
        assert fc.excluded_airlines == []

    def test_search_config_defaults(self):
        sc = SearchConfig()
        assert sc.date_range_days == 90
        assert sc.currency == "EUR"
        assert sc.adults == 1
        assert sc.flight_type == "oneway"
        assert sc.max_results_per_route == 50

    def test_storage_config_default_path(self):
        sc = StorageConfig()
        assert sc.db_path == "~/.flight_monitor/prices.db"

    def test_origin_config_defaults(self):
        oc = OriginConfig(code="BIO")
        assert oc.city == ""

    def test_destination_config(self):
        dc = DestinationConfig(name="London", airports=["LHR", "LGW"])
        assert dc.name == "London"
        assert len(dc.airports) == 2
