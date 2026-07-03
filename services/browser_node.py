"""
URUK Trinity Console — BrowserNode (v8.15 MS-1)

Spec mandate (/news mode):
  - ≥3 sources fetched per query
  - ≥2 opposing coordinates (cross-coord audit; satisfied via SourceCoordinateRegistry)
  - Each source individually 八律-audited (downstream Stage 3 reads injected summary)

v8.15 — Multi-engine search with coordinate-diversity fan-out:
  - Primary engine (default: duckduckgo_lite, no API key) runs first.
  - If primary returns < `min_coordinate_diversity` unique coordinates,
    fall over engines in order from `search_engines.fallback`, capped at
    `max_total_queries`.
  - Each engine's availability checked via .available() — missing key = skip,
    no exception. Failures of one engine never halt the rest.
  - Per-URL fetch + truncation logic from v8.14 BN is preserved.

Public API:
    BrowserNode().fetch_with_sources(query, min_sources=3) -> dict
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from browser_service import browser as default_browser, BrowserServiceError
from services.search_engines import (
    SEARCH_ENGINES,
    SearchEngineBase,
    SearchEngineError,
    SearchResult,
    DuckDuckGoLiteSearch,
)
from services.otel_setup import tracer, emit_event

log = logging.getLogger(__name__)


class BrowserNode:
    """Spec-compliant browser orchestrator for /news + URL-aware modes."""

    DEFAULT_SEARCH_OVERSAMPLE = 2     # search 2× min_sources to allow per-URL failure
    DEFAULT_PER_URL_TIMEOUT = 20.0
    DEFAULT_MAX_TEXT_CHARS = 5000     # cap per source

    # MS-1 defaults (overridable via nodes.yaml browser_node.search_engines block)
    DEFAULT_PRIMARY_ENGINE = "duckduckgo_lite"
    DEFAULT_FALLBACK_ENGINES = ["brave", "google_cse", "tavily", "serper", "bing"]
    DEFAULT_MIN_COORDINATE_DIVERSITY = 2
    DEFAULT_MAX_TOTAL_QUERIES = 3

    def __init__(self, browser_svc=None, registry=None, config: Optional[Dict] = None):
        self.browser = browser_svc or default_browser
        self.registry = registry   # SourceCoordinateRegistry (optional)
        self.apply_config(config)

    def apply_config(self, config: Optional[Dict]) -> None:
        """Apply or re-apply a config dict (e.g. nodes.yaml's `browser_node:` block).

        Safe to call after init for hot-reload from Settings UI.
        """
        cfg = config or {}
        engines_cfg = (cfg.get("search_engines") or {})
        self.primary_engine_name = engines_cfg.get("primary", self.DEFAULT_PRIMARY_ENGINE)
        self.fallback_engine_names = list(
            engines_cfg.get("fallback", self.DEFAULT_FALLBACK_ENGINES)
        )
        self.min_coordinate_diversity = int(
            engines_cfg.get("min_coordinate_diversity", self.DEFAULT_MIN_COORDINATE_DIVERSITY)
        )
        self.max_total_queries = int(
            engines_cfg.get("max_total_queries", self.DEFAULT_MAX_TOTAL_QUERIES)
        )

    # ─────────── public ───────────

    async def fetch_with_sources(
        self,
        query: str,
        min_sources: int = 3,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
    ) -> Dict:
        """Search + render N sources for cross-coordinate audit.

        v8.15: search step now fans out across engines when primary returns
        low coordinate diversity. `engines_used` records what ran and why.

        Returns:
            {
              "primary_sources": [...],
              "raw_count": int,
              "fetched_count": int,
              "errors": [...],
              "query": str,
              "engines_used": [
                {"engine": "duckduckgo_lite", "results_count": int, "reason": "primary"|"diversity_fallback"|"skipped"},
                ...
              ],
              "coordinate_diversity": int,    # unique coord count post-audit
            }
        """
        return await self._fetch_with_sources_traced(query, min_sources, max_text_chars)

    async def _fetch_with_sources_traced(self, query, min_sources, max_text_chars):
        with tracer.start_as_current_span("browser_node.fetch_with_sources") as _bn_span:
            try:
                _bn_span.set_attribute("uruk.bn.query_length", len(query or ""))
                _bn_span.set_attribute("uruk.bn.min_sources", min_sources)
            except Exception:
                pass
            result = await self._fetch_with_sources_impl(query, min_sources, max_text_chars)
            try:
                _bn_span.set_attribute("uruk.bn.fetched_count", result.get("fetched_count", 0))
                _bn_span.set_attribute("uruk.bn.coordinate_diversity", result.get("coordinate_diversity", 0))
                for eu in result.get("engines_used", []):
                    emit_event(_bn_span, "engine_used",
                               engine=str(eu.get("engine", "?")),
                               results_count=int(eu.get("results_count", 0)),
                               reason=str(eu.get("reason", "")))
            except Exception:
                pass
            return result

    async def _fetch_with_sources_impl(self, query, min_sources, max_text_chars):
        result = {
            "primary_sources": [],
            "raw_count": 0,
            "fetched_count": 0,
            "errors": [],
            "query": query,
            "engines_used": [],
            "coordinate_diversity": 0,
        }
        if not query or not isinstance(query, str):
            result["errors"].append("empty_or_invalid_query")
            return result

        target = max(min_sources, 1)
        oversample_n = target * self.DEFAULT_SEARCH_OVERSAMPLE

        # 1) Multi-engine search with diversity fan-out
        search_results, engines_used = await self._search_with_fallback(
            query=query, per_engine_n=oversample_n,
        )
        result["engines_used"] = engines_used
        result["raw_count"] = len(search_results)
        if not search_results:
            result["errors"].append("no_search_results_any_engine")
            return result

        # 2) Fetch each URL in parallel; tolerate individual failures
        candidates = search_results[: target * self.DEFAULT_SEARCH_OVERSAMPLE]
        fetch_tasks = [self._fetch_one(item) for item in candidates]
        fetched = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for item, outcome in zip(candidates, fetched):
            if isinstance(outcome, Exception):
                result["errors"].append(
                    f"fetch_failed {item.get('url','?')}: {type(outcome).__name__}: {outcome}"
                )
                continue
            if not outcome or not outcome.get("text"):
                result["errors"].append(f"empty_body {item.get('url','?')}")
                continue
            outcome["text"] = outcome["text"][:max_text_chars]
            outcome.setdefault("snippet", item.get("snippet", ""))
            outcome["source_engine"] = item.get("source_engine", "")
            result["primary_sources"].append(outcome)
            if len(result["primary_sources"]) >= target:
                break

        result["fetched_count"] = len(result["primary_sources"])
        result["coordinate_diversity"] = self._count_unique_coords(
            [s.get("url", "") for s in result["primary_sources"]]
        )
        return result

    # ─────────── search engine fan-out ───────────

    async def _search_with_fallback(
        self, query: str, per_engine_n: int,
    ) -> Tuple[List[Dict], List[Dict]]:
        """Run primary engine; fall over fallback engines if diversity < min.

        Returns (deduped_results, engines_used_log).
        """
        engines_used: List[Dict] = []
        aggregated: List[Dict] = []
        seen_urls = set()

        # Primary
        primary = self._instantiate(self.primary_engine_name)
        if primary is None:
            engines_used.append({
                "engine": self.primary_engine_name,
                "results_count": 0,
                "reason": "unknown_engine",
            })
        elif not primary.available():
            engines_used.append({
                "engine": primary.name,
                "results_count": 0,
                "reason": "skipped_no_api_key",
            })
        else:
            primary_hits = await self._run_engine_safe(primary, query, per_engine_n)
            primary_dicts = [r.to_dict() for r in primary_hits]
            for d in primary_dicts:
                if d["url"] and d["url"] not in seen_urls:
                    aggregated.append(d)
                    seen_urls.add(d["url"])
            engines_used.append({
                "engine": primary.name,
                "results_count": len(primary_dicts),
                "reason": "primary",
            })

        # Diversity check
        unique_coords = self._count_unique_coords([d["url"] for d in aggregated])
        engines_queried = 1

        # Fan over fallback engines until either threshold met or budget burned
        if unique_coords < self.min_coordinate_diversity:
            for fb_name in self.fallback_engine_names:
                if engines_queried >= self.max_total_queries:
                    break
                if fb_name == self.primary_engine_name:
                    continue
                eng = self._instantiate(fb_name)
                if eng is None:
                    engines_used.append({
                        "engine": fb_name, "results_count": 0,
                        "reason": "unknown_engine",
                    })
                    continue
                if not eng.available():
                    engines_used.append({
                        "engine": eng.name, "results_count": 0,
                        "reason": "skipped_no_api_key",
                    })
                    continue
                hits = await self._run_engine_safe(eng, query, max(per_engine_n // 2, 3))
                new_count = 0
                for r in hits:
                    if r.url and r.url not in seen_urls:
                        aggregated.append(r.to_dict())
                        seen_urls.add(r.url)
                        new_count += 1
                engines_used.append({
                    "engine": eng.name,
                    "results_count": new_count,
                    "reason": "diversity_fallback",
                })
                engines_queried += 1
                unique_coords = self._count_unique_coords([d["url"] for d in aggregated])
                if unique_coords >= self.min_coordinate_diversity:
                    break

        return aggregated, engines_used

    async def _run_engine_safe(
        self, engine: SearchEngineBase, query: str, n: int,
    ) -> List[SearchResult]:
        """Run one engine; swallow SearchEngineError + outer timeout. Return [] on failure.

        v8.35 — wrap engine.search with asyncio.wait_for as belt-and-suspenders
        timeout. Some engines (esp. DDG HTML scrape) can occasionally hang past
        their internal httpx timeout if connection sits in DNS or TLS handshake.
        Hard outer cap (35s) ensures no single engine can stall the pipeline.
        """
        import asyncio as _asyncio
        try:
            return await _asyncio.wait_for(engine.search(query, n=n), timeout=35.0)
        except _asyncio.TimeoutError:
            log.warning("search engine %s timed out (>35s outer cap)", engine.name)
            return []
        except SearchEngineError as e:
            log.warning("search engine %s failed: %s", engine.name, e)
            return []
        except Exception as e:
            log.warning("search engine %s unexpected error: %s", engine.name, type(e).__name__)
            return []
        except Exception as e:
            log.warning("search engine %s unexpected: %s: %s",
                        engine.name, type(e).__name__, e)
            return []

    def _instantiate(self, name: str) -> Optional[SearchEngineBase]:
        cls = SEARCH_ENGINES.get(name)
        if cls is None:
            return None
        try:
            if name == "duckduckgo_lite":
                return cls(browser_svc=self.browser)
            return cls()
        except Exception as e:
            log.warning("engine %s init failed: %s", name, e)
            return None

    def _count_unique_coords(self, urls: List[str]) -> int:
        """Count distinct SourceCoordinateRegistry coordinates among URLs.

        Falls back to distinct-domain count when no registry attached.
        """
        if not urls:
            return 0
        coords = set()
        if self.registry is not None:
            for u in urls:
                try:
                    a = self.registry.audit(u, "")
                    c = a.get("coordinate") or "unknown_unverified"
                    coords.add(c)
                except Exception:
                    continue
            return len(coords)
        # Fallback: distinct registered-domain proxy
        domains = set()
        for u in urls:
            try:
                d = urlparse(u).netloc.lower()
                if d.startswith("www."):
                    d = d[4:]
                if d:
                    domains.add(d)
            except Exception:
                continue
        return len(domains)

    # ─────────── per-URL fetch (unchanged from v8.14) ───────────

    async def _fetch_one(self, search_item: Dict) -> Optional[Dict]:
        """Fetch one URL via browser_service. Returns enriched dict or None."""
        url = search_item.get("url")
        title_hint = search_item.get("title", "")
        if not url:
            return None
        try:
            doc = await self.browser.fetch_url(url)
        except BrowserServiceError:
            raise
        return {
            "url": doc.get("final_url") or doc.get("url") or url,
            "title": doc.get("title") or title_hint or "(no title)",
            "text": doc.get("main_text", ""),
            "snippet": search_item.get("snippet", ""),
            "fetch_status": doc.get("status", 200),
            "fetched_at": doc.get("fetched_at", ""),
        }

    @staticmethod
    def detect_urls(text: str) -> List[str]:
        """Lightweight URL detector for triggering conditional BrowserNode in
        non-/news modes (firewall / blackbox / scr). Returns list of bare URLs."""
        import re as _re
        if not text:
            return []
        pattern = _re.compile(r"https?://[\w\-\.]+(?:/[^\s\"'<>]*)?")
        return pattern.findall(text)


# Module-level singleton (no LLM cost; safe to share)
browser_node = BrowserNode()
