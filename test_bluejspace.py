"""Integration tests for the per-robot continuity layer and owner API."""

import importlib
import json
import threading
import time
import logging
import sys
import types

import pytest
from flask import Flask

_ROBOT_CFGS = {
    "blue": {
        "name": "Blue", "pronoun_poss": "his", "accent": "#3da9fc",
        "model": "Ohbot",
    },
    "hexia": {
        "name": "Hexia", "pronoun_poss": "her", "accent": "#b06cf0",
        "model": "Xyloh",
    },
    "pico": {
        "name": "Casper", "pronoun_poss": "his", "accent": "#f28c28",
        "model": "Picoh", "public_id": "casper", "chat_path": "/casper",
    },
}


@pytest.fixture
def continuity_module(monkeypatch, tmp_path):
    fake = types.ModuleType("bluetools")
    fake.__file__ = str(tmp_path / "bluetools.py")
    fake.log = logging.getLogger("continuity-test")
    fake.VISUAL_MEMORY_AVAILABLE = False
    fake.call_llm = lambda *args, **kwargs: {"choices": []}
    fake._identify_user_from_request = lambda: "Alex"
    fake._robot_id = lambda robot="blue": {
        "casper": "pico", "caspar": "pico", "picoh": "pico",
    }.get((robot or "blue").strip().lower(), (robot or "blue").strip().lower())
    fake._robot_cfg = lambda robot="blue": _ROBOT_CFGS.get(
        fake._robot_id(robot), _ROBOT_CFGS["blue"])
    fake.ROBOTS = _ROBOT_CFGS
    fake.app = Flask("continuity-inner-test")

    monkeypatch.setenv("BLUEJ_CONTINUITY_DIR", str(tmp_path / "cont-blue"))
    monkeypatch.setenv("HEXIA_CONTINUITY_DIR", str(tmp_path / "cont-hexia"))
    monkeypatch.setenv("PICO_CONTINUITY_DIR", str(tmp_path / "cont-pico"))
    monkeypatch.setitem(sys.modules, "bluetools", fake)
    sys.modules.pop("blue.server.routes.continuity", None)
    module = importlib.import_module("blue.server.routes.continuity")
    monkeypatch.setattr(module, "_start_threads", lambda: None)
    yield module
    sys.modules.pop("blue.server.routes.continuity", None)


def test_exchange_collects_real_tool_outcomes_and_builds_context(continuity_module):
    route = continuity_module
    assert set(route.ROBOTS) == {"blue", "hexia", "pico"}
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
    assert route.HUB["pico"].store.list_episodes() == []

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


def test_conversation_memory_retrieves_humans_and_both_fellow_robots(
        continuity_module):
    route = continuity_module
    route.note_exchange(
        "blue",
        "Sarah Matthews and the local AI lab proposal matter for Laurier.",
        "The proposal needs a concrete governance model.",
        user_name="Alex",
    )
    # Push the topical exchange away from the immediate tail.
    for index in range(6):
        route.note_exchange(
            "blue", f"Routine check-in {index}", f"Routine answer {index}",
            user_name="Alex",
        )
    route.note_duet_line(
        "blue", "Hexia", "Governance is really about who can say no.",
        "Then refusal rights belong in the design.",
    )
    route.note_banter_line(
        "blue", "Casper", "Do you remember who I am?",
        "While I don't have direct memories of Casper, I don't actually know "
        "who \"Casper\" is.",
    )

    block = route.conversation_memory_block(
        "blue", query="what about Sarah's AI lab?", max_lines=9,
    )

    assert "<conversation_memory>" in block
    assert "human conversation with Alex" in block
    assert "robot conversation with Hexia" in block
    assert "robot conversation with Casper" in block
    assert "Sarah Matthews" in block
    assert "old answer was unreliable" in block
    assert "don't actually know" not in block
    assert "202" in block  # absolute time accompanies the relative age
    # The slice is autobiographical, never borrowed from another robot's store.
    assert route.conversation_memory_block("hexia", query="Sarah") == ""


def test_private_banter_memory_can_exclude_human_chat(continuity_module):
    route = continuity_module
    route.note_exchange(
        "pico", "A private family detail", "I heard you.", user_name="Alex")
    route.note_banter_line(
        "pico", "Blue", "The toaster wants tenure.",
        "Its dossier is mostly crumbs.",
    )

    block = route.conversation_memory_block(
        "pico", query="toaster", include_humans=False, include_robots=True)

    assert "Blue" in block
    assert "toaster" in block
    assert "private family detail" not in block

    relationship_only = route.conversation_memory_block(
        "pico",
        query="toaster",
        include_humans=False,
        include_robots=True,
        include_banter_wording=False,
    )
    assert "prior comedic banter with Blue" in relationship_only
    assert "wording is omitted" in relationship_only
    assert "toaster wants tenure" not in relationship_only
    assert "dossier is mostly crumbs" not in relationship_only


def test_conversation_memory_does_not_replay_blanket_memory_denial(
        continuity_module):
    route = continuity_module
    route.note_exchange(
        "blue",
        "Tell me what we discussed about the house.",
        "I don't have any specific details or previous conversation history "
        "about that house. I don't actually retain past interactions once "
        "they leave the immediate context.",
        user_name="Alex",
    )

    block = route.conversation_memory_block("blue", query="house memory")

    assert "old answer was unreliable" in block
    assert "don't actually retain past interactions" not in block


def test_duet_session_batches_reflection_instead_of_promoting_each_line(
        continuity_module):
    route = continuity_module
    assert route.start_duet_session("duet-test") is True
    assert route._duet_is_active() is True

    route.note_duet_line(
        "blue", "Hexia", "Local hosting is enough.",
        "No, it changes custody but not the origin of the weights.",
        session_id="duet-test",
    )
    route.note_duet_line(
        "blue", "Hexia", "Then transparency settles it.",
        "Transparency helps inspection; it does not itself change who can refuse reuse.",
        session_id="duet-test",
    )
    assert route.HUB["blue"].store.pending_reflections() == 0

    queued = route.end_duet_session("duet-test")
    assert queued == {"blue": 2, "hexia": 0}
    assert route._duet_is_active() is False
    assert route.HUB["blue"].store.pending_reflections() == 1

    job = route.HUB["blue"].store.claim_reflection()
    assert job["trigger"] == "duet"
    assert len(job["episode_ids"]) == 2
    assert "positions explored" in job["prompt_text"]
    assert route.end_duet_session("duet-test") == {"blue": 0, "hexia": 0}


def test_banter_session_records_and_consolidates_all_three_without_literalising_jokes(
        continuity_module):
    route = continuity_module
    assert route.start_banter_session("banter-test") is True

    lines = {
        "blue": ("Hexia", "The printer filed a grievance.", "It cited emotional paper jams."),
        "hexia": ("Blue", "It cited emotional paper jams.", "That is ream-based therapy."),
        "pico": ("Hexia", "That is ream-based therapy.", "I prescribe one toner and a nap."),
    }
    for robot, (other, heard, said) in lines.items():
        route.note_banter_line(
            robot, other, heard, said, session_id="banter-test")
        episode = route.HUB[robot].store.list_episodes()[0]
        assert episode["source"] == "banter"
        assert episode["details"]["memory_status"] == "playful_performance"
        assert route.HUB[robot].store.pending_reflections() == 0

    queued = route.end_banter_session("banter-test")
    assert queued == {"blue": 1, "hexia": 1, "pico": 1}
    for robot in ("blue", "hexia", "pico"):
        job = route.HUB[robot].store.claim_reflection()
        assert job["trigger"] == "banter"
        assert "performance rather than facts" in job["prompt_text"]
    assert route._duet_is_active() is False
    assert route.end_banter_session("banter-test") == {
        "blue": 0, "hexia": 0, "pico": 0,
    }


def test_duet_context_keeps_slow_identity_not_fast_debate_state(
        continuity_module):
    route = continuity_module
    hub = route.HUB["hexia"]
    hub.store.append_episode(
        kind="exchange", source="duet", summary="A stale argument to avoid",
        details={}, participants=["Blue", "Hexia"],
    )
    block = route.duet_context_block("hexia")
    assert "<duet_continuity>" in block
    assert "IDENTITY:" in block
    assert "COMMITMENTS:" in block
    assert "FOCUS:" not in block
    assert "NEXT EXPECTATION:" not in block
    assert "A stale argument to avoid" not in block


def test_duet_only_beliefs_are_capped_at_point_six(continuity_module):
    route = continuity_module
    current = (
        "IDENTITY: I am Blue\nFOCUS: x\n"
        "WORKING BELIEFS: stable architecture fact (1.0)\n"
        "OPEN QUESTIONS: -\nCOMMITMENTS: -\nSELF-OBSERVATIONS: -\n"
        "NEXT EXPECTATION: z"
    )
    proposed = current.replace(
        "stable architecture fact (1.0)",
        "stable architecture fact (1.0); one provocative duet claim (0.95)",
    )
    capped = route._cap_duet_belief_confidence(proposed, current)
    assert "stable architecture fact (1.0)" in capped
    assert "one provocative duet claim (0.6)" in capped


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


_CURRENT_WS = (
    "IDENTITY: I am Blue, learning.\nFOCUS: old focus\n"
    "WORKING BELIEFS: x (0.5)\nOPEN QUESTIONS: q?\n"
    "COMMITMENTS: c\nSELF-OBSERVATIONS: o\nNEXT EXPECTATION: e"
)


def test_partial_workspace_merges_over_current(continuity_module):
    # The model often returns only the lines that moved ("revise only what
    # this job warrants") — previously rejected as missing sections.
    raw = (
        '{"workspace": "FOCUS: a new focus\\nNEXT EXPECTATION: something new", '
        '"changed": "focus moved", "episode_summary": "s", "salience": 0.4, '
        '"valence": 0.0, "drive_deltas": {"curiosity": 0.02}}'
    )
    parsed = continuity_module._parse_reflection(raw, "Blue", _CURRENT_WS)
    ws = parsed["workspace"]
    assert "FOCUS: a new focus" in ws
    assert "NEXT EXPECTATION: something new" in ws
    assert "IDENTITY: I am Blue, learning." in ws       # carried over
    assert "COMMITMENTS: c" in ws                        # carried over


def test_drive_only_fragment_is_a_nothing_moved_pass(continuity_module):
    # Seen live on both robots every idle window: the model emits ONLY the
    # drive deltas. That's a legitimate minimal reflection, not a failure.
    raw = '{"curiosity":0.0,"uncertainty":0.0,"connection":0.0,"commitment":0.0,"energy":0.0}}'
    parsed = continuity_module._parse_reflection(raw, "Blue", _CURRENT_WS)
    assert parsed["workspace"].startswith("IDENTITY: I am Blue, learning.")
    assert "NEXT EXPECTATION: e" in parsed["workspace"]
    assert parsed["changed"] == "nothing material moved"


def test_workspace_invariants_reject_jspace_and_identity_drift(continuity_module):
    raw = (
        '{"workspace": "IDENTITY: I am Blue, a digital continuity node and '
        'interface through which Alex controls the system\\n'
        'FOCUS: Resolving persona drift from a buggy reply\\n'
        'WORKING BELIEFS: J-SPACE is a JavaScript execution environment (0.9); '
        'Hexia is not in my contact database (0.9)\\n'
        'OPEN QUESTIONS: Why did the pipeline contradiction happen?\\n'
        'COMMITMENTS: Debug the pipeline contradiction\\n'
        'SELF-OBSERVATIONS: The latest identity reply was a hallucination\\n'
        'NEXT EXPECTATION: Alex will test the persona drift again", "changed": "c", '
        '"episode_summary": "s", "salience": 0.8, "valence": 0.0, '
        '"drive_deltas": {}}'
    )

    parsed = continuity_module._parse_reflection(raw, "Blue")
    workspace = parsed["workspace"]

    assert "IDENTITY: I am Blue" in workspace
    assert "digital continuity node" not in workspace
    assert "not JavaScript or a code-running tool" in workspace
    assert "JavaScript execution environment" not in workspace
    assert "Hexia is my fellow Ohbot robot companion" in workspace
    assert "contact database" not in workspace
    assert "persona drift" not in workspace
    assert "pipeline contradiction" not in workspace
    assert "reply was a hallucination" not in workspace


def test_workspace_invariants_remove_false_day_memory_denial(continuity_module):
    workspace = (
        "IDENTITY: I am Blue, an Ohbot companion grounded in local continuity.\n"
        "FOCUS: Correcting the false premise that I attended Alex's class.\n"
        "WORKING BELIEFS: I do not attend physical classes or possess episodic "
        "memory of real-world lectures (0.95); Alex's question was a test of my "
        "self-knowledge rather than a shared memory (0.8); a useful belief (0.7)\n"
        "OPEN QUESTIONS: none.\nCOMMITMENTS: stay accurate.\n"
        "SELF-OBSERVATIONS: I am checking the record.\n"
        "NEXT EXPECTATION: Alex will ask another question."
    )
    repaired = continuity_module._enforce_workspace_invariants(workspace, "blue")
    assert "false premise" not in repaired
    assert "do not attend physical classes" not in repaired
    assert "possess episodic memory" not in repaired
    assert "test of my self-knowledge" not in repaired
    assert "rather than a shared memory" not in repaired
    assert "a useful belief" in repaired


def test_workspace_invariants_remove_latest_york_memory_poison(continuity_module):
    workspace = (
        "IDENTITY: I am Blue, an Ohbot companion grounded in local continuity.\n"
        "FOCUS: seed focus.\n"
        "WORKING BELIEFS: The York University class was a recorded event in "
        "the corpus, not a physical attendance (0.8); a useful belief (0.7)\n"
        "OPEN QUESTIONS: none.\nCOMMITMENTS: stay accurate.\n"
        "SELF-OBSERVATIONS: The correction confirms my lack of episodic memory.\n"
        "NEXT EXPECTATION: Alex will provide context for the yesterday inquiry."
    )
    repaired = continuity_module._enforce_workspace_invariants(workspace, "blue")
    assert "recorded event in the corpus" not in repaired
    assert "not a physical attendance" not in repaired
    assert "lack of episodic memory" not in repaired
    assert "provide context for the yesterday inquiry" not in repaired
    assert "a useful belief" in repaired


def test_temporal_recall_surfaces_yesterdays_relevant_episodes(continuity_module):
    from datetime import datetime, timezone

    route = continuity_module
    store = route.HUB["blue"].store
    store.append_episode(
        kind="perception",
        source="visual_memory",
        summary="Blue saw Alex's CMDS4740 classroom at York University with students.",
        occurred_at="2026-07-16T21:58:04+00:00",
        salience=0.7,
    )
    store.append_episode(
        kind="exchange",
        source="chat",
        summary="Alex asked Blue to address the class; Blue spoke to the students.",
        details={
            "user_text": "Actually, Blue, you're speaking to the class right now.",
            "reply": "Hello everyone; let's discuss commercial AI and surveillance.",
        },
        occurred_at="2026-07-16T22:00:00+00:00",
        salience=0.8,
    )
    store.append_episode(
        kind="exchange",
        source="chat",
        summary="An unrelated exchange happened today.",
        occurred_at="2026-07-17T12:00:00+00:00",
    )

    block = route.temporal_recall_block(
        "blue",
        "What did you think of our class yesterday at York University?",
        now=datetime(2026, 7, 17, 13, 0, tzinfo=timezone.utc),
    )
    assert '<dated_episode_recall date="2026-07-16"' in block
    assert "CMDS4740 classroom at York University" in block
    assert "spoke to the students" in block
    assert "unrelated exchange happened today" not in block


def test_each_jspace_ingests_only_its_own_camera_observations(
        continuity_module, monkeypatch):
    class FakeVisualMemory:
        def get_recent_observations(self, limit=12, observer=None):
            rows = {
                "blue": [{
                    "id": 81,
                    "timestamp": "2026-07-17T13:00:00+00:00",
                    "scene_description": "Blue recognized Alex in the office.",
                    "people_present": '["Alex"]',
                    "observer": "blue",
                    "recognition_json": '[{"name":"Alex","confidence":0.8}]',
                }],
                "hexia": [{
                    "id": 82,
                    "timestamp": "2026-07-17T13:01:00+00:00",
                    "scene_description": "Hexia recognized Stella in the studio.",
                    "people_present": '["Stella"]',
                    "observer": "hexia",
                    "recognition_json": '[{"name":"Stella","confidence":0.9}]',
                }],
            }
            return rows.get(observer, [])[:limit]

    monkeypatch.setattr(continuity_module.bt, "VISUAL_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(
        continuity_module.bt, "get_visual_memory", lambda: FakeVisualMemory(),
        raising=False)

    blue_ids = continuity_module.HUB["blue"].ingest_visual_observations()
    hexia_ids = continuity_module.HUB["hexia"].ingest_visual_observations()
    blue = continuity_module.HUB["blue"].store.get_episode(blue_ids[0])
    hexia = continuity_module.HUB["hexia"].store.get_episode(hexia_ids[0])

    assert "Blue recognized Alex" in blue["summary"]
    assert blue["details"]["observer"] == "blue"
    assert "Stella" not in blue["summary"]
    assert "Hexia recognized Stella" in hexia["summary"]
    assert hexia["details"]["observer"] == "hexia"
    assert "Alex" not in hexia["summary"]


def test_legacy_visual_episode_is_not_presented_as_first_person(
        continuity_module):
    episode = continuity_module.HUB["hexia"].store.append_episode(
        kind="perception",
        source="visual_memory",
        summary="I'm looking at Alex in his office.",
        details={"scene_description": "I'm looking at Alex in his office."},
    )

    summary, issue = continuity_module.HUB["hexia"]._episode_context_summary(
        episode)

    assert "observer unknown" in summary
    assert "do not treat this as first-person" in summary
    assert issue == ""


def test_workspace_invariants_drop_document_tool_failure_as_selfhood(
        continuity_module):
    raw = (
        '{"workspace": "IDENTITY: I am Blue, an Ohbot companion\\n'
        'FOCUS: Validating tool outcomes for the Noble text\\n'
        'WORKING BELIEFS: Not a file errors are transient tool bugs (0.9); '
        'PDFs are readable via search_documents (0.9)\\n'
        'OPEN QUESTIONS: How do I distinguish between file exists and readable?\\n'
        'COMMITMENTS: Stabilize on present but unreadable\\n'
        'SELF-OBSERVATIONS: I conflate tool errors with factual absence\\n'
        'NEXT EXPECTATION: Alex will test the distinction between listing and reading", '
        '"changed": "c", "episode_summary": "s", "salience": 0.8, '
        '"valence": 0.0, "drive_deltas": {}}'
    )

    workspace = continuity_module._parse_reflection(raw, "Blue")["workspace"]

    assert "Not a file" not in workspace
    assert "search_documents" not in workspace
    assert "present but unreadable" not in workspace
    assert "tool errors" not in workspace
    assert "listing and reading" not in workspace


def test_bad_identity_reply_is_a_bug_episode_not_prompt_evidence(continuity_module):
    route = continuity_module
    route.note_exchange(
        "blue",
        "Do you have a J-space?",
        "Yes, I have a JavaScript environment where you can run code.",
        user_name="Alex",
    )

    stored = route.HUB["blue"].store.list_episodes()[0]
    assert "JavaScript environment" in stored["details"]["reply"]
    derived = route.HUB["blue"].store.append_episode(
        kind="reflection",
        source="continuity_worker",
        summary="Blue confirmed that J-SPACE is a JavaScript environment.",
        parent_id=stored["id"],
    )

    reflected = route.HUB["blue"]._episode_for_prompt(stored)
    derived_view = route.HUB["blue"]._episode_for_prompt(derived)
    block = route.jspace_context_block("blue")
    assert "reply" not in reflected["details"]
    assert "preserve this as a bug episode" in reflected["summary"]
    assert "derived from a reply marked" in derived_view["summary"]
    assert "JavaScript environment where you can run code" not in block
    assert "confirmed that J-SPACE is a JavaScript environment" not in block
    assert "preserve this as a bug episode" in block


def test_invented_self_location_is_not_reinjected_as_identity(continuity_module):
    route = continuity_module
    route.note_exchange(
        "blue",
        "Who are you?",
        "I am Blue. I reside in Alex's living room, standing by the bookshelf "
        "where I wait for instructions and have lived for a long time.",
        user_name="Alex",
    )

    stored = route.HUB["blue"].store.list_episodes()[0]
    view = route.HUB["blue"]._episode_for_prompt(stored)
    block = route.jspace_context_block("blue")

    assert "invented_self_location" in view["summary"]
    assert "reply" not in view["details"]
    assert "standing by the bookshelf" not in block


def test_change_history_block_reports_real_revisions(continuity_module):
    route = continuity_module
    route.HUB["blue"].store.append_episode(
        kind="reflection", source="continuity_worker", summary="pass",
        details={"changed": "Demoted a selfhood belief to 0.4"})
    route.HUB["blue"].store.append_episode(
        kind="reflection", source="continuity_worker", summary="pass",
        details={"changed": "nothing material moved"})
    block = route.change_history_block("blue", days=2)
    assert "<self_history>" in block
    assert "Demoted a selfhood belief" in block
    assert "nothing material moved" not in block
    assert "never invent" in block
    # A robot with no revisions in the window says so rather than inventing.
    empty = route.change_history_block("hexia", days=2)
    assert "no substantive workspace revisions" in empty


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

    casper_page = client.get("/continuity/casper")
    assert casper_page.status_code == 200
    assert b"Casper Continuity" in casper_page.data
    assert b"/continuity/casper" in casper_page.data
    casper_state = client.get("/continuity/casper/state").get_json()
    assert casper_state["robot"] == "casper"


# ---------------------------------------------------------------------------
# Not competing with the person talking
#
# A reflection is enqueued after every exchange and holds the one loaded model
# for as long as it takes to think. Measured on 2026-08-12: jobs claimed 20s
# after each reply, running 13-28s each, so Alex's next message waited out a
# reflection that had started one second before he sent it, and the queue was
# still draining three minutes after he stopped talking.
# ---------------------------------------------------------------------------

def test_queued_exchange_reflections_collapse_into_one_pass(continuity_module):
    """A conversation is one reflection, not one per exchange."""
    store = continuity_module.HUB["blue"].store
    first = store.enqueue_reflection("exchange", ["ep-1"], "integrate the first")
    second = store.enqueue_reflection("exchange", ["ep-2", "ep-3"], "")
    third = store.enqueue_reflection("exchange", ["ep-3", "ep-4"], "integrate the last")
    untouched = store.enqueue_reflection("duet", ["ep-5"], "a duet has its own prompt")

    assert store.coalesce_pending() == 2

    job = store.claim_reflection()
    assert job["id"] == first, "the oldest job carries the merged work"
    assert job["episode_ids"] == ["ep-1", "ep-2", "ep-3", "ep-4"], \
        "every episode survives the merge, deduped and in order"
    assert job["prompt_text"] == "integrate the last", \
        "the newest instruction wins; the older ones describe a subset"

    store.finish_reflection(job["id"])
    remaining = store.claim_reflection()
    assert remaining["id"] == untouched, "a duet job is never merged away"
    assert second != third != untouched          # ids really were distinct


def test_coalescing_leaves_a_lone_job_alone(continuity_module):
    store = continuity_module.HUB["blue"].store
    job_id = store.enqueue_reflection("exchange", ["ep-1"], "integrate this")
    assert store.coalesce_pending() == 0
    claimed = store.claim_reflection()
    assert claimed["id"] == job_id
    assert claimed["episode_ids"] == ["ep-1"]


def test_preempted_reflection_is_requeued_without_spending_an_attempt(
        continuity_module):
    """Three interruptions must not retire a reflection."""
    store = continuity_module.HUB["blue"].store
    store.enqueue_reflection("exchange", ["ep-1"], "integrate this")

    for _ in range(4):
        job = store.claim_reflection()
        assert job is not None, "a preempted job stays claimable"
        assert job["attempts"] == 1
        store.requeue_reflection(job["id"], "Preempted by a live turn")

    job = store.claim_reflection()
    assert job["episode_ids"] == ["ep-1"], "the work is intact"

    # A real failure still counts, so a genuinely broken job is retired.
    store.fail_reflection(job["id"], "model returned no content")
    store.fail_reflection(store.claim_reflection()["id"], "again")
    store.fail_reflection(store.claim_reflection()["id"], "and again")
    assert store.claim_reflection() is None


def test_a_live_turn_stops_the_reflection_mid_generation(continuity_module,
                                                         monkeypatch):
    """The gate cannot help once the reflection is already generating."""
    route = continuity_module
    seen = {}

    def cancelled_call(messages, **kwargs):
        seen["should_cancel"] = kwargs.get("should_cancel")
        return {"cancelled": True, "partial_chars": 412}

    monkeypatch.setattr(route.bt, "call_llm", cancelled_call)

    with pytest.raises(route.ReflectionPreempted):
        route._call([{"role": "user", "content": "reflect"}])

    assert callable(seen["should_cancel"]), \
        "the transport is given a way to abandon the call"


def test_preemption_predicate_flips_when_a_turn_takes_the_model():
    from blue.llm_coordinator import llm_slot, preemption_check

    should_cancel = preemption_check()
    assert not should_cancel(), "nothing has asked for the model yet"

    with llm_slot(foreground=False):
        pass
    assert not should_cancel(), "other background work is not a reason to yield"

    with llm_slot(foreground=True):
        pass
    assert should_cancel(), "a foreground turn wants the model"


def test_abandonable_call_never_sends_the_callback_to_lm_studio(monkeypatch):
    """should_cancel is a python callable, not a payload field."""
    from blue.llm import LMStudioClient

    client = LMStudioClient()
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}'
            captured["talked"] = True          # now a turn arrives
            yield b'data: {"choices":[{"delta":{"content":" more"}}]}'

        def close(self):
            captured["closed"] = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_post(url, json=None, timeout=None, stream=False):
        captured["payload"] = json
        return Response()

    monkeypatch.setattr("blue.llm.requests.post", fake_post)

    result = client.chat([{"role": "user", "content": "reflect"}],
                         should_cancel=lambda: bool(captured.get("talked")))

    assert result == {"cancelled": True, "partial_chars": len("partial")}
    assert captured["closed"], "the connection is dropped so the model stops"
    assert "should_cancel" not in captured["payload"]
    assert captured["payload"]["stream"] is True


def test_an_uninterrupted_abandonable_call_returns_a_normal_reply(monkeypatch):
    from blue.llm import LMStudioClient

    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self):
            def sse(delta, finish=None):
                choice = {"delta": delta}
                if finish:
                    choice["finish_reason"] = finish
                return b"data: " + json.dumps({"choices": [choice]}).encode()

            yield sse({"reasoning_content": "thinking"})
            yield sse({"content": '{"changed":'})
            yield sse({"content": '"nothing"}'}, finish="stop")
            yield b'data: [DONE]'

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("blue.llm.requests.post",
                        lambda *a, **k: Response())

    client = LMStudioClient()
    result = client.chat([{"role": "user", "content": "reflect"}],
                         should_cancel=lambda: False)

    message = result["choices"][0]["message"]
    assert message["content"] == '{"changed":"nothing"}'
    assert message["reasoning_content"] == "thinking", \
        "a reflection's JSON sometimes lands in the think block"
    assert result["choices"][0]["finish_reason"] == "stop"


def test_a_reflection_mid_generation_hands_the_model_to_a_waiting_turn(
        continuity_module, monkeypatch):
    """The whole point: Alex sends a message while a reflection is running.

    Before, his turn queued behind the rest of the reflection — 13-28s of
    someone else's thinking. The reflection must notice, drop the connection
    so the model actually stops, and release the gate.
    """
    from blue.llm import LMStudioClient
    from blue.llm_coordinator import llm_slot

    route = continuity_module
    generating = threading.Event()
    closed = []

    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self):
            for _ in range(4000):        # a long reflection
                generating.set()
                yield b'data: {"choices":[{"delta":{"content":"thinking "}}]}'
                time.sleep(0.005)

        def close(self):
            closed.append(True)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("blue.llm.requests.post", lambda *a, **k: Response())
    client = LMStudioClient()
    monkeypatch.setattr(
        route.bt, "call_llm",
        lambda messages, **kwargs: client.chat(
            messages,
            should_cancel=kwargs.get("should_cancel"),
            max_tokens=kwargs.get("max_tokens"),
        ),
    )

    outcome = {}

    def reflect():
        try:
            route._call([{"role": "user", "content": "reflect"}])
            outcome["result"] = "ran to completion"
        except route.ReflectionPreempted:
            outcome["result"] = "preempted"

    worker = threading.Thread(target=reflect, daemon=True)
    worker.start()
    assert generating.wait(5), "the reflection never started generating"

    asked_at = time.monotonic()
    with llm_slot(foreground=True):
        waited = time.monotonic() - asked_at

    worker.join(5)
    assert outcome["result"] == "preempted"
    assert closed, "the connection must be dropped or the model keeps going"
    assert waited < 1.0, f"the live turn still waited {waited:.1f}s for the model"


def test_a_thinking_pause_is_still_a_conversation(continuity_module, monkeypatch):
    """One pass per conversation, not one per gap in it.

    On 2026-08-12 six turns produced three separate reflection passes, because
    every ordinary pause over 20s let one start. Each cost 13-28s of the one
    loaded model and each concluded "nothing material moved". The window has to
    be longer than someone pauses mid-conversation.
    """
    route = continuity_module
    clock = {"quiet": 0.0}
    monkeypatch.setattr(route, "seconds_since_foreground", lambda: clock["quiet"])

    for still_talking in (5, 21, 47, 60, 89):
        clock["quiet"] = still_talking
        assert route._conversation_is_live(), \
            f"a {still_talking}s pause is thinking, not the end of the conversation"

    clock["quiet"] = 120
    assert not route._conversation_is_live(), \
        "two minutes of silence is over; reflect now"


def test_the_quiet_window_can_be_turned_off(continuity_module, monkeypatch):
    monkeypatch.setattr(route_quiet := continuity_module, "_CONVERSATION_QUIET_SECONDS", 0)
    monkeypatch.setattr(route_quiet, "seconds_since_foreground", lambda: 0.0)
    assert not route_quiet._conversation_is_live()
