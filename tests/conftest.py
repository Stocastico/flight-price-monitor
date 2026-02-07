"""Shared test fixtures for the flight monitor test suite."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from flight_monitor.config import (
    AnalysisConfig,
    AppConfig,
    CredentialsConfig,
    DestinationConfig,
    FiltersConfig,
    KiwiCredentials,
    OriginConfig,
    ReportingConfig,
    SearchConfig,
    StorageConfig,
)
from flight_monitor.models import Airport, Deal, FlightOffer, FlightSegment, RouteKey
from flight_monitor.storage.database import PriceDatabase


@pytest.fixture
def sample_segment() -> FlightSegment:
    return FlightSegment(
        airline="VY",
        flight_number="VY1234",
        origin=Airport(code="BIO", city="Bilbao"),
        destination=Airport(code="BER", city="Berlin"),
        departure_time=datetime(2026, 4, 15, 10, 30),
        arrival_time=datetime(2026, 4, 15, 13, 45),
        duration_minutes=195,
    )


@pytest.fixture
def sample_offer(sample_segment: FlightSegment) -> FlightOffer:
    return FlightOffer(
        provider="kiwi",
        provider_id="abc123",
        origin=sample_segment.origin,
        destination=sample_segment.destination,
        segments=[sample_segment],
        departure_time=sample_segment.departure_time,
        arrival_time=sample_segment.arrival_time,
        total_duration_minutes=195,
        stops=0,
        price=Decimal("89.00"),
        currency="EUR",
        deep_link="https://example.com/book",
    )


@pytest.fixture
def connecting_offer() -> FlightOffer:
    seg1 = FlightSegment(
        airline="IB",
        flight_number="IB5678",
        origin=Airport(code="BIO", city="Bilbao"),
        destination=Airport(code="MAD", city="Madrid"),
        departure_time=datetime(2026, 4, 15, 8, 0),
        arrival_time=datetime(2026, 4, 15, 9, 15),
        duration_minutes=75,
    )
    seg2 = FlightSegment(
        airline="IB",
        flight_number="IB9012",
        origin=Airport(code="MAD", city="Madrid"),
        destination=Airport(code="BER", city="Berlin"),
        departure_time=datetime(2026, 4, 15, 11, 0),
        arrival_time=datetime(2026, 4, 15, 14, 30),
        duration_minutes=210,
    )
    return FlightOffer(
        provider="kiwi",
        provider_id="def456",
        origin=seg1.origin,
        destination=seg2.destination,
        segments=[seg1, seg2],
        departure_time=seg1.departure_time,
        arrival_time=seg2.arrival_time,
        total_duration_minutes=390,
        stops=1,
        price=Decimal("145.00"),
        currency="EUR",
    )


@pytest.fixture
def sample_config(tmp_path) -> AppConfig:
    return AppConfig(
        provider="kiwi",
        credentials=CredentialsConfig(kiwi=KiwiCredentials(api_key="test-key")),
        origins=[
            OriginConfig(code="BIO", city="Bilbao"),
            OriginConfig(code="EAS", city="San Sebastián"),
        ],
        destinations=[
            DestinationConfig(name="Berlin", airports=["BER"]),
            DestinationConfig(name="Bergamo", airports=["BGY"]),
        ],
        search=SearchConfig(),
        filters=FiltersConfig(),
        analysis=AnalysisConfig(min_history_count=3),
        storage=StorageConfig(db_path=str(tmp_path / "test.db")),
        reporting=ReportingConfig(),
    )


@pytest.fixture
def sample_db(sample_config: AppConfig) -> PriceDatabase:
    return PriceDatabase(sample_config.storage.db_path)


@pytest.fixture
def sample_deal(sample_offer: FlightOffer) -> Deal:
    return Deal(
        offer=sample_offer,
        route_key=RouteKey(origin_code="BIO", destination_code="BER"),
        historical_avg_price=Decimal("150.00"),
        historical_min_price=Decimal("95.00"),
        historical_count=10,
        savings_vs_avg_pct=40.7,
        savings_vs_avg_abs=Decimal("61.00"),
        is_historical_low=True,
    )
