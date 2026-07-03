# static/

Browser UI for URUK Trinity Console. Served by `app.py`.

## Files

| File | Purpose |
|---|---|
| `index.html` | Main DOM structure for chat, internal QA panels, settings, tools, and self-upgrade UI. |
| `app.js` | Main frontend state machine, SSE handling, mode rendering, session UI, knowledge panels, and self-upgrade controls. |
| `world_atlas.js` | Leaflet geo-temporal Atlas: real-coordinate layers, causal links, time playback, event inspection, forecast corrections, and revision history. |
| `style.css`, `style_v2.css` | UI styling. `style_v2.css` contains newer layout refinements. |
| `vendor/leaflet/` | Locally bundled Leaflet 1.9.4 distribution and BSD-2-Clause license. |
| `agent_tools.js` | Agent tools panel behavior. |
| `app_control.js` | Local app control UI helpers. |
| `local_llm.js` | Local LLM discovery/chat UI helpers. |

## UI Principle

The conversation is the main product surface. Internal Trinity details should be available but collapsed by default:

- Main answer: fused Council answer.
- Expandable area: `內部質控 / 完整流程`.
- Developer/debug chips: Son veto, Spirit interrupt, knowledge health, harness episode.
- Self-upgrade plan detail: show post-install gates directly, including knowledge audit, coordinate benchmark, quick_eval, and rollback result.
- Self-upgrade preflight: `硬閘檢查` calls `/api/upgrade/gates` and runs the same read-only gate checks before installation.
- App Relay: `app_relay` can target Claude, Codex, ChatGPT, or Windows Copilot; Copilot is for Windows-context observation and should not be presented as the self-upgrade default.
- Files tab groups corpus files by role: Core, Theory, Supplements, Protocol, Module T, Causal DB, Causal Records, Prompts, Kairos, Experiments, Config.
- Vessel tab shows runtime self-state: map/location, calendar commitments, and collapsible notes backed by `/api/vessel/state`.

Avoid making Father / Son / Spirit raw panels dominate the page unless the user explicitly opens internal QA.

## Checks

```powershell
node --check static\app.js
node --check static\world_atlas.js
node --check static\agent_tools.js
node --check static\app_control.js
node --check static\local_llm.js
```

After meaningful frontend changes, open `http://127.0.0.1:8080/` in the in-app browser and verify:

- input and output are close enough for chat use
- internal QA is collapsed by default
- self-upgrade controls remain reachable
- mobile layout does not overlap
- World Atlas loads real map tiles, falls back to coordinate overlays when tiles fail, and keeps projected nodes visibly distinct from observed history
