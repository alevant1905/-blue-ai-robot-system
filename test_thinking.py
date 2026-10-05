"""Whether Blue thinks before he answers, and what that costs the request.

Run with: python -m pytest test_thinking.py

On 2026-10-05, after LM Studio reloaded qwen3.8-27b, 116 of 116 harness calls
reasoned before answering and 81% of the tokens generated were hidden
reasoning: a spoken "what's your favorite music?" spent 700 of 751 tokens
thinking (17.5 s). Three calls came back empty or cut because the reasoning
used the whole budget — a reading report's 2,048 tokens, and two guard
retries' 500 and 900. Alex's call: no thinking for greetings, acks and short
replies, voice small talk and class introductions; thinking for real
questions, planning, opinions and document work. Retries never think.

The phrases below are the 10-05 harness turns and real turns from
conversation_log (ids given where they are Alex's own words).

SAFETY: execute_tool and both model transports are stubbed (the chat fixture
from test_chat_pipeline); requests.post is replaced wherever the real
LMStudioClient is exercised. No request leaves for LM Studio.
"""

import json
import types

import pytest
import requests

import bluetools as bt
from blue.server import tool_pipeline
from blue.server.thinking import (THINK_OFF, THINK_ON,
                                  THINKING_ALLOWANCE_TOKENS, thinking_for_turn)
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------

NO_THINKING = [
    # greetings and check-ins
    ("hi blue", {}),
    ("hi", {}),
    ("how are you doing?", {"identity_kind": "self_state"}),
    ("Hi Blue, how you doing?", {}),                          # 8633
    ("bonjour Blue, comment ça va?", {}),
    ("what have you been up to?", {"identity_kind": "evolution"}),
    ("I'm doing okay. What about you?", {}),                  # 8875
    ("pretty good and you?", {}),                             # 9383
    ("can you hear me?", {"voice": True}),
    ("Hexia. Hexia. Hexia. Hexia.", {}),                      # 9609
    # bare acknowledgements and short replies
    ("ok", {}), ("hmm", {}), ("cool", {}), ("never mind", {}),
    ("thanks, that helps", {"voice": True}),
    ("yes", {}), ("nope", {}), ("huh?", {}),
    ("thanks. sorry for snapping", {}),
    ("sorry, testing the connection", {}),
    ("pretty tired, long week of teaching", {}),
    ("we bought it!", {}),                                    # 8785
    # class greetings and introductions
    ("say hi to the students", {"voice": True}),
    ("we're in front of the DH399 class right now. do you want to say hello "
     "to everyone?", {"voice": True}),
    ("tell everyone a bit about yourself", {"voice": True}),
    ("can you tell the students a bit about yourself?", {"voice": True}),
    ("the girls are back, say hi to them", {"voice": True}),
    ("Introduce yourself to the class.", {}),                 # 9745
    # voice small talk
    ("what's your favorite music?", {"voice": True}),
    ("nori is sleeping on the floor. everything is quiet", {"voice": True}),
    ("the girls are at dance tonight", {"voice": True}),
    ("i had a rough day", {"voice": True}),
    # a forced call that is the whole job
    ("remind me to call the dentist", {"forced_tool": "create_reminder"}),
    ("what's the whether like today", {"voice": True, "forced_tool": "get_weather"}),
    ("what do you see in front of you right now?", {"forced_tool": "capture_camera"}),
    # the kids' page
    ("can you tell me a story about a dog", {"kid": True, "voice": True}),
    # the selector's greeting flag counts on a few words only
    ("sushi is great", {"is_greeting": True}),
]

THINKING = [
    # questions of substance, opinions, why
    ("what do you think makes a good lecture?", {}),
    ("i've been thinking about whether AI agents will replace a lot of office "
     "jobs", {}),
    ("i'm not so sure. a lot of it seems like hype to me", {}),
    ("ok, push back on something I've said today", {}),
    ("why that?", {}),
    ("Why", {}),                                              # 9189
    ("how are you different from chat gpt?", {"voice": True}),
    ("are you conscious?", {"voice": True, "identity_kind": "selfhood"}),
    ("tell me something funny", {}),
    # long-form and continuations
    ("explain what an AI agent is in simple terms", {}),
    ("go on", {}),
    ("keep going", {}),
    ("try again, simpler", {}),
    ("what else?", {"voice": True}),
    ("present your reading report to the class as if you were a student",
     {"voice": True}),
    # recall
    ("what did we talk about yesterday?", {"identity_kind": "shared_recall"}),
    ("do you remember what we talked about with autogpt?", {}),
    ("what is your earliest memory?", {"voice": True}),
    ("what do you remember about me?", {"voice": True}),
    # planning
    ("what's on for today?", {}),
    ("any ideas for making the lab more hands-on?", {}),
    ("Can you introduce the course?", {}),                   # 9427: the syllabus
    # questions without a question mark
    ("Is autoGPT a type of harness", {}),                     # 10057
    ("it looks fine. tell me her birthday", {}),              # 8863
    ("i dont know. thats a great question. what do you think", {}),  # 9435
    # being told he got it wrong
    ("its not lab 5", {}),                                    # 10021
    ("the calendar is still not updated", {}),                # 9471
    # document work
    ("what do you think of this https://www.theguardian.com/technology/2026/"
     "sep/15/syd-barrett-ai", {}),
    ("", {"has_attachment": True}),
    ("what are we covering in dh399?", {"forced_tool": "search_documents"}),
    # "sure" to an offer of real work is the go-ahead, not an ack
    ("sure", {"prev_reply": "Want me to sketch a lesson plan around it?"}),
    # the selector's flag is a substring match: "they" has "hey" in it
    ("which theory is better, and why do they disagree?", {"is_greeting": True}),
]


@pytest.mark.parametrize("text,kwargs", NO_THINKING)
def test_no_thinking(text, kwargs):
    assert thinking_for_turn(text, **kwargs) == THINK_OFF


@pytest.mark.parametrize("text,kwargs", THINKING)
def test_thinking(text, kwargs):
    assert thinking_for_turn(text, **kwargs) == THINK_ON


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------

@pytest.fixture
def fresh(monkeypatch):
    """No cached refusal, no budget lookup over HTTP."""
    monkeypatch.setattr(bt, "_REASONING_REFUSED_BY", set())
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": "qwen/qwen3.8-27b"})
    monkeypatch.setattr(bt, "_lm_input_budget", lambda: 100_000)


def _payload(thinking, **kw):
    kw.setdefault("include_tools", False)
    kw.setdefault("force_tool", None)
    return bt._lm_studio_payload([{"role": "user", "content": "why?"}],
                                 iteration=1, tool_scope="full",
                                 thinking=thinking, **kw)


def test_thinking_on_asks_for_medium_with_room_for_the_reasoning(fresh):
    payload = _payload(THINK_ON)
    assert payload["reasoning_effort"] == "medium"
    assert payload["max_tokens"] == bt._chat_max_tokens() + THINKING_ALLOWANCE_TOKENS


def test_thinking_off_asks_for_none_and_keeps_the_cap(fresh):
    payload = _payload(THINK_OFF)
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == bt._chat_max_tokens()


def test_no_decision_sends_no_field(fresh):
    assert "reasoning_effort" not in _payload(None)


def test_a_forced_document_keeps_its_long_cap_plus_the_allowance(fresh):
    payload = _payload(THINK_ON, include_tools=True, force_tool="create_document")
    assert payload["max_tokens"] == (bt._LONG_ARGUMENT_MAX_TOKENS
                                     + THINKING_ALLOWANCE_TOKENS)


def test_the_chat_page_sends_the_decision(chat):
    chat.ask("what do you make of memory?")
    assert chat.model.main[-1]["reasoning_effort"] == "medium"
    assert chat.model.main[-1]["max_tokens"] == (bt._chat_max_tokens()
                                                 + THINKING_ALLOWANCE_TOKENS)

    chat.ask("what's your favorite music?", voice=True)
    assert chat.model.main[-1]["reasoning_effort"] == "none"
    assert chat.model.main[-1]["max_tokens"] == bt._chat_max_tokens()

    chat.ask("hi blue")                     # the greeting fast path
    assert chat.model.main[-1]["reasoning_effort"] == "none"

    chat.ask('[Attached document: notes.pdf]\n"""\n'
             + "- a point about lectures\n" * 60
             + '"""\nwhat do you make of these notes?')
    assert chat.model.main[-1]["reasoning_effort"] == "medium"


def test_panel_keeps_the_model_default(chat):
    """Panel calls process_with_tools too, and is a separate change."""
    bt.process_with_tools([{"role": "user", "content": "what do you make of memory?"}],
                          user_name="Alex", voice=True)
    assert "reasoning_effort" not in chat.model.main[-1]


def test_a_refused_field_is_dropped_and_the_call_made_again(fresh, monkeypatch, capsys):
    sent = []

    def post(payload, timeout=120):
        sent.append(dict(payload))
        if len(sent) == 1:
            response = requests.Response()
            response.status_code = 400
            response._content = json.dumps({"error": {
                "message": "Invalid 'reasoning_effort' value: 'medium'.",
                "param": "reasoning_effort"}}).encode()
            raise requests.exceptions.HTTPError("400", response=response)
        return {"choices": [{"message": {"role": "assistant", "content": "Fine."},
                             "finish_reason": "stop"}]}

    monkeypatch.setattr(bt, "_post_to_model", post)
    result = bt.call_lm_studio([{"role": "user", "content": "why?"}],
                               include_tools=False, thinking=THINK_ON)

    assert result["choices"][0]["message"]["content"] == "Fine."
    assert sent[0]["reasoning_effort"] == "medium"
    assert "reasoning_effort" not in sent[1]
    assert sent[1]["max_tokens"] == bt._chat_max_tokens()
    assert "refused reasoning_effort" in capsys.readouterr().out
    assert "reasoning_effort" not in _payload(THINK_ON), "sent again after a refusal"


# --------------------------------------------------------------------------
# Retries never think — on both transports
# --------------------------------------------------------------------------

class _Reply:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_a_guard_regeneration_sends_none_through_the_live_client(chat, monkeypatch):
    """The guards regenerate through bt._LM.chat — the LMStudioClient in
    bluetools.py, not blue/llm.py's. The field must reach the JSON body by
    name, and nothing else may ride in with it."""
    monkeypatch.setattr(bt._LM, "chat", types.MethodType(bt.LMStudioClient.chat, bt._LM))
    bodies = []

    def post(url, json=None, timeout=None, **kwargs):
        if url == bt._LM.base_url:
            bodies.append(json)
        return _Reply({"choices": [{"message": {
            "role": "assistant",
            "content": "Athena, Emmy and Vilda — and Stella, of course."},
            "finish_reason": "stop"}]})

    monkeypatch.setattr(bt.requests, "post", post)
    chat.model.queue("I don't have any record of your family, Alex.")
    reply = reply_of(chat.ask("do you remember our family?"))

    assert "don't have any record" not in reply.lower()
    assert chat.model.main[-1]["reasoning_effort"] == "medium"
    assert bodies, "the guard never regenerated through the client"
    for body in bodies:
        assert body["reasoning_effort"] == "none"
        assert set(body) <= {"model", "messages", "frequency_penalty",
                             "presence_penalty", "temperature", "max_tokens",
                             "reasoning_effort"}, sorted(body)


def test_call_llm_names_the_field_rather_than_passing_it_through(monkeypatch):
    """Everything in **kwargs lands in the JSON body; a declared parameter is
    what the refusal handling and the regen path can rely on."""
    import inspect
    for layer in (bt.call_llm, bt._raw_call_llm, bt.LMStudioClient.chat):
        assert "reasoning_effort" in inspect.signature(layer).parameters, layer
    seen = {}
    monkeypatch.setattr(bt._LM, "chat",
                        lambda messages, **kwargs: seen.update(kwargs) or {"choices": []})
    bt.call_llm([{"role": "user", "content": "hi"}], include_tools=False,
                reasoning_effort="none")
    assert seen["reasoning_effort"] == "none"


def test_a_tool_answer_retry_sends_none(monkeypatch):
    """direct_execute's two guard retries go through call_lm_studio."""
    calls = []

    def call(messages, include_tools=True, force_tool=None, iteration=1, **kw):
        calls.append(kw.get("thinking"))
        if len(calls) == 1:
            return {"choices": [{"message": {"role": "assistant", "content":
                    "I don't have real-time data on the World Cup."}}]}
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "Spain beat Brazil 2-1."}}]}

    monkeypatch.setattr(bt, "execute_tool", lambda *a, **k: "[stubbed web_search]")
    monkeypatch.setattr(bt, "call_lm_studio", call)
    response, _ = tool_pipeline.direct_execute(
        {"web_search"}, [{"role": "user", "content": "who won last night?"}],
        "web_search", {"query": "who won last night"}, "who won last night?",
        "blue", thinking=THINK_ON)

    assert response["choices"][0]["message"]["content"] == "Spain beat Brazil 2-1."
    assert calls == [THINK_ON, THINK_OFF]


def test_the_streamed_transport_puts_the_field_on_the_wire(monkeypatch):
    sent = {}

    class Stream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self):
            chunks = [
                {"model": "qwen/qwen3.8-27b",
                 "choices": [{"delta": {"content": "Hello."}}]},
                {"model": "qwen/qwen3.8-27b",
                 "choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"model": "qwen/qwen3.8-27b", "choices": [], "usage": {
                    "prompt_tokens": 35, "completion_tokens": 17,
                    "completion_tokens_details": {"reasoning_tokens": 0}}},
            ]
            return iter([b"data: " + json.dumps(c).encode() for c in chunks]
                        + [b"data: [DONE]"])

    def post(url, json=None, timeout=None, stream=False, **kwargs):
        sent.update(json)
        return Stream()

    monkeypatch.setattr(bt.requests, "post", post)
    result = bt._stream_from_model(
        {"messages": [], "reasoning_effort": "none"}, None)

    assert sent["reasoning_effort"] == "none"
    assert sent["stream_options"] == {"include_usage": True}
    assert result["choices"][0]["message"]["content"] == "Hello."
    assert result["model"] == "qwen/qwen3.8-27b"
    assert result["usage"]["completion_tokens_details"]["reasoning_tokens"] == 0


# --------------------------------------------------------------------------
# The log line
# --------------------------------------------------------------------------

def test_the_turn_logs_model_thinking_and_tokens(chat, capsys):
    chat.model.queue({
        "model": "qwen/qwen3.8-27b",
        "usage": {"prompt_tokens": 10440, "completion_tokens": 300,
                  "completion_tokens_details": {"reasoning_tokens": 120}},
        "choices": [{"message": {"role": "assistant",
                                 "content": "Memory is a strange thing to be made of."},
                     "finish_reason": "stop"}],
    })
    chat.ask("what do you make of memory?")
    out = capsys.readouterr().out

    assert ("[LM] model qwen/qwen3.8-27b, thinking on (sent medium), 1 call: "
            "prompt 10440t, reasoning 120t, completion 300t") in out


def test_a_model_change_is_named_once(monkeypatch, capsys):
    monkeypatch.setattr(bt, "_LM_MODEL_SEEN", {"id": None, "warned": set()})
    bt._lm_turn_reset()
    for model in ("qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "qwen/qwen3.8-27b"):
        bt._lm_turn_note({"model": model, "usage": {}}, {})
    out = capsys.readouterr().out

    assert out.count("[MODEL] WARNING") == 1
    assert "qwen/qwen3.6-27b -> qwen/qwen3.8-27b" in out
