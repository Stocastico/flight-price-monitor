"""Kiwi Tequila API flight search provider."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import requests

from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.providers.base import FlightSearchProvider, ProviderError

logger = logging.getLogger(__name__)

KIWI_BASE_URL = "https://tequila-api.kiwi.com"


class KiwiProvider(FlightSearchProvider):
    """Flight search using the Kiwi Tequila API."""

    def __init__(self, api_key: str, timeout: int = 30):
        self._session = requests.Session()
        self._session.headers["apikey"] = api_key
        self._timeout = timeout

    def name(self) -> str:
        return "kiwi"

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
        params = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": date_from.strftime("%d/%m/%Y"),
            "date_to": date_to.strftime("%d/%m/%Y"),
            "flight_type": flight_type,
            "one_for_city": 0,
            "adults": adults,
            "curr": currency,
            "max_stopovers": 0 if nonstop_only else max_stopovers,
            "limit": max_results,
            "sort": "price",
            "asc": 1,
            "vehicle_type": "aircraft",
        }
        if flight_type == "round":
            params["return_from"] = date_from.strftime("%d/%m/%Y")
            params["return_to"] = date_to.strftime("%d/%m/%Y")
            params["nights_in_dst_from"] = nights_min
            params["nights_in_dst_to"] = nights_max
        if cabin_bag_only:
            params["adult_hold_bag"] = 0
            params["adult_hand_bag"] = 1

        try:
            resp = self._session.get(
                f"{KIWI_BASE_URL}/v2/search",
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError("kiwi", None, str(exc)) from exc

        if resp.status_code != 200:
            raise ProviderError("kiwi", resp.status_code, resp.text[:500])

        data = resp.json().get("data", [])
        offers = []
        for item in data:
            try:
                offers.append(self._parse_offer(item, currency))
            except (KeyError, ValueError, IndexError) as exc:
                logger.warning("Failed to parse Kiwi offer %s: %s", item.get("id"), exc)
        return offers

    @staticmethod
    def _parse_offer(item: dict, currency: str) -> FlightOffer:
        segments: list[FlightSegment] = []
        for leg in item.get("route", []):
            dep = _parse_kiwi_datetime(leg["local_departure"])
            arr = _parse_kiwi_datetime(leg["local_arrival"])
            duration = int((arr - dep).total_seconds() / 60)
            segments.append(
                FlightSegment(
                    airline=leg.get("airline", ""),
                    flight_number=f"{leg.get('airline', '')}{leg.get('flight_no', '')}",
                    origin=Airport(code=leg["flyFrom"], city=leg.get("cityFrom", "")),
                    destination=Airport(code=leg["flyTo"], city=leg.get("cityTo", "")),
                    departure_time=dep,
                    arrival_time=arr,
                    duration_minutes=duration,
                )
            )

        first_seg = segments[0]
        last_seg = segments[-1]
        total_duration = int(
            (last_seg.arrival_time - first_seg.departure_time).total_seconds() / 60
        )

        return FlightOffer(
            provider="kiwi",
            provider_id=item.get("id", ""),
            origin=first_seg.origin,
            destination=last_seg.destination,
            segments=segments,
            departure_time=first_seg.departure_time,
            arrival_time=last_seg.arrival_time,
            total_duration_minutes=total_duration,
            stops=len(segments) - 1,
            price=Decimal(str(item["price"])),
            currency=currency,
            deep_link=item.get("deep_link", ""),
        )


def _parse_kiwi_datetime(value: str) -> datetime:
    """Parse a Kiwi datetime string (ISO format with optional Z suffix)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
