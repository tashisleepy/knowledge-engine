#!/usr/bin/env bash
# Register a newly created tool, skill, or agent into the local tools registry.
# Appends entry to tools-registry.json with timestamp and source session.
#
# Usage:
#   ./scripts/register-tool.sh --name NAME --type TYPE --command "CMD" --description "DESC" [--session SESSION_SLUG]
#
# Types:
#   agent-global    - Global agent (~/.claude/agents/)
#   agent-project   - Project-specific agent
#   skill           - Slash command skill
#   mcp-tool        - MCP-connected tool
#   script          - Local utility script
#   project         - Full project deliverable
#   knowledge-file  - Knowledge file / brain file
#   prompt          - System prompt / prompt template
#
# Example:
#   ./scripts/register-tool.sh \
#     --name "report-generator" \
#     --type script \
#     --command "./scripts/report.sh --week" \
#     --description "Date-range activity report from log.md" \
#     --session session-2026-04-14-memory-systems-build

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY_FILE="$ROOT_DIR/tools-registry.json"
LOG_FILE="$ROOT_DIR/log.md"

NAME=""
TYPE=""
COMMAND=""
DESCRIPTION=""
SESSION_SLUG=""
PATH_HINT=""

usage() {
  cat <<'EOF'
Register a new tool/skill/agent into the Knowledge Engine tools registry.

Usage:
  ./scripts/register-tool.sh [OPTIONS]

Required:
  --name NAME             Tool name (e.g., "report-generator")
  --type TYPE             One of: agent-global, agent-project, skill, mcp-tool,
                          script, project, knowledge-file, prompt
  --command "CMD"         How to invoke it
  --description "DESC"    One-line description

Optional:
  --session SLUG          Source session that created this tool
  --path PATH             Filesystem path to the tool
  --help                  Show this message

Example:
  ./scripts/register-tool.sh \
    --name "retention-architect" \
    --type agent-global \
    --command "Use retention-architect - [brief]" \
    --description "Multi-channel retention strategy for DTC brands" \
    --session session-2026-04-14-10x-audit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --type) TYPE="$2"; shift 2 ;;
    --command) COMMAND="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --session) SESSION_SLUG="$2"; shift 2 ;;
    --path) PATH_HINT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$NAME" || -z "$TYPE" || -z "$COMMAND" || -z "$DESCRIPTION" ]]; then
  echo "ERROR: --name, --type, --command, --description are all required" >&2
  usage
  exit 1
fi

VALID_TYPES="agent-global agent-project skill mcp-tool script project knowledge-file prompt"
if ! echo "$VALID_TYPES" | grep -qw "$TYPE"; then
  echo "ERROR: Invalid type '$TYPE'. Must be one of: $VALID_TYPES" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not found. Install: brew install jq (macOS) or apt install jq (Linux)" >&2
  exit 1
fi

NOW="$(date '+%Y-%m-%d %H:%M')"
TODAY="$(date '+%Y-%m-%d')"

# Check if tool with this name already exists (idempotency check)
EXISTING_INDEX=$(jq --arg name "$NAME" '[.tools[] | .n] | index($name)' "$REGISTRY_FILE")
TMP_FILE="$(mktemp)"

if [[ "$EXISTING_INDEX" != "null" ]]; then
  # UPDATE existing entry - preserve created timestamp + version history
  EXISTING_CREATED=$(jq -r --arg name "$NAME" '.tools[] | select(.n == $name) | .created' "$REGISTRY_FILE")
  EXISTING_VERSION=$(jq -r --arg name "$NAME" '.tools[] | select(.n == $name) | (.version // 1)' "$REGISTRY_FILE")
  NEW_VERSION=$((EXISTING_VERSION + 1))

  jq --arg name "$NAME" \
     --arg type "$TYPE" \
     --arg cmd "$COMMAND" \
     --arg desc "$DESCRIPTION" \
     --arg session "$SESSION_SLUG" \
     --arg path_hint "$PATH_HINT" \
     --arg now "$NOW" \
     --arg today "$TODAY" \
     --arg created "$EXISTING_CREATED" \
     --argjson new_version "$NEW_VERSION" \
     '.tools = [.tools[] | if .n == $name then {
        "n": $name,
        "t": $type,
        "c": $cmd,
        "d": $desc,
        "created": $created,
        "updated": $now,
        "version": $new_version,
        "source_session": $session,
        "path": $path_hint
      } else . end] | .updated = $today' \
    "$REGISTRY_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$REGISTRY_FILE"

  ACTION="TOOL-UPDATED"
  echo "Updated: $NAME ($TYPE) - version $NEW_VERSION"
  echo "Original created: $EXISTING_CREATED"
  echo "Updated at: $NOW"
else
  # CREATE new entry
  jq --arg name "$NAME" \
     --arg type "$TYPE" \
     --arg cmd "$COMMAND" \
     --arg desc "$DESCRIPTION" \
     --arg session "$SESSION_SLUG" \
     --arg path_hint "$PATH_HINT" \
     --arg ts "$NOW" \
     --arg today "$TODAY" \
     '.tools += [{
        "n": $name,
        "t": $type,
        "c": $cmd,
        "d": $desc,
        "created": $ts,
        "updated": $ts,
        "version": 1,
        "source_session": $session,
        "path": $path_hint
      }] | .updated = $today' \
    "$REGISTRY_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$REGISTRY_FILE"

  ACTION="TOOL-REGISTERED"
  echo "Registered: $NAME ($TYPE) at $NOW"
fi

# Prepend log entry (newest at top, after header)
TMP_LOG="$(mktemp)"
{
  head -2 "$LOG_FILE"
  echo ""
  echo "## [$NOW] $ACTION | $NAME ($TYPE)"
  echo "- Name: $NAME"
  echo "- Type: $TYPE"
  echo "- Command: $COMMAND"
  echo "- Description: $DESCRIPTION"
  [[ -n "$SESSION_SLUG" ]] && echo "- Source session: [[$SESSION_SLUG]]"
  [[ -n "$PATH_HINT" ]] && echo "- Path: $PATH_HINT"
  if [[ "$ACTION" == "TOOL-UPDATED" ]]; then
    echo "- Version: $NEW_VERSION (was $EXISTING_VERSION)"
    echo "- Originally created: $EXISTING_CREATED"
  fi
  echo ""
  tail -n +3 "$LOG_FILE"
} > "$TMP_LOG" && mv "$TMP_LOG" "$LOG_FILE"

echo "Registry: $REGISTRY_FILE"
echo "Log: $LOG_FILE"
echo ""
echo "Total unique tools in registry: $(jq '.tools | length' "$REGISTRY_FILE")"
