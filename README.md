# Flight Price Monitor

Monitor flight prices from Basque Country airports (BIO, EAS, VIT) to European and transatlantic destinations, and detect deals substantially cheaper than historical averages.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
  - [API Keys](#api-keys)
  - [Origins and Destinations](#origins-and-destinations)
  - [Search Parameters](#search-parameters)
  - [Filters](#filters)
  - [Deal Detection](#deal-detection)
  - [Reporting](#reporting)
  - [Environment Variables](#environment-variables)
- [Usage](#usage)
  - [Running a Monitor Cycle](#running-a-monitor-cycle)
  - [Validating Configuration](#validating-configuration)
  - [Purging Old Data](#purging-old-data)
- [Automated Scheduling](#automated-scheduling)
  - [Cron Setup](#cron-setup)
  - [Credential Management](#credential-management)
- [Architecture](#architecture)
  - [Module Overview](#module-overview)
  - [Data Flow](#data-flow)
  - [Provider System](#provider-system)
  - [Deal Detection Algorithm](#deal-detection-algorithm)
  - [Database Schema](#database-schema)
- [Development](#development)
  - [Setting Up Dev Environment](#setting-up-dev-environment)
  - [Running Tests](#running-tests)
  - [Code Quality](#code-quality)
  - [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Features

- **Multi-provider support**: Kiwi Tequila API (primary) and Amadeus Self-Service API (secondary), with an abstract provider interface for adding more
- **Smart deal detection**: Compares current prices against historical averages stored in SQLite; flags deals that are 25%+ below average (configurable threshold)
- **Flexible filtering**: Filter by maximum flight duration, departure time window, specific airlines (allow/block lists), and number of stops
- **Direct flight priority**: Automatically ranks nonstop flights above connecting flights in results
- **Dual reporting**: Console output for terminal usage and HTML reports for browser viewing, with optional email delivery via SMTP
- **Historical tracking**: Stores every price observation in a local SQLite database for trend analysis over time
- **Cron-ready**: Designed to run unattended every couple of weeks via cron or systemd timers
- **Environment variable support**: Credentials and secrets are loaded from environment variables, never stored in config files

## Requirements

- Python 3.11 or later
- A free API key from [Kiwi Tequila](https://tequila.kiwi.com/) (primary provider) or [Amadeus for Developers](https://developers.amadeus.com/) (alternative provider)

## Installation

```bash
# Clone the repository
git clone https://github.com/Stocastico/Claude-code-experiments.git
cd Claude-code-experiments

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package
pip install -e .

# For development (includes pytest, ruff, mypy)
pip install -e ".[dev]"

# For Amadeus provider support (optional)
pip install -e ".[amadeus]"
```

After installation, the `flight-monitor` command is available in your shell.

## Configuration

The tool is driven by a YAML configuration file. Start by copying the example:

```bash
cp config.example.yaml config.yaml
```

### API Keys

The Kiwi Tequila API is the recommended provider. Sign up at [tequila.kiwi.com](https://tequila.kiwi.com/) to get a free API key.

```yaml
provider: kiwi  # or "amadeus"

credentials:
  kiwi:
    api_key: "${KIWI_API_KEY}"  # loaded from environment variable
  # amadeus:
  #   client_id: "${AMADEUS_CLIENT_ID}"
  #   client_secret: "${AMADEUS_CLIENT_SECRET}"
```

Set your API key as an environment variable:

```bash
export KIWI_API_KEY="your-api-key-here"
```

### Origins and Destinations

Configure which airports to search from and to:

```yaml
origins:
  - code: BIO    # Bilbao
    city: Bilbao
  - code: EAS    # San Sebastián
    city: San Sebastián
  - code: VIT    # Vitoria
    city: Vitoria

destinations:
  - name: Berlin
    airports: [BER]           # Multiple airport codes are supported
  - name: London
    airports: [LHR, LGW, STN, LTN]  # All London airports
  - name: Verona
    airports: [VRN]
  - name: Bergamo
    airports: [BGY]
  - name: Milan Linate
    airports: [LIN]
  - name: New York
    airports: [JFK, EWR]
```

When using the Kiwi provider, multiple airport codes per destination are sent as a single comma-separated query (efficient). With Amadeus, each airport is queried individually.

### Search Parameters

```yaml
search:
  date_range_days: 90     # Look for flights departing within the next 90 days
  currency: EUR            # Currency for prices (EUR, USD, GBP, etc.)
  adults: 1                # Number of passengers
  max_results_per_route: 50  # Max offers to fetch per origin-destination pair
```

### Filters

All filters are applied after fetching results from the API:

```yaml
filters:
  prefer_direct: true              # Sort direct flights before connecting flights
  max_stops: 1                     # Maximum number of connections (0 = direct only)
  max_duration_minutes: 600        # Maximum total travel time (600 = 10 hours)
  departure_time_earliest: "06:00" # Earliest acceptable departure time
  departure_time_latest: "22:00"   # Latest acceptable departure time
  allowed_airlines: []             # Empty = all airlines; e.g., ["VY", "FR", "IB"]
  excluded_airlines: []            # Airlines to exclude; e.g., ["FR"] to skip Ryanair
```

**Filter examples:**

- Direct flights only departing 8-18h: `max_stops: 0`, `departure_time_earliest: "08:00"`, `departure_time_latest: "18:00"`
- Only Vueling and Iberia: `allowed_airlines: ["VY", "IB"]`
- Everything except Ryanair: `excluded_airlines: ["FR"]`
- Short-haul under 4 hours: `max_duration_minutes: 240`

### Deal Detection

The analyzer compares current prices against historical data:

```yaml
analysis:
  deal_threshold_pct: 25   # Flag as deal if >= 25% below historical average
  min_history_count: 3     # Need at least 3 historical observations before judging
```

Deals are detected by comparing each offer's price against the average of all previously observed prices for the same route. If a route doesn't have enough history, the tool falls back to comparing against all airports in the same destination group (e.g., all London airports combined).

On the first few runs, no deals will be detected because the database doesn't yet have enough historical data. After 3+ runs (configurable via `min_history_count`), the system starts identifying anomalies.

### Reporting

```yaml
reporting:
  format: console   # "console" for terminal output, "html" for browser-viewable report

  # Only used when format is "html"
  html_output_path: "/tmp/flight_deals_report.html"

  # Optional email delivery of HTML reports
  email:
    enabled: false
    smtp_host: smtp.gmail.com
    smtp_port: 587
    sender: "you@gmail.com"
    password: "${SMTP_PASSWORD}"   # env var, never put real password here
    recipients:
      - "recipient@example.com"
```

### Environment Variables

The configuration file supports `${VAR_NAME}` syntax for environment variable interpolation. This keeps secrets out of the config file:

| Variable | Required | Description |
|----------|----------|-------------|
| `KIWI_API_KEY` | Yes (if using Kiwi) | Kiwi Tequila API key |
| `AMADEUS_CLIENT_ID` | Yes (if using Amadeus) | Amadeus API client ID |
| `AMADEUS_CLIENT_SECRET` | Yes (if using Amadeus) | Amadeus API client secret |
| `SMTP_PASSWORD` | Only if email enabled | SMTP password for email delivery |

Environment variables in disabled sections (like email when `enabled: false`) are safely ignored even if unset.

## Usage

### Running a Monitor Cycle

```bash
# Basic run
flight-monitor -c config.yaml run

# With verbose logging (debug output)
flight-monitor -c config.yaml --verbose run
```

A full run:
1. Searches all origin-destination pairs via the configured API
2. Applies configured filters (stops, duration, time, airline)
3. Compares prices against historical averages
4. Stores current prices in the SQLite database
5. Generates a report of any deals found

**Exit codes:**
- `0` - Deals found
- `1` - No deals found (normal operation)
- `2+` - Error occurred

Example console output:

```
=== Flight Monitor Report - 2026-02-07 09:00 ===
Total offers scanned: 127
Deals found: 3

1. BIO -> BGY  EUR 29 [DIRECT]  (42% below avg EUR 50) *** HISTORICAL LOW ***
   Departs: 2026-03-15 06:30  Duration: 1h45m  Airline: FR
   Book: https://www.kiwi.com/booking?token=...

2. BIO -> BER  EUR 65 [DIRECT]  (35% below avg EUR 100)
   Departs: 2026-04-02 10:30  Duration: 2h50m  Airline: VY

3. EAS -> LGW  EUR 48 [1 stop(s)]  (28% below avg EUR 67)
   Departs: 2026-03-20 08:00  Duration: 5h30m  Airline: IB
```

### Validating Configuration

Check your config file for errors without running a search:

```bash
flight-monitor -c config.yaml validate
```

Output:

```
Configuration is valid.
  Provider: kiwi
  Origins: ['BIO', 'EAS', 'VIT']
  Destinations: ['Berlin', 'London', 'Verona', 'Bergamo', 'Milan Linate', 'New York']
  Routes: 18 pairs
```

### Purging Old Data

Remove historical price records older than a given number of days:

```bash
# Purge records older than 1 year (default)
flight-monitor -c config.yaml purge

# Purge records older than 6 months
flight-monitor -c config.yaml purge --days 180
```

## Automated Scheduling

### Cron Setup

The included `scripts/run_monitor.sh` wrapper script handles environment setup and logging:

```bash
# Make it executable
chmod +x scripts/run_monitor.sh

# Add to crontab: runs on the 1st and 15th of each month at 9 AM
crontab -e
# Add this line:
0 9 1,15 * * /path/to/Claude-code-experiments/scripts/run_monitor.sh
```

### Credential Management

For automated runs, store credentials in `~/.flight_monitor/.env`:

```bash
mkdir -p ~/.flight_monitor

cat > ~/.flight_monitor/.env << 'EOF'
KIWI_API_KEY=your-api-key-here
EOF

chmod 600 ~/.flight_monitor/.env
```

The cron wrapper script automatically sources this file. You can also place a `config.yaml` in `~/.flight_monitor/` for the cron script to pick up.

Logs are appended to `~/.flight_monitor/monitor.log`.

## Architecture

### Module Overview

```
src/flight_monitor/
  __init__.py           # Package version
  models.py             # Pydantic data models (Airport, FlightOffer, Deal, RouteKey)
  config.py             # YAML config loading with env var interpolation
  cli.py                # Click CLI (run, validate, purge commands)
  monitor.py            # Orchestrator: search -> filter -> analyze -> record -> report
  filters.py            # Configurable flight filtering (stops, time, duration, airline)
  analyzer.py           # Deal detection via historical price comparison
  reporter.py           # Console + HTML report generation, email delivery
  providers/
    base.py             # Abstract FlightSearchProvider interface
    factory.py          # Provider factory (instantiate by config name)
    kiwi.py             # Kiwi Tequila API implementation
    amadeus_provider.py # Amadeus Self-Service API implementation
  storage/
    database.py         # SQLite storage for historical prices
```

### Data Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Provider │ --> │ Filters  │ --> │ Analyzer │ --> │ Database │ --> │ Reporter │
│ (API)    │     │          │     │          │     │ (SQLite) │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
      │                │                │                │                │
  Fetch offers    Apply user       Compare vs       Store current    Generate
  from API        filters         historical avg    prices for       deal report
                                                    future runs
```

The analyzer runs **before** recording to the database, preventing the current batch from polluting its own historical comparison.

### Provider System

The tool uses an abstract provider interface (`FlightSearchProvider`) that can be implemented for any flight search API:

```python
class FlightSearchProvider(ABC):
    def search_flights(self, origin, destination, date_from, date_to, ...) -> list[FlightOffer]: ...
    def name(self) -> str: ...
```

**Kiwi Tequila** (recommended):
- Supports comma-separated destination codes in a single query
- Returns booking deep links
- Free personal-use tier
- Uses `dd/mm/YYYY` date format

**Amadeus Self-Service**:
- Requires per-date queries (iterates in 7-day steps)
- OAuth2 handled by the SDK
- Free test tier (~2000 calls/month)
- Requires separate `pip install flight-monitor[amadeus]`

### Deal Detection Algorithm

1. For each filtered offer, look up the route's historical average price
2. If insufficient history for the specific airport pair, fall back to the destination group average (e.g., all London airports)
3. If still insufficient history (`< min_history_count`), skip the offer
4. Calculate `savings_pct = (avg_price - current_price) / avg_price * 100`
5. If `savings_pct >= deal_threshold_pct`, flag it as a deal
6. If `current_price <= historical_min`, mark it as a historical low

### Database Schema

The SQLite database (`~/.flight_monitor/prices.db`) stores one row per price observation:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-incrementing primary key |
| `route_origin` | TEXT | Origin IATA code (e.g., "BIO") |
| `route_dest` | TEXT | Destination IATA code (e.g., "BER") |
| `price` | REAL | Price in configured currency |
| `currency` | TEXT | Currency code |
| `stops` | INTEGER | Number of stops (0 = direct) |
| `airline` | TEXT | Primary airline IATA code |
| `departure_date` | TEXT | Flight departure date (ISO format) |
| `observed_at` | TEXT | When the price was recorded (ISO datetime) |
| `provider` | TEXT | Which API returned this offer |
| `provider_id` | TEXT | Provider's unique offer identifier |

Indexed on `(route_origin, route_dest)` and `observed_at` for fast aggregation queries.

## Development

### Setting Up Dev Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=flight_monitor --cov-report=term-missing

# Run a specific test file
pytest tests/test_filters.py

# Run a specific test class or method
pytest tests/test_filters.py::TestFlightFilter::test_filters_by_max_stops
```

### Code Quality

```bash
# Lint
ruff check src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/

# Format
ruff format src/ tests/

# Type checking
mypy src/flight_monitor/
```

### Project Structure

```
Claude-code-experiments/
  pyproject.toml            # Build config, dependencies, tool settings
  config.example.yaml       # Example configuration file
  README.md                 # This file
  scripts/
    run_monitor.sh          # Cron wrapper script
  src/
    flight_monitor/         # Source package
      ...
  tests/
    conftest.py             # Shared pytest fixtures
    fixtures/
      kiwi_search_response.json  # Sample API response for testing
    test_models.py
    test_config.py
    test_filters.py
    test_analyzer.py
    test_storage.py
    test_reporter.py
    test_monitor.py
    test_cli.py
    test_providers/
      test_kiwi.py
      test_amadeus.py
      test_factory.py
```

## Troubleshooting

**"Environment variable KIWI_API_KEY is not set"**
Set the variable before running: `export KIWI_API_KEY="your-key"`. For cron, put it in `~/.flight_monitor/.env`.

**"Config file not found"**
Provide the path explicitly: `flight-monitor -c /path/to/config.yaml run`

**No deals found after first run**
This is normal. The tool needs at least `min_history_count` observations (default: 3) before it can detect deals. Run it a few times to build up historical data.

**Amadeus ImportError**
Install the optional Amadeus dependency: `pip install flight-monitor[amadeus]`

**HTML report not generated**
Set `reporting.format: html` in your config and check `html_output_path` points to a writable location.

**Cron job not producing output**
Check `~/.flight_monitor/monitor.log` for errors. Ensure the `.env` file exists and contains valid credentials. Verify the `--verbose` flag is placed before the `run` subcommand.
