"""Every page Blue serves, for each robot: it answers, and its script parses.

The pages are Python strings holding thousands of lines of JavaScript (the
chat page alone is about 2,900 lines). Nothing parsed them before a browser
did, so a stray brace in an edit showed up as a page that silently did
nothing. Each inline script is now handed to Node's parser; the check is
skipped where Node is not installed.

Only GETs, with the house disconnected: execute_tool and every model call
are replaced, and a model call fails the test.
"""

import json
import re
import shutil
import subprocess

import pytest

import bluetools as bt

NODE = shutil.which("node")

# (path, something the page must contain)
PAGES = [
    ("/", "Blue"),
    ("/login", "password"),
    ("/chat", "Blue"),
    ("/hexia", "Hexia"),
    ("/casper", "Casper"),
    ("/pico", "Casper"),
    ("/duet", "Hexia"),
    ("/banter", "Casper"),
    ("/panel", "Casper"),
    ("/head", "Blue"),
    ("/head/hexia", "Hexia"),
    ("/head/casper", "Casper"),
    ("/heads", "head"),
    ("/calendar", "calendar"),
    ("/contacts", "contact"),
    ("/visual", "visual"),
    ("/documents", "document"),
    ("/perspective", "perspective"),
    ("/perspective/blue", "Blue"),
    ("/perspective/hexia", "Hexia"),
    ("/perspective/casper", "Casper"),
    ("/continuity/blue", "Blue"),
    ("/continuity/hexia", "Hexia"),
    ("/continuity/casper", "Casper"),
]
SCRIPTS = ["/assets/blue.js", "/js/ohbot-heads.js"]
ROBOT_STATE = [
    "/continuity/{robot}/state", "/continuity/{robot}/episodes",
    "/head/{robot}/state", "/tts/preferences/{robot}",
    "/chat/transcripts?robot={robot}",
]

_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)


@pytest.fixture
def client(monkeypatch, tmp_path):
    def no_model(*args, **kwargs):
        raise AssertionError("a page load called the model")

    monkeypatch.setattr(bt, "execute_tool", lambda name, args=None, *a, **k: "[stubbed]")
    for name in ("call_llm", "call_lm_studio", "_post_to_model", "_stream_from_model"):
        monkeypatch.setattr(bt, name, no_model)
    # The worldview page rebuilds its profile from the library when it is
    # stale, which is a run of model calls; the stored one is what is shown.
    monkeypatch.setattr(bt, "build_perspective_profile",
                        lambda force=False: bt._load_cached_profile() or {})
    # Each robot's self-profile is seeded and saved the first time it is
    # read; the pages here read copies.
    for key, cfg in bt.ROBOTS.items():
        copy = tmp_path / f"{key}_profile.json"
        copy.write_text(json.dumps(
            {"profile": f"I am {cfg['name']}, and this is my own account of myself.",
             "evolution_count": 2, "evolved_at": "2026-10-01 09:00"}), encoding="utf-8")
        monkeypatch.setitem(cfg, "profile_path", str(copy))
    bt.app.config["TESTING"] = True
    return bt.app.test_client()


def _get(client, path):
    return client.get(path, environ_base={"REMOTE_ADDR": "127.0.0.1"})


def _node_check(source, label, tmp_path):
    target = tmp_path / "script.js"
    target.write_text(source, encoding="utf-8")
    done = subprocess.run([NODE, "--check", str(target)], capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, f"{label}: {done.stderr.strip()[:600]}"


@pytest.mark.parametrize("path, must_contain", PAGES)
def test_the_page_answers(client, path, must_contain):
    page = _get(client, path)
    assert page.status_code == 200, path
    body = page.get_data(as_text=True)
    assert must_contain.lower() in body.lower(), path
    assert len(body) > 300, path


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
@pytest.mark.parametrize("path", [p for p, _ in PAGES])
def test_the_pages_inline_script_parses(client, path, tmp_path):
    body = _get(client, path).get_data(as_text=True)
    checked = 0
    for attrs, source in _SCRIPT_RE.findall(body):
        if "src=" in attrs.lower() or not source.strip():
            continue
        kind = re.search(r"type\s*=\s*[\"']([^\"']+)", attrs, re.I)
        if kind and "javascript" not in kind.group(1).lower() and kind.group(1) != "module":
            continue
        checked += 1
        _node_check(source, f"{path} script #{checked}", tmp_path)


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
@pytest.mark.parametrize("path", SCRIPTS)
def test_the_shared_script_parses(client, path, tmp_path):
    page = _get(client, path)
    assert page.status_code == 200
    _node_check(page.get_data(as_text=True), path, tmp_path)


def test_the_stylesheet_is_served(client):
    page = _get(client, "/assets/blue.css")
    assert page.status_code == 200
    assert "{" in page.get_data(as_text=True)


@pytest.mark.parametrize("robot", ["blue", "hexia", "casper"])
@pytest.mark.parametrize("path", ROBOT_STATE)
def test_each_robot_has_every_per_robot_endpoint(client, robot, path):
    """Blue, Hexia and Casper are served by the same routes; a robot left
    out of one answers 404 here."""
    page = _get(client, path.format(robot=robot))
    assert page.status_code == 200, path.format(robot=robot)
    assert page.is_json


def test_every_robot_is_configured_alike():
    """What each mode reads from a robot's entry."""
    needed = {"name", "pronoun_subj", "pronoun_poss", "pronoun_refl",
              "profile_path", "identity_note", "seed", "self_desc",
              "persona_line", "accent", "head", "chat_path", "model",
              "relationship_desc", "embodiment_line", "voice_lang_pref",
              "voice_pitch", "voice_rate", "voice_prefer_female"}
    assert list(bt.ROBOTS) == ["blue", "hexia", "pico"]
    for key, cfg in bt.ROBOTS.items():
        assert needed <= set(cfg), (key, sorted(needed - set(cfg)))
        assert cfg["head"] == key
        assert bt._robot_lock(key) is not None
    # Casper answers to his name everywhere a robot is named in a URL.
    assert bt._robot_id("casper") == "pico" and bt._robot_id("Casper") == "pico"
    assert bt._continuity_routes.ROBOTS == tuple(bt.ROBOTS)


# ---- each robot's own page for its self-profile ------------------------------
# Hexia and Casper have had self-profiles, read on every turn, since they
# arrived; only Blue had a page to read, edit or evolve his (2026-11-16).

@pytest.mark.parametrize("path, name, poss, refl", [
    ("/perspective/blue", "Blue", "his", "himself"),
    ("/perspective/hexia", "Hexia", "her", "herself"),
    ("/perspective/casper", "Casper", "his", "himself"),
    ("/perspective/pico", "Casper", "his", "himself"),
])
def test_each_robot_has_a_page_for_its_own_profile(client, path, name, poss, refl):
    body = _get(client, path).get_data(as_text=True)
    assert f"<title>{name}&#39;s Perspective</title>" in body or f"<title>{name}'s Perspective</title>" in body
    assert f"I am {name}, and this is my own account of myself." in body
    assert f"{poss} own evolving character" in body
    assert f"being {refl}" in body
    # It links to the other two, and never calls another robot by this one's name.
    for other in ("Blue", "Hexia", "Casper"):
        if other != name:
            assert f"{other}&#39;s Perspective" in body or f"{other}'s Perspective" in body


def test_only_blue_writes_as_alex(client):
    assert "(not writing as you)" in _get(client, "/perspective/blue").get_data(as_text=True)
    assert "(not writing as you)" not in _get(client, "/perspective/hexia").get_data(as_text=True)


def test_no_page_for_a_robot_that_does_not_exist(client):
    assert _get(client, "/perspective/nosuch").status_code == 404


@pytest.mark.parametrize("path, key", [
    ("/perspective/blue", "blue"), ("/perspective/hexia", "hexia"),
    ("/perspective/casper", "pico")])
def test_saving_a_profile_saves_that_robots_and_no_other(client, path, key):
    before = {k: json.load(open(cfg["profile_path"], encoding="utf-8"))
              for k, cfg in bt.ROBOTS.items()}
    page = client.post(path, data={"action": "save", "profile": "A profile edited by hand."},
                       environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "A profile edited by hand." in body
    assert f"action=\"{path if key != 'pico' else '/perspective/casper'}\"" in body
    for k, cfg in bt.ROBOTS.items():
        now = json.load(open(cfg["profile_path"], encoding="utf-8"))
        if k == key:
            assert now["profile"] == "A profile edited by hand."
            assert now["user_edited"] is True
        else:
            assert now == before[k]


def test_evolving_a_profile_asks_the_model_about_that_robot(client, monkeypatch):
    asked = []

    def model(messages, **kwargs):
        asked.append(messages)
        return {"choices": [{"message": {"content": "I am Hexia, a little further on."}}]}

    monkeypatch.setattr(bt, "call_llm", model)
    monkeypatch.setattr(bt, "_gather_experiences", lambda robot="blue": f"{robot}: days")
    page = client.post("/perspective/hexia", data={"action": "evolve"},
                       environ_base={"REMOTE_ADDR": "127.0.0.1"})
    body = page.get_data(as_text=True)
    assert "I am Hexia, a little further on." in body
    assert "evolution #3" in body
    assert "You are helping Hexia" in asked[0][0]["content"]
    assert "hexia: days" in asked[0][1]["content"]
    saved = json.load(open(bt.ROBOTS["hexia"]["profile_path"], encoding="utf-8"))
    assert saved["profile"] == "I am Hexia, a little further on."
