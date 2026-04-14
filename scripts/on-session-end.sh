#!/usr/bin/env bash
# on-session-end.sh
# Fires when a Claude Code CLI session ends (via Stop hook) OR when Claude Desktop app quits (via LaunchAgent).
# Best-effort auto-capture: registers newly-created tools, creates session stub for user to enrich later.
#
# This is a SAFETY NET. It catches file-based artifacts. For full context/insights/reasoning,
# the user should still paste the save-to-memory prompt manually on important sessions.

set -uo pipefail
# Note: 'set -e' intentionally disabled. SIGPIPE from `find | head` pipelines would
# silently exit the script under pipefail+errexit. We handle errors explicitly per step.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAST_RUN_FILE="$HOME/.cache/claude-on-session-end-last-run"
CAPTURE_LOG="$HOME/.cache/claude-capture-log.txt"
STATE_DIR="$HOME/.cache/claude-capture-state"

mkdir -p "$(dirname "$LAST_RUN_FILE")"
mkdir -p "$STATE_DIR"

NOW="$(date '+%Y-%m-%d %H:%M')"
TODAY="$(date '+%Y-%m-%d')"
NOW_EPOCH="$(date '+%s')"

# Determine look-back window
if [[ -f "$LAST_RUN_FILE" ]]; then
  LAST_EPOCH=$(cat "$LAST_RUN_FILE")
  WINDOW_MIN=$(( (NOW_EPOCH - LAST_EPOCH) / 60 + 5 ))  # +5 min buffer
  [[ $WINDOW_MIN -lt 5 ]] && WINDOW_MIN=5
  [[ $WINDOW_MIN -gt 720 ]] && WINDOW_MIN=720  # cap at 12 hrs
else
  WINDOW_MIN=180  # default 3 hours for first run
fi

echo "[$NOW] on-session-end fired (look-back: ${WINDOW_MIN} min)" >> "$CAPTURE_LOG"

# Scan for new files in the window (file-based artifacts only)
ARTIFACTS=$(find ~/Downloads ~/tashi-workspace ~/tashi-projects \
  -type f \
  -mmin -${WINDOW_MIN} \
  \( -name "*.pdf" -o -name "*.docx" -o -name "*.pptx" -o -name "*.md" \
     -o -name "*.sh" -o -name "*.py" -o -name "*.js" -o -name "*.ts" \
     -o -name "*.json" -o -name "*.yaml" -o -name "*.mp4" -o -name "*.mov" \) \
  2>/dev/null \
  | grep -vE "node_modules|\.git/|/__pycache__/|\.cache/|\.tmp/|claude-capture-log" \
  | head -50)

if [[ -z "$ARTIFACTS" ]]; then
  echo "[$NOW] no new artifacts detected, skipping" >> "$CAPTURE_LOG"
  echo "$NOW_EPOCH" > "$LAST_RUN_FILE"
  exit 0
fi

ARTIFACT_COUNT=$(echo "$ARTIFACTS" | wc -l | tr -d ' ')
echo "[$NOW] detected $ARTIFACT_COUNT new artifacts" >> "$CAPTURE_LOG"

# Auto-register detectable tools (scripts, knowledge files that look tool-like)
TOOLS_REGISTERED=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  basename_f=$(basename "$file")
  dirname_f=$(dirname "$file")

  # Detect type based on location + extension
  # Note: dirname strips trailing slash, so regex must match end-of-string OR /subdir
  TYPE=""
  if [[ "$dirname_f" =~ (/\.claude/agents($|/)) ]]; then
    TYPE="agent-global"
  elif [[ "$dirname_f" =~ (/\.claude/skills($|/))|(/plugins/.*/skills($|/)) ]]; then
    TYPE="skill"
  elif [[ "$basename_f" == "CLAUDE.md" ]] && [[ "$dirname_f" =~ /tashi-projects/ ]]; then
    TYPE="agent-project"
  elif [[ "$dirname_f" =~ (/scripts($|/)) ]] && [[ "$basename_f" =~ \.(sh|py|js|ts)$ ]]; then
    TYPE="script"
  elif [[ "$dirname_f" =~ (/knowledge-files($|/)) ]]; then
    TYPE="knowledge-file"
  fi

  if [[ -n "$TYPE" ]]; then
    # Generate a name from filename
    tool_name=$(echo "$basename_f" | sed 's/\.[^.]*$//' | tr '[:upper:]' '[:lower:]' | tr ' _' '--')
    rel_path=$(echo "$file" | sed "s|$HOME/||")

    # Attempt registration (idempotent - script handles duplicates)
    "$ROOT_DIR/scripts/register-tool.sh" \
      --name "$tool_name" \
      --type "$TYPE" \
      --command "see file at $rel_path" \
      --description "Auto-detected by on-session-end hook on $TODAY" \
      --session "auto-capture-$TODAY" \
      --path "$rel_path" >> "$CAPTURE_LOG" 2>&1 || true

    TOOLS_REGISTERED=$((TOOLS_REGISTERED + 1))
  fi
done <<< "$ARTIFACTS"

# Create daily capture stub (idempotent - save-session.sh handles update vs create)
SLUG="auto-capture-$TODAY"
STUB_SUMMARY="Auto-captured session end at $NOW. Artifacts detected: $ARTIFACT_COUNT. Tools auto-registered: $TOOLS_REGISTERED.

This is a placeholder stub. To enrich with context/decisions/insights, re-run save-session.sh with full details:

Artifacts found in this window:
$ARTIFACTS"

"$ROOT_DIR/scripts/save-session.sh" \
  --slug "$SLUG" \
  --client "_shared" \
  --title "Auto-Capture: $TODAY" \
  --summary "$STUB_SUMMARY" \
  --tags "auto-capture,session-end-hook,needs-enrichment" \
  --duration "unknown" \
  --date "$TODAY" \
  --time "$(date '+%H:%M')" >> "$CAPTURE_LOG" 2>&1 || true

echo "[$NOW] captured $ARTIFACT_COUNT artifacts, registered $TOOLS_REGISTERED tools, stub: $SLUG" >> "$CAPTURE_LOG"
echo "$NOW_EPOCH" > "$LAST_RUN_FILE"

# Exit quietly (don't flood terminal on session end)
exit 0
