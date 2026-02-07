"""Tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from flight_monitor.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def valid_config_file(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("KIWI_API_KEY", "test-key")
    config = tmp_path / "config.yaml"
    db_path = str(tmp_path / "test.db")
    config.write_text(
        f"""
provider: kiwi
credentials:
  kiwi:
    api_key: "${{KIWI_API_KEY}}"
origins:
  - code: BIO
    city: Bilbao
destinations:
  - name: Berlin
    airports: [BER]
storage:
  db_path: "{db_path}"
"""
    )
    return config


class TestValidateCommand:
    def test_validate_valid_config(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "validate"])
        assert result.exit_code == 0
        assert "Configuration is valid" in result.output
        assert "kiwi" in result.output

    def test_validate_nonexistent_config(self, runner: CliRunner, tmp_path):
        result = runner.invoke(cli, ["-c", str(tmp_path / "nonexistent.yaml"), "validate"])
        assert result.exit_code == 1

    def test_validate_invalid_config(self, runner: CliRunner, tmp_path):
        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text("invalid: true\n")
        result = runner.invoke(cli, ["-c", str(bad_config), "validate"])
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestRunCommand:
    def test_run_missing_config(self, runner: CliRunner, tmp_path):
        result = runner.invoke(cli, ["-c", str(tmp_path / "nonexistent.yaml"), "run"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    @patch("flight_monitor.cli.FlightMonitor")
    def test_run_with_deals(self, mock_monitor_cls, runner: CliRunner, valid_config_file: Path):
        mock_instance = MagicMock()
        mock_instance.run.return_value = (["deal1"], "Report with deals")
        mock_monitor_cls.return_value = mock_instance

        result = runner.invoke(cli, ["-c", str(valid_config_file), "run"])
        assert result.exit_code == 0
        assert "1 deal(s) found" in result.output

    @patch("flight_monitor.cli.FlightMonitor")
    def test_run_without_deals(self, mock_monitor_cls, runner: CliRunner, valid_config_file: Path):
        mock_instance = MagicMock()
        mock_instance.run.return_value = ([], "No deals")
        mock_monitor_cls.return_value = mock_instance

        result = runner.invoke(cli, ["-c", str(valid_config_file), "run"])
        assert result.exit_code == 1
        assert "0 deal(s) found" in result.output


class TestPurgeCommand:
    def test_purge(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "purge", "--days", "365"])
        assert result.exit_code == 0
        assert "Purged" in result.output
