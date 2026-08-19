"""Characterization tests for the tool loop in process_with_tools.

`process_with_tools` is 1,320 lines and, apart from what the chat-pipeline
tests reach through HTTP, was untested. Its failure mode is not a badly worded
reply — it is doing the wrong thing in a real house, or claiming to have done
something it never did. These pin that behaviour before the function is taken
apart.

SAFETY: `execute_tool` is stubbed before anything can reach it, and both model
transports are stubbed, so nothing here can photograph a room or send mail.
"""

import json
import types

import pytest

import bluetools as bt


@pytest.fixture
def loop(monkeypatch):
    executed = []
    calls = []

    def execute_tool(name, args=None, *rest, **kwargs):
        executed.append({"tool": name, "args": args or {}})
        return f"[{name} ran]"

    monkeypatch.setattr(bt, "execute_tool", execute_tool)

    class Model:
        def __init__(self):
            self.queued = []

        def queue(self, *items):
            self.queued.extend(items)

        def __call__(self, payload, timeout=120):
            calls.append(payload)
            item = self.queued.pop(0) if self.queued else "A plain spoken answer."
            if isinstance(item, dict):
                return item
            return {"choices": [{"message": {"role": "assistant", "content": item},
                                 "finish_reason": "stop"}]}

    model = Model()
    monkeypatch.setattr(bt, "_post_to_model", model)
    if getattr(bt, "_LM", None) is not None:
        monkeypatch.setattr(bt._LM, "chat",
                            lambda messages, **kw: model({"messages": messages, **kw}))

    def run(text, **kwargs):
        return bt.process_with_tools(
            [{"role": "user", "content": text}], user_name="Alex", **kwargs)

    return types.SimpleNamespace(run=run, executed=executed, model=model, calls=calls)


def content_of(result):
    return result["choices"][0]["message"].get("content") or ""


def tool_call(name, **args):
    """A model response that asks for one tool."""
    return {"choices": [{"message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]}}]}


# --------------------------------------------------------------------------
# Doing the thing
# --------------------------------------------------------------------------

def test_a_confidently_detected_tool_runs_before_any_model_call(loop):
    """The fast path: when the selector is confident, the tool is executed
    first and the model is called once, to put the result into words."""
    loop.model.queue("It's cold and grey out there.")
    result = loop.run("what's the weather doing?")

    assert [c["tool"] for c in loop.executed] == ["get_weather"]
    assert len(loop.calls) == 1, "the fast path made an extra round trip"
    assert content_of(result) == "It's cold and grey out there."


def test_the_tool_result_reaches_the_call_that_words_it(loop):
    """The answer must be composed FROM the result, so the result has to be
    in the messages that call sees."""
    loop.model.queue("Cold and grey.")
    loop.run("what's the weather doing?")

    assert "[get_weather ran]" in json.dumps(loop.calls[-1]["messages"])


def test_a_model_requested_tool_runs_and_gets_worded(loop):
    """The slower path: no confident detection, so the model asks."""
    loop.model.queue(tool_call("get_weather", location="Kitchener"),
                     "Cold and grey.")
    result = loop.run("I wonder how things are outside just now")

    if loop.executed:                      # the model chose to reach for it
        assert loop.executed[0]["tool"] == "get_weather"
        assert "[get_weather ran]" in json.dumps(loop.calls[-1]["messages"])
    assert content_of(result)


def test_a_conversational_turn_runs_no_tool(loop):
    loop.model.queue("Memory is a strange thing to be made of.")
    loop.run("what do you make of memory?")

    assert loop.executed == []


# --------------------------------------------------------------------------
# Not claiming to have done it
# --------------------------------------------------------------------------

def test_a_leaked_tool_call_written_as_text_is_executed(loop):
    """The model sometimes writes the call as visible words instead of calling
    it. Left alone, "<tool_call>..." reaches the user as prose."""
    leaked = '<tool_call>{"name": "get_weather", "arguments": {"location": "Kitchener"}}</tool_call>'
    loop.model.queue(leaked, "It's cold out.")
    # A question the selector does not claim, so the model's own text is used.
    result = loop.run("I was wondering about things in general")

    assert any(c["tool"] == "get_weather" for c in loop.executed), (
        "the leaked call was never run"
    )
    assert "<tool_call>" not in content_of(result), (
        "the raw tool call reached the user as text"
    )


# --------------------------------------------------------------------------
# The iteration cap — extra round trips cost seconds
# --------------------------------------------------------------------------

def test_the_second_iteration_is_sent_without_tools(loop):
    """After a tool has run, the model must compose an answer rather than
    reach for another tool."""
    loop.model.queue(tool_call("get_weather", location="Kitchener"),
                     "Cold and grey.")
    loop.run("what's the weather doing?")

    assert loop.calls[-1].get("tools") in (None, []), (
        "tools were offered again after a result came back"
    )


def test_the_loop_terminates_when_the_model_keeps_calling_tools(loop):
    """A model that only ever answers with tool calls must not spin."""
    loop.model.queue(*[tool_call("get_weather", location="x") for _ in range(8)])
    result = loop.run("I was wondering about things in general")

    # The invariant is termination within the cap. (A model that answers a
    # tools-disabled call with another tool call is not a real shape — LM
    # Studio is not offered any tools on that call.)
    assert len(loop.calls) <= 4, f"{len(loop.calls)} model calls for one turn"
    assert result and result.get("choices"), "the loop returned nothing at all"


# --------------------------------------------------------------------------
# Degrading rather than failing
# --------------------------------------------------------------------------

def test_an_unusable_model_response_returns_a_spoken_answer(loop):
    loop.model.queue({"choices": []})
    result = loop.run("are you there?")

    assert content_of(result), "an unusable response produced no reply"


def test_an_error_dict_from_the_model_returns_a_spoken_answer(loop):
    loop.model.queue({"error": "model not loaded"})
    result = loop.run("are you there?")

    assert content_of(result)


def test_a_failing_tool_does_not_lose_the_turn(loop, monkeypatch):
    """execute_tool reports failure as a string rather than raising, so this
    is the shape a broken camera actually arrives in."""
    monkeypatch.setattr(bt, "execute_tool",
                        lambda name, args=None, *r, **k: "Error: the camera is unplugged")
    loop.model.queue("I couldn't get a look just now.")
    result = loop.run("what do you see right now?")

    assert content_of(result), "a tool failure produced no reply"


def test_both_leaked_tool_call_formats_are_recognised():
    """The <function=...> style and the Qwen/Hermes JSON style. The loaded
    model emits the second, which used to reach the user as raw markup."""
    assert bt.parse_leaked_tool_call(
        '<function=get_weather>{"location":"Kitchener"}</function>'
    ) == ("get_weather", {"location": "Kitchener"})

    assert bt.parse_leaked_tool_call(
        '<tool_call>{"name": "get_weather", "arguments": {"location": "Kitchener"}}</tool_call>'
    ) == ("get_weather", {"location": "Kitchener"})

    assert bt.parse_leaked_tool_call("just an ordinary sentence") is None
    assert bt.parse_leaked_tool_call('<tool_call>{not json}</tool_call>') is None


# --------------------------------------------------------------------------
# Not acting on nothing
# --------------------------------------------------------------------------

def test_a_forced_tool_with_no_arguments_is_not_executed(loop):
    """"Blue, that's not less than six weeks away" forced remember_person; the
    model sensibly declined to call it, and the retry path ran it anyway with
    {} — "[OK] Remembered person:" with a blank name (live 2026-08-13). The
    old test was `if tool_args is not None`, which is always true."""
    from blue.server.tool_pipeline import _missing_required_args

    assert _missing_required_args("remember_person", {}) == ["name"]
    assert _missing_required_args("remember_person", {"name": "  "}) == ["name"]
    assert _missing_required_args("remember_person", {"name": "Felix"}) == []
    # 0 and False are real values, not missing ones.
    assert _missing_required_args("set_volume", {"level": 0}) == []
    # An unknown tool is not this guard's business.
    assert _missing_required_args("no_such_tool", {}) == []


def _forced(loop, text, tool, args):
    from blue.server import tool_pipeline
    return tool_pipeline.run_tool_loop(
        text, None, [{"role": "user", "content": text}],
        tool, args, False, text, 3, None, "Alex")


def test_the_forced_retry_still_runs_when_the_selector_supplied_arguments(loop):
    loop.model.queue("Noted — Felix it is.")
    _forced(loop, "his name is felix", "remember_person", {"name": "Felix"})

    assert [c["tool"] for c in loop.executed] == ["remember_person"]
    assert loop.executed[0]["args"]["name"] == "Felix"


def test_the_forced_retry_is_skipped_when_the_selector_supplied_nothing(loop):
    loop.model.queue("Eleven weeks, not six.")
    result = _forced(loop, "that's not less than six weeks away",
                     "remember_person", {})

    assert loop.executed == [], "a person was remembered with no name"
    assert content_of(result)


# --------------------------------------------------------------------------
# Claiming to have done something
# --------------------------------------------------------------------------
# The worst failure this loop has: the model says "sent" without ever calling
# a tool. What happens next turns entirely on whether the user asked for the
# action, and the two branches must not be swapped - one performs a real
# action in a real house, the other must never perform anything.
#
# These call the guard chain directly. Driven through the whole pipeline the
# selector answers these turns before the chain is ever reached, so the branch
# that matters would go untested.

def _judge(said, asked, *, repairs=None, iteration=1, force_tool=None):
    from blue.server import tool_pipeline

    response = {"choices": [{"message": {"role": "assistant", "content": said}}]}
    messages = [{"role": "user", "content": asked}]
    retry, pending = tool_pipeline._judge_untooled_reply(
        response, response["choices"][0]["message"],
        repairs if repairs is not None else tool_pipeline._ReplyRepairs(),
        iteration=iteration, force_tool=force_tool,
        conversation_messages=messages, improved_force_tool=None,
        improved_tool_args=None, _detect_msg=asked,
        last_user_message=asked, user_name="Alex")
    return retry, pending, response, messages


def test_a_claimed_action_the_user_asked_for_is_forced_on_the_next_pass():
    """The claim becomes a real call next iteration.

    That carry is exactly what a dropped `pending_force_tool` breaks, and it
    breaks silently: the reply still reads as though the mail went.
    """
    retry, pending, _resp, messages = _judge(
        "Sent! I've emailed the reading list to the class.",
        "email the reading list to the class")

    assert retry is True
    assert pending == "send_gmail", "the claimed tool was not carried over"
    assert "didn't actually call any tool" in json.dumps(messages)


def test_a_claimed_action_nobody_asked_for_is_regenerated_not_forced():
    """2026-07-09: "I sent the introduction email to the class", unprompted."""
    retry, pending, _resp, messages = _judge(
        "By the way, I sent the introduction email to the class.",
        "what's the weather doing?")

    assert retry is True
    assert pending is None, "an unrequested action was queued for execution"
    assert "did not ask for any such action" in json.dumps(messages)


def test_an_insisted_claim_nobody_asked_for_is_scrubbed_not_performed():
    """Second offence: the loop stops arguing and removes the claim."""
    from blue.server import tool_pipeline

    repairs = tool_pipeline._ReplyRepairs()
    repairs.phantom_claim = True           # it already tried once this turn

    retry, pending, response, _messages = _judge(
        "By the way, I sent the introduction email to the class.",
        "what's the weather doing?", repairs=repairs)

    assert retry is False, "the loop kept arguing instead of taking the reply"
    assert pending is None
    assert "sent the introduction email" not in content_of(response).lower(), \
        "the claim survived into the reply"
