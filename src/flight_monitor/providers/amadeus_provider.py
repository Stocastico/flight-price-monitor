"""Amadeus Self-Service API flight search provider."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.providers.base import FlightSearchProvider, ProviderError

logger = logging.getLogger(__name__)


class AmadeusProvider(FlightSearchProvider):
    """Flight search using the Amadeus Self-Service API.

    Requires the optional 'amadeus' dependency: pip install flight-monitor[amadeus]
    """

    def __init__(self, client_id: str, client_secret: str):
        try:
            from amadeus import Client
        except ImportError as exc:
            raise ImportError(
                "The 'amadeus' package is required for the Amadeus provider. "
                "Install it with: pip install flight-monitor[amadeus]"
            ) from exc

        self._client = Client(client_id=client_id, client_secret=client_secret)

    def name(self) -> str:
        return "amadeus"

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
        cabin_bag_only: bool = False,
        flight_type: str = "oneway",
        nights_min: int = 2,
        nights_max: int = 7,
    ) -> list[FlightOffer]:
        from amadeus import ResponseError

        all_offers: list[FlightOffer] = []
        current = date_from
        total_queries = 0
        failed_queries = 0

        while current <= date_to:
            total_queries += 1
            try:
                response = self._client.shopping.flight_offers_search.get(
                    originLocationCode=origin,
                    destinationLocationCode=destination,
                    departureDate=current.isoformat(),
                    adults=adults,
                    nonStop=nonstop_only,
                    currencyCode=currency,
                    max=min(max_results, 250),
                )
                for item in response.data:
                    try:
                        offer = self._parse_offer(item, currency)
                        if offer.stops <= max_stopovers:
                            all_offers.append(offer)
                    except (KeyError, ValueError, IndexError) as exc:
                        logger.warning("Failed to parse Amadeus offer: %s", exc)
            except ResponseError as e:
                failed_queries += 1
                logger.warning(
                    "Amadeus API error for %s->%s on %s: %s",
                    origin,
                    destination,
                    current,
                    e,
                )
            current += timedelta(days=7)

        if total_queries > 0 and failed_queries == total_queries:
            raise ProviderError(
                "amadeus",
                None,
                f"All {total_queries} queries failed for {origin}->{destination}",
            )

        all_offers.sort(key=lambda o: o.price)
        return all_offers[:max_results]

    @staticmethod
    def _parse_offer(item: dict, currency: str) -> FlightOffer:
        segments: list[FlightSegment] = []
        itinerary = item["itineraries"][0]

        for seg_data in itinerary["segments"]:
            segments.append(
                FlightSegment(
                    airline=seg_data["carrierCode"],
                    flight_number=f"{seg_data['carrierCode']}{seg_data['number']}",
                    origin=Airport(code=seg_data["departure"]["iataCode"]),
                    destination=Airport(code=seg_data["arrival"]["iataCode"]),
                    departure_time=datetime.fromisoformat(seg_data["departure"]["at"]),
                    arrival_time=datetime.fromisoformat(seg_data["arrival"]["at"]),
                    duration_minutes=_parse_iso_duration(seg_data.get("duration", "PT0H")),
                )
            )

        first_seg = segments[0]
        last_seg = segments[-1]

        return FlightOffer(
            provider="amadeus",
            provider_id=item.get("id", ""),
            origin=first_seg.origin,
            destination=last_seg.destination,
            segments=segments,
            departure_time=first_seg.departure_time,
            arrival_time=last_seg.arrival_time,
            total_duration_minutes=_parse_iso_duration(itinerary.get("duration", "PT0H")),
            stops=len(segments) - 1,
            price=Decimal(item["price"]["total"]),
            currency=item["price"].get("currency", currency),
        )


def _parse_iso_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration like 'PT2H30M' to minutes."""
    hours = minutes = 0
    m = re.search(r"(\d+)H", iso_duration)
    if m:
        hours = int(m.group(1))
    m = re.search(r"(\d+)M", iso_duration)
    if m:
        minutes = int(m.group(1))
    return hours * 60 + minutes
