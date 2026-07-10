"""Integration tests for Blue-J's continuity hooks and owner API."""

import importlib
import logging
import sys
import types

import pytest
from flask import Flask


@pytest.fixture
def bluej_module(monkeypatch, tmp_path):
    fake = types.ModuleType("bluetools")
    fake.__file__ = str(tmp_path / "bluetools.py")
    fake.log = logging.getLogger("bluej-test")
    fake.VISUAL_MEMORY_AVAILABLE = False
    fake.call_llm = lambda *args, **kwargs: {"choices": []}
    fake._identify_user_from_request = lambda: "Alex"
    fake._render_chat_page = lambda robot: f"chat:{robot}"
    fake.app = Flask("bluej-inner-test")
    fake.chat_completions = lambda: ({"choices": []}, 200)

    monkeypatch.setenv("BLUEJ_CONTINUITY_DIR", str(tmp_path / "continuity"))
    monkeypatch.setitem(sys.modules, "bluetools", fake)
    sys.modules.pop("blue.server.routes.bluejspace", None)
    module = importlib.import_module("blue.server.routes.bluejspace")
    monkeypatch.setattr(module, "_start_threads", lambda: None)
    yield module
    sys.modules.pop("blue.server.routes.bluejspace", None)


def test_exchange_collects_real_tool_outcomes_and_builds_context(bluej_module):
    route = bluej_module
    route.begin_turn()
    route.record_tool_outcome(
        "create_reminder",
        {"title": "Call Mom"},
        '{"success": true, "id": 7}',
    )
    route.note_exchange(
        "Please remind me to call Mom.",
        "I set the reminder.",
        user_name="Alex",
    )

    episodes = route._STORE.list_episodes(include_superseded=True)
    assert {episode["kind"] for episode in episodes} == {"exchange", "action"}
    action = next(episode for episode in episodes if episode["kind"] == "action")
    assert action["details"]["success"] is True
    assert action["details"]["tool"] == "create_reminder"
    assert route._STORE.pending_reflections() == 1

    messages = route.messages_with_jspace([
        {"role": "user", "content": "What did we just do?"}
    ])
    assert messages[0]["role"] == "system"
    assert "<j_space>" in messages[0]["content"]
    assert "create_reminder succeeded" in messages[0]["content"]
    assert messages[-1]["content"] == "What did we just do?"


def test_owner_routes_correct_delete_and_wipe(bluej_module):
    route = bluej_module
    original = route._STORE.append_episode(
        kind="exchange", source="test", summary="The meeting is Tuesday."
    )
    app = Flask("bluej-route-test")
    route.register(app)
    client = app.test_client()

    state = client.get("/bluej/state").get_json()
    assert state["ok"] is True
    assert state["episodes"][0]["id"] == original["id"]
    assert len(state["drives"]) == 5

    corrected_response = client.post(
        f"/bluej/episodes/{original['id']}/correct",
        json={"replacement": "The meeting is Wednesday.", "reason": "Calendar check"},
    )
    assert corrected_response.status_code == 200
    correction = corrected_response.get_json()["episode"]

    active = client.get("/bluej/episodes").get_json()["episodes"]
    assert correction["id"] in {episode["id"] for episode in active}
    assert original["id"] not in {episode["id"] for episode in active}

    deleted_response = client.delete(f"/bluej/episodes/{correction['id']}", json={})
    assert deleted_response.status_code == 200
    audit = client.get("/bluej/episodes?include_superseded=1").get_json()["episodes"]
    audit_ids = {episode["id"] for episode in audit}
    assert original["id"] not in audit_ids
    assert correction["id"] not in audit_ids

    reset = client.post("/bluej/reset", json={"archive": False}).get_json()
    assert reset == {"ok": True, "archived_as": None, "wiped": True}
    assert client.get("/bluej/state").get_json()["stats"]["episodes"] == 0

