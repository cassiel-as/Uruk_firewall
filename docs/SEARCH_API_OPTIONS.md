# Free / cheap search API options for BrowserNode

Audit done 2026-05-24 in response to: only `duckduckgo_lite` available, DDG hang
risk. BrowserNode already has slot stubs for `brave / google_cse / tavily /
serper / bing` — just need API keys (or pluggable replacements).

## Quick decision matrix

| Engine | Free quota | Signup difficulty | Existing slot? | Recommendation |
|---|---|---|---|---|
| **Tavily** | 1000 calls/mo | ★ trivial (just email) | ✓ yes | **#1 pick — easiest** |
| **Brave Search API** | 2000 calls/mo | ★★ easy (needs credit card on file for free tier) | ✓ yes | #2 — best quota if OK with CC |
| **Jina Reader / Search** | ~20 RPM, generous monthly | ★ no key needed (or free key for higher tier) | ✗ needs slot | **#3 — best no-key option** |
| **Google CSE** | 100 calls/day | ★★★ medium (CSE engine + API key) | ✓ yes | #4 — if already a Google user |
| **SearXNG self-host** | unlimited (self-host) | ★★★★ high (run container) | ✗ needs slot | only if heavy use |
| **Serper.dev** | 2500 one-time credits, then paid | ★★ easy | ✓ yes | demo only — not for long-term free |
| **Bing Web Search** | — | — | ✓ yes | **DEPRECATED Aug 2025** — remove slot |
| **DuckDuckGo Lite** | unlimited (no key) but unstable | ✓ no-key | ✓ yes (current) | keep as last-resort fallback only |

## Detailed picks

### #1 Tavily — easiest plug-in
- Sign up at https://app.tavily.com → get key → `export TAVILY_API_KEY=tvly-...`
- 1000 calls/month free. Per-call cost paid: $0.005
- Returns clean JSON with title/url/snippet/raw_content
- BrowserNode `tavily` slot already coded; just needs env var set
- **Effort**: 30 seconds (signup + paste key)

### #2 Brave Search API — best free quota
- Sign up at https://brave.com/search/api/ → needs credit card to validate (no charge on free tier)
- 2000 calls/month free, 1 query/sec rate limit
- Returns JSON
- BrowserNode `brave` slot already coded; needs `BRAVE_API_KEY` env var
- **Effort**: 2 minutes (signup + CC verify + key)

### #3 Jina Reader/Search — no-key zero-setup
- URL pattern: `https://s.jina.ai/<urlencoded-query>` → returns markdown of top search results
- Or: `https://r.jina.ai/<target-url>` for single-URL clean read
- ~20 RPM without key, higher with free signup
- **No slot in BrowserNode currently** — would need new adapter (small lift, ~30 LOC)
- **Best if user wants zero signup**, lower quota than Tavily

### #4 Google CSE — for existing Google users
- Create Custom Search Engine at https://programmablesearchengine.google.com/
- Get API key at https://console.cloud.google.com/apis (enable Custom Search API)
- 100 calls/day free
- Two env vars needed: `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID`
- BrowserNode `google_cse` slot already coded
- **Effort**: 5-10 minutes (3-step setup)

### SearXNG self-host — for power users
- Open-source meta-search aggregator (aggregates Google/Bing/DDG/etc. results)
- Self-host via Docker: `docker run searxng/searxng`
- Unlimited calls, fully private
- Would need new BrowserNode adapter pointing to local instance
- **Effort**: 30 min initial setup, then forever-free

## DuckDuckGo Lite hang analysis

**Cause** (not a bug in our code):
- DDG progressively tightened bot detection 2024-2025
- HTML endpoint sometimes returns 200 with empty body / 202 queueing
- httpx timeout was 30s; some requests sit at connection-establishment phase

**Fix applied (v8.35)**:
- `services/browser_node.py::_run_engine_safe` now wraps `engine.search()` in
  `asyncio.wait_for(timeout=35.0)` (outer cap on top of httpx's 30s)
- All exceptions swallowed (TimeoutError, SearchEngineError, generic Exception)
- → returns empty list, BrowserNode falls back to next engine or returns 0 sources
- Pipeline **cannot hang on a single search engine anymore**

## Recommended user action

1. **Now**: try Tavily (#1) — 1 min to set up, gets BrowserNode actually working
2. **If hit Tavily quota**: add Jina as second engine, or set up Brave (best quota)
3. **Leave DDG as last fallback** — even if slow/empty, won't hang pipeline now

## Wiring instructions (once user has key)

For Tavily:
```bash
# Set env var (one of):
$env:TAVILY_API_KEY = 'tvly-xxxxx'        # PowerShell
export TAVILY_API_KEY='tvly-xxxxx'         # bash
```
Then restart server. BrowserNode auto-detects via `services/search_engines.py`'s
`available()` check. `/api/search_engines` endpoint will report it as available.

Same pattern for `BRAVE_API_KEY`, `SERPER_API_KEY`, `GOOGLE_CSE_API_KEY` +
`GOOGLE_CSE_ID`.
