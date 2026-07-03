"""
URUK custom tool: search_arxiv
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='search_arxiv',
    description='Search arXiv for academic papers by keyword. Returns titles, authors, abstracts, and PDF links. No API key required.',
    args=[
        ArgSpec('query', 'str', True,
                description='Search query string.'),
        ArgSpec('max_results', 'int', False, default=5,
                description='Maximum papers to return, default 5.'),
        ArgSpec('category', 'str', False, default=None,
                description='Optional arXiv category filter e.g. "cs.AI", "physics", "q-bio".'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save paper abstracts as markdown to data/external/.'),
    ],
    needs_visual=False,
    category='file',
)

_ATOM_NS = 'http://www.w3.org/2005/Atom'
_ARXIV_NS = 'http://arxiv.org/schemas/atom'
_EXTERNAL_DIR = None


def _get_external_dir():
    global _EXTERNAL_DIR
    if _EXTERNAL_DIR is None:
        import os
        _EXTERNAL_DIR = os.path.join(
            os.path.dirname(__file__), '..', '..', 'data', 'external'
        )
        os.makedirs(_EXTERNAL_DIR, exist_ok=True)
    return _EXTERNAL_DIR


def _slug(text, max_len=50):
    import re
    s = re.sub(r'[^\w\s-]', '', str(text or '').lower())
    s = re.sub(r'[\s_-]+', '_', s).strip('_')
    return s[:max_len] or 'paper'


def _trigger_rag_reindex():
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
        from services.rag_indexer import build_index
        build_index()
        return True
    except Exception:
        return False


def execute(args: dict) -> dict:
    try:
        import os
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET
        args = args or {}

        query = str(args.get('query') or '').strip()
        if not query:
            return {'ok': False, 'error': 'missing_query'}

        max_results = max(1, min(50, int(args.get('max_results') or 5)))
        category = str(args.get('category') or '').strip()
        do_save = bool(args.get('save', False))

        search_q = f'all:{urllib.parse.quote(query)}'
        if category:
            search_q = f'cat:{urllib.parse.quote(category)}+AND+{search_q}'

        api_url = (
            f'https://export.arxiv.org/api/query'
            f'?search_query={search_q}'
            f'&max_results={max_results}'
            f'&sortBy=relevance&sortOrder=descending'
        )

        import ssl
        try:
            import certifi as _certifi
            _ssl_ctx = ssl.create_default_context(cafile=_certifi.where())
        except ImportError:
            _ssl_ctx = ssl.create_default_context()
        req = urllib.request.Request(api_url, headers={'User-Agent': 'URUK/1.0'})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            raw = resp.read()

        root = ET.fromstring(raw)
        ns = {'a': _ATOM_NS, 'arxiv': _ARXIV_NS}

        total_el = root.find('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
        total = int(total_el.text or 0) if total_el is not None else 0

        papers = []
        for entry in root.findall(f'{{{_ATOM_NS}}}entry'):
            def _t(tag, ns_uri=_ATOM_NS):
                el = entry.find(f'{{{ns_uri}}}{tag}')
                return (el.text or '').strip() if el is not None else ''

            arxiv_id = _t('id').split('/abs/')[-1]
            title = ' '.join(_t('title').split())
            abstract = ' '.join(_t('summary').split())
            published = _t('published')[:10]

            authors = [
                (a.find(f'{{{_ATOM_NS}}}name').text or '').strip()
                for a in entry.findall(f'{{{_ATOM_NS}}}author')
                if a.find(f'{{{_ATOM_NS}}}name') is not None
            ]

            pdf_url = ''
            for link in entry.findall(f'{{{_ATOM_NS}}}link'):
                if link.get('type') == 'application/pdf' or link.get('title') == 'pdf':
                    pdf_url = link.get('href', '')
                    break
            if not pdf_url and arxiv_id:
                pdf_url = f'https://arxiv.org/pdf/{arxiv_id}'

            papers.append({
                'id': arxiv_id,
                'title': title,
                'authors': authors,
                'abstract': abstract,
                'published': published,
                'pdf_url': pdf_url,
            })

        saved_count = 0
        if do_save:
            ext_dir = _get_external_dir()
            for p in papers:
                slug = _slug(p['title'])
                fname = f'arxiv_{slug}.md'
                fpath = os.path.join(ext_dir, fname)
                authors_str = ', '.join(p['authors'][:5])
                md = (
                    f'---\nsource: arxiv\nid: {p["id"]}\n'
                    f'published: {p["published"]}\nauthors: {authors_str}\n'
                    f'pdf_url: {p["pdf_url"]}\n---\n\n'
                    f'# {p["title"]}\n\n'
                    f'**Authors:** {authors_str}\n\n'
                    f'## Abstract\n\n{p["abstract"]}\n'
                )
                with open(fpath, 'w', encoding='utf-8') as fh:
                    fh.write(md)
                saved_count += 1
            if saved_count:
                _trigger_rag_reindex()

        return {
            'ok': True,
            'query': query,
            'total_results': total,
            'papers': papers,
            'saved_count': saved_count,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
