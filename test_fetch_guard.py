"""The page fetchers never reach this machine or the network it sits on.

browse_website is one of the six tools offered when Blue answers mail from a
stranger (_EMAIL_SAFE_TOOL_NAMES), and Blue's own server trusts localhost
without the password. Until 2026-11-16 the fetcher checked the page's size
and nothing else, so a message could ask him to open
http://127.0.0.1:5000/chat/transcripts and put what came back in the reply.
The address check existed (blue/server/security.py) and nothing called it.

No test here touches the network: name lookups and requests.get are stubbed.
"""

import json
import socket

import pytest
import requests

from blue.server import security


class _Response:
    def __init__(self, status=200, headers=None, body=b"<html><title>T</title>hello</html>"):
        self.status_code = status
        self.headers = headers or {"content-type": "text/html"}
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=16384):
        yield self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def close(self):
        self.closed = True


@pytest.fixture
def net(monkeypatch):
    """A fake internet: `hosts` maps a name to its address, `pages` a URL to
    its response. `asked` lists every URL actually requested."""
    monkeypatch.delenv("BLUE_BROWSE_ALLOW_PRIVATE", raising=False)
    hosts = {"example.org": "93.184.216.34"}
    pages = {}
    asked = []

    def getaddrinfo(host, port, *args, **kwargs):
        address = hosts.get(host, host)
        try:
            socket.inet_pton(socket.AF_INET6 if ":" in address else socket.AF_INET, address)
        except OSError:
            raise socket.gaierror(f"unknown host {host}")
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    def get(url, headers=None, **kwargs):
        assert kwargs.get("allow_redirects") is False, "every hop must be checked"
        asked.append((url, dict(headers or {})))
        return pages.get(url, _Response())

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(requests, "get", get)

    class Net:
        pass

    Net.hosts, Net.pages, Net.asked = hosts, pages, asked
    return Net


BLOCKED = [
    "http://127.0.0.1:5000/chat/transcripts",       # Blue's own server
    "http://localhost:5000/calendar/events",
    "http://[::1]:5000/contacts/list",
    "http://10.0.0.89/api/config",                  # the Hue bridge
    "http://192.168.1.1/",                          # a home router
    "http://169.254.169.254/latest/meta-data/",     # link-local
    "http://100.79.208.51:5000/chat",               # the tailnet (100.64.0.0/10)
    "http://0.0.0.0:1234/v1/models",                # LM Studio
    "file:///C:/Users/secret.txt",
    "ftp://example.org/file",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_a_local_or_private_address_is_never_requested(net, url):
    with pytest.raises(ValueError):
        security.fetch_public_url(url)
    assert net.asked == []


def test_a_public_name_that_resolves_to_this_machine_is_refused(net):
    net.hosts["blue.example.org"] = "127.0.0.1"
    with pytest.raises(ValueError):
        security.fetch_public_url("https://blue.example.org/")
    assert net.asked == []


def test_a_public_page_is_fetched(net):
    ctype, body = security.fetch_public_url("https://example.org/page")
    assert ctype == "text/html"
    assert b"hello" in body
    assert [url for url, _ in net.asked] == ["https://example.org/page"]


def test_a_redirect_to_this_machine_stops_before_the_second_request(net):
    net.pages["https://example.org/go"] = _Response(
        302, {"location": "http://127.0.0.1:5000/chat/transcripts"})
    with pytest.raises(ValueError):
        security.fetch_public_url("https://example.org/go")
    assert [url for url, _ in net.asked] == ["https://example.org/go"]


def test_a_redirect_between_public_pages_is_followed(net):
    net.hosts["www.example.org"] = "93.184.216.35"
    net.pages["https://example.org/old"] = _Response(301, {"location": "/new"})
    net.pages["https://example.org/new"] = _Response(
        302, {"location": "https://www.example.org/final"})
    _, body = security.fetch_public_url(
        "https://example.org/old", headers={"Authorization": "Bearer x", "Accept": "*/*"})
    assert b"hello" in body
    assert [url for url, _ in net.asked] == [
        "https://example.org/old", "https://example.org/new",
        "https://www.example.org/final"]
    # A credential is not carried to another host; an ordinary header is.
    assert "Authorization" in net.asked[1][1]
    assert "Authorization" not in net.asked[2][1]
    assert net.asked[2][1]["Accept"] == "*/*"


def test_a_redirect_loop_ends(net):
    net.pages["https://example.org/a"] = _Response(302, {"location": "/a"})
    with pytest.raises(ValueError, match="redirects"):
        security.fetch_public_url("https://example.org/a")
    assert len(net.asked) == 6


def test_the_owner_can_switch_the_check_off(net, monkeypatch):
    monkeypatch.setenv("BLUE_BROWSE_ALLOW_PRIVATE", "1")
    security.fetch_public_url("http://192.168.1.50/notes.html")
    assert [url for url, _ in net.asked] == ["http://192.168.1.50/notes.html"]


# ---- the callers -----------------------------------------------------------

def test_the_browse_tool_refuses_blues_own_server(net):
    import bluetools as bt

    result = json.loads(bt._execute_browse_website(
        {"url": "http://127.0.0.1:5000/chat/transcripts"}))
    assert result["success"] is False
    assert "blocked" in result["error"].lower()
    assert net.asked == []


def test_the_browse_tool_still_reads_a_public_page(net):
    import bluetools as bt

    result = json.loads(bt._execute_browse_website({"url": "example.org/page"}))
    assert result["success"] is True
    assert "hello" in result["text"]
    assert [url for url, _ in net.asked] == ["https://example.org/page"]


def test_a_duet_link_to_a_private_address_is_not_fetched(net):
    import bluetools as bt

    bt._DUET_URL_CACHE.clear()
    info = bt._duet_url_content("http://192.168.1.1/admin")
    bt._DUET_URL_CACHE.clear()
    assert info["text"] == ""
    assert "blocked" in (info["error"] or "").lower()
    assert net.asked == []


def test_the_banter_source_fetcher_is_guarded_too(net):
    from blue.tools import web

    result = json.loads(web.execute_browse_website(
        {"url": "http://127.0.0.1:5000/continuity/blue/episodes"}))
    assert result["success"] is False
    assert net.asked == []
