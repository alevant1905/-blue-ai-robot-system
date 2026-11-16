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


def test_a_day_shared_with_another_robot_gets_no_recap(memory, model):
    """One row a date for every robot: Hexia took Blue's day for hers."""
    _seed(memory, LAB_DAY + [
        (_at(3, 16, 0), "user", "tell me a story about a dragon", "hexia", "Vilda"),
        (_at(3, 16, 1), "assistant", "Once there was a dragon.", "hexia", "Vilda"),
    ])
    memory.summarize_session(_day(3))

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
