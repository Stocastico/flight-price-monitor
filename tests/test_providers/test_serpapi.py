"""Tests for the SerpAPI Google Flights provider."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import responses

from flight_monitor.providers.base import ProviderError
from flight_monitor.providers.serpapi_provider import SERPAPI_BASE_URL, SerpApiProvider


@pytest.fixture
def provider() -> SerpApiProvider:
    return SerpApiProvider(api_key="test-serpapi-key")


SAMPLE_RESPONSE = {
    "best_flights": [
        {
            "flights": [
                {
                    "departure_airport": {
                        "id": "BIO",
                        "name": "Bilbao Airport",
                        "time": "2026-04-15T10:30:00",
                    },
                    "arrival_airport": {
                        "id": "BER",
                        "name": "Berlin Brandenburg",
                        "time": "2026-04-15T13:45:00",
                    },
                    "duration": 195,
                    "airline": "VY",
                    "flight_number": "VY1234",
                }
            ],
            "total_duration": 195,
            "price": 89,
        }
    ],
    "other_flights": [
        {
            "flights": [
                {
                    "departure_airport": {
                        "id": "BIO",
                        "name": "Bilbao Airport",
                        "time": "2026-04-15T08:00:00",
                    },
                    "arrival_airport": {
                        "id": "MAD",
                        "name": "Madrid Barajas",
                        "time": "2026-04-15T09:15:00",
                    },
                    "duration": 75,
                    "airline": "IB",
                    "flight_number": "IB100",
                },
                {
                    "departure_airport": {
                        "id": "MAD",
                        "name": "Madrid Barajas",
                        "time": "2026-04-15T11:00:00",
                    },
                    "arrival_airport": {
                        "id": "BER",
                        "name": "Berlin Brandenburg",
                        "time": "2026-04-15T14:30:00",
                    },
                    "duration": 210,
                    "airline": "IB",
                    "flight_number": "IB200",
                },
            ],
            "total_duration": 390,
            "price": 145,
        }
    ],
}


class TestSerpApiProvider:
    def test_name(self, provider: SerpApiProvider):
        assert provider.name() == "serpapi"

    @responses.activate
    def test_search_flights_success(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json=SAMPLE_RESPONSE,
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        assert len(offers) == 2
        # First offer (sorted by price): direct BIO->BER at 89
        assert offers[0].price == Decimal("89")
        assert offers[0].origin.code == "BIO"
        assert offers[0].destination.code == "BER"
        assert offers[0].stops == 0
        assert offers[0].provider == "serpapi"

    @responses.activate
    def test_search_connecting_flight(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json=SAMPLE_RESPONSE,
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
        )

        connecting = offers[1]
        assert connecting.stops == 1
        assert connecting.price == Decimal("145")
        assert len(connecting.segments) == 2

    @responses.activate
    def test_search_empty_response(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={"best_flights": [], "other_flights": []},
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
    def test_search_api_error_status(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={"error": "Invalid API key"},
            status=401,
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.status_code == 401

    @responses.activate
    def test_search_api_error_in_body(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={"error": "No results found"},
            status=200,
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.search_flights(
                origin="BIO",
                destination="BER",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 6, 30),
            )

        assert exc_info.value.provider == "serpapi"

    @responses.activate
    def test_search_network_error(self, provider: SerpApiProvider):
        import requests

        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
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

    @responses.activate
    def test_search_max_stopovers_filter(self, provider: SerpApiProvider):
        """Connecting flights exceeding max_stopovers are excluded."""
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json=SAMPLE_RESPONSE,
            status=200,
        )

        offers = provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
            max_stopovers=0,
        )

        # Only the direct flight should pass
        assert len(offers) == 1
        assert offers[0].stops == 0

    @responses.activate
    def test_search_sends_oneway_type(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={"best_flights": [], "other_flights": []},
            status=200,
        )

        provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
            flight_type="oneway",
        )

        request = responses.calls[0].request
        assert "type=2" in request.url

    @responses.activate
    def test_search_sends_round_type(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={"best_flights": [], "other_flights": []},
            status=200,
        )

        provider.search_flights(
            origin="BIO",
            destination="BER",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 6, 30),
            flight_type="round",
        )

        request = responses.calls[0].request
        assert "type=1" in request.url
        assert "return_date=" in request.url

    @responses.activate
    def test_search_malformed_flight_skipped(self, provider: SerpApiProvider):
        responses.add(
            responses.GET,
            SERPAPI_BASE_URL,
            json={
                "best_flights": [
                    {"flights": [], "price": 50},  # Empty flights list
                ],
                "other_flights": [],
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


class TestSerpApiFactory:
    def test_factory_creates_serpapi_provider(self):
        from flight_monitor.config import (
            AppConfig,
            CredentialsConfig,
            DestinationConfig,
            OriginConfig,
            SerpApiCredentials,
        )
        from flight_monitor.providers.factory import create_provider

        config = AppConfig(
            provider="serpapi",
            credentials=CredentialsConfig(
                serpapi=SerpApiCredentials(api_key="test-key")
            ),
            origins=[OriginConfig(code="BIO")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
        )
        provider = create_provider(config)
        assert provider.name() == "serpapi"

    def test_factory_raises_without_credentials(self):
        from flight_monitor.config import (
            AppConfig,
            CredentialsConfig,
            DestinationConfig,
            OriginConfig,
        )
        from flight_monitor.providers.factory import create_provider

        config = AppConfig(
            provider="serpapi",
            credentials=CredentialsConfig(),
            origins=[OriginConfig(code="BIO")],
            destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
        )
        with pytest.raises(ValueError, match="SerpAPI credentials"):
            create_provider(config)
