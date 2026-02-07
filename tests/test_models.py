"""Tests for data models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flight_monitor.models import Airport, FlightOffer, FlightSegment, RouteKey


class TestAirport:
    def test_valid_airport(self):
        airport = Airport(code="BIO", city="Bilbao")
        assert airport.code == "BIO"
        assert airport.city == "Bilbao"

    def test_airport_code_must_be_uppercase(self):
        with pytest.raises(ValidationError):
            Airport(code="bio")

    def test_airport_code_must_be_three_chars(self):
        with pytest.raises(ValidationError):
            Airport(code="BI")
        with pytest.raises(ValidationError):
            Airport(code="BIOX")

    def test_airport_code_must_be_letters(self):
        with pytest.raises(ValidationError):
            Airport(code="B12")

    def test_airport_defaults(self):
        airport = Airport(code="BIO")
        assert airport.city == ""
        assert airport.country == ""


class TestFlightOffer:
    def test_direct_flight_is_direct(self, sample_offer: FlightOffer):
        assert sample_offer.is_direct is True
        assert sample_offer.stops == 0

    def test_connecting_flight_not_direct(self, connecting_offer: FlightOffer):
        assert connecting_offer.is_direct is False
        assert connecting_offer.stops == 1

    def test_price_is_decimal(self, sample_offer: FlightOffer):
        assert isinstance(sample_offer.price, Decimal)
        assert sample_offer.price == Decimal("89.00")

    def test_queried_at_defaults_to_now(self):
        before = datetime.utcnow()
        offer = FlightOffer(
            provider="test",
            provider_id="test-1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[
                FlightSegment(
                    airline="VY",
                    flight_number="VY1",
                    origin=Airport(code="BIO"),
                    destination=Airport(code="BER"),
                    departure_time=datetime(2026, 4, 15, 10, 0),
                    arrival_time=datetime(2026, 4, 15, 13, 0),
                    duration_minutes=180,
                )
            ],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
        )
        after = datetime.utcnow()
        assert before <= offer.queried_at <= after


class TestRouteKey:
    def test_route_key_is_hashable(self):
        r1 = RouteKey(origin_code="BIO", destination_code="BER")
        r2 = RouteKey(origin_code="BIO", destination_code="BER")
        assert hash(r1) == hash(r2)
        assert r1 == r2

    def test_different_routes_not_equal(self):
        r1 = RouteKey(origin_code="BIO", destination_code="BER")
        r2 = RouteKey(origin_code="BIO", destination_code="LHR")
        assert r1 != r2

    def test_route_key_usable_in_set(self):
        r1 = RouteKey(origin_code="BIO", destination_code="BER")
        r2 = RouteKey(origin_code="BIO", destination_code="BER")
        s = {r1, r2}
        assert len(s) == 1
