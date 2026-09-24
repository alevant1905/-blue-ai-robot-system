"""When the language model can't answer, say so — out of character.

Run with: python -m pytest test_model_failure.py

Every model failure used to become a line in Blue's own voice: "Hey there!"
(greeting path), "Done!" (a tool ran, its wording call failed) or "I'm having
trouble connecting." (tool loop). 105 of them are in conversation_log. Each was
spoken, saved, journaled and fed back on later turns — twelve copies in one
prompt on 2026-08-19, when LM Studio simply had no model loaded — and the
recovered model then invented stories from them ("the system was dropping my
context window").
"""

import requests
import pytest

import bluetools as bt
from blue_identity import is_failure_placeholder
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

NO_MODEL = '{"error":"No models loaded. Please load a model in the developer page."}'


def http_error(status, body):
    response = requests.models.Response()
    response.status_code = status
    response._content = body.encode()
    return requests.HTTPError(f"{status} Client Error", response=response)


@pytest.fixture(autouse=True)
def _dumps_go_to_tmp(tmp_path, monkeypatch):
    """_lm_studio_recover writes lm_studio_400_dump_*.json into the cwd."""
    monkeypatch.chdir(tmp_path)


def assistant_rows(chat):
    rows = []
    for args, kwargs in chat.saved:
        role = kwargs.get("role", args[1] if len(args) > 1 else None)
        if role == "assistant":
            rows.append(args)
    return rows


def test_no_model_on_a_greeting_is_an_honest_system_line(chat):
    chat.model.queue(http_error(400, NO_MODEL))
    response = chat.ask("hello")
    data = response.get_json()

    assert response.status_code == 200
    assert data["blue_error"] == "no_model"
    assert reply_of(response).startswith("[System:")
    assert "isn't loaded" in reply_of(response)
    assert reply_of(response) != "Hey there!"
    assert assistant_rows(chat) == [], "a failure is not something Blue said"
    assert "eye_mood" not in data


def test_no_model_on_a_streamed_check_in_is_not_trouble_connecting(chat):
    from blue.server.routes import stream as stream_routes
    stream_routes.open_stream("p-test")  # an unopened id silently takes the POST path
    chat.model.queue(http_error(400, NO_MODEL))
    response = chat.ask("how is blue today", stream_id="p-test")
    assert bt._LM_FAILURE.streamed is True, "the turn never used the streamed transport"
    assert response.get_json()["blue_error"] == "no_model"
    assert "trouble connecting" not in reply_of(response)


def test_a_failed_identity_turn_is_not_hidden_behind_a_canned_intro(chat):
    """The guards would call the dead model again and could swap the outage
    for the canned self-introduction."""
    chat.model.queue(requests.ConnectionError("refused"))
    response = chat.ask("tell us more about yourself")

    assert response.get_json()["blue_error"] == "unreachable"
    assert "J-space" not in reply_of(response)
    assert len(chat.model.payloads) == 1, "nothing retried against a dead model"


def test_a_read_timeout_is_named_as_one(chat):
    chat.model.queue(requests.ReadTimeout("read timed out"))
    response = chat.ask("hows your day going")
    assert response.get_json()["blue_error"] == "timeout"


def test_an_error_body_with_status_200_is_a_failure_too(chat):
    chat.model.queue({"error": "model not loaded"})
    response = chat.ask("hi")
    assert response.get_json()["blue_error"] == "unusable"
    assert "something went wrong" not in reply_of(response)


def test_hexias_page_names_hexia(chat):
    chat.model.queue(http_error(400, NO_MODEL))
    response = chat.ask("hi", robot="hexia")
    assert "Hexia's language model" in reply_of(response)


def test_placeholders_already_in_the_thread_are_dropped_with_their_question(chat):
    """Pair-drop: keeping the question would merge "Send it again now." into
    the live turn, with reflex tools available."""
    chat.model.queue("Yes, I'm here.")
    chat.client.post("/v1/chat/completions", json={"robot": "blue", "messages": [
        {"role": "user", "content": "Send it again now."},
        {"role": "assistant", "content": "I'm having trouble connecting."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hey there!"},
        {"role": "user", "content": "are you back?"},
    ]})
    shown = [m for m in chat.model.payloads[-1]["messages"] if m["role"] != "system"]
    text = " ".join(str(m.get("content") or "") for m in shown)
    assert "trouble connecting" not in text
    assert "Hey there!" not in text
    assert "Send it again now." not in text
    assert "are you back?" in text


@pytest.mark.parametrize("text,expected", [
    ("I'm having trouble connecting.", True),
    ("Hey there!", True),
    ("Done!", True),
    ("[System: Blue&#39;s language model isn&#39;t loaded in LM Studio.]", True),
    ("I had trouble connecting to the Guardian site earlier, but here are "
     "the headlines…", False),
    ("Hey there! Good to see you, Alex.", False),
    ("Done! I've set a reminder for 3pm.", False),
])
def test_only_failure_lines_count_as_failures(text, expected):
    assert is_failure_placeholder(text) is expected


def test_the_failure_kinds():
    import urllib3
    assert bt._classify_lm_failure(requests.ReadTimeout("x"), "") == "timeout"
    streamed_timeout = requests.ConnectionError(
        urllib3.exceptions.ReadTimeoutError(None, None, "read timed out"))
    assert bt._classify_lm_failure(streamed_timeout, "") == "timeout"
    assert bt._classify_lm_failure(requests.exceptions.ChunkedEncodingError("x"), "") == "dropped"
    assert bt._classify_lm_failure(requests.ConnectionError("refused"), "") == "unreachable"
    assert bt._classify_lm_failure(http_error(400, NO_MODEL), NO_MODEL) == "no_model"
    assert bt._classify_lm_failure(http_error(500, "boom"), "boom") == "server_error"


def test_the_chat_page_neither_speaks_nor_resends_a_failure():
    from blue.server.pages import chat as chat_page
    source = str(getattr(chat_page, "CHAT_HTML", "")) or open(
        chat_page.__file__, encoding="utf-8").read()
    branch = source.index("data.blue_error")
    assert branch < source.index("speak(reply)")
    assert "apiMessages.pop()" in source[branch:branch + 900]
