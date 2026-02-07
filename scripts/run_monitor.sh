#!/usr/bin/env bash
# Flight price monitor cron wrapper script.
#
# Setup:
#   1. Copy config.example.yaml to ~/.flight_monitor/config.yaml and edit
#   2. Set KIWI_API_KEY in ~/.flight_monitor/.env
#   3. Add to crontab (every other Sunday at 9 AM):
#      0 9 */14 * 0 /path/to/scripts/run_monitor.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_DIR="${HOME}/.flight_monitor"
LOG_FILE="${CONFIG_DIR}/monitor.log"

# Ensure config directory exists
mkdir -p "$CONFIG_DIR"

# Source credentials if .env file exists
if [[ -f "${CONFIG_DIR}/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${CONFIG_DIR}/.env"
    set +a
fi

# Determine config path
CONFIG_PATH="${CONFIG_DIR}/config.yaml"
if [[ ! -f "$CONFIG_PATH" ]]; then
    CONFIG_PATH="${PROJECT_DIR}/config.yaml"
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "$(date -Iseconds) [ERROR] No config.yaml found" | tee -a "$LOG_FILE"
    exit 1
fi

# Run the monitor
echo "$(date -Iseconds) [INFO] Starting flight monitor..." | tee -a "$LOG_FILE"

if [[ -d "${PROJECT_DIR}/.venv" ]]; then
    "${PROJECT_DIR}/.venv/bin/flight-monitor" -c "$CONFIG_PATH" run --verbose \
        2>&1 | tee -a "$LOG_FILE"
else
    flight-monitor -c "$CONFIG_PATH" run --verbose \
        2>&1 | tee -a "$LOG_FILE"
fi

echo "$(date -Iseconds) [INFO] Flight monitor finished." | tee -a "$LOG_FILE"
