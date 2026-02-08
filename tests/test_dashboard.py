"""Tests for the web dashboard."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from flight_monitor.config import load_config
from flight_monitor.dashboard import _build_route_data, create_app
from flight_monitor.models import Airport, FlightOffer, FlightSegment
from flight_monitor.storage.database import PriceDatabase


@pytest.fixture
def dashboard_config(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("KIWI_API_KEY", "test-key")
    db_path = str(tmp_path / "dash.db")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
provider: kiwi
credentials:
  kiwi:
    api_key: "${{KIWI_API_KEY}}"
origins:
  - code: BIO
destinations:
  - name: Berlin
    airports: [BER]
storage:
  db_path: "{db_path}"
"""
    )
    return config


@pytest.fixture
def seeded_db(dashboard_config) -> PriceDatabase:
    """Create a DB with some price history."""
    config = load_config(str(dashboard_config))
    db = PriceDatabase(config.storage.db_path)
    for i, price in enumerate([100, 120, 80, 95]):
        dep = datetime(2026, 2, 1 + i, 10, 0)
        seg = FlightSegment(
            airline="VY",
            flight_number=f"VY{i}",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            duration_minutes=180,
        )
        offer = FlightOffer(
            provider="kiwi",
            provider_id=f"dash-{i}",
            origin=seg.origin,
            destination=seg.destination,
            segments=[seg],
            departure_time=dep,
            arrival_time=dep.replace(hour=13),
            total_duration_minutes=180,
            stops=0,
            price=Decimal(str(price)),
            currency="EUR",
        )
        db.record_offers([offer])
    return db


class TestBuildRouteData:
    def test_empty_db(self, dashboard_config):
        config = load_config(str(dashboard_config))
        db = PriceDatabase(config.storage.db_path)
        routes = _build_route_data(db)
        assert routes == []

    def test_with_data(self, seeded_db):
        routes = _build_route_data(seeded_db)
        assert len(routes) == 1
        route = routes[0]
        assert route["origin"] == "BIO"
        assert route["dest"] == "BER"
        assert route["count"] == 4
        assert "labels" in route
        assert "avg_data" in route
        assert "min_data" in route


class TestDashboardApp:
    def test_index_page_empty(self, dashboard_config):
        app = create_app(str(dashboard_config))
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Flight Price Dashboard" in resp.data
        assert b"No price history" in resp.data

    def test_index_page_with_data(self, dashboard_config, seeded_db):
        app = create_app(str(dashboard_config))
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"BIO" in resp.data
        assert b"BER" in resp.data
        assert b"chart-BIO-BER" in resp.data

    def test_api_routes_endpoint(self, dashboard_config, seeded_db):
        app = create_app(str(dashboard_config))
        client = app.test_client()
        resp = client.get("/api/routes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["origin"] == "BIO"
        assert data[0]["count"] == 4

    def test_api_routes_empty(self, dashboard_config):
        app = create_app(str(dashboard_config))
        client = app.test_client()
        resp = client.get("/api/routes")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestDashboardCli:
    def test_dashboard_command_exists(self, dashboard_config):
        from click.testing import CliRunner

        from flight_monitor.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(dashboard_config), "dashboard", "--help"])
        assert result.exit_code == 0
        assert "dashboard" in result.output.lower()
        assert "--port" in result.output
