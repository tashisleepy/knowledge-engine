"""
server.py - Knowledge Engine local web UI server.

Usage:
    cd knowledge-engine && python3 server.py

Runs on http://localhost:3141
"""

import json
import os
import sys
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

# Ensure the knowledge-engine directory is on the path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from bridge_config import (
    WIKI_DIR,
    SCHEMA_DIR,
    LOG_FILE,
    INDEX_FILE,
)

# Lazy import bridge so memvid errors don't kill startup
try:
    from bridge import (
        get_stats,
        dual_search,
        check_drift,
        parse_frontmatter,
        sync_all_pages,
    )
    BRIDGE_OK = True
except Exception as e:
    BRIDGE_OK = False
    BRIDGE_ERROR = str(e)


UI_FILE = os.path.join(BASE_DIR, 'ui.html')
PORT = 3141


def _json_response(data):
    return json.dumps(data, default=str).encode('utf-8')


def _error(msg, code=500):
    return code, _json_response({'error': msg})


def handle_stats():
    if not BRIDGE_OK:
        return 500, _json_response({'error': BRIDGE_ERROR})
    try:
        data = get_stats()
        return 200, _json_response(data)
    except Exception as e:
        return 500, _json_response({'error': str(e), 'trace': traceback.format_exc()})


def handle_search(query: str):
    if not BRIDGE_OK:
        return 500, _json_response({'error': BRIDGE_ERROR})
    if not query.strip():
        return 400, _json_response({'error': 'Empty query'})
    try:
        t0 = time.time()
        results = dual_search(query)
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        return 200, _json_response({'results': results, 'count': len(results), 'query': query, 'elapsed_ms': elapsed_ms})
    except Exception as e:
        return 500, _json_response({'error': str(e), 'trace': traceback.format_exc()})


def handle_drift():
    if not BRIDGE_OK:
        return 500, _json_response({'error': BRIDGE_ERROR})
    try:
        data = check_drift()
        return 200, _json_response(data)
    except Exception as e:
        return 500, _json_response({'error': str(e), 'trace': traceback.format_exc()})


def handle_wiki_list():
    """Return a nested structure: {client: [page_slug, ...]}"""
    import glob
    from pathlib import Path
    try:
        pattern = os.path.join(WIKI_DIR, '**', '*.md')
        all_pages = glob.glob(pattern, recursive=True)
        tree = {}
        for page in sorted(all_pages):
            rel = os.path.relpath(page, WIKI_DIR)
            parts = Path(rel).parts
            # Skip _templates
            if any(p.startswith('_templates') for p in parts):
                continue
            client = parts[0] if len(parts) > 1 else '_root'
            slug = os.path.splitext(rel)[0]  # path without .md
            if client not in tree:
                tree[client] = []
            # Get title from frontmatter if possible
            title = slug.split('/')[-1]
            try:
                with open(page, 'r', encoding='utf-8') as f:
                    content = f.read()
                if BRIDGE_OK:
                    fm, _ = parse_frontmatter(content)
                    title = fm.get('title', title)
            except Exception:
                pass
            tree[client].append({'slug': slug, 'title': title})
        return 200, _json_response({'tree': tree})
    except Exception as e:
        return 500, _json_response({'error': str(e)})


def handle_wiki_page(path_suffix: str):
    """
    Read a specific wiki page. path_suffix is like 'demo-retail/sample-proposal'
    (no .md extension - we add it).
    """
    # Sanitize input. The old `.replace('..', '')` is bypassable (e.g. '....//' → '..//'),
    # so rely on realpath containment instead: any candidate we open MUST resolve inside
    # WIKI_DIR or BASE_DIR. This defeats both literal '../' and symlink escapes.
    clean = path_suffix.lstrip('/')
    if not clean:
        return 400, _json_response({'error': 'No path given'})

    wiki_real = os.path.realpath(WIKI_DIR)
    base_real = os.path.realpath(BASE_DIR)

    def _resolve_within_allowed_root(abs_path: str):
        """Resolve abs_path and return it only if it stays inside an allowed root.
        Returns None on containment failure, NUL-byte inputs, or any realpath error.
        We resolve BEFORE touching the filesystem (isfile/stat) so a malicious
        symlink or automount target can't trigger filesystem side effects."""
        try:
            real = os.path.realpath(abs_path)
        except (ValueError, OSError):
            return None
        for root in (wiki_real, base_real):
            try:
                if os.path.commonpath([real, root]) == root:
                    return real
            except ValueError:
                # commonpath raises on different drives (Windows) or NUL in path
                continue
        return None

    # Try with and without .md extension
    candidates = [
        os.path.join(WIKI_DIR, clean),
        os.path.join(WIKI_DIR, clean + '.md'),
        os.path.join(BASE_DIR, clean),
        os.path.join(BASE_DIR, clean + '.md'),
    ]
    page_path = None
    for c in candidates:
        # Order: resolve → contain → filesystem check → extension check.
        # isfile() before containment would let a malicious path trigger
        # filesystem access (automount, network share probe).
        real = _resolve_within_allowed_root(c)
        if real is None:
            continue
        if real.endswith('.md') and os.path.isfile(real):
            page_path = real
            break

    if not page_path:
        return 404, _json_response({'error': f'Page not found: {clean}'})

    try:
        with open(page_path, 'r', encoding='utf-8') as f:
            content = f.read()
        frontmatter = {}
        body = content
        if BRIDGE_OK:
            frontmatter, body = parse_frontmatter(content)
        return 200, _json_response({
            'path': clean,
            'frontmatter': frontmatter,
            'body': body,
            'raw': content,
        })
    except Exception as e:
        return 500, _json_response({'error': str(e)})


def handle_entities():
    path = os.path.join(SCHEMA_DIR, 'entities.json')
    if not os.path.exists(path):
        return 404, _json_response({'error': 'entities.json not found'})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return 200, _json_response(data)
    except Exception as e:
        return 500, _json_response({'error': str(e)})


def handle_tags():
    path = os.path.join(SCHEMA_DIR, 'tags.json')
    if not os.path.exists(path):
        return 404, _json_response({'error': 'tags.json not found'})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return 200, _json_response(data)
    except Exception as e:
        return 500, _json_response({'error': str(e)})


def handle_log():
    if not os.path.exists(LOG_FILE):
        return 404, _json_response({'error': 'log.md not found'})
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        return 200, _json_response({'content': content})
    except Exception as e:
        return 500, _json_response({'error': str(e)})


def handle_sync():
    if not BRIDGE_OK:
        return 500, _json_response({'error': BRIDGE_ERROR})
    try:
        result = sync_all_pages()
        return 200, _json_response(result)
    except Exception as e:
        return 500, _json_response({'error': str(e), 'trace': traceback.format_exc()})


class KnowledgeEngineHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Custom minimal logging
        print(f'  {self.command} {self.path} -> {args[1] if len(args) > 1 else "?"}')

    def _send(self, code: int, body: bytes, content_type: str = 'application/json'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # Serve UI
        if path == '/' or path == '/index.html':
            if os.path.exists(UI_FILE):
                with open(UI_FILE, 'rb') as f:
                    body = f.read()
                self._send(200, body, 'text/html; charset=utf-8')
            else:
                self._send(404, b'<h1>ui.html not found</h1>', 'text/html')
            return

        # API routing
        if path == '/api/stats':
            code, body = handle_stats()
            self._send(code, body)

        elif path == '/api/search':
            query = qs.get('q', [''])[0]
            code, body = handle_search(query)
            self._send(code, body)

        elif path == '/api/drift':
            code, body = handle_drift()
            self._send(code, body)

        elif path == '/api/wiki':
            code, body = handle_wiki_list()
            self._send(code, body)

        elif path.startswith('/api/wiki/'):
            suffix = unquote(path[len('/api/wiki/'):])
            code, body = handle_wiki_page(suffix)
            self._send(code, body)

        elif path == '/api/entities':
            code, body = handle_entities()
            self._send(code, body)

        elif path == '/api/tags':
            code, body = handle_tags()
            self._send(code, body)

        elif path == '/api/log':
            code, body = handle_log()
            self._send(code, body)

        # Static JSON files at root (for UI tabs that fetch them directly)
        elif path in ('/monthly-summary.json', '/tools-registry.json'):
            filename = path.lstrip('/')
            filepath = os.path.join(BASE_DIR, filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    body = f.read()
                self._send(200, body, 'application/json; charset=utf-8')
            else:
                self._send(404, _json_response({'error': f'File not found: {filename}'}))

        else:
            self._send(404, _json_response({'error': f'Unknown endpoint: {path}'}))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/sync':
            code, body = handle_sync()
            self._send(code, body)
        else:
            self._send(404, _json_response({'error': f'Unknown endpoint: {path}'}))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


def main():
    server = HTTPServer(('localhost', PORT), KnowledgeEngineHandler)
    print(f'Knowledge Engine UI running at http://localhost:{PORT}')
    print('Press Ctrl+C to stop')
    if not BRIDGE_OK:
        print(f'[WARNING] bridge import failed: {BRIDGE_ERROR}')
        print('[WARNING] Some API endpoints will return errors. Memvid features disabled.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
        server.server_close()


if __name__ == '__main__':
    main()
