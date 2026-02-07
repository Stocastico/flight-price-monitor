"""Tests for configuration loading and validation."""

from __future__ import annotations

import os

import pytest

from flight_monitor.config import AppConfig, _interpolate_env_vars, load_config


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
        # Ensure the var doesn't exist
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


class TestAppConfig:
    def test_config_with_all_fields(self, sample_config: AppConfig):
        assert sample_config.provider == "kiwi"
        assert len(sample_config.origins) == 2
        assert len(sample_config.destinations) == 2
