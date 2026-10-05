"""Style habits and stale context, from the 2026-09-23 log audit.

Run with: python -m pytest test_style_and_context.py

- A third of Blue's replies to ordinary turns ended in a question, often an
  either/or menu; the style note sat ~14,000 characters before the reply.
- A bare course code ("dh201 not dh21") fast-executed a syllabus read that
  ended "cite [filename]", so Alex's own office number came back with a
  syllabus citation.
- "Girls' dance practice" was completed in June, but the past-tense schedule
  kept listing it every Wednesday: "How are you doing tonight after the
  girls' dance practice?" (2026-08-19).
- The polisher prefixed "Okay —" and lower-cased "I am Blue".
- <current_activity> said "You're in the middle of CS101-A", and Blue talked
  as if he sat in Alex's lecture (2026-09-25 harness, 5/5 on "what are you up
  to right now?").
- EMBODIMENT said "You have no wheels", so an invitation to class came back
  as "locked to this workstation"; nothing said a face needs a photo.
"""

import re
import sqlite3
from datetime import datetime, timedelta

import pytest

import bluetools as bt


# ---- course codes in passing ---------------------------------------------------

@pytest.fixture
def library(monkeypatch):
    from blue.tool_selector.detectors.documents import DocumentsDetector as D
    monkeypatch.setattr(D, "_refresh_library", classmethod(lambda cls: None))
    monkeypatch.setattr(D, "_lib_phrases", {"dh201", "dh399", "cs101"})
    monkeypatch.setattr(D, "_lib_tokens_by_doc", [{"dh201", "syllabus"}, {"cs101"}])
    monkeypatch.setattr(D, "_lib_rare_tokens", {"dh201", "cs101"})
    return D


@pytest.mark.parametrize("message", [
    "dh201 not dh21",
    "blue, we are in front of the class in dh201 right now",
    "casper, i plan to take you to my class cs101 on friday.",
    "good. we are on our way to dh399",
    "dh201 actually starts on sept 16 not sept 9",
    # Introducing someone (harness camera_face[1], 2026-10-05).
    "that's clover, she's a ta for cs101",
    "this is sam, he's one of the tas in dh201",
    "clover is a ta for cs101",
])
def test_a_course_code_in_passing_is_not_a_document_request(library, message):
    assert library._library_match(message) is None


def test_a_course_introduced_by_name_is_not_a_person():
    """"this is dh399" introduces a course; it routes as it did before."""
    from blue.tool_selector.detectors.documents import _PERSON_INTRO_RE
    assert not _PERSON_INTRO_RE.search("this is dh399, it's about ai agents")
    assert _PERSON_INTRO_RE.search("that's clover, she's a ta for cs101")


@pytest.mark.parametrize("message", [
    "dh201",
    "tell me about dh201",
    "introduce cs101 to the class. tell them something about the course.",
    "can you introduce the course dh399 to the class?",
    "look at my syllabus for dh201",
    "what is dh201 about?",
    "how is dh201 graded",
    "who are the TAs for cs101",
    "list the tas for cs101",
    "what topics does dh399 cover",
    "tell the class what cs101 is about",
])
def test_asking_about_the_course_still_searches(library, message):
    assert library._library_match(message) is not None


def test_words_that_are_real_titles_are_not_stop_words():
    """"commercial" and "pedagogical" name documents in Alex's library."""
    from blue.tool_selector.detectors import documents
    assert "commercial" not in documents._COMMON_TITLE_WORDS
    assert "pedagogical" not in documents._COMMON_TITLE_WORDS


# ---- the style note is the last thing the model reads -----------------------------

def _system_text(user="Alex", voice=False, heard=False, text="hi", robot="blue"):
    msgs = bt._chat_system_message(
        [{"role": "user", "content": text}], robot=robot, user_name=user,
        voice=voice, language="", system_addendum="", heard=heard)
    return msgs[0]["content"]


def test_the_adult_style_note_comes_last_and_limits_questions():
    text = _system_text()
    assert text.rstrip().endswith("No emoji.")
    assert "never an either/or menu" in text
    assert "if their short reply accepts something you offered, do it" in text


def test_the_kids_style_note_is_unchanged():
    text = _system_text(user="Vilda")
    assert "never an either/or menu" not in text


def test_spoken_adult_replies_end_on_the_answer_and_note_the_transcription():
    text = _system_text(voice=True, heard=True)
    assert "End on your answer" in text
    assert "HEARD, NOT TYPED" in text
    assert "HEARD, NOT TYPED" not in _system_text(user="Vilda", voice=True, heard=True)


def test_blue_answers_questions_about_his_own_tastes():
    text = _system_text(text="what's your favorite music?")
    assert "your own tastes" in text and "never invent an experience" in text


def test_blue_is_not_told_to_keep_an_old_answer_about_his_tastes():
    """The old answer <conversation_memory> held was the 09-16 flat denial
    ("I don't have personal tastes or feelings"), recited 2/3 in replays."""
    text = _system_text(text="what's your favorite music?")
    assert "keep that answer" not in text


def test_no_hard_coded_home_city_for_blue():
    # blue_profile.json (Alex's own profile text) may still name the city.
    assert "workstation in Alex's house in Kitchener" not in _system_text()


# ---- the static rules say what is true -------------------------------------------

def test_blue_can_be_carried_but_cannot_move_himself():
    """"You have no wheels, legs..." made an invitation to class come back as
    "my physical presence is locked to this workstation... be there in
    spirit" or "I am already here" (location_corrections[3], both runs)."""
    text = _system_text()
    assert "You have no wheels" not in text
    assert "you can be carried" in text and "mains power" in text
    assert "on a wheeled cart" in text
    assert "Kuri" in text, "the hallucinated-body guard stays"


@pytest.mark.parametrize("robot", ["hexia", "pico"])
def test_only_blue_is_said_to_ride_a_cart(robot):
    text = _system_text(robot=robot)
    assert "you can be carried" in text
    assert not re.search(r"\bcart\b", text, re.I)


def test_no_face_is_said_to_be_saved_without_a_reference_photo():
    """"I've saved a description of Clover so I can match her" (09-23): no
    face was stored, and none can be without a photo."""
    text = _system_text()
    rule = text[text.index("NO FAKE ACTIONS:"):text.index("REMINDER TIME RULES:")]
    assert "never say you've noted, saved or stored their face" in rule
    assert "Visual Memory page" in rule


def test_the_light_moods_are_left_to_the_tool_schema():
    from blue.server.tool_schemas import RAW_TOOLS
    lights = next(t for t in RAW_TOOLS if t["function"]["name"] == "control_lights")
    assert "moonlight" in str(lights)
    assert "Moods: moonlight" not in _system_text()


def test_the_reminder_example_does_not_prime_tomorrow_at_ten():
    """Invented reminder times were "tomorrow at 10/10:30" in 12 of 15
    samples; the only example in the rules said exactly that."""
    text = _system_text()
    assert "ALWAYS state the full day and date" in text
    assert "tomorrow, Tuesday May 13 at 10am" not in text


# ---- the polisher adds no openers --------------------------------------------------

def test_the_polisher_leaves_the_first_word_alone():
    text = "I am Blue, Alex Levant's robot companion. I run on a workstation Alex set up."
    for _ in range(10):
        out = bt.polish_response_for_conversation(
            text, [{"role": "user", "content": "introduce yourself to the class"}])
        assert out.startswith("I am Blue")


# ---- a finished weekly series stops appearing ---------------------------------------

@pytest.fixture
def reminders_db(tmp_path, monkeypatch):
    import blue_tools_enhanced as bte
    monkeypatch.setattr(bte, "_DB_PATH", str(tmp_path / "enhanced.db"))
    bte._init_db()
    bte._migrate_reminders_columns()
    return bte


def _add_weekly(bte, title, when, completed=0, until=None):
    with bte._conn() as c:
        cur = c.execute(
            "INSERT INTO reminders (user_name, title, when_iso, recurrence, "
            "remind_before_min, completed, archived, until_iso) "
            "VALUES ('Alex', ?, ?, 'weekly', 0, ?, 0, ?)",
            (title, when, completed, until))
        return cur.lastrowid


def test_a_completed_weekly_series_without_an_end_shows_nothing(reminders_db):
    bte = reminders_db
    _add_weekly(bte, "Girls' dance practice", "2026-05-06T18:00", completed=1)
    now = datetime(2026, 8, 19, 20, 55)
    occ = bte.occurrences_in_window(now - timedelta(days=7), now,
                                    include_completed=True, include_archived=True)
    assert occ == []


def test_completing_a_weekly_series_ends_it_but_keeps_its_past(reminders_db):
    bte = reminders_db
    rid = _add_weekly(bte, "Girls' dance practice", "2026-05-06T18:00")
    assert bte.CalendarManager.complete_reminder(rid)["success"]
    with bte._conn() as c:
        until = c.execute("SELECT until_iso FROM reminders WHERE id = ?",
                          (rid,)).fetchone()[0]
    assert until, "the series got an end date"
    past = bte.occurrences_in_window(datetime(2026, 5, 1), datetime(2026, 5, 31),
                                     include_completed=True)
    assert past, "May's practices are still on record"


# ---- the calendar event is Alex's, not Blue's -----------------------------------

def _activity_block(monkeypatch, occurrences):
    import blue_tools_enhanced as bte
    monkeypatch.setattr(bt, "ENHANCED_TOOLS_AVAILABLE", True)
    monkeypatch.setattr(bte, "occurrences_in_window", lambda *a, **k: occurrences)
    return bt._build_current_activity_block()


def _lecture(user_name="Alex"):
    now = datetime.now()
    return {"title": "CS101-A: Intro (Lecture)", "user_name": user_name,
            "start": now - timedelta(minutes=7),
            "end": now + timedelta(minutes=103)}


def test_an_event_in_progress_belongs_to_alex_and_does_not_place_blue(monkeypatch):
    block = _activity_block(monkeypatch, [_lecture()])
    assert "Alex's \"CS101-A" in block
    assert "started" in block and "not yours" in block
    assert "You're in the middle of" not in block
    assert "this conversation with Alex" in block
    assert "Nothing is scheduled for you" in block


def test_the_event_line_does_not_deny_between_conversation_activity(monkeypatch):
    """<j_space> says the workspace revises itself while Blue is away, and the
    reflection worker really does. "Between conversations you are simply
    idle" contradicted it during every class demo, when students ask "do you
    think between conversations?"."""
    block = _activity_block(monkeypatch, [_lecture()])
    assert "idle" not in block
    assert "between conversations" not in block.lower()
    assert "don't present your inner workspace as an activity" in block


@pytest.mark.parametrize("user_name, owner", [
    ("Alex Levant", "Alex's"), ("Emmy", "Emmy's"), ("", "Alex's"),
])
def test_the_event_is_named_as_its_owners(monkeypatch, user_name, owner):
    assert f"{owner} \"CS101-A" in _activity_block(monkeypatch, [_lecture(user_name)])


def test_no_event_says_nothing_about_the_calendar(monkeypatch):
    assert "On the calendar" not in _activity_block(monkeypatch, [])
