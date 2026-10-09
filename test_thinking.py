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
    # ...and on a message that asks nothing
    ("hi blue", {"is_greeting": True}),
    ("hey there", {"is_greeting": True}),
    ("thanks!", {"is_greeting": True}),
    ("thanks for the help", {"is_greeting": True}),
    # agreeing is not arguing
    ("i agree", {}), ("i think so", {}), ("i guess so", {}), ("i guess", {}),
    ("i agree with you", {}),
    ("thanks! that's what i thought", {}),
    ("that's not bad", {}),
    # "again" in news is not a redo
    ("we are celebrating athenas birthday again tomorrow with her friends", {}),  # 9179
    # a name with no comma, before a statement, stays a statement
    ("blue is great", {"voice": True}),
    ("hexia can see you", {"voice": True}),
    # needing a rest is not a request
    ("i need a nap", {"voice": True}),
    ("i'd like that", {}),                    # no offer on the table
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
    # a stray greeting flag: the selector's matched "hey" in "they" until
    # 7a9f70b, and the greeting fast path still takes a short message that
    # opens on "sup" ("supervised…")
    ("which theory is better, and why do they disagree?", {"is_greeting": True}),
    ("are they conscious?", {"is_greeting": True}),
    ("why do they disagree?", {"is_greeting": True}),
    ("what is supervised learning?", {"is_greeting": True}),   # "sup"
    ("explain supervised learning", {"is_greeting": True}),
    # the greeting fast path flags any short message opening on hi or hey
    ("hey blue, what's RAG?", {"is_greeting": True}),
    ("hey, that's wrong", {"is_greeting": True}),
    # a correction is one spoken or typed
    ("the calendar is still not updated", {"voice": True}),   # 9471
    ("its not lab 5", {"voice": True}),                       # 10021
    ("dh201 actually starts on sept 16 not sept 9", {"voice": True}),  # 9485
    ("you're still getting Athena's age wrong.", {"voice": True}),     # 9239
    ("I said I'm working on my courses again.", {}),          # 9103
    ("I said I'm working on my courses again.", {"voice": True}),
    # a redo
    ("i want to hear it again", {}),                          # 9683
    ("huh check the syllabus again", {"voice": True}),        # 9941
    # the robot's name spoken without a comma
    ("blue what do you think about the reading", {"voice": True}),
    ("Hexia what do you think of the new syllabus", {"voice": True}),
    ("ok blue tell me about agents", {"voice": True}),
    # requests worded as statements
    ("Hey Blue, I was wondering if you could help me plan the dh399 lecture", {}),
    ("I'd like a lesson plan for friday", {}),
    ("any thoughts on the reading", {}),
    ("curious what you think of the three body problem", {}),
    ("yes please draft it", {}),
    ("i'd like that", {"prev_reply": "I could draft it now if you'd like."}),
    # markdown around the question
    ("**what** do you think", {}),
    ("> what do you think of this quote", {}),
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


def test_thinking_on_asks_for_the_lighter_setting_with_room_for_the_reasoning(fresh):
    payload = _payload(THINK_ON)
    assert payload["reasoning_effort"] == "low"
    assert payload["max_tokens"] == bt._chat_max_tokens() + THINKING_ALLOWANCE_TOKENS


def test_thinking_off_asks_for_none_and_keeps_the_cap(fresh):
    payload = _payload(THINK_OFF)
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == bt._chat_max_tokens()


def test_no_decision_sends_no_field(fresh):
    assert "reasoning_effort" not in _payload(None)


@pytest.mark.parametrize("tool", ["create_document", "send_gmail"])
def test_a_forced_call_does_not_think(fresh, tool):
    """Its answer is the call. Thinking, a forced send_gmail had 9,728 tokens,
    and the reasoning streams where the stop on prose never looks: minutes of
    hidden deliberation (S4 final review)."""
    payload = _payload(THINK_ON, include_tools=True, force_tool=tool)
    assert payload["tool_choice"] == "required"
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == bt._LONG_ARGUMENT_MAX_TOKENS


def test_a_forced_send_thinks_neither_on_the_call_nor_on_its_retry(chat):
    """"send an email to stella": the forced call wrote words, and the retry
    after it is a retry."""
    chat.model.queue("Sure — who is Stella, and what should it say?",
                     "I haven't sent it yet — what should the email say?")
    chat.ask("send an email to stella")

    forced, retry = chat.model.main[0], chat.model.main[1]
    assert forced["tool_choice"] == "required"
    assert (forced["reasoning_effort"], forced["max_tokens"]) == (
        "none", bt._LONG_ARGUMENT_MAX_TOKENS)
    assert "tools" not in retry
    assert (retry["reasoning_effort"], retry["max_tokens"]) == (
        "none", bt._chat_max_tokens())


def test_the_reply_after_a_forced_call_keeps_the_turn_s_decision(chat):
    chat.model.queue(
        {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {
                "name": "send_gmail", "arguments": json.dumps(
                    {"to": "stella@example.com", "subject": "Hi",
                     "body": "Hi Stella"})}}]},
            "finish_reason": "tool_calls"}]},
        "Sent — Stella has your hello.")
    chat.ask("send an email to stella@example.com saying hi")

    assert chat.model.main[0]["reasoning_effort"] == "none"
    assert [c["tool"] for c in chat.executed] == ["send_gmail"]
    assert chat.model.main[-1]["reasoning_effort"] == "low"


def test_the_chat_page_sends_the_decision(chat):
    # Short messages, so the visible reply has its short cap
    # (blue/server/reply_budget.py) and the allowance goes on top of it. An
    # opinion asked for is an idea turn, with an idea's cap.
    chat.ask("what do you make of memory?")
    assert chat.model.main[-1]["reasoning_effort"] == "low"
    assert chat.model.main[-1]["max_tokens"] == (
        bt._reply_budget.IDEA_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS)

    chat.ask("where does your memory live?")
    assert chat.model.main[-1]["reasoning_effort"] == "low"
    assert chat.model.main[-1]["max_tokens"] == (
        bt._reply_budget.TYPED_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS)

    chat.ask("what's your favorite music?", voice=True)
    assert chat.model.main[-1]["reasoning_effort"] == "none"
    assert chat.model.main[-1]["max_tokens"] == bt._reply_budget.SPOKEN_REPLY_TOKENS

    chat.ask("what do you make of memory, and of how it changes what a robot "
             "like you can be for a family?")
    assert chat.model.main[-1]["reasoning_effort"] == "low"
    assert chat.model.main[-1]["max_tokens"] == (bt._chat_max_tokens()
                                                 + THINKING_ALLOWANCE_TOKENS)

    chat.ask("hi blue")                     # the greeting fast path
    assert chat.model.main[-1]["reasoning_effort"] == "none"

    chat.ask('[Attached document: notes.pdf]\n"""\n'
             + "- a point about lectures\n" * 60
             + '"""\nwhat do you make of these notes?')
    assert chat.model.main[-1]["reasoning_effort"] == "low"


@pytest.fixture
def greeting_flags(monkeypatch):
    """The is_greeting each decision was made with, to show a test reached
    the flag it is about."""
    flags = []
    real = bt._thinking.thinking_for_turn

    def spy(text, **kwargs):
        flags.append(kwargs.get("is_greeting"))
        return real(text, **kwargs)

    monkeypatch.setattr(bt._thinking, "thinking_for_turn", spy)
    return flags


@pytest.mark.parametrize("text", [
    "hey blue, what's RAG?",            # the greeting fast path
    "good morning, why do they disagree?",
    "hello, what is supervised learning?",
    # Over eight words, so the selector's flag (whole words since 7a9f70b).
    "hi blue, which theory is better and why do they disagree?",
])
def test_a_question_carrying_the_greeting_flag_still_thinks(
        chat, greeting_flags, monkeypatch, text):
    """A greeting in front of a question. "are they conscious?" and "what is
    supervised learning?" stood here, and once the selector matched greetings
    as whole words they carried no flag and skipped on every run."""
    from blue.tool_selector.detectors.documents import DocumentsDetector
    monkeypatch.setattr(DocumentsDetector, "_refresh_library",
                        classmethod(lambda cls: None))
    for attr in ("_lib_phrases", "_lib_rare_tokens"):
        monkeypatch.setattr(DocumentsDetector, attr, set())
    monkeypatch.setattr(DocumentsDetector, "_lib_tokens_by_doc", [])

    chat.ask(text)
    assert greeting_flags and greeting_flags[-1] is True
    assert chat.model.main[-1]["reasoning_effort"] == "low"


@pytest.mark.parametrize("text", ["hi blue", "hey there", "thanks!"])
def test_a_greeting_still_does_not(chat, greeting_flags, text):
    chat.ask(text)
    assert greeting_flags[-1] is True
    assert chat.model.main[-1]["reasoning_effort"] == "none"


@pytest.mark.parametrize("text", ["the calendar is still not updated", "its not lab 5"])
def test_a_spoken_correction_thinks_like_a_typed_one(chat, text):
    chat.ask(text, voice=True)
    assert chat.model.main[-1]["reasoning_effort"] == "low"
    chat.ask(text)
    assert chat.model.main[-1]["reasoning_effort"] == "low"


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
                "message": "Invalid 'reasoning_effort' value: 'low'.",
                "param": "reasoning_effort"}}).encode()
            raise requests.exceptions.HTTPError("400", response=response)
        return {"choices": [{"message": {"role": "assistant", "content": "Fine."},
                             "finish_reason": "stop"}]}

    monkeypatch.setattr(bt, "_post_to_model", post)
    result = bt.call_lm_studio([{"role": "user", "content": "why?"}],
                               include_tools=False, thinking=THINK_ON)

    assert result["choices"][0]["message"]["content"] == "Fine."
    assert sent[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in sent[1]
    assert sent[1]["max_tokens"] == bt._chat_max_tokens()
    assert "refused reasoning_effort" in capsys.readouterr().out
    assert "reasoning_effort" not in _payload(THINK_ON), "sent again after a refusal"


# --------------------------------------------------------------------------
# The loaded model decides whether thinking is asked for at all
# --------------------------------------------------------------------------
# Alex, 10-07: "use whatever is loaded" — no model is asked for by name. That
# morning qwen3.6-35b-a3b, loaded for a class demo, reasoned at "low" for
# 2,145-12,166 characters and ran out of max_tokens with no words on 4 of
# its 11 chat calls (10125, 10143, 10147, 10151). Replayed on qwen3.8-27b at
# "low", the three short ones finished in 287-507 characters of reasoning.

THE_27B, THE_35B = "qwen/qwen3.8-27b", "qwen/qwen3.6-35b-a3b"


@pytest.mark.parametrize("model, effort", [
    (THE_27B, "low"),
    ("Qwen/Qwen3.8-27B", "low"),
    (THE_35B, "none"),
    ("google/gemma-4-31b", "none"),
    (None, "none"),                 # not known yet: no thinking either
])
def test_only_a_model_known_to_finish_its_reasoning_is_asked_to_think(
        fresh, monkeypatch, model, effort):
    monkeypatch.delenv("BLUE_THINKING_MODELS", raising=False)
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": model})
    payload = _payload(THINK_ON)
    assert payload["reasoning_effort"] == effort
    assert payload["max_tokens"] == bt._chat_max_tokens() + (
        THINKING_ALLOWANCE_TOKENS if effort == "low" else 0)
    assert _payload(THINK_OFF)["reasoning_effort"] == "none"


def test_the_short_message_cap_holds_when_the_model_may_not_think(fresh, monkeypatch):
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": THE_35B})
    payload = _payload(THINK_ON, reply_cap=bt._reply_budget.TYPED_REPLY_TOKENS)
    assert (payload["reasoning_effort"], payload["max_tokens"]) == (
        "none", bt._reply_budget.TYPED_REPLY_TOKENS)


def test_blue_thinking_models_is_the_list(fresh, monkeypatch, capsys):
    monkeypatch.setenv("BLUE_THINKING_MODELS", f" {THE_35B.upper()} , google/gemma-4-31b")
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": THE_35B})
    assert _payload(THINK_ON)["reasoning_effort"] == "low"
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": THE_27B})
    assert _payload(THINK_ON)["reasoning_effort"] == "none"
    assert (f"[MODEL] {THE_27B} is not in BLUE_THINKING_MODELS — answering "
            "without thinking") in capsys.readouterr().out

    monkeypatch.setenv("BLUE_THINKING_MODELS", "")
    assert _payload(THINK_ON)["reasoning_effort"] == "none"


def test_the_next_call_follows_the_model_that_answered(fresh, monkeypatch, capsys):
    """No "model" key goes out, so a swap shows first in the response, which
    names the model that answered; the very next call is decided for it, and
    the context size is read again."""
    sent = []
    budget = {"value": 22_937, "at": 1e12}
    monkeypatch.setattr(bt, "_lm_budget_cache", budget)

    def post(payload, timeout=120):
        sent.append(dict(payload))
        return {"model": THE_35B, "choices": [{"message": {
            "role": "assistant", "content": "Fine."}, "finish_reason": "stop"}]}

    monkeypatch.setattr(bt, "_post_to_model", post)
    for _ in range(2):
        bt.call_lm_studio([{"role": "user", "content": "why?"}],
                          include_tools=False, thinking=THINK_ON)

    assert [p["reasoning_effort"] for p in sent] == ["low", "none"]
    assert not any("model" in p for p in sent)
    assert bt._lm_loaded_model["id"] == THE_35B
    assert budget["at"] == 0.0
    out = capsys.readouterr().out
    assert f"[MODEL] {THE_35B} (sent low)" in out
    assert f"[MODEL] {THE_35B} (sent none)" in out


class _Models:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


EMBEDDER = {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings",
            "state": "loaded", "loaded_context_length": 2048}


def _loaded(model, ctx):
    return {"id": model, "type": "vlm", "state": "loaded", "loaded_context_length": ctx}


def test_the_lookup_reads_the_language_model_not_the_embedder(monkeypatch):
    """An embedding model is listed as loaded too; its 2,048 tokens would have
    sized every chat payload, and its id decided the thinking."""
    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models([
        EMBEDDER, _loaded(THE_35B, 32768),
        {"id": THE_27B, "type": "vlm", "state": "not-loaded",
         "max_context_length": 262144}]))
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": THE_27B})

    assert bt._detect_lm_context_size() == 32768
    assert bt._lm_loaded_model["id"] == THE_35B


def test_with_two_models_loaded_the_one_that_answered_stays(monkeypatch):
    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models([
        _loaded(THE_27B, 32768), _loaded(THE_35B, 65536)]))
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": THE_35B})
    assert bt._detect_lm_context_size() == 65536
    assert bt._lm_loaded_model["id"] == THE_35B

    # Neither answered last: which one will is not known, so no thinking.
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": "google/gemma-4-31b"})
    assert bt._detect_lm_context_size() == 32768
    assert bt._lm_loaded_model["id"] is None


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
    assert chat.model.main[-1]["reasoning_effort"] == "low"
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

    # A short message: its reply cap is named too (blue/server/reply_budget.py),
    # here an idea turn's.
    assert ("[LM] model qwen/qwen3.8-27b, thinking on (sent low), "
            "reply cap 450t, 1 call: "
            "prompt 10440t, reasoning 120t, completion 300t") in out


def test_a_guard_retry_logs_what_it_sent_and_spent(chat, capsys):
    """The regenerations go through _raw_call_llm and bt._LM.chat, after the
    turn's [LM] line — and they are the calls that came back empty on 10-05."""
    chat.model.queue(
        "I don't have any record of your family, Alex.",
        {"model": "qwen/qwen3.8-27b",
         "usage": {"prompt_tokens": 5000, "completion_tokens": 20,
                   "completion_tokens_details": {"reasoning_tokens": 0}},
         "choices": [{"message": {"role": "assistant", "content":
                                  "Athena, Emmy and Vilda — and Stella, of course."},
                      "finish_reason": "stop"}]})
    chat.ask("do you remember our family?")
    out = capsys.readouterr().out

    assert ("[LM] retry (sent none): prompt 5000t, reasoning 0t, "
            "completion 20t, finish stop") in out
    assert "WARNING" not in out.split("[LM] retry", 1)[1].splitlines()[0]


def test_a_retry_that_reasons_anyway_or_comes_back_empty_is_named():
    spent = {"usage": {"prompt_tokens": 4000, "completion_tokens": 900,
                       "completion_tokens_details": {"reasoning_tokens": 900}},
             "choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    line = bt._lm_retry_line(spent, "none")
    assert "reasoning 900t" in line and "finish length" in line
    assert "EMPTY reply" in line
    assert "WARNING: reasoned 900t though sent none" in line

    assert "failed: HTTP 400" in bt._lm_retry_line({"error": "HTTP 400: bad"}, "none")
    assert "(sent -)" in bt._lm_retry_line({"choices": []}, None)


def test_the_turn_line_warns_when_none_was_ignored(monkeypatch):
    # A response's model becomes the loaded model's id: kept to this test.
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    bt._lm_turn_reset()
    bt._LM_TURN.thinking = THINK_OFF
    bt._lm_turn_note({"model": "m", "usage": {
        "prompt_tokens": 100, "completion_tokens": 300,
        "completion_tokens_details": {"reasoning_tokens": 250}}},
        {"reasoning_effort": "none"})
    assert "WARNING: reasoned 250t though sent none" in bt._lm_turn_summary()

    bt._lm_turn_reset()
    bt._lm_turn_note({"model": "m", "usage": {
        "completion_tokens_details": {"reasoning_tokens": 250}}},
        {"reasoning_effort": "medium"})
    assert "WARNING" not in bt._lm_turn_summary()


def test_a_model_change_is_named_once(monkeypatch, capsys):
    monkeypatch.setattr(bt, "_LM_MODEL_SEEN", {"id": None, "warned": set()})
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    bt._lm_turn_reset()
    for model in ("qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "qwen/qwen3.8-27b"):
        bt._lm_turn_note({"model": model, "usage": {}}, {})
    out = capsys.readouterr().out

    assert out.count("[MODEL] WARNING") == 1
    assert "qwen/qwen3.6-27b -> qwen/qwen3.8-27b" in out


def test_the_thinking_setting_is_low_unless_overridden(monkeypatch):
    """Alex chose the lighter setting (2026-10-06); BLUE_THINKING_EFFORT can
    raise it, and anything else falls back to low rather than being sent."""
    monkeypatch.delenv("BLUE_THINKING_EFFORT", raising=False)
    assert bt._thinking_effort() == "low"
    for value, expected in (("medium", "medium"), (" HIGH ", "high"),
                            ("none", "low"), ("max", "low"), ("", "low")):
        monkeypatch.setenv("BLUE_THINKING_EFFORT", value)
        assert bt._thinking_effort() == expected


# --------------------------------------------------------------------------
# A request for work, which a check-in must not offer as "what happened to
# you lately" (continuity lately_line, 2026-10-08)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "don't stop at secondary points. do the whole thing!",       # 10-01
    "help me find the cheapest rtx6000 pro new or used that ships to canada",
    "Let me what you remember about me",
    "blue, can you write the intro for tomorrow's lecture",
    "great. now summarize the second chapter for me",
    "keep going with the reading report",
    "do the whole thing!",
    "don't summarize it, quote the syllabus",
    "I'd like a lesson plan for friday's DH399 class",
])
def test_a_request_for_work_is_work(text):
    from blue.server.thinking import asks_for_work
    assert asks_for_work(text)


@pytest.mark.parametrize("text", [
    "i see it as a part of the process toward tenure track work",
    "i was thinking of using lm studio to run local models. what do yo think?",
    "what is the difference between a chatbot and an AI agent?",
    "anyways lm studio is sufficient. not a computer science class",
    "i might take you with me to dh201 tomorrow",
    "that means i may have a chance to apply for a permanent position next year",
    # "do" before who does it asks what he thinks (S5 review)
    "Do you think local models will change how students write?",
    "don't you think the second reading was too long for first years?",
    "do students even read the syllabus anymore",
])
def test_a_remark_or_a_question_is_not_work(text):
    from blue.server.thinking import asks_for_work
    assert not asks_for_work(text)
