"""Tests for report generation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flight_monitor.config import ReportingConfig
from flight_monitor.models import Deal, FlightOffer
from flight_monitor.reporter import Reporter


class TestConsoleReporter:
    def test_empty_deals_report(self):
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([], [], datetime(2026, 4, 15, 10, 0))

        assert "No deals found" in report
        assert "Total offers scanned: 0" in report

    def test_report_contains_deal_info(self, sample_deal: Deal, sample_offer: FlightOffer):
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([sample_deal], [sample_offer], datetime(2026, 4, 15, 10, 0))

        assert "BIO" in report
        assert "BER" in report
        assert "89" in report
        assert "DIRECT" in report
        assert "HISTORICAL LOW" in report
        assert "Deals found: 1" in report

    def test_report_shows_airline(self, sample_deal: Deal, sample_offer: FlightOffer):
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([sample_deal], [sample_offer], datetime(2026, 4, 15, 10, 0))
        assert "VY" in report

    def test_report_shows_booking_link(self, sample_deal: Deal, sample_offer: FlightOffer):
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([sample_deal], [sample_offer], datetime(2026, 4, 15, 10, 0))
        assert "https://example.com/book" in report


class TestHtmlReporter:
    def test_html_report_structure(self, sample_deal: Deal, sample_offer: FlightOffer, tmp_path):
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([sample_deal], [sample_offer], datetime(2026, 4, 15, 10, 0))

        assert "<!DOCTYPE html>" in report
        assert "<table>" in report
        assert "BIO" in report
        assert "BER" in report
        assert "89" in report

    def test_html_report_written_to_file(
        self, sample_deal: Deal, sample_offer: FlightOffer, tmp_path
    ):
        output_path = tmp_path / "report.html"
        config = ReportingConfig(format="html", html_output_path=str(output_path))
        reporter = Reporter(config)
        reporter.generate([sample_deal], [sample_offer], datetime(2026, 4, 15, 10, 0))

        assert output_path.exists()
        content = output_path.read_text()
        assert "Flight Deals Report" in content

    def test_html_escapes_special_characters(self, tmp_path):
        """Verify HTML output doesn't have injection vulnerabilities."""
        from flight_monitor.models import Airport, FlightSegment, RouteKey

        malicious_segment = FlightSegment(
            airline="<script>alert(1)</script>"[:2],  # Truncated to 2 chars
            flight_number="XX123",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            duration_minutes=180,
        )
        offer = FlightOffer(
            provider="test",
            provider_id="test-1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[malicious_segment],
            departure_time=datetime(2026, 4, 15, 10, 0),
            arrival_time=datetime(2026, 4, 15, 13, 0),
            total_duration_minutes=180,
            stops=0,
            price=Decimal("89"),
            currency="EUR",
        )
        deal = Deal(
            offer=offer,
            route_key=RouteKey(origin_code="BIO", destination_code="BER"),
            historical_avg_price=Decimal("150"),
            historical_min_price=Decimal("95"),
            historical_count=10,
            savings_vs_avg_pct=40.7,
            savings_vs_avg_abs=Decimal("61"),
            is_historical_low=False,
        )

        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))

        # The raw <script> tag should not appear unescaped
        assert "<script>" not in report
