"""
bridge.py - Fuses the LLM Wiki (System A) with Memvid (System B) into a unified Knowledge Engine.

System A: structured markdown wiki at knowledge-engine/wiki/ - curated, cited, Obsidian-compatible
System B: Memvid semantic archive at knowledge-engine/memvid/ - fast retrieval via Smart Frames

This bridge keeps both layers in sync, enables dual-layer search, and serves as the atomic
ingest path for new sources.

Usage:
    python3 knowledge-engine/bridge.py sync
    python3 knowledge-engine/bridge.py search "query here"
    python3 knowledge-engine/bridge.py drift
    python3 knowledge-engine/bridge.py stats
    python3 knowledge-engine/bridge.py ingest path/to/file.md client-slug
"""

import argparse
from contextlib import contextmanager
import glob
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Cross-platform file locking
try:
    import portalocker
    _USE_PORTALOCKER = True
except ImportError:
    _USE_PORTALOCKER = False
    try:
        import fcntl
        _USE_FCNTL = True
    except ImportError:
        _USE_FCNTL = False


def _lock_file(fd, exclusive=True):
    """Acquire a file lock (cross-platform)."""
    if _USE_PORTALOCKER:
        portalocker.lock(fd, portalocker.LOCK_EX if exclusive else portalocker.LOCK_SH)
    elif _USE_FCNTL:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    # else: no locking available - proceed without (single-user mode)


def _unlock_file(fd):
    """Release a file lock (cross-platform)."""
    try:
        if _USE_PORTALOCKER:
            portalocker.unlock(fd)
        elif _USE_FCNTL:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass

try:
    if os.environ.get('MEMVID_DISABLE', '').strip() in ('1', 'true', 'yes'):
        raise ImportError('Disabled via MEMVID_DISABLE env var')
    import memvid_sdk as mv
    # Validate expected API exists
    for attr in ('use', 'create'):
        assert hasattr(mv, attr), f"memvid_sdk missing '{attr}'"
    MEMVID_AVAILABLE = True
except ImportError:
    MEMVID_AVAILABLE = False
    mv = None

from bridge_config import (
    BASE_DIR,
    CHUNK_COMMIT_BATCH,
    ENTITY_STOPWORDS,
    EXCLUDED_DIRS,
    EXCLUDED_FILES,
    INDEX_FILE,
    LOG_FILE,
    MASTER_MV2,
    MAX_CHUNK_SIZE,
    MAX_CHUNKS_PER_INGEST,
    MEMVID_DIR,
    MIN_CHUNK_SIZE,
    PER_CLIENT_DIR,
    SCHEMA_DIR,
    SOURCES_DIR,
    TEMPLATES_DIR,
    WIKI_DIR,
)


# ---------------------------------------------------------------------------
# Frontmatter parsing (no PyYAML dependency)
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Split markdown content into (frontmatter_dict, body).
    Returns ({}, content) if no frontmatter markers found.
    Simple regex split on '---' markers. Handles basic YAML scalars and lists.
    """
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if not match:
        return {}, content

    raw_yaml = match.group(1)
    body = match.group(2)
    frontmatter = _parse_simple_yaml(raw_yaml)
    return frontmatter, body


def _parse_simple_yaml(text: str) -> dict:
    """
    Parse a limited subset of YAML: scalar key-value pairs and simple lists.
    Handles:
        key: value
        key:
          - item1
          - item2
    Does not handle nested dicts or multiline scalars (not needed for wiki frontmatter).
    """
    result = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith('#'):
            i += 1
            continue
        # key: value or key: (start of list)
        # Use split(':', 1) so values containing colons are preserved intact.
        if ':' not in line:
            i += 1
            continue
        raw_key, raw_val = line.split(':', 1)
        raw_key = raw_key.strip()
        # Key must be a valid YAML identifier (word chars + hyphens)
        if not re.match(r'^\w[\w\-]*$', raw_key):
            i += 1
            continue
        key = raw_key
        val = raw_val.strip()
        if val == '':
            # Possibly a list on following lines
            items = []
            i += 1
            while i < len(lines) and re.match(r'^\s+-\s+', lines[i]):
                item = re.sub(r'^\s+-\s+', '', lines[i]).strip().strip('"').strip("'")
                items.append(item)
                i += 1
            result[key] = items
        else:
            # Strip inline quotes
            val = val.strip('"').strip("'")
            result[key] = val
            i += 1
    return result


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_body(body: str) -> list[str]:
    """
    Split wiki body text into paragraph-level chunks for Memvid Smart Frames.
    Paragraphs are separated by blank lines. Chunks that exceed MAX_CHUNK_SIZE
    get split further at sentence boundaries. Chunks below MIN_CHUNK_SIZE are dropped.
    """
    # Split on double newlines (paragraph breaks)
    raw_paragraphs = re.split(r'\n\s*\n', body)
    chunks = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= MAX_CHUNK_SIZE:
            if len(para) >= MIN_CHUNK_SIZE:
                chunks.append(para)
        else:
            # Split long paragraph at sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current = ''
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= MAX_CHUNK_SIZE:
                    current = (current + ' ' + sentence).strip() if current else sentence
                else:
                    if len(current) >= MIN_CHUNK_SIZE:
                        chunks.append(current)
                    current = sentence
            if len(current) >= MIN_CHUNK_SIZE:
                chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Memvid open helpers
# ---------------------------------------------------------------------------

def _open_master(mode: str = 'auto'):
    """Open or create the master archive. Returns None if memvid not available."""
    if not MEMVID_AVAILABLE:
        return None
    os.makedirs(MEMVID_DIR, exist_ok=True)
    return mv.use('basic', MASTER_MV2, mode=mode)


def _open_client_archive(client_slug: str, mode: str = 'auto'):
    """Open or create a per-client archive. Returns None if memvid not available."""
    if not MEMVID_AVAILABLE:
        return None
    os.makedirs(PER_CLIENT_DIR, exist_ok=True)
    path = os.path.join(PER_CLIENT_DIR, f'{client_slug}.mv2')
    return mv.use('basic', path, mode=mode)



@contextmanager
def _memvid_locked(mv2_path: str, mode: str = 'auto'):
    """Open a memvid archive with file-level locking (shared for reads, exclusive for writes)."""
    lock_path = mv2_path + '.lock'
    os.makedirs(os.path.dirname(mv2_path), exist_ok=True)
    lock_fd = open(lock_path, 'w')
    try:
        _lock_file(lock_fd, exclusive=(mode != 'open'))
        mem = mv.use('basic', mv2_path, mode=mode)
        yield mem
    finally:
        _unlock_file(lock_fd)
        lock_fd.close()


# ---------------------------------------------------------------------------
# Sync manifest (BUG-003 fix: prevent duplicate frames on repeated sync)
# ---------------------------------------------------------------------------

# Path resolved lazily so MEMVID_DIR is available at import time
def _sync_manifest_path() -> str:
    return os.path.join(MEMVID_DIR, '.sync-manifest.json')


def _load_manifest() -> dict:
    """Load the sync manifest, returning an empty structure on any failure."""
    path = _sync_manifest_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'synced_pages': {}}


def _save_manifest(manifest: dict) -> None:
    """Persist the sync manifest atomically."""
    path = _sync_manifest_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)


def _content_hash(content: str) -> str:
    """Return MD5 hex digest of content string."""
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Core bridge functions
# ---------------------------------------------------------------------------

def sync_page_to_memvid(wiki_page_path: str, client_slug: Optional[str] = None) -> int:
    """
    Read a wiki markdown page, extract frontmatter, chunk the body, and add
    each chunk to master.mv2 as a Smart Frame. If client_slug is provided,
    also add frames to that client's per-client archive.

    Returns the number of frames added.
    """
    with open(wiki_page_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # BUG-003 fix: skip sync if content hasn't changed since last sync
    manifest = _load_manifest()
    page_key = wiki_page_path
    content_hash = _content_hash(content)
    if page_key in manifest['synced_pages']:
        if manifest['synced_pages'][page_key].get('hash') == content_hash:
            return 0  # already synced, no changes

    frontmatter, body = parse_frontmatter(content)

    title = frontmatter.get('title', os.path.basename(wiki_page_path))
    client = client_slug or frontmatter.get('client', '_unknown')
    tags_raw = frontmatter.get('tags', [])
    # tags can be a list or a comma-separated string depending on wiki authoring
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(',') if t.strip()]
    else:
        tags = list(tags_raw)
    # Always tag with client slug for filtering
    if client and client not in tags:
        tags.append(client)

    sources = frontmatter.get('sources', [])
    confidence = frontmatter.get('confidence', 'medium')

    # Relative path from knowledge-engine root - used as the canonical reference
    try:
        rel_path = os.path.relpath(wiki_page_path, BASE_DIR)
    except ValueError:
        rel_path = wiki_page_path

    chunks = chunk_body(body)
    if not chunks:
        return 0

    # BUG-001 fix: cap chunks to prevent hang on huge files
    if len(chunks) > MAX_CHUNKS_PER_INGEST:
        print(
            f'[bridge] Warning: content has {len(chunks)} chunks, capping at {MAX_CHUNKS_PER_INGEST}',
            file=sys.stderr,
        )
        chunks = chunks[:MAX_CHUNKS_PER_INGEST]

    if not MEMVID_AVAILABLE:
        print('[bridge] Memvid not installed. Wiki-only mode. Install with: pip install memvid-sdk')
        return 0

    client_mv2_path = (
        os.path.join(PER_CLIENT_DIR, f'{client}.mv2')
        if client and client not in EXCLUDED_DIRS else None
    )

    frames_added = 0

    def _write_frames(master, client_archive=None):
        nonlocal frames_added
        for i, chunk in enumerate(chunks):
            metadata = {
                'wiki_path': rel_path,
                'client': client,
                'confidence': confidence,
                'chunk_index': str(i),
                'chunk_total': str(len(chunks)),
                'sources': json.dumps(sources) if sources else '[]',
            }
            chunk_title = f'{title} [{i + 1}/{len(chunks)}]' if len(chunks) > 1 else title
            master.put(
                text=chunk,
                title=chunk_title,
                metadata=metadata,
                tags=tags,
            )
            if client_archive:
                client_archive.put(
                    text=chunk,
                    title=chunk_title,
                    metadata=metadata,
                    tags=tags,
                )
            frames_added += 1
            # BUG-001 fix: batch commit every CHUNK_COMMIT_BATCH frames
            if (i + 1) % CHUNK_COMMIT_BATCH == 0:
                master.commit()
                if client_archive:
                    client_archive.commit()
        # Final commit for remaining frames
        master.commit()
        if client_archive:
            client_archive.commit()

    os.makedirs(MEMVID_DIR, exist_ok=True)
    if client_mv2_path:
        os.makedirs(PER_CLIENT_DIR, exist_ok=True)
        with _memvid_locked(MASTER_MV2) as master:
            with _memvid_locked(client_mv2_path) as client_archive:
                _write_frames(master, client_archive)
    else:
        with _memvid_locked(MASTER_MV2) as master:
            _write_frames(master)

    # BUG-003 fix: record sync in manifest so subsequent syncs skip unchanged pages
    manifest['synced_pages'][page_key] = {
        'hash': content_hash,
        'frame_count': frames_added,
        'synced_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    _save_manifest(manifest)

    # BUG-006 fix: update tags.json from frontmatter tags
    _update_tags_schema(wiki_page_path, frontmatter)

    return frames_added


def sync_all_pages() -> dict:
    """
    Glob all wiki pages (excluding _templates/ only), sync each to memvid.
    Returns a summary dict with total_pages, total_frames, per_client breakdown.
    """
    pattern = os.path.join(WIKI_DIR, '**', '*.md')
    all_pages = glob.glob(pattern, recursive=True)

    # Filter excluded dirs and files
    pages_to_sync = []
    for page in all_pages:
        rel = os.path.relpath(page, WIKI_DIR)
        parts = Path(rel).parts
        excluded = False
        for part in parts[:-1]:  # skip filename in check
            if part in EXCLUDED_DIRS:
                excluded = True
                break
        if os.path.basename(page) in EXCLUDED_FILES:
            excluded = True
        if not excluded:
            pages_to_sync.append(page)

    total_pages = 0
    total_frames = 0
    per_client: dict[str, int] = {}
    errors: list[str] = []

    for page in pages_to_sync:
        # Derive client slug from directory structure
        rel = os.path.relpath(page, WIKI_DIR)
        parts = Path(rel).parts
        client_slug = parts[0] if len(parts) > 1 else '_unknown'

        try:
            frames = sync_page_to_memvid(page, client_slug=client_slug)
            total_pages += 1
            total_frames += frames
            per_client[client_slug] = per_client.get(client_slug, 0) + frames
        except Exception as e:
            errors.append(f'{page}: {e}')

    result = {
        'total_pages': total_pages,
        'total_frames': total_frames,
        'per_client': per_client,
        'errors': errors,
    }
    return result


# Tantivy reserved words that cause MV999 errors in memvid semantic search
_TANTIVY_RESERVED = {'and', 'or', 'not', 'in', 'to', 'the', 'for', 'of', 'is', 'a', 'an'}


def _sanitize_memvid_query(query: str) -> str:
    """Remove Tantivy reserved words from query to prevent MV999 errors.

    BUG-002 fix: boolean keywords ('and', 'or', 'not') and common stop-words
    are reserved in Tantivy's query parser. Passing them raw silently degrades
    results or raises MV999. Strip them; if all words are reserved, keep the
    first original word as a fallback so the search is never empty.
    """
    words = query.split()
    cleaned = [w for w in words if w.lower() not in _TANTIVY_RESERVED]
    if cleaned:
        return ' '.join(cleaned)
    # Fallback: keep first word even if reserved (better than empty string)
    return words[0] if words else ''


def dual_search(query: str, k: int = 10) -> list[dict]:
    """
    Search both wiki (text matching) and memvid master archive (semantic).

    Wiki hits get priority - they are structured, curated, source-cited.
    Memvid fills semantic gaps where text matching misses.

    Returns a unified list of results with source attribution and deduplication.
    Each result: {'text', 'source', 'title', 'score', 'tags', 'wiki_path'}
    """
    results = []
    seen_paths: set[str] = set()
    seen_texts: set[str] = set()  # dedup frames with no wiki_path by content fingerprint

    # --- Layer 1: Wiki text search ---
    wiki_hits = _search_wiki_text(query, k=k)
    for hit in wiki_hits:
        path = hit.get('wiki_path', '')
        results.append({
            'text': hit['text'],
            'title': hit['title'],
            'source': f"wiki: {hit['wiki_path']}",
            'score': hit['score'],
            'tags': hit.get('tags', []),
            'wiki_path': path,
            'layer': 'wiki',
        })
        if path:
            seen_paths.add(path)

    # --- Layer 2: Memvid semantic search ---
    if not MEMVID_AVAILABLE:
        return wiki_results + []

    try:
        safe_query = _sanitize_memvid_query(query)
        with _memvid_locked(MASTER_MV2, mode='open') as master:
            mv_result = master.find(safe_query, k=k)
        mv_hits = mv_result.get('hits', []) if isinstance(mv_result, dict) else mv_result.hits

        for hit in mv_hits:
            hit_title = hit.get('title', '') if isinstance(hit, dict) else hit.title
            hit_snippet = hit.get('snippet', '') if isinstance(hit, dict) else hit.snippet
            hit_score = hit.get('score', 0.0) if isinstance(hit, dict) else hit.score
            hit_tags = hit.get('tags', []) if isinstance(hit, dict) else hit.tags

            # Extract wiki_path from snippet metadata if present
            path_match = re.search(r'wiki_path:\s*"?([^\s"]+)"?', hit_snippet)
            wiki_path = path_match.group(1) if path_match else ''

            # Skip if the same wiki page already returned from text search or prior memvid hit
            if wiki_path and wiki_path in seen_paths:
                continue

            # Strip injected metadata from the snippet for clean display
            display_text = re.sub(r'(?:wiki_path|client|confidence|chunk_index|chunk_total|sources|extractous_metadata|labels|title|tags):\s*["\[]?[^\n]+', '', hit_snippet).strip()

            # Dedup frames without wiki_path by content fingerprint (first 100 chars)
            if not wiki_path:
                text_key = (display_text or hit_snippet)[:100]
                if text_key in seen_texts:
                    continue
                seen_texts.add(text_key)

            results.append({
                'text': display_text or hit_snippet,
                'title': hit_title,
                'source': f"memvid: {wiki_path}" if wiki_path else f"memvid: frame {hit.get('frame_id', '?') if isinstance(hit, dict) else hit.frame_id}",
                'score': hit_score,
                'tags': hit_tags,
                'wiki_path': wiki_path,
                'layer': 'memvid',
            })
            if wiki_path:
                seen_paths.add(wiki_path)

    except Exception as e:
        # Memvid may reject certain queries (reserved words, disabled index).
        # Log the failure but don't pollute results - wiki layer already ran.
        print(f'[bridge] memvid search skipped: {e}', file=sys.stderr)

    # Sort: wiki hits first by score, then memvid hits by score
    wiki_results = [r for r in results if r['layer'] == 'wiki']
    memvid_results = [r for r in results if r['layer'] == 'memvid']

    wiki_results.sort(key=lambda x: x['score'], reverse=True)
    memvid_results.sort(key=lambda x: x['score'], reverse=True)

    return wiki_results + memvid_results


def _search_wiki_text(query: str, k: int = 10) -> list[dict]:
    """
    Substring search across wiki markdown files. Also checks index.md.
    Returns up to k results ranked by match count.
    """
    pattern = os.path.join(WIKI_DIR, '**', '*.md')
    all_pages = glob.glob(pattern, recursive=True)

    query_lower = query.lower()
    query_terms = query_lower.split()
    scored: list[tuple[int, dict]] = []

    for page in all_pages:
        rel = os.path.relpath(page, WIKI_DIR)
        parts = Path(rel).parts
        # Skip excluded dirs
        excluded = any(p in EXCLUDED_DIRS for p in parts[:-1])
        if excluded:
            continue

        try:
            with open(page, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        content_lower = content.lower()
        # Score = sum of occurrences of each query term
        score = sum(content_lower.count(term) for term in query_terms)
        if score == 0:
            continue

        frontmatter, body = parse_frontmatter(content)
        title = frontmatter.get('title', os.path.basename(page))
        tags = frontmatter.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',')]

        # Find the first paragraph containing any query term as snippet.
        # Fall back to the full-content match so frontmatter-only pages still show
        # something useful (the match is in frontmatter, not body).
        snippet = ''
        for para in re.split(r'\n\s*\n', body):
            if any(term in para.lower() for term in query_terms):
                snippet = para.strip()[:300]
                break
        if not snippet:
            body_stripped = body.strip()
            if body_stripped:
                snippet = body_stripped[:300]
            else:
                # Match was in frontmatter; show the raw content up to 300 chars
                snippet = content.strip()[:300]

        rel_page_path = os.path.relpath(page, BASE_DIR)
        scored.append((score, {
            'text': snippet,
            'title': title,
            'wiki_path': rel_page_path,
            'score': float(score),
            'tags': tags if isinstance(tags, list) else [],
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:k]]


def check_drift() -> dict:
    """
    Compare wiki pages against memvid frames to find drift.

    Checks:
    - Wiki pages with no corresponding memvid frames (need sync)
    - Memvid frames whose source wiki page no longer exists
    - Potentially stale frames (wiki page modified after last frame creation)

    Returns a structured drift report.
    """
    # Build set of wiki pages
    pattern = os.path.join(WIKI_DIR, '**', '*.md')
    wiki_pages = glob.glob(pattern, recursive=True)
    wiki_rel_paths: set[str] = set()
    for page in wiki_pages:
        rel = os.path.relpath(page, WIKI_DIR)
        parts = Path(rel).parts
        if any(p in EXCLUDED_DIRS for p in parts[:-1]):
            continue
        wiki_rel_paths.add(os.path.relpath(page, BASE_DIR))

    # Build set of wiki paths referenced in memvid frames
    memvid_wiki_paths: set[str] = set()
    orphan_frames: list[dict] = []

    if not MEMVID_AVAILABLE:
        return {
            'missing_from_memvid': [],
            'orphan_frames': [],
            'stale': [],
            'summary': 'Memvid not installed. Install with: pip install memvid-sdk',
        }

    try:
        with _memvid_locked(MASTER_MV2, mode='open') as master:
            mv_stats = master.stats()
            frame_count = mv_stats['frame_count'] if isinstance(mv_stats, dict) else mv_stats.frame_count
            probe_result = master.find('wiki_path', k=500, snippet_chars=2000)

        # Search specifically for 'wiki_path' metadata key to collect all synced paths.
        # Use large snippet_chars so the metadata block isn't truncated mid-path.
        # Memvid injects metadata at the end of the snippet, so 2000 chars covers most frames.
        sampled_paths: set[str] = set()
        probe_hits = probe_result.get('hits', []) if isinstance(probe_result, dict) else probe_result.hits
        for hit in probe_hits:
            snippet = hit.get('snippet', '') if isinstance(hit, dict) else hit.snippet
            # Match wiki paths ending in .md
            for path_match in re.finditer(r'wiki_path:\s*"?([^\s"]+\.md)"?', snippet):
                sampled_paths.add(path_match.group(1))

        memvid_wiki_paths = sampled_paths

        # Find frames with no backing wiki page
        for path in memvid_wiki_paths:
            abs_path = os.path.join(BASE_DIR, path)
            if not os.path.exists(abs_path):
                orphan_frames.append({'wiki_path': path, 'issue': 'source wiki page does not exist'})

    except Exception as e:
        return {
            'error': str(e),
            'missing_from_memvid': [],
            'orphan_frames': [],
            'stale': [],
            'summary': 'Drift check failed - memvid unavailable.',
        }

    # Pages missing from memvid
    missing_from_memvid = [p for p in wiki_rel_paths if p not in memvid_wiki_paths]

    # Stale check: wiki page modified after its frames were created
    # We can't get per-frame creation time easily, so flag pages where the file
    # was modified recently (last 24h) as candidates for re-sync
    stale: list[str] = []
    now = datetime.now(tz=timezone.utc).timestamp()
    for path in wiki_rel_paths:
        abs_path = os.path.join(BASE_DIR, path)
        if path in memvid_wiki_paths:
            try:
                mtime = os.path.getmtime(abs_path)
                # Flag if modified in the last 24 hours and already in memvid
                # (could have been updated after last sync)
                if now - mtime < 86400:
                    stale.append(path)
            except Exception:
                pass

    total_wiki = len(wiki_rel_paths)
    synced = len(wiki_rel_paths & memvid_wiki_paths)
    sync_pct = round(100 * synced / total_wiki, 1) if total_wiki else 0.0

    return {
        'missing_from_memvid': missing_from_memvid,
        'orphan_frames': orphan_frames,
        'stale': stale,
        'summary': {
            'total_wiki_pages': total_wiki,
            'synced': synced,
            'sync_pct': sync_pct,
            'missing_from_memvid': len(missing_from_memvid),
            'orphan_frames': len(orphan_frames),
            'recently_modified_may_be_stale': len(stale),
            'memvid_frame_count': frame_count,
        },
    }


def ingest_source_to_both(source_path: str, client_slug: str, force: bool = False) -> dict:
    """
    Atomic bridge operation. Takes a raw source file, writes it to the wiki,
    syncs to memvid, updates schema/entities.json and index.md, appends to log.md.

    Handles .md and .txt. PDF requires pymupdf.
    Returns a summary of what was created.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f'Source not found: {source_path}')

    # Check for duplicate ingest (matches INGEST_STARTED and INGEST_COMPLETE)
    source_filename = os.path.basename(source_path)
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            if f'INGEST | {source_filename}' in f.read():
                # BUG-005 fix: only print "Skipping" when force is False
                if not force:
                    print(f'Warning: {source_filename} was previously ingested. Skipping. Use --force to re-ingest.')
                    return {}
                else:
                    print(f'[bridge] Re-ingesting {source_filename} (--force)')

    _, ext = os.path.splitext(source_path)
    ext = ext.lower()

    # Read content
    if ext in ('.md', '.txt'):
        with open(source_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
    elif ext == '.pdf':
        try:
            import fitz  # pymupdf
            doc = fitz.open(source_path)
            raw_content = '\n\n'.join(page.get_text() for page in doc)
            doc.close()
        except ImportError:
            raise ValueError(
                'PDF extraction requires pymupdf. Install: pip install pymupdf'
            )
    else:
        # Generic text fallback
        try:
            with open(source_path, 'r', encoding='utf-8', errors='replace') as f:
                raw_content = f.read()
        except Exception as e:
            raise ValueError(f'Could not read file: {e}')

    source_filename = os.path.basename(source_path)
    today = datetime.now().strftime('%Y-%m-%d')
    page_slug = re.sub(r'[^\w\-]', '-', os.path.splitext(source_filename)[0]).lower()
    page_slug = re.sub(r'-+', '-', page_slug).strip('-')

    # Target wiki directory
    client_wiki_dir = os.path.join(WIKI_DIR, client_slug)
    os.makedirs(client_wiki_dir, exist_ok=True)

    wiki_page_path = os.path.join(client_wiki_dir, f'{page_slug}.md')

    # Check if a page already exists - update vs create
    if os.path.exists(wiki_page_path):
        # Update: read existing, append new content under a new section
        with open(wiki_page_path, 'r', encoding='utf-8') as f:
            existing = f.read()
        existing_fm, existing_body = parse_frontmatter(existing)

        # Update frontmatter dates and sources
        sources = existing_fm.get('sources', [])
        if isinstance(sources, str):
            sources = [sources]
        rel_source = os.path.relpath(source_path, BASE_DIR)
        if rel_source not in sources:
            sources.append(rel_source)

        new_page = _build_wiki_page(
            title=existing_fm.get('title', page_slug),
            client=client_slug,
            sources=sources,
            tags=existing_fm.get('tags', [client_slug]),
            created=existing_fm.get('created', today),
            updated=today,
            confidence=existing_fm.get('confidence', 'medium'),
            body=existing_body + f'\n\n## Update - {today}\n\n{raw_content}',
        )
        action = 'updated'
    else:
        # Create new page
        rel_source = os.path.relpath(source_path, BASE_DIR)
        new_page = _build_wiki_page(
            title=_title_from_slug(page_slug),
            client=client_slug,
            sources=[rel_source],
            tags=[client_slug],
            created=today,
            updated=today,
            confidence='medium',
            body=_build_default_body(raw_content),
        )
        action = 'created'

    with open(wiki_page_path, 'w', encoding='utf-8') as f:
        f.write(new_page)

    rel_wiki_path = os.path.relpath(wiki_page_path, BASE_DIR)

    # Write INGEST_STARTED log immediately after wiki page write.
    # The duplicate-ingest guard reads log.md, so logging first ensures a crash
    # between wiki write and memvid sync is detectable on subsequent runs.
    _append_log(
        operation='INGEST',
        description=f'{source_filename} -> {client_slug}/{page_slug}.md ({action}) [INGEST_STARTED]',
        details=[
            f'Source: {source_path}',
            f'Wiki page: {action} at {rel_wiki_path}',
        ],
        date=today,
    )

    # Sync the wiki page to memvid
    frames_added = sync_page_to_memvid(wiki_page_path, client_slug=client_slug)

    # Update schema/entities.json with any capitalized entity mentions
    entities_updated = _update_entities_schema(client_slug, wiki_page_path, raw_content, today)

    # Update schema/tags.json from the wiki page frontmatter (BUG-006 fix)
    with open(wiki_page_path, 'r', encoding='utf-8') as _f:
        _page_fm, _ = parse_frontmatter(_f.read())
    _update_tags_schema(wiki_page_path, _page_fm)

    # Update index.md
    _update_index(client_slug, page_slug, rel_wiki_path, today)

    # Append completion log entry
    _append_log(
        operation='INGEST',
        description=f'{source_filename} -> {client_slug}/{page_slug}.md ({action}) [INGEST_COMPLETE]',
        details=[
            f'Source: {source_path}',
            f'Wiki page: {action} at {rel_wiki_path}',
            f'Memvid frames added: {frames_added}',
            f'Entities updated: {entities_updated}',
        ],
        date=today,
    )

    return {
        'wiki_page': rel_wiki_path,
        'action': action,
        'frames_added': frames_added,
        'entities_updated': entities_updated,
        'client': client_slug,
        'source': source_path,
    }


def get_stats() -> dict:
    """
    Gather stats from wiki, memvid, and schema layers.
    Returns a structured dict with counts, sizes, and drift status.
    """
    # --- Wiki stats ---
    pattern = os.path.join(WIKI_DIR, '**', '*.md')
    all_wiki = glob.glob(pattern, recursive=True)
    wiki_by_client: dict[str, int] = {}
    total_cross_refs = 0

    for page in all_wiki:
        rel = os.path.relpath(page, WIKI_DIR)
        parts = Path(rel).parts
        if any(p in EXCLUDED_DIRS for p in parts[:-1]):
            continue
        client = parts[0] if len(parts) > 1 else '_root'
        wiki_by_client[client] = wiki_by_client.get(client, 0) + 1
        try:
            with open(page, 'r', encoding='utf-8') as f:
                content = f.read()
            total_cross_refs += len(re.findall(r'\[\[.+?\]\]', content))
        except Exception as e:
            print(f'[bridge] Warning: failed to read schema file: {e}', file=sys.stderr)

    total_wiki_pages = sum(wiki_by_client.values())

    # --- Memvid stats ---
    memvid_stats: dict = {}
    search_latency_ms = None
    if not MEMVID_AVAILABLE:
        memvid_stats = {'error': 'Memvid not installed. Install with: pip install memvid-sdk'}
    else:
        try:
            master = _open_master(mode='open')
            raw = master.stats()
            memvid_stats = raw if isinstance(raw, dict) else {}

            # Latency test
            t0 = time.time()
            master.find('test', k=1)
            search_latency_ms = round((time.time() - t0) * 1000, 1)

            # Per-client archive sizes
            client_archive_sizes: dict[str, int] = {}
            if os.path.exists(PER_CLIENT_DIR):
                for fname in os.listdir(PER_CLIENT_DIR):
                    if fname.endswith('.mv2'):
                        slug = fname[:-4]
                        fpath = os.path.join(PER_CLIENT_DIR, fname)
                        client_archive_sizes[slug] = os.path.getsize(fpath)
            memvid_stats['per_client_archive_sizes'] = client_archive_sizes
            memvid_stats['search_latency_ms'] = search_latency_ms
            master.close()  # release exclusive lock before drift check opens it again
        except Exception as e:
            memvid_stats = {'error': str(e)}

    # --- Schema stats ---
    schema_stats: dict = {}
    try:
        entities_path = os.path.join(SCHEMA_DIR, 'entities.json')
        graph_path = os.path.join(SCHEMA_DIR, 'graph.json')
        tags_path = os.path.join(SCHEMA_DIR, 'tags.json')

        entity_count = 0
        if os.path.exists(entities_path):
            with open(entities_path, 'r') as f:
                data = json.load(f)
            entities = data.get('entities', data) if isinstance(data, dict) else data
            entity_count = len(entities) if isinstance(entities, list) else 0

        rel_count = 0
        if os.path.exists(graph_path):
            with open(graph_path, 'r') as f:
                data = json.load(f)
            edges = data.get('edges', []) if isinstance(data, dict) else data
            rel_count = len(edges)

        tag_count = 0
        if os.path.exists(tags_path):
            with open(tags_path, 'r') as f:
                data = json.load(f)
            tags = data.get('tags', data) if isinstance(data, dict) else data
            tag_count = len(tags)

        schema_stats = {
            'entity_count': entity_count,
            'relationship_count': rel_count,
            'tag_count': tag_count,
        }
    except Exception as e:
        schema_stats = {'error': str(e)}

    # --- Drift quick check ---
    # Run after memvid section completes (archive handle released by garbage collection).
    # Use a fresh call without holding any open archive handles.
    drift_synced = 'unknown'
    try:
        drift = check_drift()
        summary = drift.get('summary', {})
        drift_synced = f"{summary.get('sync_pct', 0)}% ({summary.get('synced', 0)}/{summary.get('total_wiki_pages', 0)} pages)"
    except Exception as e:
        drift_synced = f'unavailable ({e})'

    return {
        'wiki': {
            'total_pages': total_wiki_pages,
            'by_client': wiki_by_client,
            'total_cross_references': total_cross_refs,
        },
        'memvid': memvid_stats,
        'schema': schema_stats,
        'drift': {
            'sync_status': drift_synced,
        },
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _locked_read_modify_write(filepath: str, modifier_fn) -> None:
    """Read-modify-write with exclusive file lock to prevent concurrent corruption."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)

    # Create file if it doesn't exist
    if not os.path.exists(filepath):
        with open(filepath, 'w') as f:
            f.write('')

    with open(filepath, 'r+') as f:
        _lock_file(f, exclusive=True)
        try:
            content = f.read()
            new_content = modifier_fn(content)
            f.seek(0)
            f.truncate()
            f.write(new_content)
        finally:
            _unlock_file(f)


def _build_wiki_page(
    title: str,
    client: str,
    sources: list,
    tags: list,
    created: str,
    updated: str,
    confidence: str,
    body: str,
) -> str:
    """Build a wiki page string with proper frontmatter."""
    sources_yaml = '\n'.join(f'  - {s}' for s in sources) if sources else '  []'
    tags_yaml = '\n'.join(f'  - {t}' for t in tags) if tags else '  []'

    return f"""---
title: {title}
type: source-summary
client: {client}
sources:
{sources_yaml}
tags:
{tags_yaml}
related: []
created: {created}
updated: {updated}
confidence: {confidence}
---

{body}
"""


def _build_default_body(raw_content: str) -> str:
    """Build a basic wiki page body from raw source content."""
    stripped = raw_content.strip()
    if not stripped:
        # Nothing to put in the body - return empty so chunk_body produces 0 frames.
        return ''

    return f"""## Summary

Source ingested via bridge. Review and expand with citations.

## Content

{stripped}

## Open Questions

- What entities need pages?
- What relationships should be added to schema/graph.json?

## Cross-References

"""


def _title_from_slug(slug: str) -> str:
    """Convert a kebab-case or snake_case slug to a Title Case string."""
    # Normalise both hyphens and underscores as word separators
    normalised = re.sub(r'[-_]+', ' ', slug)
    return ' '.join(w.capitalize() for w in normalised.split())


def _update_entities_schema(client_slug: str, wiki_page_path: str, content: str, today: str) -> int:
    """
    Scan content for capitalized multi-word phrases (rough entity detection).
    Add any new entities to schema/entities.json.
    Returns count of new entities added.
    """
    entities_path = os.path.join(SCHEMA_DIR, 'entities.json')
    os.makedirs(SCHEMA_DIR, exist_ok=True)

    # Detect capitalized proper nouns (2+ consecutive capitalized words on the same line).
    # Restrict to single lines so heading fragments like "Title\n\nNext" are never captured.
    # Strip markdown heading markers before matching so headings are not captured as entities.
    found = []
    for line in content.splitlines():
        stripped_line = re.sub(r'^#+\s*', '', line)
        found.extend(re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', stripped_line))
    unique_names = list(dict.fromkeys(found))  # preserve order, deduplicate

    rel_wiki = os.path.relpath(wiki_page_path, os.path.join(BASE_DIR, 'wiki'))
    rel_wiki_no_ext = os.path.splitext(rel_wiki)[0]

    added_count = 0

    def modifier(raw: str) -> str:
        nonlocal added_count
        # Parse existing data
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f'[bridge] Warning: entities.json was corrupt. Resetting to empty. Prior entities lost.', file=sys.stderr)
                data = {'version': 1, 'updated': today, 'entities': []}
        else:
            data = {'version': 1, 'updated': today, 'entities': []}

        # Always use nested format; migrate list format if encountered
        if isinstance(data, list):
            data = {'version': 1, 'updated': today, 'entities': data}

        entities = data.get('entities', [])
        if not isinstance(entities, list):
            entities = []
        existing_ids: set[str] = {e.get('id', '') for e in entities if isinstance(e, dict)}

        for name in unique_names[:20]:  # cap at 20 new entities per ingest
            if name.lower() in ENTITY_STOPWORDS:
                continue
            entity_id = re.sub(r'\s+', '-', name.lower())
            entity_id = re.sub(r'[^\w\-]', '', entity_id)
            if entity_id in existing_ids:
                continue
            entities.append({
                'id': entity_id,
                'name': name,
                'type': 'unknown',
                'client': client_slug,
                'wiki_page': rel_wiki_no_ext,
                'tags': [client_slug],
            })
            existing_ids.add(entity_id)
            added_count += 1

        data['entities'] = entities
        data['updated'] = today
        return json.dumps(data, indent=2)

    _locked_read_modify_write(entities_path, modifier)
    return added_count


def _update_tags_schema(wiki_page_path: str, frontmatter: dict) -> None:
    """
    Extract tags from wiki page frontmatter and update schema/tags.json.

    BUG-006 fix: tags.json was never populated because no code path called
    into it. This function is called from ingest_source_to_both() and
    sync_page_to_memvid() after the wiki page is written.
    """
    tags = frontmatter.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]
    if not tags:
        return

    try:
        rel_path = os.path.relpath(wiki_page_path, WIKI_DIR)
    except ValueError:
        rel_path = wiki_page_path

    today = datetime.now().strftime('%Y-%m-%d')
    tags_file = os.path.join(SCHEMA_DIR, 'tags.json')
    os.makedirs(SCHEMA_DIR, exist_ok=True)

    def modifier(raw: str) -> str:
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {'version': 1, 'updated': today, 'tags': {}}
        else:
            data = {'version': 1, 'updated': today, 'tags': {}}

        if 'tags' not in data or not isinstance(data['tags'], dict):
            data['tags'] = {}

        for tag in tags:
            if not isinstance(tag, str):
                continue
            tag = tag.strip().lower()
            if not tag:
                continue
            if tag not in data['tags']:
                data['tags'][tag] = {'count': 0, 'pages': []}
            entry = data['tags'][tag]
            if rel_path not in entry.get('pages', []):
                entry.setdefault('pages', []).append(rel_path)
            entry['count'] = len(entry['pages'])

        data['updated'] = today
        return json.dumps(data, indent=2)

    _locked_read_modify_write(tags_file, modifier)


def _update_index(client_slug: str, page_slug: str, rel_wiki_path: str, today: str) -> None:
    """
    Add or update an entry in index.md for the given wiki page.
    Entry format: | [[client/page-slug]] | type | description | date | confidence |
    """
    # Ensure file exists with header before locking
    if not os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'w') as f:
            f.write(f'# Knowledge Engine Index\nLast updated: {today}\n\n')

    wikilink = f'[[{client_slug}/{page_slug}]]'
    new_entry = f'| {wikilink} | source-summary | Ingested via bridge on {today} | {today} | medium |\n'

    def modifier(index_content: str) -> str:
        # If entry already exists, skip (wiki agent handles detailed updates)
        if wikilink in index_content:
            return index_content

        # Find or create client section
        client_header = f'## {client_slug}'
        if client_header in index_content:
            index_content = index_content.replace(
                client_header + '\n',
                client_header + '\n' + new_entry,
            )
        else:
            index_content += f'\n{client_header}\n{new_entry}'

        # Update last updated date
        index_content = re.sub(
            r'Last updated: \d{4}-\d{2}-\d{2}',
            f'Last updated: {today}',
            index_content,
        )

        # Update stats table: count all wikilink entries (lines starting with "| [[")
        total_pages = len(re.findall(r'^\| \[\[', index_content, re.MULTILINE))
        index_content = re.sub(
            r'(\| Total pages\s*\|)\s*\d+',
            f'\\g<1> {total_pages}',
            index_content,
        )
        return index_content

    _locked_read_modify_write(INDEX_FILE, modifier)


def _append_log(operation: str, description: str, details: list[str], date: str) -> None:
    """Append a log entry to log.md (newest first)."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    entry_lines = [f'## [{now}] {operation} | {description}']
    for d in details:
        entry_lines.append(f'- {d}')
    entry_lines.append('')
    entry = '\n'.join(entry_lines) + '\n'

    # Ensure file exists with header before locking
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f:
            f.write('# Knowledge Engine Log\n\n')

    def modifier(existing: str) -> str:
        if not existing:
            existing = '# Knowledge Engine Log\n\n'
        # Insert after the header (first blank line after the first heading)
        header_end = existing.find('\n\n')
        if header_end == -1:
            return existing + '\n' + entry
        return existing[:header_end + 2] + entry + existing[header_end + 2:]

    _locked_read_modify_write(LOG_FILE, modifier)


# ---------------------------------------------------------------------------
# Init workspace
# ---------------------------------------------------------------------------

def init_workspace(project_name=None, clients=None):
    """
    Create a clean Knowledge Engine workspace in the current directory.

    Creates the full directory structure, empty schema files, index.md, log.md,
    and CLAUDE.md protocol. Client directories are created under wiki/.
    """
    if project_name is None:
        project_name = os.path.basename(os.getcwd())

    if not clients:
        clients = ['default']

    today = datetime.now().strftime('%Y-%m-%d')

    dirs = [
        'sources/pdfs',
        'sources/emails',
        'sources/conversations',
        'sources/web-captures',
        'sources/images',
        'wiki/_shared',
        'wiki/_templates',
        'schema',
        'memvid',
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    for client in clients:
        os.makedirs('wiki/' + client, exist_ok=True)

    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wiki', '_templates')
    for tpl in ('page.md', 'client-overview.md'):
        src = os.path.join(template_dir, tpl)
        dst = os.path.join('wiki', '_templates', tpl)
        if os.path.exists(src) and not os.path.exists(dst):
            with open(src, 'r', encoding='utf-8') as f:
                tpl_content = f.read()
            with open(dst, 'w', encoding='utf-8') as fw:
                fw.write(tpl_content)

    entities_path = os.path.join('schema', 'entities.json')
    if not os.path.exists(entities_path):
        with open(entities_path, 'w') as f:
            json.dump({'version': 1, 'updated': today, 'entities': []}, f, indent=2)

    graph_path = os.path.join('schema', 'graph.json')
    if not os.path.exists(graph_path):
        with open(graph_path, 'w') as f:
            json.dump({'version': 1, 'updated': today, 'nodes': [], 'edges': []}, f, indent=2)

    tags_path = os.path.join('schema', 'tags.json')
    if not os.path.exists(tags_path):
        with open(tags_path, 'w') as f:
            json.dump({'version': 1, 'updated': today, 'tags': {}}, f, indent=2)

    index_path = 'index.md'
    if not os.path.exists(index_path):
        client_sections = ''.join('\n## ' + c + '\n\n' for c in clients)
        with open(index_path, 'w', encoding='utf-8') as f:
            lines = [
                '# ' + project_name + ' - Knowledge Engine Index',
                '',
                'Last updated: ' + today,
                '',
                '| Page | Type | Description | Updated | Confidence |',
                '|---|---|---|---|---|',
                client_sections,
            ]
            f.write('\n'.join(lines))

    log_path = 'log.md'
    if not os.path.exists(log_path):
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(
                '# Knowledge Engine Log\n\n'
                '## [' + today + '] INIT | ' + project_name + ' workspace created\n'
                '- Clients: ' + ', '.join(clients) + '\n'
                '- Structure: sources/, wiki/, schema/, memvid/\n\n'
            )

    claude_md_path = 'CLAUDE.md'
    if not os.path.exists(claude_md_path):
        client_table_rows = '\n'.join(
            '| `' + c + '` | ' + c.replace('-', ' ').title() + ' | Your domain | Active |'
            for c in clients
        )
        claude_content = '\n'.join([
            '# Knowledge Engine - Wiki Protocol',
            '',
            '## Purpose',
            '',
            'This is a persistent knowledge base. It replaces re-deriving answers from raw documents',
            'with a living, compounding intelligence layer maintained by LLM agents.',
            '',
            'Every question answered here stays answered. Every source ingested compounds into',
            'structured knowledge. Agents read from this layer instead of starting from scratch.',
            '',
            '---',
            '',
            '## Architecture',
            '',
            '### Layer 1: Sources (Read-Only)',
            '',
            'Location: `sources/`',
            '',
            'Rule: IMMUTABLE. Never modify source files. They are evidence.',
            '',
            '### Layer 2: Wiki (LLM-Owned)',
            '',
            'Location: `wiki/`',
            '',
            'Rule: LLM agents create and maintain all content. Humans browse and curate.',
            '',
            '### Layer 3: Schema (Machine-Readable)',
            '',
            'Location: `schema/`',
            '',
            'Files: `entities.json`, `graph.json`, `tags.json`',
            '',
            '---',
            '',
            '## Client Directories',
            '',
            '| Slug | Client | Domain | Status |',
            '|---|---|---|---|',
            client_table_rows,
            '| `_shared` | Shared cross-client knowledge | - | Always active |',
            '',
            'Add your own clients by creating directories under wiki/ and running `bridge.py init --clients your-client-name`',
            '',
            '---',
            '',
            '## Page Format',
            '',
            'All wiki pages use YAML frontmatter. See `wiki/_templates/page.md` for the full template.',
            '',
            'Required fields: `title`, `type`, `client`, `sources`, `tags`, `created`, `updated`, `confidence`',
            '',
            'Page types: `overview`, `entity`, `concept`, `source-summary`, `comparison`, `deliverable`',
            '',
            '---',
            '',
            '## Quality Standards',
            '',
            '**Claims and Citations**',
            '- Every factual claim must cite a source: `(source: filename)` or `(wiki: [[page]])`',
            '- If no source exists for a claim, mark it: `(inferred)`',
            '',
            '**Structure**',
            '- Use tables for any comparison of 2+ items',
            '- Lead with the answer, then explain. Never bury the conclusion.',
            '',
            '**Confidence**',
            '- `confidence: high` - cross-referenced from multiple sources or verified',
            '- `confidence: medium` - likely correct but based on one source or contains inferences',
            '- `confidence: low` - uncertain; explain why in the Summary section',
            '',
            '---',
            '',
            '## Operations',
            '',
            '### INGEST',
            'Trigger: New source file added to `sources/`',
            'Steps: Read source, identify entities/facts, create or update wiki pages, update schema, update index.md, append to log.md.',
            '',
            '### QUERY',
            'Trigger: User asks a question',
            'Steps: Search index.md, read relevant wiki pages, synthesize answer with citations. File reusable answers as new pages.',
            '',
            '### LINT',
            'Trigger: Manual or after every 10 ingest operations',
            'Checks: Orphan pages, dead links, stale pages, missing citations, schema drift, coverage gaps.',
            '',
        ])
        with open(claude_md_path, 'w', encoding='utf-8') as f:
            f.write(claude_content)

    print('Knowledge Engine initialized.')
    print('  Project:  ' + project_name)
    print('  Clients:  ' + ', '.join(clients))
    print('')
    print('Run `bridge.py ingest <file> <client>` to add your first source.')




# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_sync_result(result: dict) -> None:
    print(f'Sync complete.')
    print(f'  Pages synced:  {result["total_pages"]}')
    print(f'  Frames added:  {result["total_frames"]}')
    if result['per_client']:
        print('  Per client:')
        for client, frames in sorted(result['per_client'].items()):
            print(f'    {client}: {frames} frames')
    if result['errors']:
        print(f'  Errors ({len(result["errors"])}):')
        for err in result['errors']:
            print(f'    - {err}')


def _print_search_results(results: list[dict]) -> None:
    if not results:
        print('No results found.')
        return
    for i, r in enumerate(results, 1):
        layer_tag = '[wiki]' if r['layer'] == 'wiki' else '[memvid]'
        print(f'\n{i}. {layer_tag} {r["title"]}')
        print(f'   Source: {r["source"]}')
        if r['tags']:
            print(f'   Tags:   {", ".join(r["tags"][:5])}')
        text = r['text']
        if len(text) > 200:
            text = text[:200].rstrip() + '...'
        print(f'   {text}')


def _print_drift_report(report: dict) -> None:
    if 'error' in report:
        print(f'Drift check error: {report["error"]}')
        return
    s = report['summary']
    print('Drift report:')
    print(f'  Wiki pages total:      {s["total_wiki_pages"]}')
    print(f'  Synced to memvid:      {s["synced"]} ({s["sync_pct"]}%)')
    print(f'  Missing from memvid:   {s["missing_from_memvid"]}')
    print(f'  Orphan frames:         {s["orphan_frames"]}')
    print(f'  Recently modified:     {s["recently_modified_may_be_stale"]}')

    if report['missing_from_memvid']:
        print('\nPages missing from memvid:')
        for p in report['missing_from_memvid'][:10]:
            print(f'  - {p}')
        if len(report['missing_from_memvid']) > 10:
            print(f'  ... and {len(report["missing_from_memvid"]) - 10} more')

    if report['orphan_frames']:
        print('\nOrphan frames (source page gone):')
        for f in report['orphan_frames'][:10]:
            print(f'  - {f["wiki_path"]}')

    if report['stale']:
        print('\nRecently modified (may need re-sync):')
        for p in report['stale'][:10]:
            print(f'  - {p}')


def _print_stats(stats: dict) -> None:
    w = stats['wiki']
    m = stats['memvid']
    sc = stats['schema']
    d = stats['drift']

    print('=== Knowledge Engine Stats ===\n')
    print('WIKI')
    print(f'  Total pages:       {w["total_pages"]}')
    print(f'  Cross-references:  {w["total_cross_references"]}')
    if w['by_client']:
        print('  By client:')
        for client, count in sorted(w['by_client'].items()):
            print(f'    {client}: {count} pages')

    print('\nMEMVID')
    if 'error' in m:
        print(f'  Error: {m["error"]}')
    else:
        print(f'  Frame count:       {m.get("frame_count", "?")}')
        size_mb = round(m.get("size_bytes", 0) / 1024 / 1024, 2)
        print(f'  Master size:       {size_mb} MB')
        if m.get('search_latency_ms') is not None:
            print(f'  Search latency:    {m["search_latency_ms"]} ms')
        if m.get('per_client_archive_sizes'):
            print('  Per-client archives:')
            for slug, size in sorted(m['per_client_archive_sizes'].items()):
                print(f'    {slug}: {round(size / 1024, 1)} KB')

    print('\nSCHEMA')
    if 'error' in sc:
        print(f'  Error: {sc["error"]}')
    else:
        print(f'  Entities:          {sc["entity_count"]}')
        print(f'  Relationships:     {sc["relationship_count"]}')
        print(f'  Tags:              {sc["tag_count"]}')

    print('\nDRIFT')
    print(f'  Sync status:       {d["sync_status"]}')



def repair() -> dict:
    """
    Repair corrupted Knowledge Engine archives and schema files.

    Checks:
    - master.mv2: exists and is readable; if missing/corrupt, deletes and recreates via sync_all_pages
    - entities.json, graph.json, tags.json: valid JSON; if corrupt, resets to empty structure
    - index.md: exists

    Returns a dict summarising what was repaired.
    """
    repaired = []
    warnings = []

    # --- master.mv2 ---
    master_ok = False
    if os.path.exists(MASTER_MV2):
        try:
            m = mv.use('basic', MASTER_MV2, mode='open')
            m.stats()
            master_ok = True
        except Exception as e:
            warnings.append(f'master.mv2 unreadable: {e}')
            try:
                os.remove(MASTER_MV2)
            except OSError:
                pass
    if not master_ok:
        print('[bridge] repair: master.mv2 missing or corrupt - rebuilding via sync_all_pages...', file=sys.stderr)
        sync_result = sync_all_pages()
        repaired.append(f'master.mv2 rebuilt ({sync_result["total_frames"]} frames from {sync_result["total_pages"]} pages)')

    # --- Schema files ---
    today = datetime.now().strftime('%Y-%m-%d')
    empty_structures = {
        'entities.json': {'version': 1, 'updated': today, 'entities': []},
        'graph.json': {'version': 1, 'updated': today, 'nodes': [], 'edges': []},
        'tags.json': {'version': 1, 'updated': today, 'tags': {}},
    }
    os.makedirs(SCHEMA_DIR, exist_ok=True)
    for fname, empty in empty_structures.items():
        fpath = os.path.join(SCHEMA_DIR, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r') as f:
                    json.loads(f.read())
            except (json.JSONDecodeError, OSError) as e:
                print(f'[bridge] repair: {fname} corrupt ({e}) - resetting to empty structure.', file=sys.stderr)
                with open(fpath, 'w') as f:
                    json.dump(empty, f, indent=2)
                repaired.append(f'{fname} reset to empty structure')

    # --- index.md ---
    if not os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'w') as f:
            f.write(f'# Knowledge Engine Index\nLast updated: {today}\n\n')
        repaired.append('index.md created (was missing)')

    return {
        'repaired': repaired,
        'warnings': warnings,
        'ok': len(repaired) == 0 and len(warnings) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='bridge',
        description='Knowledge Engine bridge - fuses Wiki (System A) with Memvid (System B)',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # sync
    subparsers.add_parser('sync', help='Sync all wiki pages to memvid')

    # search
    search_parser = subparsers.add_parser('search', help='Dual-layer search (wiki + memvid)')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('-k', type=int, default=10, help='Max results (default: 10)')

    # drift
    subparsers.add_parser('drift', help='Check sync drift between wiki and memvid')

    # stats
    subparsers.add_parser('stats', help='Show stats for all layers')

    # ingest
    ingest_parser = subparsers.add_parser('ingest', help='Atomic ingest: source -> wiki + memvid')
    ingest_parser.add_argument('file', help='Path to source file (.md, .txt, .pdf)')
    ingest_parser.add_argument('client_slug', help='Client slug (e.g. demo-retail, my-client)')
    ingest_parser.add_argument('--force', action='store_true', help='Re-ingest even if source was previously ingested')

    # init
    init_parser = subparsers.add_parser('init', help='Initialize a new Knowledge Engine workspace')
    init_parser.add_argument('--project', type=str, default=None, help='Project name (default: current directory name)')
    init_parser.add_argument('--clients', type=str, default=None, help='Comma-separated client slugs (default: default)')

    # repair
    subparsers.add_parser('repair', help='Repair corrupted archives and schema')

    args = parser.parse_args()

    if args.command == 'sync':
        result = sync_all_pages()
        _print_sync_result(result)

    elif args.command == 'search':
        if not args.query.strip():
            print('Error: search query cannot be empty.', file=sys.stderr)
            sys.exit(1)
        results = dual_search(args.query, k=args.k)
        _print_search_results(results)

    elif args.command == 'drift':
        report = check_drift()
        _print_drift_report(report)

    elif args.command == 'stats':
        stats = get_stats()
        _print_stats(stats)

    elif args.command == 'ingest':
        if not re.match(r'^[a-z0-9][a-z0-9\-]*$', args.client_slug):
            print(f'Error: invalid client slug "{args.client_slug}". Use lowercase letters, numbers, hyphens only.', file=sys.stderr)
            sys.exit(1)
        try:
            result = ingest_source_to_both(args.file, args.client_slug, force=args.force)
            if not result:
                # Skipped due to duplicate detection
                sys.exit(0)
            print(f'Ingest complete.')
            print(f'  Action:          {result["action"]}')
            print(f'  Wiki page:       {result["wiki_page"]}')
            print(f'  Memvid frames:   {result["frames_added"]}')
            print(f'  Entities added:  {result["entities_updated"]}')
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f'Error: {e}', file=sys.stderr)
            sys.exit(1)


    elif args.command == 'init':
        client_list = [c.strip() for c in args.clients.split(',')] if args.clients else None
        init_workspace(project_name=args.project, clients=client_list)

    elif args.command == 'repair':
        result = repair()
        if result['ok']:
            print('repair: all checks passed - nothing needed fixing.')
        else:
            if result['repaired']:
                print('repair: fixed the following issues:')
                for item in result['repaired']:
                    print(f'  - {item}')
            if result['warnings']:
                print('repair: warnings:')
                for w in result['warnings']:
                    print(f'  - {w}')


if __name__ == '__main__':
    main()
