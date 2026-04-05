# Knowledge Engine - Wiki Protocol

## Purpose

This is a persistent knowledge base. It replaces re-deriving answers from raw documents with a living, compounding intelligence layer maintained by LLM agents.

Every question answered here stays answered. Every source ingested compounds into structured knowledge. Agents read from this layer instead of starting from scratch.

---

## Architecture

### Layer 1: Sources (Read-Only)

Location: `knowledge-engine/sources/`

Rule: IMMUTABLE. Never modify source files. They are evidence.

Types: PDFs, emails, conversations, web captures, images, exported chat logs, spec documents, contracts, research outputs.

Sub-structure:
```
sources/
  pdfs/          - PDF documents
  emails/        - Email exports
  conversations/ - Chat/meeting transcripts
  web-captures/  - Saved web pages
  images/        - Screenshots, diagrams
```

### Layer 2: Wiki (LLM-Owned)

Location: `knowledge-engine/wiki/`

Rule: LLM agents create and maintain all content. Humans browse and curate.

Structure:
```
wiki/
  {client-slug}/     - One directory per client engagement
  _shared/           - Cross-client concepts, markets, technologies
  _templates/        - Page templates (never instantiate in place)
```

### Layer 3: Schema (Machine-Readable)

Location: `knowledge-engine/schema/`

Files:
- `entities.json` - All named entities (companies, people, products, technologies)
- `graph.json` - Relationship graph between entities and wiki pages
- `tags.json` - Tag registry with page counts and definitions

Rule: Updated by wiki agent after every ingest operation. Schema must stay in sync with wiki content at all times.

Note: `graph.json` and `tags.json` are populated by the bridge's entity extraction during ingest. They start as empty structures and grow with each ingested source. Do not expect them to be pre-populated.

---

## Special Files

| File | Purpose | Update rule |
|---|---|---|
| `index.md` | Master catalog. One entry per wiki page. | After every wiki operation |
| `log.md` | Append-only activity timeline. | After every ingest, query-filed, or lint |
| `schema/entities.json` | Entity registry | After every ingest |
| `schema/graph.json` | Relationship graph | After every ingest |
| `schema/tags.json` | Tag definitions and counts | After every ingest |

---

## Page Format

All wiki pages use YAML frontmatter. The full template:

```markdown
---
title: [Page Title]
type: [overview|entity|concept|source-summary|comparison|deliverable]
client: [client-slug]
sources:
  - [path/to/source/file]
tags:
  - [tag1]
  - [tag2]
related:
  - "[[client/related-page]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: [high|medium|low]
---

## Summary

[2-3 sentences. Specific. No abstractions. What is this page about and why does it matter?]

## Key Facts

- [Fact 1] (source: filename, p.N)
- [Fact 2] (source: filename)

## Detail

[Main content organized by subtopic]

## Open Questions

- [What we don't know yet]
- [What needs verification]

## Cross-References

- [[related/page-1]] - [relationship description]
- [[related/page-2]] - [relationship description]
```

Frontmatter field rules:
- `type`: Must match one of the six defined page types
- `client`: Use the slug from Client Directories section below. Use `_shared` for cross-client pages
- `sources`: Relative paths from `knowledge-engine/` root
- `confidence`: Set to `low` if based on a single source or unverified claim. Explain why in the page body.
- `updated`: Agents must update this field on every edit

---

## Page Types

| Type | Purpose | Example |
|---|---|---|
| `overview` | Client or topic summary | `example-client/overview.md` |
| `entity` | Company, person, product, or technology profile | `example-client/product-overview.md` |
| `concept` | Technical concept, framework, or methodology | `_shared/demand-forecasting.md` |
| `source-summary` | Summary of a single ingested source | `example-client/proposal-v2.md` |
| `comparison` | Side-by-side analysis of alternatives | `_shared/vendor-comparison.md` |
| `deliverable` | Work product description and outcome | `example-client/audit-report.md` |

Each type has a distinct role. Do not use `entity` for abstract concepts. Do not use `concept` for named products. When in doubt: if it has a proper name and exists in the world, it is an entity. If it is an idea or methodology, it is a concept.

---

## Client Directories

Each directory under `wiki/` represents one engagement.

| Slug | Client | Domain | Status |
|---|---|---|---|
| `example-client` | Your Client Name | Your domain | Active |
| `_shared` | Shared cross-client knowledge | - | Always active |

Add your own clients by creating directories under wiki/ and running `bridge.py init --clients your-client-name`

Adding a new client manually:
1. Create directory `wiki/[slug]/`
2. Create `wiki/[slug]/overview.md` using the `client-overview.md` template
3. Add entry to `index.md` under Clients section
4. Add entity to `schema/entities.json`
5. Log the creation in `log.md`

---

## Cross-Reference Syntax

Use Obsidian-compatible wikilinks throughout all wiki pages.

Format: `[[path/page-name]]`

Examples:
- `[[client-a/product-overview]]` - links to a client entity page
- `[[_shared/market-analysis]]` - links to a shared concept page
- `[[client-b/proposal-q2]]` - links to a deliverable page

Rules:
- Always use the path relative to `wiki/`
- Never link to a page that does not exist. Create the stub first or use a comment: `<!-- TODO: create [[page]] -->`
- Use the `related` frontmatter field to declare the most important links. Inline links in body text for secondary references.

---

## Quality Standards

These rules apply to every wiki page created or updated:

**Claims and Citations**
- Every factual claim must cite a source: `(source: filename)` or `(source: filename, p.N)` or `(wiki: [[page]])`
- If no source exists for a claim, mark it as an inference: `(inferred)`
- Never state something as fact without a citation or an explicit inference marker

**Structure**
- Use tables for any comparison of 2+ items. Always.
- Rate numerically when evaluating: use a 1-10 scale with specific reasoning for the gap to 10
- Lead with the answer, then explain. Never bury the conclusion.

**Confidence**
- If information is uncertain, set `confidence: low` in frontmatter and explain why in the Summary section
- `confidence: medium` means: likely correct but based on one source or contains inferences
- `confidence: high` means: cross-referenced from multiple sources or verified by the client

---

## Operations

Three operations govern all wiki activity. Full execution protocols are in `wiki-agent.md`.

### INGEST

Trigger: New source file added to `sources/[client]/`

Steps:
1. Read the source file completely
2. Identify all entities, concepts, facts, and relationships it contains
3. For each item: check if a wiki page exists. Create if not, update if yes.
4. Typical output: 5-15 wiki pages created or updated per source
5. Update `schema/entities.json`, `schema/graph.json`, `schema/tags.json`
6. Update `index.md` with all new or changed pages
7. Append to `log.md`: `[date] INGEST | [filename] | [N pages created] | [M pages updated]`

Ingest does not summarize the source into one page. It distributes knowledge across the right pages.

### QUERY

Trigger: User asks a question about a client or topic

Steps:
1. Search `index.md` for relevant pages
2. Read the relevant wiki pages
3. Synthesize an answer with citations to wiki pages and sources
4. If the answer surface is substantial and reusable: file it as a new `deliverable` or `comparison` page
5. Log queries that generate new pages: `[date] QUERY-FILED | [question] | [new page created]`

QUERY never reads source files directly unless the wiki contains no relevant pages. The wiki layer is the primary retrieval target.

### LINT

Trigger: Manual request or after every 10 ingest operations

Checks:
1. Orphan pages - pages with no incoming links from other wiki pages
2. Dead links - wikilinks pointing to pages that do not exist
3. Stale pages - pages not updated in 90+ days with sources that have been updated
4. Missing citations - claims without source or inference markers
5. Schema drift - entities in wiki pages not registered in `entities.json`
6. Coverage gaps - source files with no corresponding wiki pages

Output: Report filed as `wiki/lint-report-YYYY-MM-DD.md`. Not a wiki page (no frontmatter). Fix critical issues immediately. Log: `[date] LINT | [N issues found] | [M fixed] | [report path]`

---

## Immutability Rules

These rules are absolute. No exceptions.

1. `sources/` is NEVER modified by any agent. Sources are read-only evidence.
2. `index.md` and `log.md` are ALWAYS updated after any wiki modification.
3. Schema files are ALWAYS kept in sync with wiki content.
4. Existing wiki pages are updated (not replaced) when new information arrives. History is preserved through the `updated` field.
5. Page deletion requires explicit user approval. Agents flag candidates for deletion but do not delete.
6. `_templates/` files are NEVER instantiated in place. Copy to the target directory first.

---

## Index Entry Format

Each entry in `index.md` follows this format:

```
| [[client/page-slug]] | type | one-line description | updated date | confidence |
```

Example:
```
| [[client-a/product-overview]] | entity | Product description with key specs | 2026-04-05 | high |
```

---

## Log Entry Format

All log entries are appended to `log.md` in reverse-chronological order (newest first).

```
## [YYYY-MM-DD] OPERATION | Brief description
- Detail line 1
- Detail line 2
```

Operations: `INIT`, `INGEST`, `QUERY`, `QUERY-FILED`, `LINT`, `UPDATE`, `CLIENT-ADDED`

---

## Schema Formats

### entities.json

```json
{
  "version": 1,
  "updated": "YYYY-MM-DD",
  "entities": [
    {
      "id": "slug-here",
      "name": "Full Name",
      "type": "company|person|product|technology|brand",
      "client": "client-slug",
      "wiki_page": "client/page-slug",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

### graph.json

```json
{
  "version": 1,
  "updated": "YYYY-MM-DD",
  "nodes": [
    { "id": "client/page-slug", "type": "page-type", "client": "client-slug" }
  ],
  "edges": [
    { "from": "client/page-a", "to": "client/page-b", "label": "relationship description" }
  ]
}
```

### tags.json

```json
{
  "version": 1,
  "updated": "YYYY-MM-DD",
  "tags": {
    "tag-name": {
      "count": 0,
      "description": "What this tag means",
      "pages": ["client/page-slug"]
    }
  }
}
```
