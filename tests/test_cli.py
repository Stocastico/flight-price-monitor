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

    def test_purge_custom_days(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "purge", "--days", "30"])
        assert result.exit_code == 0
        assert "30 days" in result.output

    def test_purge_default_days(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "purge"])
        assert result.exit_code == 0
        assert "365 days" in result.output


class TestVerboseFlag:
    def test_verbose_flag_accepted(self, runner: CliRunner, valid_config_file: Path):
        """--verbose flag should be accepted before subcommand."""
        result = runner.invoke(cli, ["-c", str(valid_config_file), "--verbose", "validate"])
        assert result.exit_code == 0

    def test_short_verbose_flag(self, runner: CliRunner, valid_config_file: Path):
        """Short -v flag should work."""
        result = runner.invoke(cli, ["-c", str(valid_config_file), "-v", "validate"])
        assert result.exit_code == 0


class TestValidateCommandExtended:
    def test_validate_shows_route_count(self, runner: CliRunner, valid_config_file: Path):
        """Validate should display the number of route pairs."""
        result = runner.invoke(cli, ["-c", str(valid_config_file), "validate"])
        assert result.exit_code == 0
        assert "Routes:" in result.output

    def test_validate_shows_origins(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "validate"])
        assert "BIO" in result.output

    def test_validate_shows_destinations(self, runner: CliRunner, valid_config_file: Path):
        result = runner.invoke(cli, ["-c", str(valid_config_file), "validate"])
        assert "Berlin" in result.output or "BER" in result.output


class TestRunCommandExtended:
    @patch("flight_monitor.cli.FlightMonitor")
    def test_run_with_multiple_deals(
        self, mock_monitor_cls, runner: CliRunner, valid_config_file: Path
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = (["deal1", "deal2", "deal3"], "3 deals report")
        mock_monitor_cls.return_value = mock_instance

        result = runner.invoke(cli, ["-c", str(valid_config_file), "run"])
        assert result.exit_code == 0
        assert "3 deal(s) found" in result.output

    @patch("flight_monitor.cli.FlightMonitor")
    def test_run_console_format_echoes_report(
        self, mock_monitor_cls, runner: CliRunner, valid_config_file: Path
    ):
        """Console format should echo the full report."""
        mock_instance = MagicMock()
        mock_instance.run.return_value = (["deal1"], "=== Flight Monitor Report ===")
        mock_monitor_cls.return_value = mock_instance

        result = runner.invoke(cli, ["-c", str(valid_config_file), "run"])
        assert "Flight Monitor Report" in result.output


class TestTrendsCommand:
    def test_trends_empty_db(self, runner: CliRunner, valid_config_file: Path):
        """Trends with no history should say so."""
        result = runner.invoke(cli, ["-c", str(valid_config_file), "trends"])
        assert result.exit_code == 0
        assert "No price history" in result.output

    def test_trends_with_data(self, runner: CliRunner, valid_config_file: Path):
        """Trends should display route stats when data exists."""
        from decimal import Decimal

        from flight_monitor.config import load_config
        from flight_monitor.models import Airport, FlightOffer, FlightSegment
        from flight_monitor.storage.database import PriceDatabase

        config = load_config(str(valid_config_file))
        db = PriceDatabase(config.storage.db_path)
        from datetime import datetime

        for i, price in enumerate([100, 120, 90]):
            dep = datetime(2026, 4, 1 + i, 10, 0)
            seg = FlightSegment(
                airline="VY",
                flight_number=f"VY{i}",
                origin=Airport(code="BIO"),
                destination=Airport(code="BER"),
                departure_time=dep,
                arrival_time=dep.replace(hour=13),
                duration_minutes=180,
            )
            offer = FlightOffer(
                provider="kiwi",
                provider_id=f"trend-{i}",
                origin=seg.origin,
                destination=seg.destination,
                segments=[seg],
                departure_time=dep,
                arrival_time=dep.replace(hour=13),
                total_duration_minutes=180,
                stops=0,
                price=Decimal(str(price)),
                currency="EUR",
            )
            db.record_offers([offer])

        result = runner.invoke(cli, ["-c", str(valid_config_file), "trends"])
        assert result.exit_code == 0
        assert "BIO -> BER" in result.output
        assert "3 records" in result.output
        assert "Avg:" in result.output
        assert "Min:" in result.output

    def test_trends_route_filter(self, runner: CliRunner, valid_config_file: Path):
        """--route flag should filter to specific route."""
        result = runner.invoke(
            cli, ["-c", str(valid_config_file), "trends", "--route", "BIO-BER"]
        )
        assert result.exit_code == 0

    def test_trends_invalid_route_format(self, runner: CliRunner, valid_config_file: Path):
        """Invalid route format should show error."""
        result = runner.invoke(
            cli, ["-c", str(valid_config_file), "trends", "--route", "INVALID"]
        )
        assert result.exit_code == 1
        assert "Invalid route format" in result.output

    def test_trends_custom_days(self, runner: CliRunner, valid_config_file: Path):
        """--days flag should be accepted."""
        result = runner.invoke(
            cli, ["-c", str(valid_config_file), "trends", "--days", "30"]
        )
        assert result.exit_code == 0


class TestWatchCommand:
    def test_watch_no_routes_configured(self, runner: CliRunner, valid_config_file: Path):
        """Watch with no watch_routes should inform user."""
        result = runner.invoke(cli, ["-c", str(valid_config_file), "watch"])
        assert result.exit_code == 0
        assert "No watch_routes" in result.output

    def test_watch_with_routes(self, runner: CliRunner, tmp_path, monkeypatch):
        """Watch with routes should call provider and display results."""
        monkeypatch.setenv("KIWI_API_KEY", "test-key")
        db_path = str(tmp_path / "watch.db")
        config = tmp_path / "config.yaml"
        config.write_text(
            f"""
provider: kiwi
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
watch_routes:
  - origin: BIO
    destination: BER
    date: "2026-06-15"
    max_price: 100
"""
        )
        with patch("flight_monitor.cli.create_provider") as mock_cp:
            mock_provider = MagicMock()
            mock_provider.search_flights.return_value = []
            mock_cp.return_value = mock_provider

            result = runner.invoke(cli, ["-c", str(config), "watch"])
            assert result.exit_code == 0
            assert "BIO -> BER" in result.output
            assert "No offers found" in result.output

    def test_watch_flags_under_target_price(self, runner: CliRunner, tmp_path, monkeypatch):
        """Watch should flag offers under max_price."""
        from datetime import datetime
        from decimal import Decimal

        from flight_monitor.models import Airport, FlightOffer, FlightSegment

        monkeypatch.setenv("KIWI_API_KEY", "test-key")
        db_path = str(tmp_path / "watch.db")
        config = tmp_path / "config.yaml"
        config.write_text(
            f"""
provider: kiwi
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
watch_routes:
  - origin: BIO
    destination: BER
    date: "2026-06-15"
    max_price: 80
"""
        )

        dep = datetime(2026, 6, 15, 10, 0)
        seg = FlightSegment(
            airline="VY",
            flight_number="VY100",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            duration_minutes=180,
        )
        cheap_offer = FlightOffer(
            provider="kiwi",
            provider_id="watch-1",
            origin=seg.origin,
            destination=seg.destination,
            segments=[seg],
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("65"),
            currency="EUR",
        )

        with patch("flight_monitor.cli.create_provider") as mock_cp:
            mock_provider = MagicMock()
            mock_provider.search_flights.return_value = [cheap_offer]
            mock_cp.return_value = mock_provider

            result = runner.invoke(cli, ["-c", str(config), "watch"])
            assert result.exit_code == 0
            assert "EUR 65" in result.output
            assert "UNDER TARGET" in result.output
