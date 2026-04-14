#!/usr/bin/env bash
# generate-monthly-summary.sh
# Generates monthly-summary.json from log.md + tools-registry.json for the current calendar month.
# Reads rate/multiplier config from monthly-summary-config.json.
# Output is consumed by the "Month in a Nutshell" tab in ui.html.
#
# Usage:
#   ./scripts/generate-monthly-summary.sh                    # current month (1st to today)
#   ./scripts/generate-monthly-summary.sh --month 2026-03    # specific month

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$ROOT_DIR/log.md"
REGISTRY_FILE="$ROOT_DIR/tools-registry.json"
CONFIG_FILE="$ROOT_DIR/monthly-summary-config.json"
OUTPUT_FILE="$ROOT_DIR/monthly-summary.json"

# Parse args
MONTH="$(date '+%Y-%m')"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --month) MONTH="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

START_DATE="${MONTH}-01"
TODAY="$(date '+%Y-%m-%d')"
MONTH_LABEL="$(date -j -f '%Y-%m' "$MONTH" '+%B %Y' 2>/dev/null || date -d "${MONTH}-01" '+%B %Y')"

# Load rates from config
CONS_RATE=$(jq '.rates.conservative_usd_per_hour' "$CONFIG_FILE")
REAL_RATE=$(jq '.rates.realistic_usd_per_hour' "$CONFIG_FILE")
HIGH_RATE=$(jq '.rates.high_end_usd_per_hour' "$CONFIG_FILE")

# Count UNIQUE sessions (by wiki file path, session-* prefixed only, not general ingests)
SESSION_COUNT=$(grep -E "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] INGEST " "$LOG_FILE" 2>/dev/null \
  | sed -nE 's|.*-> ([^ ]+) \(.*|\1|p' \
  | grep "session-${MONTH}-" \
  | sort -u | wc -l | tr -d ' ')
[[ -z "$SESSION_COUNT" ]] && SESSION_COUNT=0

# Separately count non-session ingests (bridge ingests - knowledge files, memory files, etc.)
OTHER_INGESTS=$(grep -E "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] INGEST " "$LOG_FILE" 2>/dev/null \
  | sed -nE 's|.*-> ([^ ]+) \(.*|\1|p' \
  | grep -v "session-${MONTH}-" \
  | sort -u | wc -l | tr -d ' ')
[[ -z "$OTHER_INGESTS" ]] && OTHER_INGESTS=0

# Count tool registrations in the month from registry (use created field)
TOOLS_TOTAL=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m))] | length' "$REGISTRY_FILE")

# Tools by type
TOOLS_BY_TYPE=$(jq --arg m "$MONTH" '
  [.tools[] | select(.created | startswith($m))]
  | group_by(.t)
  | map({type: .[0].t, count: length})
' "$REGISTRY_FILE")

# Documents count in Downloads from month start
PDF_COUNT=$(find ~/Downloads -type f -name "*.pdf" -newermt "$START_DATE" 2>/dev/null | wc -l | tr -d ' ')
DOCX_COUNT=$(find ~/Downloads -type f -name "*.docx" -newermt "$START_DATE" 2>/dev/null | wc -l | tr -d ' ')
PPTX_COUNT=$(find ~/Downloads -type f -name "*.pptx" -newermt "$START_DATE" 2>/dev/null | wc -l | tr -d ' ')
MD_COUNT=$(find ~/Downloads -type f -name "*.md" -newermt "$START_DATE" 2>/dev/null | wc -l | tr -d ' ')

# TOOL-REGISTERED count in log
TOOL_REG_COUNT=$(grep -cE "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] TOOL-REGISTERED " "$LOG_FILE" 2>/dev/null || echo 0)
TOOL_UPD_COUNT=$(grep -cE "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] TOOL-UPDATED " "$LOG_FILE" 2>/dev/null || echo 0)

# Compute estimated hours using multipliers from config
HOURS_CALC=$(jq -n \
  --argjson sessions "$SESSION_COUNT" \
  --argjson pdf "$PDF_COUNT" \
  --argjson docx "$DOCX_COUNT" \
  --argjson pptx "$PPTX_COUNT" \
  --slurpfile config "$CONFIG_FILE" \
  --slurpfile byType <(echo "$TOOLS_BY_TYPE") \
  '
    ($config[0].hours_multipliers) as $h |
    ($byType[0]) as $types |
    ($sessions * $h.session_default) as $session_hours |
    ($pdf * $h.document_pdf) as $pdf_hours |
    ($docx * $h.document_docx) as $docx_hours |
    ($pptx * $h.document_pptx) as $pptx_hours |
    ([$types[] | (
       if .type == "agent-global" or .type == "agent-project" then .count * $h.tool_agent
       elif .type == "skill" then .count * $h.tool_skill
       elif .type == "script" then .count * $h.tool_script
       elif .type == "knowledge-file" then .count * $h.tool_knowledge_file
       elif .type == "prompt" then .count * $h.tool_prompt
       elif .type == "mcp-tool" then .count * $h.tool_mcp
       elif .type == "project" then .count * $h.tool_project
       else 0 end
    )] | add // 0) as $tool_hours |
    {
      session_hours: $session_hours,
      tool_hours: $tool_hours,
      pdf_hours: $pdf_hours,
      docx_hours: $docx_hours,
      pptx_hours: $pptx_hours,
      total: ($session_hours + $tool_hours + $pdf_hours + $docx_hours + $pptx_hours)
    }
  '
)

TOTAL_HOURS=$(echo "$HOURS_CALC" | jq '.total')
CONS_VALUE=$(echo "$TOTAL_HOURS * $CONS_RATE" | bc)
REAL_VALUE=$(echo "$TOTAL_HOURS * $REAL_RATE" | bc)
HIGH_VALUE=$(echo "$TOTAL_HOURS * $HIGH_RATE" | bc)

# Top sessions this month (titles)
TOP_SESSIONS=$(grep -E "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] INGEST " "$LOG_FILE" 2>/dev/null | head -15 | sed -E 's/^## \[([0-9]{4}-[0-9]{2}-[0-9]{2}) [0-9]{2}:[0-9]{2}\] INGEST \| (session-[^ ]+\.md) -> (.+)$/{"date":"\1","source":"\2","wiki":"\3"}/' | grep -oE '^\{.*\}$' | jq -s '.' 2>/dev/null || echo '[]')

# Build final JSON
jq -n \
  --arg month "$MONTH" \
  --arg month_label "$MONTH_LABEL" \
  --arg start_date "$START_DATE" \
  --arg today "$TODAY" \
  --arg generated_at "$(date '+%Y-%m-%d %H:%M')" \
  --argjson sessions "$SESSION_COUNT" \
  --argjson other_ingests "$OTHER_INGESTS" \
  --argjson tools_total "$TOOLS_TOTAL" \
  --argjson tools_by_type "$TOOLS_BY_TYPE" \
  --argjson pdf "$PDF_COUNT" \
  --argjson docx "$DOCX_COUNT" \
  --argjson pptx "$PPTX_COUNT" \
  --argjson md "$MD_COUNT" \
  --argjson tool_reg "$TOOL_REG_COUNT" \
  --argjson tool_upd "$TOOL_UPD_COUNT" \
  --argjson hours "$HOURS_CALC" \
  --argjson cons_rate "$CONS_RATE" \
  --argjson real_rate "$REAL_RATE" \
  --argjson high_rate "$HIGH_RATE" \
  --arg cons_value "$CONS_VALUE" \
  --arg real_value "$REAL_VALUE" \
  --arg high_value "$HIGH_VALUE" \
  '{
    version: 1,
    month: $month,
    month_label: $month_label,
    period: "\($start_date) to \($today)",
    generated_at: $generated_at,
    counts: {
      sessions: $sessions,
      other_ingests: $other_ingests,
      tools_registered: $tool_reg,
      tools_updated: $tool_upd,
      tools_total_in_month: $tools_total,
      documents: {
        pdf: $pdf,
        docx: $docx,
        pptx: $pptx,
        md: $md,
        total: ($pdf + $docx + $pptx + $md)
      }
    },
    tools_by_type: $tools_by_type,
    human_hours_estimate: $hours,
    value_proposition: {
      currency: "USD",
      conservative: {
        rate_per_hour: $cons_rate,
        total_value: ($cons_value | tonumber),
        label: "Dubai/UK mid-market consultant"
      },
      realistic: {
        rate_per_hour: $real_rate,
        total_value: ($real_value | tonumber),
        label: "Senior Dubai/London/NYC specialist"
      },
      high_end: {
        rate_per_hour: $high_rate,
        total_value: ($high_value | tonumber),
        label: "Big 4 / McKinsey / BCG tier"
      }
    },
    disclaimer: "Human hours are estimates based on session type and deliverable count multipliers from monthly-summary-config.json. Edit that file to adjust assumptions for your market. Actual billable value depends on engagement type, client, and market conditions."
  }' > "$OUTPUT_FILE"

echo "Generated: $OUTPUT_FILE"
echo ""
cat "$OUTPUT_FILE" | jq '{month_label, counts, human_hours_estimate, value_proposition}'
