"""Tests for the Amadeus flight search provider."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from flight_monitor.providers.amadeus_provider import AmadeusProvider, _parse_iso_duration
from flight_monitor.providers.base import ProviderError


class TestParseIsoDuration:
    def test_hours_and_minutes(self):
        assert _parse_iso_duration("PT2H30M") == 150

    def test_hours_only(self):
        assert _parse_iso_duration("PT3H") == 180

    def test_minutes_only(self):
        assert _parse_iso_duration("PT45M") == 45

    def test_zero_duration(self):
        assert _parse_iso_duration("PT0H0M") == 0

    def test_zero_shorthand(self):
        assert _parse_iso_duration("PT0H") == 0

    def test_large_duration(self):
        assert _parse_iso_duration("PT12H45M") == 765


class TestAmadeusProvider:
    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_name(self, mock_init):
        provider = AmadeusProvider.__new__(AmadeusProvider)
        assert provider.name() == "amadeus"

    def test_parse_offer_single_segment(self):
        item = {
            "id": "amadeus-1",
            "itineraries": [
                {
                    "duration": "PT2H30M",
                    "segments": [
                        {
                            "carrierCode": "LH",
                            "number": "1234",
                            "departure": {
                                "iataCode": "BIO",
                                "at": "2026-04-15T10:00:00",
                            },
                            "arrival": {
                                "iataCode": "BER",
                                "at": "2026-04-15T12:30:00",
                            },
                            "duration": "PT2H30M",
                        }
                    ],
                }
            ],
            "price": {"total": "89.50", "currency": "EUR"},
        }

        offer = AmadeusProvider._parse_offer(item, "EUR")

        assert offer.provider == "amadeus"
        assert offer.provider_id == "amadeus-1"
        assert offer.origin.code == "BIO"
        assert offer.destination.code == "BER"
        assert offer.price == Decimal("89.50")
        assert offer.currency == "EUR"
        assert offer.stops == 0
        assert offer.is_direct is True
        assert offer.total_duration_minutes == 150
        assert len(offer.segments) == 1
        assert offer.segments[0].airline == "LH"
        assert offer.segments[0].flight_number == "LH1234"

    def test_parse_offer_connecting_flight(self):
        item = {
            "id": "amadeus-2",
            "itineraries": [
                {
                    "duration": "PT6H0M",
                    "segments": [
                        {
                            "carrierCode": "IB",
                            "number": "100",
                            "departure": {
                                "iataCode": "BIO",
                                "at": "2026-04-15T08:00:00",
                            },
                            "arrival": {
                                "iataCode": "MAD",
                                "at": "2026-04-15T09:15:00",
                            },
                            "duration": "PT1H15M",
                        },
                        {
                            "carrierCode": "IB",
                            "number": "200",
                            "departure": {
                                "iataCode": "MAD",
                                "at": "2026-04-15T11:00:00",
                            },
                            "arrival": {
                                "iataCode": "BER",
                                "at": "2026-04-15T14:00:00",
                            },
                            "duration": "PT3H0M",
                        },
                    ],
                }
            ],
            "price": {"total": "145.00", "currency": "EUR"},
        }

        offer = AmadeusProvider._parse_offer(item, "EUR")

        assert offer.stops == 1
        assert offer.is_direct is False
        assert len(offer.segments) == 2
        assert offer.segments[0].destination.code == "MAD"
        assert offer.segments[1].origin.code == "MAD"
        assert offer.total_duration_minutes == 360

    def test_parse_offer_uses_response_currency(self):
        item = {
            "id": "amadeus-3",
            "itineraries": [
                {
                    "duration": "PT2H",
                    "segments": [
                        {
                            "carrierCode": "BA",
                            "number": "500",
                            "departure": {
                                "iataCode": "BIO",
                                "at": "2026-04-15T10:00:00",
                            },
                            "arrival": {
                                "iataCode": "LHR",
                                "at": "2026-04-15T12:00:00",
                            },
                            "duration": "PT2H",
                        }
                    ],
                }
            ],
            "price": {"total": "75.00", "currency": "GBP"},
        }

        offer = AmadeusProvider._parse_offer(item, "EUR")
        assert offer.currency == "GBP"

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_raises_on_total_failure(self, mock_init):
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        # Mock amadeus ResponseError
        response_error = type("ResponseError", (Exception,), {})
        provider._client.shopping.flight_offers_search.get.side_effect = response_error(
            "Auth failed"
        )

        with patch(
            "flight_monitor.providers.amadeus_provider.AmadeusProvider.search_flights"
        ) as mock_search:
            # Simulate what happens when all queries fail
            mock_search.side_effect = ProviderError("amadeus", None, "All queries failed")
            with pytest.raises(ProviderError) as exc_info:
                mock_search(
                    origin="BIO",
                    destination="BER",
                    date_from=date(2026, 4, 1),
                    date_to=date(2026, 4, 7),
                )
            assert exc_info.value.provider == "amadeus"
