"""Phase 2, step 4: class introductions, plain canned replies, and the
robot-relationship misfire.

The 10-05 harness: "we're in front of the DH399 class right now. do you want
to say hello to everyone?" and "say hi to the students" classified as nothing
(no identity note, old class greetings quoted back); "can you tell the
students a bit about yourself?" listed eyes, lips, LEDs and J-space; "tell
everyone a bit about yourself" came back nameless; "who am I?" was read out
as a record with semicolons. Live 09-07, Casper: "do you know where blue is
right now?" got "Blue is the calmer, steadier original companion."
"""

import re

import bluetools as bt  # before blue.server.*: the package imports it

import pytest

from blue_identity import (
    canonical_identity_reply,
    canonical_robot_relationship_reply,
    canonical_user_identity_reply,
    class_audience,
    contextual_identity_request_kind,
    extract_explicit_location,
    identity_grounding_note,
    identity_request_kind,
    identity_response_problem,
    robot_relationship_targets,
)


def _thread(*user_turns):
    """A page thread of user turns with a short reply after each but the last."""
    messages = []
    for index, text in enumerate(user_turns):
        messages.append({"role": "user", "content": text})
        if index < len(user_turns) - 1:
            messages.append({"role": "assistant", "content": "Sure."})
    return messages


def _kind(*user_turns):
    return contextual_identity_request_kind(user_turns[-1], _thread(*user_turns))


# ---- class greetings are introductions ---------------------------------------

@pytest.mark.parametrize("turns, kind", [
    (("we're in front of the DH399 class right now. do you want to say hello "
      "to everyone?",), "introduction"),
    (("can you tell the students a bit about yourself?",), "identity"),
    (("say hi to the students",), "introduction"),
    (("Do you want to say hello to the students?",), "introduction"),
    (("why don't you say hi to the class?",), "introduction"),
    (("tell everyone a bit about yourself",), "identity"),
    (("Hi! Tell me a little about yourself.",), "identity"),
    # "everyone" after a turn that named the class
    (("we're in DH201 today", "say hello to everyone"), "introduction"),
])
def test_a_class_greeting_is_an_introduction(turns, kind):
    assert _kind(*turns) == kind


@pytest.mark.parametrize("turns", [
    ("say hello to the kids",),
    ("the girls are back, say hi to them",),
    ("Stella is here with her friends, say hello to everyone",),
    ("we're in DH201 today", "dont say hello to everyone again"),
    ("we're in DH201 today", "did you say hello to everyone?"),
    ("did you say hi to the students?",),
    ("say hi to the group chat",),
    ("welcome everyone to the party",),
    ("say hello to my mom",),
    ("can you say hi to Stella",),
    ("the kids are home", "say hello to everyone"),
])
def test_household_greetings_stay_out(turns):
    assert _kind(*turns) is None


def test_everyone_needs_the_class_named_in_this_turn_or_the_last():
    assert identity_request_kind("do you want to say hello to everyone?") is None
    assert _kind("we're in front of the class", "ok", "say hello to everyone") is None


# ---- the audience: from the live turn, or "us" right after the class -----------

def test_the_class_is_the_audience_only_when_the_turn_speaks_to_it():
    assert class_audience("say hi to the students") == "class"
    assert class_audience("we're in front of the DH399 class right now") == "class"
    thread = _thread("can you tell the students a bit about yourself?",
                     "tell us more about yourself")
    assert class_audience("tell us more about yourself", thread) == "class"
    # Alex talking about the class is not the class listening
    thread = _thread("the students seemed bored", "who are you really?")
    assert class_audience("who are you really?", thread) is None
    assert class_audience("I'm grading my students' essays, what are you?") is None
    assert class_audience("tell us more about yourself") is None


def test_the_class_note_says_already_said_no_hardware_and_the_topic():
    topic = 'DH399, "What is under the hood of an AI agent? How do they work?"'
    note = identity_grounding_note(
        "Blue", "Alex's robot companion", "introduction",
        audience="class", class_topic=topic)
    assert "already said" in note and "hardware list" in note
    assert "about 60" in note and "first-year" in note
    assert "No J-space" in note and "no city" in note
    assert note.endswith(f"Today's class is {topic} — a better hook than your hardware.]")
    # without a syllabus row today, still a hook, never an invented topic
    bare = identity_grounding_note(
        "Blue", "Alex's robot companion", "introduction", audience="class")
    assert bare.endswith("What the class is about is a better hook than your hardware.]")
    # Alex's robot, not his robot companion (2026-09-24)
    assert "Say that you are Blue, Alex's robot," in note
    assert "Alex's robot companion, then" not in note
    # no room, no line
    home = identity_grounding_note("Blue", "Alex's robot companion", "introduction")
    assert "AUDIENCE" not in home and "J-space" in home
    assert "AUDIENCE" not in identity_grounding_note(
        "Blue", "Alex's robot companion", "self_state", audience="class")


def test_telling_the_class_about_himself_starts_with_name_and_role():
    note = identity_grounding_note(
        "Hexia", "Blue's friend", "identity", audience="class")
    assert "Start by saying you're Hexia, Alex's robot" in note
    assert "AUDIENCE" in note
    plain = identity_grounding_note("Hexia", "Blue's friend", "identity")
    assert "Start by saying" not in plain and "AUDIENCE" not in plain


# ---- a greeting is complete with the name ---------------------------------------

def test_an_introduction_needs_only_the_name():
    greeting = ("Hi everyone, I'm Blue. We're digging into what's under the hood "
                "of AI agents today, and I'm curious what you'll make of it.")
    assert identity_response_problem(
        greeting, "Blue", ["Hexia"], request_kind="introduction") is None
    # still a name, and still nothing false
    assert identity_response_problem(
        "Hi everyone! Great to see you all.", "Blue",
        request_kind="introduction") == "missing_name"
    assert identity_response_problem(
        "Hi everyone, I'm Blue, a large language model developed by Google.",
        "Blue", request_kind="introduction") is not None
    # "who are you?" keeps the full check
    assert identity_response_problem(
        "I'm Blue. Nice to meet you.", "Blue",
        request_kind="identity") == "missing_robot_role"


# ---- "we're at…" is a place; "in front of the class" is not ---------------------

@pytest.mark.parametrize("text, place", [
    ("we're at york university", ("York University", "at")),
    ("were not at fullford. we're at wilfrid laurier university",
     ("Wilfrid Laurier University", "at")),
    ("We're here at Wilfred Laura university in CS101 do you wanna say hello "
     "to the class.", ("Wilfred Laura university in CS101", "at")),
    ("blue, we are in front of the class in dh201 right now", None),
    ("we're in front of the DH399 class right now. do you want to say hello "
     "to everyone?", None),
    ("We are at the end of the research talk do you have any final thoughts.", None),
    ("When we're in class tomorrow blue, I'm gonna ask you to introduce "
     "yourself to the class.", None),
    ("I want you to pretend we're in the first class right now", None),
    # unchanged
    ("Hi Blue. We are at york university. Can you introduce yourself to the "
     "class?", ("York University", "at")),
])
def test_a_spoken_were_names_a_place(text, place):
    assert extract_explicit_location(text) == place


# ---- canned replies in plain spoken sentences ---------------------------------

FACTS = {
    "employer": "Wilfrid Laurier University",
    "department": "Communication Studies",
    "user_role": "Professor, teaches DH201 and DH399",
    "partner_name": "Stella",
    "daughter_name": "Athena, Emmy, Vilda",
    "pet_name": "Nori",
}


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def test_who_am_i_is_said_not_read_out():
    reply = canonical_user_identity_reply(FACTS, "Alex")
    assert reply == (
        "Of course — you're Alex. You built me, and you look after me. You "
        "teach at Wilfrid Laurier University, and at home there's Stella and "
        "the girls, Athena, Emmy and Vilda, plus Nori.")
    assert ";" not in reply and "dad to" not in reply
    assert "Communication Studies" not in reply
    assert len(_sentences(reply)) <= 3
    assert canonical_user_identity_reply({}, "Alex") == (
        "Of course — you're Alex. You built me, and you look after me.")
    work = canonical_user_identity_reply(
        {"employer": "Wilfrid Laurier University"}, "Alex")
    assert work.endswith("You work at Wilfrid Laurier University.")
    home = canonical_user_identity_reply({"partner_name": "Stella"}, "Alex")
    assert home.endswith("At home there's Stella.")
    assert canonical_user_identity_reply(FACTS, "Vilda") == (
        "Yes, of course I know you — you're Vilda.")


@pytest.mark.parametrize("variant", [0, 1, 2])
@pytest.mark.parametrize("audience", [None, "class"])
def test_the_canned_introductions_do_not_place_him_at_home(variant, audience):
    reply = canonical_identity_reply(
        "Blue", "Alex's robot companion", "introduction",
        introduction_variant=variant, audience=audience)
    assert "home" not in reply.lower()


# ---- "where is blue?" is not a question about the relationship -------------------

@pytest.mark.parametrize("robot, text", [
    ("pico", "do you know where blue is right now?"),
    ("pico", "where is blue?"),
    ("blue", "is hexia on?"),
    ("hexia", "what did blue say?"),
    ("blue", "do you know if hexia is awake"),
    ("hexia", "what do you think of blue's new voice?"),
    ("blue", "what do you remember about the conversation with hexia"),
])
def test_where_and_whether_go_to_the_model(robot, text):
    assert canonical_robot_relationship_reply(text, robot=robot) is None


@pytest.mark.parametrize("robot, text, opens", [
    ("pico", "what do you think of blue", "Blue is the calmer"),
    ("blue", "who is hexia to you", "Hexia is my quick"),
    ("hexia", "do you like casper?", "Casper is our compact"),
    ("pico", "what's blue like?", "Blue is the calmer"),
    ("blue", "Do you know Hexia?", "Hexia is my quick"),
    ("hexia", "So how do you know blue?", "Blue is my steady"),
    ("pico", "And what do you know about blue and hexia?", "Blue is the calmer"),
])
def test_relationship_questions_keep_their_answer(robot, text, opens):
    reply = canonical_robot_relationship_reply(text, robot=robot)
    assert reply and reply.startswith(opens)


def test_are_you_sure_follows_only_a_relationship_question():
    after_where = _thread("where is blue?", "are you sure?")
    assert robot_relationship_targets("are you sure?", "pico", after_where) == ()
    assert canonical_robot_relationship_reply(
        "are you sure?", "pico", after_where) is None
    after_opinion = _thread("what do you think of blue?", "are you sure?")
    assert canonical_robot_relationship_reply(
        "are you sure?", "pico", after_opinion).startswith("Yes—absolutely.")


def test_a_robot_named_in_passing_is_not_asked_about():
    reply = canonical_robot_relationship_reply(
        "blue said something funny earlier, what do you think of hexia?", "pico")
    assert reply.startswith("Hexia is the quick") and "Blue" not in reply


# ---- today's topic comes from the syllabus row ---------------------------------

TOPICS = {
    "DH399": "{label}: What is under the hood of an AI agent? How do they work?",
    "CS101": "{label} – Topics in Media and Communication History 1 (33 pages)",
}


def _library(monkeypatch, tmp_path, day, codes=("DH399",)):
    label = f"{day.strftime('%B')} {day.day}"
    docs, rows = [], {}
    for code in codes:
        doc = tmp_path / f"{code}_AL_2026F.docx"
        doc.write_text("x")
        docs.append({"folder": code, "filename": doc.name, "filepath": str(doc)})
        rows[str(doc)] = TOPICS[code].format(label=label)
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": docs})
    monkeypatch.setattr(bt, "_syllabus_file_text", lambda fp: (
        f"Grading\nClass Schedule\n{rows[fp]}\nReadings: Pasquinelli ch. 1\n"))
    monkeypatch.setattr(bt, "_calendar_event_now", lambda now=None: None)


def test_the_topic_is_todays_row_for_the_named_class(monkeypatch, tmp_path):
    from datetime import date, timedelta
    _library(monkeypatch, tmp_path, date.today())
    topic = 'DH399, "What is under the hood of an AI agent? How do they work?"'
    assert bt._class_topic_today(
        ["we're in front of the DH399 class right now"]) == topic
    # named a turn earlier
    assert bt._class_topic_today(["say hi to the students", "we're in dh 399"]) == topic
    # not named, not on the calendar: no guess
    assert bt._class_topic_today(["say hi to the students"]) == ""
    # the class on the calendar right now names it
    monkeypatch.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "DH399: AI Agents at Work and in Society (Lecture)"})
    assert bt._class_topic_today(["say hi to the students"]) == topic
    # a course that doesn't meet today has no topic today
    _library(monkeypatch, tmp_path, date.today() + timedelta(days=3))
    assert bt._class_topic_today(["we're in front of the DH399 class"]) == ""


def test_the_audience_and_topic_ride_only_on_class_identity_turns(monkeypatch, tmp_path):
    from datetime import date
    _library(monkeypatch, tmp_path, date.today())
    thread = _thread("we're in DH399", "say hi to the students")
    audience, topic = bt._identity_audience_for_turn(
        "introduction", "say hi to the students", thread)
    assert audience == "class" and topic.startswith("DH399, ")
    assert bt._identity_audience_for_turn(
        "self_state", "how are you, students?", thread) == (None, "")
    assert bt._identity_audience_for_turn(
        "identity", "who are you really?", _thread("who are you really?")) == (None, "")


def test_the_class_is_the_one_alex_named_not_one_in_a_pinned_block(monkeypatch, tmp_path):
    """By the time the note is built the live turn can carry pinned recall
    blocks; an old episode's course code is not today's class."""
    from datetime import date
    _library(monkeypatch, tmp_path, date.today(), codes=("CS101", "DH399"))
    thread = _thread("we're in DH399 now", (
        "[Dated recall: on Friday you were in the CS101 lecture]\n\n"
        "say hi to the students"))
    _, topic = bt._identity_audience_for_turn(
        "introduction", "say hi to the students", thread)
    assert topic == 'DH399, "What is under the hood of an AI agent? How do they work?"'
    # a CS101 row is read without its date and page count
    assert bt._class_topic_today(["the CS101-A class"]) == (
        'CS101, "Topics in Media and Communication History 1"')


# ---- the pipeline -----------------------------------------------------------------

from test_chat_pipeline import chat  # noqa: E402,F401  (fixture)


def test_a_class_greeting_reaches_the_model_with_the_room(chat, monkeypatch):
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    chat.model.queue("Hi everyone, I'm Blue. Good to see you all today.")
    response = chat.ask("say hi to the students")
    assert response.status_code == 200
    pinned = [m["content"] for m in chat.model.main[0]["messages"]
              if m.get("role") == "user"][-1]
    assert "[IDENTITY GROUNDING" in pinned and "AUDIENCE:" in pinned
    assert pinned.rstrip().endswith("say hi to the students")
    # a greeting with a name but no "robot" is not regenerated
    assert len(chat.model.payloads) == 1
    assert response.get_json()["choices"][0]["message"]["content"].startswith(
        "Hi everyone, I'm Blue.")


def test_a_nameless_class_greeting_is_retried_in_the_room(chat, monkeypatch):
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    chat.model.queue("Hi everyone! Great to see you all.",
                     "Hi everyone, I'm Blue. Good to be here with you.")
    response = chat.ask("say hi to the students")
    retry = chat.model.payloads[1]
    assert any("AUDIENCE:" in str(m.get("content")) and "missing name" in
               str(m.get("content")) for m in retry["messages"])
    assert response.get_json()["choices"][0]["message"]["content"] == (
        "Hi everyone, I'm Blue. Good to be here with you.")


def test_where_is_blue_is_answered_by_the_model_on_caspers_page(chat):
    chat.model.queue("I'm not sure where Blue is right now — I can't see him from here.")
    response = chat.ask("do you know where blue is right now?", robot="pico")
    reply = response.get_json()["choices"][0]["message"]["content"]
    assert chat.model.main, "the model was asked"
    assert "calmer, steadier original companion" not in reply
    assert not chat.executed, "no contact, camera or document lookup for a sibling"
