"""
URUK custom tool: speak_text (語言輸出 — speech output)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='speak_text',
    description='Convert text to speech. Primary: edge-tts (neural, multilingual, saves .mp3). Fallback: pyttsx3 → Windows SAPI. Supports Cantonese, Mandarin, English.',
    args=[
        ArgSpec('text', 'str', True,
                description='Text to speak aloud.'),
        ArgSpec('lang', 'str', False, default='auto',
                description='Language/voice: "auto" (detect), "yue" (Cantonese female), "yue-male" (Cantonese male), "zh" (Mandarin), "en" (English).'),
        ArgSpec('rate', 'int', False, default=150,
                description='Speech rate in words per minute for pyttsx3/SAPI fallback, default 150.'),
        ArgSpec('voice', 'str', False, default=None,
                description='pyttsx3/SAPI fallback voice selector: "male", "female", or numeric index string.'),
        ArgSpec('save_to_file', 'str', False, default=None,
                description='Optional file path to save audio output. Defaults to a temp file for edge-tts.'),
    ],
    needs_visual=False,
    category='misc',
)

# edge-tts voice map
_EDGE_VOICES = {
    'yue':      'zh-HK-HiuMaanNeural',
    'yue-male': 'zh-HK-WanLungNeural',
    'zh':       'zh-CN-XiaoxiaoNeural',
    'en':       'en-US-JennyNeural',
}


def _detect_lang_voice(text: str) -> tuple:
    """Return (lang_key, voice) by scanning for CJK characters."""
    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            return ('yue', _EDGE_VOICES['yue'])
    return ('en', _EDGE_VOICES['en'])


def _run_coroutine(coro):
    """Run an async coroutine safely from a sync context (handles existing event loop)."""
    import asyncio
    import threading

    result_box = [None]
    exc_box = [None]

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box[0] = loop.run_until_complete(coro)
        except Exception as e:
            exc_box[0] = e
        finally:
            loop.close()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=30)
    if exc_box[0]:
        raise exc_box[0]
    return result_box[0]


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        import time
        args = args or {}

        text = str(args.get('text') or '').strip()
        if not text:
            return {'ok': False, 'error': 'empty_text'}

        lang_arg = str(args.get('lang') or 'auto').strip().lower()
        rate = max(50, min(400, int(args.get('rate') or 150)))
        voice_arg = args.get('voice') or None
        save_to_file = args.get('save_to_file') or None
        if save_to_file:
            save_to_file = os.path.abspath(os.path.expanduser(str(save_to_file)))

        word_count = len(text.split())
        duration_estimate = round(word_count / max(1, rate / 60), 1)

        # ── Primary: edge-tts ──────────────────────────────────────
        try:
            import edge_tts

            if lang_arg == 'auto':
                lang_detected, voice = _detect_lang_voice(text)
            elif lang_arg in _EDGE_VOICES:
                lang_detected = lang_arg
                voice = _EDGE_VOICES[lang_arg]
            else:
                lang_detected = 'en'
                voice = _EDGE_VOICES['en']

            if save_to_file:
                out_path = save_to_file
            else:
                ts = int(time.time())
                out_path = os.path.join(tempfile.gettempdir(), f'uruk_tts_{ts}.mp3')

            async def _speak(t, v, p):
                communicate = edge_tts.Communicate(t, v)
                await communicate.save(p)

            _run_coroutine(_speak(text, voice, out_path))

            # Play the file
            try:
                os.startfile(out_path)
            except Exception:
                pass

            return {
                'ok': True,
                'method': 'edge-tts',
                'voice': voice,
                'lang_detected': lang_detected,
                'output_path': out_path,
            }
        except ImportError:
            pass

        # ── Fallback 1: pyttsx3 ────────────────────────────────────
        lang_detected = lang_arg if lang_arg != 'auto' else 'unknown'
        duration_estimate = round(word_count / max(1, rate / 60), 1)

        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', rate)
            voices = engine.getProperty('voices') or []

            if voice_arg is not None and voices:
                v = str(voice_arg).lower()
                if v == 'female':
                    picks = [x for x in voices if any(k in x.name.lower() for k in ('female', 'zira', 'hazel'))]
                    if picks:
                        engine.setProperty('voice', picks[0].id)
                elif v == 'male':
                    picks = [x for x in voices if any(k in x.name.lower() for k in ('male', 'david', 'mark'))]
                    if picks:
                        engine.setProperty('voice', picks[0].id)
                else:
                    try:
                        idx = int(v)
                        if 0 <= idx < len(voices):
                            engine.setProperty('voice', voices[idx].id)
                    except (ValueError, TypeError):
                        pass

            out_path = save_to_file or None
            if out_path:
                engine.save_to_file(text, out_path)
            else:
                engine.say(text)
            engine.runAndWait()
            return {
                'ok': True,
                'method': 'pyttsx3',
                'voice': None,
                'lang_detected': lang_detected,
                'output_path': out_path,
                'duration_estimate_seconds': duration_estimate,
            }
        except ImportError:
            pass

        # ── Fallback 2: Windows SAPI ───────────────────────────────
        try:
            import win32com.client
            speaker = win32com.client.Dispatch('SAPI.SpVoice')
            sapi_rate = max(-10, min(10, round((rate - 150) / 25)))
            speaker.Rate = sapi_rate
            speaker.Speak(text)
            return {
                'ok': True,
                'method': 'SAPI.SpVoice',
                'voice': None,
                'lang_detected': lang_detected,
                'output_path': None,
                'duration_estimate_seconds': duration_estimate,
            }
        except ImportError:
            pass

        return {
            'ok': False,
            'error': 'no_tts_backend',
            'install_hint': 'pip install edge-tts  OR  pip install pyttsx3  OR  pip install pywin32',
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
