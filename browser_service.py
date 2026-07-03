"""
URUK Trinity Console — Browser Service

Phase 1 tools: web_search (DuckDuckGo HTML scrape) + fetch_url with SSRF protection.

Security:
    - URL scheme whitelist: http / https only
    - Reject localhost / private IP / link-local (SSRF protection)
    - 5MB response size cap, streamed
    - 30s timeout
    - Reasonable User-Agent (avoid 403 on some sites)
"""

import asyncio
import hashlib
import ipaddress
import re
import socket
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote_plus

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "URUKConsole/8.1 (cassiel-as) httpx/0.28"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT = 30.0


class BrowserServiceError(Exception):
    """Generic browser service error."""


class URLRejected(BrowserServiceError):
    """URL failed safety validation."""


# ─────────────────────────────────────────────────────────────────
# SSRF protection
# ─────────────────────────────────────────────────────────────────

def _is_private_address(host: str) -> bool:
    """Return True if host resolves to a private/loopback/link-local IP."""
    try:
        # Resolve hostname to IPs (may raise gaierror)
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return True  # Unknown host → reject
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
    return False


def _resolve_safe_url(url: str) -> str:
    """Validate URL. Raises URLRejected on safety violation."""
    if not url or not isinstance(url, str):
        raise URLRejected("URL must be non-empty string")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLRejected(f"unsupported scheme: {parsed.scheme!r}")
    if not parsed.netloc:
        raise URLRejected("URL missing host")
    host = parsed.hostname or ""
    if not host:
        raise URLRejected("URL missing hostname")
    # Reject localhost / private IPs / common bypass attempts
    if host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise URLRejected("localhost rejected")
    if _is_private_address(host):
        raise URLRejected(f"private/loopback host rejected: {host}")
    return url


# ─────────────────────────────────────────────────────────────────
class BrowserService:
    """Web search + URL fetch with SSRF protection."""

    def __init__(self):
        self.headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,zh;q=0.7"}

    async def web_search(self, query: str, n: int = 5) -> List[Dict]:
        """DuckDuckGo HTML scrape (no API key required).

        Returns list of {title, url, snippet}.
        """
        if not query or not isinstance(query, str):
            raise BrowserServiceError("query must be non-empty string")
        n = max(1, min(n, 20))
        ddg_url = "https://html.duckduckgo.com/html/"
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=self.headers, follow_redirects=True) as client:
                r = await client.post(ddg_url, data={"q": query, "b": ""})
                r.raise_for_status()
                html = r.text
        except httpx.HTTPError as e:
            raise BrowserServiceError(f"DDG request failed: {e}")

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict] = []
        for result in soup.select(".result"):
            if len(results) >= n:
                break
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")
            # DDG wraps URLs through /l/?uddg=...
            real_url = self._unwrap_ddg_url(url)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            results.append({
                "title": title,
                "url": real_url,
                "snippet": snippet[:300],
            })
        return results

    def _unwrap_ddg_url(self, ddg_link: str) -> str:
        """DDG wraps URLs in /l/?uddg=<encoded>. Extract real URL."""
        if "uddg=" in ddg_link:
            from urllib.parse import parse_qs, unquote
            try:
                # Sometimes the link is //duckduckgo.com/l/?...
                if ddg_link.startswith("//"):
                    ddg_link = "https:" + ddg_link
                p = urlparse(ddg_link)
                qs = parse_qs(p.query)
                if "uddg" in qs:
                    return unquote(qs["uddg"][0])
            except Exception:
                pass
        return ddg_link

    async def fetch_url(self, url: str) -> Dict:
        """Fetch URL content with SSRF protection + size cap.

        Returns: {url, final_url, status, title, main_text (50KB),
                  date_published, fetched_at, content_hash}
        """
        url = _resolve_safe_url(url)
        try:
            async with httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT, headers=self.headers, follow_redirects=True,
                max_redirects=5,
            ) as client:
                # Stream to enforce size cap early
                async with client.stream("GET", url) as r:
                    final_url = str(r.url)
                    # Re-validate final URL (redirect may target private IP)
                    _resolve_safe_url(final_url)
                    status = r.status_code
                    # Read body capped
                    chunks = []
                    total = 0
                    async for chunk in r.aiter_bytes(chunk_size=65536):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > MAX_RESPONSE_BYTES:
                            break
                    body = b"".join(chunks)[:MAX_RESPONSE_BYTES]
        except httpx.HTTPError as e:
            raise BrowserServiceError(f"fetch failed: {e}")

        # Detect content type
        ct = "text/html"
        try:
            ct = r.headers.get("content-type", "text/html")
        except Exception:
            pass

        text = body.decode("utf-8", errors="replace")
        title = ""
        main_text = ""
        date_published = None

        if "html" in ct.lower() or text.lstrip().startswith("<"):
            soup = BeautifulSoup(text, "html.parser")
            # Title
            title_el = soup.find("title")
            if title_el:
                title = title_el.get_text(strip=True)[:250]
            # Strip script/style/nav/footer for main text
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            # Try article > main > body
            main_el = soup.find("article") or soup.find("main") or soup.find("body")
            if main_el:
                # Get visible text, collapse whitespace
                main_text = re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', main_el.get_text(separator='\n', strip=True)))
            # Try to extract date
            for meta_name in ("article:published_time", "datePublished", "date"):
                meta = soup.find("meta", attrs={"property": meta_name}) or soup.find("meta", attrs={"name": meta_name})
                if meta and meta.get("content"):
                    date_published = meta["content"]
                    break
        else:
            # Plain text / JSON / other
            main_text = text

        # Cap main_text to 50KB
        if len(main_text) > 50000:
            main_text = main_text[:50000] + "\n\n[... truncated, original was {} chars]".format(len(main_text))

        return {
            "url": url,
            "final_url": final_url,
            "status": status,
            "title": title,
            "main_text": main_text,
            "date_published": date_published,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "content_hash": hashlib.sha256(body).hexdigest(),
            "content_type": ct,
            "size_bytes": total,
        }


# Module-level singleton
browser = BrowserService()
