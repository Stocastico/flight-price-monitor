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
