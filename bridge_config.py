import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WIKI_DIR = os.path.join(BASE_DIR, 'wiki')
SOURCES_DIR = os.path.join(BASE_DIR, 'sources')
SCHEMA_DIR = os.path.join(BASE_DIR, 'schema')
MEMVID_DIR = os.path.join(BASE_DIR, 'memvid')
MASTER_MV2 = os.path.join(MEMVID_DIR, 'master.mv2')
PER_CLIENT_DIR = os.path.join(MEMVID_DIR, 'per-client')
INDEX_FILE = os.path.join(BASE_DIR, 'index.md')
LOG_FILE = os.path.join(BASE_DIR, 'log.md')
TEMPLATES_DIR = os.path.join(WIKI_DIR, '_templates')

# Excluded from sync
EXCLUDED_DIRS = ['_templates']
EXCLUDED_FILES = ['_meta.yaml']

# Chunk settings for memvid
MAX_CHUNK_SIZE = 500  # characters per Smart Frame
MIN_CHUNK_SIZE = 50   # don't create tiny frames

# Ingest limits to prevent hangs on huge files
MAX_CHUNKS_PER_INGEST = 200   # hard cap on chunks sent to memvid per page
CHUNK_COMMIT_BATCH = 50       # commit to memvid every N chunks (avoids one giant commit)

# Entity extraction stopwords - phrases excluded from entity detection during ingest
ENTITY_STOPWORDS = {
    'key facts', 'open questions', 'page title', 'page types', 'special files',
    'client directories', 'cross references', 'source summary', 'detail section',
    'wiki page', 'wiki pages', 'wiki protocol', 'knowledge engine', 'summary section',
    'how to', 'last updated', 'activity log', 'health report', 'action plan',
    'executive summary', 'final verdict', 'risk scorecard', 'prior art',
    'patent strategy', 'filing strategy', 'negotiation strategy',
    'competitive landscape', 'technology stack', 'bill of materials',
    'system architecture', 'operating principle', 'performance analysis',
    'technical specifications', 'environmental conditions', 'safety compliance',
    'target market', 'intended use', 'design rationale', 'component photographs',
    'novelty and inventive step', 'background and technical', 'thermal and electrical',
    'prefer anglo', 'total pages', 'recent activity',
}
