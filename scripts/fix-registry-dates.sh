#!/usr/bin/env bash
# fix-registry-dates.sh
# One-time fix: corrects tools-registry.json so `created` reflects ACTUAL work date
# (extracted from source_session), not the date it was registered.
# Also marks tools that duplicate the hardcoded TOOLS_DATA in ui.html.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="$ROOT_DIR/tools-registry.json"
UI_FILE="$ROOT_DIR/ui.html"
BACKUP="$REGISTRY.backup-$(date '+%Y%m%d-%H%M%S')"

cp "$REGISTRY" "$BACKUP"
echo "Backup created: $BACKUP"

# Extract hardcoded tool names from ui.html
HARDCODED=$(grep -oE '\{n:"[^"]+"' "$UI_FILE" | sed 's/{n:"//; s/"$//' | sort -u)
HARDCODED_JSON=$(echo "$HARDCODED" | jq -R . | jq -s .)

# Process registry: fix created date + add metadata flags
TMP="$(mktemp)"
jq --argjson hardcoded "$HARDCODED_JSON" '
  .tools |= map(
    (.source_session // "") as $sess |
    # Extract actual work date from session name if present
    ($sess | capture("session-(?<d>[0-9]{4}-[0-9]{2}-[0-9]{2})-"; "g") // {d: null}) as $m |
    ($m.d // (.created | split(" ")[0])) as $actual_date |
    (.created | split(" ")[1] // "00:00") as $time_part |
    . + {
      created: "\($actual_date) \($time_part)",
      registered_at: .created,
      is_backfill: (if $m.d and (.created | startswith($m.d) | not) then true else false end),
      duplicate_of_hardcoded: ([.n] | inside($hardcoded))
    }
  )
  | .updated = (now | strftime("%Y-%m-%d"))
' "$REGISTRY" > "$TMP" && mv "$TMP" "$REGISTRY"

echo ""
echo "═══ Results ═══"
echo "Total tools: $(jq '.tools | length' "$REGISTRY")"
echo "Backfilled (registered after actual work): $(jq '[.tools[] | select(.is_backfill == true)] | length' "$REGISTRY")"
echo "Duplicates of hardcoded TOOLS_DATA: $(jq '[.tools[] | select(.duplicate_of_hardcoded == true)] | length' "$REGISTRY")"
echo ""
echo "═══ By actual work date (not registration date) ═══"
jq -r '.tools | group_by(.created | split(" ")[0]) | map({date: .[0].created | split(" ")[0], count: length}) | sort_by(.date) | .[] | "\(.date): \(.count) tools"' "$REGISTRY"
