"""Focused tests for human-led three-robot Panel Mode."""

import importlib
import json
import logging
import re
import sys
import types

import pytest
from flask import Flask


_ROBOTS = {
    "blue": {
        "name": "Blue",
        "persona_line": "You are Blue, calm and thoughtful.",
        "head": "blue",
        "accent": "#3da9fc",
        "voice_pitch": 1.0,
        "voice_rate": 1.0,
    },
    "hexia": {
        "name": "Hexia",
        "persona_line": "You are Hexia, playful and incisive.",
        "head": "hexia",
        "accent": "#b06cf0",
        "voice_pitch": 1.18,
        "voice_rate": 1.06,
        "voice_prefer_female": True,
    },
    "pico": {
        "name": "Casper",
        "persona_line": "You are Casper, curious and direct.",
        "head": "pico",
        "accent": "#f28c28",
        "voice_pitch": 1.08,
        "voice_rate": 1.02,
    },
}


class FakeMemory:
    """Stands in for the enhanced memory system's prompt-block builders."""

    def __init__(self):
        self.searched = []
        self.recalled = []

    def _build_facts_block(self):
        return (
            "<known_facts>\n"
            "- Daughter Names: Athena, Emmy, Vilda\n"
            "- Partner Name: Stella\n"
            "- Brother Name: Felix\n"
            "</known_facts>"
        )

    def _build_user_notes_block(self):
        return "<user_notes>\n- Alex prefers short answers.\n</user_notes>"

    def search_memories(self, query, top_k=6):
        self.searched.append(query)
        return [
            {"type": "person", "subject": "brother", "content": "Felix is from Waterloo.",
             "created_at": "2026-07-01T09:00:00"},
            {"type": "session", "subject": "day", "content": "A day recap that belongs elsewhere.",
             "created_at": "2026-07-02T09:00:00"},
        ]

    def _is_junk_memory(self, subject, content, kind):
        return False

    def _humanize_age(self, created_at, now=None):
        return "a month ago"

    def _build_session_history_block(self, robot="blue"):
        return f"<earlier_sessions>\n- {robot} spoke with Alex on Tuesday.\n</earlier_sessions>"

    def _build_recalled_days_block(self, query, robot="blue", messages=None):
        self.recalled.append(query)
        return "<remembered_days>\n- Felix visited in June.\n</remembered_days>"


class FakeHead:
    def __init__(self, driver="ohbot"):
        self.driver = driver
        self.colors = []
        self.nods = []

    def eye_color(self, r, g, b):
        self.colors.append((r, g, b))
        return True

    def nod_yes(self, times):
        self.nods.append(times)
        return True


@pytest.fixture
def panel_module(monkeypatch):
    calls = []
    fake_bt = types.ModuleType("bluetools")
    fake_bt.log = logging.getLogger("panel-test")
    fake_bt._robot_cfg = lambda robot="blue": _ROBOTS[
        {"casper": "pico", "caspar": "pico", "picoh": "pico"}.get(
            str(robot or "blue").lower(), str(robot or "blue").lower()
        )
    ]
    fake_bt._duet_documents = lambda: [
        {"filename": "blue-notes.pdf", "folder": "Blue"},
        {"filename": "hexia-notes.pdf", "folder": "Hexia"},
        {"filename": "shared.txt", "folder": ""},
    ]
    fake_bt.load_document_index = lambda: {"documents": []}
    fake_bt._build_now_block = lambda: "<now>today</now>"

    # The durable-memory stack the panel borrows from chat.
    memory = FakeMemory()
    fake_bt.memory_system = memory
    fake_bt.ENHANCED_MEMORY_AVAILABLE = True
    fake_bt._FAMILY_QUERY_RE = re.compile(r"\bfamily\b|\bdaughters?\b", re.I)
    fake_bt._family_ground_truth_block = lambda: "<family>\n- Athena, Emmy, Vilda\n</family>"
    fake_bt._ASSISTANT_REFUSAL_MARKERS = ("i don't have any", "haven't met")
    fake_bt._IDENTITY_TALK_RE = re.compile(r"subjective experience", re.I)
    fake_bt._canonical_person_ages = lambda: {}
    fake_bt._misstated_ages = lambda text, canonical: {}
    fake_bt._visual_context_block = lambda text, observer="blue": ""

    def call_llm(messages, **kwargs):
        calls.append({"pipeline": "conversation", "messages": messages, "kwargs": kwargs})
        return {"choices": [{"message": {"content": "Hexia: I heard Blue, and here is my own view."}}]}

    def process_with_tools(messages, **kwargs):
        calls.append({"pipeline": "tools", "messages": messages, "kwargs": kwargs})
        return {"choices": [{"message": {"content": "Hexia: I heard Blue, and here is my own view."}}]}

    class FakeSelector:
        def select_tool(self, text, history=None):
            primary = None
            if "what do you see" in str(text).lower():
                primary = types.SimpleNamespace(tool_name="capture_camera")
            return types.SimpleNamespace(
                primary_tool=primary,
                needs_disambiguation=False,
            )

    fake_bt.call_llm = call_llm
    fake_bt.process_with_tools = process_with_tools
    fake_bt.TOOL_SELECTOR = FakeSelector()
    fake_bt.detect_camera_capture_intent = lambda text: "what do you see" in str(text).lower()
    monkeypatch.setitem(sys.modules, "bluetools", fake_bt)

    continuity = types.ModuleType("blue.server.routes.continuity")
    continuity.conversation_memory_block = lambda *args, **kwargs: "<memory>shared past</memory>"
    continuity.duet_context_block = lambda robot: f"<continuity>{robot}</continuity>"
    monkeypatch.setitem(sys.modules, "blue.server.routes.continuity", continuity)
    routes_package = importlib.import_module("blue.server.routes")
    monkeypatch.setattr(routes_package, "continuity", continuity, raising=False)

    sys.modules.pop("blue.server.routes.panel", None)
    module = importlib.import_module("blue.server.routes.panel")
    heads = {
        "blue": FakeHead(),
        "hexia": FakeHead(),
        "pico": FakeHead("picoh"),
    }
    monkeypatch.setattr(module.blue_head, "get_head", lambda name: heads[name])
    monkeypatch.setattr(
        module,
        "_voice_preferences_payload",
        lambda: json.dumps({
            "blue": {"provider": "browser", "voice": "Microsoft David"},
            "hexia": {"provider": "browser", "voice": "Microsoft Zira"},
            "pico": {"provider": "edge", "voice": "en-US-AnaNeural"},
        }),
    )
    monkeypatch.setattr(
        module,
        "_library_grounding",
        lambda robot, topic, latest, history, filenames: (
            "GROUNDING: " + ", ".join(filenames) if filenames else ""
        ),
    )
    module._test_calls = calls
    module._test_heads = heads
    module._test_memory = memory
    yield module
    sys.modules.pop("blue.server.routes.panel", None)


def _client(module):
    app = Flask("panel-test")
    module.register(app)
    app.testing = True
    return app.test_client()


def test_panel_page_contains_three_robot_controls_and_library(panel_module):
    response = _client(panel_module).get("/panel")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Panel Mode" in html
    assert "Blue" in html and "Hexia" in html and "Casper" in html
    assert "blue-notes.pdf" in html
    assert "Start listening" in html
    assert "Stop talking" in html
    assert "Role / perspective" in html
    assert "Slang / register" in html
    assert '"hexia": {"provider": "browser", "voice": "Microsoft Zira"}' in html
    assert "waitForBrowserVoice(cfg.id,3500)" in html
    assert "voices.some(v=>v.name===name)" in html
    assert "headGesture(cfg" not in html
    assert "isStopCommand(heard)" in html
    assert "turnAbort.abort()" in html
    assert "isLikelyRobotEcho(heard)" in html
    assert "flushRecognitionAfterSpeech()" in html
    assert "recognition.abort()" in html


@pytest.mark.parametrize(
    "robot,head_key,expects_green",
    [("blue", "blue", True), ("hexia", "hexia", False), ("casper", "pico", True)],
)
def test_acknowledgement_is_one_nod_and_green_where_required(
    panel_module, robot, head_key, expects_green
):
    response = _client(panel_module).post("/panel/ack", json={"robot": robot})
    data = response.get_json()
    head = panel_module._test_heads[head_key]

    assert response.status_code == 200
    assert data["nodded"] is True
    assert head.nods[-1] == 1
    if expects_green:
        assert data["color"] == "green"
        assert head.colors[-1] == (0, 10, 0)
    else:
        assert data["color"] is None
        assert head.colors == []


def test_turn_receives_full_shared_transcript_and_per_robot_context(panel_module):
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "text": "Hexia, how does that change your answer?",
            "topic": "Whether cities should ban cars downtown",
            "history": [
                {"speaker": "user", "text": "Blue, what is the strongest case?"},
                {"speaker": "blue", "text": "Access improves when streets serve people."},
                {"speaker": "user", "text": "Hexia, how does that change your answer?"},
            ],
            "settings": {
                "blue": {
                    "role": "transport planner",
                    "slang": "plain language",
                    "documents": ["blue-notes.pdf"],
                },
                "hexia": {
                    "role": "skeptical shop owner",
                    "slang": "dry wit",
                    "documents": ["hexia-notes.pdf", "not-in-library.pdf"],
                },
                "pico": {
                    "role": "accessibility advocate",
                    "slang": "light Gen Z",
                    "documents": ["shared.txt"],
                },
            },
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["speaker"] == "hexia"
    assert data["text"] == "I heard Blue, and here is my own view."
    call = panel_module._test_calls[-1]
    assert call["pipeline"] == "conversation"
    system = call["messages"][0]["content"]
    assert "SHARED HEARING" in system
    assert "skeptical shop owner" in system
    assert "dry wit" in system
    assert "Blue: Access improves when streets serve people." in system
    assert "Blue: role=transport planner" in system
    assert "Casper: role=accessibility advocate" in system
    assert "GROUNDING: hexia-notes.pdf" in system
    assert "not-in-library.pdf" not in system
    assert "Your identity is Hexia" in system
    assert "active discussion topic is: Whether cities should ban cars downtown" in system
    assert call["messages"][-1]["role"] == "user"
    assert "Alex's exact words: Hexia, how does that change your answer?" in call["messages"][-1]["content"]
    assert "Defend this assigned position without reversing it: skeptical shop owner" in call["messages"][-1]["content"]
    assert {
        "role": "user",
        "content": "[Blue, another robot in the panel, said]: Access improves when streets serve people.",
    } in call["messages"]
    assert call["kwargs"]["include_tools"] is False


def test_discussion_turn_carries_the_household_memory_chat_would_have(panel_module):
    """The Felix bug: ordinary discussion skipped the tool pipeline, so the
    facts that answer "who is Felix" never reached the prompt at all."""
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "text": "do you remember who Felix is",
            "history": [
                {"speaker": "user", "text": "do you remember who Felix is"},
            ],
        },
    )

    assert response.status_code == 200
    call = panel_module._test_calls[-1]
    assert call["pipeline"] == "conversation"
    system = call["messages"][0]["content"]
    assert "<known_facts>" in system
    assert "Brother Name: Felix" in system
    assert "<user_notes>" in system
    assert "<relevant_memories>" in system
    assert "Felix is from Waterloo." in system
    assert "<earlier_sessions>" in system
    assert "<remembered_days>" in system
    # Day recaps have their own block; they must not double up in the generic list.
    assert "A day recap that belongs elsewhere." not in system
    assert "Never tell Alex you have no record of someone listed here" in system


def test_family_question_gets_the_canonical_block_and_others_do_not(panel_module):
    client = _client(panel_module)

    client.post(
        "/panel/turn",
        json={"speaker": "hexia", "text": "tell me everything you remember about our family"},
    )
    assert "<family>" in panel_module._test_calls[-1]["messages"][0]["content"]

    client.post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "text": "what do you make of the article",
            # An older line about the family must not force the block on later turns.
            "history": [
                {"speaker": "user", "text": "tell me about our family"},
                {"speaker": "hexia", "text": "Athena, Emmy and Vilda."},
                {"speaker": "user", "text": "what do you make of the article"},
            ],
        },
    )
    assert "<family>" not in panel_module._test_calls[-1]["messages"][0]["content"]


def test_own_memory_denial_is_removed_before_the_next_reply(panel_module):
    """Blue repeated "I don't have any record of a Felix" for three turns: the
    refusal sat in the transcript and outranked the facts by proximity."""
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "text": "of course you know who Felix is",
            "history": [
                {"speaker": "user", "text": "do you remember who Felix is"},
                {"speaker": "blue",
                 "text": "I don't have any record of a Felix in our shared history."},
                {"speaker": "hexia",
                 "text": "I don't have any record of him either, Alex."},
                {"speaker": "user", "text": "of course you know who Felix is"},
            ],
        },
    )

    assert response.status_code == 200
    call = panel_module._test_calls[-1]
    messages = json.dumps(call["messages"])
    assert "I don't have any record of a Felix" not in messages
    # Another robot's line and Alex's own questions stay: shared hearing holds.
    assert "I don't have any record of him either" in messages
    assert "do you remember who Felix is" in messages


def test_identity_talk_is_not_mistaken_for_a_memory_denial(panel_module):
    assert panel_module._is_memory_denial(
        "I don't have any record of that, Alex."
    ) is True
    assert panel_module._is_memory_denial(
        "I don't have any subjective experience of the kind you mean."
    ) is False


def test_short_followup_still_retrieves_using_the_transcript(panel_module):
    """"what's going on" has no searchable terms of its own."""
    _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "text": "what's going on",
            "history": [
                {"speaker": "user", "text": "Felix is going to come over in a little bit"},
                {"speaker": "blue", "text": "I'll put the kettle on."},
                {"speaker": "user", "text": "what's going on"},
            ],
        },
    )

    assert "Felix is going to come over" in panel_module._test_memory.searched[-1]


def test_memory_failures_never_break_a_turn(panel_module):
    def explode(*args, **kwargs):
        raise RuntimeError("chromadb is rebuilding")

    panel_module.bt.memory_system.search_memories = explode
    panel_module.bt.memory_system._build_facts_block = explode

    response = _client(panel_module).post(
        "/panel/turn", json={"speaker": "blue", "text": "who is coming over?"}
    )

    assert response.status_code == 200
    system = panel_module._test_calls[-1]["messages"][0]["content"]
    assert "<earlier_sessions>" in system


def test_turn_rejects_unknown_speaker(panel_module):
    response = _client(panel_module).post(
        "/panel/turn", json={"speaker": "robot-four", "text": "Hello"}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "unknown speaker"


def test_turn_does_not_repeat_name_acknowledgement_before_speech(panel_module):
    panel_module.bt.call_llm = lambda messages, **kwargs: {
        "choices": [{"message": {"content": "I completely agree with that."}}]
    }

    response = _client(panel_module).post(
        "/panel/turn",
        json={"speaker": "hexia", "text": "Hexia, do you agree?"},
    )

    assert response.status_code == 200
    assert "head_gesture" not in response.get_json()


def test_camera_request_uses_chat_tool_pipeline(panel_module):
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "text": "Blue, what do you see?",
            "history": [
                {"speaker": "user", "text": "Blue, what do you see?"},
            ],
        },
    )

    assert response.status_code == 200
    call = panel_module._test_calls[-1]
    assert call["pipeline"] == "tools"
    assert call["messages"][-1] == {
        "role": "user",
        "content": "Blue, what do you see?",
    }
    assert call["kwargs"]["robot"] == "blue"
    assert call["kwargs"]["system_addendum"]
    assert call["kwargs"]["_pre_selection"].primary_tool.tool_name == "capture_camera"


def test_short_followup_keeps_hexia_identity_topic_and_own_history(panel_module):
    topic = (
        "is another ai possible? an ai not based on extraction but oriented "
        "on human flourishing"
    )
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "text": "what did you say",
            "topic": topic,
            "history": [
                {"speaker": "user", "text": "what do you think"},
                {
                    "speaker": "hexia",
                    "text": "I think extraction remains the central obstacle.",
                },
                {"speaker": "user", "text": "what did you say"},
            ],
            "settings": {
                "hexia": {
                    "role": "no",
                    "slang": "dry Gen X wit",
                    "documents": ["hexia-notes.pdf"],
                }
            },
        },
    )

    assert response.status_code == 200
    call = panel_module._test_calls[-1]
    assert call["pipeline"] == "conversation"
    assert call["messages"][-1]["role"] == "user"
    assert "Alex's exact words: what did you say" in call["messages"][-1]["content"]
    assert "Your required answer is NO" in call["messages"][-1]["content"]
    assert "Never invent something another robot supposedly said" in call["messages"][-1]["content"]
    assert {
        "role": "assistant",
        "content": "I think extraction remains the central obstacle.",
    } in call["messages"]
    system = call["messages"][0]["content"]
    assert "Your identity is Hexia" in system
    assert "You are never Blue or Casper" in system
    assert "The name Blue always means the separate robot Blue" in system
    assert "The human speaking in user messages is Alex" in system
    assert f"active discussion topic is: {topic}" in system
    assert "Your assigned position is: no" in system
    assert "A bare 'no' means argue that the topic's proposal is not possible" in system


@pytest.mark.parametrize(
    "text,active,targets,explicit,name_only",
    [
        ("hexia", "pico", ["hexia"], True, True),
        (
            "what's your response to Casper's point",
            "hexia",
            ["hexia"],
            False,
            False,
        ),
        (
            "who do you agree with more Hexia or Casper",
            "blue",
            ["blue"],
            False,
            False,
        ),
        ("Hexia, respond to Casper's point", "pico", ["hexia"], True, False),
        ("Blue and Hexia, compare your positions", "pico", ["blue", "hexia"], True, False),
        ("Blue and Hexia are wrong", "pico", ["pico"], False, False),
        ("everyone, give me your view", "blue", ["blue", "hexia", "pico"], True, False),
        ("what did Blue say?", "", [], False, False),
        ("what do you think Hexia", "", ["hexia"], True, False),
    ],
)
def test_panel_routing_distinguishes_addressee_from_subject(
    panel_module, text, active, targets, explicit, name_only
):
    result = panel_module._resolve_panel_routing(text, active)

    assert result["targets"] == targets
    assert result["explicit"] is explicit
    assert result["nameOnly"] is name_only


def test_panel_route_endpoint_uses_current_listener(panel_module):
    response = _client(panel_module).post(
        "/panel/route",
        json={
            "text": "who do you agree with more, Hexia or Casper?",
            "activeRobot": "blue",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["targets"] == ["blue"]
    assert response.get_json()["explicit"] is False
