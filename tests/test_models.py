"""Tests for data models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flight_monitor.models import Airport, Deal, FlightOffer, FlightSegment, RouteKey


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

    def test_airport_with_country(self):
        airport = Airport(code="JFK", city="New York", country="US")
        assert airport.country == "US"

    def test_airport_code_with_numbers_rejected(self):
        with pytest.raises(ValidationError):
            Airport(code="1AB")

    def test_airport_code_empty_string(self):
        with pytest.raises(ValidationError):
            Airport(code="")


class TestFlightSegment:
    def test_segment_creation(self, sample_segment):
        assert sample_segment.airline == "VY"
        assert sample_segment.flight_number == "VY1234"
        assert sample_segment.duration_minutes == 195

    def test_segment_origin_destination(self, sample_segment):
        assert sample_segment.origin.code == "BIO"
        assert sample_segment.destination.code == "BER"

    def test_segment_times(self, sample_segment):
        assert sample_segment.departure_time < sample_segment.arrival_time

    def test_segment_with_zero_duration(self):
        seg = FlightSegment(
            airline="VY",
            flight_number="VY1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 10, 0),
            duration_minutes=0,
        )
        assert seg.duration_minutes == 0

    def test_segment_negative_duration_allowed_by_model(self):
        """Model doesn't enforce positive duration - that's provider logic."""
        seg = FlightSegment(
            airline="VY",
            flight_number="VY1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            duration_minutes=-10,
        )
        assert seg.duration_minutes == -10


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
        before = datetime.now(UTC)
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
        after = datetime.now(UTC)
        assert before <= offer.queried_at <= after

    def test_currency_defaults_to_eur(self):
        offer = FlightOffer(
            provider="test",
            provider_id="t1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
        )
        assert offer.currency == "EUR"

    def test_deep_link_defaults_to_empty(self):
        offer = FlightOffer(
            provider="test",
            provider_id="t1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
        )
        assert offer.deep_link == ""

    def test_offer_with_multiple_stops(self):
        offer = FlightOffer(
            provider="test",
            provider_id="t1",
            origin=Airport(code="BIO"),
            destination=Airport(code="JFK"),
            segments=[],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 23, 0),
            total_duration_minutes=780,
            stops=2,
            price=Decimal("350"),
        )
        assert offer.is_direct is False
        assert offer.stops == 2

    def test_offer_model_copy_update(self, sample_offer):
        updated = sample_offer.model_copy(update={"price": Decimal("50.00")})
        assert updated.price == Decimal("50.00")
        assert sample_offer.price == Decimal("89.00")  # original unchanged

    def test_offer_with_different_currency(self):
        offer = FlightOffer(
            provider="test",
            provider_id="t1",
            origin=Airport(code="BIO"),
            destination=Airport(code="LHR"),
            segments=[],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("75.00"),
            currency="GBP",
        )
        assert offer.currency == "GBP"


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

    def test_route_key_is_immutable(self):
        rk = RouteKey(origin_code="BIO", destination_code="BER")
        with pytest.raises(ValidationError):
            rk.origin_code = "EAS"

    def test_route_key_usable_as_dict_key(self):
        rk = RouteKey(origin_code="BIO", destination_code="BER")
        d = {rk: "test_value"}
        assert d[RouteKey(origin_code="BIO", destination_code="BER")] == "test_value"

    def test_route_key_repr(self):
        rk = RouteKey(origin_code="BIO", destination_code="BER")
        r = repr(rk)
        assert "BIO" in r
        assert "BER" in r


class TestDeal:
    def test_deal_creation(self, sample_deal):
        assert sample_deal.savings_vs_avg_pct == 40.7
        assert sample_deal.is_historical_low is True
        assert sample_deal.historical_count == 10

    def test_deal_route_key(self, sample_deal):
        assert sample_deal.route_key.origin_code == "BIO"
        assert sample_deal.route_key.destination_code == "BER"

    def test_deal_savings_abs(self, sample_deal):
        assert sample_deal.savings_vs_avg_abs == Decimal("61.00")

    def test_deal_offer_access(self, sample_deal):
        assert sample_deal.offer.price == Decimal("89.00")
        assert sample_deal.offer.provider == "kiwi"

    def test_deal_not_historical_low(self, sample_offer):
        deal = Deal(
            offer=sample_offer,
            route_key=RouteKey(origin_code="BIO", destination_code="BER"),
            historical_avg_price=Decimal("150.00"),
            historical_min_price=Decimal("50.00"),
            historical_count=10,
            savings_vs_avg_pct=40.7,
            savings_vs_avg_abs=Decimal("61.00"),
            is_historical_low=False,
        )
        assert deal.is_historical_low is False

    def test_deal_with_zero_historical_count(self, sample_offer):
        deal = Deal(
            offer=sample_offer,
            route_key=RouteKey(origin_code="BIO", destination_code="BER"),
            historical_avg_price=Decimal("100.00"),
            historical_min_price=Decimal("100.00"),
            historical_count=0,
            savings_vs_avg_pct=11.0,
            savings_vs_avg_abs=Decimal("11.00"),
            is_historical_low=True,
        )
        assert deal.historical_count == 0
