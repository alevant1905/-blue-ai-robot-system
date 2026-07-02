"""
Blue Robot Scholarly Research Tools
===================================
Serious academic search for Alex's research and teaching, wired to the
Wilfrid Laurier University library.

Design: Blue NEVER stores or uses Alex's Laurier password. Automated logins
can't survive Duo MFA, and the library's database licenses prohibit
credentialed scraping. Instead:

  1. SEARCH runs against sources that need no credentials:
       - Omni, Laurier's Primo VE discovery layer (public guest API) —
         shows what the Laurier collection actually holds.
       - OpenAlex — rich scholarly metadata: abstracts, citation counts,
         open-access links.
       - Crossref — DOI-authoritative metadata (fallback + lookups).
  2. FULL TEXT comes via the library proxy: every result carries a
     https://libproxy.wlu.ca/login?url=… link. Alex clicks it, signs in
     with his own Laurier account, and lands on the licensed full text.
  3. OPEN ACCESS PDFs are resolved through Unpaywall where a legal free
     copy exists, so many papers need no sign-in at all.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional
from urllib.parse import quote, quote_plus

import requests

# ================================================================================
# CONFIGURATION
# ================================================================================

# Laurier library proxy prefix for licensed full text (user signs in themselves).
WLU_PROXY_PREFIX = os.getenv("WLU_PROXY_PREFIX", "https://libproxy.wlu.ca/login?url=")

# Omni — Laurier's discovery system (Ex Libris Primo VE, shared across OCUL).
OMNI_HOST = os.getenv("OMNI_HOST", "ocul-wlu.primo.exlibrisgroup.com")
OMNI_INST = os.getenv("OMNI_INST", "01OCUL_WLU")
OMNI_VID = os.getenv("OMNI_VID", "01OCUL_WLU:WLU_DEF")
OMNI_TAB = os.getenv("OMNI_TAB", "Everything")
OMNI_SCOPE = os.getenv("OMNI_SCOPE", "MyInst_and_CI")

# Polite-pool identification for OpenAlex/Crossref/Unpaywall (they ask for a
# contact email in exchange for faster, more reliable service).
SCHOLAR_CONTACT_EMAIL = (
    os.getenv("UNPAYWALL_EMAIL")
    or os.getenv("GMAIL_USER_EMAIL")
    or "blue-robot@example.com"
)

SCHOLAR_MAX_PER_MINUTE = int(os.getenv("SCHOLAR_MAX_PER_MINUTE", "10"))
SCHOLAR_CACHE_TTL_SEC = int(os.getenv("SCHOLAR_CACHE_TTL_SEC", "21600"))
SCHOLAR_RESULTS_PER_QUERY = int(os.getenv("SCHOLAR_RESULTS_PER_QUERY", "6"))
SCHOLAR_TIMEOUT_SEC = int(os.getenv("SCHOLAR_TIMEOUT_SEC", "12"))

_REQUEST_HEADERS = {
    "User-Agent": f"BlueBot/1.0 (personal research assistant; mailto:{SCHOLAR_CONTACT_EMAIL})",
    "Accept": "application/json",
}
# Ex Libris fronts Omni with bot filtering that rejects obvious scripts, so
# the Omni calls present as a browser.
_OMNI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"https://{OMNI_HOST}/discovery/search?vid={quote(OMNI_VID)}",
}

_CALL_TIMESTAMPS: deque = deque(maxlen=64)
_CACHE: Dict[str, tuple] = {}
_LOCK = threading.Lock()


# ================================================================================
# RATE LIMITING & CACHING (same pattern as blue.tools.web)
# ================================================================================

def _budget_ok() -> bool:
    now = time.time()
    cutoff = now - 60
    while _CALL_TIMESTAMPS and _CALL_TIMESTAMPS[0] < cutoff:
        _CALL_TIMESTAMPS.popleft()
    return len(_CALL_TIMESTAMPS) < SCHOLAR_MAX_PER_MINUTE


def _record_call():
    _CALL_TIMESTAMPS.append(time.time())


def _get_cached(key: str) -> Optional[str]:
    key = key.lower().strip()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < SCHOLAR_CACHE_TTL_SEC:
            return val
        del _CACHE[key]
    return None


def _set_cached(key: str, result: str):
    _CACHE[key.lower().strip()] = (time.time(), result)


# ================================================================================
# LINK BUILDERS
# ================================================================================

def proxy_link(url: str) -> Optional[str]:
    """Wrap a publisher/DOI URL in the Laurier off-campus proxy prefix."""
    if not url:
        return None
    return f"{WLU_PROXY_PREFIX}{url}"


def _doi_url(doi: str) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip()
    if doi.startswith("http"):
        return doi
    return f"https://doi.org/{doi}"


def _clean_doi(doi: str) -> Optional[str]:
    """Normalize a DOI to its bare form (10.xxxx/...)."""
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi or None


def omni_search_url(query: str) -> str:
    """Human-clickable Omni search page for this query (always works)."""
    return (
        f"https://{OMNI_HOST}/discovery/search"
        f"?query=any,contains,{quote_plus(query)}"
        f"&tab={quote(OMNI_TAB)}&search_scope={quote(OMNI_SCOPE)}"
        f"&vid={quote(OMNI_VID)}"
    )


# ================================================================================
# SOURCE: OPENALEX
# ================================================================================

def _reconstruct_abstract(inverted: Optional[dict], max_chars: int = 700) -> Optional[str]:
    """OpenAlex ships abstracts as an inverted index; rebuild the text."""
    if not inverted:
        return None
    try:
        positions: List[tuple] = []
        for word, idxs in inverted.items():
            for i in idxs:
                positions.append((i, word))
        positions.sort()
        text = " ".join(w for _, w in positions)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        return text or None
    except Exception:
        return None


def _normalize_openalex(work: dict, position: int) -> dict:
    doi = _clean_doi(work.get("doi") or "")
    authors = [
        (a.get("author") or {}).get("display_name")
        for a in (work.get("authorships") or [])[:6]
        if (a.get("author") or {}).get("display_name")
    ]
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    oa = work.get("open_access") or {}
    landing = _doi_url(doi) or (work.get("primary_location") or {}).get("landing_page_url")
    return {
        "position": position,
        "title": work.get("display_name") or "Untitled",
        "authors": authors,
        "year": work.get("publication_year"),
        "venue": venue,
        "type": work.get("type"),
        "doi": doi,
        "cited_by": work.get("cited_by_count"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "open_access_pdf": oa.get("oa_url") if oa.get("is_oa") else None,
        "laurier_access": proxy_link(landing),
        "source": "openalex",
    }


def _openalex_search(query: str, limit: int, year_from: Optional[int] = None,
                     year_to: Optional[int] = None, open_access_only: bool = False) -> List[dict]:
    filters = []
    if year_from:
        filters.append(f"from_publication_date:{int(year_from)}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{int(year_to)}-12-31")
    if open_access_only:
        filters.append("is_oa:true")
    params: Dict[str, Any] = {
        "search": query,
        "per-page": limit,
        "mailto": SCHOLAR_CONTACT_EMAIL,
    }
    if filters:
        params["filter"] = ",".join(filters)
    resp = requests.get("https://api.openalex.org/works", params=params,
                        headers=_REQUEST_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC)
    resp.raise_for_status()
    works = (resp.json() or {}).get("results") or []
    return [_normalize_openalex(w, i + 1) for i, w in enumerate(works[:limit])]


def _openalex_by_doi(doi: str) -> Optional[dict]:
    resp = requests.get(
        f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='/')}",
        params={"mailto": SCHOLAR_CONTACT_EMAIL},
        headers=_REQUEST_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ================================================================================
# SOURCE: CROSSREF
# ================================================================================

def _normalize_crossref(item: dict, position: int) -> dict:
    doi = _clean_doi(item.get("DOI") or "")
    title_list = item.get("title") or []
    authors = []
    for a in (item.get("author") or [])[:6]:
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p)
        if name:
            authors.append(name)
    year = None
    issued = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    if issued and issued[0]:
        year = issued[0]
    container = (item.get("container-title") or [None])[0]
    abstract = item.get("abstract")
    if abstract:
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()[:700]
    return {
        "position": position,
        "title": title_list[0] if title_list else "Untitled",
        "authors": authors,
        "year": year,
        "venue": container,
        "type": item.get("type"),
        "doi": doi,
        "cited_by": item.get("is-referenced-by-count"),
        "abstract": abstract or None,
        "open_access_pdf": None,
        "laurier_access": proxy_link(_doi_url(doi)),
        "source": "crossref",
    }


def _crossref_search(query: str, limit: int) -> List[dict]:
    resp = requests.get(
        "https://api.crossref.org/works",
        params={
            "query.bibliographic": query,
            "rows": limit,
            "mailto": SCHOLAR_CONTACT_EMAIL,
        },
        headers=_REQUEST_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    items = ((resp.json() or {}).get("message") or {}).get("items") or []
    return [_normalize_crossref(it, i + 1) for i, it in enumerate(items[:limit])]


def _crossref_by_doi(doi: str) -> Optional[dict]:
    resp = requests.get(
        f"https://api.crossref.org/works/{quote(doi, safe='/')}",
        params={"mailto": SCHOLAR_CONTACT_EMAIL},
        headers=_REQUEST_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return ((resp.json() or {}).get("message")) or None


# ================================================================================
# SOURCE: OMNI (Laurier's Primo VE discovery layer)
# ================================================================================

def _omni_guest_jwt(session: requests.Session) -> Optional[str]:
    """The public Omni UI authenticates as 'guest' with a JWT; fetch one."""
    resp = session.get(
        f"https://{OMNI_HOST}/primaws/rest/pub/institution/{OMNI_INST}/guestJwt",
        headers=_OMNI_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    token = resp.text.strip().strip('"')
    return token or None


def _first(val) -> Optional[str]:
    """Primo PNX fields are usually lists; take the first non-empty entry."""
    if isinstance(val, list):
        for v in val:
            if v:
                return str(v)
        return None
    return str(val) if val else None


def _normalize_omni(doc: dict, position: int) -> dict:
    pnx = doc.get("pnx") or {}
    display = pnx.get("display") or {}
    addata = pnx.get("addata") or {}
    control = pnx.get("control") or {}
    record_id = _first(control.get("recordid"))
    context = doc.get("context") or "L"
    permalink = None
    if record_id:
        permalink = (
            f"https://{OMNI_HOST}/discovery/fulldisplay"
            f"?docid={quote(record_id)}&context={quote(context)}&vid={quote(OMNI_VID)}"
        )
    doi = _clean_doi(_first(addata.get("doi")) or "")
    creators = display.get("creator") or display.get("contributor") or []
    if isinstance(creators, str):
        creators = [creators]
    authors = [re.sub(r"\$\$Q.*$", "", c).strip() for c in creators[:6] if c]
    year = None
    m = re.search(r"\d{4}", _first(display.get("creationdate")) or "")
    if m:
        year = int(m.group(0))
    return {
        "position": position,
        "title": re.sub(r"\s+", " ", _first(display.get("title")) or "Untitled"),
        "authors": authors,
        "year": year,
        "venue": _first(display.get("ispartof")),
        "type": _first(display.get("type")),
        "doi": doi,
        "cited_by": None,
        "abstract": (_first(display.get("description")) or "")[:700] or None,
        "open_access_pdf": None,
        "laurier_access": proxy_link(_doi_url(doi)) if doi else permalink,
        "omni_record": permalink,
        "source": "omni",
    }


def _omni_search(query: str, limit: int) -> List[dict]:
    """Guest search of Laurier's Omni. Raises on failure — caller degrades."""
    session = requests.Session()
    jwt = _omni_guest_jwt(session)
    headers = dict(_OMNI_HEADERS)
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    params = {
        "acTriggered": "false",
        "blendFacetsSeparately": "false",
        "disableCache": "false",
        "getMore": "0",
        "inst": OMNI_INST,
        "lang": "en",
        "limit": limit,
        "mode": "advanced",
        "newspapersActive": "false",
        "newspapersSearch": "false",
        "offset": "0",
        "pcAvailability": "false",
        "q": f"any,contains,{query}",
        "qExclude": "",
        "qInclude": "",
        "refEntryActive": "false",
        "rtaLinks": "true",
        "scope": OMNI_SCOPE,
        "skipDelivery": "Y",
        "sort": "rank",
        "tab": OMNI_TAB,
        "vid": OMNI_VID,
    }
    resp = session.get(
        f"https://{OMNI_HOST}/primaws/rest/pub/pnxs",
        params=params, headers=headers, timeout=SCHOLAR_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    docs = (resp.json() or {}).get("docs") or []
    return [_normalize_omni(d, i + 1) for i, d in enumerate(docs[:limit])]


# ================================================================================
# SOURCE: UNPAYWALL (legal open-access copies)
# ================================================================================

def _unpaywall_pdf(doi: str) -> Optional[str]:
    try:
        resp = requests.get(
            f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}",
            params={"email": SCHOLAR_CONTACT_EMAIL},
            headers=_REQUEST_HEADERS, timeout=SCHOLAR_TIMEOUT_SEC,
        )
        if resp.status_code != 200:
            return None
        best = (resp.json() or {}).get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except Exception:
        return None


# ================================================================================
# MERGING
# ================================================================================

def _dedupe_key(r: dict) -> str:
    if r.get("doi"):
        return f"doi:{r['doi'].lower()}"
    title = re.sub(r"[^a-z0-9]+", "", (r.get("title") or "").lower())
    return f"title:{title[:80]}"


def _merge_results(primary: List[dict], secondary: List[dict], limit: int) -> List[dict]:
    """Interleave-free merge: primary first, then unseen secondary results."""
    merged: List[dict] = []
    seen = set()
    for r in primary + secondary:
        key = _dedupe_key(r)
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
        if len(merged) >= limit:
            break
    for i, r in enumerate(merged):
        r["position"] = i + 1
    return merged


# ================================================================================
# TOOL: search_scholar
# ================================================================================

def execute_scholar_search(args: dict) -> str:
    """Search academic journals & the Laurier library. Returns JSON string."""
    args = args or {}
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({
            "success": False,
            "error": "Please provide a search topic, e.g. 'activity theory and disability studies'."
        })

    limit = int(args.get("limit") or SCHOLAR_RESULTS_PER_QUERY)
    limit = max(1, min(limit, 15))
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    open_access_only = bool(args.get("open_access_only"))

    cache_key = f"scholar|{query}|{limit}|{year_from}|{year_to}|{open_access_only}"
    with _LOCK:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
        if not _budget_ok():
            return json.dumps({
                "success": False,
                "error": "[RATE LIMIT] Too many scholarly searches this minute. Wait ~60 seconds and try again."
            })
        _record_call()

    sources_used: List[str] = []
    notes: List[str] = []

    # Primary: OpenAlex (abstracts, citation counts, OA links).
    openalex_results: List[dict] = []
    try:
        openalex_results = _openalex_search(query, limit, year_from, year_to, open_access_only)
        sources_used.append("openalex")
    except Exception as e:
        notes.append(f"OpenAlex unavailable ({e.__class__.__name__}).")

    # Fallback when OpenAlex is down/empty: Crossref.
    crossref_results: List[dict] = []
    if not openalex_results:
        try:
            crossref_results = _crossref_search(query, limit)
            sources_used.append("crossref")
        except Exception as e:
            notes.append(f"Crossref unavailable ({e.__class__.__name__}).")

    # Laurier holdings via Omni. Year/OA filters don't apply here; when the
    # user asked for those, Omni results would pollute the list, so skip it.
    omni_results: List[dict] = []
    if not (year_from or year_to or open_access_only):
        try:
            omni_results = _omni_search(query, min(limit, 5))
            sources_used.append("omni")
        except Exception as e:
            notes.append(
                f"Omni API unreachable ({e.__class__.__name__}) — "
                "use the omni_search_url link to search the Laurier catalogue directly."
            )

    results = _merge_results(openalex_results or crossref_results, omni_results, limit)

    if not results:
        payload = json.dumps({
            "success": False,
            "query": query,
            "error": "No scholarly results found." if sources_used else
                     "All scholarly search sources are unreachable right now.",
            "notes": notes,
            "omni_search_url": omni_search_url(query),
        }, ensure_ascii=False)
        _set_cached(cache_key, payload)
        return payload

    payload = json.dumps({
        "success": True,
        "query": query,
        "sources_used": sources_used,
        "result_count": len(results),
        "results": results,
        "omni_search_url": omni_search_url(query),
        "notes": notes,
        "_instruction": (
            "Present these as a numbered scholarly reading list: Authors (Year), "
            "Title, Journal/venue, then one sentence from the abstract. For each "
            "item ALWAYS give the 'laurier_access' link (full text — Alex signs in "
            "with his Laurier account) and the 'open_access_pdf' link when present "
            "(free legal PDF, no sign-in). Mention citation counts for impact. "
            "Offer the omni_search_url for browsing more results in the Laurier library."
        ),
    }, ensure_ascii=False)
    _set_cached(cache_key, payload)
    return payload


# ================================================================================
# TOOL: get_paper
# ================================================================================

def _format_apa(title: str, authors: List[str], year, venue: Optional[str],
                volume: Optional[str] = None, issue: Optional[str] = None,
                pages: Optional[str] = None, doi: Optional[str] = None) -> str:
    if authors:
        if len(authors) == 1:
            author_str = authors[0]
        elif len(authors) <= 7:
            author_str = ", ".join(authors[:-1]) + f", & {authors[-1]}"
        else:
            author_str = ", ".join(authors[:6]) + ", … " + authors[-1]
    else:
        author_str = "[No author]"
    parts = [f"{author_str} ({year or 'n.d.'}). {title}."]
    if venue:
        vi = venue
        if volume:
            vi += f", {volume}"
            if issue:
                vi += f"({issue})"
        if pages:
            vi += f", {pages}"
        parts.append(f"{vi}.")
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return " ".join(parts)


def execute_get_paper(args: dict) -> str:
    """Look up one paper by DOI or title: full metadata + access links."""
    args = args or {}
    doi = _clean_doi(args.get("doi") or "")
    title_query = (args.get("title") or "").strip()

    if not doi and not title_query:
        return json.dumps({
            "success": False,
            "error": "Provide a DOI or a paper title to look up."
        })

    cache_key = f"paper|{doi or title_query}"
    with _LOCK:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
        if not _budget_ok():
            return json.dumps({
                "success": False,
                "error": "[RATE LIMIT] Too many scholarly lookups this minute. Wait ~60 seconds and try again."
            })
        _record_call()

    # Resolve a title to a DOI via Crossref.
    cr = None
    if not doi:
        try:
            hits = _crossref_search(title_query, 1)
            if hits and hits[0].get("doi"):
                doi = hits[0]["doi"]
        except Exception:
            pass
        if not doi:
            return json.dumps({
                "success": False,
                "error": f"Couldn't resolve a DOI for '{title_query}'. Try search_scholar instead.",
                "omni_search_url": omni_search_url(title_query),
            }, ensure_ascii=False)

    try:
        cr = _crossref_by_doi(doi)
    except Exception:
        cr = None
    oa_work = None
    try:
        oa_work = _openalex_by_doi(doi)
    except Exception:
        oa_work = None

    if not cr and not oa_work:
        return json.dumps({
            "success": False,
            "error": f"No metadata found for DOI {doi}.",
            "laurier_access": proxy_link(_doi_url(doi)),
        }, ensure_ascii=False)

    # Prefer Crossref for bibliographic fields, OpenAlex for abstract/impact.
    norm_cr = _normalize_crossref(cr, 1) if cr else {}
    norm_oa = _normalize_openalex(oa_work, 1) if oa_work else {}
    title = norm_cr.get("title") or norm_oa.get("title") or "Untitled"
    authors = norm_cr.get("authors") or norm_oa.get("authors") or []
    year = norm_cr.get("year") or norm_oa.get("year")
    venue = norm_cr.get("venue") or norm_oa.get("venue")
    abstract = norm_oa.get("abstract") or norm_cr.get("abstract")
    cited_by = norm_oa.get("cited_by") if norm_oa.get("cited_by") is not None else norm_cr.get("cited_by")

    volume = (cr or {}).get("volume")
    issue = (cr or {}).get("issue")
    pages = (cr or {}).get("page")

    open_access_pdf = norm_oa.get("open_access_pdf") or _unpaywall_pdf(doi)

    payload = json.dumps({
        "success": True,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "type": norm_cr.get("type") or norm_oa.get("type"),
        "cited_by": cited_by,
        "abstract": abstract,
        "open_access_pdf": open_access_pdf,
        "laurier_access": proxy_link(_doi_url(doi)),
        "publisher_url": _doi_url(doi),
        "apa_citation": _format_apa(title, authors, year, venue, volume, issue, pages, doi),
        "_instruction": (
            "Summarize this paper's details naturally. Give the abstract's gist, "
            "the APA citation, and the access links: 'open_access_pdf' if present "
            "(free legal PDF), otherwise 'laurier_access' (full text after Alex "
            "signs in with his Laurier account)."
        ),
    }, ensure_ascii=False)
    _set_cached(cache_key, payload)
    return payload


__all__ = [
    'execute_scholar_search',
    'execute_get_paper',
    'proxy_link',
    'omni_search_url',
    'WLU_PROXY_PREFIX',
    'OMNI_HOST',
    'OMNI_VID',
    'SCHOLAR_MAX_PER_MINUTE',
    'SCHOLAR_CACHE_TTL_SEC',
    'SCHOLAR_RESULTS_PER_QUERY',
]
