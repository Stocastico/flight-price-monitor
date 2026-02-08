"""Tests for report generation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from flight_monitor.config import EmailConfig, ReportingConfig
from flight_monitor.models import Airport, Deal, FlightOffer, FlightSegment, RouteKey
from flight_monitor.reporter import Reporter


def _make_deal(
    origin="BIO",
    destination="BER",
    price=89,
    stops=0,
    deep_link="https://example.com/book",
    is_historical_low=True,
    airline="VY",
    currency="EUR",
) -> tuple[Deal, FlightOffer]:
    dep = datetime(2026, 4, 15, 10, 0)
    arr = datetime(2026, 4, 15, 13, 0)
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
                duration_minutes=180,
            )
        )
    else:
        segments.append(
            FlightSegment(
                airline=airline,
                flight_number=f"{airline}100",
                origin=Airport(code=origin),
                destination=Airport(code="MAD"),
                departure_time=dep,
                arrival_time=datetime(2026, 4, 15, 11, 15),
                duration_minutes=75,
            )
        )
        segments.append(
            FlightSegment(
                airline=airline,
                flight_number=f"{airline}200",
                origin=Airport(code="MAD"),
                destination=Airport(code=destination),
                departure_time=datetime(2026, 4, 15, 13, 0),
                arrival_time=datetime(2026, 4, 15, 16, 0),
                duration_minutes=180,
            )
        )
    offer = FlightOffer(
        provider="kiwi",
        provider_id="test-1",
        origin=Airport(code=origin),
        destination=Airport(code=destination),
        segments=segments,
        departure_time=dep,
        arrival_time=arr if stops == 0 else datetime(2026, 4, 15, 16, 0),
        total_duration_minutes=180 if stops == 0 else 360,
        stops=stops,
        price=Decimal(str(price)),
        currency=currency,
        deep_link=deep_link,
    )
    deal = Deal(
        offer=offer,
        route_key=RouteKey(origin_code=origin, destination_code=destination),
        historical_avg_price=Decimal("150"),
        historical_min_price=Decimal("95"),
        historical_count=10,
        savings_vs_avg_pct=40.7,
        savings_vs_avg_abs=Decimal("61"),
        is_historical_low=is_historical_low,
    )
    return deal, offer


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

    def test_connecting_flight_shows_stops(self):
        """Connecting flights should show stop count."""
        deal, offer = _make_deal(stops=1)
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "1 stop(s)" in report
        assert "DIRECT" not in report

    def test_no_deep_link_omits_book_line(self):
        """Offer without deep_link should not have Book line."""
        deal, offer = _make_deal(deep_link="")
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "Book:" not in report

    def test_not_historical_low_no_marker(self):
        """Deal that is not a historical low should not show marker."""
        deal, offer = _make_deal(is_historical_low=False)
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "HISTORICAL LOW" not in report

    def test_multiple_deals_numbered(self):
        """Multiple deals should be numbered."""
        deal1, offer1 = _make_deal(price=89)
        deal2, offer2 = _make_deal(price=75, destination="BGY")
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate(
            [deal1, deal2], [offer1, offer2], datetime(2026, 4, 15, 10, 0)
        )
        assert "1." in report
        assert "2." in report
        assert "Deals found: 2" in report

    def test_duration_formatting(self):
        """Duration should show hours and minutes."""
        deal, offer = _make_deal()
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "3h00m" in report

    def test_offer_with_empty_segments_shows_na(self):
        """Offer with no segments should show N/A for airline."""
        offer = FlightOffer(
            provider="test",
            provider_id="t1",
            origin=Airport(code="BIO"),
            destination=Airport(code="BER"),
            segments=[],
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
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "N/A" in report

    def test_report_shows_currency(self):
        """Report should show the offer's currency."""
        deal, offer = _make_deal(currency="USD")
        config = ReportingConfig(format="console")
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "USD" in report


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

    def test_html_empty_deals(self, tmp_path):
        """HTML report with no deals should still produce valid HTML."""
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([], [], datetime(2026, 4, 15, 10, 0))
        assert "<!DOCTYPE html>" in report
        assert "Deals: 0" in report

    def test_html_connecting_flight(self, tmp_path):
        """HTML report should handle connecting flights."""
        deal, offer = _make_deal(stops=1)
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "1 stop(s)" in report

    def test_html_historical_low_marker(self, tmp_path):
        """HTML report should show LOWEST EVER for historical lows."""
        deal, offer = _make_deal(is_historical_low=True)
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "LOWEST EVER" in report

    def test_html_no_historical_low(self, tmp_path):
        """HTML report should not show LOWEST EVER when not a low."""
        deal, offer = _make_deal(is_historical_low=False)
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "LOWEST EVER" not in report

    def test_html_no_deep_link(self, tmp_path):
        """HTML should not have Book link when deep_link is empty."""
        deal, offer = _make_deal(deep_link="")
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "Book</a>" not in report

    def test_html_uses_offer_currency(self, tmp_path):
        """HTML should display the offer currency, not hardcoded EUR."""
        deal, offer = _make_deal(currency="GBP")
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(format="html", html_output_path=output_path)
        reporter = Reporter(config)
        report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
        assert "GBP" in report


class TestEmailReporter:
    def test_email_sent_on_html_with_deals(self, tmp_path):
        """Email should be sent when HTML format, email enabled, and deals exist."""
        deal, offer = _make_deal()
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(
            format="html",
            html_output_path=output_path,
            email=EmailConfig(
                enabled=True,
                smtp_host="smtp.example.com",
                smtp_port=587,
                sender="test@example.com",
                password="secret",
                recipients=["user@example.com"],
            ),
        )
        reporter = Reporter(config)

        with patch("flight_monitor.reporter.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("test@example.com", "secret")
            mock_server.send_message.assert_called_once()

    def test_email_not_sent_without_deals(self, tmp_path):
        """Email should NOT be sent when there are no deals."""
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(
            format="html",
            html_output_path=output_path,
            email=EmailConfig(
                enabled=True,
                smtp_host="smtp.example.com",
                sender="test@example.com",
                password="secret",
                recipients=["user@example.com"],
            ),
        )
        reporter = Reporter(config)

        with patch("flight_monitor.reporter.smtplib.SMTP") as mock_smtp:
            reporter.generate([], [], datetime(2026, 4, 15, 10, 0))
            mock_smtp.assert_not_called()

    def test_email_not_sent_when_disabled(self, tmp_path):
        """Email should NOT be sent when email is disabled."""
        deal, offer = _make_deal()
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(
            format="html",
            html_output_path=output_path,
            email=EmailConfig(enabled=False),
        )
        reporter = Reporter(config)

        with patch("flight_monitor.reporter.smtplib.SMTP") as mock_smtp:
            reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
            mock_smtp.assert_not_called()

    def test_email_failure_logged_not_raised(self, tmp_path):
        """Email send failure should be logged, not crash the program."""
        deal, offer = _make_deal()
        output_path = str(tmp_path / "report.html")
        config = ReportingConfig(
            format="html",
            html_output_path=output_path,
            email=EmailConfig(
                enabled=True,
                smtp_host="smtp.example.com",
                sender="test@example.com",
                password="secret",
                recipients=["user@example.com"],
            ),
        )
        reporter = Reporter(config)

        with patch("flight_monitor.reporter.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            mock_server.send_message.side_effect = ConnectionRefusedError("Connection refused")
            # Should not raise
            report = reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
            assert "<!DOCTYPE html>" in report

    def test_email_not_sent_for_console_format(self):
        """Email should not be sent when format is console."""
        deal, offer = _make_deal()
        config = ReportingConfig(
            format="console",
            email=EmailConfig(
                enabled=True,
                smtp_host="smtp.example.com",
                sender="test@example.com",
                password="secret",
                recipients=["user@example.com"],
            ),
        )
        reporter = Reporter(config)

        with patch("flight_monitor.reporter.smtplib.SMTP") as mock_smtp:
            reporter.generate([deal], [offer], datetime(2026, 4, 15, 10, 0))
            mock_smtp.assert_not_called()
