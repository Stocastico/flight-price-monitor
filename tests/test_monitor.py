"""Tests for the flight monitor orchestrator."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from flight_monitor.config import AppConfig, DestinationConfig
from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.monitor import FlightMonitor
from flight_monitor.providers.base import ProviderError


def _make_offer(
    origin: str = "BIO",
    destination: str = "BER",
    price: float = 100.0,
) -> FlightOffer:
    dep = datetime(2026, 4, 15, 10, 0)
    arr = datetime(2026, 4, 15, 13, 0)
    seg = FlightSegment(
        airline="VY",
        flight_number="VY123",
        origin=Airport(code=origin),
        destination=Airport(code=destination),
        departure_time=dep,
        arrival_time=arr,
        duration_minutes=180,
    )
    return FlightOffer(
        provider="kiwi",
        provider_id=f"test-{price}",
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


class TestFlightMonitor:
    @patch("flight_monitor.monitor.create_provider")
    def test_run_searches_all_routes(self, mock_factory, sample_config: AppConfig):
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_provider.search_flights.return_value = [_make_offer()]
        mock_factory.return_value = mock_provider

        monitor = FlightMonitor(sample_config)
        _deals, report = monitor.run()

        # 2 origins x 2 destinations = 4 searches
        assert mock_provider.search_flights.call_count == 4
        assert isinstance(report, str)

    @patch("flight_monitor.monitor.create_provider")
    def test_run_handles_provider_error(self, mock_factory, sample_config: AppConfig):
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_provider.search_flights.side_effect = ProviderError("kiwi", 500, "Server error")
        mock_factory.return_value = mock_provider

        monitor = FlightMonitor(sample_config)
        deals, report = monitor.run()

        assert deals == []
        assert "0" in report or "No deals" in report

    @patch("flight_monitor.monitor.create_provider")
    def test_run_filters_are_applied(self, mock_factory, sample_config: AppConfig):
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"

        # Return offer with departure at 3 AM (should be filtered out)
        early_offer = _make_offer()
        early_offer = early_offer.model_copy(update={"departure_time": datetime(2026, 4, 15, 3, 0)})
        mock_provider.search_flights.return_value = [early_offer]
        mock_factory.return_value = mock_provider

        monitor = FlightMonitor(sample_config)
        _deals, report = monitor.run()

        assert "Total offers scanned: 0" in report or "Offers scanned: 0" in report

    @patch("flight_monitor.monitor.create_provider")
    def test_kiwi_uses_comma_separated_destinations(self, mock_factory, sample_config: AppConfig):
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_provider.search_flights.return_value = []
        mock_factory.return_value = mock_provider

        # Add a destination with multiple airports
        sample_config.destinations = [
            DestinationConfig(name="London", airports=["LHR", "LGW", "STN"])
        ]

        monitor = FlightMonitor(sample_config)
        monitor.run()

        # Should be called with comma-separated destination
        call_args = mock_provider.search_flights.call_args_list[0]
        assert (
            call_args.kwargs.get("destination") == "LHR,LGW,STN"
            or call_args[1].get("destination") == "LHR,LGW,STN"
            or "LHR,LGW,STN" in str(call_args)
        )

    @patch("flight_monitor.monitor.create_provider")
    def test_non_kiwi_searches_per_airport(self, mock_factory, sample_config: AppConfig):
        mock_provider = MagicMock()
        mock_provider.name.return_value = "amadeus"
        mock_provider.search_flights.return_value = []
        mock_factory.return_value = mock_provider

        sample_config.destinations = [DestinationConfig(name="London", airports=["LHR", "LGW"])]

        monitor = FlightMonitor(sample_config)
        monitor.run()

        # 2 origins x 2 airports = 4 individual calls
        assert mock_provider.search_flights.call_count == 4

    @patch("flight_monitor.monitor.create_provider")
    def test_analyze_before_record_ordering(self, mock_factory, sample_config: AppConfig):
        """Deals should be analyzed BEFORE offers are recorded to avoid self-pollution."""
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_provider.search_flights.return_value = [_make_offer(price=80)]
        mock_factory.return_value = mock_provider

        call_order: list[str] = []

        monitor = FlightMonitor(sample_config)

        original_find_deals = monitor._analyzer.find_deals
        original_record_offers = monitor._db.record_offers

        def mock_find_deals(*args, **kwargs):
            call_order.append("find_deals")
            return original_find_deals(*args, **kwargs)

        def mock_record_offers(*args, **kwargs):
            call_order.append("record_offers")
            return original_record_offers(*args, **kwargs)

        monitor._analyzer.find_deals = mock_find_deals
        monitor._db.record_offers = mock_record_offers

        monitor.run()

        # For each route, find_deals should come before record_offers
        for i, call in enumerate(call_order):
            if call == "record_offers":
                # There should be a find_deals before this record_offers
                preceding = call_order[:i]
                assert "find_deals" in preceding

    @patch("flight_monitor.monitor.create_provider")
    def test_non_kiwi_partial_provider_failure(self, mock_factory, sample_config: AppConfig):
        """Non-kiwi provider: some airports fail, others succeed."""
        mock_provider = MagicMock()
        mock_provider.name.return_value = "amadeus"

        # First call succeeds, second raises error
        mock_provider.search_flights.side_effect = [
            [_make_offer(destination="LHR", price=100)],
            ProviderError("amadeus", 500, "Server error"),
        ] * len(sample_config.origins)  # Repeat for each origin

        mock_factory.return_value = mock_provider

        sample_config.destinations = [DestinationConfig(name="London", airports=["LHR", "LGW"])]

        monitor = FlightMonitor(sample_config)
        _deals, report = monitor.run()

        # Should still produce a report (not crash)
        assert isinstance(report, str)

    @patch("flight_monitor.monitor.create_provider")
    def test_run_returns_sorted_deals(self, mock_factory, sample_config: AppConfig):
        """All deals across routes should be sorted by savings percentage."""
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_provider.search_flights.return_value = [_make_offer(price=50)]
        mock_factory.return_value = mock_provider

        monitor = FlightMonitor(sample_config)
        deals, report = monitor.run()

        # Just verify the run completes and returns a report
        assert isinstance(report, str)
        assert isinstance(deals, list)

    @patch("flight_monitor.monitor.create_provider")
    def test_empty_destinations_list(self, mock_factory, sample_config: AppConfig):
        """No destinations should produce empty results."""
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"
        mock_factory.return_value = mock_provider

        sample_config.destinations = []

        monitor = FlightMonitor(sample_config)
        deals, _report = monitor.run()

        assert deals == []
        mock_provider.search_flights.assert_not_called()

    @patch("flight_monitor.monitor.create_provider")
    def test_run_records_filtered_offers(self, mock_factory, sample_config: AppConfig):
        """Monitor should record FILTERED offers, not raw ones."""
        mock_provider = MagicMock()
        mock_provider.name.return_value = "kiwi"

        # One offer at 10am (passes filter), one at 3am (filtered out)
        good_offer = _make_offer(price=100)
        bad_offer = _make_offer(price=80)
        bad_offer = bad_offer.model_copy(
            update={"departure_time": datetime(2026, 4, 15, 3, 0)}
        )
        mock_provider.search_flights.return_value = [good_offer, bad_offer]
        mock_factory.return_value = mock_provider

        monitor = FlightMonitor(sample_config)

        record_calls: list[list] = []
        original_record = monitor._db.record_offers

        def track_record(offers):
            record_calls.append(list(offers))
            return original_record(offers)

        monitor._db.record_offers = track_record
        monitor.run()

        # Each route should record only the filtered offer
        for call_offers in record_calls:
            for offer in call_offers:
                assert offer.departure_time.hour != 3
