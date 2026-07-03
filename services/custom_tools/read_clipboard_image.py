"""
URUK custom tool: read_clipboard_image (觸覺/感知 — perception)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='read_clipboard_image',
    description='Read an image or text from the clipboard. Saves image to file and optionally runs OCR on it.',
    args=[
        ArgSpec('save_path', 'str', False, default=None,
                description='Optional path to save the clipboard image as PNG.'),
        ArgSpec('return_text', 'bool', False, default=False,
                description='If true and clipboard has an image, run OCR and include text in result.'),
    ],
    needs_visual=False,
    category='clipboard',
)


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        import time
        args = args or {}
        save_path = args.get('save_path') or None
        return_text = bool(args.get('return_text', False))

        if save_path:
            save_path = os.path.abspath(os.path.expanduser(str(save_path)))

        try:
            from PIL import ImageGrab, Image
        except ImportError:
            return {'ok': False, 'error': 'pillow_not_installed', 'install_hint': 'pip install Pillow'}

        img = ImageGrab.grabclipboard()

        if img is None:
            # Try reading text via tkinter
            text = None
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                try:
                    text = root.clipboard_get()
                except Exception:
                    pass
                root.destroy()
            except Exception:
                pass
            if text:
                return {'ok': True, 'has_image': False, 'has_text': True, 'text': text}
            return {'ok': True, 'has_image': False, 'has_text': False, 'text': None}

        if isinstance(img, list):
            # File paths from clipboard
            return {'ok': True, 'has_image': False, 'has_text': False,
                    'files': [str(f) for f in img]}

        if not isinstance(img, Image.Image):
            return {'ok': True, 'has_image': False, 'has_text': False}

        if not save_path:
            ts = int(time.time())
            save_path = os.path.join(tempfile.gettempdir(), f'uruk_clipboard_{ts}.png')

        img.save(save_path, 'PNG')
        result = {
            'ok': True,
            'has_image': True,
            'path': save_path,
            'width': img.width,
            'height': img.height,
        }

        if return_text:
            try:
                import pytesseract
                text = pytesseract.image_to_string(img)
                result['text'] = text
                result['word_count'] = len(text.split()) if text.strip() else 0
            except ImportError:
                result['ocr_error'] = 'pytesseract_not_installed'
            except Exception as exc:
                result['ocr_error'] = str(exc)

        return result
    except Exception as e:
        return {'ok': False, 'error': str(e)}
