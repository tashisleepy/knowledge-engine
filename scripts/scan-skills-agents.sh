#!/usr/bin/env bash
# scan-skills-agents.sh
# Scans the filesystem for ALL installed skills and agents, adds missing ones to
# tools-registry.json with their actual file mtime as created date.
#
# This catches everything installed via plugins (claude-mem, superpowers,
# marketing-skills, etc.) that wasn't manually registered.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="$ROOT_DIR/tools-registry.json"
BACKUP="$REGISTRY.backup-$(date '+%Y%m%d-%H%M%S')"

cp "$REGISTRY" "$BACKUP"
echo "Backup: $BACKUP"

# Get existing names from registry (for dedup)
EXISTING_NAMES=$(jq -r '.tools[].n' "$REGISTRY" | sort -u)

ADDED=0
SKIPPED=0

# Helper: extract description from YAML frontmatter
extract_desc() {
  local f="$1"
  local desc=$(awk '/^description:/{
    sub(/^description: */, "");
    gsub(/^["'\'']|["'\'']$/, "");
    print;
    exit
  }' "$f" 2>/dev/null | head -c 200)
  [[ -z "$desc" ]] && desc=$(head -30 "$f" 2>/dev/null | grep -m1 -E "^# |^description" | sed 's/^# //; s/^description: *//' | head -c 200)
  echo "$desc"
}

# Helper: add tool to registry
add_to_registry() {
  local name="$1"
  local type="$2"
  local path="$3"
  local desc="$4"
  local mtime_iso=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$path" 2>/dev/null)

  # Check if name already exists
  if echo "$EXISTING_NAMES" | grep -qxF "$name"; then
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  local rel_path=$(echo "$path" | sed "s|$HOME/||")

  TMP=$(mktemp)
  local now_ts=$(date '+%Y-%m-%d %H:%M')
  local today=$(date '+%Y-%m-%d')
  jq --arg name "$name" \
     --arg type "$type" \
     --arg desc "$desc" \
     --arg path "$rel_path" \
     --arg cmd "Installed at $rel_path" \
     --arg created "$mtime_iso" \
     --arg now_ts "$now_ts" \
     --arg today "$today" \
     '.tools += [{
        n: $name,
        t: $type,
        c: $cmd,
        d: $desc,
        created: $created,
        updated: $created,
        registered_at: $now_ts,
        version: 1,
        source_session: "filesystem-scan",
        path: $path,
        is_backfill: true,
        duplicate_of_hardcoded: false,
        auto_scanned: true
      }] | .updated = $today' \
    "$REGISTRY" > "$TMP" 2>/dev/null && mv "$TMP" "$REGISTRY"

  ADDED=$((ADDED + 1))
  EXISTING_NAMES="$EXISTING_NAMES
$name"
}

echo ""
echo "═══ Scanning global skills (~/.claude/skills) ═══"
while IFS= read -r f; do
  dir=$(dirname "$f")
  name=$(basename "$dir")
  desc=$(extract_desc "$f")
  [[ -z "$desc" ]] && desc="Skill at $f"
  add_to_registry "$name" "skill" "$f" "$desc"
done < <(find ~/.claude/skills -name "SKILL.md" 2>/dev/null)

echo "═══ Scanning plugin skills (~/.claude/plugins) ═══"
while IFS= read -r f; do
  dir=$(dirname "$f")
  name=$(basename "$dir")
  desc=$(extract_desc "$f")
  [[ -z "$desc" ]] && desc="Plugin skill at $f"
  add_to_registry "$name" "skill" "$f" "$desc"
done < <(find ~/.claude/plugins -name "SKILL.md" 2>/dev/null)

echo "═══ Scanning global agents (~/.claude/agents) ═══"
while IFS= read -r f; do
  name=$(basename "$f" .md)
  desc=$(extract_desc "$f")
  [[ -z "$desc" ]] && desc="Agent at $f"
  add_to_registry "$name" "agent-global" "$f" "$desc"
done < <(find ~/.claude/agents -name "*.md" 2>/dev/null)

echo "═══ Scanning plugin agents ═══"
while IFS= read -r f; do
  name=$(basename "$f" .md)
  # Prefix with plugin name to avoid collisions
  plugin=$(echo "$f" | grep -oE 'plugins/[^/]+' | head -1 | sed 's|plugins/||')
  full_name="${plugin}-${name}"
  desc=$(extract_desc "$f")
  [[ -z "$desc" ]] && desc="Plugin agent at $f"
  add_to_registry "$full_name" "agent-project" "$f" "$desc"
done < <(find ~/.claude/plugins -path "*/agents/*.md" 2>/dev/null)

echo ""
echo "═══ Results ═══"
echo "Added: $ADDED new tools from filesystem"
echo "Skipped (already in registry): $SKIPPED"
echo "New registry total: $(jq '.tools | length' "$REGISTRY")"
