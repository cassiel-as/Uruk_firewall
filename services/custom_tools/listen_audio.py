"""
URUK custom tool: listen_audio (聽覺 — hearing)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='listen_audio',
    description='Record audio from the microphone for N seconds and save to a WAV file. Uses sounddevice + scipy.io.wavfile.',
    args=[
        ArgSpec('duration_seconds', 'int', True,
                description='Recording duration in seconds (1–30).'),
        ArgSpec('sample_rate', 'int', False, default=44100,
                description='Sample rate in Hz, default 44100.'),
        ArgSpec('save_path', 'str', False, default=None,
                description='Optional output WAV file path. Defaults to a temp file.'),
    ],
    needs_visual=False,
    category='misc',
)


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        import time
        args = args or {}

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

        duration = max(1, min(30, int(args.get('duration_seconds') or 5)))
        sample_rate = max(8000, min(96000, int(args.get('sample_rate') or 44100)))
        save_path = args.get('save_path') or None

        if save_path:
            save_path = os.path.abspath(os.path.expanduser(str(save_path)))
        else:
            ts = int(time.time())
            save_path = os.path.join(tempfile.gettempdir(), f'uruk_audio_{ts}.wav')

        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
        sd.wait()
        wav_write(save_path, sample_rate, recording)

        return {
            'ok': True,
            'path': save_path,
            'duration': duration,
            'sample_rate': sample_rate,
            'channels': 1,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}
