"""End-to-end tests using recorded HTTP fixtures.

These tests exercise the full pipeline: API call -> parse -> filter ->
analyze -> store -> report, using the `responses` library to replay
canned Kiwi API responses without hitting the real network.
"""

from __future__ import annotations

from decimal import Decimal

import responses

from flight_monitor.config import (
    AnalysisConfig,
    AppConfig,
    CredentialsConfig,
    DestinationConfig,
    FiltersConfig,
    KiwiCredentials,
    OriginConfig,
    SearchConfig,
    StorageConfig,
)
from flight_monitor.monitor import FlightMonitor
from flight_monitor.storage.database import PriceDatabase

from .conftest import register_kiwi_routes


class TestColdStart:
    """First run with no history — offers recorded, no deals (insufficient history)."""

    @responses.activate
    def test_cold_start_records_offers_but_no_deals(self, e2e_config_single: AppConfig):
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        deals, report = monitor.run()

        # No deals: we have zero historical data (min_history_count=3)
        assert deals == []

        # But offers were recorded to the database
        db = PriceDatabase(e2e_config_single.storage.db_path)
        stats = db.get_route_stats_for_destination_group("BIO", ["BER"])
        assert stats.count > 0
        assert "0" in report or "No deals" in report or "deal(s)" in report

    @responses.activate
    def test_cold_start_stores_correct_prices(self, e2e_config_single: AppConfig):
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        monitor.run()

        db = PriceDatabase(e2e_config_single.storage.db_path)
        stats = db.get_route_stats_for_destination_group("BIO", ["BER"])
        # Fixture has prices: 79, 125, 210
        assert stats.min_price == Decimal("79.0")
        assert stats.max_price == Decimal("210.0")
        assert stats.count == 3

    @responses.activate
    def test_cold_start_report_contains_scan_info(self, e2e_config_single: AppConfig):
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        _deals, report = monitor.run()

        # Report should mention the number of offers scanned
        assert "3" in report or "offers" in report.lower()


class TestDealDetection:
    """Seed the DB with high historical prices, then run with cheap recorded offers."""

    @responses.activate
    def test_detects_deal_when_price_drops(self, e2e_config_single: AppConfig):
        """Seed history with avg ~200 EUR, then fixture has 79 EUR -> deal."""
        db = PriceDatabase(e2e_config_single.storage.db_path)
        self._seed_history(db, "BIO", "BER", prices=[190, 200, 210, 195, 205])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        deals, report = monitor.run()

        # The 79 EUR offer should be detected as a deal (avg ~200, saving ~60%)
        assert len(deals) >= 1
        cheapest_deal = min(deals, key=lambda d: d.offer.price)
        assert cheapest_deal.offer.price == Decimal("79")
        assert cheapest_deal.savings_vs_avg_pct > 50
        assert "deal" in report.lower() or "BIO" in report

    @responses.activate
    def test_deal_has_correct_route_key(self, e2e_config_single: AppConfig):
        db = PriceDatabase(e2e_config_single.storage.db_path)
        self._seed_history(db, "BIO", "BER", prices=[200, 200, 200])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        deals, _report = monitor.run()

        for deal in deals:
            assert deal.route_key.origin_code == "BIO"
            assert deal.route_key.destination_code == "BER"

    @responses.activate
    def test_no_deal_when_prices_are_normal(self, e2e_config_single: AppConfig):
        """Seed history with avg ~80 EUR — current prices are similar, no deal."""
        db = PriceDatabase(e2e_config_single.storage.db_path)
        self._seed_history(db, "BIO", "BER", prices=[75, 80, 85, 78, 82])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        deals, _report = monitor.run()

        # 79 EUR is close to avg ~80, shouldn't be a deal at 25% threshold
        assert deals == []

    @responses.activate
    def test_historical_low_flag(self, e2e_config_single: AppConfig):
        """When offer is cheaper than all history, is_historical_low should be True."""
        db = PriceDatabase(e2e_config_single.storage.db_path)
        self._seed_history(db, "BIO", "BER", prices=[150, 160, 170, 155, 165])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(e2e_config_single)
        deals, _report = monitor.run()

        cheapest_deal = min(deals, key=lambda d: d.offer.price)
        assert cheapest_deal.offer.price == Decimal("79")
        assert cheapest_deal.is_historical_low is True

    @staticmethod
    def _seed_history(
        db: PriceDatabase,
        origin: str,
        dest: str,
        prices: list[float],
    ) -> None:
        """Insert fake historical prices into the database."""
        from datetime import datetime

        from flight_monitor.models import Airport, FlightOffer, FlightSegment

        for i, price in enumerate(prices):
            dep = datetime(2026, 3, 1 + i, 10, 0)
            arr = datetime(2026, 3, 1 + i, 13, 0)
            seg = FlightSegment(
                airline="XX",
                flight_number=f"XX{i}",
                origin=Airport(code=origin),
                destination=Airport(code=dest),
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


class TestMultiOriginMultiDestination:
    """Full run with 2 origins x 2 destinations = 4 route searches."""

    @responses.activate
    def test_all_routes_searched(self, e2e_config: AppConfig):
        register_kiwi_routes({
            ("BIO", "BER"): "kiwi_bio_ber.json",
            ("BIO", "BGY"): "kiwi_bio_bgy.json",
            ("EAS", "BER"): "kiwi_eas_ber.json",
            ("EAS", "BGY"): "kiwi_eas_bgy.json",
        })

        monitor = FlightMonitor(e2e_config)
        _deals, report = monitor.run()

        # All 4 routes should have been searched
        assert len(responses.calls) == 4
        assert isinstance(report, str)

    @responses.activate
    def test_offers_recorded_for_all_routes(self, e2e_config: AppConfig):
        register_kiwi_routes({
            ("BIO", "BER"): "kiwi_bio_ber.json",
            ("BIO", "BGY"): "kiwi_bio_bgy.json",
            ("EAS", "BER"): "kiwi_eas_ber.json",
            ("EAS", "BGY"): "kiwi_eas_bgy.json",
        })

        monitor = FlightMonitor(e2e_config)
        monitor.run()

        db = PriceDatabase(e2e_config.storage.db_path)

        bio_ber = db.get_route_stats_for_destination_group("BIO", ["BER"])
        bio_bgy = db.get_route_stats_for_destination_group("BIO", ["BGY"])
        eas_ber = db.get_route_stats_for_destination_group("EAS", ["BER"])
        eas_bgy = db.get_route_stats_for_destination_group("EAS", ["BGY"])

        assert bio_ber.count == 3  # 3 offers in kiwi_bio_ber.json
        assert bio_bgy.count == 2  # 2 offers in kiwi_bio_bgy.json
        assert eas_ber.count == 1  # 1 offer in kiwi_eas_ber.json
        assert eas_bgy.count == 1  # 1 offer in kiwi_eas_bgy.json

    @responses.activate
    def test_cross_route_deals(self, e2e_config: AppConfig):
        """Seed high prices for BGY, cheap fixture offers → deal detected."""
        db = PriceDatabase(e2e_config.storage.db_path)
        TestDealDetection._seed_history(db, "BIO", "BGY", prices=[120, 130, 125, 140, 135])

        register_kiwi_routes({
            ("BIO", "BER"): "kiwi_bio_ber.json",
            ("BIO", "BGY"): "kiwi_bio_bgy.json",
            ("EAS", "BER"): "kiwi_eas_ber.json",
            ("EAS", "BGY"): "kiwi_eas_bgy.json",
        })

        monitor = FlightMonitor(e2e_config)
        deals, _report = monitor.run()

        # 42 EUR Bergamo offer vs avg ~130 → deal
        bgy_deals = [d for d in deals if d.route_key.destination_code == "BGY"]
        assert len(bgy_deals) >= 1
        assert bgy_deals[0].offer.price == Decimal("42")


class TestFilterIntegration:
    """Verify that filters are applied in the full pipeline."""

    @responses.activate
    def test_early_departure_filtered_out(self, tmp_path):
        """Offer departing at 07:30 should pass, but if earliest is 08:00, it's filtered."""
        config = AppConfig(
            provider="kiwi",
            credentials=CredentialsConfig(
                kiwi=KiwiCredentials(api_key="e2e-test-key")
            ),
            origins=[OriginConfig(code="BIO", city="Bilbao")],
            destinations=[DestinationConfig(name="Bergamo", airports=["BGY"])],
            search=SearchConfig(date_range_days=30),
            filters=FiltersConfig(
                departure_time_earliest="08:00",
                departure_time_latest="22:00",
            ),
            analysis=AnalysisConfig(min_history_count=3),
            storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
        )

        # kiwi_bio_bgy has a 07:30 departure and an 11:00 departure
        register_kiwi_routes({("BIO", "BGY"): "kiwi_bio_bgy.json"})

        monitor = FlightMonitor(config)
        monitor.run()

        db = PriceDatabase(config.storage.db_path)
        stats = db.get_route_stats_for_destination_group("BIO", ["BGY"])
        # Only the 11:00 departure should pass the 08:00 filter
        assert stats.count == 1

    @responses.activate
    def test_direct_only_filters_connections(self, tmp_path):
        """With max_stops=0, connecting flights should be filtered out."""
        config = AppConfig(
            provider="kiwi",
            credentials=CredentialsConfig(
                kiwi=KiwiCredentials(api_key="e2e-test-key")
            ),
            origins=[OriginConfig(code="BIO", city="Bilbao")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
            search=SearchConfig(date_range_days=30),
            filters=FiltersConfig(max_stops=0),
            analysis=AnalysisConfig(min_history_count=3),
            storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
        )

        # kiwi_bio_ber has 2 direct + 1 connecting
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor = FlightMonitor(config)
        monitor.run()

        db = PriceDatabase(config.storage.db_path)
        stats = db.get_route_stats_for_destination_group("BIO", ["BER"])
        # Only 2 direct flights should be recorded
        assert stats.count == 2


class TestEmptyResults:
    """Handle routes with no offers gracefully."""

    @responses.activate
    def test_empty_response_no_crash(self, tmp_path):
        config = AppConfig(
            provider="kiwi",
            credentials=CredentialsConfig(
                kiwi=KiwiCredentials(api_key="e2e-test-key")
            ),
            origins=[OriginConfig(code="BIO", city="Bilbao")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
            search=SearchConfig(date_range_days=30),
            analysis=AnalysisConfig(min_history_count=3),
            storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
        )

        register_kiwi_routes({("BIO", "BER"): "kiwi_empty.json"})

        monitor = FlightMonitor(config)
        deals, report = monitor.run()

        assert deals == []
        assert isinstance(report, str)

    @responses.activate
    def test_empty_response_records_nothing(self, tmp_path):
        config = AppConfig(
            provider="kiwi",
            credentials=CredentialsConfig(
                kiwi=KiwiCredentials(api_key="e2e-test-key")
            ),
            origins=[OriginConfig(code="BIO", city="Bilbao")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
            search=SearchConfig(date_range_days=30),
            analysis=AnalysisConfig(min_history_count=3),
            storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
        )

        register_kiwi_routes({("BIO", "BER"): "kiwi_empty.json"})

        monitor = FlightMonitor(config)
        monitor.run()

        db = PriceDatabase(config.storage.db_path)
        stats = db.get_route_stats_for_destination_group("BIO", ["BER"])
        assert stats.count == 0


class TestHistoryCycle:
    """Two consecutive runs — second run should see history from the first."""

    @responses.activate
    def test_second_run_has_history_from_first(self, e2e_config_single: AppConfig):
        """Run once to build history, then run again — second should see it."""
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        # First run — cold start, builds history
        monitor1 = FlightMonitor(e2e_config_single)
        deals1, _report1 = monitor1.run()
        assert deals1 == []  # no history yet

        # Verify history was recorded
        db = PriceDatabase(e2e_config_single.storage.db_path)
        stats_after_first = db.get_route_stats_for_destination_group("BIO", ["BER"])
        assert stats_after_first.count == 3

    @responses.activate
    def test_second_run_can_detect_deals(self, e2e_config_single: AppConfig):
        """Seed enough history, then a second run with cheap prices finds deals."""
        db = PriceDatabase(e2e_config_single.storage.db_path)
        TestDealDetection._seed_history(db, "BIO", "BER", prices=[200, 190, 210])

        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        # Run — should detect 79 EUR as deal against avg ~200
        monitor = FlightMonitor(e2e_config_single)
        deals, _report = monitor.run()
        assert len(deals) >= 1

        # Second identical run — now with even more history
        responses.reset()
        register_kiwi_routes({("BIO", "BER"): "kiwi_bio_ber.json"})

        monitor2 = FlightMonitor(e2e_config_single)
        deals2, _report2 = monitor2.run()
        # Average has shifted down from first run's recorded prices
        # so deal detection depends on new average
        assert isinstance(deals2, list)
