"""Abstract base interface for flight search providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from flight_monitor.models import FlightOffer


class FlightSearchProvider(ABC):
    """Abstract interface for flight search API providers."""

    @abstractmethod
    def search_flights(
        self,
        origin: str,
        destination: str,
        date_from: date,
        date_to: date,
        adults: int = 1,
        currency: str = "EUR",
        max_stopovers: int = 1,
        nonstop_only: bool = False,
        max_results: int = 50,
    ) -> list[FlightOffer]:
        """Search for flight offers on a single origin-destination pair.

        Returns a list of FlightOffer, sorted by price ascending.
        Raises ProviderError on API failures.
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Return provider identifier, e.g. 'kiwi' or 'amadeus'."""
        ...


class ProviderError(Exception):
    """Raised when a provider API call fails."""

    def __init__(self, provider: str, status_code: int | None, message: str):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message} (HTTP {status_code})")
