# Knowledge Engine

The bridge between human-readable wikis and machine-speed memory. Built on Karpathy's LLM Wiki pattern + Memvid.

---

## What This Actually Does

Knowledge workers produce massive amounts of documents - proposals, meeting notes, research, client briefs. Every time a question comes up, they re-read everything from scratch. Notes exist but aren't searchable at machine speed. Knowledge decays instead of compounding.

Knowledge Engine takes your source documents and creates two synchronized layers: a human-readable wiki you browse in Obsidian, and a machine-searchable memory that returns results in under 5ms. You drop in a document once. From that point, both a consultant and an AI agent can query it instantly without touching the original file again.

The Bridge is the Python script that keeps both layers in lockstep. Without it, you have two separate tools doing different things. With it, every ingest is one atomic operation that writes the wiki page and the memory frame simultaneously, keeps them hashed against each other, and alerts you when they drift.

**Fair warning:** If you have fewer than 50 documents, the wiki layer alone does the job. The Memvid layer and the Bridge add real value at scale (500+ documents, multiple clients or projects). Memvid is optional by design - start with the wiki, add the machine layer when you outgrow grep.

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

## Why the Bridge Matters (Honest Version)

At 5 wiki pages, you don't need the Bridge. Grep finds anything in under 50ms. The wiki alone is plenty.

At 500 pages across 20 clients, grep takes seconds and misses semantic matches. You need a machine layer. But a machine layer alone is opaque - you can't browse a .mv2 file, you can't audit what the AI "knows," and you can't hand a binary archive to a colleague and say "read this."

That's the real scale where the Bridge earns its complexity:

| Scale | Wiki Only | Wiki + Bridge + Memvid |
|---|---|---|
| 5 pages | Works fine, use this | Overkill |
| 50 pages | Still fine | Starting to help |
| 500 pages | Search takes 2-3s, misses related concepts | 2ms, finds connections across clients |
| 5,000 pages | Unusable without indexing | Still 2ms |

The Bridge is not magic. It's a sync layer between two formats optimized for different consumers: humans read markdown, machines search embeddings. The engineering pattern is real - it's just premature at small scale.

If you're one person with 20 documents, use the wiki alone. Memvid is optional for a reason.

If you're a consulting firm with 500+ source documents across a dozen engagements and you need an analyst to find "what did we learn about supply chain risk in GCC last year" in under a second - that's what this is for.

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
