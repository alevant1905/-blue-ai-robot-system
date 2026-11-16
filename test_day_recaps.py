"""What Blue keeps of a day: the recap in session_summaries.

Read from his live memory on 2026-11-16 (142 stored days):

  * 11 recaps were keyword stand-ins, written when the model was busy or
    unloaded and never written again: "Conversation touching on assistant,
    user, today, open, class, source." (10-07). The first two "topics" are
    the speaker labels of the transcript.
  * The rest called their speakers "the user" and "the assistant", and came
    back to Blue as memories of his own day in those words.
  * Each was written from the day's last 4,000 characters at 300 a message:
    of 09-24's 63 exchanges, the final dozen.
  * A day that was one "hello" got a recap ("The assistant greeted the user,
    Alex.") and a memory to match.
  * None of it reached <earlier_sessions>, which held the last four things
    Alex said that day at 120 characters each.

No test here calls a model: _llm_extract is replaced.
"""

import datetime
import json
from datetime import timedelta

import pytest

import blue_memory_improved as bmi
from blue_memory_improved import EnhancedMemorySystem

STAND_IN = EnhancedMemorySystem.FALLBACK_SUMMARY_PREFIX


def _at(days_ago, hour, minute=0):
    return (datetime.datetime.now() - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def _day(days_ago):
    return _at(days_ago, 12).date().isoformat()


def _seed(memory, rows):
    """rows: (when, role, content) or (when, role, content, robot, user)."""
    conn = memory._conn()
    for row in rows:
        when, role, content = row[:3]
        robot = row[3] if len(row) > 3 else "blue"
        user = row[4] if len(row) > 4 else "Alex"
        conn.execute(
            "INSERT INTO conversation_log (timestamp, user_name, role, content, "
            "session_id, importance, robot) VALUES (?, ?, ?, ?, NULL, 5, ?)",
            (when.isoformat(), user, role, content, robot))
    conn.commit()
    conn.close()


def _recap(memory, day):
    conn = memory._conn()
    row = conn.execute("SELECT summary, topics FROM session_summaries "
                       "WHERE session_id = ?", (day,)).fetchone()
    conn.close()
    return (row["summary"], row["topics"]) if row else None


def _session_memories(memory, day):
    conn = memory._conn()
    rows = conn.execute("SELECT content FROM memories WHERE type = 'session' "
                        "AND subject = ?", (f"conversation on {day}",)).fetchall()
    conn.close()
    return [r["content"] for r in rows]


@pytest.fixture
def memory(tmp_path):
    return EnhancedMemorySystem(str(tmp_path / "memory.db"))


@pytest.fixture
def model(monkeypatch):
    """The recap model: `model.reply` is what it returns (None = unloaded);
    `model.prompts` is what it was asked."""
    class Model:
        reply = json.dumps({"summary": "Alex and Blue planned the DH399 lab.",
                            "topics": ["DH399", "lab"]})
        prompts = []

    Model.prompts = []

    def fake(prompt, timeout=30):
        Model.prompts.append(prompt)
        return Model.reply

    monkeypatch.setattr(bmi, "_llm_extract", fake)
    monkeypatch.setattr(bmi, "LLM_EXTRACTION_ENABLED", True)
    return Model


LAB_DAY = [
    (_at(3, 9, 0), "user", "lets plan the second lab for dh399, the one on agents"),
    (_at(3, 9, 1), "assistant", "A lab where each group builds one small agent and breaks it."),
    (_at(3, 9, 5), "user", "good. what should they hand in at the end"),
    (_at(3, 9, 6), "assistant", "A one page log of what the agent did and where it went wrong."),
]


# ---- the transcript ---------------------------------------------------------

def test_the_transcript_names_its_speakers(memory, model):
    _seed(memory, LAB_DAY + [
        (_at(3, 16, 0), "user", "can you tell me a story about a dragon",
         "hexia", "Vilda"),
        (_at(3, 16, 1), "assistant", "Once there was a dragon who collected socks.",
         "hexia", "Vilda"),
        (_at(3, 17, 0), "user", "what is the homework for cs101 this week",
         "pico", "Alex"),
        (_at(3, 17, 1), "assistant", "The reading response on chapter two.",
         "pico", "Alex"),
    ])
    memory.summarize_session(_day(3))

    sent = model.prompts[-1]
    assert "Alex: lets plan the second lab for dh399" in sent
    assert "Blue: A lab where each group builds one small agent" in sent
    assert "Vilda: can you tell me a story about a dragon" in sent
    assert "Hexia: Once there was a dragon" in sent
    assert "Casper: The reading response on chapter two." in sent
    assert "USER:" not in sent and "ASSISTANT:" not in sent
    # The model is told who the names are, and not to fall back on roles.
    assert "Never write 'the user' or 'the assistant'" in sent


def test_a_long_day_keeps_its_morning(memory, model):
    """63 exchanges on 09-24; the recap was written from the last dozen."""
    rows = [(_at(3, 8, 0), "user", "first thing: the dean wants the lab budget by friday"),
            (_at(3, 8, 1), "assistant", "Then the budget goes ahead of the syllabus today.")]
    for i in range(70):
        rows.append((_at(3, 9, 0) + timedelta(minutes=2 * i), "user",
                     f"point {i}: " + "we went over the reading in detail " * 12))
        rows.append((_at(3, 9, 1) + timedelta(minutes=2 * i), "assistant",
                     f"reply {i}: " + "the chapter argues the opposite " * 12))
    rows.append((_at(3, 20, 0), "user", "last thing: remind me about the grant on monday"))
    _seed(memory, rows)

    transcript, user_words = memory._day_transcript(_day(3))

    assert len(transcript) <= memory.DAY_TRANSCRIPT_CHARS + 60
    assert "the dean wants the lab budget by friday" in transcript
    assert "remind me about the grant on monday" in transcript
    # Every exchange is there, each cut short.
    assert "point 0:" in transcript and "point 35:" in transcript
    assert "point 69:" in transcript
    assert user_words > 500


def test_more_exchanges_than_fit_keeps_both_ends_and_says_so(memory):
    rows = []
    for i in range(400):
        rows.append((_at(3, 0, 0) + timedelta(minutes=3 * i), "user",
                     f"message number {i} " + "about the course outline " * 10))
    _seed(memory, rows)

    transcript, _ = memory._day_transcript(_day(3))

    assert len(transcript) <= memory.DAY_TRANSCRIPT_CHARS + 60
    assert "message number 0 " in transcript
    assert "message number 399 " in transcript
    assert "the middle of the day is left out" in transcript


# ---- what is stored ---------------------------------------------------------

def test_a_recap_is_stored_and_remembered(memory, model):
    _seed(memory, LAB_DAY)
    assert memory.summarize_session(_day(3)) is True
    assert _recap(memory, _day(3)) == ("Alex and Blue planned the DH399 lab.",
                                       "DH399, lab")
    assert _session_memories(memory, _day(3)) == [
        "Alex and Blue planned the DH399 lab. (topics: DH399, lab)"]


@pytest.mark.parametrize("said", [["hi"], ["hello", "you there"], ["good morning blue"]])
def test_a_day_that_was_only_a_greeting_is_no_memory(memory, model, said):
    """"The assistant greeted the user, Alex." was the whole of 10-18."""
    rows = []
    for i, text in enumerate(said):
        rows.append((_at(3, 9, i), "user", text))
        rows.append((_at(3, 9, i), "assistant", "Hey. Good to see you."))
    _seed(memory, rows)

    assert memory.summarize_session(_day(3)) is True

    assert model.prompts == []
    assert _recap(memory, _day(3)) == ("", "")
    assert _session_memories(memory, _day(3)) == []
    # A row is written all the same, so the day is not offered again.
    assert memory._unsummarized_session_date() is None


def test_the_stand_in_counts_what_was_said_not_who_said_it(memory, model):
    model.reply = None
    _seed(memory, LAB_DAY)
    memory.summarize_session(_day(3))

    summary, topics = _recap(memory, _day(3))
    assert summary.startswith(STAND_IN)
    words = set(topics.split(", "))
    assert not words & {"alex", "blue", "user", "assistant"}
    assert "agent" in words or "agents" in words
    # A stand-in is no memory of the day.
    assert _session_memories(memory, _day(3)) == []


def test_a_stand_in_is_written_again_when_the_model_is_back(memory, model):
    """10-07 stayed "Conversation touching on assistant, user, today, open,
    class, source." for five weeks."""
    _seed(memory, LAB_DAY)
    model.reply = None
    assert memory.summarize_previous_sessions() == 1
    assert _recap(memory, _day(3))[0].startswith(STAND_IN)
    # Not again in the same run: a model that is still down costs one call.
    calls = len(model.prompts)
    assert memory.summarize_previous_sessions() == 0
    assert len(model.prompts) == calls

    # The server is started again, and the model is loaded this time.
    restarted = EnhancedMemorySystem(memory.db_path)
    model.reply = json.dumps({"summary": "Alex and Blue planned the DH399 lab.",
                              "topics": ["DH399"]})
    assert restarted.summarize_previous_sessions() == 1
    assert _recap(restarted, _day(3))[0] == "Alex and Blue planned the DH399 lab."
    assert _session_memories(restarted, _day(3)) == [
        "Alex and Blue planned the DH399 lab. (topics: DH399)"]
    assert restarted.summarize_previous_sessions() == 0


def test_an_old_stand_in_and_its_memory_are_replaced(memory, model):
    """As stored before this change: the stand-in in both tables, on a day
    older than the 90 the catch-up looks back over."""
    old = 140
    _seed(memory, [(_at(old, 9, 0), "user",
                    "lets plan the second lab for dh399, the one on agents"),
                   (_at(old, 9, 1), "assistant", "Each group builds one small agent.")])
    junk = STAND_IN + "assistant, user, today, open, class, source."
    conn = memory._conn()
    conn.execute("INSERT INTO session_summaries (session_id, summary, topics, created_at) "
                 "VALUES (?, ?, ?, ?)", (_day(old), junk, "assistant, user", "2026-10-08T14:12:00"))
    conn.commit()
    conn.close()
    memory._store_memory(mem_type="session", subject=f"conversation on {_day(old)}",
                         content=junk, source="session_summary", importance=0.6)

    assert memory.summarize_previous_sessions() == 1

    assert _recap(memory, _day(old))[0] == "Alex and Blue planned the DH399 lab."
    assert _session_memories(memory, _day(old)) == [
        "Alex and Blue planned the DH399 lab. (topics: DH399, lab)"]


def test_a_stand_in_never_replaces_a_recap_the_model_wrote(memory, model):
    _seed(memory, LAB_DAY)
    memory.summarize_session(_day(3))
    model.reply = None

    assert memory.summarize_session(_day(3)) is True

    assert _recap(memory, _day(3))[0] == "Alex and Blue planned the DH399 lab."


def test_backfill_does_not_remember_stand_ins(memory):
    conn = memory._conn()
    conn.execute("INSERT INTO session_summaries (session_id, summary, topics, created_at) "
                 "VALUES (?, ?, ?, ?)", (_day(9), STAND_IN + "user, assistant.", "", "x"))
    conn.execute("INSERT INTO session_summaries (session_id, summary, topics, created_at) "
                 "VALUES (?, ?, ?, ?)", (_day(8), "Alex asked Blue about the lab.", "", "x"))
    conn.commit()
    conn.close()

    memory.backfill_session_memories()

    assert _session_memories(memory, _day(9)) == []
    assert _session_memories(memory, _day(8)) == ["Alex asked Blue about the lab."]


# ---- what he is shown -------------------------------------------------------

def test_earlier_sessions_carry_the_recap_of_his_own_day(memory, model):
    _seed(memory, LAB_DAY)
    memory.summarize_session(_day(3))

    block = memory._build_session_history_block(robot="blue")

    assert "Alex: lets plan the second lab for dh399" in block
    assert "The day in short: Alex and Blue planned the DH399 lab." in block


SHARED_DAY = LAB_DAY + [
    (_at(3, 16, 0), "user", "tell me a story about a dragon", "hexia", "Vilda"),
    (_at(3, 16, 1), "assistant", "Once there was a dragon.", "hexia", "Vilda"),
]


def test_a_shared_day_is_shown_only_to_a_robot_its_recap_names(memory, model):
    """One row a date for every robot. A recap that says who did what can
    be shown to a robot it names; Hexia is not in this one."""
    _seed(memory, SHARED_DAY)
    memory.summarize_session(_day(3))

    blue = memory._build_session_history_block(robot="blue")
    hexia = memory._build_session_history_block(robot="hexia")

    assert ("The day in short: (the other robots' conversations that day are "
            "in it too, each under its own name) Alex and Blue planned the "
            "DH399 lab.") in blue
    assert hexia and "The day in short:" not in hexia


def test_a_shared_day_in_the_old_wording_is_nobodys(memory):
    """"The assistant" on a day two robots talked: Hexia took Blue's day
    for hers, which is why the recaps left this block."""
    _seed(memory, SHARED_DAY)
    conn = memory._conn()
    conn.execute("INSERT INTO session_summaries (session_id, summary, topics, created_at) "
                 "VALUES (?, ?, ?, ?)", (
                     _day(3), "The user planned a lab with the assistant, and "
                     "Blue told a story about a dragon.", "", "x"))
    conn.commit()
    conn.close()

    for robot in ("blue", "hexia"):
        block = memory._build_session_history_block(robot=robot)
        assert block and "The day in short:" not in block


def test_an_old_recap_is_shown_with_names(memory):
    """A recap stored before 2026-11-16, as it reads in the live table."""
    _seed(memory, LAB_DAY)
    conn = memory._conn()
    conn.execute("INSERT INTO session_summaries (session_id, summary, topics, created_at) "
                 "VALUES (?, ?, ?, ?)", (
                     _day(3),
                     "The user asked the assistant about its location and recent "
                     "changes, to which the assistant responded that it remains "
                     "at the office.", "", "x"))
    conn.commit()
    conn.close()

    block = memory._build_session_history_block(robot="blue")

    assert ("The day in short: Alex asked Blue about its location and recent "
            "changes, to which Blue responded that it remains at the office.") in block
    assert "the user" not in block.split("The day in short:")[1].lower()


def test_a_stand_in_is_not_shown_as_the_day(memory, model):
    model.reply = None
    _seed(memory, LAB_DAY)
    memory.summarize_session(_day(3))

    block = memory._build_session_history_block(robot="blue")

    assert "Alex: lets plan the second lab for dh399" in block
    assert "The day in short:" not in block
    assert STAND_IN not in block


# ---- a day asked for by its date --------------------------------------------
# 2026-11-16, live: "what happened when we did the dh201 class on october
# 7th?" got "I don't have a record of that specific class", with 35 rows of
# that class in the log. Nothing in the memory layer read a calendar date.

from blue_identity import recall_day_asked  # noqa: E402

TODAY = datetime.date(2026, 11, 16)


@pytest.mark.parametrize("text, day", [
    ("what happened when we did the dh201 class on october 7th?", (2026, 10, 7)),
    ("what did we talk about on october 7", (2026, 10, 7)),
    ("do you remember our conversation on the 7th of october?", (2026, 10, 7)),
    ("what did i tell you on Oct. 24th", (2026, 10, 24)),
    ("remember what we discussed september 24?", (2026, 9, 24)),
    # A date still ahead this year is last year's.
    ("what did we talk about on december 3rd", (2025, 12, 3)),
    # The older forms are untouched.
    ("what did we talk about yesterday?", (2026, 11, 15)),
    ("what did we talk about on friday", (2026, 11, 13)),
])
def test_a_calendar_date_in_a_recall_question_is_that_day(text, day):
    assert recall_day_asked(text, today=TODAY) == datetime.date(*day)


@pytest.mark.parametrize("text", [
    # No recall in it: a plan, a fact, a request.
    "i have a talk on october 7th",
    "the assignment is due october 7th",
    "remember to book the room for december 3rd",
    "put the dentist on october 7th at 3",
    # Recall, but the date is where something is going to happen.
    "do you remember we will have the guest lecture on december 3rd",
    "what did we say is due by october 7th",
    # A thing on that date, not a conversation.
    "what is october 7th's reading",
    # Two days named.
    "what did we talk about on october 7th or october 8th",
    # Not a date.
    "what did we say about may",
    "remember the 7 of us went",
    "what happened on february 30th",
])
def test_a_date_that_does_not_date_a_conversation_is_no_day(text):
    assert recall_day_asked(text, today=TODAY) is None


def _class_day(memory, days_ago=40):
    rows = [
        (_at(days_ago, 9, 30), "user", "what is the dh201 schedule for week 4 and what are the readings"),
        (_at(days_ago, 9, 31), "assistant", "Week 4 is Lineages of AI: Wooldridge, Chomsky and Pasquinelli."),
        (_at(days_ago, 10, 5), "user", "we are in front of the class, introduce connectionism and symbolic ai"),
        (_at(days_ago, 10, 6), "assistant", "Good morning everyone. Two families of AI share one history."),
        (_at(days_ago, 11, 0), "user", "i was thinking of using lm studio to run the lab"),
        (_at(days_ago, 11, 1), "assistant", "LM Studio is enough for this level."),
    ]
    # Three later days, so the class is older than <earlier_sessions> shows.
    for later in (20, 12, 5):
        rows.append((_at(later, 9, 0), "user", "just checking in on the course outline today"))
        rows.append((_at(later, 9, 1), "assistant", "The outline is where we left it."))
    _seed(memory, rows)
    return _at(days_ago, 12).date()


def test_the_day_asked_about_is_looked_up(memory, model):
    day = _class_day(memory)
    model.reply = json.dumps({"summary": "Alex asked Blue for the DH201 week 4 "
                              "readings and had Blue introduce the topic to the class.",
                              "topics": ["DH201"]})
    memory.summarize_session(day.isoformat())
    question = f"what happened when we did the dh201 class on {day.strftime('%B')} {day.day}?"

    block = memory._build_asked_day_block(question, robot="blue")

    assert block.startswith(f'<asked_day date="{day.isoformat()}">')
    assert "(40 days ago)" in block
    assert ("The day in short: Alex asked Blue for the DH201 week 4 readings "
            "and had Blue introduce the topic to the class.") in block
    assert "Alex: what is the dh201 schedule for week 4" in block
    assert "Alex: i was thinking of using lm studio to run the lab" in block
    assert "never say the day itself is unrecorded" in block
    # And it reaches the prompt.
    parts = memory.build_context([{"role": "user", "content": question}],
                                 user_name="Alex", robot="blue")
    assert any("<asked_day" in p["content"] for p in parts)


def test_a_long_day_is_shown_from_first_to_last(memory):
    rows = [(_at(40, 8, 0) + timedelta(minutes=i), "user", f"this is point number {i} of the morning")
            for i in range(60)]
    for later in (20, 12, 5):
        rows.append((_at(later, 9, 0), "user", "just checking in on the course outline today"))
    _seed(memory, rows)
    day = _at(40, 12).date()

    block = memory._build_asked_day_block(
        f"what did we talk about on {day.strftime('%B')} {day.day}", robot="blue")

    assert block.count("Alex: this is point number") == memory.ASKED_DAY_LINES
    assert "point number 0 of" in block and "point number 59 of" in block
    # He is told how much of the day he is looking at.
    assert "(10 of the 60 things said, spread over the whole day)" in block


@pytest.mark.parametrize("build_question", [
    # A day he has no rows on: the guard lets "we didn't talk" stand.
    lambda day: "what did we talk about on january 2nd",
    # No day named.
    lambda day: "what did we talk about",
    # A plan for that date, not a memory of it.
    lambda day: f"i have a talk on {day.strftime('%B')} {day.day}",
])
def test_no_asked_day_block_without_a_day_on_record(memory, build_question):
    day = _class_day(memory)
    assert memory._build_asked_day_block(build_question(day), robot="blue") == ""


def test_a_day_already_in_earlier_sessions_is_not_shown_twice(memory):
    _class_day(memory)
    recent = _at(5, 12).date()
    question = f"what did we talk about on {recent.strftime('%B')} {recent.day}"
    assert recent.isoformat() in memory._recent_robot_session_days("blue")
    assert memory._build_asked_day_block(question, robot="blue") == ""


def test_another_robots_day_is_not_this_ones(memory):
    day = _class_day(memory)
    question = f"what did we talk about on {day.strftime('%B')} {day.day}"
    assert memory._build_asked_day_block(question, robot="hexia") == ""
