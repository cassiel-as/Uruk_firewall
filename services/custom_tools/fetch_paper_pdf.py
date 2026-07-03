"""
URUK custom tool: fetch_paper_pdf
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='fetch_paper_pdf',
    description='Download and extract text from a PDF (academic paper or any document). Prioritizes abstract, introduction, and conclusion sections.',
    args=[
        ArgSpec('url_or_path', 'str', True,
                description='URL or local file path to the PDF.'),
        ArgSpec('save', 'bool', False, default=False,
                description='If true, save extracted text as markdown to data/external/.'),
        ArgSpec('tag', 'str', False, default=None,
                description='Optional label used in the saved filename.'),
        ArgSpec('sections_only', 'bool', False, default=True,
                description='If true, extract abstract/introduction/conclusion first. Default true.'),
    ],
    needs_visual=False,
    category='file',
)

_MAX_CHARS = 100_000
_SECTION_HEADERS = [
    r'abstract', r'introduction', r'conclusion', r'summary',
    r'related work', r'background', r'discussion',
]
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
    return s[:max_len] or 'pdf'


def _trigger_rag_reindex():
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
        from services.rag_indexer import build_index
        build_index()
        return True
    except Exception:
        return False


def _extract_sections(text):
    """Return dict of section_name -> content for key sections."""
    import re
    header_pat = re.compile(
        r'^(?:\d+\.?\s*)?(' + '|'.join(_SECTION_HEADERS) + r')[\s\S]*?(?=\n(?:\d+\.?\s*)?(?:'
        + '|'.join(_SECTION_HEADERS) + r')|\Z)',
        re.I | re.M,
    )
    found = {}
    for m in header_pat.finditer(text):
        key = m.group(1).lower()
        if key not in found:
            found[key] = m.group(0).strip()
    return found


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        args = args or {}

        src = str(args.get('url_or_path') or '').strip()
        if not src:
            return {'ok': False, 'error': 'missing_url_or_path'}

        do_save = bool(args.get('save', False))
        tag = str(args.get('tag') or '').strip() or 'pdf'
        sections_only = bool(args.get('sections_only', True))

        # Download if URL
        local_path = None
        if src.startswith('http://') or src.startswith('https://'):
            import urllib.request, ssl
            try:
                import certifi as _certifi
                _ssl_ctx = ssl.create_default_context(cafile=_certifi.where())
            except ImportError:
                _ssl_ctx = ssl.create_default_context()
            tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            tmp.close()
            local_path = tmp.name
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=_ssl_ctx)
            )
            with opener.open(src, timeout=60) as resp, open(local_path, 'wb') as fh:
                fh.write(resp.read())
        else:
            local_path = os.path.abspath(os.path.expanduser(src))
            if not os.path.isfile(local_path):
                return {'ok': False, 'error': 'file_not_found', 'path': local_path}

        full_text = ''
        pages = 0

        # Try pymupdf (fitz) first
        try:
            import fitz
            doc = fitz.open(local_path)
            pages = doc.page_count
            parts = []
            for page in doc:
                parts.append(page.get_text())
            doc.close()
            full_text = '\n'.join(parts)
        except ImportError:
            # Fallback: pypdf
            try:
                from pypdf import PdfReader
                reader = PdfReader(local_path)
                pages = len(reader.pages)
                parts = []
                for page in reader.pages:
                    t = page.extract_text() or ''
                    parts.append(t)
                full_text = '\n'.join(parts)
            except ImportError:
                return {
                    'ok': False,
                    'error': 'pdf_lib_missing',
                    'install_hint': 'pip install pymupdf  OR  pip install pypdf',
                }

        sections_extracted = {}
        if sections_only:
            sections_extracted = _extract_sections(full_text)
            if sections_extracted:
                text = '\n\n'.join(
                    f'## {k.title()}\n\n{v}' for k, v in sections_extracted.items()
                )
            else:
                text = full_text
        else:
            text = full_text

        text = text[:_MAX_CHARS]

        saved_path = None
        if do_save:
            ext_dir = _get_external_dir()
            slug = _slug(os.path.basename(src))
            fname = f'pdf_{tag}_{slug}.md'
            saved_path = os.path.join(ext_dir, fname)
            md = f'---\nsource: pdf\norigin: {src}\npages: {pages}\n---\n\n{text}\n'
            with open(saved_path, 'w', encoding='utf-8') as fh:
                fh.write(md)
            _trigger_rag_reindex()

        return {
            'ok': True,
            'source': src,
            'pages': pages,
            'text': text,
            'sections_extracted': list(sections_extracted.keys()),
            'saved_path': saved_path,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
