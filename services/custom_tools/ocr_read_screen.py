"""
URUK custom tool: ocr_read_screen (視覺+讀取 — vision + read)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='ocr_read_screen',
    description='OCR text from a screen region or image file using pytesseract + PIL. Returns extracted text, confidence, and word count.',
    args=[
        ArgSpec('source', 'str', False, default='screen',
                description='"screen" to capture current screen, or a file path to an image.'),
        ArgSpec('region', 'str', False, default=None,
                description='Optional screen region "x,y,w,h". Only used when source="screen".'),
        ArgSpec('lang', 'str', False, default='chi_tra+eng',
                description='Tesseract language string, e.g. "chi_tra+eng" or "eng".'),
    ],
    needs_visual=False,
    category='screen',
)


def execute(args: dict) -> dict:
    try:
        import os
        args = args or {}
        source = str(args.get('source') or 'screen').strip()
        region_arg = args.get('region') or None
        lang = str(args.get('lang') or 'chi_tra+eng').strip()

        try:
            import pytesseract
        except ImportError:
            return {
                'ok': False,
                'error': 'tesseract_not_installed',
                'install_hint': (
                    'pip install pytesseract  AND  '
                    'install Tesseract-OCR from https://github.com/UB-Mannheim/tesseract/wiki'
                ),
            }

        try:
            from PIL import Image, ImageGrab
        except ImportError:
            return {'ok': False, 'error': 'pillow_not_installed', 'install_hint': 'pip install Pillow'}

        def parse_region(s):
            if not s:
                return None
            parts = [x.strip() for x in str(s).split(',')]
            if len(parts) == 4:
                return tuple(int(p) for p in parts)
            return None

        if source == 'screen':
            region = parse_region(region_arg)
            if region:
                x, y, w, h = region
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            else:
                img = ImageGrab.grab()
        else:
            path = os.path.abspath(os.path.expanduser(source))
            if not os.path.isfile(path):
                return {'ok': False, 'error': 'file_not_found', 'path': path}
            img = Image.open(path)

        text = pytesseract.image_to_string(img, lang=lang)
        word_count = len(text.split()) if text.strip() else 0

        confidence = None
        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            confs = [c for c in data.get('conf', []) if isinstance(c, (int, float)) and c >= 0]
            if confs:
                confidence = round(sum(confs) / len(confs), 1)
        except Exception:
            pass

        return {'ok': True, 'text': text, 'confidence': confidence, 'word_count': word_count}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
