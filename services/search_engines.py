"""
URUK Trinity Console — Search-engine plug-in registry (v8.15 MS-1).

Six engines behind a single `SearchEngineBase` interface so BrowserNode can
fall over engines when coordinate diversity is below threshold.

Engines:
    duckduckgo_lite — HTML scrape (no API key). Default primary.
    brave           — https://api.search.brave.com/res/v1/web/search
    bing            — https://api.bing.microsoft.com/v7.0/search
    google_cse      — https://www.googleapis.com/customsearch/v1
    tavily          — https://api.tavily.com/search
    serper          — https://google.serper.dev/search

Each engine reads its API key from env vars at call-time. Missing key →
`available()` returns False and the engine is skipped, no exception.
Failure of one engine NEVER halts the search; BrowserNode aggregates whatever
came back.

Public API:
    SearchResult dataclass — {title, url, snippet, source_engine}
    SearchEngineBase ABC   — .available(), .search(query, n)
    SEARCH_ENGINES dict    — name → class
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "Mozilla/5.0 (compatible; URUK-Trinity-Console/8.15; +browser_node)"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source_engine: str = ""

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source_engine": self.source_engine,
        }


class SearchEngineError(Exception):
    """Raised on transport / parse failure. Caller handles + skips engine."""


class SearchEngineBase(ABC):
    """Common interface for all search-engine plug-ins."""

    name: str = "base"

    def available(self) -> bool:
        """True if engine is callable (e.g. API key present). Default True."""
        return True

    @abstractmethod
    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        """Return up to n results. May raise SearchEngineError on transport fail."""
        ...

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,zh;q=0.7"}


# ─────────────────────────────────────────────────────────────────
# 1. DuckDuckGo Lite — wraps the existing browser_service implementation
# ─────────────────────────────────────────────────────────────────

class DuckDuckGoLiteSearch(SearchEngineBase):
    """Default no-key engine. Delegates to browser_service.web_search()."""

    name = "duckduckgo_lite"

    def __init__(self, browser_svc=None):
        # Lazy import to avoid circular: browser_service imports nothing from us
        if browser_svc is None:
            from browser_service import browser as default_browser
            browser_svc = default_browser
        self.browser = browser_svc

    def available(self) -> bool:
        return True   # always available, no key

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        try:
            raw = await self.browser.web_search(query, n=n)
        except Exception as e:
            raise SearchEngineError(f"duckduckgo_lite: {type(e).__name__}: {e}")
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                source_engine=self.name,
            )
            for item in raw
            if item.get("url")
        ]


# ─────────────────────────────────────────────────────────────────
# 2. Brave Search
# ─────────────────────────────────────────────────────────────────

class BraveSearch(SearchEngineBase):
    name = "brave"
    api_url = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.available():
            raise SearchEngineError("brave: missing BRAVE_SEARCH_API_KEY")
        headers = self._headers()
        headers["X-Subscription-Token"] = self.api_key
        headers["Accept"] = "application/json"
        params = {"q": query, "count": min(max(n, 1), 20)}
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as cli:
                r = await cli.get(self.api_url, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise SearchEngineError(f"brave HTTP: {e}")
        web_results = (data.get("web") or {}).get("results", []) or []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("description", "") or "")[:300],
                source_engine=self.name,
            )
            for item in web_results[:n]
            if item.get("url")
        ]


# ─────────────────────────────────────────────────────────────────
# 3. Bing Web Search (Azure)
# ─────────────────────────────────────────────────────────────────

class BingSearch(SearchEngineBase):
    name = "bing"
    api_url = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BING_SEARCH_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.available():
            raise SearchEngineError("bing: missing BING_SEARCH_API_KEY")
        headers = self._headers()
        headers["Ocp-Apim-Subscription-Key"] = self.api_key
        params = {"q": query, "count": min(max(n, 1), 20), "responseFilter": "Webpages"}
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as cli:
                r = await cli.get(self.api_url, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise SearchEngineError(f"bing HTTP: {e}")
        pages = (data.get("webPages") or {}).get("value", []) or []
        return [
            SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=(item.get("snippet", "") or "")[:300],
                source_engine=self.name,
            )
            for item in pages[:n]
            if item.get("url")
        ]


# ─────────────────────────────────────────────────────────────────
# 4. Google Programmable Search Engine (Custom Search JSON API)
# ─────────────────────────────────────────────────────────────────

class GoogleCSESearch(SearchEngineBase):
    name = "google_cse"
    api_url = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: Optional[str] = None, cse_id: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.cse_id = cse_id or os.environ.get("GOOGLE_CSE_ID", "")

    def available(self) -> bool:
        return bool(self.api_key and self.cse_id)

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.available():
            raise SearchEngineError("google_cse: missing GOOGLE_API_KEY or GOOGLE_CSE_ID")
        # CSE caps "num" at 10
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(max(n, 1), 10),
        }
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=self._headers()) as cli:
                r = await cli.get(self.api_url, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise SearchEngineError(f"google_cse HTTP: {e}")
        items = data.get("items", []) or []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=(item.get("snippet", "") or "")[:300],
                source_engine=self.name,
            )
            for item in items[:n]
            if item.get("link")
        ]


# ─────────────────────────────────────────────────────────────────
# 5. Tavily (AI-optimized snippets)
# ─────────────────────────────────────────────────────────────────

class TavilySearch(SearchEngineBase):
    name = "tavily"
    api_url = "https://api.tavily.com/search"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.available():
            raise SearchEngineError("tavily: missing TAVILY_API_KEY")
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": min(max(n, 1), 20),
            "include_answer": False,
        }
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=self._headers()) as cli:
                r = await cli.post(self.api_url, json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise SearchEngineError(f"tavily HTTP: {e}")
        items = data.get("results", []) or []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("content", "") or "")[:300],
                source_engine=self.name,
            )
            for item in items[:n]
            if item.get("url")
        ]


# ─────────────────────────────────────────────────────────────────
# 6. Serper (Google SERP wrapper)
# ─────────────────────────────────────────────────────────────────

class SerperSearch(SearchEngineBase):
    name = "serper"
    api_url = "https://google.serper.dev/search"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, n: int = 5) -> List[SearchResult]:
        if not self.available():
            raise SearchEngineError("serper: missing SERPER_API_KEY")
        headers = self._headers()
        headers["X-API-KEY"] = self.api_key
        headers["Content-Type"] = "application/json"
        payload = {"q": query, "num": min(max(n, 1), 20)}
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as cli:
                r = await cli.post(self.api_url, json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise SearchEngineError(f"serper HTTP: {e}")
        organic = data.get("organic", []) or []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=(item.get("snippet", "") or "")[:300],
                source_engine=self.name,
            )
            for item in organic[:n]
            if item.get("link")
        ]


# ─────────────────────────────────────────────────────────────────
# Registry — name → class
# ─────────────────────────────────────────────────────────────────

SEARCH_ENGINES: Dict[str, type] = {
    "duckduckgo_lite": DuckDuckGoLiteSearch,
    "brave":           BraveSearch,
    "bing":            BingSearch,
    "google_cse":      GoogleCSESearch,
    "tavily":          TavilySearch,
    "serper":          SerperSearch,
}


def get_engine(name: str) -> Optional[SearchEngineBase]:
    """Instantiate an engine by name. Returns None for unknown."""
    cls = SEARCH_ENGINES.get(name)
    if cls is None:
        return None
    return cls()


def list_available_engines() -> List[Dict]:
    """Return availability snapshot for UI display.

    Each entry: {name, available: bool, reason: str|None}
    """
    out: List[Dict] = []
    for name, cls in SEARCH_ENGINES.items():
        try:
            inst = cls()
            avail = inst.available()
            reason = None if avail else f"missing API key (set env var for {name})"
        except Exception as e:
            avail = False
            reason = f"init_failed: {type(e).__name__}"
        out.append({"name": name, "available": avail, "reason": reason})
    return out
