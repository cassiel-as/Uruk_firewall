"""
URUK Trinity Console — Calendar Service

Phase 1 tool: list local .ics files + parse events with optional date range filter.

User flow:
  - Operator exports Google Calendar / iCloud Calendar to .ics
  - Drops .ics file into C:\\uruk-trinity-console\\data\\calendar\\
  - Console list_files() shows available .ics files
  - list_events(file, from_dt, to_dt) returns parsed events

Falls back gracefully if `icalendar` package not installed (minimal parser).
"""

from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Try icalendar (preferred); fall back to regex parsing if not available
try:
    from icalendar import Calendar
    HAS_ICALENDAR = True
except ImportError:
    HAS_ICALENDAR = False


BASE_DIR = Path(__file__).parent.resolve()
CALENDAR_DIR = BASE_DIR / "data" / "calendar"


class CalendarServiceError(Exception):
    """Generic calendar service error."""


# ─────────────────────────────────────────────────────────────────
def _ensure_calendar_dir():
    """Create data/calendar/ folder + README if not present."""
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    readme = CALENDAR_DIR / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Calendar Data Folder\n\n"
            "Drop `.ics` files here. Each file represents a calendar.\n\n"
            "## Export Google Calendar to .ics\n\n"
            "1. Go to https://calendar.google.com\n"
            "2. Settings → Import & Export → Export\n"
            "3. Download `.zip` containing one `.ics` per calendar\n"
            "4. Extract + copy the `.ics` files into this folder\n\n"
            "## Export iCloud Calendar to .ics\n\n"
            "1. Open Calendar.app (macOS)\n"
            "2. File → Export → Export...\n"
            "3. Save as `.ics`\n"
            "4. Copy into this folder\n\n"
            "## Console usage\n\n"
            "- `GET /api/tools/calendar/files` → lists `.ics` files here\n"
            "- `GET /api/tools/calendar/events?file=NAME.ics&from_dt=2026-01-01&to_dt=2026-12-31`\n"
            "  → parses events within the date range\n",
            encoding="utf-8",
        )


def _parse_dt(value) -> Optional[str]:
    """Best-effort convert icalendar dt to ISO 8601 string."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.isoformat()
            return value.astimezone(timezone.utc).isoformat()
        return value.isoformat()
    return str(value)


def _filter_date(dt_str: Optional[str], lo: Optional[str], hi: Optional[str]) -> bool:
    """Return True if dt_str falls within [lo, hi]. Naive ISO date prefix compare."""
    if not dt_str:
        return True  # Include events with no date
    s = dt_str[:10]  # YYYY-MM-DD prefix
    if lo and s < lo:
        return False
    if hi and s > hi:
        return False
    return True


# ─────────────────────────────────────────────────────────────────
class CalendarService:
    """Local .ics file calendar service."""

    def __init__(self):
        _ensure_calendar_dir()

    def list_files(self) -> List[Dict]:
        """List all .ics files in data/calendar/ with metadata."""
        _ensure_calendar_dir()
        files = []
        for p in sorted(CALENDAR_DIR.glob("*.ics")):
            stat = p.stat()
            files.append({
                "filename": p.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
        return files

    def list_events(
        self,
        filename: str,
        from_dt: Optional[str] = None,
        to_dt: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Parse .ics file, return events filtered by date range.

        from_dt / to_dt: ISO date prefix "YYYY-MM-DD" (no time).
        Returns up to `limit` events sorted by start ascending.
        """
        # Safety: only file names, no path components
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise CalendarServiceError(f"invalid filename: {filename!r}")
        path = CALENDAR_DIR / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        if not filename.lower().endswith(".ics"):
            raise CalendarServiceError("only .ics files supported")

        data = path.read_text(encoding="utf-8", errors="replace")

        if HAS_ICALENDAR:
            return self._parse_with_icalendar(data, from_dt, to_dt, limit)
        else:
            return self._parse_minimal(data, from_dt, to_dt, limit)

    def _parse_with_icalendar(self, data: str, from_dt, to_dt, limit) -> List[Dict]:
        try:
            cal = Calendar.from_ical(data)
        except Exception as e:
            raise CalendarServiceError(f"icalendar parse failed: {e}")

        events = []
        for comp in cal.walk("VEVENT"):
            try:
                summary = str(comp.get("SUMMARY", "(no title)"))
                start = _parse_dt(comp.decoded("DTSTART") if comp.get("DTSTART") else None)
                end = _parse_dt(comp.decoded("DTEND") if comp.get("DTEND") else None)
                location = str(comp.get("LOCATION", ""))[:200]
                description = str(comp.get("DESCRIPTION", ""))[:500]
                uid = str(comp.get("UID", ""))
            except Exception:
                continue

            if not _filter_date(start, from_dt, to_dt):
                continue

            events.append({
                "summary": summary,
                "start": start,
                "end": end,
                "location": location,
                "description": description,
                "uid": uid,
            })

        # Sort by start (None → end)
        events.sort(key=lambda e: e.get("start") or "9999")
        return events[:limit]

    def _parse_minimal(self, data: str, from_dt, to_dt, limit) -> List[Dict]:
        """Minimal regex parser if icalendar package not available."""
        import re
        events = []
        for block in re.split(r"BEGIN:VEVENT", data)[1:]:
            block = block.split("END:VEVENT")[0]
            def grab(key):
                m = re.search(rf"^{key}[^:]*:(.+?)(?:\r?\n[^ \t])", block, re.MULTILINE | re.DOTALL)
                if m:
                    val = m.group(1).strip()
                    # Unfold continuation lines (lines starting with space/tab)
                    val = re.sub(r'\r?\n[ \t]', '', val)
                    return val
                return ""
            summary = grab("SUMMARY")
            start = grab("DTSTART")
            end = grab("DTEND")
            location = grab("LOCATION")
            description = grab("DESCRIPTION")[:500]
            uid = grab("UID")
            # Normalize DT to ISO if possible
            iso_start = _normalize_ics_dt(start)
            iso_end = _normalize_ics_dt(end)
            if not _filter_date(iso_start, from_dt, to_dt):
                continue
            events.append({
                "summary": summary or "(no title)",
                "start": iso_start,
                "end": iso_end,
                "location": location,
                "description": description,
                "uid": uid,
            })
        events.sort(key=lambda e: e.get("start") or "9999")
        return events[:limit]


def _normalize_ics_dt(s: str) -> Optional[str]:
    """Convert ICS DTSTART like '20260513T140000Z' or '20260513' to ISO format."""
    if not s:
        return None
    s = s.strip()
    import re
    m = re.match(r'(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?', s)
    if not m:
        return s  # Return as-is if can't parse
    y, mo, d, h, mi, se, z = m.groups()
    if h is None:
        return f"{y}-{mo}-{d}"
    return f"{y}-{mo}-{d}T{h}:{mi}:{se}{'Z' if z else ''}"


# Module-level singleton
calendar_svc = CalendarService()
