"""The closing note: react, add your own, hold a true fact, ask rarely.

Run with: python -m pytest test_closing_note.py

- c1692cb's STYLE + ENDINGS + FEELINGS + HUMOUR closed every reply with stop
  rules ("respond to that and stop", "not on a question back", "add one warm
  or wry line, and stop", "Tell it and stop"): replies ending in "?" fell
  from 38% to 9% and Blue answered and stopped. Alex, 10-07: respond to
  what I said, talk like a person, have your own take; questions "rarely,
  specific only", never two replies in a row.
- Told "i think lm studio is open source and free to use" (10139), Blue
  conceded "Fair point on the licensing" while his reasoning knew the app is
  proprietary: "When corrected, take the fix in a few words" covered any
  pushback.
- "Never two in a row" is a note beside his words when Blue's last reply
  ended on a question, not a net that counts or cuts questions.

SAFETY: the pipeline tests use the chat fixture from test_chat_pipeline
(execute_tool and both model transports stubbed). No request leaves for LM
Studio.
"""

import json
import re

import pytest

import bluetools as bt
from blue.server.reply_budget import (NO_QUESTION_NOTE, NO_QUESTION_NOTE_HEARD,
                                      SHORT_TURN_NOTE, SOCIAL_TURN_NOTE,
                                      ends_on_question, no_question_note,
                                      questions_are_the_content, turn_note)
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

ALEX_QUESTION_RULE = (
    "When something he just said genuinely makes you curious, you can ask "
    "one short question about that exact thing, in his words — rarely; "
    "most replies have none.")


def _system_text(user="Alex", voice=False, heard=False, robot="blue"):
    msgs = bt._chat_system_message(
        [{"role": "user", "content": "hi"}], robot=robot, user_name=user,
        voice=voice, language="", system_addendum="", heard=heard)
    return msgs[0]["content"]


def _closing(text):
    return text[text.rindex("\nSTYLE:"):]


# ---- the note ---------------------------------------------------------------------

def test_the_stop_rules_are_gone():
    text = _system_text()
    for stop in ("respond to that and stop", "add one warm or wry line, and stop",
                 "Tell it and stop", "Ask a question only when you can't go on",
                 "usually two to five sentences"):
        assert stop not in text, stop


def test_a_reply_reacts_first_and_adds_something_of_his_own():
    note = _closing(_system_text())
    assert "Start from what he just said" in note
    assert "add one thing of your own: what you think and why" in note
    assert note.index("Start from what he just said") < note.index("add one thing of your own")


def test_his_own_thing_comes_from_what_alex_said():
    """ "or a detail you noticed" was filled from the context blocks or made
    up: Nori "dragging the rest of us through the park" (home_checkin[5]),
    the week's timetable recited to "pretty tired, long week of teaching",
    "I was at DH201 last Thursday" (10112) (S7 review)."""
    note = _closing(_system_text())
    assert "what you think and why, or something you noticed in what he said" in note
    assert "a detail you noticed" not in note
    heard = _system_text(voice=True, heard=True)
    assert "something you noticed in what he said" in heard
    assert "a detail you noticed" not in heard


def test_alexs_question_rule_is_in_the_note_in_his_words():
    note = _closing(_system_text())
    assert ALEX_QUESTION_RULE in note
    for banned in ("no check-ins", "no asking what he needs from you",
                   "no either/or choices", "no checking whether he agrees",
                   "Don't offer to do things he didn't ask for"):
        assert banned in note, banned
    assert "A greeting gets a greeting back and something of your own, not a question" in note


@pytest.mark.parametrize("heard", [False, True])
def test_a_check_back_and_a_needed_detail_are_still_asked(heard):
    """ "No other question" forbade the check-back HEARD, NOT TYPED asks for
    on a garbled turn, and the clarification the earlier note allowed
    ("could you tell me her name so I can check properly?", 7662)."""
    text = _system_text(voice=heard, heard=heard)
    note = text[text.rindex("\nSTYLE:"):]
    assert "No other question" not in note
    assert ("ask only to check a word you didn't catch or a detail you need "
            "before you can do what he asked") in note
    assert note.index(ALEX_QUESTION_RULE) < note.index("ask only to check a word")
    if heard:
        assert text.index("HEARD, NOT TYPED") < text.rindex("\nSTYLE:")


def test_a_true_fact_is_held_and_his_own_life_is_his():
    """10139: the reasoning knew the app is proprietary and conceded. On a
    draft that said only "about his own plans, family and life, he is the
    authority", the reasoning read it as "the authority on his own plans and
    what he's verified" for a fact about LM Studio; with his courses in that
    list, as "the authority on… his own tools and his course material"
    (2 of 3 replays conceded, S7 review)."""
    note = _closing(_system_text())
    assert "When corrected, take the fix" not in note
    assert "When he corrects you and he's right, take it in a few words" in note
    assert "About what only he can know — his plans, his family, his own life — he is the authority" in note
    assert "what you know doesn't change because he disagrees" in note
    assert "say so once, plainly and kindly" in note
    assert "don't argue it again" in note


def test_his_courses_are_his_to_set():
    """Spec S7: his courses → he is the authority. Checking what he says
    against the syllabus "before you give way" was the 09-24 stubbornness:
    "Yes, I'm sure. The PDF syllabus… lists Lab 5" (10020), then "its not
    lab 5". The syllabus is mentioned once, then he decides (S7 review)."""
    note = _closing(_system_text())
    assert "before you give way" not in note
    assert "if they agree with you, say so once" not in note
    assert ("His courses and schedule are his to set: if what he says differs "
            "from the syllabus or schedule in front of you, say what it shows "
            "once, then go with what he says.") in note
    # Not in the "only he can know" list, where LM Studio read as his course.
    only = note[note.index("About what only he can know"):]
    only = only[:only.index("he is the authority")]
    assert "course" not in only


def test_the_note_quotes_no_phrase_to_say_back():
    """This model says quoted lines back ("You built me…", 10145)."""
    note = _closing(_system_text())
    assert not re.search(r"(?<!\w)'[^']+'(?!\w)", note), "a single-quoted phrase"
    assert not re.search(r"[\"“”‘’]", note), "a quoted phrase"
    assert "lip motors" not in note and "Ohbot" not in note


@pytest.mark.parametrize("robot", ["hexia", "pico"])
def test_hexia_and_casper_share_the_note(robot):
    assert _closing(_system_text(robot=robot)) == _closing(_system_text())


def test_the_note_is_the_last_thing_in_the_system_message():
    text = _system_text()
    assert text.rstrip().endswith("No emoji.")
    assert text.rindex("\nSTYLE:") > text.rindex("</")


def test_a_heard_turn_gets_the_turn_rules_before_spoken_reply():
    text = _system_text(voice=True, heard=True)
    spoken = text.rindex("\nSPOKEN REPLY:")
    style = text.rindex("\nSTYLE:")
    assert style < spoken
    assert ALEX_QUESTION_RULE in text[style:spoken]
    assert "what you know doesn't change because he disagrees" in text[style:spoken]
    assert "Small talk gets a sentence or two" not in text
    assert "no follow-up question unless you need one" not in text
    assert text.rstrip().endswith(
        "End on your answer: a question only rarely, one short one about "
        "what he just said.")


def test_the_kids_page_keeps_its_own_note():
    text = _system_text(user="Vilda")
    assert ALEX_QUESTION_RULE not in text
    assert "what you know doesn't change" not in text
    spoken = _system_text(user="Vilda", voice=True, heard=True)
    assert "a question only rarely" not in spoken


# ---- ending on a question --------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "What model did you point it at?",
    "Did you get around to reading it?  ",
    '"How was the drive in?"',
    "**“Did the lab run long?”**",
    "Was it the **Reigeluth** reading or the agent loops?**",
    "(Or was that just the wifi?)",
    "Do you want to talk about what happened, or let the day go?\n",
])
def test_a_reply_that_ends_on_a_question(reply):
    assert ends_on_question(reply)
    assert no_question_note(reply) == NO_QUESTION_NOTE


@pytest.mark.parametrize("reply", [
    "", None, "That makes sense.", "What? No, the lab is on Wednesday.",
    "Fair point on the gloss — it isn't open source, though.",
    "Is it hype? Partly. The procedural middle is real.",
    # A quoted question is someone's words, not Blue asking (3971, 4495,
    # 7910 in conversation_log).
    'He asked me, "why?"',
    'The guiding question for the class is: "what happens to representation?"',
    "Her title says it all: “Who owns the model?”",
    '"Open" is doing the work in "who gets to run it?"',
])
def test_a_reply_that_does_not(reply):
    assert not ends_on_question(reply)
    assert no_question_note(reply) == ""


@pytest.mark.parametrize("turn", [
    "give me three discussion questions for tomorrow's dh201 reading",
    "draft an email asking the dean whether the lab can move",
    "ask the class what they think about agents",
    "what were those questions again?",
    "make a quick quiz on the reading",
    "write felix a note about friday",
])
def test_a_request_that_may_end_on_a_question_gets_no_note(turn):
    """The pin contradicted a request whose questions are the content."""
    assert questions_are_the_content(turn)
    assert no_question_note(ASKED, turn) == ""
    assert no_question_note(ASKED, turn, heard=True) == ""


@pytest.mark.parametrize("turn", [
    "the dh399 crowd mostly", "pretty tired", "tell me more about that",
    "what could go wrong?", "i don't know, maybe the material is too dense",
])
def test_a_conversational_turn_keeps_the_note(turn):
    assert not questions_are_the_content(turn)
    assert no_question_note(ASKED, turn) == NO_QUESTION_NOTE
    assert no_question_note(ASKED, turn, heard=True) == NO_QUESTION_NOTE_HEARD


def test_the_heard_note_leaves_room_to_check_a_word():
    """HEARD, NOT TYPED asks for one short question naming the guess on a
    garbled turn; the plain note forbade it on the turns that answer Blue's
    question, a name or a code, what speech recognition swaps most."""
    assert NO_QUESTION_NOTE_HEARD.startswith(NO_QUESTION_NOTE[:-1])
    assert "check a word you didn't catch" in NO_QUESTION_NOTE_HEARD
    assert "check a word" not in NO_QUESTION_NOTE


def test_the_notes_beside_his_words_are_one():
    assert turn_note(SHORT_TURN_NOTE, NO_QUESTION_NOTE) == (
        f"{SHORT_TURN_NOTE} {NO_QUESTION_NOTE}")
    assert turn_note("", NO_QUESTION_NOTE) == NO_QUESTION_NOTE
    assert turn_note(SHORT_TURN_NOTE, "") == SHORT_TURN_NOTE
    assert turn_note("", "") == ""


# ---- the chat page ---------------------------------------------------------------

ASKED = "That sounds like a long week. What drained you the most?"
SAID = "That sounds like a long week, and the new courses take the most out of you."


def _user_text(payload):
    return next(m["content"] for m in reversed(payload["messages"])
                if m.get("role") == "user")


def _thread(chat, reply, turn, headers=None, **body):
    payload = {"messages": [
        {"role": "user", "content": "pretty tired, long week of teaching"},
        {"role": "assistant", "content": reply},
        {"role": "user", "content": turn}], "robot": "blue"}
    payload.update(body)
    return chat.client.post("/v1/chat/completions", json=payload,
                            headers=headers or {})


def test_after_a_question_the_turn_asks_for_none(chat):
    """home_checkin[2] on the 10-05 harness: after "How has your week been
    treating you?", "pretty tired…" got an either/or menu or a check-in."""
    _thread(chat, ASKED, "the dh399 crowd mostly")
    text = _user_text(chat.model.main[-1])
    assert text == f"the dh399 crowd mostly\n\n[{NO_QUESTION_NOTE}]"
    # The note is not his words: neither stored nor replayed.
    assert NO_QUESTION_NOTE not in json.dumps(chat.saved)


def test_after_a_statement_nothing_is_added(chat):
    _thread(chat, SAID, "the dh399 crowd mostly")
    assert _user_text(chat.model.main[-1]) == "the dh399 crowd mostly"


@pytest.mark.parametrize("reply,note", [
    (ASKED, f"[{SOCIAL_TURN_NOTE} {NO_QUESTION_NOTE}]"),
    (SAID, f"[{SOCIAL_TURN_NOTE}]")])
def test_news_gets_the_social_note_and_both_in_one_bracket(chat, reply, note):
    """One bracket with the social note (spec S8)."""
    _thread(chat, reply, "we are in the class rightnow")
    assert _user_text(chat.model.main[-1]) == f"we are in the class rightnow\n\n{note}"


def test_a_short_question_after_a_question_gets_one_note(chat):
    _thread(chat, ASKED, "what could go wrong?")
    text = _user_text(chat.model.main[-1])
    assert text.endswith(f"what could go wrong?\n\n[{SHORT_TURN_NOTE} {NO_QUESTION_NOTE}]")
    assert text.count("[") == 1


def test_a_greeting_after_a_question_gets_the_note(chat):
    """The greeting fast path pins it too."""
    _thread(chat, ASKED, "hi blue")
    assert _user_text(chat.model.main[-1]).endswith(
        f"[{SOCIAL_TURN_NOTE} {NO_QUESTION_NOTE}]")


def test_a_spoken_turn_after_a_question_gets_the_note(chat):
    """The heard note, which leaves room for HEARD, NOT TYPED's check-back."""
    _thread(chat, ASKED, "i don't know, maybe the material is too dense", voice=True)
    text = _user_text(chat.model.main[-1])
    assert text.endswith(f"[{NO_QUESTION_NOTE_HEARD}]")
    assert "HEARD, NOT TYPED" in chat.model.main[-1]["messages"][0]["content"]


def test_spoken_news_after_a_question_gets_both_notes_in_one(chat):
    _thread(chat, ASKED, "i had a rough day", voice=True)
    assert _user_text(chat.model.main[-1]).endswith(
        f"[{SOCIAL_TURN_NOTE} {NO_QUESTION_NOTE_HEARD}]")


CHECKED_BACK = "I didn't catch that — did you mean how old is Athena?"


@pytest.mark.parametrize("voice", [False, True])
def test_after_a_check_back_the_turn_gets_no_note(chat, voice):
    """A check-back is no question back. His answer may come through
    garbled again, and HEARD, NOT TYPED asks for another (S7 review)."""
    _thread(chat, CHECKED_BACK, "how old is athena now", voice=voice)
    text = _user_text(chat.model.main[-1])
    assert NO_QUESTION_NOTE not in text and NO_QUESTION_NOTE_HEARD not in text


@pytest.mark.parametrize("turn", [
    "give me three discussion questions for tomorrow's dh201 reading",
    "ask the class what they think about agents",
])
def test_a_request_for_questions_after_a_question_gets_no_note(chat, turn):
    _thread(chat, ASKED, turn)
    text = _user_text(chat.model.main[-1])
    assert NO_QUESTION_NOTE not in text


def test_a_forced_tool_that_writes_gets_no_note(chat, monkeypatch):
    """The email or the document is the request, whatever it ends on."""
    monkeypatch.setattr(bt._reply_budget, "questions_are_the_content",
                        lambda text: False)
    _thread(chat, ASKED, "compose a reply to the email from felix")
    assert chat.model.main[0].get("tool_choice") == "required"
    assert NO_QUESTION_NOTE not in _user_text(chat.model.main[0])


def test_the_kids_page_gets_no_note(chat):
    _thread(chat, "Do you like dogs?", "yes i love dogs",
            headers={"X-Blue-Device": "ipad"})
    assert NO_QUESTION_NOTE not in _user_text(chat.model.main[-1])


@pytest.mark.parametrize("turn,body", [
    ("oui, la semaine était longue", {}),
    ("the dh399 crowd mostly", {"language": "fr"}),
])
def test_another_language_gets_no_english_note(chat, turn, body):
    _thread(chat, ASKED, turn, **body)
    assert NO_QUESTION_NOTE not in _user_text(chat.model.main[-1])


def test_panel_gets_no_note(chat):
    """Panel calls process_with_tools with its own contract."""
    bt.process_with_tools([
        {"role": "user", "content": "pretty tired"},
        {"role": "assistant", "content": ASKED},
        {"role": "user", "content": "the dh399 crowd mostly"}],
        user_name="Alex", voice=True)
    assert NO_QUESTION_NOTE not in _user_text(chat.model.main[-1])


BOILERPLATE = ("As a large language model developed by OpenAI, I don't have a "
               "body, but yes, autoGPT is a kind of harness.")


def test_a_guards_retry_keeps_the_note(chat):
    """The identity guard's regeneration is asked with the turn's notes."""
    chat.model.queue(BOILERPLATE, "AutoGPT is a harness: it loops a model through tools.")
    _thread(chat, ASKED, "is autoGPT a type of harness")
    retry = chat.model.payloads[1]
    live = [m["content"] for m in retry["messages"] if m.get("role") == "user"][-2]
    assert live.endswith(f"[{SHORT_TURN_NOTE} {NO_QUESTION_NOTE}]")
