"""Price analysis engine for detecting flight deals."""

from __future__ import annotations

from flight_monitor.config import AnalysisConfig, DestinationConfig
from flight_monitor.models import Deal, FlightOffer, RouteKey
from flight_monitor.storage.database import PriceDatabase, PriceStats


class PriceAnalyzer:
    """Detect deals by comparing current prices to historical averages."""

    def __init__(self, config: AnalysisConfig, db: PriceDatabase):
        self._config = config
        self._db = db

    def find_deals(
        self,
        offers: list[FlightOffer],
        destination_config: DestinationConfig,
    ) -> list[Deal]:
        """Analyze offers against historical prices and return detected deals."""
        deals: list[Deal] = []

        for offer in offers:
            route = RouteKey(
                origin_code=offer.origin.code,
                destination_code=offer.destination.code,
            )

            stats = self._get_best_stats(route, destination_config)
            if stats is None:
                continue

            if stats.avg_price <= 0:
                continue

            savings_pct = float((stats.avg_price - offer.price) / stats.avg_price * 100)

            if savings_pct >= self._config.deal_threshold_pct:
                deals.append(
                    Deal(
                        offer=offer,
                        route_key=route,
                        historical_avg_price=stats.avg_price,
                        historical_min_price=stats.min_price,
                        historical_count=stats.count,
                        savings_vs_avg_pct=round(savings_pct, 1),
                        savings_vs_avg_abs=stats.avg_price - offer.price,
                        is_historical_low=offer.price <= stats.min_price,
                    )
                )

        deals.sort(key=lambda d: d.savings_vs_avg_pct, reverse=True)
        return deals

    def _get_best_stats(
        self,
        route: RouteKey,
        destination_config: DestinationConfig,
    ) -> PriceStats | None:
        """Get historical stats, falling back to destination group if needed."""
        stats = self._db.get_route_stats(route)
        if stats.count >= self._config.min_history_count:
            return stats

        group_stats = self._db.get_route_stats_for_destination_group(
            origin_code=route.origin_code,
            destination_codes=destination_config.airports,
        )
        if group_stats.count >= self._config.min_history_count:
            return group_stats

        return None
