"""
URUK auto-upgraded tool: play_sound
Installed: 2026-05-30T14:27:02.537060
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='play_sound',
    description='Play a Windows system sound, a simple frequency beep, or a local WAV file using the standard winsound backend. Returns result.played, result.backend, and source metadata.',
    args=[ArgSpec(**a) for a in [{'name': 'sound', 'type': 'str', 'required': False, 'description': 'System sound alias: default, ok, asterisk, exclamation, hand, or question.'}, {'name': 'file_path', 'type': 'str', 'required': False, 'description': 'Optional local WAV file path to play instead of a system sound.'}, {'name': 'async_play', 'type': 'bool', 'required': False, 'description': 'Play WAV files asynchronously when true, default true.'}, {'name': 'frequency_hz', 'type': 'int', 'required': False, 'description': 'Optional beep frequency from 37 to 32767 Hz.'}, {'name': 'duration_ms', 'type': 'int', 'required': False, 'description': 'Beep duration in milliseconds, clamped from 50 to 5000.'}, {'name': 'stop', 'type': 'bool', 'required': False, 'description': 'Stop any currently playing asynchronous WAV sound and return.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        args = args or {}
        import winsound

        if bool(args.get("stop", False)):
            winsound.PlaySound(None, 0)
            return {"result": {"played": False, "stopped": True, "backend": "winsound"}}

        frequency = args.get("frequency_hz")
        if frequency is not None:
            frequency = max(37, min(32767, int(frequency)))
            duration = max(50, min(5000, int(args.get("duration_ms", 300))))
            winsound.Beep(frequency, duration)
            return {"result": {"played": True, "backend": "winsound", "source": "beep", "frequency_hz": frequency, "duration_ms": duration}}

        file_path = str(args.get("file_path") or "").strip()
        async_play = bool(args.get("async_play", True))
        if file_path:
            from pathlib import Path
            path = Path(file_path).expanduser()
            if not path.is_file():
                return {"error": "file_path does not exist or is not a file"}
            if path.suffix.lower() != ".wav":
                return {"error": "winsound file playback supports .wav files only"}
            if path.stat().st_size > 26214400:
                return {"error": "file_path is larger than 25 MB"}
            flags = winsound.SND_FILENAME | (winsound.SND_ASYNC if async_play else winsound.SND_SYNC)
            winsound.PlaySound(str(path), flags)
            return {"result": {"played": True, "backend": "winsound", "source": "file", "file_path": str(path), "async_play": async_play}}

        sound = str(args.get("sound") or "default").lower()
        aliases = {
            "default": -1,
            "ok": winsound.MB_OK,
            "asterisk": winsound.MB_ICONASTERISK,
            "exclamation": winsound.MB_ICONEXCLAMATION,
            "hand": winsound.MB_ICONHAND,
            "question": winsound.MB_ICONQUESTION
        }
        beep_type = aliases.get(sound, -1)
        winsound.MessageBeep(beep_type)
        return {"result": {"played": True, "backend": "winsound", "source": "system", "sound": sound if sound in aliases else "default"}}
    except Exception as e:
        return {"error": str(e)}
