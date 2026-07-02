"""
Blue Robot Scholarly Research Tools
===================================
Serious academic search for Alex's research and teaching, wired to the
Wilfrid Laurier University library.

How access works:

  1. SEARCH runs against sources that need no credentials:
       - Omni, Laurier's Primo VE discovery layer (public guest API) —
         shows what the Laurier collection actually holds.
       - OpenAlex — rich scholarly metadata: abstracts, citation counts,
         open-access links.
       - Crossref — DOI-authoritative metadata (fallback + lookups).
  2. FULL TEXT (read_paper) is fetched one article at a time, on demand:
       - a legal open-access copy via Unpaywall first (no sign-in), then
       - through the Laurier library proxy (libproxy.wlu.ca) using Alex's
         own library credentials, so Blue can actually read and
         synthesize licensed articles.
  3. CREDENTIALS live ONLY on this machine: wlu_credentials.json in the
     project root (gitignored, like gmail_credentials.json) or env vars.
     If the proxy login is fronted by single-sign-on/Duo MFA, a browser
     session cookie can be pasted in instead of a password.

Fair-use guardrails, deliberately: read_paper fetches ONE article per
call, everything is rate-limited and cached, and there is no bulk/crawl
mode — this is Alex's personal, on-demand research access, exactly what
the library account is for. Every result still carries the proxy link
for reading in the browser.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, quote_plus, urljoin, urlsplit

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
            "Offer the omni_search_url for browsing more results in the Laurier "
            "library, and offer to READ any of these in full (read_paper tool "
            "with the result's doi) to summarize or synthesize them."
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


# ================================================================================
# LAURIER LIBRARY PROXY SESSION (EZproxy)
# ================================================================================

# https://libproxy.wlu.ca/login — derived from the prefix so one env var
# retargets everything if the library ever moves hosts.
_PROXY_LOGIN_URL = WLU_PROXY_PREFIX.split("?", 1)[0]
_PROXY_HOST = urlsplit(_PROXY_LOGIN_URL).netloc

# Local credential store, gitignored like gmail_credentials.json.
# Shape: {"user": "...", "pass": "...", "cookie": "..."} — any subset.
_CRED_FILE = Path(__file__).resolve().parents[2] / "wlu_credentials.json"

_PROXY_SESSION_TTL = 90 * 60  # EZproxy sessions idle out; re-login after this
_proxy_session: Optional[requests.Session] = None
_proxy_session_ts = 0.0

# Hosts/markers that mean the login page handed us off to campus SSO —
# a password POST can't get through that (Duo MFA), so we bail with guidance.
_SSO_MARKER_RE = re.compile(
    r"microsoftonline|duosecurity|duo\.com|okta|adfs|shibboleth|/idp/|"
    r"login\.wlu\.ca|cas\.|onelogin|azuread", re.I)


class LibraryAuthError(Exception):
    """code is one of: no-creds, sso, bad-creds, login-failed."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _load_credentials() -> dict:
    creds: Dict[str, str] = {}
    try:
        with open(_CRED_FILE, encoding="utf-8") as f:
            data = json.load(f) or {}
        for k in ("user", "pass", "cookie"):
            if data.get(k):
                creds[k] = str(data[k]).strip()
    except Exception:
        pass
    for env, key in (("WLU_LIBRARY_USER", "user"),
                     ("WLU_LIBRARY_PASS", "pass"),
                     ("WLU_PROXY_COOKIE", "cookie")):
        v = os.getenv(env)
        if v:
            creds[key] = v.strip()
    return creds


def library_account_status() -> str:
    creds = _load_credentials()
    if creds.get("cookie"):
        return "configured (browser session cookie)"
    if creds.get("user") and creds.get("pass"):
        return "configured (username/password)"
    return "not configured"


def _auth_guidance(code: str) -> str:
    setup = (
        f"Put your Laurier library sign-in in {_CRED_FILE.name} in the Blue "
        'project folder (it is gitignored, never leaves this machine): '
        '{"user": "your Laurier username", "pass": "your password"}. '
        "Env vars WLU_LIBRARY_USER / WLU_LIBRARY_PASS also work."
    )
    cookie_help = (
        f"Sign in once at {_PROXY_LOGIN_URL} in your browser, copy the "
        "'ezproxy' cookie value (DevTools > Application > Cookies), and add "
        f'it to {_CRED_FILE.name} as {{"cookie": "..."}} or set '
        "WLU_PROXY_COOKIE. Blue will reuse that session."
    )
    if code == "no-creds":
        return f"No Laurier library credentials are set up yet. {setup}"
    if code == "sso":
        return (
            "The Laurier proxy login redirects to campus single-sign-on "
            f"(Duo MFA), which a password alone can't get through. {cookie_help}"
        )
    if code == "bad-creds":
        return (
            "The Laurier proxy rejected the stored sign-in. Double-check the "
            f"username/password in {_CRED_FILE.name} (alumni/community "
            "accounts use library barcode + PIN). If your login now goes "
            f"through Duo, use the cookie method instead: {cookie_help}"
        )
    return f"Couldn't sign in to the Laurier library proxy. {cookie_help}"


def _parse_login_form(html: str) -> Tuple[str, Dict[str, str], Optional[str], Optional[str]]:
    """Return (action, hidden_fields, user_field_name, pass_field_name)."""
    forms = re.findall(r"(?is)<form\b[^>]*>.*?</form>", html or "")
    # Prefer the form that actually has a password box.
    forms.sort(key=lambda f: ("password" not in f.lower()))
    if not forms:
        return "", {}, None, None
    form = forms[0]
    m = re.search(r'(?i)action\s*=\s*["\']([^"\']*)["\']', form)
    action = m.group(1) if m else ""
    fields: Dict[str, str] = {}
    user_field = pass_field = None
    for tag in re.findall(r"(?i)<input\b[^>]*>", form):
        attrs = dict(re.findall(r'(\w+)\s*=\s*["\']([^"\']*)["\']', tag))
        name = attrs.get("name")
        if not name:
            continue
        itype = (attrs.get("type") or "text").lower()
        if itype == "password" or re.search(r"pass|pin", name, re.I):
            pass_field = pass_field or name
        elif re.search(r"^user|user(name)?$|login|barcode|^id$", name, re.I) and itype in ("text", "email"):
            user_field = user_field or name
        elif itype in ("hidden", "submit"):
            fields[name] = attrs.get("value", "")
    return action, fields, user_field, pass_field


def _new_proxy_session() -> requests.Session:
    """Log in to the Laurier EZproxy and return an authenticated session."""
    creds = _load_credentials()
    session = requests.Session()
    session.headers.update({"User-Agent": _OMNI_HEADERS["User-Agent"]})

    # A pasted browser cookie skips login entirely (and survives Duo/SSO).
    if creds.get("cookie"):
        raw = creds["cookie"]
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                name, val = part.split("=", 1)
                session.cookies.set(name.strip(), val.strip(), domain=_PROXY_HOST)
            else:
                session.cookies.set("ezproxy", part, domain=_PROXY_HOST)
        return session

    if not (creds.get("user") and creds.get("pass")):
        raise LibraryAuthError("no-creds")

    resp = session.get(_PROXY_LOGIN_URL, timeout=SCHOLAR_TIMEOUT_SEC, allow_redirects=True)
    if _SSO_MARKER_RE.search(resp.url) or _SSO_MARKER_RE.search(resp.text[:8000] or ""):
        raise LibraryAuthError("sso", resp.url)

    action, fields, user_field, pass_field = _parse_login_form(resp.text)
    fields[user_field or "user"] = creds["user"]
    fields[pass_field or "pass"] = creds["pass"]
    post_url = urljoin(resp.url, action or _PROXY_LOGIN_URL)
    resp2 = session.post(post_url, data=fields, timeout=SCHOLAR_TIMEOUT_SEC, allow_redirects=True)

    if any(c.name.lower().startswith("ezproxy") for c in session.cookies):
        return session
    if _SSO_MARKER_RE.search(resp2.url):
        raise LibraryAuthError("sso", resp2.url)
    if resp2.status_code in (401, 403) or re.search(
            r"(?i)invalid|incorrect|denied|failed", resp2.text[:4000] or ""):
        raise LibraryAuthError("bad-creds")
    raise LibraryAuthError("login-failed", f"HTTP {resp2.status_code}")


def _get_proxy_session(force_new: bool = False) -> requests.Session:
    global _proxy_session, _proxy_session_ts
    with _LOCK:
        if (not force_new and _proxy_session is not None
                and time.time() - _proxy_session_ts < _PROXY_SESSION_TTL):
            return _proxy_session
    session = _new_proxy_session()
    with _LOCK:
        _proxy_session = session
        _proxy_session_ts = time.time()
    return session


# ================================================================================
# FULL-TEXT RETRIEVAL
# ================================================================================

_MAX_FETCH_BYTES = 20_000_000  # PDFs of scanned book chapters get big
_READ_MAX_CHARS_DEFAULT = int(os.getenv("SCHOLAR_READ_MAX_CHARS", "12000"))

# <meta name="citation_pdf_url" content="..."> — the near-universal way
# publishers advertise the PDF (it's what Google Scholar indexes).
_CITATION_PDF_RES = [
    re.compile(r'(?is)<meta[^>]+name\s*=\s*["\']citation_pdf_url["\'][^>]*content\s*=\s*["\']([^"\']+)["\']'),
    re.compile(r'(?is)<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']citation_pdf_url["\']'),
]

_PAYWALL_MARKERS = [
    "purchase access", "buy this article", "get access", "access options",
    "institutional login", "log in via your institution", "sign in to continue",
    "purchase pdf", "rent this article", "add to cart",
]


def _bounded_get(getter, url: str, timeout: int = 30,
                 max_bytes: int = _MAX_FETCH_BYTES) -> Tuple[str, str, bytes]:
    """GET with a byte cap. Returns (final_url, content_type, body)."""
    resp = getter(url, timeout=timeout, stream=True, allow_redirects=True)
    resp.raise_for_status()
    content = b""
    for chunk in resp.iter_content(chunk_size=65536):
        if chunk:
            content += chunk
            if len(content) > max_bytes:
                break
    return resp.url, (resp.headers.get("content-type") or ""), content


def _pdf_to_text(data: bytes, max_chars: int) -> Optional[str]:
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        total = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            pages.append(t)
            total += len(t)
            if total >= max_chars * 3:  # a little slack, trimmed later
                break
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(pages)).strip()
        return text or None
    except Exception:
        return None


def _looks_like_pdf(ctype: str, body: bytes) -> bool:
    return "pdf" in (ctype or "").lower() or body[:5] == b"%PDF-"


def _extract_fulltext(getter, url: str, max_chars: int) -> Optional[dict]:
    """Fetch url and pull readable article text out of PDF or HTML.

    Returns {"text", "final_url", "format", "pdf_bytes"?} or None.
    """
    final_url, ctype, body = _bounded_get(getter, url)

    if _looks_like_pdf(ctype, body):
        text = _pdf_to_text(body, max_chars)
        if text:
            return {"text": text, "final_url": final_url, "format": "pdf",
                    "pdf_bytes": body}
        return None

    html = body.decode("utf-8", errors="ignore")

    # Landing page? Hunt for the advertised PDF and fetch that instead.
    for pat in _CITATION_PDF_RES:
        m = pat.search(html)
        if m:
            pdf_url = urljoin(final_url, m.group(1))
            try:
                pdf_final, pdf_ctype, pdf_body = _bounded_get(getter, pdf_url)
                if _looks_like_pdf(pdf_ctype, pdf_body):
                    text = _pdf_to_text(pdf_body, max_chars)
                    if text:
                        return {"text": text, "final_url": pdf_final,
                                "format": "pdf", "pdf_bytes": pdf_body}
            except Exception:
                pass
            break

    # Fall back to the page's own text (many journals serve full HTML).
    from .web import _clean_html_to_text
    text = _clean_html_to_text(html, max_chars=max_chars)
    if text and len(text) > 200:
        return {"text": text, "final_url": final_url, "format": "html"}
    return None


def _save_to_library(title: str, doi: Optional[str], fulltext: dict) -> Optional[str]:
    """Drop the fetched article into Blue's document library under Papers/."""
    try:
        from .documents import DOCUMENTS_FOLDER, ensure_unique_path
        papers_dir = os.path.join(DOCUMENTS_FOLDER, "Papers")
        os.makedirs(papers_dir, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9 _-]+", "", title or (doi or "paper")).strip()
        slug = re.sub(r"\s+", "_", slug)[:80] or "paper"
        if fulltext.get("format") == "pdf" and fulltext.get("pdf_bytes"):
            path = ensure_unique_path(papers_dir, f"{slug}.pdf")
            with open(path, "wb") as f:
                f.write(fulltext["pdf_bytes"])
        else:
            path = ensure_unique_path(papers_dir, f"{slug}.txt")
            with open(path, "w", encoding="utf-8") as f:
                if doi:
                    f.write(f"{title}\nDOI: {doi}\nSource: {fulltext.get('final_url')}\n\n")
                f.write(fulltext["text"])
        # Best-effort immediate semantic indexing; the startup rescan of
        # DOCUMENTS_FOLDER will pick it up regardless.
        try:
            from .rag import index_document
            index_document(path, os.path.basename(path), folder="Papers")
        except Exception:
            pass
        return path
    except Exception:
        return None


def execute_read_paper(args: dict) -> str:
    """Fetch ONE article's full text so Blue can actually read it."""
    args = args or {}
    doi = _clean_doi(args.get("doi") or "")
    url = (args.get("url") or "").strip()
    title_query = (args.get("title") or "").strip()
    max_chars = max(2000, min(int(args.get("max_chars") or _READ_MAX_CHARS_DEFAULT), 60000))
    save = bool(args.get("save"))

    if not doi and not url and not title_query:
        return json.dumps({
            "success": False,
            "error": "Provide a DOI, a URL, or a paper title to read."
        })

    with _LOCK:
        if not _budget_ok():
            return json.dumps({
                "success": False,
                "error": "[RATE LIMIT] Too many scholarly fetches this minute. Wait ~60 seconds and try again."
            })
        _record_call()

    # Resolve a bare title to a DOI so we have something fetchable + citable.
    if not doi and not url:
        try:
            hits = _crossref_search(title_query, 1)
            if hits and hits[0].get("doi"):
                doi = hits[0]["doi"]
        except Exception:
            pass
        if not doi:
            return json.dumps({
                "success": False,
                "error": f"Couldn't resolve '{title_query}' to a DOI. Run search_scholar first and read from a result.",
            }, ensure_ascii=False)

    # Metadata for citing what we read (best-effort).
    title, authors, year, venue = title_query or None, [], None, None
    if doi:
        try:
            cr = _crossref_by_doi(doi)
            if cr:
                norm = _normalize_crossref(cr, 1)
                title = norm.get("title") or title
                authors = norm.get("authors") or []
                year = norm.get("year")
                venue = norm.get("venue")
        except Exception:
            pass

    target = url or _doi_url(doi)
    fulltext = None
    access_route = None
    notes: List[str] = []

    # 1) Legal open-access copy — no sign-in needed at all.
    if doi:
        oa_url = _unpaywall_pdf(doi)
        if oa_url:
            try:
                plain = requests.Session()
                plain.headers.update({"User-Agent": _OMNI_HEADERS["User-Agent"]})
                fulltext = _extract_fulltext(plain.get, oa_url, max_chars)
                if fulltext:
                    access_route = "open_access"
            except Exception:
                notes.append("Open-access copy found but couldn't be fetched.")

    # 2) Licensed copy through the Laurier proxy with Alex's credentials.
    if fulltext is None:
        try:
            session = _get_proxy_session()
            try:
                fulltext = _extract_fulltext(session.get, proxy_link(target), max_chars)
            except requests.exceptions.HTTPError:
                # Session may have idled out server-side; one fresh login retry.
                session = _get_proxy_session(force_new=True)
                fulltext = _extract_fulltext(session.get, proxy_link(target), max_chars)
            if fulltext:
                access_route = "laurier_proxy"
        except LibraryAuthError as e:
            notes.append(_auth_guidance(e.code))
        except Exception as e:
            notes.append(f"Laurier proxy fetch failed ({e.__class__.__name__}).")

    if fulltext is None:
        return json.dumps({
            "success": False,
            "error": "Couldn't retrieve the full text of this article.",
            "title": title,
            "doi": doi,
            "library_account": library_account_status(),
            "notes": notes,
            "laurier_access": proxy_link(target),
            "_instruction": (
                "Tell Alex plainly why the full text couldn't be fetched "
                "(see notes — if credentials are missing or blocked by SSO, "
                "relay the setup steps verbatim) and give the laurier_access "
                "link so he can read it in the browser."
            ),
        }, ensure_ascii=False)

    text = fulltext["text"]
    truncated = len(text) >= max_chars
    text_lower = text[:4000].lower()
    paywall_suspected = (
        access_route == "laurier_proxy"
        and fulltext.get("format") == "html"
        and (len(text) < 1500 or any(m in text_lower for m in _PAYWALL_MARKERS))
    )
    if paywall_suspected:
        notes.append(
            "This looks like it may be only the abstract/paywall page, not "
            "the full article — the proxy session may not be signed in."
        )

    saved_to = None
    if save and not paywall_suspected:
        saved_to = _save_to_library(title or title_query, doi, fulltext)
        if saved_to:
            notes.append(f"Saved into Blue's library: {saved_to}")

    payload = json.dumps({
        "success": True,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi,
        "access_route": access_route,
        "format": fulltext.get("format"),
        "source_url": fulltext.get("final_url"),
        "text_chars": len(text),
        "truncated": truncated,
        "paywall_suspected": paywall_suspected,
        "saved_to": saved_to,
        "notes": notes,
        "text": text,
        "_instruction": (
            "You now have the article's text — do serious scholarly work with "
            "it: lay out the argument, methods, and findings; quote sparingly "
            "and mark quotes clearly; distinguish the authors' claims from "
            "your commentary; and cite it (authors, year, venue, DOI). "
            + ("NOTE: the text was truncated at the character limit; say so "
               "if asked about later sections. " if truncated else "")
            + ("WARNING: this may be just the abstract/paywall page — check "
               "the notes and be upfront about it. " if paywall_suspected else "")
        ),
    }, ensure_ascii=False)
    return payload


__all__ = [
    'execute_scholar_search',
    'execute_get_paper',
    'execute_read_paper',
    'library_account_status',
    'proxy_link',
    'omni_search_url',
    'WLU_PROXY_PREFIX',
    'OMNI_HOST',
    'OMNI_VID',
    'SCHOLAR_MAX_PER_MINUTE',
    'SCHOLAR_CACHE_TTL_SEC',
    'SCHOLAR_RESULTS_PER_QUERY',
]
