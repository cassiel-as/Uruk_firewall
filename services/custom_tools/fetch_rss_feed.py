"""
URUK custom tool: fetch_rss_feed
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='fetch_rss_feed',
    description='Fetch and parse an RSS/Atom feed. Returns titles, summaries, and links. Optionally saves entries as markdown to data/external/.',
    args=[
        ArgSpec('url', 'str', True,
                description='URL of the RSS or Atom feed.'),
        ArgSpec('max_items', 'int', False, default=10,
                description='Maximum number of items to return, default 10.'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save each item as a markdown file in data/external/.'),
        ArgSpec('tag', 'str', False, default=None,
                description='Optional label used in saved filenames.'),
    ],
    needs_visual=False,
    category='file',
)

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


def _slug(text, max_len=40):
    import re
    s = re.sub(r'[^\w\s-]', '', str(text or '').lower())
    s = re.sub(r'[\s_-]+', '_', s).strip('_')
    return s[:max_len] or 'item'


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
        import xml.etree.ElementTree as ET
        args = args or {}

        url = str(args.get('url') or '').strip()
        if not url:
            return {'ok': False, 'error': 'missing_url'}

        max_items = max(1, min(100, int(args.get('max_items') or 10)))
        do_save = bool(args.get('save', False))
        tag = str(args.get('tag') or '').strip() or 'feed'

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 URUK/1.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()

        root = ET.fromstring(raw)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        # Detect feed format
        is_atom = 'Atom' in root.tag or root.tag.endswith('}feed') or root.tag == 'feed'

        items = []
        feed_title = ''

        if is_atom:
            t_el = root.find('atom:title', ns) or root.find('title')
            feed_title = t_el.text or '' if t_el is not None else ''
            entries = root.findall('atom:entry', ns) or root.findall('entry')
            for entry in entries[:max_items]:
                def _text(tag):
                    el = entry.find(f'atom:{tag}', ns) or entry.find(tag)
                    return (el.text or '').strip() if el is not None else ''
                link_el = entry.find('atom:link', ns) or entry.find('link')
                link = (link_el.get('href') or link_el.text or '').strip() if link_el is not None else ''
                items.append({
                    'title':   _text('title'),
                    'link':    link,
                    'summary': _text('summary') or _text('content'),
                    'date':    _text('updated') or _text('published'),
                })
        else:
            # RSS 2.0
            channel = root.find('channel') or root
            t_el = channel.find('title')
            feed_title = t_el.text or '' if t_el is not None else ''
            for item in channel.findall('item')[:max_items]:
                def _text(tag):
                    el = item.find(tag)
                    return (el.text or '').strip() if el is not None else ''
                items.append({
                    'title':   _text('title'),
                    'link':    _text('link'),
                    'summary': _text('description'),
                    'date':    _text('pubDate'),
                })

        saved_count = 0
        if do_save:
            ext_dir = _get_external_dir()
            for i, item in enumerate(items):
                slug = _slug(item.get('title', str(i)))
                fname = f'rss_{tag}_{slug}.md'
                fpath = os.path.join(ext_dir, fname)
                md = (
                    f'---\nsource: rss\nfeed: {feed_title}\n'
                    f'url: {item.get("link","")}\ndate: {item.get("date","")}\n---\n\n'
                    f'# {item.get("title","")}\n\n{item.get("summary","")}\n'
                )
                with open(fpath, 'w', encoding='utf-8') as fh:
                    fh.write(md)
                saved_count += 1
            if saved_count:
                _trigger_rag_reindex()

        return {
            'ok': True,
            'feed_title': feed_title,
            'items': items,
            'saved_count': saved_count,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
