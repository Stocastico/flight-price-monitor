"""Tests for the price analysis engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from flight_monitor.analyzer import PriceAnalyzer
from flight_monitor.config import AnalysisConfig, DestinationConfig
from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.storage.database import PriceDatabase


def _make_offer(
    origin: str = "BIO",
    destination: str = "BER",
    price: float = 100.0,
    queried_at: datetime | None = None,
) -> FlightOffer:
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
        provider_id=f"test-{price}",
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

        dest_config = DestinationConfig(
            name="London", airports=["LHR", "LGW", "STN"]
        )
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
