"""Factory for creating flight search provider instances."""

from __future__ import annotations

from flight_monitor.config import AppConfig
from flight_monitor.providers.base import FlightSearchProvider


def create_provider(config: AppConfig) -> FlightSearchProvider:
    """Instantiate the configured flight search provider."""
    if config.provider == "kiwi":
        from flight_monitor.providers.kiwi import KiwiProvider

        if not config.credentials.kiwi:
            raise ValueError("Kiwi credentials not configured")
        return KiwiProvider(api_key=config.credentials.kiwi.api_key)
    elif config.provider == "amadeus":
        from flight_monitor.providers.amadeus_provider import AmadeusProvider

        if not config.credentials.amadeus:
            raise ValueError("Amadeus credentials not configured")
        return AmadeusProvider(
            client_id=config.credentials.amadeus.client_id,
            client_secret=config.credentials.amadeus.client_secret,
        )
    else:
        raise ValueError(f"Unknown provider: {config.provider}")
