"""Flight offer filtering based on user configuration."""

from __future__ import annotations

from datetime import time

from flight_monitor.config import FiltersConfig
from flight_monitor.models import FlightOffer


class FlightFilter:
    """Apply user-configured filters to flight offers."""

    def __init__(self, config: FiltersConfig):
        self._config = config
        self._earliest = time.fromisoformat(config.departure_time_earliest)
        self._latest = time.fromisoformat(config.departure_time_latest)

    def apply(self, offers: list[FlightOffer]) -> list[FlightOffer]:
        """Filter and sort offers according to configuration."""
        filtered = [o for o in offers if self._passes(o)]

        if self._config.prefer_direct:
            filtered.sort(key=lambda o: (o.stops > 0, o.price))
        else:
            filtered.sort(key=lambda o: o.price)

        return filtered

    def _passes(self, offer: FlightOffer) -> bool:
        if offer.stops > self._config.max_stops:
            return False

        if offer.total_duration_minutes > self._config.max_duration_minutes:
            return False

        dep_time = offer.departure_time.time()
        if dep_time < self._earliest or dep_time > self._latest:
            return False

        offer_airlines = {s.airline for s in offer.segments}

        if self._config.allowed_airlines and not offer_airlines & set(
            self._config.allowed_airlines
        ):
            return False

        return not (
            self._config.excluded_airlines
            and offer_airlines & set(self._config.excluded_airlines)
        )
