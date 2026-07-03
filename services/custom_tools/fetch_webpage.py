"""
URUK custom tool: fetch_webpage
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='fetch_webpage',
    description='Fetch and extract main text content from a webpage. Strips navigation, ads, and boilerplate.',
    args=[
        ArgSpec('url', 'str', True,
                description='URL of the webpage to fetch.'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save extracted text as markdown to data/external/.'),
        ArgSpec('tag', 'str', False, default=None,
                description='Optional label used in the saved filename.'),
    ],
    needs_visual=False,
    category='file',
)

_STRIP_TAGS = {'script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript'}
_MAX_CHARS = 50_000

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
    return s[:max_len] or 'page'


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
        args = args or {}

        url = str(args.get('url') or '').strip()
        if not url:
            return {'ok': False, 'error': 'missing_url'}

        do_save = bool(args.get('save', False))
        tag = str(args.get('tag') or '').strip() or 'web'

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) URUK/1.0'},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode('utf-8', errors='replace')

        title = ''
        text = ''

        # Try BeautifulSoup first
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, 'html.parser')
            t_el = soup.find('title')
            title = t_el.get_text(strip=True) if t_el else ''
            for tag_name in _STRIP_TAGS:
                for el in soup.find_all(tag_name):
                    el.decompose()
            body = soup.find('main') or soup.find('article') or soup.find('body') or soup
            text = body.get_text(separator='\n', strip=True)
        except ImportError:
            # Fallback: regex strip
            import re
            t_match = re.search(r'<title[^>]*>(.*?)</title>', raw, re.I | re.S)
            title = t_match.group(1).strip() if t_match else ''
            # Remove script/style blocks
            clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.I | re.S)
            # Strip remaining tags
            clean = re.sub(r'<[^>]+>', ' ', clean)
            # Collapse whitespace
            text = re.sub(r'\s{3,}', '\n\n', clean).strip()

        text = text[:_MAX_CHARS]

        saved_path = None
        if do_save:
            ext_dir = _get_external_dir()
            slug = _slug(title or url)
            fname = f'web_{tag}_{slug}.md'
            saved_path = os.path.join(ext_dir, fname)
            md = f'---\nsource: webpage\nurl: {url}\ntitle: {title}\n---\n\n# {title}\n\n{text}\n'
            with open(saved_path, 'w', encoding='utf-8') as fh:
                fh.write(md)
            _trigger_rag_reindex()

        return {
            'ok': True,
            'url': url,
            'title': title,
            'text': text,
            'char_count': len(text),
            'saved_path': saved_path,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
