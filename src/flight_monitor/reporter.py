"""Report generation for flight deals (console, HTML, and Telegram)."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

import requests

from flight_monitor.config import ReportingConfig
from flight_monitor.models import Deal, FlightOffer
from flight_monitor.retry import retry_on_exception

logger = logging.getLogger(__name__)


class Reporter:
    """Generate deal reports in console or HTML format."""

    def __init__(self, config: ReportingConfig):
        self._config = config

    def generate(
        self,
        deals: list[Deal],
        all_offers: list[FlightOffer],
        run_timestamp: datetime,
    ) -> str:
        """Generate report and return the report text."""
        if self._config.format == "html":
            report = self._generate_html(deals, all_offers, run_timestamp)
            path = Path(self._config.html_output_path)
            path.write_text(report, encoding="utf-8")
            logger.info("HTML report written to %s", path)
            if self._config.email.enabled and deals:
                self._send_email(report, run_timestamp)
        else:
            report = self._generate_console(deals, all_offers, run_timestamp)

        if self._config.telegram.enabled and deals:
            self._send_telegram(deals)

        return report

    def _generate_console(
        self,
        deals: list[Deal],
        all_offers: list[FlightOffer],
        run_timestamp: datetime,
    ) -> str:
        lines: list[str] = []
        lines.append(f"=== Flight Monitor Report - {run_timestamp:%Y-%m-%d %H:%M} ===")
        lines.append(f"Total offers scanned: {len(all_offers)}")
        lines.append(f"Deals found: {len(deals)}")
        lines.append("")

        if not deals:
            lines.append("No deals found this run. Prices are at or above average.")
            return "\n".join(lines)

        for i, deal in enumerate(deals, 1):
            o = deal.offer
            direct_tag = " [DIRECT]" if o.is_direct else f" [{o.stops} stop(s)]"
            hist_low = " *** HISTORICAL LOW ***" if deal.is_historical_low else ""
            lines.append(
                f"{i}. {o.origin.code} -> {o.destination.code}"
                f"  {o.currency} {o.price}{direct_tag}"
                f"  ({deal.savings_vs_avg_pct:.0f}% below avg"
                f" {o.currency} {deal.historical_avg_price})"
                f"{hist_low}"
            )
            hours = o.total_duration_minutes // 60
            mins = o.total_duration_minutes % 60
            lines.append(
                f"   Departs: {o.departure_time:%Y-%m-%d %H:%M}"
                f"  Duration: {hours}h{mins:02d}m"
                f"  Airline: {o.segments[0].airline if o.segments else 'N/A'}"
            )
            if o.deep_link:
                lines.append(f"   Book: {o.deep_link}")
            lines.append("")

        return "\n".join(lines)

    def _generate_html(
        self,
        deals: list[Deal],
        all_offers: list[FlightOffer],
        run_timestamp: datetime,
    ) -> str:
        rows_html = ""
        for deal in deals:
            o = deal.offer
            badge = "DIRECT" if o.is_direct else f"{o.stops} stop(s)"
            low_marker = (
                '<span style="color:red;font-weight:bold;">LOWEST EVER</span>'
                if deal.is_historical_low
                else ""
            )
            link = f'<a href="{escape(o.deep_link)}">Book</a>' if o.deep_link else ""
            rows_html += (
                "<tr>"
                f"<td>{escape(o.origin.code)} &rarr; {escape(o.destination.code)}</td>"
                f"<td><strong>{escape(o.currency)} {o.price}</strong></td>"
                f"<td>{escape(badge)}</td>"
                f"<td>{deal.savings_vs_avg_pct:.0f}% below avg"
                f" ({escape(o.currency)} {deal.historical_avg_price})</td>"
                f"<td>{o.departure_time:%Y-%m-%d %H:%M}</td>"
                f"<td>{escape(o.segments[0].airline) if o.segments else ''}</td>"
                f"<td>{low_marker} {link}</td>"
                "</tr>\n"
            )

        return (
            "<!DOCTYPE html>\n"
            '<html><head><meta charset="utf-8">\n'
            f"<title>Flight Deals - {run_timestamp:%Y-%m-%d}</title>\n"
            "<style>\n"
            "  body { font-family: sans-serif; margin: 20px; }\n"
            "  table { border-collapse: collapse; width: 100%; }\n"
            "  th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }\n"
            "  th { background: #4a90d9; color: white; }\n"
            "  tr:nth-child(even) { background: #f2f2f2; }\n"
            "</style></head><body>\n"
            "<h1>Flight Deals Report</h1>\n"
            f"<p>Generated: {run_timestamp:%Y-%m-%d %H:%M}"
            f" | Offers scanned: {len(all_offers)}"
            f" | Deals: {len(deals)}</p>\n"
            "<table>\n"
            "<tr><th>Route</th><th>Price</th><th>Stops</th>"
            "<th>vs History</th><th>Departure</th><th>Airline</th>"
            "<th>Notes</th></tr>\n"
            f"{rows_html}"
            "</table></body></html>"
        )

    def _send_email(self, html_body: str, run_timestamp: datetime) -> None:
        cfg = self._config.email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Flight Deals - {run_timestamp:%Y-%m-%d}"
        msg["From"] = cfg.sender
        msg["To"] = ", ".join(cfg.recipients)
        msg.attach(MIMEText(html_body, "html"))

        def _do_send() -> None:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
                server.starttls()
                server.login(cfg.sender, cfg.password)
                server.send_message(msg)

        try:
            retry_on_exception(
                _do_send,
                max_retries=3,
                base_delay=2.0,
                retryable=(OSError, smtplib.SMTPException),
                description="email delivery",
            )
            logger.info("Email sent to %s", cfg.recipients)
        except (OSError, smtplib.SMTPException):
            logger.exception("Failed to send email after retries")

    def _send_telegram(self, deals: list[Deal]) -> None:
        """Send deal summary to Telegram via Bot API."""
        cfg = self._config.telegram
        text = self._format_telegram(deals)
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"

        def _do_send() -> None:
            resp = requests.post(
                url,
                json={"chat_id": cfg.chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=15,
            )
            if not resp.ok:
                if resp.status_code >= 500:
                    raise requests.HTTPError(
                        f"Telegram server error {resp.status_code}", response=resp
                    )
                logger.warning(
                    "Telegram API returned %s: %s", resp.status_code, resp.text[:200]
                )

        try:
            retry_on_exception(
                _do_send,
                max_retries=3,
                base_delay=2.0,
                retryable=(OSError, requests.RequestException),
                description="Telegram notification",
            )
            logger.info("Telegram message sent to chat %s", cfg.chat_id)
        except (OSError, requests.RequestException):
            logger.exception("Failed to send Telegram message after retries")

    @staticmethod
    def _format_telegram(deals: list[Deal]) -> str:
        """Format deals as a compact Telegram message."""
        lines = [f"*Flight Deals* ({len(deals)} found)\n"]
        for deal in deals[:10]:  # Cap at 10 to stay under Telegram limits
            o = deal.offer
            direct = "direct" if o.is_direct else f"{o.stops} stop"
            low = " NEW LOW" if deal.is_historical_low else ""
            lines.append(
                f"  {o.origin.code} > {o.destination.code}"
                f"  *{o.currency} {o.price}*  ({direct})"
                f"  -{deal.savings_vs_avg_pct:.0f}%{low}"
            )
            airline = o.segments[0].airline if o.segments else ""
            lines.append(f"  {o.departure_time:%b %d %H:%M}  {airline}")
            if o.deep_link:
                lines.append(f"  [Book]({o.deep_link})")
            lines.append("")
        return "\n".join(lines)
