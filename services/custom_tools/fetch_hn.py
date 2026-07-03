"""
URUK custom tool: fetch_hn
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='fetch_hn',
    description='Fetch top stories and optionally comments from Hacker News. No API key required.',
    args=[
        ArgSpec('feed', 'str', False, default='topstories',
                description='Feed type: "topstories", "newstories", or "beststories". Default "topstories".'),
        ArgSpec('max_items', 'int', False, default=10,
                description='Maximum stories to return, default 10.'),
        ArgSpec('include_comments', 'bool', False, default=False,
                description='If true, fetch top 3 comments per story.'),
        ArgSpec('min_score', 'int', False, default=0,
                description='Minimum score filter. Default 0 (no filter).'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save stories as markdown to data/external/.'),
    ],
    needs_visual=False,
    category='file',
)

_HN_BASE = 'https://hacker-news.firebaseio.com/v0'
_VALID_FEEDS = {'topstories', 'newstories', 'beststories', 'askstories', 'showstories', 'jobstories'}
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


def _hn_get(path):
    import urllib.request
    import json
    req = urllib.request.Request(
        f'{_HN_BASE}/{path}',
        headers={'User-Agent': 'URUK-Research/1.0'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _fetch_item(item_id):
    try:
        return _hn_get(f'item/{item_id}.json')
    except Exception:
        return None


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
        import datetime
        import concurrent.futures
        args = args or {}

        feed = str(args.get('feed') or 'topstories').strip().lower()
        if feed not in _VALID_FEEDS:
            feed = 'topstories'
        max_items = max(1, min(100, int(args.get('max_items') or 10)))
        include_comments = bool(args.get('include_comments', False))
        min_score = int(args.get('min_score') or 0)
        do_save = bool(args.get('save', False))

        # Get story IDs
        story_ids = _hn_get(f'{feed}.json')
        if not isinstance(story_ids, list):
            return {'ok': False, 'error': 'unexpected_response'}

        # Fetch up to max_items * 2 to allow for min_score filtering
        fetch_count = min(max_items * 2, len(story_ids), 100)
        ids_to_fetch = story_ids[:fetch_count]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            raw_items = list(pool.map(_fetch_item, ids_to_fetch))

        items = []
        for item in raw_items:
            if not item or item.get('type') != 'story':
                continue
            score = item.get('score', 0) or 0
            if score < min_score:
                continue

            ts = item.get('time', 0)
            time_str = datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M UTC') if ts else ''

            story = {
                'id':             item.get('id'),
                'title':          item.get('title', ''),
                'url':            item.get('url', ''),
                'score':          score,
                'by':             item.get('by', ''),
                'time':           time_str,
                'comments_count': item.get('descendants', 0) or 0,
                'comments':       [],
            }

            if include_comments:
                kid_ids = (item.get('kids') or [])[:3]
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as cpool:
                    comments_raw = list(cpool.map(_fetch_item, kid_ids))
                for c in comments_raw:
                    if c and c.get('text') and not c.get('deleted'):
                        story['comments'].append({
                            'by':   c.get('by', ''),
                            'text': (c.get('text') or '')[:400],
                        })

            items.append(story)
            if len(items) >= max_items:
                break

        saved_count = 0
        if do_save:
            ext_dir = _get_external_dir()
            fname = f'hn_{feed}.md'
            fpath = os.path.join(ext_dir, fname)
            lines = [f'---\nsource: hackernews\nfeed: {feed}\n---\n']
            for s in items:
                lines.append(f'## {s["title"]}\n')
                lines.append(f'**Score:** {s["score"]}  **By:** {s["by"]}  **Time:** {s["time"]}  **Comments:** {s["comments_count"]}\n')
                if s['url']:
                    lines.append(f'**URL:** {s["url"]}\n')
                for c in s.get('comments', []):
                    lines.append(f'\n> **{c["by"]}**: {c["text"]}\n')
                lines.append('\n---\n')
            with open(fpath, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines))
            saved_count = 1
            _trigger_rag_reindex()

        # Strip comments from return payload if not requested
        for s in items:
            if not include_comments:
                del s['comments']

        return {
            'ok': True,
            'feed': feed,
            'items': items,
            'saved_count': saved_count,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
