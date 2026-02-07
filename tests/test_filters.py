"""Tests for flight offer filtering."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flight_monitor.config import FiltersConfig
from flight_monitor.filters import FlightFilter
from flight_monitor.models import Airport, FlightOffer, FlightSegment


def _make_offer(
    origin: str = "BIO",
    destination: str = "BER",
    price: float = 100.0,
    stops: int = 0,
    airline: str = "VY",
    departure_hour: int = 10,
    duration_minutes: int = 180,
) -> FlightOffer:
    dep = datetime(2026, 4, 15, departure_hour, 0)
    arr_minutes = departure_hour * 60 + duration_minutes
    arr = datetime(2026, 4, 15, arr_minutes // 60, arr_minutes % 60)

    segments = []
    if stops == 0:
        segments.append(
            FlightSegment(
                airline=airline,
                flight_number=f"{airline}123",
                origin=Airport(code=origin),
                destination=Airport(code=destination),
                departure_time=dep,
                arrival_time=arr,
                duration_minutes=duration_minutes,
            )
        )
    else:
        mid_dep = dep.replace(hour=dep.hour + 2)
        segments.append(
            FlightSegment(
                airline=airline,
                flight_number=f"{airline}100",
                origin=Airport(code=origin),
                destination=Airport(code="MAD"),
                departure_time=dep,
                arrival_time=mid_dep,
                duration_minutes=120,
            )
        )
        segments.append(
            FlightSegment(
                airline=airline,
                flight_number=f"{airline}200",
                origin=Airport(code="MAD"),
                destination=Airport(code=destination),
                departure_time=mid_dep.replace(hour=mid_dep.hour + 1),
                arrival_time=arr,
                duration_minutes=duration_minutes - 180,
            )
        )

    return FlightOffer(
        provider="kiwi",
        provider_id=f"test-{price}-{airline}",
        origin=Airport(code=origin),
        destination=Airport(code=destination),
        segments=segments,
        departure_time=dep,
        arrival_time=arr,
        total_duration_minutes=duration_minutes,
        stops=stops,
        price=Decimal(str(price)),
        currency="EUR",
    )


class TestFlightFilter:
    def test_filters_by_max_stops(self):
        config = FiltersConfig(max_stops=0)
        flt = FlightFilter(config)

        offers = [
            _make_offer(stops=0, price=100),
            _make_offer(stops=1, price=80),
        ]
        result = flt.apply(offers)
        assert len(result) == 1
        assert result[0].stops == 0

    def test_filters_by_max_duration(self):
        config = FiltersConfig(max_duration_minutes=200)
        flt = FlightFilter(config)

        offers = [
            _make_offer(duration_minutes=180),
            _make_offer(duration_minutes=300),
        ]
        result = flt.apply(offers)
        assert len(result) == 1
        assert result[0].total_duration_minutes == 180

    def test_filters_by_departure_time_window(self):
        config = FiltersConfig(
            departure_time_earliest="08:00",
            departure_time_latest="18:00",
        )
        flt = FlightFilter(config)

        offers = [
            _make_offer(departure_hour=5),   # Too early
            _make_offer(departure_hour=10),  # OK
            _make_offer(departure_hour=20),  # Too late
        ]
        result = flt.apply(offers)
        assert len(result) == 1
        assert result[0].departure_time.hour == 10

    def test_filters_by_allowed_airlines(self):
        config = FiltersConfig(allowed_airlines=["VY", "FR"])
        flt = FlightFilter(config)

        offers = [
            _make_offer(airline="VY"),
            _make_offer(airline="IB"),
            _make_offer(airline="FR"),
        ]
        result = flt.apply(offers)
        assert len(result) == 2
        airlines = {r.segments[0].airline for r in result}
        assert airlines == {"VY", "FR"}

    def test_filters_by_excluded_airlines(self):
        config = FiltersConfig(excluded_airlines=["FR"])
        flt = FlightFilter(config)

        offers = [
            _make_offer(airline="VY"),
            _make_offer(airline="FR"),
            _make_offer(airline="IB"),
        ]
        result = flt.apply(offers)
        assert len(result) == 2
        airlines = {r.segments[0].airline for r in result}
        assert "FR" not in airlines

    def test_prefer_direct_sorting(self):
        config = FiltersConfig(prefer_direct=True, max_stops=1)
        flt = FlightFilter(config)

        offers = [
            _make_offer(stops=1, price=50),
            _make_offer(stops=0, price=100),
            _make_offer(stops=0, price=80),
        ]
        result = flt.apply(offers)
        assert len(result) == 3
        # Direct flights should come first, sorted by price
        assert result[0].stops == 0
        assert result[0].price == Decimal("80")
        assert result[1].stops == 0
        assert result[1].price == Decimal("100")
        # Then connecting
        assert result[2].stops == 1

    def test_price_sorting_without_direct_preference(self):
        config = FiltersConfig(prefer_direct=False, max_stops=1)
        flt = FlightFilter(config)

        offers = [
            _make_offer(stops=1, price=50),
            _make_offer(stops=0, price=100),
        ]
        result = flt.apply(offers)
        assert result[0].price == Decimal("50")
        assert result[1].price == Decimal("100")

    def test_all_filters_combined(self):
        config = FiltersConfig(
            max_stops=0,
            max_duration_minutes=200,
            departure_time_earliest="08:00",
            departure_time_latest="18:00",
            allowed_airlines=["VY"],
        )
        flt = FlightFilter(config)

        offers = [
            _make_offer(stops=0, duration_minutes=180, departure_hour=10, airline="VY"),
            _make_offer(stops=1, duration_minutes=180, departure_hour=10, airline="VY"),
            _make_offer(stops=0, duration_minutes=500, departure_hour=10, airline="VY"),
            _make_offer(stops=0, duration_minutes=180, departure_hour=5, airline="VY"),
            _make_offer(stops=0, duration_minutes=180, departure_hour=10, airline="IB"),
        ]
        result = flt.apply(offers)
        assert len(result) == 1

    def test_empty_input(self):
        config = FiltersConfig()
        flt = FlightFilter(config)
        assert flt.apply([]) == []
