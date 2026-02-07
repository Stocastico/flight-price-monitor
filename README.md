# Flight Price Monitor

Monitor flight prices from Basque Country airports (BIO, EAS, VIT) to European and transatlantic destinations, and detect deals substantially cheaper than historical averages.

## Features

- **Multi-provider support**: Kiwi Tequila API (primary) and Amadeus Self-Service API
- **Smart deal detection**: Compares current prices against historical averages stored in SQLite
- **Flexible filtering**: Filter by max duration, departure time window, airline, and number of stops
- **Direct flight priority**: Automatically ranks nonstop flights higher
- **Dual reporting**: Console output and HTML reports with optional email delivery
- **Cron-ready**: Designed to run biweekly via cron

## Quick Start

```bash
# Install
pip install -e .

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your API key (get one from https://tequila.kiwi.com/)

# Set credentials
export KIWI_API_KEY="your-api-key-here"

# Run
flight-monitor -c config.yaml run

# Validate config
flight-monitor -c config.yaml validate
```

## Monitored Routes

**Origins**: Bilbao (BIO), San Sebastián (EAS), Vitoria (VIT)

**Destinations**: Berlin, London, Verona, Bergamo, Milan Linate, New York

## Cron Setup

```bash
# Run every other Sunday at 9 AM
0 9 */14 * 0 /path/to/scripts/run_monitor.sh
```
