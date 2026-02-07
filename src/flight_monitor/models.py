"""Data models for the flight price monitor."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class Airport(BaseModel):
    """An airport identified by IATA code."""

    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    city: str = ""
    country: str = ""


class FlightSegment(BaseModel):
    """A single leg of a flight (one takeoff-to-landing)."""

    airline: str
    flight_number: str
    origin: Airport
    destination: Airport
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int


class FlightOffer(BaseModel):
    """A complete one-way flight offer, possibly with connections."""

    provider: str
    provider_id: str
    origin: Airport
    destination: Airport
    segments: list[FlightSegment]
    departure_time: datetime
    arrival_time: datetime
    total_duration_minutes: int
    stops: int
    price: Decimal
    currency: str = "EUR"
    deep_link: str = ""
    queried_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_direct(self) -> bool:
        return self.stops == 0


class RouteKey(BaseModel, frozen=True):
    """Identifies a specific origin-destination pair for price tracking."""

    origin_code: str
    destination_code: str

    def __hash__(self) -> int:
        return hash((self.origin_code, self.destination_code))


class PriceRecord(BaseModel):
    """A historical price observation stored in SQLite."""

    id: int | None = None
    route_origin: str
    route_destination: str
    price: Decimal
    currency: str
    stops: int
    airline: str
    observed_at: datetime
    departure_date: date
    provider: str


class Deal(BaseModel):
    """A flight offer identified as significantly cheaper than historical average."""

    offer: FlightOffer
    route_key: RouteKey
    historical_avg_price: Decimal
    historical_min_price: Decimal
    historical_count: int
    savings_vs_avg_pct: float
    savings_vs_avg_abs: Decimal
    is_historical_low: bool
