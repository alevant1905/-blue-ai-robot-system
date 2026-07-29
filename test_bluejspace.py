"""Integration tests for the per-robot continuity layer and owner API."""

import importlib
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
