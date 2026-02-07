"""Tests for the SQLite storage layer."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from flight_monitor.models import Airport, FlightOffer, FlightSegment, RouteKey
from flight_monitor.storage.database import PriceDatabase


def _make_offer(
    origin: str = "BIO",
    destination: str = "BER",
    price: float = 100.0,
    stops: int = 0,
    airline: str = "VY",
    departure: datetime | None = None,
    queried_at: datetime | None = None,
) -> FlightOffer:
    dep = departure or datetime(2026, 4, 15, 10, 0)
    arr = dep.replace(hour=dep.hour + 3)
    seg = FlightSegment(
        airline=airline,
        flight_number=f"{airline}123",
        origin=Airport(code=origin),
        destination=Airport(code=destination),
        departure_time=dep,
        arrival_time=arr,
        duration_minutes=180,
    )
    offer = FlightOffer(
        provider="kiwi",
        provider_id=f"offer-{price}-{origin}-{destination}",
        origin=seg.origin,
        destination=seg.destination,
        segments=[seg],
        departure_time=dep,
        arrival_time=arr,
        total_duration_minutes=180,
        stops=stops,
        price=Decimal(str(price)),
        currency="EUR",
    )
    if queried_at:
        offer = offer.model_copy(update={"queried_at": queried_at})
    return offer


class TestPriceDatabase:
    def test_record_and_retrieve_stats(self, sample_db: PriceDatabase):
        offers = [
            _make_offer(price=100),
            _make_offer(price=120),
            _make_offer(price=80),
        ]
        count = sample_db.record_offers(offers)
        assert count == 3

        route = RouteKey(origin_code="BIO", destination_code="BER")
        stats = sample_db.get_route_stats(route)
        assert stats.count == 3
        assert stats.avg_price == Decimal("100.0")
        assert stats.min_price == Decimal("80.0")
        assert stats.max_price == Decimal("120.0")

    def test_empty_route_stats(self, sample_db: PriceDatabase):
        route = RouteKey(origin_code="BIO", destination_code="XYZ")
        stats = sample_db.get_route_stats(route)
        assert stats.count == 0
        assert stats.avg_price == Decimal("0")

    def test_route_stats_with_max_stops_filter(self, sample_db: PriceDatabase):
        offers = [
            _make_offer(price=100, stops=0),
            _make_offer(price=200, stops=1),
            _make_offer(price=300, stops=2),
        ]
        sample_db.record_offers(offers)

        route = RouteKey(origin_code="BIO", destination_code="BER")

        # All offers
        stats_all = sample_db.get_route_stats(route)
        assert stats_all.count == 3

        # Direct only
        stats_direct = sample_db.get_route_stats(route, max_stops=0)
        assert stats_direct.count == 1
        assert stats_direct.avg_price == Decimal("100.0")

        # Up to 1 stop
        stats_one = sample_db.get_route_stats(route, max_stops=1)
        assert stats_one.count == 2

    def test_destination_group_stats(self, sample_db: PriceDatabase):
        offers = [
            _make_offer(destination="LHR", price=100),
            _make_offer(destination="LGW", price=120),
            _make_offer(destination="STN", price=80),
        ]
        sample_db.record_offers(offers)

        stats = sample_db.get_route_stats_for_destination_group(
            origin_code="BIO",
            destination_codes=["LHR", "LGW", "STN"],
        )
        assert stats.count == 3
        assert stats.avg_price == Decimal("100.0")
        assert stats.min_price == Decimal("80.0")

    def test_purge_old_records(self, sample_db: PriceDatabase):
        old_time = datetime.utcnow() - timedelta(days=400)
        recent_time = datetime.utcnow() - timedelta(days=30)

        offers_old = [_make_offer(price=100, queried_at=old_time)]
        offers_recent = [_make_offer(price=120, queried_at=recent_time)]

        sample_db.record_offers(offers_old)
        sample_db.record_offers(offers_recent)

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 2

        removed = sample_db.purge_old_records(older_than_days=365)
        assert removed == 1

        stats = sample_db.get_route_stats(route)
        assert stats.count == 1
        assert stats.avg_price == Decimal("120.0")

    def test_db_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "nested" / "dirs" / "test.db"
        db = PriceDatabase(db_path)
        db.record_offers([_make_offer()])
        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert db.get_route_stats(route).count == 1
