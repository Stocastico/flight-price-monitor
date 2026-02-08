"""Tests for the SQLite storage layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
        old_time = datetime.now(UTC) - timedelta(days=400)
        recent_time = datetime.now(UTC) - timedelta(days=30)

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

    def test_empty_destination_codes_returns_zero_stats(self, sample_db: PriceDatabase):
        stats = sample_db.get_route_stats_for_destination_group(
            origin_code="BIO",
            destination_codes=[],
        )
        assert stats.count == 0
        assert stats.avg_price == Decimal("0")

    def test_record_empty_offers_list(self, sample_db: PriceDatabase):
        """Recording empty list should succeed and return 0."""
        count = sample_db.record_offers([])
        assert count == 0

    def test_record_offer_with_no_segments(self, sample_db: PriceDatabase):
        """Offer with empty segments list should record airline as ''."""
        dep = datetime(2026, 4, 15, 10, 0)
        offer = FlightOffer(
            provider="kiwi",
            provider_id="no-seg",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[],
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
            currency="EUR",
        )
        count = sample_db.record_offers([offer])
        assert count == 1

        route = RouteKey(origin_code="BIO", destination_code="BER")
        stats = sample_db.get_route_stats(route)
        assert stats.count == 1

    def test_schema_reinitialization(self, tmp_path):
        """Creating PriceDatabase twice on same path should not error."""
        db_path = tmp_path / "test.db"
        db1 = PriceDatabase(db_path)
        db1.record_offers([_make_offer(price=100)])

        # Re-open same database
        db2 = PriceDatabase(db_path)
        route = RouteKey(origin_code="BIO", destination_code="BER")
        stats = db2.get_route_stats(route)
        assert stats.count == 1

    def test_destination_group_with_max_stops(self, sample_db: PriceDatabase):
        """Group stats should filter by max_stops."""
        offers = [
            _make_offer(destination="LHR", price=100, stops=0),
            _make_offer(destination="LGW", price=200, stops=1),
            _make_offer(destination="STN", price=300, stops=2),
        ]
        sample_db.record_offers(offers)

        stats = sample_db.get_route_stats_for_destination_group(
            origin_code="BIO",
            destination_codes=["LHR", "LGW", "STN"],
            max_stops=0,
        )
        assert stats.count == 1
        assert stats.avg_price == Decimal("100.0")

    def test_destination_group_no_matching_records(self, sample_db: PriceDatabase):
        """Group stats with codes that have no records."""
        stats = sample_db.get_route_stats_for_destination_group(
            origin_code="BIO",
            destination_codes=["ZZZ", "YYY"],
        )
        assert stats.count == 0
        assert stats.avg_price == Decimal("0")

    def test_record_preserves_provider_info(self, sample_db: PriceDatabase):
        """Recorded offers should store provider and provider_id."""
        import sqlite3

        offer = _make_offer(price=100)
        sample_db.record_offers([offer])

        conn = sqlite3.connect(str(sample_db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT provider, provider_id FROM price_history").fetchone()
        conn.close()
        assert row["provider"] == "kiwi"
        assert "100" in row["provider_id"]

    def test_purge_preserves_recent_records(self, sample_db: PriceDatabase):
        """Purge should not touch records newer than cutoff."""
        recent_time = datetime.now(UTC) - timedelta(days=10)
        offers = [_make_offer(price=p, queried_at=recent_time) for p in [100, 120, 80]]
        sample_db.record_offers(offers)

        removed = sample_db.purge_old_records(older_than_days=365)
        assert removed == 0

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 3

    def test_purge_custom_days(self, sample_db: PriceDatabase):
        """Purge with custom days threshold."""
        old_time = datetime.now(UTC) - timedelta(days=50)
        sample_db.record_offers([_make_offer(price=100, queried_at=old_time)])
        sample_db.record_offers([_make_offer(price=120)])

        removed = sample_db.purge_old_records(older_than_days=30)
        assert removed == 1

    def test_multiple_routes_separate_stats(self, sample_db: PriceDatabase):
        """Stats for different routes should be independent."""
        sample_db.record_offers([
            _make_offer(origin="BIO", destination="BER", price=100),
            _make_offer(origin="BIO", destination="LHR", price=200),
        ])

        ber_stats = sample_db.get_route_stats(
            RouteKey(origin_code="BIO", destination_code="BER")
        )
        lhr_stats = sample_db.get_route_stats(
            RouteKey(origin_code="BIO", destination_code="LHR")
        )
        assert ber_stats.count == 1
        assert ber_stats.avg_price == Decimal("100.0")
        assert lhr_stats.count == 1
        assert lhr_stats.avg_price == Decimal("200.0")

    def test_route_stats_last_observed(self, sample_db: PriceDatabase):
        """Stats should include last_observed timestamp."""
        sample_db.record_offers([_make_offer(price=100)])
        route = RouteKey(origin_code="BIO", destination_code="BER")
        stats = sample_db.get_route_stats(route)
        assert stats.last_observed is not None


class TestDeduplication:
    """Tests for offer deduplication by provider_id."""

    def test_duplicate_provider_id_ignored(self, sample_db: PriceDatabase):
        """Recording the same provider_id twice should only store one record."""
        offer = _make_offer(price=100)
        assert sample_db.record_offers([offer]) == 1
        assert sample_db.record_offers([offer]) == 0

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 1

    def test_different_provider_ids_both_stored(self, sample_db: PriceDatabase):
        """Two offers with different provider_ids should both be stored."""
        offer1 = _make_offer(price=100)
        offer2 = _make_offer(price=120)
        assert sample_db.record_offers([offer1, offer2]) == 2

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 2

    def test_empty_provider_id_always_inserts(self, sample_db: PriceDatabase):
        """Offers with empty provider_id should always be inserted (no dedup)."""
        dep = datetime(2026, 4, 15, 10, 0)
        offer = FlightOffer(
            provider="kiwi",
            provider_id="",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[],
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
            currency="EUR",
        )
        assert sample_db.record_offers([offer]) == 1
        assert sample_db.record_offers([offer]) == 1

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 2

    def test_same_provider_id_different_providers_both_stored(self, sample_db: PriceDatabase):
        """Same provider_id from different providers should not collide."""
        dep = datetime(2026, 4, 15, 10, 0)
        seg = FlightSegment(
            airline="VY",
            flight_number="VY123",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            duration_minutes=180,
        )
        offer_kiwi = FlightOffer(
            provider="kiwi",
            provider_id="shared-id",
            origin=seg.origin,
            destination=seg.destination,
            segments=[seg],
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("100"),
            currency="EUR",
        )
        offer_amadeus = offer_kiwi.model_copy(update={"provider": "amadeus"})

        assert sample_db.record_offers([offer_kiwi]) == 1
        assert sample_db.record_offers([offer_amadeus]) == 1

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 2

    def test_batch_with_duplicates_returns_new_count(self, sample_db: PriceDatabase):
        """A batch containing a duplicate should count only new inserts."""
        offer_a = _make_offer(price=100)
        offer_b = _make_offer(price=120)

        assert sample_db.record_offers([offer_a]) == 1
        # Batch: offer_a is duplicate, offer_b is new
        assert sample_db.record_offers([offer_a, offer_b]) == 1

        route = RouteKey(origin_code="BIO", destination_code="BER")
        assert sample_db.get_route_stats(route).count == 2

    def test_dedup_preserves_first_price(self, sample_db: PriceDatabase):
        """First recorded price should be kept, duplicate ignored."""
        import sqlite3

        offer = _make_offer(price=100)
        sample_db.record_offers([offer])

        # "Updated" offer with different price but same provider_id
        updated = offer.model_copy(update={"price": Decimal("50")})
        sample_db.record_offers([updated])

        conn = sqlite3.connect(str(sample_db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT price FROM price_history").fetchone()
        conn.close()
        assert row["price"] == 100.0


class TestGetAllRoutes:
    """Tests for get_all_routes."""

    def test_empty_db(self, sample_db: PriceDatabase):
        assert sample_db.get_all_routes() == []

    def test_returns_distinct_routes(self, sample_db: PriceDatabase):
        sample_db.record_offers([
            _make_offer(origin="BIO", destination="BER", price=100),
            _make_offer(origin="BIO", destination="BER", price=120),
            _make_offer(origin="EAS", destination="BGY", price=80),
        ])
        routes = sample_db.get_all_routes()
        assert ("BIO", "BER") in routes
        assert ("EAS", "BGY") in routes
        assert len(routes) == 2

    def test_sorted_by_origin_then_dest(self, sample_db: PriceDatabase):
        sample_db.record_offers([
            _make_offer(origin="EAS", destination="BGY", price=80),
            _make_offer(origin="BIO", destination="LHR", price=100),
            _make_offer(origin="BIO", destination="BER", price=90),
        ])
        routes = sample_db.get_all_routes()
        assert routes == [("BIO", "BER"), ("BIO", "LHR"), ("EAS", "BGY")]


class TestGetPriceTrend:
    """Tests for get_price_trend."""

    def test_empty_db(self, sample_db: PriceDatabase):
        trend = sample_db.get_price_trend("BIO", "BER")
        assert trend == []

    def test_returns_daily_aggregates(self, sample_db: PriceDatabase):
        t1 = datetime(2026, 2, 1, 10, 0)
        t2 = datetime(2026, 2, 1, 14, 0)
        t3 = datetime(2026, 2, 2, 10, 0)
        sample_db.record_offers([
            _make_offer(price=100, queried_at=t1),
            _make_offer(price=120, queried_at=t2),
            _make_offer(price=90, queried_at=t3),
        ])
        trend = sample_db.get_price_trend("BIO", "BER", last_n_days=365)
        assert len(trend) == 2  # Two distinct dates
        assert trend[0]["count"] == 2  # Two records on Feb 1
        assert trend[1]["count"] == 1  # One record on Feb 2
        assert trend[0]["min_price"] == 100.0

    def test_respects_day_filter(self, sample_db: PriceDatabase):
        old = datetime(2025, 1, 1, 10, 0)
        recent = datetime.now(UTC)
        sample_db.record_offers([
            _make_offer(price=100, queried_at=old),
            _make_offer(price=120, queried_at=recent),
        ])
        trend = sample_db.get_price_trend("BIO", "BER", last_n_days=30)
        # Only the recent record should appear
        assert len(trend) == 1

    def test_filters_by_route(self, sample_db: PriceDatabase):
        sample_db.record_offers([
            _make_offer(origin="BIO", destination="BER", price=100),
            _make_offer(origin="BIO", destination="LHR", price=200),
        ])
        trend = sample_db.get_price_trend("BIO", "BER", last_n_days=365)
        assert len(trend) == 1
        assert trend[0]["avg_price"] == 100.0
