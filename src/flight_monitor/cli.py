"""CLI entry point for the flight price monitor."""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import click

from flight_monitor.config import load_config
from flight_monitor.models import RouteKey
from flight_monitor.monitor import FlightMonitor
from flight_monitor.providers.factory import create_provider
from flight_monitor.storage.database import PriceDatabase


@click.group()
@click.option(
    "--config",
    "-c",
    default="config.yaml",
    help="Path to YAML configuration file",
    type=click.Path(exists=False),
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: bool) -> None:
    """Flight Price Monitor - track and find flight deals."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Execute a full monitoring cycle."""
    config_path = ctx.obj["config_path"]
    if not Path(config_path).expanduser().exists():
        click.echo(f"Config file not found: {config_path}", err=True)
        click.echo("Copy config.example.yaml to config.yaml and edit it.", err=True)
        sys.exit(1)

    config = load_config(config_path)
    monitor = FlightMonitor(config)
    deals, report = monitor.run()

    if config.reporting.format == "console":
        click.echo(report)

    click.echo(f"\nDone. {len(deals)} deal(s) found.")
    sys.exit(0 if deals else 1)


@cli.command()
@click.option("--days", default=365, help="Purge records older than N days")
@click.pass_context
def purge(ctx: click.Context, days: int) -> None:
    """Remove old price records from the database."""
    config = load_config(ctx.obj["config_path"])
    db = PriceDatabase(config.storage.db_path)
    removed = db.purge_old_records(older_than_days=days)
    click.echo(f"Purged {removed} records older than {days} days.")


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate the configuration file."""
    config_path = ctx.obj["config_path"]
    try:
        config = load_config(config_path)
        click.echo("Configuration is valid.")
        click.echo(f"  Provider: {config.provider}")
        click.echo(f"  Origins: {[o.code for o in config.origins]}")
        click.echo(f"  Destinations: {[d.name for d in config.destinations]}")
        click.echo(f"  Routes: {len(config.origins) * len(config.destinations)} pairs")
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--days", default=90, help="Show trends for the last N days")
@click.option("--route", default=None, help="Filter to a specific route (e.g. BIO-BER)")
@click.pass_context
def trends(ctx: click.Context, days: int, route: str | None) -> None:
    """Show historical price trends per route."""
    config = load_config(ctx.obj["config_path"])
    db = PriceDatabase(config.storage.db_path)

    if route:
        parts = route.upper().split("-")
        if len(parts) != 2 or len(parts[0]) != 3 or len(parts[1]) != 3:
            click.echo("Invalid route format. Use ORIGIN-DEST (e.g. BIO-BER)", err=True)
            sys.exit(1)
        routes = [(parts[0], parts[1])]
    else:
        routes = db.get_all_routes()

    if not routes:
        click.echo("No price history found.")
        return

    for origin, dest in routes:
        stats = db.get_route_stats(
            RouteKey(origin_code=origin, destination_code=dest)
        )
        if stats.count == 0:
            continue

        click.echo(f"\n{origin} -> {dest}  ({stats.count} records)")
        click.echo(
            f"  Avg: EUR {stats.avg_price}  "
            f"Min: EUR {stats.min_price}  "
            f"Max: EUR {stats.max_price}"
        )

        trend = db.get_price_trend(origin, dest, last_n_days=days)
        if trend:
            click.echo(f"  Last {days} days:")
            for entry in trend:
                click.echo(
                    f"    {entry['date']}  "
                    f"avg {entry['avg_price']:.0f}  "
                    f"min {entry['min_price']:.0f}  "
                    f"({entry['count']} offers)"
                )


@cli.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Check prices for watched routes (date+route combos in config)."""
    config = load_config(ctx.obj["config_path"])
    if not config.watch_routes:
        click.echo("No watch_routes configured. Add them to config.yaml.")
        return

    provider = create_provider(config)
    flex = config.search.date_flex_days

    for wr in config.watch_routes:
        target = date.fromisoformat(wr.date)
        d_from = max(target - timedelta(days=flex), date.today())
        d_to = target + timedelta(days=flex)

        click.echo(f"\n{wr.origin} -> {wr.destination} on {wr.date}:")
        try:
            offers = provider.search_flights(
                origin=wr.origin,
                destination=wr.destination,
                date_from=d_from,
                date_to=d_to,
                adults=config.search.adults,
                currency=config.search.currency,
                max_stopovers=config.filters.max_stops,
                max_results=5,
                cabin_bag_only=config.filters.cabin_bag_only,
                flight_type=config.search.flight_type,
                nights_min=config.search.nights_min,
                nights_max=config.search.nights_max,
            )
        except Exception as e:
            click.echo(f"  Error: {e}", err=True)
            continue

        if not offers:
            click.echo("  No offers found.")
            continue

        offers.sort(key=lambda o: o.price)
        for o in offers[:5]:
            tag = "DIRECT" if o.is_direct else f"{o.stops} stop"
            price_alert = ""
            if wr.max_price and o.price <= wr.max_price:
                price_alert = " << UNDER TARGET"
            click.echo(
                f"  {o.currency} {o.price}  {tag}"
                f"  {o.departure_time:%Y-%m-%d %H:%M}"
                f"{price_alert}"
            )


@cli.command()
@click.option("--port", default=5555, help="Port to serve the dashboard on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.pass_context
def dashboard(ctx: click.Context, port: int, host: str) -> None:
    """Launch a web dashboard showing price history charts."""
    try:
        from flight_monitor.dashboard import create_app
    except ImportError:
        click.echo(
            "Flask is required for the dashboard. "
            "Install with: pip install flight-monitor[dashboard]",
            err=True,
        )
        sys.exit(1)

    app = create_app(ctx.obj["config_path"])
    click.echo(f"Dashboard running at http://{host}:{port}/")
    app.run(host=host, port=port, debug=False)
