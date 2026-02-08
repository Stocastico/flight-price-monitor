"""Tests for the Amadeus flight search provider."""

from __future__ import annotations

import sys
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

    def test_no_hours_no_minutes(self):
        """Duration string with no H or M should return 0."""
        assert _parse_iso_duration("PT") == 0

    def test_single_digit_values(self):
        assert _parse_iso_duration("PT1H5M") == 65

    def test_double_digit_minutes(self):
        assert _parse_iso_duration("PT0H59M") == 59


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

    def test_parse_offer_without_currency_in_response(self):
        """When response has no currency, use the requested one."""
        item = {
            "id": "amadeus-4",
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
            "price": {"total": "75.00"},
        }

        offer = AmadeusProvider._parse_offer(item, "EUR")
        assert offer.currency == "EUR"

    def test_parse_offer_missing_id(self):
        """Offer without id should still parse (defaults to empty)."""
        item = {
            "itineraries": [
                {
                    "duration": "PT2H",
                    "segments": [
                        {
                            "carrierCode": "LH",
                            "number": "100",
                            "departure": {"iataCode": "BIO", "at": "2026-04-15T10:00:00"},
                            "arrival": {"iataCode": "BER", "at": "2026-04-15T12:00:00"},
                            "duration": "PT2H",
                        }
                    ],
                }
            ],
            "price": {"total": "100.00", "currency": "EUR"},
        }
        offer = AmadeusProvider._parse_offer(item, "EUR")
        assert offer.provider_id == ""

    def test_parse_offer_missing_segment_duration(self):
        """Segment without duration should default to PT0H."""
        item = {
            "id": "amadeus-5",
            "itineraries": [
                {
                    "duration": "PT2H",
                    "segments": [
                        {
                            "carrierCode": "LH",
                            "number": "100",
                            "departure": {"iataCode": "BIO", "at": "2026-04-15T10:00:00"},
                            "arrival": {"iataCode": "BER", "at": "2026-04-15T12:00:00"},
                        }
                    ],
                }
            ],
            "price": {"total": "100.00", "currency": "EUR"},
        }
        offer = AmadeusProvider._parse_offer(item, "EUR")
        assert offer.segments[0].duration_minutes == 0

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_iterates_in_7_day_steps(self, mock_init):
        """search_flights should iterate from date_from to date_to in 7-day steps."""
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        mock_response = MagicMock()
        mock_response.data = []
        provider._client.shopping.flight_offers_search.get.return_value = mock_response

        # Mock the amadeus ResponseError so the import inside search_flights works
        mock_amadeus = MagicMock()
        mock_amadeus.ResponseError = type("ResponseError", (Exception,), {})
        with patch.dict(sys.modules, {"amadeus": mock_amadeus}):
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 22),  # 22 days = 4 queries (1, 8, 15, 22)
            )

        assert provider._client.shopping.flight_offers_search.get.call_count == 4

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_partial_failure(self, mock_init):
        """Some queries fail but not all -> should return results from successful ones."""
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        mock_amadeus = MagicMock()
        response_error = type("ResponseError", (Exception,), {})
        mock_amadeus.ResponseError = response_error

        # First call succeeds, second fails
        success_response = MagicMock()
        success_response.data = [
            {
                "id": "a1",
                "itineraries": [
                    {
                        "duration": "PT2H",
                        "segments": [
                            {
                                "carrierCode": "LH",
                                "number": "100",
                                "departure": {"iataCode": "BIO", "at": "2026-04-01T10:00:00"},
                                "arrival": {"iataCode": "BER", "at": "2026-04-01T12:00:00"},
                                "duration": "PT2H",
                            }
                        ],
                    }
                ],
                "price": {"total": "89.00", "currency": "EUR"},
            }
        ]

        provider._client.shopping.flight_offers_search.get.side_effect = [
            success_response,
            response_error("Server error"),
        ]

        with patch.dict(sys.modules, {"amadeus": mock_amadeus}):
            offers = provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 8),  # 2 queries
            )

        assert len(offers) == 1
        assert offers[0].price == Decimal("89.00")

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_all_fail_raises_provider_error(self, mock_init):
        """When all queries fail, should raise ProviderError."""
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        mock_amadeus = MagicMock()
        response_error = type("ResponseError", (Exception,), {})
        mock_amadeus.ResponseError = response_error

        provider._client.shopping.flight_offers_search.get.side_effect = response_error(
            "Auth failed"
        )

        with (
            patch.dict(sys.modules, {"amadeus": mock_amadeus}),
            pytest.raises(ProviderError) as exc_info,
        ):
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 7),
            )

        assert exc_info.value.provider == "amadeus"
        assert "All" in str(exc_info.value)

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_filters_by_max_stopovers(self, mock_init):
        """Offers with more stops than max_stopovers should be excluded."""
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        mock_amadeus = MagicMock()
        mock_amadeus.ResponseError = type("ResponseError", (Exception,), {})

        mock_response = MagicMock()
        mock_response.data = [
            {
                "id": "a1",
                "itineraries": [
                    {
                        "duration": "PT6H",
                        "segments": [
                            {
                                "carrierCode": "IB",
                                "number": "100",
                                "departure": {"iataCode": "BIO", "at": "2026-04-01T08:00:00"},
                                "arrival": {"iataCode": "MAD", "at": "2026-04-01T09:00:00"},
                                "duration": "PT1H",
                            },
                            {
                                "carrierCode": "IB",
                                "number": "200",
                                "departure": {"iataCode": "MAD", "at": "2026-04-01T11:00:00"},
                                "arrival": {"iataCode": "BER", "at": "2026-04-01T14:00:00"},
                                "duration": "PT3H",
                            },
                        ],
                    }
                ],
                "price": {"total": "145.00", "currency": "EUR"},
            }
        ]
        provider._client.shopping.flight_offers_search.get.return_value = mock_response

        with patch.dict(sys.modules, {"amadeus": mock_amadeus}):
            # max_stopovers=0 should filter out the 1-stop offer
            offers = provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 1),
                max_stopovers=0,
            )

        assert len(offers) == 0

    @patch("flight_monitor.providers.amadeus_provider.AmadeusProvider.__init__", return_value=None)
    def test_search_results_sorted_by_price(self, mock_init):
        """Results should be sorted by price ascending."""
        provider = AmadeusProvider.__new__(AmadeusProvider)
        provider._client = MagicMock()

        mock_amadeus = MagicMock()
        mock_amadeus.ResponseError = type("ResponseError", (Exception,), {})

        def make_item(offer_id, price):
            return {
                "id": offer_id,
                "itineraries": [
                    {
                        "duration": "PT2H",
                        "segments": [
                            {
                                "carrierCode": "LH",
                                "number": "100",
                                "departure": {"iataCode": "BIO", "at": "2026-04-01T10:00:00"},
                                "arrival": {"iataCode": "BER", "at": "2026-04-01T12:00:00"},
                                "duration": "PT2H",
                            }
                        ],
                    }
                ],
                "price": {"total": str(price), "currency": "EUR"},
            }

        mock_response = MagicMock()
        mock_response.data = [make_item("a1", 200), make_item("a2", 100), make_item("a3", 150)]
        provider._client.shopping.flight_offers_search.get.return_value = mock_response

        with patch.dict(sys.modules, {"amadeus": mock_amadeus}):
            offers = provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 1),
            )

        assert offers[0].price == Decimal("100")
        assert offers[1].price == Decimal("150")
        assert offers[2].price == Decimal("200")

    def test_import_error_without_amadeus_package(self):
        """AmadeusProvider should raise ImportError if amadeus package missing."""
        with (
            patch.dict(sys.modules, {"amadeus": None}),
            pytest.raises(ImportError, match="amadeus"),
        ):
            AmadeusProvider(client_id="id", client_secret="secret")
