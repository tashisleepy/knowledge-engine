# Knowledge Engine

> **The bridge between human-readable wikis and machine-speed memory.**
> Built on Karpathy's LLM Wiki pattern + Memvid. Designed for AI-augmented knowledge workers.

If you use Claude (or any LLM) every day to build, write, research, or ship — this is your second brain. It captures everything you do, organises it as a wiki, makes it instantly searchable, and gives you a beautiful local dashboard to see your work, your tools, and your monthly value at a glance.

---

## ⚡ What You Actually Get

```
┌──────────────────────────────────────────────────────────────────┐
│  http://localhost:3141                                            │
├──────────────────────────────────────────────────────────────────┤
│  Dashboard │ Search │ Wiki │ Entities │ Health │ Tool Caller │ Month in Nutshell │
└──────────────────────────────────────────────────────────────────┘
```

A self-hosted dashboard with **7 tabs**, each solving a real problem AI-augmented workers hit every week.

### 🎨 Beautiful Local UI
Dark-theme dashboard you launch with one command. No login. No cloud. No subscription. Loads in <100ms.

### 🔍 Dual-Layer Search (Wiki + Memvid)
Type a question. Get answers from your wiki (curated) AND from raw documents (semantic). Source-attributed, citation-linked. Sub-5ms even at 5,000+ documents.

### 📚 Auto-Maintained Wiki
Every document, conversation, or session you ingest becomes a markdown wiki page with frontmatter, wikilinks, and entity extraction. Browse in Obsidian, VS Code, or the built-in viewer.

### 🛠️ Tool Caller — Your Personal AI Stack Inventory
**Every** agent, skill, MCP, script, knowledge file, prompt, and project you've built — in one searchable, filterable table. Filter by type. Search by name. Click to copy the invocation command. **Discover tools you forgot you built 3 months ago.**

### 📊 "Month in a Nutshell" — The Killer Feature
One tab that shows everything you produced this month:
- **Hours breakdown** by category (sessions, tools, documents) with editable rates
- **Value calculation** — defensible market rates for the work output (conservative → senior consultant → partner-tier)
- **Tools breakdown** by type (Skills, Agents, MCPs, Scripts, Prompts, Knowledge Files, Projects) with BUILT vs INSTALLED badges
- **Document tally** — PDFs, DOCX, PPTX, Markdown files generated
- **Sessions list** — every work session with one-click jump to the wiki page
- **Tools detail** — every single tool built this month with descriptions
- Auto-regenerated; never stale

> *"What did I do this month?" — answered in 3 seconds, with a number you can show a client.*

### 📅 Date-Range Reports — Stop Guessing What You Did
```bash
./scripts/report.sh --week              # last 7 days
./scripts/report.sh --month             # last 30 days
./scripts/report.sh --quarter           # last 90 days
./scripts/report.sh --since 2026-01-01  # custom date
./scripts/report.sh --month --client acme  # filter by client
```
Outputs clean markdown. Pipe to a file. Send to your boss. Never write a status report from memory again.

### 🤖 Talk to Claude in Plain English
The repo includes Claude Code agents that handle wiki operations and reports. Just say:
```
"Save this session to my wiki under client acme"
"Generate a monthly retrospective for this quarter"
"Register this new agent I just built"
"Show me everything I worked on between Jan and Mar 2026"
```
Claude runs the scripts, files the records, generates the reports.

### 🧠 Idempotent by Design
Every script can be re-run 100 times — same end state, no duplicates, no corruption. Sessions update in place. Indexes never duplicate. Logs preserve full history. **You can't break it.**

### 🔗 Disaster-Recovery Companion: [claude-backup-system](https://github.com/tashisleepy/claude-backup-system)
A sister repo (also open source, MIT) that automatically backs up everything in this Knowledge Engine — plus your `.claude/` agents, skills, MCP configs, and projects — to an external SSD AND Google Drive once a month at 2 AM. Set up once, automated forever. If your Mac dies tomorrow, you restore from a single tar.gz.

---

## 🚀 Quick Start (60 seconds)

```bash
git clone https://github.com/tashisleepy/knowledge-engine.git
cd knowledge-engine
pip install -r requirements.txt    # memvid-sdk + pymupdf + portalocker

# Try the demo data
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

Memvid is **optional**. The wiki layer alone handles thousands of documents. Add Memvid only if you genuinely need sub-5ms semantic search across 5,000+ pages.

---

## 🏛️ The Three Components

### 1. The LLM Wiki (Karpathy's Pattern)
Andrej Karpathy published this April 3, 2026. Stop re-deriving answers from raw documents on every query. Have an LLM build and maintain a persistent, structured wiki that **compounds over time**.

- **Raw sources** — immutable evidence
- **Wiki pages** — LLM-generated markdown, organised by client/project
- **Schema** — entities, relationships, tag taxonomy, all machine-readable

Plain markdown in a git repo. Browse in Obsidian. The human reads. The LLM maintains. Knowledge **compounds** instead of decaying.

Credit: [Karpathy's gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

### 2. Memvid (The Machine Layer)
Single-file memory for AI agents. 14K GitHub stars. Number 1 trending when it shipped.

- One portable `.mv2` file holds data, embeddings, and search index
- Sub-5ms retrieval, no databases, no servers, no infrastructure
- Append-only, immutable Smart Frames with timestamps and checksums

Think SQLite for AI memory.

Credit: [Olow304/memvid](https://github.com/Olow304/memvid)

### 3. The Bridge (Why This Project Exists)
The wiki and Memvid solve different problems. Nobody connected them. That's the Bridge.

| Feature | Wiki Only | Memvid Only | Bridge (Both) |
|---|---|---|---|
| Human browsable | ✅ | ❌ | ✅ |
| Machine searchable | Slow grep | 2ms | 2ms + structured |
| Cross-references | ✅ | ❌ | ✅ |
| Entity extraction | Manual | ❌ | Automatic |
| Contradiction detection | Manual | ❌ | Automatic |
| Obsidian compatible | ✅ | ❌ | ✅ |
| Scales to 10K+ docs | Slow | ✅ | ✅ |
| Knowledge compounds | If maintained | ❌ | Auto-maintained |

Five operations:
1. **INGEST** — write wiki page + Memvid frame in one atomic op
2. **SEARCH** — wiki first (curated), Memvid fallback (raw), merged with attribution
3. **SYNC** — keep both layers in lockstep via content hashing
4. **DRIFT** — detect when layers disagree, flag before it compounds
5. **LINT** — check contradictions, orphan pages, missing cross-refs

```
Source Document
      │
      ▼
   [BRIDGE]
      │
      ├──► Wiki Layer (Obsidian-compatible markdown)
      │    Frontmatter + citations + confidence + tags + [[wikilinks]]
      │
      ├──► Memvid Layer (.mv2 archive)
      │    Smart Frames + sub-5ms semantic search
      │
      └──► Schema Layer (entities.json, graph.json, tags.json)
           Auto-extracted entities + relationships + tag taxonomy
```

---

## 🖥️ Web UI — Tab by Tab

Launch: `python3 server.py` → http://localhost:3141

| Tab | What It Does |
|---|---|
| **Dashboard** | Stats cards, per-client document counts, recent activity timeline |
| **Search** | Dual-layer results, wiki/memvid source badges, citation links |
| **Wiki** | Sidebar tree, rendered markdown with frontmatter confidence badges |
| **Entities** | Filterable table of auto-extracted companies, people, products, technologies |
| **Health** | Drift check, sync status, lint report summary |
| **Tool Caller** | Searchable inventory of every tool/skill/agent/MCP/script you've built. Type filters, BUILT/INSTALLED badges. Click to copy invocation command. |
| **Month in Nutshell** | Visual monthly review — hours breakdown, value calculation, tools by type, sessions list, document tally |

---

## 🛠️ CLI Reference

| Command | What It Does | Example |
|---|---|---|
| `init` | Create new workspace | `bridge.py init --project "Research" --clients "a,b"` |
| `ingest` | Process source into both layers | `bridge.py ingest doc.pdf my-client` |
| `search` | Dual-layer search | `bridge.py search "quarterly revenue"` |
| `sync` | Sync wiki to Memvid | `bridge.py sync` |
| `drift` | Check layer synchronization | `bridge.py drift` |
| `stats` | System overview | `bridge.py stats` |
| `repair` | Fix corrupted archives | `bridge.py repair` |

Source formats: `.md`, `.txt`, `.pdf`. Platforms: macOS / Linux / Windows.

---

## 📅 Reports & Status Updates

Stop scrolling Slack. Stop guessing dates. Stop writing status reports from memory.

### Just ask Claude
```
"Give me my work report for the last 7 days."
"Generate a quarterly retrospective for client {slug}."
"Show me everything between 2026-01-01 and 2026-03-31."
"Build a monthly status update covering all clients."
```

### Or run it yourself
```bash
./scripts/report.sh --week        # Last 7 days
./scripts/report.sh --month       # Last 30 days
./scripts/report.sh --quarter     # Last 90 days
./scripts/report.sh --year        # Last 365 days
./scripts/report.sh --since 2026-04-01
./scripts/report.sh --between 2026-01-01 2026-03-31
./scripts/report.sh --month --client {slug}
./scripts/report.sh --week > reports/weekly-$(date +%Y-%m-%d).md
```

---

## 🧰 Tools Registry

Every AI tool you build — agents, skills, MCP tools, scripts, knowledge files, prompts — gets registered. Shows up in the Tool Caller tab and future reports.

### Just ask Claude
```
"Register this new script as a tool — it does {description}"
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
  --path "relative/path"
```

Valid types: `agent-global` · `agent-project` · `skill` · `mcp-tool` · `script` · `project` · `knowledge-file` · `prompt`

What it does:
- Appends to `tools-registry.json` (LOCAL only, gitignored)
- Prepends `TOOL-REGISTERED` entry to `log.md`
- Tool appears in Web UI Tool Caller tab
- Shows in date-range reports

---

## 💾 Save Sessions

Three ways. Each idempotent (run 100x = same result, no duplicates).

### Quickest: save-session.sh
```bash
./scripts/save-session.sh \
  --slug "my-topic" \
  --client {client-slug} \
  --title "Session Title" \
  --summary "What this session accomplished" \
  --tags "tag1,tag2,tag3" \
  --duration 1.5
```

Guarantees:
- Existing session → UPDATE in place, preserve `created`, set new `updated`
- New session → CREATE source + wiki + log + index entries
- Index row: only one per session (updates, never duplicates)
- Log timeline: full history preserved
- Pressure-tested: re-run 5x → same end state, full version history

### Automatic (every ingest)
```bash
python3 bridge.py ingest path/to/document.pdf {client-slug}
# Auto-logs: ## [YYYY-MM-DD HH:MM] INGEST | source -> wiki/path (created)
```

### Manual via Claude
```
"Save this session to Knowledge Engine wiki under client {slug}"
"Log this work session in my wiki — title it {topic}"
"Add today's session to the wiki with full details"
```

---

## 🏗️ Architecture

| File | Purpose |
|---|---|
| `bridge.py` | Core engine — ingest, search, sync, drift, lint (1,575 lines) |
| `bridge_config.py` | Configuration constants |
| `server.py` | Local web UI server |
| `ui.html` | Single-file dashboard (no build step, vanilla JS) |
| `CLAUDE.md` | Wiki protocol for LLM agents |
| `.claude/agents/` | Claude Code agents + skills |

```
knowledge-engine/
  sources/            Raw documents (immutable)
    pdfs/ emails/ conversations/ web-captures/
  wiki/               LLM-generated markdown (Obsidian-compatible)
    {client-slug}/ _shared/ _templates/
  schema/             Machine-readable structure
    entities.json graph.json tags.json
  scripts/            Helper scripts
    report.sh save-session.sh register-tool.sh generate-monthly-summary.sh
  demo/               Sample data
  bridge.py
  server.py
  ui.html
  index.md            Master page catalog
  log.md              Append-only activity timeline
```

---

## 🤔 Why Not Just a Vector DB?

You don't need one. Seriously.

A well-organised folder of markdown files with `grep` handles 500+ documents under 1 second. You wrote the docs — you know your vocabulary. Grep finds them. The vector DB ecosystem (Pinecone, Chroma, Weaviate, pgvector) solves a problem most teams don't have. They add infrastructure, embedding drift, re-indexing pipelines, and monthly bills to something a filesystem already handles.

**This project's bet:** Wiki pages are markdown. You can read them. Open them in Obsidian. Grep across them. No embeddings to maintain. No servers to run. No databases to migrate.

The Memvid layer is **optional**. Add it only when you have thousands of pages and need fuzzy semantic search across languages or synonyms.

| Scale | Wiki (grep) | Wiki + Memvid |
|---|---|---|
| 50 pages | Instant | Unnecessary |
| 500 pages | <1 sec | Nice to have |
| 5,000 pages | 2-3 sec | Earns its keep |

If forced to pick one layer, pick the wiki every time. **Humans need to read what the AI knows. A `.mv2` file can't give you that. A markdown folder can.**

---

## 🎁 Demo Data

`demo/` contains three sample files for a fictional GCC retail AI engagement:
- `sample-proposal.md` — Project proposal with budget, team, competition
- `sample-meeting-notes.md` — Kickoff notes with action items
- `sample-research.md` — Market analysis with competitor data

Run `python3 bridge.py ingest demo/<file> retailcorp` on all three to see the dual-layer system end to end.

---

## 🧱 Companion Project

**[claude-backup-system](https://github.com/tashisleepy/claude-backup-system)** — Automated monthly backups of your entire Claude Code workflow (this Knowledge Engine + agents + skills + MCP config + projects) to external SSD and Google Drive. MIT licensed. Set up once, automated forever via launchd.

Together they form the complete stack:
- **Knowledge Engine** = capture, organise, query, report
- **Backup System** = ensure none of it is ever lost

---

## 🙏 Credits

- LLM Wiki pattern: [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- Memvid memory layer: [Olow304/memvid](https://github.com/Olow304/memvid)
- Bridge + UI + monthly review system: built for the Claude Code community

---

## 🤝 Contributing

PRs welcome. Keep the bridge dependency-light. Memvid must stay optional.

1. Fork the repo
2. Add your feature or fix
3. Run `python3 bridge.py stats` to verify nothing broke
4. Open a PR with what changed and why

Wanted contributions:
- Windows/Linux launchd alternatives
- More ingest formats (DOCX, ePub, HTML)
- Encryption layer for the wiki
- Dashboard themes (light mode)
- Notification webhooks (Slack, Discord, email)

---

## 📜 License

MIT. Use it, fork it, improve it.
