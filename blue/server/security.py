"""Security helpers shared by Blue's server and web tools."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit


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
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            raise ValueError("Private/local network URLs are blocked")
    return url


def marker_matches_host(marker: str, request_host: str) -> bool:
    """Return True when an Origin/Referer marker matches the request host."""
    marker_host = (urlsplit(marker or "").netloc or "").lower()
    return bool(marker_host and marker_host == (request_host or "").lower())

