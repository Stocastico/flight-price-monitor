"""SQLite storage layer for historical flight prices."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flight_monitor.models import FlightOffer, RouteKey

SCHEMA_VERSION = 1

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS price_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    route_origin   TEXT    NOT NULL,
    route_dest     TEXT    NOT NULL,
    price          REAL    NOT NULL,
    currency       TEXT    NOT NULL,
    stops          INTEGER NOT NULL,
    airline        TEXT    NOT NULL DEFAULT '',
    departure_date TEXT    NOT NULL,
    observed_at    TEXT    NOT NULL,
    provider       TEXT    NOT NULL,
    provider_id    TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_route
    ON price_history(route_origin, route_dest);

CREATE INDEX IF NOT EXISTS idx_observed
    ON price_history(observed_at);
"""


class PriceStats:
    """Historical price statistics for a route."""

    __slots__ = ("avg_price", "count", "last_observed", "max_price", "min_price")

    def __init__(
        self,
        avg_price: Decimal,
        min_price: Decimal,
        max_price: Decimal,
        count: int,
        last_observed: str | None,
    ):
        self.avg_price = avg_price
        self.min_price = min_price
        self.max_price = max_price
        self.count = count
        self.last_observed = last_observed


class PriceDatabase:
    """SQLite-backed storage for flight price history."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(CREATE_TABLES)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record_offers(self, offers: list[FlightOffer]) -> int:
        """Store a batch of flight offers. Returns count stored."""
        with self._connect() as conn:
            for offer in offers:
                airline = offer.segments[0].airline if offer.segments else ""
                conn.execute(
                    """INSERT INTO price_history
                       (route_origin, route_dest, price, currency, stops,
                        airline, departure_date, observed_at, provider, provider_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        offer.origin.code,
                        offer.destination.code,
                        float(offer.price),
                        offer.currency,
                        offer.stops,
                        airline,
                        offer.departure_time.date().isoformat(),
                        offer.queried_at.isoformat(),
                        offer.provider,
                        offer.provider_id,
                    ),
                )
        return len(offers)

    def get_route_stats(
        self,
        route: RouteKey,
        max_stops: int | None = None,
    ) -> PriceStats:
        """Return historical price stats for a specific route."""
        query = """
            SELECT
                AVG(price) AS avg_price,
                MIN(price) AS min_price,
                MAX(price) AS max_price,
                COUNT(*)   AS cnt,
                MAX(observed_at) AS last_observed
            FROM price_history
            WHERE route_origin = ? AND route_dest = ?
        """
        params: list[object] = [route.origin_code, route.destination_code]
        if max_stops is not None:
            query += " AND stops <= ?"
            params.append(max_stops)

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            if row and row["cnt"] > 0:
                return PriceStats(
                    avg_price=Decimal(str(round(row["avg_price"], 2))),
                    min_price=Decimal(str(row["min_price"])),
                    max_price=Decimal(str(row["max_price"])),
                    count=row["cnt"],
                    last_observed=row["last_observed"],
                )
        return PriceStats(
            avg_price=Decimal("0"),
            min_price=Decimal("0"),
            max_price=Decimal("0"),
            count=0,
            last_observed=None,
        )

    def get_route_stats_for_destination_group(
        self,
        origin_code: str,
        destination_codes: list[str],
        max_stops: int | None = None,
    ) -> PriceStats:
        """Aggregate stats across multiple destination airports."""
        if not destination_codes:
            return PriceStats(
                avg_price=Decimal("0"),
                min_price=Decimal("0"),
                max_price=Decimal("0"),
                count=0,
                last_observed=None,
            )
        placeholders = ",".join("?" * len(destination_codes))
        query = f"""
            SELECT
                AVG(price) AS avg_price,
                MIN(price) AS min_price,
                MAX(price) AS max_price,
                COUNT(*)   AS cnt
            FROM price_history
            WHERE route_origin = ?
              AND route_dest IN ({placeholders})
        """
        params: list[object] = [origin_code, *destination_codes]
        if max_stops is not None:
            query += " AND stops <= ?"
            params.append(max_stops)

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            if row and row["cnt"] > 0:
                return PriceStats(
                    avg_price=Decimal(str(round(row["avg_price"], 2))),
                    min_price=Decimal(str(row["min_price"])),
                    max_price=Decimal(str(row["max_price"])),
                    count=row["cnt"],
                    last_observed=None,
                )
        return PriceStats(
            avg_price=Decimal("0"),
            min_price=Decimal("0"),
            max_price=Decimal("0"),
            count=0,
            last_observed=None,
        )

    def purge_old_records(self, older_than_days: int = 365) -> int:
        """Remove records older than N days. Returns count removed."""
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM price_history WHERE observed_at < ?", (cutoff,))
            return cursor.rowcount
