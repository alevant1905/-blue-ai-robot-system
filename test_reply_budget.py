"""A short message gets a short reply: the length follows the user's turn.

Run with: python -m pytest test_reply_budget.py

Live after 09-27 the median chat reply was 196 words, and 21 of 29 turns
without an attachment ran over 100 ("Is autoGPT a type of harness" -> 253).
On the 10-05 harness 20 of 98 turns of twelve words or fewer got more than
100 words, every one a turn that thought first: "what could go wrong?" 391,
"would you do it differently?" 392, "keep going" 618. A message of twelve
words or fewer that asks for nothing long now has its visible reply capped
(220 tokens typed, 120 spoken, the reasoning allowance on top), and a typed
question gets a short-message note beside its words.

The phrases are the 10-05 harness turns and real turns (conversation_log ids
where they are Alex's own words).

SAFETY: execute_tool and both model transports are stubbed (the chat fixture
from test_chat_pipeline); requests.post is replaced where the stream is
exercised. No request leaves for LM Studio.
"""

import json

import pytest

import bluetools as bt
from blue.server import runaway
from blue.server.reply_budget import (SHORT_TURN_NOTE, SPOKEN_REPLY_TOKENS,
                                      TYPED_REPLY_TOKENS, reply_budget,
                                      short_turn_note, visible_chars)
from blue.server.thinking import THINK_OFF, THINK_ON, THINKING_ALLOWANCE_TOKENS
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------

CAPPED = [
    # the harness's long replies to short questions
    ("what could go wrong?", {}),
    ("how would you grade something like that?", {}),
    ("would you do it differently?", {}),
    ("what do you think makes a good lecture?", {}),
    ("any ideas for making the lab more hands-on?", {}),
    ("explain what an AI agent is in simple terms", {}),
    ("give me an example from everyday life", {}),
    ("do you ever disagree with me?", {}),
    ("ok, push back on something I've said today", {}),
    ("what's something you're curious about lately?", {}),
    ("Is autoGPT a type of harness", {}),                     # 10057
    # short already, and kept so
    ("hi blue", {}),
    ("where are you right now?", {}),
    ("what did I say I was using it for?", {}),
    ("its not lab 5", {}),                                    # 10021
    # words that only look like a request for length
    ("let's go on a walk later", {}),
    ("what's going on?", {}),
    ("i plan to grade tonight", {}),
]

SPOKEN = [
    ("how are you different from chat gpt?", {"voice": True}),
    ("tell everyone a bit about yourself", {"voice": True}),
    ("what's your favorite music?", {"voice": True}),
]

UNCAPPED = [
    # more of what was just said
    ("go on", {}), ("keep going", {}), ("tell me more", {}),
    ("cool. can you tell us more about that?", {}),
    ("what else?", {}), ("please go on", {}), ("continue", {}),
    ("try again, simpler", {}),
    ("say that again", {"voice": True}),
    # depth asked for in so many words
    ("explain agents in detail", {}),
    ("walk me through it", {}),
    ("go deeper on the second one", {}),
    ("break it down for me", {}),
    # something long by name
    ("write me a letter to the dean", {}),
    ("draft an email to Stella about friday", {}),
    ("summarize the chapter", {}),
    ("make a list of the readings", {}),
    ("I'd like a lesson plan for friday", {}),
    ("can you tell me a story about a dog", {"voice": True}),
    ("give me 5 examples", {}),
    ("three ideas for the lab", {}),
    ("read me the email from Sara", {}),
    # recall of something long he said: <earlier_answers> comes back whole
    ("what were those ideas?", {}),
    ("what were the lab ideas you gave me last night?", {}),
    ("what did we talk about yesterday?", {}),
    ("do you remember what we talked about with autogpt?", {}),
    # an article, a document, an image
    ("what do you think of this https://www.theguardian.com/technology/2026/"
     "sep/15/syd-barrett-ai", {}),
    ("what do you make of these notes?", {"has_attachment": True}),
    # the caller's own sign: "sure" after "want me to draft it?"
    ("sure", {"depth_cue": True}),
    # not a short message
    ("i'm thinking of having my DH399 students build an agent that reads the "
     "news and emails them a digest", {}),
]


@pytest.mark.parametrize("text,kwargs", CAPPED)
def test_a_short_message_gets_the_typed_cap(text, kwargs):
    assert reply_budget(text, **kwargs) == TYPED_REPLY_TOKENS


@pytest.mark.parametrize("text,kwargs", SPOKEN)
def test_a_spoken_one_gets_the_spoken_cap(text, kwargs):
    assert reply_budget(text, **kwargs) == SPOKEN_REPLY_TOKENS


@pytest.mark.parametrize("text,kwargs", UNCAPPED)
def test_asking_for_length_lifts_the_cap(text, kwargs):
    assert reply_budget(text, **kwargs) is None


def test_the_note_goes_with_a_typed_question_that_thinks():
    """Where the long replies were. A greeting or a correction is short
    already, and a size in the note could pad it."""
    assert short_turn_note("what could go wrong?", thinking=THINK_ON) == SHORT_TURN_NOTE
    assert short_turn_note("ok, push back on something I've said today",
                           thinking=THINK_ON) == SHORT_TURN_NOTE
    assert short_turn_note("hi blue", thinking=THINK_OFF) == ""
    assert short_turn_note("its not lab 5", thinking=THINK_ON) == ""
    assert short_turn_note("how are you different from chat gpt?", voice=True,
                           thinking=THINK_ON) == ""
    assert short_turn_note("why is the sky blue?", kid=True, thinking=THINK_ON) == ""
    assert short_turn_note("what could go wrong?", thinking=None) == ""


def test_the_note_asks_for_a_ceiling_and_no_offer():
    """"about 100 words" is a target a one-line answer can be padded to; the
    offer to go deeper closed one reply in four on "If you want, I can…"."""
    assert "under 100 words" in SHORT_TURN_NOTE
    assert "offer" not in SHORT_TURN_NOTE.lower()


# --------------------------------------------------------------------------
# The cut
# --------------------------------------------------------------------------

def test_a_reply_past_its_cap_ends_on_its_last_full_sentence():
    text = ("The digest will be confidently wrong. " * 20).strip()
    held = runaway.cut_to_length(text, 200)
    assert len(held) <= 200
    assert held.endswith("wrong.")


def test_a_cut_inside_a_list_drops_the_dangling_number():
    text = ("1. Credentials leak into a repo.\n2. The API rate-limits the class."
            "\n3. The summary invents a headline nobody wrote anywhere at all")
    held = runaway.cut_to_length(text, len(text) - 30)
    assert held == "1. Credentials leak into a repo.\n2. The API rate-limits the class."


def test_a_reply_under_its_cap_is_left_alone():
    assert runaway.cut_to_length("Short and done.", 900) == "Short and done."


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------

@pytest.fixture
def fresh(monkeypatch):
    """No cached refusal, no budget lookup over HTTP."""
    monkeypatch.setattr(bt, "_REASONING_REFUSED_BY", set())
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": "qwen/qwen3.8-27b"})
    monkeypatch.setattr(bt, "_lm_input_budget", lambda: 100_000)


def _payload(thinking, reply_cap, **kw):
    kw.setdefault("include_tools", False)
    kw.setdefault("force_tool", None)
    return bt._lm_studio_payload([{"role": "user", "content": "why?"}],
                                 iteration=1, tool_scope="full",
                                 thinking=thinking, reply_cap=reply_cap, **kw)


def test_the_allowance_goes_on_top_of_the_cap(fresh):
    assert _payload(THINK_ON, 220)["max_tokens"] == 220 + THINKING_ALLOWANCE_TOKENS
    assert _payload(THINK_OFF, 220)["max_tokens"] == 220
    assert _payload(THINK_OFF, None)["max_tokens"] == bt._chat_max_tokens()


@pytest.mark.parametrize("tool,cap", [
    ("create_document", bt._LONG_ARGUMENT_MAX_TOKENS),
    ("create_reminder", bt._FORCED_SHORT_MAX_TOKENS),
])
def test_a_forced_call_keeps_its_own_room(fresh, tool, cap):
    payload = _payload(THINK_ON, 220, include_tools=True, force_tool=tool)
    assert payload["max_tokens"] == cap


def test_a_tool_that_carries_a_body_lifts_the_cap(fresh, monkeypatch):
    """A selector tie can offer send_gmail or create_document beside the
    reflex tools; at 220 tokens their call would be cut off mid-JSON."""
    def payload():
        return bt._lm_studio_payload(
            [{"role": "user", "content": "send it to stella"}], include_tools=True,
            force_tool=None, iteration=1, tool_scope="reflex", thinking=THINK_OFF,
            reply_cap=220)

    monkeypatch.setattr(bt._TURN_OFFER, "tools", (), raising=False)
    assert payload()["max_tokens"] == 220
    monkeypatch.setattr(bt._TURN_OFFER, "tools", ("send_gmail",), raising=False)
    assert payload()["max_tokens"] == bt._chat_max_tokens()


def _reply(content, finish_reason="stop", reasoning=0):
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 9000, "completion_tokens": reasoning + 50,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}


LONG = " ".join(f"Point {i} is a whole sentence about what could go wrong."
                for i in range(40))


def test_a_thinking_reply_past_the_cap_is_held_to_it(fresh, monkeypatch, capsys):
    """Thinking, max_tokens is the cap plus 1,536: the words have room to run
    on, so they are held to the cap as well, at a sentence end."""
    sent = []

    def post(payload, timeout=120):
        sent.append(dict(payload))
        return _reply(LONG, reasoning=400)

    monkeypatch.setattr(bt, "_post_to_model", post)
    result = bt.call_lm_studio([{"role": "user", "content": "what could go wrong?"}],
                               include_tools=False, thinking=THINK_ON,
                               reply_cap=TYPED_REPLY_TOKENS)

    text = result["choices"][0]["message"]["content"]
    assert sent[0]["max_tokens"] == TYPED_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS
    assert len(text) <= visible_chars(TYPED_REPLY_TOKENS)
    assert text.endswith("wrong.") and text.startswith("Point 0")
    assert result["choices"][0]["finish_reason"] == "length"
    assert "[LENGTH] reply held to its cap" in capsys.readouterr().out


def test_a_model_that_refused_the_switch_keeps_its_room(fresh, monkeypatch):
    """Without reasoning_effort it may think by its own default, inside
    max_tokens: 220 tokens could all go to that. The words are held to the
    cap instead."""
    bt._REASONING_REFUSED_BY.add("qwen/qwen3.8-27b")
    sent = []

    def post(payload, timeout=120):
        sent.append(dict(payload))
        return _reply(LONG)

    monkeypatch.setattr(bt, "_post_to_model", post)
    result = bt.call_lm_studio([{"role": "user", "content": "what could go wrong?"}],
                               include_tools=False, thinking=THINK_ON,
                               reply_cap=TYPED_REPLY_TOKENS)
    assert "reasoning_effort" not in sent[0]
    assert sent[0]["max_tokens"] == bt._chat_max_tokens()
    assert len(result["choices"][0]["message"]["content"]) <= visible_chars(
        TYPED_REPLY_TOKENS)


def test_without_a_cap_a_long_reply_is_untouched(fresh, monkeypatch):
    monkeypatch.setattr(bt, "_post_to_model",
                        lambda payload, timeout=120: _reply(LONG, reasoning=400))
    result = bt.call_lm_studio([{"role": "user", "content": "go on"}],
                               include_tools=False, thinking=THINK_ON)
    assert result["choices"][0]["message"]["content"] == LONG


def test_a_reply_the_reasoning_starved_is_asked_again_without_thinking(
        fresh, monkeypatch, capsys):
    """With the cap, the reasoning has 1,536 tokens; two of the harness's
    short turns reasoned for 1,945 and 2,062. That reply would be empty."""
    sent = []

    def post(payload, timeout=120):
        sent.append(dict(payload))
        if len(sent) == 1:
            return _reply("", finish_reason="length", reasoning=1756)
        return _reply("A few things, mostly the email step.")

    monkeypatch.setattr(bt, "_post_to_model", post)
    bt._lm_turn_reset()
    result = bt.call_lm_studio([{"role": "user", "content": "any ideas?"}],
                               include_tools=False, thinking=THINK_ON,
                               reply_cap=TYPED_REPLY_TOKENS)

    assert result["choices"][0]["message"]["content"] == (
        "A few things, mostly the email step.")
    assert [(p["reasoning_effort"], p["max_tokens"]) for p in sent] == [
        ("medium", TYPED_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS),
        ("none", TYPED_REPLY_TOKENS)]
    assert "asking again without thinking" in capsys.readouterr().out
    assert "2 calls" in bt._lm_turn_summary()


def test_a_reply_that_stopped_short_is_not_asked_again(fresh, monkeypatch):
    """Over a third of the cap written: a shorter answer, ended on its last
    full sentence, not a retry."""
    sent = []
    words = "The email step is the risky one. Then the rate limits on the "

    def post(payload, timeout=120):
        sent.append(payload)
        return _reply(words * 6, finish_reason="length", reasoning=1500)

    monkeypatch.setattr(bt, "_post_to_model", post)
    result = bt.call_lm_studio([{"role": "user", "content": "any ideas?"}],
                               include_tools=False, thinking=THINK_ON,
                               reply_cap=TYPED_REPLY_TOKENS)
    assert len(sent) == 1
    assert result["choices"][0]["message"]["content"].endswith("risky one.")


class _FakeResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines
        self.read = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for line in self._lines:
            self.read += 1
            yield line


def test_the_stream_stops_once_the_words_pass_the_cap(monkeypatch):
    """The reasoning streams as reasoning_content and is not counted; the
    words are, and the model is not left to run on for another 1,500
    tokens."""
    pieces = [{"choices": [{"delta": {"reasoning_content": "Let me think. " * 50}}]}]
    pieces += [{"choices": [{"delta": {"content": f"Sentence {i} is short. "}}]}
               for i in range(200)]
    lines = [b"data: " + json.dumps(p).encode() for p in pieces] + [b"data: [DONE]"]
    response = _FakeResponse(lines)
    monkeypatch.setattr(bt.requests, "post", lambda *a, **k: response)

    seen = []
    result = bt._stream_from_model({"messages": []}, seen.append, visible_limit=300)

    text = result["choices"][0]["message"]["content"]
    assert 300 < len(text) < 340
    assert result["choices"][0]["finish_reason"] == "length"
    assert response.read < 40, "the stream ran on past the cap"


# --------------------------------------------------------------------------
# The chat page
# --------------------------------------------------------------------------

def _user_text(payload):
    return next(m["content"] for m in reversed(payload["messages"])
                if m.get("role") == "user")


def test_a_short_question_is_capped_and_noted(chat):
    chat.ask("what could go wrong?")
    payload = chat.model.main[-1]
    assert payload["max_tokens"] == TYPED_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS
    assert _user_text(payload).endswith(f"what could go wrong?\n\n[{SHORT_TURN_NOTE}]")
    # Not in the system message: STYLE stays the last thing there.
    system = payload["messages"][0]["content"]
    assert SHORT_TURN_NOTE not in system
    # The user's words alone are stored and replayed.
    assert SHORT_TURN_NOTE not in json.dumps(chat.saved)


def test_a_greeting_is_capped_without_the_note(chat):
    chat.ask("hi blue")
    payload = chat.model.main[-1]
    assert payload["max_tokens"] == TYPED_REPLY_TOKENS
    assert SHORT_TURN_NOTE not in _user_text(payload)


def test_a_spoken_question_is_capped_without_the_note(chat):
    chat.ask("how are you different from chat gpt?", voice=True)
    payload = chat.model.main[-1]
    assert payload["max_tokens"] == SPOKEN_REPLY_TOKENS + THINKING_ALLOWANCE_TOKENS
    assert SHORT_TURN_NOTE not in _user_text(payload)


@pytest.mark.parametrize("text,body", [
    ("pourquoi tu dis ça?", {}),
    ("what could go wrong?", {"language": "fr"}),
])
def test_a_turn_in_another_language_gets_the_cap_without_the_english_note(
        chat, text, body):
    chat.ask(text, **body)
    payload = chat.model.main[-1]
    assert payload["max_tokens"] - bt._thinking_allowance(payload) == TYPED_REPLY_TOKENS
    assert SHORT_TURN_NOTE not in _user_text(payload)


@pytest.mark.parametrize("text", ["go on", "write me a letter to the dean",
                                  "what were those ideas?"])
def test_asking_for_length_on_the_chat_page_lifts_both(chat, text):
    chat.model.queue("Here it is.")
    chat.ask(text)
    payload = chat.model.main[-1]
    assert payload["max_tokens"] in (bt._chat_max_tokens(),
                                     bt._chat_max_tokens() + THINKING_ALLOWANCE_TOKENS)
    assert SHORT_TURN_NOTE not in _user_text(payload)


def test_accepting_an_offer_of_real_work_lifts_the_cap(chat):
    payload = {"messages": [
        {"role": "user", "content": "i need something for friday's lab"},
        {"role": "assistant", "content": "Want me to sketch a lesson plan around it?"},
        {"role": "user", "content": "sure"}], "robot": "blue"}
    chat.client.post("/v1/chat/completions", json=payload)
    assert chat.model.main[-1]["max_tokens"] in (
        bt._chat_max_tokens(), bt._chat_max_tokens() + THINKING_ALLOWANCE_TOKENS)


def test_a_reply_after_a_tool_has_run_is_not_capped(chat):
    """The model reached for a reflex tool itself: its answer is what the
    tool brought back, so only the first call has the cap."""
    chat.model.queue(
        {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {
                "name": "get_weather", "arguments": json.dumps({})}}]},
            "finish_reason": "tool_calls"}]},
        "Cloudy, 12 degrees.")
    chat.ask("should i bring a jacket?")

    assert [c["tool"] for c in chat.executed] == ["get_weather"]
    first, last = chat.model.main[0], chat.model.main[-1]
    assert first["max_tokens"] - bt._thinking_allowance(first) == TYPED_REPLY_TOKENS
    assert last["max_tokens"] - bt._thinking_allowance(last) == bt._chat_max_tokens()


def test_a_forced_tool_turn_is_not_capped(chat):
    chat.model.queue("Sent — Stella has your hello.")
    chat.ask("send an email to stella")
    assert all(p["max_tokens"] - bt._thinking_allowance(p) != TYPED_REPLY_TOKENS
               for p in chat.model.main)


def test_a_long_reply_on_the_chat_page_ends_within_the_cap(chat):
    chat.model.queue(LONG)
    reply = reply_of(chat.ask("what could go wrong?"))
    assert len(reply) <= visible_chars(TYPED_REPLY_TOKENS)
    assert reply.endswith("wrong.")


def test_panel_has_no_cap(chat):
    """Panel calls process_with_tools with its own length contract."""
    bt.process_with_tools([{"role": "user", "content": "what could go wrong?"}],
                          user_name="Alex", voice=True)
    payload = chat.model.main[-1]
    assert payload["max_tokens"] == bt._chat_max_tokens()
    assert SHORT_TURN_NOTE not in _user_text(payload)
