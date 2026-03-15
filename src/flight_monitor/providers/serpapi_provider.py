"""Google Flights via SerpAPI flight search provider."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import requests

from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.providers.base import FlightSearchProvider, ProviderError
from flight_monitor.retry import retry_on_exception

logger = logging.getLogger(__name__)

SERPAPI_BASE_URL = "https://serpapi.com/search"


class SerpApiProvider(FlightSearchProvider):
    """Flight search using Google Flights via the SerpAPI."""

    def __init__(self, api_key: str, timeout: int = 60):
        self._api_key = api_key
        self._timeout = timeout

    def name(self) -> str:
        return "serpapi"

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
        params: dict[str, object] = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": date_from.isoformat(),
            "type": 1 if flight_type == "round" else 2,
            "adults": adults,
            "currency": currency,
            "api_key": self._api_key,
        }
        if flight_type == "round":
            return_date = date_from + (date_to - date_from)
            params["return_date"] = return_date.isoformat()
        if nonstop_only:
            params["stops"] = 0

        def _do_request() -> requests.Response:
            try:
                r = requests.get(
                    SERPAPI_BASE_URL,
                    params=params,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                raise ProviderError("serpapi", None, str(exc)) from exc
            if r.status_code >= 500:
                raise ProviderError("serpapi", r.status_code, r.text[:500])
            return r

        resp = retry_on_exception(
            _do_request,
            max_retries=3,
            base_delay=2.0,
            retryable=(ProviderError,),
            description=f"SerpAPI search {origin}->{destination}",
        )

        if resp.status_code != 200:
            raise ProviderError("serpapi", resp.status_code, resp.text[:500])

        data = resp.json()
        if "error" in data:
            raise ProviderError("serpapi", None, data["error"])

        offers: list[FlightOffer] = []
        for flight_group in ("best_flights", "other_flights"):
            for item in data.get(flight_group, []):
                try:
                    offer = self._parse_flight(item, currency)
                    if offer.stops <= max_stopovers:
                        offers.append(offer)
                except (KeyError, ValueError, IndexError) as exc:
                    logger.warning("Failed to parse SerpAPI flight: %s", exc)

        offers.sort(key=lambda o: o.price)
        return offers[:max_results]

    @staticmethod
    def _parse_flight(item: dict, currency: str) -> FlightOffer:
        segments: list[FlightSegment] = []
        for leg in item.get("flights", []):
            dep_airport = leg["departure_airport"]
            arr_airport = leg["arrival_airport"]
            dep_time = datetime.fromisoformat(dep_airport["time"])
            arr_time = datetime.fromisoformat(arr_airport["time"])
            duration = leg.get("duration", 0)

            segments.append(
                FlightSegment(
                    airline=leg.get("airline", ""),
                    flight_number=leg.get("flight_number", ""),
                    origin=Airport(
                        code=dep_airport["id"],
                        city=dep_airport.get("name", ""),
                    ),
                    destination=Airport(
                        code=arr_airport["id"],
                        city=arr_airport.get("name", ""),
                    ),
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    duration_minutes=duration,
                )
            )

        first_seg = segments[0]
        last_seg = segments[-1]
        total_duration = item.get("total_duration", 0)

        return FlightOffer(
            provider="serpapi",
            provider_id="",
            origin=first_seg.origin,
            destination=last_seg.destination,
            segments=segments,
            departure_time=first_seg.departure_time,
            arrival_time=last_seg.arrival_time,
            total_duration_minutes=total_duration,
            stops=len(segments) - 1,
            price=Decimal(str(item["price"])),
            currency=currency,
        )
