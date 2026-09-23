"""Reminder alerts are worded when delivered, and dropped when stale.

Run with: python -m pytest test_proactive_alerts.py

Alerts wait for the next chat turn. "Heads up, Alex — 'DH201…' is starting
now." was worded at 10:00 and delivered at 13:13, after the 12:50 end, glued
in front of "Yes, I can hear you perfectly" (2026-09-23). Of 10 "is starting
now" deliveries in the ledger, 8 went out 42-285 minutes late.
"""

from datetime import datetime

import pytest

import blue_proactive as bp


@pytest.fixture(autouse=True)
def empty_queue(monkeypatch):
    monkeypatch.setattr(bp, "QUEUE", bp.ProactiveQueue())


def occ(start, end=None, title="DH201: Introduction to Generative AI (Lecture)"):
    return {"start": start, "end": end, "title": title, "user_name": "Alex"}


def queue(o, key="k"):
    bp.QUEUE.push(bp._voice_phrase(o, o["start"]), key, o)


def test_an_alert_after_its_class_ended_is_dropped():
    queue(occ(datetime(2026, 9, 23, 10, 0), datetime(2026, 9, 23, 12, 50)))
    assert bp.drain_for_response(now=datetime(2026, 9, 23, 13, 13)) == ""


@pytest.mark.parametrize("hour,minute,expected", [
    (11, 58, "'Meeting with Dean' in 2 minutes."),
    (12, 1, "'Meeting with Dean' is starting now."),
    (12, 5, "'Meeting with Dean' started at 12:00 PM."),
    (12, 11, ""),
])
def test_an_alert_is_worded_for_the_moment_it_is_delivered(hour, minute, expected):
    queue(occ(datetime(2026, 9, 23, 12, 0), title="Meeting with Dean"))
    out = bp.drain_for_response(now=datetime(2026, 9, 23, hour, minute))
    assert out.endswith(expected) if expected else out == ""


def test_an_alert_the_briefing_already_lists_is_not_stacked_on_it():
    queue(occ(datetime(2026, 9, 18, 8, 30), datetime(2026, 9, 18, 10, 20),
              title="CS101-A: Canadian Communication in Context (Lecture)"))
    briefing = ("Here's your day — 2 things on the calendar: CS101-A: Canadian "
                "Communication in Context (Lecture) from 8:30 AM to 10:20 AM.")
    assert bp.drain_for_response(now=datetime(2026, 9, 18, 8, 31),
                                 skip_text=briefing) == ""


def test_an_alert_without_an_occurrence_is_delivered_as_is():
    bp.QUEUE.push("Heads up, Alex — check the oven.", "plain")
    assert bp.drain_for_response() == "Heads up, Alex — check the oven."


def test_the_replay_guard_honours_its_switches():
    from blue.server import reply_guards as rg

    def ctx(**over):
        base = dict(reply="A long enough reply that was already said before today.",
                    response={"choices": [{"message": {"content": "x"}}]},
                    messages=[], robot="blue", user_name="Alex", last_user_msg="hi",
                    regen_once=lambda note, max_tokens=700: "Something new instead.",
                    norm_final="a long enough reply that was already said before today",
                    norm_recents=set(), parrot_norm=lambda t: t.lower().strip("."))
        base.update(over)
        return rg.ReplyContext(**base)

    assert rg.guard_verbatim_replay(ctx()) is None
    replayed = lambda t: t.startswith("A long enough reply")
    assert rg.guard_verbatim_replay(
        ctx(opening_replay=replayed)) == "Something new instead."
    for switch in ({"repeat_requested": True}, {"templated": True}):
        assert rg.guard_verbatim_replay(
            ctx(opening_replay=replayed, **switch)) is None
