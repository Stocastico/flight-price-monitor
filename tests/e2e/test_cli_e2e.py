"""End-to-end CLI tests using recorded HTTP fixtures.

Exercises the full CLI flow: validate -> run -> purge via CliRunner
with real config files and mocked HTTP responses.
"""

from __future__ import annotations

from pathlib import Path

import responses
from click.testing import CliRunner

from flight_monitor.cli import cli

from .conftest import register_kiwi_routes


class TestCliValidateRunPurge:
    """Full CLI lifecycle: validate config, run search, purge old records."""

    def _write_config(self, tmp_path: Path) -> Path:
        config_file = tmp_path / "e2e_config.yaml"
        db_path = str(tmp_path / "e2e.db")
        config_file.write_text(
            f"""\
provider: kiwi
credentials:
  kiwi:
    api_key: "e2e-test-key"
origins:
  - code: BIO
    city: Bilbao
destinations:
  - name: Berlin
    airports: [BER]
search:
  date_range_days: 30
  max_results_per_route: 10
filters:
  max_stops: 1
analysis:
  min_history_count: 3
storage:
  db_path: "{db_path}"
"""
        )
        return config_file

    def test_validate_then_run_then_purge(self, tmp_path):
        config_file = self._write_config(tmp_path)
        runner = CliRunner()

        # Step 1: validate
        result = runner.invoke(cli, ["-c", str(config_file), "validate"])
        assert result.exit_code == 0
        assert "Configuration is valid" in result.output
        assert "kiwi" in result.output
        assert "BIO" in result.output

        # Step 2: run (with recorded HTTP)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://tequila-api.kiwi.com/v2/search",
                json={
                    "search_id": "cli-e2e",
                    "data": [
                        {
                            "id": "cli-1",
                            "price": 99,
                            "deep_link": "https://example.com",
                            "route": [
                                {
                                    "airline": "VY",
                                    "flight_no": 1234,
                                    "flyFrom": "BIO",
                                    "flyTo": "BER",
                                    "cityFrom": "Bilbao",
                                    "cityTo": "Berlin",
                                    "local_departure": "2026-05-10T10:00:00.000Z",
                                    "local_arrival": "2026-05-10T13:00:00.000Z",
                                }
                            ],
                        }
                    ],
                    "currency": "EUR",
                },
                status=200,
            )
            result = runner.invoke(cli, ["-c", str(config_file), "run"])

        # No deals on cold start, exit code 1
        assert result.exit_code == 1
        assert "0 deal(s) found" in result.output

        # Step 3: purge
        result = runner.invoke(cli, ["-c", str(config_file), "purge", "--days", "365"])
        assert result.exit_code == 0
        assert "Purged" in result.output

    @responses.activate
    def test_run_with_verbose_flag(self, tmp_path):
        config_file = self._write_config(tmp_path)
        runner = CliRunner()

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        result = runner.invoke(cli, ["-c", str(config_file), "--verbose", "run"])
        # Should complete without error (exit 1 = no deals, which is OK)
        assert result.exit_code in (0, 1)
        assert "deal(s) found" in result.output


class TestCliRunWithDeals:
    """CLI run that finds deals (seeded history)."""

    def _write_config(self, tmp_path: Path) -> Path:
        config_file = tmp_path / "e2e_config.yaml"
        db_path = str(tmp_path / "e2e.db")
        config_file.write_text(
            f"""\
provider: kiwi
credentials:
  kiwi:
    api_key: "e2e-test-key"
origins:
  - code: BIO
    city: Bilbao
destinations:
  - name: Berlin
    airports: [BER]
search:
  date_range_days: 30
analysis:
  min_history_count: 3
storage:
  db_path: "{db_path}"
"""
        )
        return config_file

    @responses.activate
    def test_run_finds_deals_and_exits_zero(self, tmp_path):
        config_file = self._write_config(tmp_path)
        db_path = str(tmp_path / "e2e.db")

        # Seed history with high prices
        from decimal import Decimal

        from flight_monitor.models import Airport, FlightOffer, FlightSegment
        from flight_monitor.storage.database import PriceDatabase

        db = PriceDatabase(db_path)
        for i, price in enumerate([200, 210, 190, 205, 195]):
            from datetime import datetime

            dep = datetime(2026, 3, 1 + i, 10, 0)
            arr = datetime(2026, 3, 1 + i, 13, 0)
            seg = FlightSegment(
                airline="XX",
                flight_number=f"XX{i}",
                origin=Airport(code="BIO"),
                destination=Airport(code="BER"),
                departure_time=dep,
                arrival_time=arr,
                duration_minutes=180,
            )
            offer = FlightOffer(
                provider="kiwi",
                provider_id=f"seed-{i}",
                origin=seg.origin,
                destination=seg.destination,
                segments=[seg],
                departure_time=dep,
                arrival_time=arr,
                total_duration_minutes=180,
                stops=0,
                price=Decimal(str(price)),
                currency="EUR",
            )
            db.record_offers([offer])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(config_file), "run"])

        # Should find deals: 79 EUR vs avg ~200 EUR
        assert result.exit_code == 0
        assert "deal(s) found" in result.output
        # Should show at least 1 deal
        assert "1 deal" in result.output or "2 deal" in result.output or "3 deal" in result.output


class TestCliWithMultiAirportDestination:
    """CLI with a destination having multiple airports."""

    @responses.activate
    def test_multi_airport_comma_separated(self, tmp_path):
        config_file = tmp_path / "e2e_config.yaml"
        db_path = str(tmp_path / "e2e.db")
        config_file.write_text(
            f"""\
provider: kiwi
credentials:
  kiwi:
    api_key: "e2e-test-key"
origins:
  - code: BIO
    city: Bilbao
destinations:
  - name: Italy
    airports: [BGY, MXP, LIN]
search:
  date_range_days: 30
storage:
  db_path: "{db_path}"
"""
        )

        # Kiwi should receive fly_to=BGY,MXP,LIN as a single call
        responses.add(
            responses.GET,
            "https://tequila-api.kiwi.com/v2/search",
            json={
                "search_id": "multi-apt",
                "data": [
                    {
                        "id": "multi-1",
                        "price": 55,
                        "route": [
                            {
                                "airline": "FR",
                                "flight_no": 1234,
                                "flyFrom": "BIO",
                                "flyTo": "BGY",
                                "cityFrom": "Bilbao",
                                "cityTo": "Bergamo",
                                "local_departure": "2026-05-10T10:00:00.000Z",
                                "local_arrival": "2026-05-10T12:00:00.000Z",
                            }
                        ],
                    }
                ],
                "currency": "EUR",
            },
            status=200,
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(config_file), "run"])
        assert result.exit_code in (0, 1)

        # Verify the fly_to param was comma-separated
        assert len(responses.calls) == 1
        assert "BGY%2CMXP%2CLIN" in responses.calls[0].request.url or \
            "BGY,MXP,LIN" in responses.calls[0].request.url


class TestCliErrorHandling:
    """CLI handles API errors gracefully."""

    @responses.activate
    def test_api_error_exits_with_code_1(self, tmp_path):
        config_file = tmp_path / "e2e_config.yaml"
        db_path = str(tmp_path / "e2e.db")
        config_file.write_text(
            f"""\
provider: kiwi
credentials:
  kiwi:
    api_key: "e2e-test-key"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
storage:
  db_path: "{db_path}"
"""
        )

        responses.add(
            responses.GET,
            "https://tequila-api.kiwi.com/v2/search",
            json={"error": "Unauthorized"},
            status=401,
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(config_file), "run"])
        # Should handle the error and exit with code 1 (no deals)
        assert result.exit_code == 1
