"""
URUK custom tool: transcribe_audio (聽覺+理解 — speech to text)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='transcribe_audio',
    description='Transcribe audio file or record + transcribe using Whisper. Supports Cantonese (yue), Mandarin (zh), English (en) and auto-detection.',
    args=[
        ArgSpec('source', 'str', True,
                description='Path to an existing audio file, or "record" to record from microphone first then transcribe.'),
        ArgSpec('duration_seconds', 'int', False, default=5,
                description='Recording duration in seconds (1–60). Only used when source="record".'),
        ArgSpec('lang', 'str', False, default='auto',
                description='Transcription language: "yue" (Cantonese), "zh" (Mandarin), "en" (English), "auto" (Whisper auto-detect).'),
        ArgSpec('model_size', 'str', False, default='base',
                description='Whisper model size: "tiny", "base", "small", "medium". Larger = more accurate, slower.'),
    ],
    needs_visual=False,
    category='misc',
)

# Module-level model cache to avoid reloading on every call
_WHISPER_MODELS: dict = {}

# Whisper language codes
_LANG_MAP = {
    'yue':  'yue',
    'zh':   'zh',
    'en':   'en',
    'auto': None,
}

_VALID_SIZES = ('tiny', 'base', 'small', 'medium', 'large')


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        import time
        args = args or {}

        source = str(args.get('source') or '').strip()
        if not source:
            return {'ok': False, 'error': 'missing_source',
                    'hint': 'Provide a file path or "record"'}

        duration = max(1, min(60, int(args.get('duration_seconds') or 5)))
        lang_arg = str(args.get('lang') or 'auto').strip().lower()
        model_size = str(args.get('model_size') or 'base').strip().lower()

        if model_size not in _VALID_SIZES:
            model_size = 'base'
        if lang_arg not in _LANG_MAP:
            lang_arg = 'auto'

        # ── Check whisper availability ────────────────────────────
        try:
            import whisper
        except ImportError:
            return {
                'ok': False,
                'error': 'whisper_not_installed',
                'install_hint': 'pip install openai-whisper',
            }

        audio_path = None

        # ── Record mode ──────────────────────────────────────────
        if source == 'record':
            try:
                import sounddevice as sd
            except ImportError:
                return {'ok': False, 'error': 'sounddevice_not_installed',
                        'install_hint': 'pip install sounddevice'}

            try:
                from scipy.io.wavfile import write as wav_write
            except ImportError:
                return {'ok': False, 'error': 'scipy_not_installed',
                        'install_hint': 'pip install scipy'}

            sample_rate = 16000  # Whisper prefers 16 kHz
            ts = int(time.time())
            audio_path = os.path.join(tempfile.gettempdir(), f'uruk_record_{ts}.wav')
            recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
            sd.wait()
            wav_write(audio_path, sample_rate, recording)

        # ── File mode ────────────────────────────────────────────
        else:
            audio_path = os.path.abspath(os.path.expanduser(source))
            if not os.path.isfile(audio_path):
                return {'ok': False, 'error': 'file_not_found', 'path': audio_path}

        # ── Load model (cached) ──────────────────────────────────
        if model_size not in _WHISPER_MODELS:
            _WHISPER_MODELS[model_size] = whisper.load_model(model_size)
        model = _WHISPER_MODELS[model_size]

        # ── Transcribe ───────────────────────────────────────────
        whisper_lang = _LANG_MAP[lang_arg]
        result = model.transcribe(audio_path, language=whisper_lang, task='transcribe')

        return {
            'ok': True,
            'text': result.get('text', '').strip(),
            'lang_detected': result.get('language'),
            'segments_count': len(result.get('segments', [])),
            'model': model_size,
            'source': audio_path,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
