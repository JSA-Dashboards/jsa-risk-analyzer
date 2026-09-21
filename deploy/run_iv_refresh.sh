#!/usr/bin/env bash
# run_iv_refresh.sh — daily IV_SNAPSHOT refresh from CME DataMine, invoked by cron on the
# Droplet. Writes straight to Snowflake (JSA.RISK_ANALYZER.IV_SNAPSHOT); every deployed
# app reads that live, so there is no propagation step.
#
# TIMING. CME publishes three files per trade date (Central time):
#   Early       ~18:00  — carries NO implied vol, so it is useless here
#   Preliminary ~22:00  — full IV
#   Final       ~10:00 the next trade date — full IV, the record of truth
#
# The script always takes the newest file that is actually posted, Final before
# Preliminary. What that means depends on when cron fires:
#   18:00 run -> the PREVIOUS trade date's Final (today's Preliminary isn't out yet)
#   22:15 run -> today's Preliminary
#   10:15 run -> the previous trade date's Final
# Two jobs are installed, and they complement each other:
#   22:15 — today's Preliminary, so the dashboard has same-day vol overnight
#   18:00 — the previous trade date's Final, which supersedes that Preliminary
# The MERGE refuses to move a row backwards, so order never matters and a late file
# simply leaves the row as it was. If CME is running behind at 22:15 the run falls back
# to the newest posted file and rewrites the same values harmlessly.
#
# flock prevents overlapping runs. Cron installs this; adjust APP_DIR if deployed elsewhere.
set -uo pipefail

APP_DIR="/opt/jsa-risk-analyzer"
VENV="$APP_DIR/.venv"
LOG_DIR="$APP_DIR/logs"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/iv_refresh_$(date +%Y%m%d_%H%M%S).log"

cd "$APP_DIR" || { echo "APP_DIR $APP_DIR missing" >&2; exit 1; }

exec 9>"$LOG_DIR/.iv_refresh.lock"
if ! flock -n 9; then
    echo "$(date -Is) another run is in progress - skipping" >>"$LOG"
    exit 0
fi

rc=0
{
    echo "=== IV refresh start $(date -Is) ==="
    "$VENV/bin/python" scripts/refresh_iv_from_cme.py
    rc=$?
    echo "=== IV refresh finished $(date -Is) rc=$rc ==="
} >>"$LOG" 2>&1

# Keep 30 days of logs, matching the other droplet jobs.
find "$LOG_DIR" -name 'iv_refresh_*.log' -mtime +30 -delete 2>/dev/null || true

exit "$rc"
