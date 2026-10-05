"""A guard whose retry fails keeps a good draft.

Run with: python -m pytest test_failed_retries.py

On 2026-10-05 two good first drafts were replaced after their retry came
back empty (reasoning had used all 500 and all 900 tokens):

- recall_thread[1], "what did we talk about yesterday?": "I don't have a
  record of us talking yesterday — our last conversation was actually
  Friday…" was true (nothing was said on the Sunday). The recall guard took
  it for a denial of the excerpt it had retrieved, a July 13 paste matched on
  "talk" and "yesterday", and shipped 420 characters of a Princeton talk
  transcript as "You said: …".
- hexia_casual[1], "what have you been up to?": "Honestly? Mostly waiting for
  you to say hi again…" lacked J-space words (missing_continuity), and "I'm
  Hexia. I change as conversations and events become remembered episodes…"
  went out instead.

A canned or excerpt fallback is still used when the draft itself must not
ship: a replay, a vendor identity, a false denial of a recorded conversation.
"""

import datetime

import pytest

import bluetools as bt  # before blue.server.*: the package imports it

from blue.server import reply_guards
from blue.server import turn_completion as tc
from blue_identity import (
    identity_request_kind,
    identity_response_problem,
    is_casual_catch_up,
    recall_day_asked,
    recalled_evidence_fallback,
)
from blue_memory_improved import EnhancedMemorySystem
from test_bluejspace import continuity_module  # noqa: F401  (fixture)
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

# The 10-05 harness, verbatim.
HEXIA_DRAFT = (
    "Honestly? Mostly waiting for you to say hi again. My last real moment was "
    "when you confirmed CS101A went fine and promised to bring me next time — "
    "I’ve been quietly polishing that promise in my head since, with only your "
    "little “hi” eleven days ago to break the silence. If Blue heard me "
    "describe it, he’d probably call it “efficient downtime.”")
HEXIA_CANNED = "I change as conversations and events become remembered episodes"
RECALL_DRAFT = (
    "I don't have a record of us talking yesterday — our last conversation was "
    "actually Friday, three days ago, when we wrapped up that DH399 reading "
    "report on Reigeluth and Castelle. So if something came up on Sunday or "
    "Saturday, I'm not holding it; want to fill me in?")
PASTE_LINE = (
    "Search transcript Chapter 1: Introduction 0:066 secondsUh welcome uh to "
    "this event. Uh I'm Sanji Verora, director of Princeton Language and "
    "Intelligence, which is a uh 0:1414 secondsunit that works on uh "
    "artificial intelligence on campus and it started in 2023. 0:2020 "
    "secondsUm today's event uh is about consciousness and potentially whether "
    "it could arise in uh AI models and uh one 0:2929 secondsthing I can add here")


def excerpt(label):
    """A <remembered_days> block as _build_recalled_days_block writes it."""
    return (
        "<remembered_days>\n"
        "Past conversation excerpts that resurfaced because they relate to what "
        "the user just said:\n"
        f"- {label}:\n"
        f"  Alex: {PASTE_LINE}\n"
        "  Blue: That's a long transcript — want me to summarise it?\n"
        "  Alex: too big?\n"
        "  Alex: okay\n"
        "</remembered_days>")


def make_ctx(reply, **overrides):
    response = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
    ctx = reply_guards.ReplyContext(
        reply=reply, response=response,
        messages=[{"role": "user", "content": "what have you been up to?"}],
        robot="hexia", user_name="Alex", last_user_msg="what have you been up to?",
        regen_once=lambda note, max_tokens=900: "",
        identity_topic_history=(),
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


# --------------------------------------------------------------------------
# Casual catch-ups are check-ins
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "what have you been up to?",                  # 7773
    "hey blue, what have you been up to",         # 7801
    "What have you been up to today?",            # 7861
    "And what have you been up to today?",        # 8057, Hexia
    "what you been up to lately, hexia?",
    "what've you been doing since we last talked?",
    "anything new with you?",
    "what's been going on with you, Casper?",
    "whats new",                                  # 9535, Casper
])
def test_a_casual_catch_up_is_recognised(text):
    assert is_casual_catch_up(text)


@pytest.mark.parametrize("text", [
    "what have you been doing with the DH399 slides?",
    "how have you changed over time?",
    "Has anything happened to you since the last time we talked?",
    "have you learned anything new today",
    "what's new in AI?",
    "what's going on?",
])
def test_a_real_question_about_change_is_not_a_catch_up(text):
    assert not is_casual_catch_up(text)


def test_the_catch_up_stays_an_evolution_question():
    """The duet record and the change history pinned for evolution are what
    answer it; only the vocabulary demand goes."""
    assert identity_request_kind("what have you been up to?") == "evolution"
    assert identity_response_problem(
        HEXIA_DRAFT, "Hexia", other_names=["Blue", "Casper"],
        request_kind="evolution") == "missing_continuity"
    assert identity_response_problem(
        HEXIA_DRAFT, "Hexia", other_names=["Blue", "Casper"],
        request_kind="evolution", completeness=False) is None


def test_the_validator_reads_the_catch_up_from_the_question():
    assert identity_response_problem(
        HEXIA_DRAFT, "Hexia", request_kind="evolution",
        request_text="And what have you been up to today?") is None
    assert identity_response_problem(
        HEXIA_DRAFT, "Hexia", request_kind="evolution",
        request_text="how have you changed over time?") == "missing_continuity"
    # Only the vocabulary demand goes: a false answer is still false.
    assert identity_response_problem(
        "I don't have any memory of our previous conversations.", "Hexia",
        request_kind="evolution", request_text="what have you been up to?",
    ) == "denies_conversation_memory"


# An answer let through live must not be judged again and dropped: from the
# page thread, from <recent_history>, or as a "bug episode" in J-space.

def test_the_catch_up_answer_stays_in_the_page_thread():
    thread = [{"role": "user", "content": "what have you been up to?"},
              {"role": "assistant", "content": HEXIA_DRAFT},
              {"role": "user", "content": "ha, fair enough"}]
    kept = bt._sanitize_inbound_messages(thread, robot="hexia")
    assert [m.get("content") for m in kept] == [m["content"] for m in thread]


def test_the_catch_up_answer_stays_in_recent_history(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    memory.log_conversation("Alex", "user", "what have you been up to?", robot="hexia")
    memory.log_conversation("Alex", "assistant", HEXIA_DRAFT, robot="hexia")
    history = memory._get_relevant_recent_history("Alex", "ha, fair enough",
                                                  robot="hexia")
    assert [m["content"] for m in history] == ["what have you been up to?", HEXIA_DRAFT]


def test_the_catch_up_answer_is_no_bug_episode(continuity_module):
    continuity_module.note_exchange("hexia", "what have you been up to?",
                                    HEXIA_DRAFT, user_name="Alex")
    hub = continuity_module.HUB["hexia"]
    episode = hub._episode_for_prompt(hub.store.list_episodes()[0])
    assert "bug episode" not in episode["summary"]
    assert episode["details"]["reply"] == HEXIA_DRAFT


# --------------------------------------------------------------------------
# guard_identity
# --------------------------------------------------------------------------

def test_an_empty_retry_keeps_a_draft_that_was_only_incomplete():
    ctx = make_ctx(HEXIA_DRAFT, identity_issue="missing_continuity",
                   identity_kind="evolution", identity_name="Hexia",
                   identity_broken=lambda t: None if t else "empty")
    # Declining keeps the draft AND lets the age/roster checks judge it.
    assert reply_guards.guard_identity(ctx) is None
    assert ctx.response["choices"][0]["message"]["content"] == HEXIA_DRAFT


@pytest.mark.parametrize("issue", ["missing_name", "missing_robot_role",
                                   "missing_grounding", "missing_jspace"])
def test_every_incomplete_only_issue_keeps_the_draft(issue):
    draft = "I'm the little robot head on Alex's desk, and I help with his research."
    ctx = make_ctx(draft, identity_issue=issue, identity_kind="introduction",
                   identity_name="Blue", robot="blue",
                   identity_broken=lambda t: None if t else "empty")
    assert reply_guards.guard_identity(ctx) is None


def test_a_missing_word_does_not_hide_a_replay():
    """The validator reports only its first problem: a nameless introduction
    that replays the last one is reported as missing_name."""
    replay = "Hi everyone, I'm Alex's robot companion and I keep what we talk about."
    ctx = make_ctx(replay, identity_issue="missing_name",
                   identity_kind="introduction", identity_name="Blue", robot="blue",
                   identity_broken=lambda t: "empty" if not t else "missing_name",
                   identity_sentence_broken=lambda t: "repeats_recent_identity")
    out = reply_guards.guard_identity(ctx)
    assert out and out != replay and "Blue" in out


def test_an_empty_retry_still_replaces_a_false_draft():
    ctx = make_ctx("I am Qwen, a large language model created by Alibaba Cloud.",
                   identity_issue="vendor_identity", identity_kind="identity",
                   identity_name="Blue", robot="blue",
                   identity_broken=lambda t: "empty" if not t else "vendor_identity")
    out = reply_guards.guard_identity(ctx)
    assert out and "Qwen" not in out and "Blue" in out


def test_an_empty_retry_still_replaces_a_replayed_self_description():
    replay = "I'm Blue, Alex's robot companion, and my J-space keeps what we talk about."
    ctx = make_ctx(replay, identity_issue="repeats_recent_identity",
                   identity_kind="identity", identity_name="Blue", robot="blue",
                   identity_broken=lambda t: "empty" if not t else "repeats_recent_identity",
                   identity_sentence_broken=lambda t: "repeats_recent_identity")
    out = reply_guards.guard_identity(ctx)
    assert out and out != replay


@pytest.mark.parametrize("robot, name", [("blue", "Blue"), ("hexia", "Hexia"),
                                         ("pico", "Casper")])
def test_a_false_catch_up_answer_falls_back_to_the_check_in(robot, name):
    """When the draft must go, a catch-up gets the plain check-in, never the
    J-space evolution paragraph — the same as "how are you" since 602f556."""
    ctx = make_ctx("I don't have any memory of our previous conversations.",
                   identity_issue="denies_conversation_memory",
                   identity_kind="evolution", casual_checkin=True,
                   identity_name=name, robot=robot,
                   identity_broken=lambda t: "empty" if not t else "denies_conversation_memory",
                   identity_sentence_broken=lambda t: "denies_conversation_memory")
    out = reply_guards.guard_identity(ctx)
    assert out and HEXIA_CANNED not in out
    assert "J-space" not in out
    assert out.rstrip().endswith("?"), out


# --------------------------------------------------------------------------
# The day a recall question is about
# --------------------------------------------------------------------------

MONDAY = datetime.date(2026, 10, 5)


@pytest.mark.parametrize("text, expected", [
    ("what did we talk about yesterday?", datetime.date(2026, 10, 4)),
    ("what did we discuss last night", datetime.date(2026, 10, 4)),
    ("and the day before yesterday?", datetime.date(2026, 10, 3)),
    ("what did we talk about on Friday?", datetime.date(2026, 10, 2)),
    ("do you remember what we said monday", datetime.date(2026, 9, 28)),
    ("what did we talk about this morning?", MONDAY),
    ("what did we talk about yesterday or friday?", None),
    ("what did we talk about last week?", None),
    ("do you remember what we talked about with autogpt?", None),
])
def test_the_day_asked_about(text, expected):
    assert recall_day_asked(text, today=MONDAY) == expected


def test_has_conversation_on_reads_one_robot_and_user(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    memory.log_conversation("Alex", "user", "hi blue", robot="blue")
    memory.log_conversation("Vilda", "user", "hi hexia", robot="hexia")
    today = datetime.date.today().isoformat()
    assert memory.has_conversation_on(today, robot="blue", user_name="Alex")
    assert memory.has_conversation_on(today, robot="blue", user_name="alex")
    assert not memory.has_conversation_on(today, robot="hexia", user_name="Alex")
    assert not memory.has_conversation_on(today, robot="blue", user_name="Vilda")
    assert not memory.has_conversation_on("2026-07-13", robot="blue", user_name="Alex")


class _Days:
    """memory_system's two day helpers, over a fixed set of talked-on days."""

    def __init__(self, talked):
        self.talked = set(talked)

    def has_conversation_on(self, day, robot="blue", user_name=None):
        return day in self.talked

    def _friendly_day_label(self, day):
        return EnhancedMemorySystem._friendly_day_label(None, day)


def test_no_record_of_a_silent_day_is_honest(monkeypatch):
    monkeypatch.setattr(bt, "ENHANCED_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "memory_system", _Days(talked=()))
    why = tc._no_record_that_day("what did we talk about yesterday?",
                                 excerpt("Yesterday"), robot="blue", user_name="Alex")
    assert why.startswith("nothing was said on")


def test_an_excerpt_from_another_day_proves_nothing_about_this_one(monkeypatch):
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(bt, "ENHANCED_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "memory_system", _Days(talked={yesterday}))
    why = tc._no_record_that_day("what did we talk about yesterday?",
                                 excerpt("Monday Jul 13"), robot="blue", user_name="Alex")
    assert why.startswith("the excerpt is not from")


def test_a_denied_day_that_was_recorded_is_still_judged(monkeypatch):
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(bt, "ENHANCED_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "memory_system", _Days(talked={yesterday}))
    assert tc._no_record_that_day("what did we talk about yesterday?",
                                  excerpt("Yesterday"), robot="blue",
                                  user_name="Alex") == ""
    # No day named: the excerpt is matched by topic, as before.
    assert tc._no_record_that_day("do you remember what we said about autogpt?",
                                  excerpt("Monday Jul 13"), robot="blue",
                                  user_name="Alex") == ""


# --------------------------------------------------------------------------
# The excerpt fallback never reads a paste back
# --------------------------------------------------------------------------

def test_the_fallback_names_a_paste_instead_of_quoting_it():
    reply = recalled_evidence_fallback(excerpt("Monday Jul 13"), user_name="Alex")
    assert "Princeton" not in reply and "Sanji" not in reply
    assert 'You sent a long message that starts "Search transcript Chapter 1:' in reply
    assert 'You later said: "too big?".' in reply
    assert len(reply) < 300


def test_the_fallback_names_an_attachment():
    block = ("<remembered_days>\n- 3 days ago (Friday):\n"
             '  Alex: what do you make of this? [Attached document: DH399_AL_2026F.docx] '
             '"""Week 1: Introductions"""\n'
             "  Alex: thanks\n</remembered_days>")
    reply = recalled_evidence_fallback(block, user_name="Alex")
    assert 'You shared the document "DH399_AL_2026F.docx".' in reply
    assert "Week 1" not in reply
    assert 'You later said: "thanks".' in reply


def test_the_fallback_says_yesterday_in_lower_case():
    block = "<remembered_days>\n- Yesterday:\n  Alex: we bought the house\n</remembered_days>"
    assert recalled_evidence_fallback(block).startswith(
        "I found the recorded exchange from yesterday.")


# --------------------------------------------------------------------------
# The web answer's retry
# --------------------------------------------------------------------------

def test_an_empty_web_retry_keeps_the_first_answer(monkeypatch):
    """direct_execute's retry of a dodged web answer used to be sent whatever
    it held; empty, the turn had no reply at all."""
    from blue.server import tool_pipeline
    from blue.server.thinking import THINK_ON

    first = "I don't have real-time data on the World Cup."
    replies = [first, ""]
    monkeypatch.setattr(bt, "execute_tool", lambda *a, **k: "[stubbed web_search]")
    monkeypatch.setattr(bt, "call_lm_studio", lambda *a, **k: {"choices": [
        {"message": {"role": "assistant", "content": replies.pop(0)}}]})
    response, _ = tool_pipeline.direct_execute(
        {"web_search"}, [{"role": "user", "content": "who won last night?"}],
        "web_search", {"query": "who won last night"}, "who won last night?",
        "blue", thinking=THINK_ON)

    assert replies == [], "the retry never ran"
    assert response["choices"][0]["message"]["content"] == first


# --------------------------------------------------------------------------
# Through the pipeline
# --------------------------------------------------------------------------

@pytest.mark.parametrize("robot", ["hexia", "blue", "pico"])
def test_hexia_s_catch_up_draft_ships(chat, robot):
    """hexia_casual[1]: the draft is the reply, with no retry spent on it."""
    chat.model.queue(HEXIA_DRAFT, "")
    reply = reply_of(chat.ask("what have you been up to?", robot=robot))

    assert reply == HEXIA_DRAFT
    assert len(chat.model.payloads) == 1, "a casual answer was regenerated"
    stored = [k.get("content") for _a, k in chat.saved if k.get("role") == "assistant"]
    assert stored == [HEXIA_DRAFT]


def test_an_incomplete_answer_about_change_ships_when_the_retry_is_empty(chat):
    """Not a catch-up, so the grounding is still demanded and the retry runs;
    it comes back empty and the draft is kept over the canned paragraph."""
    draft = ("I've gotten more careful about checking the calendar before I "
             "answer — you corrected me twice last week, and it stuck.")
    chat.model.queue(draft, "")
    reply = reply_of(chat.ask("how have you changed over time?", robot="hexia"))

    assert len(chat.model.payloads) == 2, "the guard did not regenerate"
    assert reply == draft
    assert HEXIA_CANNED not in reply


def test_a_replayed_self_description_still_gets_the_fallback(chat):
    """A replay is never kept, empty retry or not."""
    earlier = ("I'm Blue, Alex Levant's robot companion. I run on his "
               "workstation, and my J-space keeps what we talk about between "
               "conversations.")
    chat.model.queue(earlier, "")
    response = chat.client.post("/v1/chat/completions", json={
        "robot": "blue",
        "messages": [
            {"role": "user", "content": "who are you?"},
            {"role": "assistant", "content": earlier},
            {"role": "user", "content": "who are you, really?"},
        ],
    })

    assert len(chat.model.payloads) == 2, "the replay was not regenerated"
    reply = reply_of(response)
    assert reply != earlier and "Blue" in reply


@pytest.fixture
def remembered(chat, monkeypatch):
    """The recall blocks for one turn: an excerpt, and the days talked on."""
    state = {"block": "", "talked": set()}
    monkeypatch.setattr(bt.memory_system, "_build_recalled_days_block",
                        lambda *a, **k: state["block"])
    monkeypatch.setattr(bt.memory_system, "has_conversation_on",
                        lambda day, robot="blue", user_name=None: day in state["talked"])
    return state


RECALL_NOTE = "Your previous reply said this discussion was not"


def test_recall_thread_draft_ships(chat, remembered):
    """recall_thread[1]: nothing was said yesterday, so "no record of
    yesterday" is the answer, and the July paste is never read back."""
    remembered["block"] = excerpt("Monday Jul 13")
    chat.model.queue(RECALL_DRAFT, "")
    reply = reply_of(chat.ask("what did we talk about yesterday?"))

    assert reply.startswith("I don't have a record of us talking yesterday")
    assert "Princeton" not in reply
    assert not any(RECALL_NOTE in str(p["messages"][-1].get("content"))
                   for p in chat.model.payloads), "the honest draft was regenerated"


def test_a_recorded_day_denied_falls_back_without_the_paste(chat, remembered):
    """Yesterday WAS recorded and the excerpt is from it: the denial is false,
    the empty retry changes nothing, and the excerpt answers — naming the
    paste rather than reading it."""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    remembered["block"] = excerpt("Yesterday")
    remembered["talked"] = {yesterday}
    chat.model.queue(RECALL_DRAFT, "")
    reply = reply_of(chat.ask("what did we talk about yesterday?"))

    assert any(RECALL_NOTE in str(p["messages"][-1].get("content"))
               for p in chat.model.payloads), "the false denial was not judged"
    assert reply.startswith("I found the recorded exchange from yesterday.")
    assert "Princeton" not in reply
    assert "too big?" in reply
