"""
URUK Trinity Console — Skill Registry

Phase 1 of chat-discoverable skills system.

Structure:
    data/skills/builtin/   — system-seeded skills (read-only by convention)
    data/skills/user/      — user / chat-created skills (read-write)

Skill YAML schema:
    name: str                          # display name
    description: str                   # one-line summary
    trigger_cue: str                   # semantic description of when to invoke
    action_type: prompt_template|tool_call
    prompt_template: str               # if prompt_template, with {{variables}}
    tool_calls: list[dict]             # if tool_call, list of {tool, params}
    enabled: bool
    source: builtin|user
    created: ISO-8601 date
"""

import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import yaml


BASE_DIR = Path(__file__).parent.resolve()
SKILLS_DIR = BASE_DIR / "data" / "skills"
BUILTIN_DIR = SKILLS_DIR / "builtin"
USER_DIR = SKILLS_DIR / "user"


class SkillRegistryError(Exception):
    """Generic skill registry error."""


# ─────────────────────────────────────────────────────────────────
def _ensure_dirs():
    BUILTIN_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)


def _sluggify(name: str) -> str:
    """Convert name to filesystem-safe slug (ASCII only + sha256 suffix for CJK).

    Strict — only [a-z0-9_]+ allowed. CJK / other Unicode chars dropped and
    replaced with sha256 hash suffix for uniqueness + path-safety.
    """
    import hashlib
    # Keep ASCII alphanumerics + underscore
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()[:24]
    # Hash the original name (so different CJK names get different files)
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    if ascii_part:
        return f"{ascii_part}_{h}"
    return f"user_skill_{h}"


def _render_template(template: str, variables: Dict[str, str]) -> str:
    """Replace {{var}} placeholders with variable values."""
    def sub(m):
        key = m.group(1).strip()
        return str(variables.get(key, m.group(0)))
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def _detect_url(text: str) -> Optional[str]:
    """Extract first http(s) URL from text."""
    m = re.search(r"https?://[^\s\"<>]+", text)
    return m.group(0) if m else None


# ─────────────────────────────────────────────────────────────────
class SkillRegistry:
    """Discover + load + toggle skills."""

    def __init__(self):
        _ensure_dirs()
        self._cache: Dict[str, Dict] = {}
        self._cache_mtime = 0.0
        self.reload()

    # ─── Loading ───
    def reload(self) -> int:
        """Reload all skills from disk. Returns count."""
        self._cache = {}
        for folder, source in [(BUILTIN_DIR, "builtin"), (USER_DIR, "user")]:
            if not folder.exists():
                continue
            for p in sorted(folder.glob("*.yaml")):
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"⚠ skill load fail {p.name}: {e}")
                    continue
                if not isinstance(data, dict) or "name" not in data:
                    continue
                # Validate required fields
                data.setdefault("description", "")
                data.setdefault("trigger_cue", "")
                data.setdefault("action_type", "prompt_template")
                data.setdefault("enabled", True)
                data.setdefault("source", source)
                data["_filename"] = p.name
                data["_folder"] = source
                self._cache[data["name"]] = data
        self._cache_mtime = datetime.now().timestamp()
        return len(self._cache)

    def _maybe_reload(self):
        """Hot-reload if any skill file mtime newer than cache mtime."""
        for folder in (BUILTIN_DIR, USER_DIR):
            if not folder.exists():
                continue
            for p in folder.glob("*.yaml"):
                if p.stat().st_mtime > self._cache_mtime:
                    self.reload()
                    return

    # ─── Query ───
    def list_skills(self, enabled_only: bool = False) -> List[Dict]:
        """Return list of skill summaries."""
        self._maybe_reload()
        result = []
        for s in self._cache.values():
            if enabled_only and not s.get("enabled"):
                continue
            result.append({
                "name": s["name"],
                "description": s.get("description", ""),
                "trigger_cue": s.get("trigger_cue", ""),
                "action_type": s.get("action_type", "prompt_template"),
                "enabled": s.get("enabled", True),
                "source": s.get("source", "user"),
            })
        return result

    def get_skill(self, name: str) -> Optional[Dict]:
        self._maybe_reload()
        return self._cache.get(name)

    # ─── Toggle ───
    def toggle_skill(self, name: str, enabled: bool) -> bool:
        """Enable or disable skill. Writes back to YAML. Returns success."""
        skill = self.get_skill(name)
        if not skill:
            return False
        folder = BUILTIN_DIR if skill.get("_folder") == "builtin" else USER_DIR
        path = folder / skill["_filename"]
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        data["enabled"] = bool(enabled)
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.reload()
        return True

    # ─── Create (user / chat-created) ───
    def create_skill(self, data: Dict) -> str:
        """Save new skill to data/skills/user/. Returns saved filename."""
        if "name" not in data:
            raise SkillRegistryError("missing name")
        data.setdefault("source", "user")
        data.setdefault("enabled", True)
        data.setdefault("created", date.today().isoformat())
        # Schema validation
        action_type = data.get("action_type", "prompt_template")
        if action_type not in ("prompt_template", "tool_call"):
            raise SkillRegistryError(f"invalid action_type: {action_type}")
        if action_type == "prompt_template" and not data.get("prompt_template"):
            raise SkillRegistryError("prompt_template action requires prompt_template field")
        if action_type == "tool_call" and not data.get("tool_calls"):
            raise SkillRegistryError("tool_call action requires tool_calls field")

        slug = _sluggify(data["name"])
        filename = f"{slug}.yaml"
        path = USER_DIR / filename
        # Avoid clobber: if exists, suffix
        suffix = 0
        while path.exists():
            suffix += 1
            filename = f"{slug}_{suffix}.yaml"
            path = USER_DIR / filename
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.reload()
        return filename

    def delete_skill(self, name: str) -> bool:
        """Delete user skill (builtin protected)."""
        skill = self.get_skill(name)
        if not skill:
            return False
        if skill.get("_folder") == "builtin":
            raise SkillRegistryError("cannot delete builtin skill (use toggle to disable)")
        path = USER_DIR / skill["_filename"]
        if path.exists():
            path.unlink()
            self.reload()
            return True
        return False

    # ─── Apply skill action ───
    def apply_skill(self, skill: Dict, user_input: str) -> Dict:
        """Apply skill action. Returns {
            type: 'prompt_template' | 'tool_call',
            rendered_prompt: str (if prompt_template) or template-with-tool-placeholders,
            tool_calls: list (if tool_call), each with `tool` + `params`,
            variables: dict of template variables for downstream use,
        }"""
        action_type = skill.get("action_type", "prompt_template")
        # Build variables dict
        today = date.today().isoformat()
        today_plus_7 = (date.today() + timedelta(days=7)).isoformat()
        variables = {
            "user_input": user_input,
            "today": today,
            "today_plus_7": today_plus_7,
            "tomorrow": (date.today() + timedelta(days=1)).isoformat(),
            "detected_url": _detect_url(user_input) or "",
        }

        if action_type == "prompt_template":
            tmpl = skill.get("prompt_template", "")
            rendered = _render_template(tmpl, variables)
            return {
                "type": "prompt_template",
                "rendered_prompt": rendered,
                "tool_calls": [],
                "variables": variables,
            }

        # tool_call
        tool_calls = skill.get("tool_calls", [])
        rendered_calls = []
        for tc in tool_calls:
            tool = tc.get("tool")
            params = tc.get("params", {})
            rendered_params = {}
            for k, v in params.items():
                if isinstance(v, str):
                    rendered_params[k] = _render_template(v, variables)
                else:
                    rendered_params[k] = v
            rendered_calls.append({"tool": tool, "params": rendered_params})
        return {
            "type": "tool_call",
            "rendered_prompt": skill.get("prompt_template", ""),  # may be empty
            "tool_calls": rendered_calls,
            "variables": variables,
        }


# Module-level singleton
skill_registry = SkillRegistry()
