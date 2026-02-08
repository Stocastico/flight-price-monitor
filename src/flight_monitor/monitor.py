"""Flight monitor orchestrator - coordinates the full monitoring cycle."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from flight_monitor.analyzer import PriceAnalyzer
from flight_monitor.config import AppConfig
from flight_monitor.filters import FlightFilter
from flight_monitor.models import Deal, FlightOffer
from flight_monitor.providers.base import FlightSearchProvider, ProviderError
from flight_monitor.providers.factory import create_provider
from flight_monitor.reporter import Reporter
from flight_monitor.storage.database import PriceDatabase

logger = logging.getLogger(__name__)


class FlightMonitor:
    """Orchestrates a complete monitoring run."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._provider: FlightSearchProvider = create_provider(config)
        self._db = PriceDatabase(config.storage.db_path)
        self._filter = FlightFilter(config.filters)
        self._analyzer = PriceAnalyzer(config.analysis, self._db)
        self._reporter = Reporter(config.reporting)

    def run(self) -> tuple[list[Deal], str]:
        """Execute a full monitoring cycle.

        Returns (deals_found, report_text).
        """
        run_time = datetime.now(UTC)
        date_from = datetime.now(UTC).date()
        date_to = date_from + timedelta(days=self._config.search.date_range_days)

        all_offers: list[FlightOffer] = []
        all_deals: list[Deal] = []

        for origin in self._config.origins:
            for dest in self._config.destinations:
                logger.info(
                    "Searching %s -> %s (%s)...",
                    origin.code,
                    dest.name,
                    ",".join(dest.airports),
                )
                route_offers = self._search_route(
                    origin_code=origin.code,
                    destination_codes=dest.airports,
                    date_from=date_from,
                    date_to=date_to,
                )
                logger.info("  Found %d offers", len(route_offers))

                filtered = self._filter.apply(route_offers)
                logger.info("  After filters: %d offers", len(filtered))

                # Analyze BEFORE recording to avoid polluting historical stats
                deals = self._analyzer.find_deals(filtered, dest)
                logger.info("  Deals detected: %d", len(deals))

                self._db.record_offers(filtered)

                all_offers.extend(filtered)
                all_deals.extend(deals)

        all_deals.sort(key=lambda d: d.savings_vs_avg_pct, reverse=True)
        report = self._reporter.generate(all_deals, all_offers, run_time)
        return all_deals, report

    def _search_route(
        self,
        origin_code: str,
        destination_codes: list[str],
        date_from: date,
        date_to: date,
    ) -> list[FlightOffer]:
        """Search flights from one origin to a destination group."""
        if self._provider.name() == "kiwi":
            # Kiwi accepts comma-separated fly_to
            destination_str = ",".join(destination_codes)
            try:
                return self._provider.search_flights(
                    origin=origin_code,
                    destination=destination_str,
                    date_from=date_from,
                    date_to=date_to,
                    adults=self._config.search.adults,
                    currency=self._config.search.currency,
                    max_stopovers=self._config.filters.max_stops,
                    max_results=self._config.search.max_results_per_route,
                    cabin_bag_only=self._config.filters.cabin_bag_only,
                    flight_type=self._config.search.flight_type,
                    nights_min=self._config.search.nights_min,
                    nights_max=self._config.search.nights_max,
                )
            except ProviderError as e:
                logger.error("Search failed for %s->%s: %s", origin_code, destination_str, e)
                return []

        # Other providers: search per individual airport
        offers: list[FlightOffer] = []
        for dest_code in destination_codes:
            try:
                results = self._provider.search_flights(
                    origin=origin_code,
                    destination=dest_code,
                    date_from=date_from,
                    date_to=date_to,
                    adults=self._config.search.adults,
                    currency=self._config.search.currency,
                    max_stopovers=self._config.filters.max_stops,
                    max_results=self._config.search.max_results_per_route,
                    cabin_bag_only=self._config.filters.cabin_bag_only,
                    flight_type=self._config.search.flight_type,
                    nights_min=self._config.search.nights_min,
                    nights_max=self._config.search.nights_max,
                )
                offers.extend(results)
            except ProviderError as e:
                logger.error("Search failed for %s->%s: %s", origin_code, dest_code, e)
        return offers
