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


@pytest.mark.parametrize("turns", [
    # A number after a short word is no course code (P2-4 review): the
    # canned introduction went out at the party.
    ("there are 150 people at Stella's party", "say hello to everyone"),
    ("we'll be in room 138 with the neighbours", "say hello to everyone"),
    ("I'm at 630 Main with the girls", "say hello to everyone"),
])
def test_a_number_is_not_a_course(turns):
    assert _kind(*turns) is None


@pytest.mark.parametrize("named", [
    "we're in dh399 today", "we're in CS 101 today", "we're in BH399.",
    "this is CS-101",
])
def test_a_course_code_still_names_the_class(named):
    assert _kind(named, "say hello to everyone") == "introduction"


# ---- a greeting remembered, reported, the user's own, or written --------------
# P2-4 review: each of these was a live introduction, so a recall lost its
# memory blocks and a nameless answer was replaced by the canned introduction.

@pytest.mark.parametrize("text, kind", [
    ("do you remember when you had to say hello to the class last week?",
     "shared_recall"),
    ("what did you say when I asked you to say hi to the students?", None),
    ("remember when I asked you to say hello to the students?", None),
    ("last thursday I asked you to say hello to the class. what did you say?",
     None),
    ("you were supposed to say hi to the class, what happened?", None),
    ("I told you to say hello to the class", None),
])
def test_a_remembered_or_reported_greeting_is_no_introduction(text, kind):
    assert identity_request_kind(text) == kind
    assert _kind(text) == kind
    from blue_identity import asked_after_himself
    assert not asked_after_himself(text)


@pytest.mark.parametrize("text", [
    "how do I say hello to the class in French?",
    "Should I say hi to the class?",
    "I'll say hi to the students first",
    "let me say hello to the class before we start",
    "how to say good morning to the class in Danish",
    "email the students and say hello to the class for me",
    "write a message to my students to say hi to the class",
    "say hi to the students in the email",
    "send them a short note and say hi to the class",
])
def test_the_users_own_or_a_written_greeting_is_no_introduction(text):
    assert _kind(text) is None


@pytest.mark.parametrize("text", [
    "say hello to the class in French",
    "can I get you to say hi to the students?",
    "let me hear you say hello to the class",
    "I'd like you to say hello to the class.",
    "Blue, say hi to the class. We're reading the text by Pasquinelli today.",
    "I got an email from the dean, say hi to the class",
    "great reply, now say hello to the students",
    # the six logged class greetings (P2-4's sweep)
    "Here we are Wilfred Laurie university in CS101 would you like to say "
    "hello to the class.",
    "I want you to stop repeating that I want you to accept the fact that you "
    "can be moved around and that I brought you to look for glory university "
    "accept that you're actually there and say hello to the class.",
    "I brought you here to look for Laura university we're in front of the "
    "classroom right now it's in CS 10101 I'd like you to say hello to the "
    "class.",
    "We're here at Wilfred Laura university in CS101 do you wanna say hello "
    "to the class.",
    "we're in front of the class here in DH201. Do you want to say hello to "
    "everyone?",
    "we're in BH399. Do you want to say hello to the students?",
])
def test_a_greeting_asked_of_him_now_stays_an_introduction(text):
    assert _kind(text) == "introduction"


def test_a_recalled_class_greeting_keeps_the_recall_blocks(tmp_path, monkeypatch):
    """"A user asking what was said … still gets it" (_skips_recalled_days):
    both lost <remembered_days> and <earlier_answers> as introductions."""
    from blue_memory_improved import EnhancedMemorySystem
    from test_memory_recall import _ask, _at, _blocks, _seed
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [
        (_at(6, 12, 26), "user",
         "we're in DH399. Do you want to say hello to the students?"),
        (_at(6, 12, 27), "assistant",
         "Hi everyone, I'm Blue, Alex's robot. Today is about AI agents."),
        (_at(6, 12, 29), "user", "what should the students read for the class?"),
        (_at(6, 12, 30), "assistant", "Crawford, chapter two, on the planetary costs."),
    ])
    for asked in ("do you remember when you had to say hello to the class "
                  "last week?",
                  "what did you say when I asked you to say hi to the students?"):
        thread = _ask(asked)
        assert not EnhancedMemorySystem._skips_recalled_days(
            thread, asked, chat_turn=True)
        # <earlier_answers> is skipped for any other identity kind
        assert contextual_identity_request_kind(asked, thread) in (
            None, "shared_recall")
        assert "remembered_days" in _blocks(memory, monkeypatch, thread)


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
    # a kind, not a room
    assert class_audience("who are you? what class of AI are you?") is None
    assert class_audience("i want you to introduce yourself to the class of "
                          "cmds4740") == "class"
    assert class_audience("I'm grading my students' essays") is None


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
    # a state, not a place (P2-4 review)
    ("we're in trouble", None),
    ("we're in a meeting until four", None),
    ("we're in luck, the bus is late", None),
    ("ha, we're at it again", None),
    ("we're in this together", None),
    ("we're in Italy", ("Italy", "in")),
    ("we're at a friend's house", ("a friend's house", "at")),
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
    # P2-4 review: the paragraph again, or one that doesn't answer
    ("blue", "tell me more about hexia"),
    ("blue", "do you miss hexia?"),
    ("hexia", "do you trust blue?"),
    ("pico", "do you love blue?"),
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
        "introduction", "say hi to the students", thread, user_name="Alex")
    assert audience == "class" and topic.startswith("DH399, ")
    assert bt._identity_audience_for_turn(
        "self_state", "how are you, students?", thread,
        user_name="Alex") == (None, "")
    assert bt._identity_audience_for_turn(
        "identity", "who are you really?", _thread("who are you really?"),
        user_name="Alex") == (None, "")


@pytest.mark.parametrize("text", [
    "say hi to my class",
    "tell me about yourself, my class is learning about robots",
])
def test_vildas_class_is_not_alexs_students(monkeypatch, tmp_path, text):
    """P2-4 review: on the kids' page "say hi to my class" got the AUDIENCE
    line, "These are Alex's students, live in the room… first-year class"."""
    from datetime import date
    _library(monkeypatch, tmp_path, date.today())
    thread = _thread("we're in DH399", text)
    kind = contextual_identity_request_kind(text, thread)
    assert kind in ("introduction", "identity")
    assert bt._identity_audience_for_turn(
        kind, text, thread, user_name="Vilda") == (None, "")
    assert bt._identity_audience_for_turn(
        kind, text, thread, user_name="Alex")[0] == "class"


def test_the_class_is_the_one_alex_named_not_one_in_a_pinned_block(monkeypatch, tmp_path):
    """By the time the note is built the live turn can carry pinned recall
    blocks; an old episode's course code is not today's class."""
    from datetime import date
    _library(monkeypatch, tmp_path, date.today(), codes=("CS101", "DH399"))
    thread = _thread("we're in DH399 now", (
        "[Dated recall: on Friday you were in the CS101 lecture]\n\n"
        "say hi to the students"))
    _, topic = bt._identity_audience_for_turn(
        "introduction", "say hi to the students", thread, user_name="Alex")
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


def _pinned(chat):
    return [m["content"] for m in chat.model.main[0]["messages"]
            if m.get("role") == "user"][-1]


def _reply(response):
    return response.get_json()["choices"][0]["message"]["content"]


@pytest.mark.parametrize("asked", [
    "do you remember when you had to say hello to the class last week?",
    "what did you say when I asked you to say hi to the students?",
])
def test_a_recalled_class_greeting_is_answered_not_reintroduced(chat, monkeypatch, asked):
    """P2-4 review: both got the introduction task and the AUDIENCE line, and
    this nameless recall was replaced by the canned hardware introduction."""
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    recall = ("Yes — last week I greeted the DH399 students and talked about "
              "AI agents.")
    chat.model.queue(recall)
    response = chat.ask(asked)
    pinned = _pinned(chat)
    assert "Speak as though the named audience" not in pinned
    assert "AUDIENCE:" not in pinned
    assert len(chat.model.payloads) == 1
    assert _reply(response) == recall


def test_how_to_greet_the_class_is_a_question_not_a_greeting(chat, monkeypatch):
    """It pinned the introduction task, offered no tools, and shipped "Hello
    everyone at French. I'm Blue…" after a nameless answer (P2-4 review)."""
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    chat.model.queue("Bonjour à tous!")
    response = chat.ask("how do I say hello to the class in French?")
    assert "[IDENTITY GROUNDING" not in _pinned(chat)
    assert len(chat.model.payloads) == 1
    assert _reply(response) == "Bonjour à tous!"


@pytest.mark.parametrize("asked", [
    "say hi to my class!",
    "my class is on the call, say hello to everyone",
])
def test_vildas_class_greeting_is_an_ordinary_turn(chat, monkeypatch, asked):
    """Whole-branch review: on the kids' page her class is hers. Read as an
    introduction, the turn had the adult identity note about Alex's robot
    beside her words and no tools, and "Hi everyone! Have a fun day at
    school!" was regenerated for leaving out his name, then replaced by the
    canned introduction.

    Asserted on what the code builds, the turn as pinned and the tools
    offered: the payload as a whole carries live memory text (the J-space
    block), which may say "Alex's students" any day."""
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    monkeypatch.setattr(bt, "_identify_user_from_request", lambda: "Vilda")
    greeting = "Hi everyone! Have a fun day at school!"
    chat.model.queue(greeting)
    response = chat.ask(asked)
    pinned = _pinned(chat)
    assert "[IDENTITY GROUNDING" not in pinned
    assert "AUDIENCE:" not in pinned and "Alex's students" not in pinned
    assert chat.model.main[0].get("tools"), "her tools are offered"
    assert len(chat.model.payloads) == 1, "a greeting without his name stands"
    assert _reply(response) == greeting


def test_a_class_greeting_introduces_him_only_to_an_adults_class():
    """The kids' page passes class_greetings=False (_speaker_identity_kind);
    "introduce yourself" is an introduction on any page."""
    for asked in ("say hi to my class", "say hello to the students"):
        assert bt._speaker_identity_kind(
            asked, _thread(asked), user_name="Alex") == "introduction"
        assert bt._speaker_identity_kind(
            asked, _thread(asked), user_name="Vilda") is None
    everyone = _thread("my class is on the call", "say hello to everyone")
    assert bt._speaker_identity_kind(
        "say hello to everyone", everyone, user_name="Alex") == "introduction"
    assert bt._speaker_identity_kind(
        "say hello to everyone", everyone, user_name="Vilda") is None
    assert bt._speaker_identity_kind(
        "introduce yourself to my class", _thread("introduce yourself to my class"),
        user_name="Vilda") == "introduction"
    # "tell me more" after her greeting is no identity follow-up either
    after = _thread("say hi to my class", "tell me more")
    assert bt._speaker_identity_kind(
        "tell me more", after, user_name="Vilda") is None


@pytest.mark.parametrize("text, kind, wanted", [
    # the room, not the household (the 09-16 turn is the one logged turn of
    # 403 with <family> that this changes)
    ("we're in front of the class here in DH201. Do you want to say hello "
     "to everyone?", "introduction", False),
    ("tell everyone a bit about yourself", "identity", False),
    ("say hello to everybody", "introduction", False),
    # still the household
    ("introduce yourself to everyone in my family", "introduction", True),
    ("do you remember everyone's names?", None, True),
    ("how is everyone doing at home?", None, True),
    ("tell me about the girls", None, True),
    ("what's the weather like?", None, False),
])
def test_everyone_in_an_introduction_is_the_room(text, kind, wanted):
    assert bt._asks_about_the_family(text, kind) is wanted


def test_a_class_introduction_carries_no_family_roster(chat, monkeypatch):
    """Whole-branch review: the class greeting's payload carried <family>
    (Athena's age and school, the bunk beds, where Stella teaches) beside
    the AUDIENCE line. The block is stubbed: the live one is built from the
    facts table."""
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    monkeypatch.setattr(bt, "_family_ground_truth_block",
                        lambda: "<family>\nFAMILY ROSTER\n</family>")
    chat.model.queue("Hi everyone, I'm Blue. Good to see you all today.")
    chat.ask("we're in front of the DH399 class right now. do you want to say "
             "hello to everyone?")
    assert "AUDIENCE:" in _pinned(chat)
    assert "FAMILY ROSTER" not in str(chat.model.main[0]["messages"])
    chat.model.queue("Athena, Emmy and Vilda, and Nori.")
    chat.ask("do you remember everyone's names?")
    assert "FAMILY ROSTER" in str(chat.model.main[-1]["messages"])


def test_tell_me_more_about_hexia_is_not_the_same_paragraph(chat):
    """After the canned answer to "what do you think of hexia?", "tell me
    more about hexia" got the identical paragraph, with no model call."""
    first = _reply(chat.ask("what do you think of hexia?"))
    assert first.startswith("Hexia is my quick") and not chat.model.payloads
    chat.model.queue("She once asked me whether I dream in Danish, and then "
                     "argued with my answer for ten minutes.")
    second = _reply(chat.ask("tell me more about hexia", messages=[
        {"role": "user", "content": "what do you think of hexia?"},
        {"role": "assistant", "content": first},
        {"role": "user", "content": "tell me more about hexia"}]))
    assert chat.model.main, "the model was asked"
    assert second != first and "quick, mischievous counterpart" not in second
