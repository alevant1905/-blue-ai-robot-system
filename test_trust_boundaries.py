"""The boundaries that decide what a request is allowed to make Blue do.

Blue runs with full owner powers: he sends mail as Alex, reads his inbox,
drives the lights and opens the camera. Four things stand between a request
and all of that, and before this file none of them had a test:

  * `_is_local_request`   - who skips the password entirely
  * `_require_remote_auth` - the password itself
  * `_identify_user_from_request` - which person a device counts as
  * `_restrict_chat_only_users`   - the fence that keeps the kids' iPad in chat

Three of the four had a hole when this file was written (2026-08-19). Each is
named in the test that now covers it.

The other half of every test here is the reverse risk, which is worse because
it is silent: a boundary drawn too tight does not announce itself, it just
stops Alex's phone from working, or stops Vilda from talking to Blue at all.
So the cases that must be LET THROUGH are checked as carefully as the ones
that must be refused.

SAFETY: `execute_tool` is replaced before any request is made, so nothing here
can reach the house even if a request gets further than it should.
"""

import pytest

import bluetools as bt


IPAD_IP = sorted(bt._TAILSCALE_IP_OWNER)[0]        # Vilda's iPad, by tailnet address
KID = bt._TAILSCALE_IP_OWNER[IPAD_IP]
PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(monkeypatch):
    """The real app, with the house disconnected and a known password."""
    monkeypatch.setattr(bt, "execute_tool",
                        lambda name, args=None, *a, **k: "[stubbed]")
    monkeypatch.setattr(bt, "_access_password", lambda: PASSWORD)
    bt.app.config["TESTING"] = True
    return bt.app.test_client()


def get(client, path, ip="127.0.0.1", headers=None, method="GET"):
    return client.open(path, method=method, environ_base={"REMOTE_ADDR": ip},
                       headers=headers or {})


def whoami(**kwargs):
    headers = kwargs.pop("headers", None)
    ip = kwargs.pop("ip", "127.0.0.1")
    with bt.app.test_request_context("/", headers=headers or {},
                                     environ_base={"REMOTE_ADDR": ip}):
        return bt._identify_user_from_request()


# --------------------------------------------------------------------------
# Who skips the password
# --------------------------------------------------------------------------

def test_a_proxied_request_is_not_local(client):
    """The Tailscale bypass: HTTPS is terminated on the host, so remote
    devices arrive from 127.0.0.1 and used to be trusted as fully local.

    The password protected only plain-LAN access, which is not the path the
    phone actually uses. A proxied request carries X-Forwarded-For and a real
    local caller never does, so presence of that header ends locality.
    """
    r = get(client, "/documents", ip="127.0.0.1",
            headers={"X-Forwarded-For": "100.99.99.99"})
    assert r.status_code in (302, 401), "a Tailscale peer must authenticate"


def test_the_value_of_the_forwarded_header_is_not_believed(client):
    """It is client-settable, so only its presence may be read.

    A caller who writes 127.0.0.1 into it is asking to be treated as local.
    Reading the value would grant exactly that.
    """
    r = get(client, "/documents", ip="192.168.1.50",
            headers={"X-Forwarded-For": "127.0.0.1"})
    assert r.status_code in (302, 401)
    r = get(client, "/documents", ip="127.0.0.1",
            headers={"X-Forwarded-For": "127.0.0.1"})
    assert r.status_code in (302, 401)


def test_the_pc_and_the_ohbot_client_are_still_ungated(client):
    """The robot POSTs to 127.0.0.1 with no proxy in between and must never
    be asked for a password - there is nobody at that end to type one."""
    assert get(client, "/documents").status_code == 200


def test_remote_without_a_password_configured_fails_closed(client, monkeypatch):
    monkeypatch.setattr(bt, "_access_password", lambda: "")
    r = get(client, "/documents", ip="192.168.1.50")
    assert r.status_code == 503


def test_the_password_is_compared_in_constant_time():
    """A shared secret checked with == leaks its length and prefix by timing."""
    import inspect
    source = inspect.getsource(bt.blue_login)
    assert "compare_digest" in source
    assert "supplied == pw" not in source and "pw == supplied" not in source


def test_a_wrong_password_grants_no_session(client):
    r = client.post("/login", data={"password": "wrong", "next": "/chat"},
                    environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert "blue_auth" not in (r.headers.get("Set-Cookie") or "")


def test_the_right_password_does_grant_one(client):
    r = client.post("/login", data={"password": PASSWORD, "next": "/chat"},
                    environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 302
    assert "session=" in (r.headers.get("Set-Cookie") or "")
    assert get(client, "/documents", ip="192.168.1.50").status_code == 200


# --------------------------------------------------------------------------
# Which person a device counts as
# --------------------------------------------------------------------------

def test_the_ipad_cannot_promote_itself_out_of_the_kid_fence():
    """The escalation this fence exists to prevent, and it was open.

    X-Blue-Device is whatever the client types. It used to be read first, so
    the iPad could send "pc" and become Alex - full tools, every page. The
    Tailscale address is assigned by the tailnet and travels with the
    machine, so where it names a chat-only user it now wins.
    """
    assert whoami(headers={"X-Forwarded-For": IPAD_IP,
                           "X-Blue-Device": "pc"}) == KID
    assert whoami(headers={"X-Forwarded-For": IPAD_IP,
                           "X-Blue-Device": "nonsense"}) == KID
    assert whoami(headers={"X-Forwarded-For": IPAD_IP}) == KID


def test_the_fence_holds_over_http_too(client):
    """Not just the identity function - the endpoints it guards."""
    for path in ("/documents", "/contacts", "/calendar", "/memory/facts"):
        r = get(client, path, headers={"X-Forwarded-For": IPAD_IP,
                                       "X-Blue-Device": "pc",
                                       "Accept": "text/html"})
        assert r.status_code != 200, f"{path} reachable from the iPad"


def test_the_header_can_still_restrict_a_device():
    """Claiming to be the iPad only ever costs you tools, so it stays
    believed. It is also the only way to tell a desktop-mode iPad from a Mac,
    which is why the header exists at all.
    """
    assert whoami(headers={"X-Blue-Device": "ipad"}) == KID


def test_everything_else_is_alex():
    assert whoami() == "Alex"
    assert whoami(headers={"X-Blue-Device": "pc"}) == "Alex"
    assert whoami(ip="192.168.1.50",
                  headers={"User-Agent": "Mozilla/5.0 (Macintosh)"}) == "Alex"


def test_an_ipad_user_agent_is_recognised_without_any_header():
    """The Ohbot client and any device whose JS did not run fall back to this."""
    ua = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    assert whoami(ip="192.168.1.77", headers={"User-Agent": ua}) == KID


def test_the_chat_page_stays_reachable_for_the_kid_once_logged_in(client):
    """If this breaks, Vilda cannot talk to Blue at all.

    Her iPad reaches Blue through Tailscale, so closing the proxy bypass
    means her device is now asked for the household password like any other
    remote one. That is a real change in her experience: one login, then a
    30-day session. What must not happen is the fence and the password
    combining into a device that can never get anywhere.
    """
    r = get(client, "/chat", headers={"X-Forwarded-For": IPAD_IP,
                                      "Accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]

    client.post("/login", data={"password": PASSWORD, "next": "/chat"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": IPAD_IP})
    r = get(client, "/chat", headers={"X-Forwarded-For": IPAD_IP,
                                      "Accept": "text/html"})
    assert r.status_code == 200, "logged in and still cannot reach the chat"


def test_logging_in_does_not_let_the_kid_out_of_the_fence(client):
    """The password proves the device may talk to Blue. It does not decide
    WHO the device is, so a session must not become a promotion."""
    client.post("/login", data={"password": PASSWORD, "next": "/chat"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": IPAD_IP})
    for path in ("/documents", "/contacts", "/memory/facts"):
        r = get(client, path, headers={"X-Forwarded-For": IPAD_IP,
                                       "X-Blue-Device": "pc",
                                       "Accept": "text/html"})
        assert r.status_code != 200, f"{path} reachable after login"


def test_every_endpoint_the_kid_may_reach_is_one_the_chat_page_needs():
    """The allow-list is what an 8-year-old's device can reach. A name added
    here carelessly is the whole exposure, so the shape is asserted: nothing
    that sends, deletes, moves the robot, or reads Alex's private data.
    """
    forbidden = ("document", "contact", "calendar", "memory", "email", "mail",
                 "head", "duet", "visual", "panel", "banter", "delete",
                 "remove", "reminder", "music", "camera", "capture")
    for endpoint in bt._CHAT_ONLY_ALLOWED:
        assert not any(word in endpoint.lower() for word in forbidden), \
            f"{endpoint} does not belong in the chat-only allow-list"


def test_the_head_stays_still_for_the_kid():
    """Blue's reply to Vilda is spoken by the iPad. The physical robot must
    not perform it, so /head/* is deliberately absent from the allow-list."""
    assert not any(e.startswith("head") for e in bt._CHAT_ONLY_ALLOWED)
    assert "move_head" in bt._KID_BLOCKED_TOOLS


def test_a_blocked_tool_is_refused_at_execution_not_just_at_selection():
    """The backstop that matters: the model can emit a tool call the selector
    never chose, so blocking it only during selection would block nothing.
    """
    with bt.app.test_request_context("/", headers={"X-Forwarded-For": IPAD_IP}):
        for tool in ("email_snapshot", "create_reminder", "control_music"):
            out = bt.execute_tool(tool, {})
            assert "isn't available" in out, f"{tool} ran for a chat-only user"


# --------------------------------------------------------------------------
# Requests another website made
# --------------------------------------------------------------------------

CROSS = {"Sec-Fetch-Site": "cross-site"}


@pytest.mark.parametrize("method, path, mode", [
    ("POST", "/head/move", "no-cors"),          # a form on someone else's page
    ("POST", "/v1/chat/completions", "cors"),   # fetch()
    ("GET", "/head/move", "no-cors"),           # <img src=...>
    # The classic one: a form on another page, submitted as a top-level
    # navigation. It is cross-site AND mode=navigate, so a gate that lets
    # navigations through without also checking the method lets this in.
    ("POST", "/head/move", "navigate"),
    ("POST", "/documents/upload", "navigate"),
])
def test_another_site_cannot_drive_the_house_through_alexs_browser(
        client, method, path, mode):
    """Localhost is fully trusted and needs no session, so any page open in
    Alex's browser could POST to 127.0.0.1 and change the lights. It never
    sees the response - it does not need to.

    Sec-Fetch-Site is attached by the browser and a page cannot forge it.
    """
    r = get(client, path, method=method,
            headers=dict(CROSS, **{"Sec-Fetch-Mode": mode}))
    assert r.status_code == 403


@pytest.mark.parametrize("headers", [
    {},                                                    # the Ohbot client
    {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"},   # Blue's page
    {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"},      # address bar
    {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},  # a link
])
def test_the_callers_that_must_keep_working_do(client, headers):
    """The Ohbot client sends no Sec-Fetch headers at all; if this gate ever
    blocks a header-less caller, the robot goes silent with no error anyone
    would connect to a security change."""
    assert get(client, "/chat", headers=headers).status_code == 200


# --------------------------------------------------------------------------
# Where a login can send you
# --------------------------------------------------------------------------

@pytest.mark.parametrize("nxt", [
    "//evil.com",
    "/\\evil.com",        # browsers read a backslash as a separator
    "/%5Cevil.com",       # ... and decode this into one first
    "/\t/evil.com",       # ... and strip the tab before parsing
    "/\n/evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "/%2F%2Fevil.com",
])
def test_a_login_link_cannot_land_you_on_another_site(client, nxt):
    """Two of these were live. The guard tested the raw string, but the
    browser does not use the raw string: it strips tabs and newlines and
    decodes %5C before deciding what the URL means, and "/<TAB>/evil.com"
    arrives as "//evil.com" - off the site, from a link that looks like Blue's
    own login.
    """
    assert bt._safe_next_path(nxt) == "/chat"
    r = client.post("/login", data={"password": PASSWORD, "next": nxt},
                    environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.headers.get("Location") == "/chat"


@pytest.mark.parametrize("nxt", [
    "/chat", "/documents", "/chat?robot=hexia", "/duet?x=1&y=2",
    "/documents/download?filename=a%20b.pdf",
])
def test_ordinary_destinations_survive_intact(client, nxt):
    """The redirect is how a logged-out phone gets back to the page it asked
    for, so mangling a query string here sends Alex somewhere unexpected
    after every remote login."""
    assert bt._safe_next_path(nxt) == nxt


def test_control_characters_are_removed_before_the_decision():
    """A browser strips tab, newline and carriage return from a URL
    before it parses it, so the check has to strip them too - otherwise
    it is deciding about a different string than the one that will be
    followed."""
    for raw in ("/" + chr(9) + "/evil.com", "/" + chr(10) + "/evil.com", "/" + chr(13) + "/evil.com", "/" + chr(127) + "/evil.com",):
        assert bt._safe_next_path(raw) == "/chat", repr(raw)


def test_an_absent_next_is_the_chat_page():
    assert bt._safe_next_path("") == "/chat"
    assert bt._safe_next_path(None) == "/chat"


# --------------------------------------------------------------------------
# Reading files off the host
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/documents/file/../../../../Windows/win.ini",
    "/documents/file/..%2f..%2f..%2f..%2fWindows%2fwin.ini",
    "/documents/file/....//....//bluetools.py",
    "/documents/download?filename=../../bluetools.py&folder=",
    "/documents/download?filename=bluetools.py&folder=../..",
])
def test_the_file_endpoints_stay_inside_the_library(client, path):
    """These pass today. The test is here so that a later refactor of the
    document routes cannot quietly turn os.path.join into a file read of
    anything on the machine."""
    assert get(client, path).status_code == 404


# --------------------------------------------------------------------------
# What a stranger's email can reach
# --------------------------------------------------------------------------

def test_a_duet_email_can_never_call_a_tool():
    """Anyone may email Blue with "duet" in the subject and have the robots
    read it out; only automated and self-addressed senders are filtered. That
    is the feature, and it is safe precisely because a duet turn carries no
    tools - so an instruction in the body has nothing to drive.

    If tools are ever enabled on that path, an anonymous email becomes a tool
    trigger. This asserts the property that keeps the feature harmless.
    """
    import re
    src = open("blue/server/routes/duet.py", encoding="utf-8").read()
    calls = re.findall(r"bt\.call_llm\(|call_llm\(", src)
    assert calls, "the duet stopped calling the model; this test is stale"
    assert "include_tools=True" not in src
    assert src.count("include_tools=False") >= len(calls) - 1
