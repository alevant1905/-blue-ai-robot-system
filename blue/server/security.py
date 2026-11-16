"""Security helpers shared by Blue's server and web tools."""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlsplit


def assert_public_http_url(url: str) -> str:
    """Validate an outbound URL and block local/private network targets."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed")
    if not parts.hostname:
        raise ValueError("URL must include a host")

    if os.environ.get("BLUE_BROWSE_ALLOW_PRIVATE") == "1":
        return url

    host = parts.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Private/local hosts are blocked")

    try:
        infos = socket.getaddrinfo(
            host,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve URL host: {e}") from e

    for info in infos:
        ip_text = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        # is_global is what catches 100.64.0.0/10: the tailnet, where this
        # machine's own address answers as Blue's server. It is neither
        # "private" nor "reserved" to the ipaddress module.
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
            or not ip.is_global
        ):
            raise ValueError("Private/local network URLs are blocked")
    return url


_MAX_REDIRECTS = 5
_REDIRECT_CODES = frozenset((301, 302, 303, 307, 308))
_CREDENTIAL_HEADERS = frozenset(("authorization", "cookie", "proxy-authorization"))


def fetch_public_url(url: str, headers: Optional[dict] = None, timeout: int = 15,
                     max_bytes: int = 1_500_000) -> Tuple[str, bytes]:
    """GET a page on the public internet. Returns (content_type, body).

    The page fetchers called themselves safe and checked only the size. The
    address check above was written for them and never called (found
    2026-11-16), so browse_website would fetch http://127.0.0.1:5000/..., and
    Blue's server trusts localhost without the password. The tool is on the
    list offered when Blue answers a stranger's email, so a message could
    ask him to read his own chat transcripts or calendar back into the reply.

    Every hop is checked, not only the first: a public page can redirect to a
    private address. Credentials a caller added are dropped when a redirect
    leaves the host they were meant for.
    """
    import requests

    current = url
    sent = dict(headers or {})
    for _ in range(_MAX_REDIRECTS + 1):
        assert_public_http_url(current)
        resp = requests.get(current, headers=sent, timeout=timeout,
                            stream=True, allow_redirects=False)
        location = resp.headers.get("location")
        if resp.status_code not in _REDIRECT_CODES or not location:
            break
        target = urljoin(current, location)
        resp.close()
        if urlsplit(target).hostname != urlsplit(current).hostname:
            sent = {k: v for k, v in sent.items()
                    if k.lower() not in _CREDENTIAL_HEADERS}
        current = target
    else:
        raise ValueError("Too many redirects")
    resp.raise_for_status()
    content = b""
    for chunk in resp.iter_content(chunk_size=16384):
        if chunk:
            content += chunk
            if len(content) > max_bytes:
                break
    return resp.headers.get("content-type", ""), content


def marker_matches_host(marker: str, request_host: str) -> bool:
    """Return True when an Origin/Referer marker matches the request host."""
    marker_host = (urlsplit(marker or "").netloc or "").lower()
    return bool(marker_host and marker_host == (request_host or "").lower())
