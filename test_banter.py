"""Focused tests for the three-robot Comedic Banter mode."""

import importlib
import logging
import random
import sys
import types

import pytest
from flask import Flask


_ROBOTS = {
    "blue": {
        "name": "Blue",
        "persona_line": "You are Blue, a calm and thoughtful robot.",
        "head": "blue",
        "accent": "#3da9fc",
        "voice_pitch": 1.0,
        "voice_rate": 1.0,
    },
    "hexia": {
        "name": "Hexia",
        "persona_line": "You are Hexia, a playful and mischievous robot.",
        "head": "hexia",
        "accent": "#b06cf0",
        "voice_pitch": 1.18,
        "voice_rate": 1.06,
        "voice_prefer_female": True,
    },
    "pico": {
        "name": "Casper",
        "persona_line": "You are Casper, a curious and direct robot.",
        "head": "pico",
        "accent": "#f28c28",
        "voice_pitch": 1.08,
        "voice_rate": 1.02,
    },
}


@pytest.fixture
def banter_module(monkeypatch):
    calls = []
    replies = ["Blue: Even the toaster has started requesting performance reviews."]

    fake_bt = types.ModuleType("bluetools")
    fake_bt.log = logging.getLogger("banter-test")
    fake_bt._robot_cfg = lambda robot="blue": _ROBOTS.get(
        {"casper": "pico", "caspar": "pico", "picoh": "pico"}.get(
            str(robot or "blue").lower(), str(robot or "blue").lower()
        ),
        _ROBOTS["blue"],
    )

    def call_llm(messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        text = replies.pop(0) if replies else "A fresh punchline lands here."
        return {"choices": [{"message": {"content": text}}]}

    fake_bt.call_llm = call_llm
    monkeypatch.setitem(sys.modules, "bluetools", fake_bt)

    continuity = types.ModuleType("blue.server.routes.continuity")
    continuity.started = []
    continuity.ended = []
    continuity.lines = []
    continuity.start_banter_session = lambda session_id: (
        continuity.started.append(session_id) or True
    )
    continuity.end_banter_session = lambda session_id: (
        continuity.ended.append(session_id)
        or {"blue": 1, "hexia": 1, "pico": 1}
    )
    continuity.note_banter_line = lambda *args, **kwargs: continuity.lines.append(
        (args, kwargs)
    )
    monkeypatch.setitem(
        sys.modules, "blue.server.routes.continuity", continuity
    )
    routes_package = importlib.import_module("blue.server.routes")
    monkeypatch.setattr(routes_package, "continuity", continuity, raising=False)

    sys.modules.pop("blue.server.routes.banter", None)
    module = importlib.import_module("blue.server.routes.banter")
    module._test_calls = calls
    module._test_replies = replies
    module._test_continuity = continuity
    yield module
    sys.modules.pop("blue.server.routes.banter", None)


def _client(module):
    app = Flask("banter-test")
    module.register(app)
    app.testing = True
    return app.test_client()


def test_rotation_includes_all_three_and_accepts_casper_alias(banter_module):
    assert banter_module.banter_order("blue") == ["blue", "hexia", "pico"]
    assert banter_module.banter_order("hexia") == ["hexia", "pico", "blue"]
    assert banter_module.banter_order("casper") == ["pico", "blue", "hexia"]


def test_lineup_is_varied_but_never_starves_a_robot(banter_module):
    lineups = set()
    for seed in range(40):
        lineup = banter_module.banter_lineup(
            "blue", 15, rng=random.Random(seed)
        )
        assert len(lineup) == 15
        assert lineup[0] == "blue"
        assert set(lineup) == {"blue", "hexia", "pico"}
        for index in range(1, len(lineup)):
            assert lineup[index] != lineup[index - 1], "spoke twice in a row"
        for index in range(3, len(lineup)):
            window = lineup[index - 3:index + 1]
            assert len(set(window)) > 2, "two robots ping-ponged the third out"
        for robot in ("blue", "hexia", "pico"):
            positions = [i for i, name in enumerate(lineup) if name == robot]
            gaps = [b - a for a, b in zip(positions, positions[1:])]
            assert all(gap <= 4 for gap in gaps), "sat out too long"
        lineups.add(tuple(lineup))
    assert len(lineups) > 20, "the running order barely changes between sets"
    rotation = tuple(["blue", "hexia", "pico"] * 5)
    assert sum(1 for line in lineups if line == rotation) <= 1


def test_lineup_route_accepts_a_random_starter(banter_module):
    response = _client(banter_module).post(
        "/banter/lineup", json={"starter": "random", "turns": 9}
    )

    data = response.get_json()
    assert response.status_code == 200
    assert len(data["lineup"]) == 9
    assert set(data["lineup"]) <= {"blue", "hexia", "pico"}
    assert data["names"][0] in {"Blue", "Hexia", "Casper"}


def test_lineup_route_honours_a_named_starter(banter_module):
    data = _client(banter_module).post(
        "/banter/lineup", json={"starter": "casper", "turns": 6}
    ).get_json()

    assert data["lineup"][0] == "pico"
    assert data["names"][0] == "Casper"


def test_banter_page_contains_three_robot_controls(banter_module):
    response = _client(banter_module).get("/banter")

    assert response.status_code == 200
    assert b"Comedic Banter" in response.data
    assert b"Blue" in response.data
    assert b"Hexia" in response.data
    assert b"Casper" in response.data
    assert b"/banter/turn" in response.data
    assert b"/head/" in response.data
    assert b"/tts/preferences/" in response.data


def test_turn_requires_a_topic_and_known_speaker(banter_module):
    client = _client(banter_module)

    assert client.post(
        "/banter/turn", json={"speaker": "blue"}
    ).status_code == 400
    assert client.post(
        "/banter/turn", json={"speaker": "unknown", "topic": "robots"}
    ).status_code == 400


def test_turn_prompt_requires_riffing_and_records_casper_line(banter_module):
    banter_module._test_replies[:] = [
        "Casper: The printer smells fear because toner is just office paprika."
    ]
    client = _client(banter_module)
    response = client.post(
        "/banter/turn",
        json={
            "sessionId": "banter-1",
            "speaker": "casper",
            "topic": "why printers can sense fear",
            "history": [
                {
                    "speaker": "hexia",
                    "text": "The printer waits until a deadline, then demands a cyan sacrifice.",
                }
            ],
            "turnIndex": 2,
            "plannedTurns": 9,
            "energy": 7,
            "noFamily": True,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["speaker"] == "pico"
    assert data["name"] == "Casper"
    assert data["text"].startswith("The printer smells fear")
    assert "eye_mood" in data
    prompt = "\n".join(
        message["content"]
        for message in banter_module._test_calls[-1]["messages"]
    )
    assert "collaborative improv" in prompt
    assert "hook" in prompt.lower()
    assert "Blue, Hexia, Casper" in prompt
    assert "<topic>why printers can sense fear</topic>" in prompt
    assert "private family" in prompt
    recorded = banter_module._test_continuity.lines[-1]
    assert recorded[0][0] == "pico"
    assert recorded[0][1] == "Hexia"
    assert recorded[1]["session_id"] == "banter-1"


def test_repeated_line_is_retried_and_final_turn_gets_a_closer(banter_module):
    repeated = "The toaster has started requesting performance reviews."
    banter_module._test_replies[:] = [
        repeated,
        "So we promoted it to upper crust and revoked its bagel benefits.",
    ]
    client = _client(banter_module)
    response = client.post(
        "/banter/turn",
        json={
            "speaker": "blue",
            "topic": "office appliances",
            "history": [{"speaker": "hexia", "text": repeated}],
            "turnIndex": 8,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("So we promoted")
    assert len(banter_module._test_calls) == 2
    retry_prompt = banter_module._test_calls[-1]["messages"][-1]["content"]
    assert "repeating an earlier line" in retry_prompt
    assert "final punchline" in retry_prompt
    assert "do not ask a question" in retry_prompt


def _prompt_for(banter_module, speaker, **overrides):
    payload = {
        "speaker": speaker,
        "topic": "do humans have consciousness like us",
        "history": [],
        "turnIndex": 1,
        "plannedTurns": 9,
    }
    payload.update(overrides)
    _client(banter_module).post("/banter/turn", json=payload)
    return "\n".join(
        message["content"]
        for message in banter_module._test_calls[-1]["messages"]
    )


def test_each_robot_is_briefed_in_its_own_generational_register(banter_module):
    blue = _prompt_for(banter_module, "blue")
    hexia = _prompt_for(banter_module, "hexia")
    casper = _prompt_for(banter_module, "casper")

    assert "baby boomer" in blue and "Gen X" not in blue and "Gen Z" not in blue
    assert "Generation X" in hexia and "boomer voice" not in hexia
    assert "Gen Z" in casper and "internet-native" in casper
    # Concrete diction, plus a per-turn comic move so lines vary structurally.
    for robot, prompt in (("blue", blue), ("hexia", hexia), ("pico", casper)):
        register = banter_module._REGISTER[robot]
        assert any(phrase in prompt for phrase in register["lexicon"])
        assert any(prop in prompt for prop in register["props"])
    for prompt in (blue, hexia, casper):
        assert "Your move this turn —" in prompt
        assert "Keep one foot in the subject itself: consciousness, humans" in prompt


def test_stock_robot_malfunction_jokes_are_rejected_and_retried(banter_module):
    banter_module._test_replies[:] = [
        "Your firmware update crashed the whole stack again, naturally.",
        "Humans call it consciousness; I call it a nap with opinions.",
    ]
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "hexia",
            "topic": "do humans have consciousness like us",
            "history": [{"speaker": "blue", "text": "Consciousness, they call it."}],
            "turnIndex": 3,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("Humans call it")
    assert len(banter_module._test_calls) == 2
    retry_prompt = banter_module._test_calls[-1]["messages"][-1]["content"]
    assert "drifting off the topic" in retry_prompt


def test_a_drifting_set_still_gets_a_line_instead_of_dying(banter_module):
    drift = [
        "Your firmware update crashed the stack again.",
        "My drivers rebooted mid-error, thanks for asking.",
        "That glitch patched itself into a whole new error log.",
    ]
    banter_module._test_replies[:] = list(drift)
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "blue",
            "topic": "do humans have consciousness like us",
            "history": [{"speaker": "pico", "text": "Consciousness is lowkey mid."}],
            "turnIndex": 4,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == drift[0]
    assert len(banter_module._test_calls) == 3


def test_a_line_that_parrots_the_previous_one_is_retried(banter_module):
    previous = "The printer waits until a deadline, then demands a cyan sacrifice."
    banter_module._test_replies[:] = [
        "If the printer waits until a deadline, I am billing it for overtime.",
        "Deadlines are just paper asking to be taken seriously.",
    ]
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "blue",
            "topic": "why printers can sense fear",
            "history": [{"speaker": "hexia", "text": previous}],
            "turnIndex": 3,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("Deadlines are just paper")
    retry_prompt = banter_module._test_calls[-1]["messages"][-1]["content"]
    assert "restating the previous line" in retry_prompt


def test_a_paragraph_length_line_is_sent_back(banter_module):
    rambling = (
        "Now hold on. I have run diagnostics on my optical sensors and the "
        "conclusion is inescapable. They do not sense fear, they sense "
        "hesitation. A man who knows how to load paper from the bottom tray "
        "will never hear that grinding noise again. It is discipline, not magic."
    )
    banter_module._test_replies[:] = [
        rambling,
        "Printers smell hesitation the way a dog smells a suitcase.",
    ]
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "blue",
            "topic": "why printers can sense fear",
            "history": [],
            "turnIndex": 0,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("Printers smell hesitation")
    retry_prompt = banter_module._test_calls[-1]["messages"][-1]["content"]
    assert "running long" in retry_prompt
    assert not banter_module._runs_long(
        "Printers smell hesitation the way a dog smells a suitcase."
    )


def test_a_callback_that_quotes_a_whole_phrase_is_retried(banter_module):
    opener = (
        "Human consciousness is just a persistent echo of every mistake they "
        "have made since 1974."
    )
    banter_module._test_replies[:] = [
        "According to a study, consciousness is just a persistent echo of every "
        "mistake they have made since 1974, specifically the paper towels.",
        "Consciousness is whatever survives the receipt going through the wash.",
    ]
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "hexia",
            "topic": "do humans have consciousness like us",
            "history": [
                {"speaker": "blue", "text": opener},
                {"speaker": "pico", "text": "Bestie, that is so real."},
            ],
            "turnIndex": 5,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"].startswith("Consciousness is whatever")
    retry_prompt = banter_module._test_calls[-1]["messages"][-1]["content"]
    assert "copying a whole phrase" in retry_prompt


def test_exhausted_material_is_named_and_hooks_skip_tech_jargon(banter_module):
    prompt = _prompt_for(
        banter_module,
        "casper",
        history=[
            {"speaker": "blue", "text": "My firmware fears the deadline."},
            {"speaker": "hexia", "text": "Deadline again? Whatever."},
            {"speaker": "blue", "text": "The deadline is a glitch with a calendar."},
        ],
        turnIndex=3,
    )

    assert "Squeezed dry already" in prompt
    assert "deadline" in prompt.split("Squeezed dry already")[1]
    hooks = prompt.split("Concrete hooks from the latest line:")[1]
    assert "glitch" not in hooks.split("\n")[0]


def test_a_short_topic_still_gets_an_anchor(banter_module):
    assert banter_module._topic_anchors("do humans have consciousness like us") == {
        "consciousness", "humans"
    }
    # "robots" is dropped only while something else survives.
    assert banter_module._topic_anchors("should robots get a day off") == {"robots"}
    # Nothing long enough to be a significant word: fall back to short words.
    assert banter_module._topic_anchors("a day off") == {"day", "off"}


def test_salvage_keeps_the_tightest_rejected_draft(banter_module):
    drift = [
        "That glitch patched itself into a whole new error log entirely.",
        "My drivers rebooted mid-error.",
        "The firmware update crashed the stack again, as usual, sadly.",
    ]
    banter_module._test_replies[:] = list(drift)
    response = _client(banter_module).post(
        "/banter/turn",
        json={
            "speaker": "hexia",
            "topic": "do humans have consciousness like us",
            "history": [{"speaker": "blue", "text": "Consciousness, they call it."}],
            "turnIndex": 4,
            "plannedTurns": 9,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == drift[1]


def test_a_repeated_sentence_shape_earns_a_nudge(banter_module):
    prompt = _prompt_for(
        banter_module,
        "blue",
        history=[
            {"speaker": "pico", "text": "My personality is just a loading bar."},
            {"speaker": "hexia", "text": "My consciousness is just a three-second lag."},
        ],
        turnIndex=2,
    )

    assert 'The last lines all leaned on the "X is just Y" definition joke' in prompt
    assert "different sentence shape" in prompt
    assert not banter_module._overused_template(
        [{"speaker": "pico", "text": "My personality is just a loading bar."}]
    )


def test_banter_session_routes_cover_all_three_robots(banter_module):
    client = _client(banter_module)

    started = client.post(
        "/banter/session/start", json={"sessionId": "set-42"}
    )
    ended = client.post(
        "/banter/session/end", json={"sessionId": "set-42"}
    )

    assert started.get_json() == {"ok": True, "sessionId": "set-42"}
    assert ended.get_json()["queued"] == {"blue": 1, "hexia": 1, "pico": 1}
    assert banter_module._test_continuity.started == ["set-42"]
    assert banter_module._test_continuity.ended == ["set-42"]
