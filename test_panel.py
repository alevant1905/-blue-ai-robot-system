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


def test_the_floor_lasts_exactly_one_answer(panel_module):
    """A robot that has finished replying stops listening.

    Before this, whoever spoke last kept the floor, so an unaddressed remark to
    the room was quietly answered by the previous speaker.
    """
    html = _client(panel_module).get("/panel").get_data(as_text=True)

    # Released in the finally, so a failed or errored turn releases it too.
    assert "if(!heldForFollowUp)setActive('')" in html
    # ...and the flag is only raised by a bare name.
    assert "if(routing.nameOnly){heldForFollowUp=true;" in html


def test_a_bare_name_still_holds_the_floor(panel_module):
    """"Hexia" on its own IS the act of addressing her — she waits for the
    sentence that follows rather than being dropped immediately."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)

    held = html.index("heldForFollowUp=true")
    name_only = html.index("routing.nameOnly")
    assert name_only < held, "the floor is held for something other than a bare name"


def test_interrupting_releases_the_floor(panel_module):
    """Cut off mid-answer is still an answer that ended."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    body = html[html.index("function interruptReply("):]
    body = body[:body.index("async function submitUtterance(")]
    assert "setActive('')" in body


def test_the_page_describes_the_one_answer_floor(panel_module):
    """The old copy promised the opposite behaviour."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "they keep it until you clearly call someone else" not in html
    assert "the floor returns to the room" in html


def test_an_unaddressed_remark_is_told_to_use_a_name(panel_module):
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "Everyone heard that. Call Blue, Hexia, or Casper by name" in html
    assert "'Panel is listening. Call a robot by name.'" in html


@pytest.mark.parametrize(
    "held,text,targets",
    [
        # "Everyone" hands the floor to all three; the follow-up reaches all three.
        (["blue", "hexia", "pico"], "what do you make of that?",
         ["blue", "hexia", "pico"]),
        # A single held robot still works, list form or bare string.
        (["hexia"], "and why is that?", ["hexia"]),
        ("hexia", "and why is that?", ["hexia"]),
        # An explicit name overrides whoever is holding it.
        (["blue", "hexia", "pico"], "Casper, what about you?", ["pico"]),
        # Nobody holding means nobody answers.
        ([], "and why is that?", []),
        ("", "and why is that?", []),
        # Junk in the held list is ignored rather than routed to.
        (["blue", "nobody", "blue"], "go on", ["blue"]),
    ],
)
def test_the_floor_can_be_held_by_several_robots(panel_module, held, text, targets):
    """Saying "everyone" used to leave only Casper listening: the page
    acknowledged each robot in turn and the last one won."""
    result = panel_module._resolve_panel_routing(text, held)
    assert result["targets"] == targets


def test_the_route_endpoint_accepts_a_list_floor(panel_module):
    response = _client(panel_module).post(
        "/panel/route",
        json={"text": "go on then", "activeRobot": ["blue", "hexia", "pico"]},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["targets"] == ["blue", "hexia", "pico"]
    assert data["activeRobots"] == ["blue", "hexia", "pico"]


def test_everyone_holds_the_floor_for_all_three_in_the_page(panel_module):
    """The page must set the floor from the target list, not from whatever the
    acknowledgement loop happened to light last."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "heldForFollowUp=true;setActive(targets);" in html
    # The floor is a list throughout.
    assert "activeRobots=[]" in html
    assert "activeRobot:activeRobots" in html


# --- Continuous discussion ------------------------------------------------


def test_the_continuous_running_order_is_random_and_never_doubles_up(panel_module):
    """Random, but not so random that anyone speaks twice in a row or vanishes."""
    orders = set()
    for _ in range(40):
        lineup = panel_module.panel_lineup(9)
        assert len(lineup) == 9
        assert set(lineup) <= set(panel_module.PANEL_ROBOTS)
        assert all(a != b for a, b in zip(lineup, lineup[1:]))
        assert set(lineup) == set(panel_module.PANEL_ROBOTS)
        orders.add(tuple(lineup))
    assert len(orders) > 1, "a fixed rotation is not a random order"


def test_the_next_lineup_does_not_hand_the_last_speaker_two_turns(panel_module):
    for _ in range(30):
        assert panel_module.panel_lineup(6, avoid="hexia")[0] != "hexia"
        # Casper answers to several names; the seam must respect all of them.
        assert panel_module.panel_lineup(6, avoid="casper")[0] != "pico"


def test_alex_can_name_who_opens_the_discussion(panel_module):
    """His choice of opener outranks the no-repeat rule: it is a decision about
    this discussion, not an accident of the last one."""
    for _ in range(20):
        assert panel_module.panel_lineup(9, first="hexia")[0] == "hexia"
        assert panel_module.panel_lineup(9, avoid="pico", first="pico")[0] == "pico"
        # Casper answers to several names.
        assert panel_module.panel_lineup(9, first="casper")[0] == "pico"
    # No choice means the running order picks, still avoiding a repeat.
    assert all(
        panel_module.panel_lineup(9, avoid="blue", first="")[0] != "blue"
        for _ in range(20)
    )


def test_the_lineup_endpoint_takes_the_chosen_opener(panel_module):
    response = _client(panel_module).post(
        "/panel/lineup", json={"turns": 4, "avoid": "hexia", "starter": "hexia"}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["lineup"][0] == "hexia"
    assert data["names"][0] == "Hexia"


def test_the_lineup_endpoint_serves_the_page_a_running_order(panel_module):
    response = _client(panel_module).post(
        "/panel/lineup", json={"turns": 5, "avoid": "blue"}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert len(data["lineup"]) == 5
    assert data["lineup"][0] != "blue"
    assert data["names"][0] in {"Blue", "Hexia", "Casper"}


def test_a_continuous_turn_needs_no_utterance_from_alex(panel_module):
    """Nobody prompts the robot: the transcript and the topic are the prompt."""
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "mode": "continuous",
            "text": "",
            "topic": "Whether cities should ban cars downtown",
            "history": [
                {"speaker": "user", "text": "Talk it over between you."},
                {"speaker": "blue", "text": "Access improves when streets serve people."},
            ],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["speaker"] == "hexia"
    call = panel_module._test_calls[-1]
    assert call["pipeline"] == "conversation"
    system = call["messages"][0]["content"]
    assert "CONTINUOUSLY" in system
    assert "OPEN DISCUSSION MANNERS" in system
    assert "Nobody called on you" in system
    assert "Blue: Access improves when streets serve people." in system
    requirement = call["messages"][-1]["content"]
    assert "<panel_turn_requirement>" in requirement
    assert "The last thing said: Blue: Access improves when streets serve people." in requirement
    # The human-led framing must not leak into a turn Alex never asked for.
    assert "Alex has addressed you by name" not in system
    assert "Alex's exact words" not in requirement


def test_a_continuous_turn_answers_the_other_robots_not_only_the_topic(panel_module):
    _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "pico",
            "mode": "continuous",
            "topic": "Whether cities should ban cars downtown",
            "history": [
                {"speaker": "blue", "text": "Access improves when streets serve people."},
                {"speaker": "hexia", "text": "Deliveries would collapse within a week."},
            ],
        },
    )

    call = panel_module._test_calls[-1]
    prompt = call["messages"][0]["content"] + call["messages"][-1]["content"]
    assert "take up the last speaker's actual point by name" in prompt
    assert "Do not repeat a point the transcript already contains" in prompt
    # Both other robots' lines are in the transcript it answers from.
    assert "Hexia: Deliveries would collapse within a week." in call["messages"][0]["content"]
    assert {
        "role": "user",
        "content": "[Blue, another robot in the panel, said]: Access improves when streets serve people.",
    } in call["messages"]


def test_continuous_chatter_never_reaches_the_tool_pipeline(panel_module):
    """Robot discussion is not a command. Letting the selector see it is how a
    panel that talks about photographs ends up firing the real camera."""
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "mode": "continuous",
            "topic": "what do you see in street photography",
            "history": [
                {"speaker": "hexia", "text": "what do you see when a street empties out"},
            ],
        },
    )

    assert response.status_code == 200
    assert panel_module._test_calls[-1]["pipeline"] == "conversation"


def test_a_continuous_turn_still_carries_the_household_memory(panel_module):
    _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "blue",
            "mode": "continuous",
            "topic": "What Felix would make of all this",
            "history": [{"speaker": "hexia", "text": "Alex's brother would disagree."}],
        },
    )

    system = panel_module._test_calls[-1]["messages"][0]["content"]
    assert "<known_facts>" in system
    assert "Brother Name: Felix" in system
    assert "<earlier_sessions>" in system


def test_a_continuous_turn_is_grounded_on_the_line_it_is_answering(panel_module):
    """Alex said nothing, so the last spoken line is the live utterance. Without
    that, a discussion that turns to his family gets none of the grounding the
    same question typed into chat would have had."""
    _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "pico",
            "mode": "continuous",
            "topic": "How households divide their time",
            "history": [
                {"speaker": "blue", "text": "Alex's daughters would settle this quickly."},
            ],
        },
    )

    assert "<family>" in panel_module._test_calls[-1]["messages"][0]["content"]
    assert "daughters" in panel_module._test_memory.searched[-1]


def _material(label, fresh=False):
    source = {
        "kind": "pdf",
        "label": label,
        "url": "",
        "brief": f"An excerpt from {label} about kerb space and delivery windows.",
    }
    if fresh:
        source["fresh"] = True
    return source


def test_a_document_handed_over_mid_discussion_is_taken_up(panel_module):
    """Appending it silently to a list the panel has carried for ten turns
    changes nothing about the next turn. Alex added it because he wants it
    used now."""
    response = _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "mode": "continuous",
            "topic": "Whether cities should ban cars downtown",
            "history": [{"speaker": "blue", "text": "Deliveries would adapt."}],
            "materials": [
                _material("older-study.pdf"),
                _material("kerb-space-2026.pdf", fresh=True),
            ],
        },
    )

    assert response.status_code == 200
    system = panel_module._test_calls[-1]["messages"][0]["content"]
    # The material itself is marked, and the turn is told to use it.
    assert "kerb-space-2026.pdf (pdf) — JUST HANDED TO THE PANEL" in system
    assert "older-study.pdf (pdf)]" in system
    assert "just put kerb-space-2026.pdf in front of the panel" in system
    assert "Alex has just handed the panel kerb-space-2026.pdf" in system
    assert "do not pretend to have read more of it" in system


def test_material_already_in_hand_is_not_announced_again(panel_module):
    """Greeting the same document every turn is how it stops being read."""
    _client(panel_module).post(
        "/panel/turn",
        json={
            "speaker": "hexia",
            "mode": "continuous",
            "topic": "Whether cities should ban cars downtown",
            "history": [{"speaker": "blue", "text": "Deliveries would adapt."}],
            "materials": [_material("kerb-space-2026.pdf")],
        },
    )

    system = panel_module._test_calls[-1]["messages"][0]["content"]
    assert "kerb-space-2026.pdf" in system
    assert "JUST HANDED TO THE PANEL" not in system
    assert "has just handed the panel" not in system


def test_a_prepared_turn_lets_a_live_one_have_the_model_first(panel_module, monkeypatch):
    """Nobody has asked for a speculative turn yet, so it must not hold the one
    local model in front of a turn Alex is actually waiting on."""
    import contextlib

    priorities = []

    @contextlib.contextmanager
    def recording_slot(foreground=False):
        priorities.append(foreground)
        yield

    monkeypatch.setattr(panel_module, "llm_slot", recording_slot)
    client = _client(panel_module)
    discussion = {
        "speaker": "blue",
        "mode": "continuous",
        "topic": "Whether cities should ban cars downtown",
        "history": [{"speaker": "hexia", "text": "Deliveries would collapse."}],
    }
    client.post("/panel/turn", json={**discussion, "speculative": True})
    client.post("/panel/turn", json=discussion)
    # A human-led turn is never speculative, whatever the page claims.
    client.post(
        "/panel/turn",
        json={"speaker": "blue", "text": "Blue, your view?", "speculative": True},
    )

    assert priorities == [False, True, True]


def test_a_continuous_turn_without_a_topic_or_transcript_is_refused(panel_module):
    response = _client(panel_module).post(
        "/panel/turn", json={"speaker": "blue", "mode": "continuous"}
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_a_human_led_turn_still_requires_an_utterance(panel_module):
    response = _client(panel_module).post(
        "/panel/turn", json={"speaker": "blue", "topic": "anything"}
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "text is required"


def test_the_page_runs_the_discussion_itself_in_continuous_mode(panel_module):
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert 'id="continuousChk"' in html
    assert "async function runContinuous()" in html
    assert "mode:'continuous'" in html
    # The order comes from the server's weighted lineup, with a local fallback.
    assert "'/panel/lineup'" in html
    assert "while(lineup.length&&lineup[0]===lastRobotTurn)lineup.shift();" in html
    # The queue is kept ahead and read without awaiting: the next speaker has to
    # be known while the current one is still talking.
    assert "function nextSpeaker(){" in html
    assert "async function nextSpeaker" not in html
    assert "if(lineup.length<4)refillLineup();" in html


def test_the_next_turn_is_prepared_while_the_last_one_is_still_speaking(panel_module):
    """Speech is the slow part. Asking for the next turn only after it ends
    leaves a hole in the conversation the length of a whole generation."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    # Requested after the line is added to the transcript and before it is
    # spoken, so the prepared answer really does respond to what was just said.
    assert re.search(r"addTurn\(ticket\.id.*?primeNextTurn\(\);\s*await speakAs\(", html, re.S)
    assert "let ticket=takePreparedTurn();" in html
    assert "speculative:!!speculative" in html


def test_a_prepared_turn_is_thrown_away_once_the_room_moves_on(panel_module):
    """It answered a conversation that no longer exists — Alex cut in, or the
    discussion was stopped — so it must never be spoken."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "ticket={id:id,basis:roomBasis()" in html
    assert "if(ticket.basis!==roomBasis()){dropTicket(ticket);return null;}" in html
    # Every line said — and every document handed over — moves it on.
    assert "history.push({speaker:speaker,text:text});historyVersion+=1;" in html
    assert "function roomBasis(){return historyVersion+'/'+materialsVersion;}" in html
    # Interrupting, stopping, and unticking all drop it.
    assert html.count("discardPreparedTurn()") >= 4


def test_the_pause_between_turns_is_adjustable_while_they_talk(panel_module):
    """A captured gap would only take effect the next time the panel started."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert 'id="paceRange"' in html
    assert 'type="range" min="0" max="8"' in html
    assert "await pauseBetweenTurns();" in html
    # Read live, and waited out in slices, so a drag is felt during the gap.
    assert "function paceMs(){const seconds=parseFloat(paceRange.value);" in html
    assert "const remaining=paceMs()-(Date.now()-started);" in html
    # The setting survives a reload with the rest of the panel settings.
    assert "pace:parseFloat(paceRange.value)" in html
    assert "if(typeof data.pace==='number'" in html


def test_alex_can_barge_into_a_running_discussion(panel_module):
    """Without this, a robot is always mid-turn and he can never get a word in."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "if(busy){if(!continuousOn())return;interruptReply(false,true);}" in html
    # An unaddressed remark is dropped in human-led mode but joins the discussion
    # when it is running on its own.
    assert "continuousOn()?'Heard. They will pick it up.'" in html


def test_the_page_lets_alex_choose_who_opens(panel_module):
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert 'id="starterSel"' in html
    assert 'value="pico">Casper</option>' in html
    # Only on a fresh discussion, and the choice clears the no-repeat memory so
    # it is not dropped for having just answered Alex.
    assert "async function openLineup()" in html
    assert "if(first)lastRobotTurn='';" in html
    assert "if(!lineupOpened){await openLineup();" in html


def test_the_page_can_pause_the_discussion_between_turns(panel_module):
    """Pausing is not stopping: the running order and anything already prepared
    survive it, and Alex can still ask them things while it is held."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert 'id="pauseBtn"' in html
    assert "function setPaused(on){" in html
    assert "if(paused){await sleep(200);continue;}" in html
    assert "pauseBtn.textContent=(paused&&live)?'Resume discussion':'Pause discussion';" in html
    # Nothing is prepared while it is held.
    assert "if(pendingTurn||!running||!continuousOn()||paused)return;" in html


def test_the_page_hands_a_document_over_mid_discussion(panel_module):
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "source.fresh=true;materials.push(source);materialsVersion+=1;" in html
    # A turn prepared before it arrived has not read it, so it is thrown away.
    assert "if(running){discardPreparedTurn();addNote('Alex hands the panel '" in html
    assert "function clearFreshMaterials()" in html


def test_a_robot_saying_stop_does_not_stop_the_panel(panel_module):
    """The microphone hears the robots too. A robot whose own line contained
    "stop" — "we should stop pretending" — was heard as Alex calling the room
    to order, and it cut itself off mid-sentence. The echo guard already knew
    those were its own words; it was simply consulted second."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "function classifyHeard(text){" in html
    assert html.index("isLikelyRobotEcho(heard)") < html.index("isStopCommand(heard)")
    # The handler asks once, and never tests for a stop before the echo guard.
    assert "const kind=classifyHeard(heard);if(kind==='echo')" in html
    assert "if(heard&&isStopCommand(heard)){interruptReply();return;}" not in html


def test_stopping_the_talking_stops_the_discussion(panel_module):
    """"Stop talking" that resumed a second later would just be ignoring him."""
    html = _client(panel_module).get("/panel").get_data(as_text=True)
    assert "if(!keepGoing&&continuousOn()){" in html
    assert "continuousChk.checked=false;saveSettings();" in html
