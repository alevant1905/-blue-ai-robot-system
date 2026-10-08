"""Context is background: where he is, when they last talked, the day's rows.

Run with: python -m pytest test_context_background.py

From the 10-06/10-07 turns (conversation_log ids):
- "hi" got "Hey Alex, it's been a few days since we last talked." (10108):
  <last_conversation> said "answer with this figure directly".
- "hi" got "I'm here in your office, ready for DH201 in about an hour"
  (10123); during the DH201 lecture "we are in the class rightnow" got
  "Since we are currently in front of the class in **DAWB 2-138**" (10149),
  Alex's office. <location> named only the office; the syllabus says the
  lecture is in SB107.
- "i might take you with me to dh201 tomorrow" (10111) got the day's
  syllabus rows and came back as musing about the syllabus (10112); "we
  will do that in class" (10132) kept the rows of the turn before because
  it was 60 characters or fewer.
"""

from datetime import date, datetime, timedelta

import pytest

import bluetools as bt


def _users(*texts):
    out = []
    for i, text in enumerate(texts):
        if i:
            out.append({"role": "assistant", "content": "(reply)"})
        out.append({"role": "user", "content": text})
    return out


TOMORROW = date.today() + timedelta(days=1)


# ---- <syllabus_day>: a statement of his gets no rows ---------------------------

@pytest.mark.parametrize("thread", [
    # 10111, with the turns before it on 10-06
    ("hi", "how are you", "i might take you with me to dh201 tomorrow"),
    # 10132, after the lab title he shared (10130)
    ("what else are we reading today",
     "today's AI Lab for dh201: How to download, install, and operate local, "
     "private, open-source models",
     "we will do that in class"),
    # 9815, 9643, 9957: taking him to class is news, not a question
    ("i will bring you to sb107 tomorrow morning for class",),
    ("I heck yeah, I'm going to bring you to my class with me on Friday.",),
    ("what am i teaching tomorrow", "when is dh399", "i have you on a cart with wheels."),
    # acknowledgements and greetings after a day question (3772, 3924, 10121)
    ("What are we doing in class on Wednesday in abstract media?",
     "Okay, sounds good. Thanks."),
    ("what do we have tomorrow", "Got it!"),
    ("what are we doing in dh201 today?", "isnt there another reading too?", "hi"),
    ("what do we have tomorrow", "cool"),
    ("what's on in dh399 friday", "we'll see"),
])
def test_a_statement_gets_no_syllabus_day(thread):
    assert bt._syllabus_day_target(_users(*thread)) is None


@pytest.mark.parametrize("thread", [
    # 10017-10025, 09-24: each follow-up asked or corrected
    ("what do we have tomorrow", "are you sure?"),
    ("what do we have tomorrow", "are you sure?", "its not lab 5"),
    ("what do we have tomorrow", "are you sure?", "its not lab 5", "what lab #?"),
    ("what do we have tomorrow", "its not lab 5", "what lab #?", "yup lab 2"),
    ("what do we have tomorrow", "thats not the topic"),
    ("what do we have tomorrow", "and the readings"),
    # pushing back on the rows (3932, 7761, 3928)
    ("can you tell me what readings we're doing tomorrow in that class",
     "You're making those things up."),
    ("what are we reading tomorrow in class", "wrong", "you do have it"),
    ("what do we have tomorrow", "It does try again. Keep looking until you find it."),
    # a short request after his plan for the day (9743)
    ("today we have orientation for the TAs for cs101",
     "tomorrow i will take you to my classes with me", "course content"),
    # a question after his statement asks about that day
    ("i might take you with me to dh201 tomorrow", "what's the reading?"),
])
def test_a_follow_up_that_asks_or_corrects_keeps_the_day(thread):
    assert bt._syllabus_day_target(_users(*thread)) == TOMORROW


@pytest.mark.parametrize("text", [
    "what are we doing tomorrow in that class",          # 10113
    "I wanna focus on our presentation tomorrow in CS101.",  # 454
    "we have dh201 tomorrow right",
    "we're doing lab 5 tomorrow?",
    "i need the readings for dh201 tomorrow",
    "i forgot what we're doing in class tomorrow",
    "i'd like the dh201 readings for tomorrow",
    "i'm not sure what the dh201 lab is tomorrow",
    "we are doing the wrong lab tomorrow in dh201",
    "tomorrow's dh201 class is the lab",
])
def test_his_questions_and_requests_about_a_day_still_get_it(text):
    assert bt._syllabus_day_target(_users(text)) == TOMORROW


def _one_course_library(monkeypatch, tmp_path, day):
    doc = tmp_path / "DH201_AL_2026F.docx"
    doc.write_text("x")
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"folder": "DH201", "filename": "DH201_AL_2026F.docx", "filepath": str(doc)}]})
    label = f"{day.strftime('%B')} {day.day}"
    monkeypatch.setattr(bt, "_syllabus_file_text", lambda fp: (
        f"Class Schedule\nWeek 4 - {label}: Lineages of AI: Connectionism and "
        "Symbolic AI\nReadings:\nWooldridge, Chapter 2 The Golden Age\n"))


def test_the_statement_reaches_the_model_without_the_rows(monkeypatch, tmp_path, chat):
    _one_course_library(monkeypatch, tmp_path, TOMORROW)
    chat.ask("i might take you with me to dh201 tomorrow")
    assert "<syllabus_day>" not in chat.model.system_prompt
    chat.ask("what are we doing in dh201 tomorrow")
    assert "<syllabus_day>" in chat.model.system_prompt
    assert "Lineages of AI" in chat.model.system_prompt


# ---- <location>: background, plus the room of the class going on now -----------

DH201_SYLLABUS = (
    "DH201: Introduction to Generative AI\n"
    "Wednesday 10:00am-12:50pm \n"
    "Fall 2026 \n"
    "Lecture and location\n"
    "Wednesday 10:00am - 12:50pm in SB107. \n"
    "Instructor: Dr. Alex Levant\n"
    "Office hours: Friday 10:30am – 11:30am in DAWB 2-138 or by appointment via Zoom. \n"
    "Course description\n"
    "An introduction to generative AI.\n"
    "Class Schedule\n"
    "October 7 - Lineages of AI\n"
)

LECTURE_NOW = datetime(2026, 10, 7, 11, 44)


@pytest.fixture
def place(monkeypatch, tmp_path):
    import json
    path = tmp_path / "place.json"
    path.write_text(json.dumps({
        "home": "Alex's office at Wilfrid Laurier University (DAWB 2-138)",
        "city": "Waterloo", "current": None, "current_set_at": None}))
    monkeypatch.setattr(bt, "_PLACE_PATH", str(path))
    return path


@pytest.fixture
def calendar(monkeypatch, tmp_path):
    """The DH201 syllabus in the library and a settable calendar."""
    import blue_tools_enhanced as bte
    doc = tmp_path / "DH201_AL_2026F.docx"
    doc.write_text("x")
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"folder": "DH201", "filename": "DH201_AL_2026F.docx", "filepath": str(doc)}]})
    monkeypatch.setattr(bt, "_syllabus_file_text", lambda fp: DH201_SYLLABUS)
    monkeypatch.setattr(bt, "ENHANCED_TOOLS_AVAILABLE", True)
    events = []
    monkeypatch.setattr(bte, "occurrences_in_window", lambda *a, **k: list(events))
    return events


def _event(title, start, end, user_name="Alex", description=None):
    return {"title": title, "user_name": user_name, "description": description,
            "start": start, "end": end, "recurring": True}


def _dh201(day=LECTURE_NOW):
    return _event("DH201: Introduction to Generative AI (Lecture)",
                  day.replace(hour=10, minute=0), day.replace(hour=12, minute=50))


def test_the_base_is_background_not_news(place, calendar):
    block = bt._build_location_block()
    assert ("Your base is Alex's office at Wilfrid Laurier University (DAWB 2-138) "
            "in Waterloo. That's background, not news: say where you are only when "
            "Alex asks or when it matters to what he said. If Alex has said where "
            "you are now, that is where you are.") in block
    assert "teaching" not in block, "no class on the calendar, no class line"


def test_during_the_lecture_the_room_comes_from_the_syllabus(calendar):
    """The text the S3 replays measured (s3/t_s3.py CLASS_LINE)."""
    calendar.append(_dh201())
    assert bt._class_room_line(LECTURE_NOW) == (
        "Alex is teaching DH201 in SB107 until 12:50 PM. If he says you're "
        "in class, you're in SB107.")


def test_the_office_hours_room_is_not_the_lecture_room():
    assert bt._lecture_room(
        "Lecture and location\n"
        "Office hours: Friday 10:30am - 11:30am in DAWB 2-138 or by appointment.\n"
        "Friday 8:30 - 10:20am starting September 11, 2026 in ART 1E1") == "ART 1E1"
    assert bt._lecture_room("Lecture and location\nThursdays, online") == ""


@pytest.mark.parametrize("title, description, room", [
    ("CS101-A: Canadian Communication in Context (Lecture)",
     "Lecture in ART 1E1 starting September 11, 2026. See CS101A_Levant_2026F.docx "
     "for details on tutorials, assignments, and policies.", "ART 1E1"),
    ("CMDS4740 Surveillance, Media, and Society",
     "Location: VH 1154. Current focus: Education and AI.", "VH 1154"),
    # the calendar's room comes before the syllabus's
    ("DH201: Introduction to Generative AI (Lecture)", "Moved to BA201 today", ""),
    ("DH201: Introduction to Generative AI (Lecture)", "Location: BA 201", "BA 201"),
])
def test_the_calendar_event_names_the_room(calendar, title, description, room):
    calendar.append(_event(title, LECTURE_NOW.replace(hour=10),
                           LECTURE_NOW.replace(hour=12, minute=50), description=description))
    line = bt._class_room_line(LECTURE_NOW)
    if room:
        assert f" in {room} until 12:50 PM. If he says you're in class, you're in {room}." in line
    else:
        assert "you're in SB107." in line, "no room in the description: the syllabus's"


@pytest.mark.parametrize("event", [
    _event("Dentist", LECTURE_NOW.replace(hour=11), LECTURE_NOW.replace(hour=12)),
    _event("Meeting about DH201 next term", LECTURE_NOW.replace(hour=11),
           LECTURE_NOW.replace(hour=12)),
    _event("DH201: Introduction to Generative AI (Lecture)",
           LECTURE_NOW.replace(hour=10), LECTURE_NOW.replace(hour=12, minute=50),
           user_name="Emmy"),
    # a course whose syllabus is not in the library, with no room on the event
    _event("CS240J: Programming (Lecture)", LECTURE_NOW.replace(hour=10),
           LECTURE_NOW.replace(hour=12, minute=50)),
])
def test_no_class_line_without_his_class_and_its_room(calendar, event):
    calendar.append(event)
    assert bt._class_room_line(LECTURE_NOW) == ""


def test_no_class_line_after_the_lecture(calendar):
    calendar.append(_dh201())
    assert bt._class_room_line(LECTURE_NOW.replace(hour=13, minute=5)) == ""


def test_the_class_line_is_inside_location_during_the_lecture(place, calendar):
    now = datetime.now()
    calendar.append(_event("DH201: Introduction to Generative AI (Lecture)",
                           now - timedelta(minutes=30), now + timedelta(minutes=60)))
    block = bt._build_location_block()
    assert block.startswith("<location>\n") and block.endswith("\n</location>")
    assert "That's background, not news" in block
    assert "Alex is teaching DH201 in SB107 until " in block
    assert "If he says you're in class, you're in SB107." in block
    # <current_activity> still says the event doesn't place him by itself
    assert "only Alex or <location> can" in bt._build_current_activity_block()


def test_a_place_he_set_wins_over_the_calendar(place, calendar):
    import json
    now = datetime.now()
    place.write_text(json.dumps({
        "home": "his office", "city": "", "current": "the cottage",
        "current_set_at": now.isoformat()}))
    calendar.append(_event("DH201: Introduction to Generative AI (Lecture)",
                           now - timedelta(minutes=30), now + timedelta(minutes=60)))
    block = bt._build_location_block()
    assert "the cottage" in block and "SB107" not in block


def test_a_broken_calendar_never_breaks_the_location(place, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db locked")
    monkeypatch.setattr(bt, "_calendar_event_now", boom)
    assert "Your base is" in bt._build_location_block()


def test_the_system_prompt_has_one_location_with_the_room(place, calendar):
    now = datetime.now()
    calendar.append(_event("DH201: Introduction to Generative AI (Lecture)",
                           now - timedelta(minutes=30), now + timedelta(minutes=60)))
    text = bt.build_dynamic_system_message(
        _users("we are in the class rightnow"),
        bt.build_system_preamble(robot_name="Blue"), robot="blue")["content"]
    assert text.count("\n<location>\n") == 1
    assert "you're in SB107." in text
    assert text.index("<location>") < text.index("<now>")


# ---- <last_conversation>: the figure answers the question, it doesn't open "hi" --

def test_the_last_conversation_is_not_news_to_open_a_greeting_with(tmp_path):
    import sqlite3
    import blue_memory_improved as bmi
    memory = bmi.EnhancedMemorySystem(db_path=str(tmp_path / "m.db"))
    four_days = (datetime.now() - timedelta(days=4)).isoformat()
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute(
            "INSERT INTO conversation_log (timestamp, user_name, role, content, robot) "
            "VALUES (?, 'Alex', 'user', 'hi', 'blue')", (four_days,))
    block = memory._build_last_conversation_block(user_name="Alex", robot="blue")
    assert "4 days ago" in block
    assert ("how long since we last talked, answer with this figure; it is not "
            "news to open a greeting with.") in block
    assert "figure directly" not in block
    # the denial rule the temporal guard leans on is still there
    assert "Never say you have no log of past conversations" in block


from test_chat_pipeline import chat  # noqa: E402,F401  (fixture)
