"""<connections> and <daily_rhythms> state facts; they don't prompt offers.

Run with: python -m pytest test_connections_offers.py

From the 2026-09-25 harness runs. The <connections> line "... there's a
document on file that looks related — "DH399_AL_2026F.docx". You could offer
to pull it up or summarise it beforehand" was in every main call of both
runs, "i had a rough day" and "tell me a joke" among them: the weekly class
is always a day or two away. Blue offered the syllabus in 7 of 114 replies,
and replays of home_checkin[0] said "I've got the DH399 syllabus pulled up"
in 2 of 3 samples when nothing had been opened. At 08:37 CS101, running since
08:30, was "coming up (today)".

No bluetools import: the memory system runs on a temporary database.
"""

from datetime import datetime, timedelta

import pytest

import blue_memory_improved as bmi


SYLLABUS = "DH399_AL_2026F.docx"


@pytest.fixture
def memory(tmp_path, monkeypatch):
    mem = bmi.EnhancedMemorySystem(db_path=str(tmp_path / "memory.db"))
    monkeypatch.setattr(mem, "_library_documents",
                        lambda: [SYLLABUS, "CS101_syllabus.docx",
                                 "Toscano_Automation_2023.pdf"])
    return mem


def _schedule(monkeypatch, *events):
    import blue_tools_enhanced as bte
    monkeypatch.setattr(bte, "occurrences_in_window", lambda *a, **k: list(events))


def _event(title, start, minutes=80, recurring=False):
    return {"title": title, "start": start,
            "end": start + timedelta(minutes=minutes), "recurring": recurring}


NOW = datetime.now().replace(second=0, microsecond=0)
DH399_LATER = _event("DH399: AI and Society (Seminar)", NOW + timedelta(hours=2),
                     recurring=True)
CS101_RUNNING = _event("CS101-A: Intro (Lecture)", NOW - timedelta(minutes=7),
                       minutes=110, recurring=True)


def _connections(memory, message):
    return memory.find_connections(NOW, current_user_msg=message)


def test_a_weekly_class_does_not_ride_along_on_every_turn(memory, monkeypatch):
    _schedule(monkeypatch, CS101_RUNNING, DH399_LATER)
    for message in ("i had a rough day", "tell me a joke"):
        assert not any(SYLLABUS in c for c in _connections(memory, message))


@pytest.mark.parametrize("message", [
    "what are we doing in dh 399", "what are we doing in DH399 today?",
    "anything to prep for dh-399?",
])
def test_naming_the_course_links_its_document(memory, monkeypatch, message):
    _schedule(monkeypatch, CS101_RUNNING, DH399_LATER)
    line = next(c for c in _connections(memory, message) if SYLLABUS in c)
    assert "you have NOT opened it" in line
    assert "offer" not in line and "pull it up" not in line


def test_a_class_in_progress_is_never_coming_up(memory, monkeypatch):
    _schedule(monkeypatch, CS101_RUNNING, DH399_LATER)
    for message in ("what are we doing in cs101", "i had a rough day"):
        for line in _connections(memory, message):
            assert not ("CS101-A" in line and "coming up" in line), line


def test_a_one_off_event_still_links_its_document(memory, monkeypatch):
    _schedule(monkeypatch, _event("Toscano reading group", NOW + timedelta(days=1)))
    lines = _connections(memory, "i had a rough day")
    assert any("Toscano_Automation_2023.pdf" in c and "coming up" in c
               for c in lines)


def test_an_event_under_way_is_on_now_in_the_stress_line(memory, monkeypatch):
    _schedule(monkeypatch, _event("Grant proposal review", NOW - timedelta(minutes=10)))
    lines = _connections(memory, "i'm so stressed about the grant proposal")
    line = next(c for c in lines if "Grant proposal review" in c)
    assert "on now" in line and "coming up" not in line


def test_the_offer_header_needs_a_line_that_offers(memory, monkeypatch):
    _schedule(monkeypatch, DH399_LATER,
              _event("Grant proposal review", NOW + timedelta(days=1)))
    calm = memory._build_connections_block(NOW, user_msg="what's on in dh399?")
    assert SYLLABUS in calm
    assert "gentle action" not in calm

    stressed = memory._build_connections_block(
        NOW, user_msg="i'm so stressed about the grant proposal")
    assert memory._UNWIND_OFFER in stressed
    assert "gentle action you could offer" in stressed


def test_the_rhythms_are_context_not_a_cue_to_offer(memory):
    part = memory._part_of_day(NOW.hour)
    with memory._conn() as c:
        c.execute(
            "INSERT INTO routines (category, part_of_day, observations, "
            "distinct_days, confidence, updated_at) VALUES (?, ?, 5, 3, 0.8, ?)",
            ("music", part, NOW.isoformat()))
    block = memory._build_rhythms_block(NOW)
    assert "putting on music" in block
    assert "gently offer" not in block
    assert "never as a reason to offer something" in block
