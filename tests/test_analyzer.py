"""Tests for the price analysis engine."""

from __future__ import annotations

import itertools
from datetime import datetime
from decimal import Decimal

import pytest

from flight_monitor.analyzer import PriceAnalyzer
from flight_monitor.config import AnalysisConfig, DestinationConfig
from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.storage.database import PriceDatabase

_counter = itertools.count()


def _make_offer(
    origin: str = "BIO",
    destination: str = "BER",
    price: float = 100.0,
    queried_at: datetime | None = None,
) -> FlightOffer:
    uid = next(_counter)
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
    offer = FlightOffer(
        provider="kiwi",
        provider_id=f"test-{uid}",
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
    if queried_at:
        offer = offer.model_copy(update={"queried_at": queried_at})
    return offer


class TestPriceAnalyzer:
    @pytest.fixture
    def db(self, tmp_path) -> PriceDatabase:
        return PriceDatabase(tmp_path / "test.db")

    @pytest.fixture
    def dest_config(self) -> DestinationConfig:
        return DestinationConfig(name="Berlin", airports=["BER"])

    def _seed_history(self, db: PriceDatabase, prices: list[float]):
        """Populate the database with historical prices for BIO->BER."""
        offers = [_make_offer(price=p) for p in prices]
        db.record_offers(offers)

    def test_detects_deal_below_threshold(self, db, dest_config):
        # Historical average: 200. A flight at 100 is 50% below.
        self._seed_history(db, [180, 200, 220])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        cheap_offer = _make_offer(price=100)
        deals = analyzer.find_deals([cheap_offer], dest_config)

        assert len(deals) == 1
        assert deals[0].savings_vs_avg_pct == 50.0
        assert deals[0].offer.price == Decimal("100")

    def test_no_deal_above_threshold(self, db, dest_config):
        self._seed_history(db, [100, 110, 120])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        # Price of 95 is only ~13.6% below average of ~110
        normal_offer = _make_offer(price=95)
        deals = analyzer.find_deals([normal_offer], dest_config)

        assert len(deals) == 0

    def test_skips_insufficient_history(self, db, dest_config):
        # Only 2 records, but min_history_count=3
        self._seed_history(db, [200, 220])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        cheap_offer = _make_offer(price=50)
        deals = analyzer.find_deals([cheap_offer], dest_config)

        assert len(deals) == 0

    def test_detects_historical_low(self, db, dest_config):
        self._seed_history(db, [150, 160, 170])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        # Price below the historical minimum (150)
        very_cheap = _make_offer(price=100)
        deals = analyzer.find_deals([very_cheap], dest_config)

        assert len(deals) == 1
        assert deals[0].is_historical_low is True

    def test_not_historical_low(self, db, dest_config):
        self._seed_history(db, [200, 250, 300])
        config = AnalysisConfig(deal_threshold_pct=10, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        # Price 210 is below avg (250) but above min (200)
        offer = _make_offer(price=210)
        deals = analyzer.find_deals([offer], dest_config)

        if deals:
            assert deals[0].is_historical_low is False

    def test_falls_back_to_destination_group(self, db):
        # BIO->LHR has 3 records, but we're checking BIO->LGW
        offers_lhr = [_make_offer(destination="LHR", price=p) for p in [200, 220, 240]]
        db.record_offers(offers_lhr)

        dest_config = DestinationConfig(name="London", airports=["LHR", "LGW", "STN"])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        # LGW flight at 100 is ~55% below LHR avg of 220
        cheap_lgw = _make_offer(destination="LGW", price=100)
        deals = analyzer.find_deals([cheap_lgw], dest_config)

        assert len(deals) == 1
        assert deals[0].offer.destination.code == "LGW"

    def test_deals_sorted_by_savings(self, db, dest_config):
        self._seed_history(db, [200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=10, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offers = [
            _make_offer(price=150),  # 25% savings
            _make_offer(price=100),  # 50% savings
            _make_offer(price=170),  # 15% savings
        ]
        deals = analyzer.find_deals(offers, dest_config)

        assert len(deals) == 3
        assert deals[0].savings_vs_avg_pct > deals[1].savings_vs_avg_pct
        assert deals[1].savings_vs_avg_pct > deals[2].savings_vs_avg_pct

    def test_empty_offers_list(self, db, dest_config):
        """No offers should produce no deals."""
        self._seed_history(db, [200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        deals = analyzer.find_deals([], dest_config)
        assert deals == []

    def test_avg_price_zero_skipped(self, db, dest_config):
        """Offers with zero average price in history should be skipped (no div by zero)."""
        # Seed with zero-price records
        self._seed_history(db, [0, 0, 0])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=50)
        deals = analyzer.find_deals([offer], dest_config)
        assert deals == []

    def test_exact_threshold_boundary(self, db, dest_config):
        """Price exactly at threshold percentage should be a deal."""
        # avg = 200, price = 150 => savings = 25% exactly
        self._seed_history(db, [200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=150)
        deals = analyzer.find_deals([offer], dest_config)
        assert len(deals) == 1
        assert deals[0].savings_vs_avg_pct == 25.0

    def test_just_below_threshold(self, db, dest_config):
        """Price just below threshold should not be a deal."""
        # avg = 200, price = 151 => savings = 24.5%
        self._seed_history(db, [200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=151)
        deals = analyzer.find_deals([offer], dest_config)
        assert deals == []

    def test_multiple_offers_different_routes(self, db):
        """Analyzer handles offers going to different destinations."""
        # Seed BIO->BER with history
        ber_offers = [_make_offer(destination="BER", price=p) for p in [200, 200, 200]]
        db.record_offers(ber_offers)
        # Seed BIO->BGY with history
        bgy_offers = [_make_offer(destination="BGY", price=p) for p in [100, 100, 100]]
        db.record_offers(bgy_offers)

        dest_config = DestinationConfig(name="Multi", airports=["BER", "BGY"])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offers = [
            _make_offer(destination="BER", price=100),  # 50% below BER avg
            _make_offer(destination="BGY", price=90),  # 10% below BGY avg
        ]
        deals = analyzer.find_deals(offers, dest_config)
        # Only BER deal should qualify (50% >= 25%)
        assert len(deals) == 1
        assert deals[0].offer.destination.code == "BER"

    def test_deal_savings_abs_calculated(self, db, dest_config):
        """savings_vs_avg_abs should be avg - price."""
        self._seed_history(db, [200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=10, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=100)
        deals = analyzer.find_deals([offer], dest_config)
        assert len(deals) == 1
        assert deals[0].savings_vs_avg_abs == Decimal("100.0")

    def test_min_history_count_one(self, db, dest_config):
        """With min_history_count=1, even a single record is enough."""
        self._seed_history(db, [200])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=1)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=100)
        deals = analyzer.find_deals([offer], dest_config)
        assert len(deals) == 1

    def test_no_history_no_fallback(self, db):
        """No history at all (route or group) -> no deals."""
        dest_config = DestinationConfig(name="Unknown", airports=["ZZZ"])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(destination="ZZZ", price=10)
        deals = analyzer.find_deals([offer], dest_config)
        assert deals == []

    def test_historical_count_in_deal(self, db, dest_config):
        """Deal should contain the correct historical count."""
        self._seed_history(db, [200, 200, 200, 200, 200])
        config = AnalysisConfig(deal_threshold_pct=25, min_history_count=3)
        analyzer = PriceAnalyzer(config, db)

        offer = _make_offer(price=100)
        deals = analyzer.find_deals([offer], dest_config)
        assert deals[0].historical_count == 5

    def test_stats_lookback_days_filters_old_history(self, db, dest_config):
        """Only recent history should be used when stats_lookback_days is set."""
        from datetime import UTC, timedelta

        old_time = datetime.now(UTC) - timedelta(days=200)
        recent_time = datetime.now(UTC) - timedelta(days=5)

        # Old history: expensive
        old_offers = [_make_offer(price=p, queried_at=old_time) for p in [300, 310, 320]]
        db.record_offers(old_offers)
        # Recent history: cheap
        recent_offers = [_make_offer(price=p, queried_at=recent_time) for p in [80, 85, 90]]
        db.record_offers(recent_offers)

        # With lookback=30, only recent prices (avg ~85) used -> 80 is NOT a deal
        config = AnalysisConfig(
            deal_threshold_pct=25, min_history_count=3, stats_lookback_days=30
        )
        analyzer = PriceAnalyzer(config, db)
        offer = _make_offer(price=80)
        deals = analyzer.find_deals([offer], dest_config)
        assert deals == []

        # Without lookback, all history (avg ~197) used -> 80 IS a deal
        config_all = AnalysisConfig(
            deal_threshold_pct=25, min_history_count=3, stats_lookback_days=None
        )
        analyzer_all = PriceAnalyzer(config_all, db)
        offer2 = _make_offer(price=80)
        deals_all = analyzer_all.find_deals([offer2], dest_config)
        assert len(deals_all) == 1
