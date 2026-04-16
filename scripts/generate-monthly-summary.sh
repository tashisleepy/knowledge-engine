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

# Count UNIQUE sessions from actual wiki files (ground truth - not log entries)
SESSION_COUNT=$(find "$ROOT_DIR/wiki" -name "session-${MONTH}-*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
[[ -z "$SESSION_COUNT" ]] && SESSION_COUNT=0

# Separately count non-session ingests (bridge ingests - knowledge files, memory files, etc.)
OTHER_INGESTS=$(grep -E "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] INGEST " "$LOG_FILE" 2>/dev/null \
  | sed -nE 's|.*-> ([^ ]+) \(.*|\1|p' \
  | grep -v "session-${MONTH}-" \
  | sort -u | wc -l | tr -d ' ')
[[ -z "$OTHER_INGESTS" ]] && OTHER_INGESTS=0

# Count tool registrations in the month from registry (EXCLUDE duplicates of hardcoded UI list)
TOOLS_TOTAL=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true)] | length' "$REGISTRY_FILE")

# Backfill vs genuinely-new split
TOOLS_GENUINE_NEW=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true) | select(.is_backfill != true)] | length' "$REGISTRY_FILE")
TOOLS_BACKFILLED=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true) | select(.is_backfill == true)] | length' "$REGISTRY_FILE")
TOOLS_DUPLICATES=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded == true)] | length' "$REGISTRY_FILE")

# Within "genuinely-new": split built-from-scratch (manually registered) vs installed-configured (auto-scanned from plugins/marketplaces)
TOOLS_BUILT_FROM_SCRATCH=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true) | select(.is_backfill != true) | select(.auto_scanned != true)] | length' "$REGISTRY_FILE")
TOOLS_INSTALLED_CONFIGURED=$(jq --arg m "$MONTH" '[.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true) | select(.is_backfill != true) | select(.auto_scanned == true)] | length' "$REGISTRY_FILE")

# Tools by type with built-vs-installed split
TOOLS_BY_TYPE=$(jq --arg m "$MONTH" '
  [.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true)]
  | group_by(.t)
  | map({
      type: .[0].t,
      count: length,
      built: [.[] | select(.auto_scanned != true)] | length,
      installed: [.[] | select(.auto_scanned == true)] | length
    })
' "$REGISTRY_FILE")

# Full tools list with names + descriptions (grouped by type, excludes duplicates)
TOOLS_DETAIL=$(jq --arg m "$MONTH" '
  [.tools[] | select(.created | startswith($m)) | select(.duplicate_of_hardcoded != true)]
  | group_by(.t)
  | map({
      type: .[0].t,
      count: length,
      items: (. | map({
        name: .n,
        description: .d,
        created: .created,
        registered_at: .registered_at,
        is_backfill: (.is_backfill // false),
        path: .path
      }))
    })
' "$REGISTRY_FILE")

# List of unique sessions this month from wiki files (more reliable than parsing log)
SESSIONS_LIST=$(find "$ROOT_DIR/wiki" -name "session-${MONTH}-*.md" -type f 2>/dev/null \
  | while read -r f; do
      basename_f=$(basename "$f" .md)
      dir_f=$(basename "$(dirname "$f")")
      # Extract date from filename: session-YYYY-MM-DD-slug
      date_part=$(echo "$basename_f" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
      slug=$(echo "$basename_f" | sed "s/session-${date_part}-//")
      # Try to read title from frontmatter
      title=$(grep -m1 "^title:" "$f" 2>/dev/null | sed 's/^title: *//' | head -c 120)
      [[ -z "$title" ]] && title="$slug"
      echo "{\"date\":\"$date_part\",\"client\":\"$dir_f\",\"slug\":\"$slug\",\"title\":\"$(echo "$title" | sed 's/"/\\"/g')\",\"wiki_path\":\"$dir_f/$basename_f.md\"}"
    done \
  | jq -s 'sort_by(.date) | reverse' 2>/dev/null || echo '[]')

# Document count: scan the workspace containing this repo for real work artifacts, excluding noise
# (session auto-captures, vendored deps, build output, virtualenvs).
# ~/Downloads is intentionally skipped — it's a dumping ground for invoices/receipts/screenshots
# that have nothing to do with work output and inflate the count dishonestly.
# Override with DOC_SCAN_ROOT env var if your work lives elsewhere.
DOC_SCAN_ROOT="${DOC_SCAN_ROOT:-$(dirname "$ROOT_DIR")}"
DOC_EXCLUDES=(
  -not -path "*/.git/*"
  -not -path "*/node_modules/*"
  -not -path "*/__pycache__/*"
  -not -path "*/.venv/*"
  -not -path "*/venv/*"
  -not -path "*/.next/*"
  -not -path "*/dist/*"
  -not -path "*/build/*"
  -not -path "*/knowledge-engine/sources/conversations/*"
  -not -path "*/knowledge-engine/sources/claude-export/*"
  -not -path "*/knowledge-engine/memvid/*"
  -not -path "*/knowledge-engine/wiki/*"
  -not -path "*/knowledge-engine/schema/*"
)
PDF_COUNT=$(find "$DOC_SCAN_ROOT" -type f -name "*.pdf"  -newermt "$START_DATE" "${DOC_EXCLUDES[@]}" 2>/dev/null | wc -l | tr -d ' ')
DOCX_COUNT=$(find "$DOC_SCAN_ROOT" -type f -name "*.docx" -newermt "$START_DATE" "${DOC_EXCLUDES[@]}" 2>/dev/null | wc -l | tr -d ' ')
PPTX_COUNT=$(find "$DOC_SCAN_ROOT" -type f -name "*.pptx" -newermt "$START_DATE" "${DOC_EXCLUDES[@]}" 2>/dev/null | wc -l | tr -d ' ')
MD_COUNT=$(find "$DOC_SCAN_ROOT"  -type f -name "*.md"   -newermt "$START_DATE" "${DOC_EXCLUDES[@]}" 2>/dev/null | wc -l | tr -d ' ')

# TOOL-REGISTERED count in log
# Use UNIQUE tool count from registry (ground truth), not log entries (may include duplicates)
TOOL_REG_COUNT=$TOOLS_TOTAL
TOOL_UPD_COUNT=$(grep -cE "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] TOOL-UPDATED " "$LOG_FILE" 2>/dev/null || echo 0)
# Also expose log entry counts for transparency (may exceed unique count)
TOOL_LOG_ENTRIES=$(grep -cE "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] TOOL-REGISTERED " "$LOG_FILE" 2>/dev/null || echo 0)

# Updated tools with version info (current version >= 2 = was updated)
TOOLS_UPDATED=$(jq --arg m "$MONTH" '
  [.tools[]
   | select(.created | startswith($m))
   | select((.version // 1) >= 2)
   | {name: .n, type: .t, description: .d, version: .version, created: .created, updated: .updated, path: .path}]
  | sort_by(.updated) | reverse
' "$REGISTRY_FILE" 2>/dev/null || echo '[]')

# Sessions updated multiple times (look for UPDATE entries in log)
# Parse each line: ## [YYYY-MM-DD HH:MM] UPDATE | ... -> {wiki_path} (...) [...]
SESSIONS_UPDATED_RAW=$(grep -E "^## \[${MONTH}-[0-9]{2} [0-9]{2}:[0-9]{2}\] UPDATE " "$LOG_FILE" 2>/dev/null)
if [[ -n "$SESSIONS_UPDATED_RAW" ]]; then
  SESSIONS_UPDATED=$(echo "$SESSIONS_UPDATED_RAW" \
    | while IFS= read -r line; do
        ts=$(echo "$line" | grep -oE '\[[0-9-]+ [0-9:]+\]' | head -1 | tr -d '[]')
        path=$(echo "$line" | grep -oE '\-> [^ ]+' | head -1 | sed 's/^-> //')
        if [[ -n "$ts" && -n "$path" ]]; then
          echo "{\"timestamp\":\"$ts\",\"wiki_path\":\"$path\"}"
        fi
      done \
    | jq -s 'group_by(.wiki_path) | map({wiki_path: .[0].wiki_path, update_count: length, last_updated: .[0].timestamp}) | sort_by(.update_count) | reverse' 2>/dev/null)
  [[ -z "$SESSIONS_UPDATED" ]] && SESSIONS_UPDATED='[]'
else
  SESSIONS_UPDATED='[]'
fi

# Compute estimated hours using REALISTIC multipliers from config
HOURS_CALC=$(jq -n \
  --argjson sessions "$SESSION_COUNT" \
  --argjson pdf "$PDF_COUNT" \
  --argjson docx "$DOCX_COUNT" \
  --argjson pptx "$PPTX_COUNT" \
  --argjson md "$MD_COUNT" \
  --slurpfile config "$CONFIG_FILE" \
  --slurpfile byType <(echo "$TOOLS_BY_TYPE") \
  '
    ($config[0].hours_multipliers) as $h |
    ($byType[0]) as $types |
    ($config[0].hours_multipliers._built_from_scratch) as $built_h |
    ($config[0].hours_multipliers._installed_configured) as $inst_h |
    ($sessions * $h.session_base_overhead) as $session_hours |
    ($pdf * $h.document_pdf) as $pdf_hours |
    ($docx * $h.document_docx) as $docx_hours |
    ($pptx * $h.document_pptx) as $pptx_hours |
    ($md * $h.document_md) as $md_hours |
    # For each type, calculate hours using built + installed split
    (def type_rate($t; $role): if $role == "built" then
       if $t == "agent-global" then $built_h.tool_agent_global
       elif $t == "agent-project" then $built_h.tool_agent_project
       elif $t == "skill" then $built_h.tool_skill
       elif $t == "script" then $built_h.tool_script
       elif $t == "knowledge-file" then $built_h.tool_knowledge_file
       elif $t == "prompt" then $built_h.tool_prompt
       elif $t == "mcp-tool" then $built_h.tool_mcp
       elif $t == "project" then $built_h.tool_project
       else 0 end
    else
       if $t == "agent-global" then $inst_h.tool_agent_global
       elif $t == "agent-project" then $inst_h.tool_agent_project
       elif $t == "skill" then $inst_h.tool_skill
       elif $t == "script" then $inst_h.tool_script
       elif $t == "knowledge-file" then $inst_h.tool_knowledge_file
       elif $t == "prompt" then $inst_h.tool_prompt
       elif $t == "mcp-tool" then $inst_h.tool_mcp
       elif $t == "project" then $inst_h.tool_project
       else 0 end
    end;
    [$types[] | {
      t: .type,
      built: .built,
      installed: .installed,
      built_rate: type_rate(.type; "built"),
      installed_rate: type_rate(.type; "installed"),
      built_hrs: (.built * type_rate(.type; "built")),
      installed_hrs: (.installed * type_rate(.type; "installed")),
      total_hrs: ((.built * type_rate(.type; "built")) + (.installed * type_rate(.type; "installed")))
    }]) as $tool_breakdown |
    ($tool_breakdown | map(.total_hrs) | add // 0) as $tool_hours |
    {
      session_hours: $session_hours,
      session_count: $sessions,
      session_rate: $h.session_base_overhead,
      tool_hours: $tool_hours,
      tool_breakdown: $tool_breakdown,
      pdf_hours: $pdf_hours,
      pdf_count: $pdf,
      pdf_rate: $h.document_pdf,
      docx_hours: $docx_hours,
      docx_count: $docx,
      docx_rate: $h.document_docx,
      pptx_hours: $pptx_hours,
      pptx_count: $pptx,
      pptx_rate: $h.document_pptx,
      md_hours: $md_hours,
      md_count: $md,
      md_rate: $h.document_md,
      total: ($session_hours + $tool_hours + $pdf_hours + $docx_hours + $pptx_hours + $md_hours)
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
  --argjson tools_detail "$TOOLS_DETAIL" \
  --argjson tools_updated "$TOOLS_UPDATED" \
  --argjson sessions_updated "$SESSIONS_UPDATED" \
  --argjson sessions_list "$SESSIONS_LIST" \
  --argjson pdf "$PDF_COUNT" \
  --argjson docx "$DOCX_COUNT" \
  --argjson pptx "$PPTX_COUNT" \
  --argjson md "$MD_COUNT" \
  --argjson tool_reg "$TOOL_REG_COUNT" \
  --argjson tool_upd "$TOOL_UPD_COUNT" \
  --argjson tool_log_entries "$TOOL_LOG_ENTRIES" \
  --argjson genuine_new "$TOOLS_GENUINE_NEW" \
  --argjson backfilled "$TOOLS_BACKFILLED" \
  --argjson duplicates "$TOOLS_DUPLICATES" \
  --argjson built_from_scratch "$TOOLS_BUILT_FROM_SCRATCH" \
  --argjson installed_configured "$TOOLS_INSTALLED_CONFIGURED" \
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
      tools_log_entries: $tool_log_entries,
      tools_genuinely_new: $genuine_new,
      tools_built_from_scratch: $built_from_scratch,
      tools_installed_configured: $installed_configured,
      tools_backfilled: $backfilled,
      tools_duplicates_hidden: $duplicates,
      documents: {
        pdf: $pdf,
        docx: $docx,
        pptx: $pptx,
        md: $md,
        total: ($pdf + $docx + $pptx + $md)
      }
    },
    tools_by_type: $tools_by_type,
    tools_detail: $tools_detail,
    tools_updated: $tools_updated,
    sessions_updated: $sessions_updated,
    sessions_list: $sessions_list,
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
