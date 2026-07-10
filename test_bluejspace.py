"""Integration tests for the per-robot continuity layer and owner API."""

import importlib
import logging
import sys
import types

import pytest
from flask import Flask

_ROBOT_CFGS = {
    "blue": {"name": "Blue", "pronoun_poss": "his", "accent": "#3da9fc"},
    "hexia": {"name": "Hexia", "pronoun_poss": "her", "accent": "#b06cf0"},
}


@pytest.fixture
def continuity_module(monkeypatch, tmp_path):
    fake = types.ModuleType("bluetools")
    fake.__file__ = str(tmp_path / "bluetools.py")
    fake.log = logging.getLogger("continuity-test")
    fake.VISUAL_MEMORY_AVAILABLE = False
    fake.call_llm = lambda *args, **kwargs: {"choices": []}
    fake._identify_user_from_request = lambda: "Alex"
    fake._robot_cfg = lambda robot="blue": _ROBOT_CFGS.get(
        (robot or "blue").strip().lower(), _ROBOT_CFGS["blue"])
    fake.app = Flask("continuity-inner-test")

    monkeypatch.setenv("BLUEJ_CONTINUITY_DIR", str(tmp_path / "cont-blue"))
    monkeypatch.setenv("HEXIA_CONTINUITY_DIR", str(tmp_path / "cont-hexia"))
    monkeypatch.setitem(sys.modules, "bluetools", fake)
    sys.modules.pop("blue.server.routes.continuity", None)
    module = importlib.import_module("blue.server.routes.continuity")
    monkeypatch.setattr(module, "_start_threads", lambda: None)
    yield module
    sys.modules.pop("blue.server.routes.continuity", None)


def test_exchange_collects_real_tool_outcomes_and_builds_context(continuity_module):
    route = continuity_module
    assert set(route.ROBOTS) == {"blue", "hexia"}
    route.begin_turn("blue")
    route.record_tool_outcome(
        "create_reminder",
        {"title": "Call Mom"},
        '{"success": true, "id": 7}',
    )
    route.note_exchange(
        "blue",
        "Please remind me to call Mom.",
        "I set the reminder.",
        user_name="Alex",
    )

    episodes = route.HUB["blue"].store.list_episodes(include_superseded=True)
    assert {episode["kind"] for episode in episodes} == {"exchange", "action"}
    action = next(episode for episode in episodes if episode["kind"] == "action")
    assert action["details"]["success"] is True
    assert action["details"]["tool"] == "create_reminder"
    assert route.HUB["blue"].store.pending_reflections() == 1
    # Blue's turn never leaks into Hexia's store.
    assert route.HUB["hexia"].store.list_episodes() == []

    messages = route.messages_with_jspace("blue", [
        {"role": "user", "content": "What did we just do?"}
    ])
    assert messages[0]["role"] == "system"
    assert "<j_space>" in messages[0]["content"]
    assert "create_reminder succeeded" in messages[0]["content"]
    assert messages[-1]["content"] == "What did we just do?"


def test_duet_lines_feed_each_speakers_own_store(continuity_module):
    route = continuity_module
    route.note_duet_line("hexia", "Blue", "What do you make of sparks?",
                         "I think a spark is just attention with nowhere to sit.")
    hexia_eps = route.HUB["hexia"].store.list_episodes()
    assert len(hexia_eps) == 1
    assert hexia_eps[0]["kind"] == "exchange"
    assert hexia_eps[0]["source"] == "duet"
    assert "Blue asked:" in hexia_eps[0]["summary"]
    assert route.HUB["blue"].store.list_episodes() == []
    block = route.jspace_context_block("hexia")
    assert "<j_space>" in block
    assert "attention with nowhere to sit" in block


def test_reflection_salvaged_from_broken_json(continuity_module):
    # Unescaped inner quotes make json.loads fail; the labelled workspace
    # must still be recovered instead of losing the whole reflection pass.
    raw = (
        '{"workspace": "IDENTITY: I am Blue, revising a "phantom" belief\\n'
        'FOCUS: testing\\nWORKING BELIEFS: x (0.4)\\nOPEN QUESTIONS: -\\n'
        'COMMITMENTS: -\\nSELF-OBSERVATIONS: -\\nNEXT EXPECTATION: next", '
        '"changed": "demoted a belief", "episode_summary": "Blue revised.", '
        '"salience": 0.6, "valence": 0.1, '
        '"drive_deltas": {"curiosity": 0.05}}'
    )
    parsed = continuity_module._parse_reflection(raw, "Blue")
    assert parsed["workspace"].startswith("IDENTITY:")
    assert "NEXT EXPECTATION:" in parsed["workspace"]
    assert "\n" in parsed["workspace"]
    assert parsed["changed"] == "demoted a belief"
    assert parsed["salience"] == 0.6
    assert parsed["drive_deltas"]["curiosity"] == 0.05


def test_reflection_recovered_from_think_block(continuity_module):
    # Seen live: the model left the real JSON inside <think> and only a
    # drive_deltas fragment leaked out after it. The full text must be
    # tried when the post-think tail fails.
    good = (
        '{"workspace": "IDENTITY: I am Blue\\nFOCUS: x\\n'
        'WORKING BELIEFS: y (0.5)\\nOPEN QUESTIONS: -\\nCOMMITMENTS: -\\n'
        'SELF-OBSERVATIONS: -\\nNEXT EXPECTATION: z", '
        '"changed": "c", "episode_summary": "s", "salience": 0.5, '
        '"valence": 0.0, "drive_deltas": {"curiosity": 0.0}}'
    )
    raw = f"<think>drafting...\n{good}\n</think>\n{{\n\"curiosity\": 0.0\n}}\n}}"
    parsed = continuity_module._parse_reflection(raw, "Blue")
    assert parsed["workspace"].startswith("IDENTITY:")
    assert "NEXT EXPECTATION:" in parsed["workspace"]


def test_owner_routes_correct_delete_and_wipe(continuity_module):
    route = continuity_module
    original = route.HUB["blue"].store.append_episode(
        kind="exchange", source="test", summary="The meeting is Tuesday."
    )
    app = Flask("continuity-route-test")
    route.register(app)
    client = app.test_client()

    state = client.get("/continuity/blue/state").get_json()
    assert state["ok"] is True
    assert state["robot"] == "blue"
    assert state["episodes"][0]["id"] == original["id"]
    assert len(state["drives"]) == 5

    # Hexia's console answers separately and starts empty.
    hexia_state = client.get("/continuity/hexia/state").get_json()
    assert hexia_state["ok"] is True
    assert hexia_state["episodes"] == []
    assert client.get("/continuity/nosuch/state").status_code == 404

    corrected_response = client.post(
        f"/continuity/blue/episodes/{original['id']}/correct",
        json={"replacement": "The meeting is Wednesday.", "reason": "Calendar check"},
    )
    assert corrected_response.status_code == 200
    correction = corrected_response.get_json()["episode"]

    active = client.get("/continuity/blue/episodes").get_json()["episodes"]
    assert correction["id"] in {episode["id"] for episode in active}
    assert original["id"] not in {episode["id"] for episode in active}

    deleted_response = client.delete(
        f"/continuity/blue/episodes/{correction['id']}", json={})
    assert deleted_response.status_code == 200
    audit = client.get(
        "/continuity/blue/episodes?include_superseded=1").get_json()["episodes"]
    audit_ids = {episode["id"] for episode in audit}
    assert original["id"] not in audit_ids
    assert correction["id"] not in audit_ids

    reset = client.post("/continuity/blue/reset", json={"archive": False}).get_json()
    assert reset == {"ok": True, "archived_as": None, "wiped": True}
    assert client.get("/continuity/blue/state").get_json()["stats"]["episodes"] == 0

    page = client.get("/continuity/hexia")
    assert page.status_code == 200
    assert b"Hexia Continuity" in page.data
    assert b"/continuity/hexia" in page.data
