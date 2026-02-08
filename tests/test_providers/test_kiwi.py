"""Tests for the Kiwi Tequila flight search provider."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import responses

from flight_monitor.providers.base import ProviderError
from flight_monitor.providers.kiwi import KIWI_BASE_URL, KiwiProvider, _parse_kiwi_datetime

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def kiwi_response_data() -> dict:
    with open(FIXTURES_DIR / "kiwi_search_response.json") as f:
        return json.load(f)


@pytest.fixture
def provider() -> KiwiProvider:
    return KiwiProvider(api_key="test-api-key")


class TestParseKiwiDatetime:
    def test_parse_with_z_suffix(self):
        dt = _parse_kiwi_datetime("2026-04-15T10:30:00.000Z")
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.hour == 10
        assert dt.minute == 30

    def test_parse_without_z(self):
        dt = _parse_kiwi_datetime("2026-04-15T10:30:00")
        assert dt.hour == 10


class TestKiwiProvider:
    def test_name(self, provider: KiwiProvider):
        assert provider.name() == "kiwi"

    @responses.activate
    def test_search_flights_success(self, provider: KiwiProvider, kiwi_response_data: dict):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json=kiwi_response_data,
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert len(offers) == 3
        # First offer: direct BIO->BER
        assert offers[0].origin.code == "BIO"
        assert offers[0].destination.code == "BER"
        assert offers[0].price == Decimal("89")
        assert offers[0].stops == 0
        assert offers[0].is_direct is True
        assert offers[0].provider == "kiwi"
        assert offers[0].deep_link.startswith("https://")

    @responses.activate
    def test_search_flights_connecting(self, provider: KiwiProvider, kiwi_response_data: dict):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json=kiwi_response_data,
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        # Second offer has a connection via MAD
        connecting = offers[1]
        assert connecting.stops == 1
        assert connecting.is_direct is False
        assert len(connecting.segments) == 2
        assert connecting.segments[0].origin.code == "BIO"
        assert connecting.segments[0].destination.code == "MAD"
        assert connecting.segments[1].origin.code == "MAD"
        assert connecting.segments[1].destination.code == "BER"
        assert connecting.price == Decimal("145")

    @responses.activate
    def test_search_flights_empty_response(self, provider: KiwiProvider):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"data": []},
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="XYZ",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert offers == []

    @responses.activate
    def test_search_flights_api_error(self, provider: KiwiProvider):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"error": "Unauthorized"},
            status=403,
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.provider == "kiwi"

    @responses.activate
    def test_search_passes_nonstop_parameter(self, provider: KiwiProvider):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"data": []},
            status=200,
        )

        provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
            nonstop_only=True,
        )

        # Verify max_stopovers=0 was sent
        request = responses.calls[0].request
        assert "max_stopovers=0" in request.url

    @responses.activate
    def test_search_formats_dates_correctly(self, provider: KiwiProvider):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"data": []},
            status=200,
        )

        provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        request = responses.calls[0].request
        # Kiwi expects dd/mm/YYYY
        assert "date_from=01%2F04%2F2026" in request.url
        assert "date_to=30%2F06%2F2026" in request.url

    @responses.activate
    def test_search_handles_malformed_offer(self, provider: KiwiProvider):
        """Malformed offers should be skipped, not crash."""
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={
                "data": [
                    {"id": "bad-offer", "price": 50},  # Missing route
                    {
                        "id": "good-offer",
                        "price": 89,
                        "deep_link": "https://example.com",
                        "route": [
                            {
                                "airline": "VY",
                                "flight_no": 1,
                                "flyFrom": "BIO",
                                "flyTo": "BER",
                                "cityFrom": "Bilbao",
                                "cityTo": "Berlin",
                                "local_departure": "2026-04-15T10:30:00.000Z",
                                "local_arrival": "2026-04-15T13:45:00.000Z",
                            }
                        ],
                    },
                ]
            },
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert len(offers) == 1
        assert offers[0].provider_id == "good-offer"

    @responses.activate
    def test_search_network_error(self, provider: KiwiProvider):
        """Network error should raise ProviderError with no status code."""
        import requests

        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            body=requests.ConnectionError("Connection refused"),
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.status_code is None
        assert exc_info.value.provider == "kiwi"

    @responses.activate
    def test_search_timeout_error(self, provider: KiwiProvider):
        """Timeout should raise ProviderError."""
        import requests

        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            body=requests.Timeout("Request timed out"),
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.status_code is None

    @responses.activate
    def test_search_500_error(self, provider: KiwiProvider):
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"error": "Internal Server Error"},
            status=500,
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.status_code == 500

    @responses.activate
    def test_search_with_custom_parameters(self, provider: KiwiProvider):
        """Verify all parameters are passed to the API."""
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"data": []},
            status=200,
        )

        provider.search_flights(
            origin="BIO",
            destination="BER,BGY",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
            adults=2,
            currency="USD",
            max_stopovers=2,
            max_results=100,
        )

        request = responses.calls[0].request
        assert "adults=2" in request.url
        assert "curr=USD" in request.url
        assert "max_stopovers=2" in request.url
        assert "limit=100" in request.url
        # Comma-separated destinations
        assert "fly_to=BER%2CBGY" in request.url or "fly_to=BER,BGY" in request.url

    @responses.activate
    def test_search_empty_route_in_offer(self, provider: KiwiProvider):
        """Offer with empty route list should be skipped (IndexError caught)."""
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={
                "data": [
                    {
                        "id": "empty-route",
                        "price": 50,
                        "route": [],
                    },
                ]
            },
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert offers == []

    @responses.activate
    def test_search_missing_optional_fields(self, provider: KiwiProvider):
        """Offer without deep_link and optional city fields should still parse."""
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={
                "data": [
                    {
                        "id": "minimal-offer",
                        "price": 60,
                        "route": [
                            {
                                "airline": "FR",
                                "flight_no": 100,
                                "flyFrom": "BIO",
                                "flyTo": "BGY",
                                "local_departure": "2026-04-20T06:30:00",
                                "local_arrival": "2026-04-20T08:45:00",
                            }
                        ],
                    }
                ]
            },
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BGY",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert len(offers) == 1
        assert offers[0].deep_link == ""
        assert offers[0].segments[0].origin.city == ""

    @responses.activate
    def test_search_response_without_data_key(self, provider: KiwiProvider):
        """Response missing 'data' key should return empty list."""
        responses.add(
            responses.GET,
            f"{KIWI_BASE_URL}/v2/search",
            json={"search_id": "123"},
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert offers == []

    def test_parse_offer_third_offer_in_fixture(self, kiwi_response_data):
        """Parse the third offer (BIO->BGY direct) from fixture."""
        item = kiwi_response_data["data"][2]
        offer = KiwiProvider._parse_offer(item, "EUR")
        assert offer.origin.code == "BIO"
        assert offer.destination.code == "BGY"
        assert offer.price == Decimal("52")
        assert offer.stops == 0

    def test_provider_sets_api_key_header(self):
        """Verify API key is set in the session headers."""
        provider = KiwiProvider(api_key="my-secret-key")
        assert provider._session.headers["apikey"] == "my-secret-key"


class TestParseKiwiDatetimeExtended:
    def test_parse_with_explicit_timezone_offset(self):
        dt = _parse_kiwi_datetime("2026-04-15T10:30:00+02:00")
        assert dt.hour == 10
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_parse_with_negative_timezone_offset(self):
        dt = _parse_kiwi_datetime("2026-04-15T10:30:00-05:00")
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_parse_midnight(self):
        dt = _parse_kiwi_datetime("2026-04-15T00:00:00.000Z")
        assert dt.hour == 0
        assert dt.minute == 0
