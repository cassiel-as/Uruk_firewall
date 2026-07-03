"""
URUK auto-upgraded tool: watch_file
Installed: 2026-05-30T14:19:05.899575
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='watch_file',
    description='Poll a file or directory for a short bounded interval and return JSON change events for created, modified, and deleted paths.',
    args=[ArgSpec(**a) for a in [{'name': 'path', 'type': 'str', 'required': False, 'description': 'File or directory path to watch; defaults to current directory.'}, {'name': 'seconds', 'type': 'int', 'required': False, 'description': 'Number of seconds to watch, clamped from 0 to 60.'}, {'name': 'interval_ms', 'type': 'int', 'required': False, 'description': 'Polling interval in milliseconds, clamped from 100 to 5000.'}, {'name': 'recursive', 'type': 'bool', 'required': False, 'description': 'Watch directory trees recursively when true.'}, {'name': 'max_events', 'type': 'int', 'required': False, 'description': 'Maximum events to return, default 500.'}, {'name': 'max_entries', 'type': 'int', 'required': False, 'description': 'Maximum filesystem entries to snapshot, default 5000.'}]],
    needs_visual=False,
    category='file',
)

def execute(args: dict) -> dict:
    try:
        args = args or {}
        import os
        import time

        path = str(args.get("path") or ".").strip() or "."
        full_path = os.path.abspath(path)
        if not os.path.exists(full_path):
            return {"error": "path does not exist", "path": full_path}

        seconds = int(args.get("seconds", 2))
        interval_ms = int(args.get("interval_ms", 500))
        recursive = bool(args.get("recursive", True))
        max_events = int(args.get("max_events", 500))
        max_entries = int(args.get("max_entries", 5000))

        if seconds < 0:
            seconds = 0
        if seconds > 60:
            seconds = 60
        if interval_ms < 100:
            interval_ms = 100
        if interval_ms > 5000:
            interval_ms = 5000
        if max_events < 1:
            max_events = 1
        if max_events > 5000:
            max_events = 5000
        if max_entries < 100:
            max_entries = 100
        if max_entries > 50000:
            max_entries = 50000

        def snapshot(root):
            items = {}
            truncated = False

            def add_path(candidate):
                nonlocal truncated
                if len(items) >= max_entries:
                    truncated = True
                    return
                try:
                    stat = os.stat(candidate)
                except (FileNotFoundError, PermissionError, OSError):
                    return
                kind = "directory" if os.path.isdir(candidate) else "file"
                items[os.path.abspath(candidate)] = {
                    "type": kind,
                    "mtime": float(stat.st_mtime),
                    "size": int(stat.st_size) if kind == "file" else 0
                }

            if os.path.isfile(root):
                add_path(root)
            else:
                for dirpath, dirnames, filenames in os.walk(root):
                    add_path(dirpath)
                    for filename in filenames:
                        add_path(os.path.join(dirpath, filename))
                        if len(items) >= max_entries:
                            break
                    if not recursive:
                        dirnames[:] = []
                    if len(items) >= max_entries:
                        truncated = True
                        dirnames[:] = []
                        break
            return items, truncated

        def compare(previous, current):
            events = []
            previous_paths = set(previous.keys())
            current_paths = set(current.keys())

            for candidate in sorted(current_paths - previous_paths):
                meta = current[candidate]
                events.append({"event": "created", "path": candidate, "type": meta["type"], "size": meta["size"], "mtime": meta["mtime"]})

            for candidate in sorted(previous_paths - current_paths):
                meta = previous[candidate]
                events.append({"event": "deleted", "path": candidate, "type": meta["type"], "size": meta["size"], "mtime": meta["mtime"]})

            for candidate in sorted(previous_paths & current_paths):
                before = previous[candidate]
                after = current[candidate]
                if before["mtime"] != after["mtime"] or before["size"] != after["size"] or before["type"] != after["type"]:
                    events.append({"event": "modified", "path": candidate, "type": after["type"], "old_size": before["size"], "size": after["size"], "old_mtime": before["mtime"], "mtime": after["mtime"]})

            return events

        previous, truncated_start = snapshot(full_path)
        if seconds == 0:
            return {"path": full_path, "watched_seconds": 0, "recursive": recursive, "events": [], "event_count": 0, "snapshot_count": len(previous), "truncated": truncated_start}

        events = []
        truncated = truncated_start
        deadline = time.time() + seconds
        while time.time() < deadline and len(events) < max_events:
            remaining = deadline - time.time()
            time.sleep(min(interval_ms / 1000.0, max(0.0, remaining)))
            current, truncated_now = snapshot(full_path)
            truncated = truncated or truncated_now
            detected_at = time.time()
            for event in compare(previous, current):
                event["detected_at"] = detected_at
                events.append(event)
                if len(events) >= max_events:
                    break
            previous = current

        return {"path": full_path, "watched_seconds": seconds, "recursive": recursive, "events": events, "event_count": len(events), "final_snapshot_count": len(previous), "truncated": truncated}
    except Exception as e:
        return {"error": str(e)}
