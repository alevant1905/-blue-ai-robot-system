"""
Blue Robot Web Tools
====================
Web search and browsing functionality.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlsplit

import requests

from blue.server.security import assert_public_http_url

# ================================================================================
# CONFIGURATION
# ================================================================================

SEARCH_MAX_PER_MINUTE = int(os.getenv("SEARCH_MAX_PER_MINUTE", "8"))
SEARCH_CACHE_TTL_SEC = int(os.getenv("SEARCH_CACHE_TTL_SEC", "21600"))
SEARCH_RESULTS_PER_QUERY = int(os.getenv("SEARCH_RESULTS_PER_QUERY", "5"))

_SEARCH_TIMESTAMPS: deque = deque(maxlen=64)
_SEARCH_CACHE: Dict[str, tuple] = {}
_SEARCH_LOCK = threading.Lock()


# ================================================================================
# RATE LIMITING & CACHING
# ================================================================================

def _search_budget_ok() -> bool:
    """Check if we have search budget remaining."""
    now = time.time()
    cutoff = now - 60
    while _SEARCH_TIMESTAMPS and _SEARCH_TIMESTAMPS[0] < cutoff:
        _SEARCH_TIMESTAMPS.popleft()
    return len(_SEARCH_TIMESTAMPS) < SEARCH_MAX_PER_MINUTE


def _record_search():
    """Record a search timestamp."""
    _SEARCH_TIMESTAMPS.append(time.time())


def _get_cached(query: str) -> Optional[str]:
    """Get cached search result if valid."""
    key = query.lower().strip()
    if key in _SEARCH_CACHE:
        ts, val = _SEARCH_CACHE[key]
        if time.time() - ts < SEARCH_CACHE_TTL_SEC:
            return val
        del _SEARCH_CACHE[key]
    return None


def _set_cached(query: str, result: str):
    """Cache a search result."""
    key = query.lower().strip()
    _SEARCH_CACHE[key] = (time.time(), result)


# ================================================================================
# WEB SEARCH
# ================================================================================

def execute_web_search(query: str) -> str:
    """Execute a web search with caching + rate limiting."""
    if not query or not query.strip():
        return json.dumps({
            "success": False,
            "error": "Please provide a search query."
        })

    q = query.strip()

    with _SEARCH_LOCK:
        cached = _get_cached(q)
        if cached is not None:
            return cached
        if not _search_budget_ok():
            if cached is not None:
                return cached
            return json.dumps({
                "success": False,
                "error": "[RATE LIMIT] You've run out of web searches for the moment. Please wait ~60 seconds and try again."
            })
        _record_search()

    results = []
    used_provider = None

    # Try ddgs library first
    try:
        from ddgs import DDGS
        used_provider = "ddgs.DDGS"
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(q, region="ca-en", max_results=SEARCH_RESULTS_PER_QUERY)):
                title = (r.get("title") or "").strip() or "Untitled"
                href = (r.get("href") or r.get("link") or "").strip()
                snippet = (r.get("body") or r.get("description") or "").strip()
                if href:
                    results.append({
                        "position": i + 1,
                        "title": title,
                        "url": href,
                        "snippet": snippet
                    })
        if not results:
            used_provider = None
    except Exception:
        used_provider = None

    # Fallback to HTML endpoint
    if not results:
        try:
            from bs4 import BeautifulSoup
            used_provider = "duckduckgo html"
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; BlueBot/1.0)"})
            if resp.status_code == 429:
                cached = _get_cached(q)
                if cached is not None:
                    return cached
                return json.dumps({
                    "success": False,
                    "error": "[PROVIDER LIMIT] The search provider is rate-limiting right now. Please retry in a minute."
                })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".result__body")
            for i, item in enumerate(items[:SEARCH_RESULTS_PER_QUERY]):
                a = item.select_one("a.result__a")
                if not a:
                    continue
                title = a.get_text(strip=True) or "Untitled"
                href = a.get("href", "")
                snippet_el = item.select_one(".result__snippet")
                snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
                if href:
                    results.append({
                        "position": i + 1,
                        "title": title,
                        "url": href,
                        "snippet": snippet
                    })
        except Exception as e:
            msg = json.dumps({
                "success": False,
                "error": f"Web search failed: {e.__class__.__name__}: {e}"
            })
            _set_cached(q, msg)
            return msg

    if not results:
        msg = json.dumps({
            "success": False,
            "query": q,
            "error": "No results found."
        })
        _set_cached(q, msg)
        return msg

    payload = json.dumps({
        "success": True,
        "query": q,
        "provider": used_provider or "unknown",
        "results": results,
        "result_count": len(results)
    }, ensure_ascii=False)

    _set_cached(q, payload)
    return payload


# ================================================================================
# WEATHER
# ================================================================================

def get_weather_data(location: str) -> str:
    """Get weather data for a location."""
    try:
        url = f"https://wttr.in/{location}?format=j1"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            current = data['current_condition'][0]
            temp_c = current['temp_C']
            temp_f = current['temp_F']
            weather_desc = current['weatherDesc'][0]['value']
            humidity = current['humidity']
            wind_speed = current['windspeedKmph']
            location_name = data['nearest_area'][0]['areaName'][0]['value']
            return f"Weather in {location_name}: {weather_desc}, {temp_c}°C ({temp_f}°F), Humidity: {humidity}%, Wind: {wind_speed} km/h"
        return f"Could not get weather for '{location}'"
    except Exception as e:
        return f"Weather error: {str(e)}"


# ================================================================================
# BROWSE WEBSITE
# ================================================================================

# HTML cleaning patterns
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_MULTI_WS = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL = re.compile(r"\n{3,}")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_LINK_RE = re.compile(r'(?i)href=["\'](.*?)["\']')


def _clean_html_to_text(html_str: str, max_chars: int = 8000) -> str:
    """Clean HTML and convert to readable text."""
    if not isinstance(html_str, str):
        html_str = str(html_str or "")
    s = _SCRIPT_STYLE.sub(" ", html_str)
    title = None
    mt = _TITLE_RE.search(s)
    if mt:
        title = _html.unescape(mt.group(1).strip())
    s = _TAGS.sub("\n", s)
    s = _html.unescape(s)
    s = _MULTI_WS.sub(" ", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _MULTI_NL.sub("\n\n", s)
    s = s.strip()
    if max_chars and len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    if title and title not in s[:500]:
        s = f"{title}\n\n{s}"
    return s


def _extract_links(html_str: str, base_url: str, max_links: int = 40) -> List[str]:
    """Extract links from HTML."""
    out = []
    seen = set()
    for m in _LINK_RE.finditer(html_str or ""):
        href = m.group(1).strip()
        if not href:
            continue
        href_abs = urljoin(base_url, href)
        if not href_abs.startswith(("http://", "https://")):
            continue
        if href_abs in seen:
            continue
        seen.add(href_abs)
        out.append(href_abs)
        if len(out) >= max_links:
            break
    return out


def _assert_public_http_url(url: str) -> str:
    """Validate an outbound browse URL and block local/private networks."""
    return assert_public_http_url(url)


def _safe_fetch_url(url: str, headers: Optional[dict] = None, timeout: int = 15, max_bytes: int = 1_500_000):
    """Safely fetch a URL with size, redirect, and private-network limits."""
    if not isinstance(url, str):
        raise ValueError("url must be a string")
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        raise ValueError("Only http/https URLs are allowed")
    parts = urlsplit(u)
    if not parts.netloc:
        raise ValueError("URL must be absolute")
    req_headers = {
        "User-Agent": "BlueBot/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    if isinstance(headers, dict):
        req_headers.update({str(k): str(v) for k, v in headers.items()})

    redirects = 0
    while True:
        _assert_public_http_url(u)
        resp = requests.get(u, headers=req_headers, timeout=timeout, stream=True, allow_redirects=False)
        if resp.is_redirect or resp.is_permanent_redirect:
            redirects += 1
            if redirects > 5:
                raise ValueError("Too many redirects")
            location = resp.headers.get("Location")
            if not location:
                raise ValueError("Redirect missing Location header")
            u = urljoin(u, location)
            resp.close()
            continue
        break

    resp.raise_for_status()
    content = b""
    for chunk in resp.iter_content(chunk_size=16384):
        if chunk:
            content += chunk
            if len(content) > max_bytes:
                break
    return resp.headers.get("content-type", ""), content


def execute_browse_website(args: dict) -> str:
    """Execute the browse_website tool."""
    url = (args or {}).get("url", "")
    extract = (args or {}).get("extract", "text") or "text"
    max_chars = int((args or {}).get("max_chars", 8000) or 8000)
    include_links = bool((args or {}).get("include_links", True))
    headers = (args or {}).get("headers", None)

    try:
        print(f"   [BROWSE] Fetching URL: {url}")
        ctype, content = _safe_fetch_url(url, headers=headers)
        html_raw = content.decode("utf-8", errors="ignore")

        if extract == "html":
            body = html_raw[:max_chars] + ("…" if len(html_raw) > max_chars else "")
        else:
            body = _clean_html_to_text(html_raw, max_chars=max_chars)

        result = {
            "url": url,
            "content_type": ctype,
            "extract": extract,
            "text": body,
            "success": True
        }
        if include_links:
            result["links"] = _extract_links(html_raw, url, max_links=40)

        print(f"   [BROWSE] Successfully fetched {len(body)} characters from {url}")
        return json.dumps(result, ensure_ascii=False)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout: The website {url} took too long to respond (>15 seconds)."
        print(f"   [ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "url": url, "success": False})

    except requests.exceptions.ConnectionError:
        error_msg = f"Connection Error: Could not connect to {url}. The website may be down or unreachable."
        print(f"   [ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "url": url, "success": False})

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP Error {e.response.status_code}: {url} returned an error."
        print(f"   [ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "url": url, "success": False})

    except ValueError as e:
        error_msg = f"Invalid URL: {str(e)}"
        print(f"   [ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "url": url, "success": False})

    except Exception as e:
        error_msg = f"Unexpected error while browsing {url}: {str(e)}"
        print(f"   [ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "url": url, "success": False})


__all__ = [
    'execute_web_search',
    'get_weather_data',
    'execute_browse_website',
    'SEARCH_MAX_PER_MINUTE',
    'SEARCH_CACHE_TTL_SEC',
    'SEARCH_RESULTS_PER_QUERY',
]
