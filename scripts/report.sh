#!/usr/bin/env bash
# Knowledge Engine - Date-Range Activity Report Generator
# Generates work reports from log.md filtered by date range.
#
# Usage:
#   ./scripts/report.sh --week        Last 7 days
#   ./scripts/report.sh --month       Last 30 days
#   ./scripts/report.sh --quarter     Last 90 days
#   ./scripts/report.sh --year        Last 365 days
#   ./scripts/report.sh --since 2026-04-01
#   ./scripts/report.sh --between 2026-04-01 2026-04-14
#   ./scripts/report.sh --client my-client --month
#   ./scripts/report.sh --client my-client --since 2026-04-01
#
# Output: Markdown report to stdout. Pipe to file if needed.
#
# Reads from: ./log.md (Knowledge Engine activity log)
# Filters by: date prefix in log entries (## [YYYY-MM-DD ...] format)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$ROOT_DIR/log.md"

if [[ ! -f "$LOG_FILE" ]]; then
  echo "ERROR: log.md not found at $LOG_FILE" >&2
  exit 1
fi

# Default values
START_DATE=""
END_DATE="$(date '+%Y-%m-%d')"
CLIENT_FILTER=""
LABEL=""

usage() {
  cat <<'EOF'
Knowledge Engine Activity Report Generator

Usage:
  ./scripts/report.sh [TIME_RANGE] [OPTIONS]

Time Range (pick one):
  --week                Last 7 days
  --month               Last 30 days
  --quarter             Last 90 days
  --year                Last 365 days
  --since YYYY-MM-DD    Since specific date
  --between START END   Between two dates (inclusive)

Options:
  --client SLUG         Filter by client slug (matches Client: field or wiki path)
  --help                Show this message

Examples:
  ./scripts/report.sh --week
  ./scripts/report.sh --month --client my-client
  ./scripts/report.sh --since 2026-04-01
  ./scripts/report.sh --between 2026-01-01 2026-03-31

Output: Markdown formatted report to stdout.
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --week)
      START_DATE="$(date -v-7d '+%Y-%m-%d' 2>/dev/null || date -d '7 days ago' '+%Y-%m-%d')"
      LABEL="Last 7 Days"
      shift
      ;;
    --month)
      START_DATE="$(date -v-30d '+%Y-%m-%d' 2>/dev/null || date -d '30 days ago' '+%Y-%m-%d')"
      LABEL="Last 30 Days"
      shift
      ;;
    --quarter)
      START_DATE="$(date -v-90d '+%Y-%m-%d' 2>/dev/null || date -d '90 days ago' '+%Y-%m-%d')"
      LABEL="Last 90 Days"
      shift
      ;;
    --year)
      START_DATE="$(date -v-365d '+%Y-%m-%d' 2>/dev/null || date -d '365 days ago' '+%Y-%m-%d')"
      LABEL="Last 365 Days"
      shift
      ;;
    --since)
      START_DATE="$2"
      LABEL="Since $2"
      shift 2
      ;;
    --between)
      START_DATE="$2"
      END_DATE="$3"
      LABEL="$2 to $3"
      shift 3
      ;;
    --client)
      CLIENT_FILTER="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$START_DATE" ]]; then
  echo "ERROR: Specify a time range. Use --help for options." >&2
  exit 1
fi

# Header
echo "# Knowledge Engine Activity Report"
echo "## Period: $LABEL ($START_DATE to $END_DATE)"
if [[ -n "$CLIENT_FILTER" ]]; then
  echo "## Client Filter: $CLIENT_FILTER"
fi
echo ""
echo "Generated: $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "---"
echo ""

# Extract entries within date range
# Log format: ## [YYYY-MM-DD HH:MM] OPERATION | description
# Portable POSIX awk - no capture groups
awk -v start="$START_DATE" -v end="$END_DATE" '
  BEGIN { matched = 0; entry_buf = "" }

  /^## \[/ {
    # Flush previous entry if matched
    if (matched && entry_buf != "") {
      printf "%s", entry_buf
      print ""
    }
    entry_buf = ""
    matched = 0

    # Extract date from entry header: ## [YYYY-MM-DD HH:MM]
    # Find the date by substring after [
    bracket_pos = index($0, "[")
    if (bracket_pos > 0) {
      entry_date = substr($0, bracket_pos + 1, 10)
      if (entry_date >= start && entry_date <= end) {
        matched = 1
      }
    }
  }

  matched == 1 {
    entry_buf = entry_buf $0 "\n"
  }

  END {
    if (matched && entry_buf != "") {
      printf "%s", entry_buf
    }
  }
' "$LOG_FILE" | (
  if [[ -n "$CLIENT_FILTER" ]]; then
    # Filter blocks containing the client filter
    awk -v client="$CLIENT_FILTER" '
      BEGIN { block = "" }
      /^## \[/ {
        if (block != "" && (index(block, "Client: " client) > 0 || index(block, client "/") > 0)) {
          printf "%s", block
        }
        block = $0 "\n"
        next
      }
      { block = block $0 "\n" }
      END {
        if (block != "" && (index(block, "Client: " client) > 0 || index(block, client "/") > 0)) {
          printf "%s", block
        }
      }
    '
  else
    cat
  fi
)

# Footer summary
echo ""
echo "---"
echo ""
echo "## Summary"
ENTRY_COUNT=$(grep -c "^## \[" "$LOG_FILE" | head -1)
echo "Total log entries (all time): $ENTRY_COUNT"
echo ""
echo "Tip: Use --client SLUG to filter by client engagement."
