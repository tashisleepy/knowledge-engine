#!/usr/bin/env bash
# watch-claude-desktop.sh
# Polled by LaunchAgent every 3 minutes.
# Detects when Claude Desktop app transitions from RUNNING -> NOT RUNNING.
# On detected quit, fires on-session-end.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$HOME/.cache/claude-desktop-state"
LOG_FILE="$HOME/.cache/claude-capture-log.txt"

mkdir -p "$(dirname "$STATE_FILE")"

NOW="$(date '+%Y-%m-%d %H:%M')"

# Check if Claude.app is running (matches both "Claude" and "Claude Helper" processes)
if pgrep -fi "Claude.app/Contents/MacOS/Claude" > /dev/null 2>&1; then
  CURRENT_STATE="running"
else
  CURRENT_STATE="stopped"
fi

# Load previous state
PREV_STATE="unknown"
[[ -f "$STATE_FILE" ]] && PREV_STATE=$(cat "$STATE_FILE")

# Transition detection
if [[ "$PREV_STATE" == "running" && "$CURRENT_STATE" == "stopped" ]]; then
  echo "[$NOW] Claude Desktop quit detected (was $PREV_STATE, now $CURRENT_STATE)" >> "$LOG_FILE"
  "$SCRIPT_DIR/on-session-end.sh" >> "$LOG_FILE" 2>&1 || true
fi

# Save current state for next poll
echo "$CURRENT_STATE" > "$STATE_FILE"
