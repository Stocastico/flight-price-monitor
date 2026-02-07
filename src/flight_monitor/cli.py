"""CLI entry point for the flight price monitor."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from flight_monitor.config import load_config
from flight_monitor.monitor import FlightMonitor
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
