# CLAUDE.md - Development Guide for Flight Price Monitor

## Project Overview

Flight price monitor that tracks prices from Basque Country airports (BIO, EAS, VIT) to European/transatlantic destinations. Detects deals cheaper than historical averages and sends notifications via console, email, or Telegram.

## Quick Reference

### Build & Run

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Install optional providers/features
pip install -e ".[amadeus]"     # Amadeus provider
pip install -e ".[dashboard]"   # Flask web dashboard

# Run the monitor
flight-monitor -c config.yaml run
flight-monitor -c config.yaml --verbose run

# Other commands
flight-monitor -c config.yaml validate
flight-monitor -c config.yaml trends --days 30
flight-monitor -c config.yaml watch
flight-monitor -c config.yaml purge --days 365
flight-monitor -c config.yaml dashboard --port 5555
```

### Test & Lint

```bash
# Run all tests (dashboard tests require flask)
pytest
pytest --cov=flight_monitor --cov-report=term-missing

# Lint and format
ruff check src/ tests/
ruff check --fix src/ tests/
ruff format src/ tests/

# Type checking
mypy src/flight_monitor/
```

### Key Settings

- **Python**: 3.11+
- **Line length**: 100 (ruff)
- **Type checking**: strict mypy
- **Ruff rules**: E, F, W, I, N, UP, B, SIM, RUF
- **Test runner**: pytest with `tests/` path and `src/` in pythonpath

## Architecture

```
CLI (click) → FlightMonitor (orchestrator)
  ├─ Provider (Kiwi/Amadeus/SerpAPI) → fetches offers
  ├─ FlightFilter → applies user filters
  ├─ PriceAnalyzer → compares vs historical avg
  ├─ PriceDatabase (SQLite) → stores prices
  └─ Reporter → console/HTML/email/Telegram
```

### Key Design Decisions

- **Analyze before record**: Deals are detected BEFORE storing current prices, so current batch doesn't pollute its own comparison
- **Provider pattern**: Abstract `FlightSearchProvider` base class — add new providers by subclassing and registering in `factory.py`
- **Env var interpolation**: Config YAML uses `${VAR_NAME}` syntax; disabled sections (email/telegram) use lenient mode that ignores unset vars
- **Deduplication**: SQLite partial unique index on `(provider, provider_id)` prevents duplicate offers across runs
- **Retry with backoff**: `retry.py` utility wraps API calls and notifications with configurable exponential backoff

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `models.py` | Pydantic data models: Airport, FlightSegment, FlightOffer, Deal, RouteKey |
| `config.py` | YAML loading, env var interpolation, Pydantic config models |
| `cli.py` | Click CLI commands: run, validate, purge, trends, watch, dashboard |
| `monitor.py` | Orchestrator: coordinates search → filter → analyze → record → report |
| `filters.py` | Post-fetch filtering: stops, duration, time, airlines, cabin bag |
| `analyzer.py` | Deal detection: compares prices vs historical avg/min |
| `reporter.py` | Report generation: console text, HTML, email (SMTP), Telegram bot |
| `retry.py` | Retry utility with exponential backoff for transient failures |
| `dashboard.py` | Flask web dashboard with Chart.js price trend charts |
| `providers/base.py` | Abstract FlightSearchProvider + ProviderError |
| `providers/factory.py` | `create_provider()` factory function |
| `providers/kiwi.py` | Kiwi Tequila API (primary, supports comma-separated destinations) |
| `providers/amadeus_provider.py` | Amadeus Self-Service API (per-date queries, 7-day steps) |
| `providers/serpapi_provider.py` | Google Flights via SerpAPI |
| `storage/database.py` | SQLite: record_offers, get_route_stats, purge, trends |

### Database Schema

Table `price_history` in `~/.flight_monitor/prices.db`:
- Columns: id, route_origin, route_dest, price, currency, stops, airline, departure_date, observed_at, provider, provider_id
- Indexes: `idx_route` (origin, dest), `idx_observed` (observed_at), `idx_provider_dedup` (provider, provider_id) UNIQUE partial

## Adding a New Flight Provider

1. Create `src/flight_monitor/providers/new_provider.py`
2. Subclass `FlightSearchProvider` from `providers/base.py`
3. Implement `search_flights()` → returns `list[FlightOffer]` sorted by price
4. Implement `name()` → returns provider string identifier
5. Register in `providers/factory.py` `create_provider()` function
6. Add credentials model to `config.py` `CredentialsConfig`
7. Add tests in `tests/test_providers/test_new_provider.py`
8. Use `retry_on_exception()` from `retry.py` for HTTP calls
9. Add optional dependency to `pyproject.toml` if needed

## Common Patterns

- **Error handling**: Providers raise `ProviderError(provider, status_code, message)`. The orchestrator catches these per-route and continues.
- **Notifications**: Reporter catches delivery failures (email/Telegram) and logs them without crashing the run.
- **Config sections**: Use lenient env var interpolation for optional sections. Check `enabled` flag before sending.
- **Testing HTTP**: Use the `responses` library to mock HTTP calls. See `tests/test_providers/test_kiwi.py` for examples.
- **Fixtures**: Shared fixtures in `tests/conftest.py` (sample_offer, sample_deal, sample_config).

## CI/CD

- **GitHub Actions**: `.github/workflows/monitor.yml` runs the monitor on a cron schedule (1st/15th at 09:00 UTC)
- SQLite database persisted between runs via GitHub Actions artifacts
- Secrets configured in repo Settings > Secrets: KIWI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SMTP_PASSWORD

## Potential Future Work

- Async I/O (aiohttp) for concurrent route searches
- Multi-provider fallback (try Kiwi, fall back to SerpAPI)
- Jinja2 templates for HTML reports
- Price prediction / trend analysis
- Webhook notifications (Slack, Discord, IFTTT)
- Docker image for cloud deployment
- Database migrations for schema evolution
- Skyscanner/Ryanair provider integrations (see README for API status)
