#!/usr/bin/env bash
# Save session - idempotent. Creates or updates session entry without duplication.
#
# Usage:
#   ./scripts/save-session.sh \
#     --slug "my-session-topic" \
#     --client primeframe|_shared|... \
#     --date 2026-04-14 \
#     --time 11:30 \
#     --title "My Session Title" \
#     --summary "Brief summary" \
#     --content-file /path/to/full-session-content.md
#
# Behavior:
#   - If session-{date}-{slug}.md already exists in sources/conversations/ AND wiki/{client}/:
#     READ existing files, MERGE with new content (preserve created, update updated), write back.
#     Log entry uses [UPDATE_COMPLETE] status.
#   - If new: CREATE both files with full frontmatter, log uses [INGEST_COMPLETE].
#   - Index.md row gets created or updated in place (no duplicates).
#   - Always idempotent. Run 100 times = same end state.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

SLUG=""
CLIENT="_shared"
DATE="$(date '+%Y-%m-%d')"
TIME="$(date '+%H:%M')"
TITLE=""
SUMMARY=""
CONTENT_FILE=""
TAGS=""
DURATION=""

usage() {
  cat <<'EOF'
Save session to Knowledge Engine - idempotent (no duplicates).

Usage:
  ./scripts/save-session.sh [OPTIONS]

Required:
  --slug SLUG                  Session slug (lowercase, hyphenated)
  --title "TITLE"              Session title
  --summary "SUMMARY"          One-paragraph summary

Optional:
  --client CLIENT              Client slug (default: _shared)
  --date YYYY-MM-DD            Session date (default: today)
  --time HH:MM                 Session time (default: now)
  --content-file PATH          Path to full markdown content (gets appended to body)
  --tags "tag1,tag2"           Comma-separated tags
  --duration HOURS             Session duration in hours

Behavior:
  - Existing session: UPDATE in place, preserve created, set new updated
  - New session: CREATE source + wiki + log + index entries
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --client) CLIENT="$2"; shift 2 ;;
    --date) DATE="$2"; shift 2 ;;
    --time) TIME="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    --summary) SUMMARY="$2"; shift 2 ;;
    --content-file) CONTENT_FILE="$2"; shift 2 ;;
    --tags) TAGS="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$SLUG" || -z "$TITLE" || -z "$SUMMARY" ]]; then
  echo "ERROR: --slug, --title, --summary are required" >&2
  usage
  exit 1
fi

SOURCE_FILE="$ROOT_DIR/sources/conversations/session-${DATE}-${SLUG}.md"
WIKI_FILE="$ROOT_DIR/wiki/${CLIENT}/session-${DATE}-${SLUG}.md"
LOG_FILE="$ROOT_DIR/log.md"
INDEX_FILE="$ROOT_DIR/index.md"
NOW="$(date '+%Y-%m-%d %H:%M')"

mkdir -p "$(dirname "$SOURCE_FILE")"
mkdir -p "$(dirname "$WIKI_FILE")"

# Determine action
if [[ -f "$WIKI_FILE" ]]; then
  ACTION="UPDATE"
  STATUS="UPDATE_COMPLETE"
  CREATED_DATE=$(grep "^created:" "$WIKI_FILE" | head -1 | awk '{print $2}')
  [[ -z "$CREATED_DATE" ]] && CREATED_DATE="$DATE"
  echo "EXISTING session detected at $WIKI_FILE"
  echo "  Original created: $CREATED_DATE"
  echo "  Updating to: $NOW"
else
  ACTION="INGEST"
  STATUS="INGEST_COMPLETE"
  CREATED_DATE="$DATE"
  echo "NEW session - creating fresh entry"
fi

# Build content (appends content-file if provided, else uses summary only)
BODY_CONTENT="$SUMMARY"
if [[ -n "$CONTENT_FILE" && -f "$CONTENT_FILE" ]]; then
  BODY_CONTENT="$SUMMARY"$'\n\n'"$(cat "$CONTENT_FILE")"
fi

# Write source file (append-on-update preserves history)
if [[ "$ACTION" == "UPDATE" && -f "$SOURCE_FILE" ]]; then
  # Append update marker + new content
  {
    echo ""
    echo "---"
    echo ""
    echo "## UPDATE [$NOW]"
    echo ""
    echo "$BODY_CONTENT"
  } >> "$SOURCE_FILE"
else
  cat > "$SOURCE_FILE" <<EOF
---
session_date: $DATE
session_time: $TIME
session_id: $SLUG
client: $CLIENT
title: $TITLE
created: $DATE
updated: $NOW
duration_hours: $DURATION
tags: [$TAGS]
status: COMPLETE
---

# $TITLE
## $DATE $TIME

$BODY_CONTENT
EOF
fi

# Write wiki file (idempotent - update frontmatter, append content if existing)
if [[ "$ACTION" == "UPDATE" ]]; then
  # Update the `updated:` field in YAML frontmatter
  sed -i.bak "s/^updated:.*/updated: $NOW/" "$WIKI_FILE" && rm -f "${WIKI_FILE}.bak"
  # Append update section to body
  {
    echo ""
    echo "## UPDATE [$NOW]"
    echo ""
    echo "$BODY_CONTENT"
  } >> "$WIKI_FILE"
else
  cat > "$WIKI_FILE" <<EOF
---
title: $TITLE
type: deliverable
client: $CLIENT
sources: [session-${DATE}-${SLUG}.md]
tags: [$TAGS]
related: []
created: $DATE
updated: $NOW
confidence: high
session_date: $DATE
session_time: $TIME
duration_hours: $DURATION
---

# $TITLE
## $DATE $TIME IST

## Summary
$SUMMARY

## Content
$BODY_CONTENT

## Status
COMPLETE
EOF
fi

# Prepend log entry
TMP_LOG="$(mktemp)"
{
  head -2 "$LOG_FILE"
  echo ""
  echo "## [$NOW] $ACTION | session-${DATE}-${SLUG}.md -> ${CLIENT}/session-${DATE}-${SLUG}.md ($([ "$ACTION" = "INGEST" ] && echo "created" || echo "updated")) [$STATUS]"
  echo "- Client: $CLIENT"
  echo "- Source: knowledge-engine/sources/conversations/session-${DATE}-${SLUG}.md"
  echo "- Wiki page: $([ "$ACTION" = "INGEST" ] && echo "created at" || echo "updated at") wiki/${CLIENT}/session-${DATE}-${SLUG}.md"
  echo "- Title: $TITLE"
  [[ -n "$TAGS" ]] && echo "- Tags: [$TAGS]"
  [[ -n "$DURATION" ]] && echo "- Duration: $DURATION hours"
  echo "- Original created: $CREATED_DATE"
  echo ""
  tail -n +3 "$LOG_FILE"
} > "$TMP_LOG" && mv "$TMP_LOG" "$LOG_FILE"

# Update index.md - check for existing entry, update in place or add new
INDEX_PATTERN="\[\[${CLIENT}/session-${DATE}-${SLUG}\]\]"
INDEX_ROW="| [[${CLIENT}/session-${DATE}-${SLUG}]] | deliverable | ${TITLE} | ${DATE} | high |"

if grep -qF "[[${CLIENT}/session-${DATE}-${SLUG}]]" "$INDEX_FILE" 2>/dev/null; then
  # Update existing row in place
  sed -i.bak "s|^.*\[\[${CLIENT}/session-${DATE}-${SLUG}\]\].*$|${INDEX_ROW}|" "$INDEX_FILE" && rm -f "${INDEX_FILE}.bak"
  echo "Index: updated existing row"
else
  # Add new row under Recent Sessions section, or create section
  if grep -qF "## Recent Sessions ($DATE)" "$INDEX_FILE" 2>/dev/null; then
    # Section exists, add row right after it
    sed -i.bak "/^## Recent Sessions ($DATE)$/a\\
$INDEX_ROW
" "$INDEX_FILE" && rm -f "${INDEX_FILE}.bak"
    echo "Index: added row under existing date section"
  else
    # Add section + row at top
    TMP_IDX="$(mktemp)"
    {
      head -3 "$INDEX_FILE"
      echo ""
      echo "## Recent Sessions ($DATE)"
      echo "$INDEX_ROW"
      tail -n +4 "$INDEX_FILE"
    } > "$TMP_IDX" && mv "$TMP_IDX" "$INDEX_FILE"
    echo "Index: created new date section + row"
  fi
fi

# Update Last updated date in index
sed -i.bak "s/^Last updated:.*/Last updated: $DATE/" "$INDEX_FILE" && rm -f "${INDEX_FILE}.bak"

echo ""
echo "═══════════════════════════════════════════════"
echo "Session saved: $ACTION"
echo "═══════════════════════════════════════════════"
echo "Source:  $SOURCE_FILE"
echo "Wiki:    $WIKI_FILE"
echo "Log:     $LOG_FILE (entry prepended)"
echo "Index:   $INDEX_FILE (row $([ "$ACTION" = "INGEST" ] && echo "added" || echo "updated"))"
echo ""
echo "Verify with:"
echo "  ./scripts/report.sh --since $DATE | head -20"
