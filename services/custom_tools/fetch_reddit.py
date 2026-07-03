"""
URUK custom tool: fetch_reddit
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='fetch_reddit',
    description='Fetch posts and top comments from a Reddit subreddit or thread. No API key required (uses public JSON API).',
    args=[
        ArgSpec('source', 'str', True,
                description='Subreddit name (e.g. "MachineLearning") or full Reddit post URL.'),
        ArgSpec('sort', 'str', False, default='hot',
                description='Sort order: "hot", "new", or "top". Default "hot".'),
        ArgSpec('max_posts', 'int', False, default=10,
                description='Maximum posts to return, default 10.'),
        ArgSpec('include_comments', 'bool', False, default=False,
                description='If true, fetch top 5 comments for each post.'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save posts as markdown to data/external/.'),
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


def _reddit_get(url):
    import urllib.request
    import json
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 URUK-Research/1.0'},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


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
        args = args or {}

        source = str(args.get('source') or '').strip()
        if not source:
            return {'ok': False, 'error': 'missing_source'}

        sort = str(args.get('sort') or 'hot').strip().lower()
        if sort not in ('hot', 'new', 'top'):
            sort = 'hot'
        max_posts = max(1, min(100, int(args.get('max_posts') or 10)))
        include_comments = bool(args.get('include_comments', False))
        do_save = bool(args.get('save', False))

        is_url = source.startswith('http')
        if is_url:
            json_url = source.rstrip('/') + '.json?limit=' + str(max_posts)
        else:
            sub = source.lstrip('r/').strip('/')
            json_url = f'https://www.reddit.com/r/{sub}/{sort}.json?limit={max_posts}'

        data = _reddit_get(json_url)

        # Handle both listing and post+comments structures
        if isinstance(data, list):
            listing = data[0]
        else:
            listing = data

        children = listing.get('data', {}).get('children', [])
        posts = []

        for child in children[:max_posts]:
            d = child.get('data', {})
            post = {
                'title':          d.get('title', ''),
                'url':            d.get('url', ''),
                'permalink':      'https://www.reddit.com' + d.get('permalink', ''),
                'score':          d.get('score', 0),
                'comments_count': d.get('num_comments', 0),
                'author':         d.get('author', ''),
                'text_preview':   (d.get('selftext') or '')[:500],
                'comments':       [],
            }

            if include_comments and d.get('permalink'):
                try:
                    comment_url = 'https://www.reddit.com' + d['permalink'] + '.json?limit=5'
                    cdata = _reddit_get(comment_url)
                    if isinstance(cdata, list) and len(cdata) > 1:
                        for cc in cdata[1].get('data', {}).get('children', [])[:5]:
                            cd = cc.get('data', {})
                            body = cd.get('body', '')
                            if body and body != '[deleted]':
                                post['comments'].append({
                                    'author': cd.get('author', ''),
                                    'score':  cd.get('score', 0),
                                    'body':   body[:500],
                                })
                except Exception:
                    pass

            posts.append(post)

        saved_count = 0
        if do_save:
            ext_dir = _get_external_dir()
            import re
            label = re.sub(r'[^\w]', '_', source)[:30]
            fname = f'reddit_{label}_{sort}.md'
            fpath = os.path.join(ext_dir, fname)
            lines = [f'---\nsource: reddit\nquery: {source}\nsort: {sort}\n---\n']
            for p in posts:
                lines.append(f'## {p["title"]}\n')
                lines.append(f'**Score:** {p["score"]}  **Comments:** {p["comments_count"]}  **Author:** {p["author"]}\n')
                lines.append(f'**URL:** {p["url"]}\n')
                if p['text_preview']:
                    lines.append(f'\n{p["text_preview"]}\n')
                for c in p.get('comments', []):
                    lines.append(f'\n> **{c["author"]}** ({c["score"]}): {c["body"]}\n')
                lines.append('\n---\n')
            with open(fpath, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines))
            saved_count = 1
            _trigger_rag_reindex()

        # Strip comments from return if not requested (keep payload small)
        for p in posts:
            if not include_comments:
                del p['comments']

        return {
            'ok': True,
            'source': source,
            'posts': posts,
            'saved_count': saved_count,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
