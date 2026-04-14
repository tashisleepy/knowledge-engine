# Knowledge Engine

The bridge between human-readable wikis and machine-speed memory. Built on Karpathy's LLM Wiki pattern + Memvid.

---

## What This Actually Does

Knowledge workers produce massive amounts of documents - proposals, meeting notes, research, client briefs. Every time a question comes up, they re-read everything from scratch. Notes exist but aren't searchable at machine speed. Knowledge decays instead of compounding.

Knowledge Engine takes your source documents and creates two synchronized layers: a human-readable wiki you browse in Obsidian, and a machine-searchable memory that returns results in under 5ms. You drop in a document once. From that point, both a consultant and an AI agent can query it instantly without touching the original file again.

The Bridge is the Python script that keeps both layers in lockstep. Without it, you have two separate tools doing different things. With it, every ingest is one atomic operation that writes the wiki page and the memory frame simultaneously, keeps them hashed against each other, and alerts you when they drift.

Memvid is optional by design. The wiki layer handles the job at any practical document count. Start with the wiki. Add the machine layer only if you genuinely need sub-5ms semantic search across thousands of pages.

---

## The Three Components

### What is the LLM Wiki? (Karpathy's Pattern)

Andrej Karpathy published this pattern on April 3, 2026. The core insight: stop re-deriving answers from raw documents on every query. Instead, have an LLM build and maintain a persistent, structured wiki that compounds over time.

Three layers:

- **Raw sources** - immutable evidence, never touched after ingest
- **Wiki pages** - LLM-generated markdown, organized by client or project
- **Schema** - entities, relationships, tag taxonomy, all machine-readable

Three operations:

- **Ingest** - process a source, create or update wiki pages, extract entities
- **Query** - search the wiki, synthesize an answer with citations, file reusable answers
- **Lint** - health-check for contradictions, orphan pages, missing cross-references

The wiki is plain markdown in a git repo. Browse it in Obsidian, VS Code, or any text editor. The human reads the wiki. The LLM maintains it. Knowledge compounds instead of decaying.

Credit: [Karpathy's gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

---

### What is Memvid?

Memvid is a single-file memory layer for AI agents. 14K GitHub stars. Number 1 trending when it shipped.

What it does:

- Packages data, embeddings, and search into one portable `.mv2` file
- Sub-5ms retrieval with no databases, no vector DB infrastructure, no servers
- Smart Frames: append-only, immutable content units with timestamps and checksums
- One file you copy, backup, or ship anywhere

Think of it as SQLite for AI memory. The machine queries Memvid. Humans never read the `.mv2` file directly - that's not what it's for.

Credit: [Olow304/memvid](https://github.com/Olow304/memvid)

---

### What is the Bridge? (Why This Project Exists)

The LLM Wiki and Memvid solve different problems. Nobody connected them. That's what the Bridge does.

| Feature | Wiki Only | Memvid Only | Bridge (Both) |
|---|---|---|---|
| Human browsable | Yes | No | Yes |
| Machine searchable | Slow (grep) | 2ms | 2ms + structured context |
| Cross-references | Yes (wikilinks) | No | Yes |
| Entity extraction | Manual | No | Automatic |
| Contradiction detection | Manual | No | Automatic |
| Obsidian compatible | Yes | No | Yes |
| Scales to 10K+ docs | Slow | Yes | Yes |
| Knowledge compounds | Yes (if maintained) | No (just stores) | Yes (auto-maintained) |

The Bridge is a Python script that does five things:

1. **On INGEST** - writes the wiki page (human layer) and creates Memvid Smart Frames (machine layer) in one atomic operation
2. **On SEARCH** - queries the wiki first (structured, curated) then falls back to Memvid (raw, comprehensive) and merges results with source attribution
3. **On SYNC** - keeps both layers in lockstep using content hashing, no duplicate frames, no stale data
4. **On DRIFT** - detects when the layers disagree and flags it before it compounds into bigger problems
5. **On LINT** - checks for contradictions, orphan pages, missing cross-references across both layers simultaneously

```
Source Document
      |
      v
  [BRIDGE]
      |
      +---> Wiki Layer (Obsidian-compatible markdown)
      |     - Frontmatter with citations, confidence, tags
      |     - [[wikilinks]] for cross-references
      |     - Human reads and browses here
      |
      +---> Memvid Layer (.mv2 archive)
      |     - Smart Frames with metadata
      |     - Sub-5ms semantic search
      |     - Machine queries here
      |
      +---> Schema Layer (entities.json, graph.json, tags.json)
            - Named entities auto-extracted
            - Relationship tracking
            - Tag taxonomy
```

---

## Quick Start

Under 60 seconds from clone to first search.

```bash
git clone https://github.com/[repo]
cd knowledge-engine
pip install -r requirements.txt    # memvid-sdk + pymupdf + portalocker

# Ingest the included demo data
python3 bridge.py ingest demo/sample-proposal.md demo-client
python3 bridge.py ingest demo/sample-meeting-notes.md demo-client
python3 bridge.py ingest demo/sample-research.md demo-client

# Search across everything
python3 bridge.py search "RetailCorp budget timeline"

# Check system health
python3 bridge.py stats

# Launch the web UI
python3 server.py
# Open http://localhost:3141
```

Memvid is optional. Without it, the system runs as a wiki-only knowledge base with text search. Install `memvid-sdk` for dual-layer semantic search.

---

## CLI Reference

| Command | What It Does | Example |
|---|---|---|
| `init` | Create a new workspace | `bridge.py init --project "Research" --clients "client-a,client-b"` |
| `ingest` | Process source into both layers | `bridge.py ingest document.pdf my-client` |
| `search` | Dual-layer search | `bridge.py search "quarterly revenue"` |
| `sync` | Sync wiki pages to Memvid | `bridge.py sync` |
| `drift` | Check layer synchronization | `bridge.py drift` |
| `stats` | System overview | `bridge.py stats` |
| `repair` | Fix corrupted archives | `bridge.py repair` |

Supported source formats: `.md`, `.txt`, `.pdf`

**Platform support:** macOS, Linux, Windows. File locking uses `portalocker` (cross-platform). Falls back to `fcntl` on Unix or no-lock single-user mode if neither is available.

---

## Tired of telling your boss what you did last week?

Stop scrolling through Slack. Stop guessing dates. Stop writing status reports from memory.

Knowledge Engine remembers every session you've ever logged. One command and you get a clean markdown report - weekly, monthly, quarterly, or any custom range you want. Filter by client. Export to file. Send it.

### Just ask Claude (or any LLM with this repo)

Drop these prompts into your AI assistant. It will run the script and hand you the report:

```
"Give me my work report for the last 7 days."
"Generate a quarterly retrospective for client {slug}."
"Show me everything I worked on between 2026-01-01 and 2026-03-31."
"Build a monthly status update for my boss covering all clients."
```

### Or run it yourself

```bash
# Quick presets - one flag, one report
./scripts/report.sh --week        # Last 7 days
./scripts/report.sh --month       # Last 30 days
./scripts/report.sh --quarter     # Last 90 days
./scripts/report.sh --year        # Last 365 days

# Custom date ranges
./scripts/report.sh --since 2026-04-01
./scripts/report.sh --between 2026-01-01 2026-03-31

# Narrow to one client
./scripts/report.sh --month --client {slug}
./scripts/report.sh --quarter --client {slug}

# Save it for the record
./scripts/report.sh --week > reports/weekly-$(date +%Y-%m-%d).md
```

The script reads timestamped entries from `log.md`, filters by your date range, and outputs clean markdown to stdout.

---

## Register new tools, skills, and agents as you build them

Every time you create a new AI tool - an agent, a skill, an MCP tool, a script, a knowledge file, a prompt - register it so it shows up in your Tools tab and future work reports.

### Just ask Claude

```
"Register this new script as a tool - it does {description}"
"Log the agent I just built into the tools registry"
"Add this skill to my local tools tab"
```

### Or run it yourself

```bash
./scripts/register-tool.sh \
  --name "tool-name" \
  --type agent-global \
  --command "How to invoke it" \
  --description "One-line description" \
  --session "session-YYYY-MM-DD-{slug}" \
  --path "relative/path/to/tool"
```

Valid types: `agent-global`, `agent-project`, `skill`, `mcp-tool`, `script`, `project`, `knowledge-file`, `prompt`

What it does:
- Appends entry to `tools-registry.json` (LOCAL only, gitignored)
- Prepends `TOOL-REGISTERED` entry to `log.md` with timestamp
- Tool appears in the Web UI Tools tab (at `http://localhost:3141`)
- Shows up in date-range reports so you can see what you built this quarter

---

## How do you record your sessions?

Three ways. Each idempotent (run 100x = same result, no duplicates).

### Quickest: save-session.sh (recommended)

```bash
./scripts/save-session.sh \
  --slug "my-topic" \
  --client {client-slug} \
  --title "Session Title" \
  --summary "What this session accomplished" \
  --tags "tag1,tag2,tag3" \
  --duration 1.5
```

What it guarantees:
- If session-{date}-{slug}.md already exists: UPDATES in place, preserves `created`, sets new `updated`
- If new: CREATES source + wiki + log + index entries
- Index row: only one per session (updates in place, never duplicates)
- Log timeline: full history preserved (INGEST + subsequent UPDATEs)
- Pressure-tested: run it 5 times in a row = same end state, with full version history



### Automatic (every ingest)

Every time you ingest a source, Knowledge Engine auto-logs it with a timestamp:

```bash
python3 bridge.py ingest path/to/document.pdf {client-slug}
# Auto-logs: ## [YYYY-MM-DD HH:MM] INGEST | source -> wiki/path (created)
```

### Manual (high-signal sessions worth remembering)

For important conversations, deliverables, or decisions worth a permanent record, just tell Claude:

```
"Save this session to Knowledge Engine wiki under client {slug}."
"Log this work session in my wiki - title it {topic}."
"Add today's session to the wiki with full details."
```

Claude will:
1. Create a source file at `sources/conversations/session-YYYY-MM-DD-{slug}.md`
2. Create a wiki page at `wiki/{client}/session-YYYY-MM-DD-{slug}.md` with proper YAML frontmatter
3. Append a timestamped entry to `log.md` (newest at top)
4. Update `index.md` so it shows up in future reports

The session is now permanent. It compounds. It's queryable by date. It's filterable by client. It's the source of every future status report you generate.

---

## Web UI

Start with `python3 server.py` and open `http://localhost:3141`.

Dark theme dashboard with five tabs:

- **Dashboard** - stats cards, per-client document counts, recent activity log
- **Search** - dual-layer results with wiki and memvid source badges, citation links
- **Wiki** - sidebar tree, rendered markdown with frontmatter confidence badges
- **Entities** - filterable table of auto-extracted companies, people, products, technologies
- **Health** - drift check, sync status, lint report summary

---

## Architecture

Five files do everything:

| File | Purpose | Size |
|---|---|---|
| `bridge.py` | Core engine - ingest, search, sync, drift, lint | 1,575 lines |
| `bridge_config.py` | Configuration constants | small |
| `server.py` | Local web UI server | - |
| `CLAUDE.md` | Wiki protocol for LLM agents (page format, operations, quality rules) | - |
| `.claude/agents/` | Claude Code agents: `wiki-agent.md`, `knowledge-query.md` + 3 skills | - |

Directory structure:

```
knowledge-engine/
  sources/          - Raw documents (immutable)
    pdfs/
    emails/
    conversations/
    web-captures/
  wiki/             - LLM-generated markdown (Obsidian-compatible)
    {client-slug}/
    _shared/
    _templates/
  schema/           - Machine-readable structure
    entities.json
    graph.json
    tags.json
  demo/             - Sample data for GCC retail AI project
  bridge.py
  bridge_config.py
  server.py
  index.md          - Master page catalog
  log.md            - Append-only activity timeline
  CLAUDE.md         - Agent protocol
```

---

## Why Not Just Use a Vector DB?

You don't need one. Seriously.

A well-organized folder of markdown files with grep handles 500+ documents without breaking a sweat. Full-text search on 500 markdown files takes under a second. You know your own vocabulary - you wrote the docs. Grep finds them.

The entire vector DB ecosystem (Pinecone, ChromaDB, Weaviate, pgvector) solves a problem most teams don't have. They add infrastructure, embedding drift, re-indexing pipelines, and monthly bills to something a filesystem already handles.

**What this project does instead:**

Wiki pages are markdown. You can read them. Open them in Obsidian. Send them to a colleague. Grep across them. No embeddings to maintain. No servers to run. No databases to migrate.

The Memvid layer is optional. It adds sub-5ms semantic search for the edge case where you have thousands of pages and need fuzzy matching across languages or synonyms. Most people won't need it. The wiki is the product.

| Scale | Wiki (grep) | Wiki + Memvid |
|---|---|---|
| 50 pages | Instant | Unnecessary |
| 500 pages | Under 1 second | Nice to have |
| 5,000 pages | 2-3 seconds | Earns its keep |

The Bridge keeps both in sync so you never have to choose. But if you forced us to pick one layer, we'd pick the wiki every time. Humans need to read what the AI knows. A .mv2 file can't give you that. A markdown folder can.

---

## Demo Data

`demo/` contains three sample files for a fictional GCC retail AI engagement:

- `sample-proposal.md` - Project proposal with budget, team, competition
- `sample-meeting-notes.md` - Kickoff meeting notes with action items
- `sample-research.md` - Market analysis with competitor data

Run `python3 bridge.py ingest demo/<file> retailcorp` on all three to see the dual-layer system end to end.

---

## Credits

- LLM Wiki pattern: [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- Memvid memory layer: [Olow304/memvid](https://github.com/Olow304/memvid)
- Bridge + fusion: Tashi

---

## Contributing

PRs welcome. Keep the bridge dependency-light. Memvid must stay optional.

1. Fork the repo
2. Add your feature or fix
3. Run `python3 bridge.py stats` to verify nothing broke
4. Open a PR with what changed and why

---

## License

MIT
