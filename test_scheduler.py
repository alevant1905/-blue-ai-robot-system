"""Regression tests for the scheduler's date parser.

Run with: python test_scheduler.py   (or under pytest)

These pin the behaviour that caused a real bug: "last Monday at 10am" used to
fall through to dateutil's fuzzy parser, which ignored "last" and fabricated a
future date with the current minute leaked in — so a past meeting fired today.
"""

from datetime import datetime

import pytest

from blue_tools_enhanced import (
    parse_when, parse_recurrence_phrase, parse_lead_minutes,
    recurrence_label, _expand_row,
)

# A fixed reference instant so every case is deterministic: Monday 2026-05-25.
NOW = datetime(2026, 5, 25, 13, 0)

EXPECTED = {
    # Past-relative weekdays resolve BACKWARD, never forward.
    "last monday at 10am": "2026-05-18T10:00",
    "last friday at 9am": "2026-05-22T09:00",
    "previous thursday at 8am": "2026-05-21T08:00",
    # Forward weekdays.
    "next monday at 10am": "2026-06-01T10:00",
    "monday at 10am": "2026-06-01T10:00",        # bare = next future occurrence
    "on tuesday at 2pm": "2026-05-26T14:00",
    "this coming friday at 5pm": "2026-05-29T17:00",
    # "this <weekday>" = the weekday within the current Mon–Sun week.
    "this wednesday at 9am": "2026-05-27T09:00",
    # Relative days.
    "tomorrow at 8am": "2026-05-26T08:00",
    "yesterday at 3pm": "2026-05-24T15:00",
    "today at 4pm": "2026-05-25T16:00",
    "in 30 minutes": "2026-05-25T13:30",
    "in 2 hours": "2026-05-25T15:00",
    # Explicit date via the dateutil fallback: no minute-leak from NOW (:00 not :13).
    "May 18 at 10am": "2026-05-18T10:00",
}

# Phrases carrying an unresolved past cue must RAISE, not silently guess.
MUST_REFUSE = ["last week sometime", "3 days ago", "a while ago"]


# --- Recurrence phrase parsing ---
RECUR = {
    "every day": "daily", "every other day": "daily:2", "daily": "daily",
    "every week": "weekly", "every 2 weeks": "weekly:2",
    "every other week": "weekly:2", "every weekday": "weekdays",
    "weekends": "weekends", "every monday and wednesday and friday": "dow:0,2,4",
    "mon/wed/fri": "dow:0,2,4", "every monday": "dow:0", "monthly": "monthly",
    "every 3 months": "monthly:3", "yearly": "yearly", "annually": "yearly",
    "once": None, "": None,
}

# --- Lead-time parsing (minutes) ---
LEADS = {
    "30 minutes before": 30, "2 hours before": 120, "1 day before": 1440,
    "a day before": 1440, "the day before": 1440, "1 week before": 10080,
    "an hour before": 60, "15": 15, "": 0, "at start": 0,
}


def _row(when, rec="", end=None, until=None):
    return {"id": 1, "user_name": "Alex", "title": "X", "description": "",
            "when_iso": when, "end_iso": end, "recurrence": rec,
            "remind_before_min": 0, "until_iso": until}


def _starts(occs):
    return [o["start"].strftime("%Y-%m-%d %H:%M") for o in occs]


# Expansion expectations: (row, window_start, window_end) -> list of starts
EXPAND = [
    (_row("2026-05-01T09:00", "daily"), datetime(2026, 5, 10), datetime(2026, 5, 12, 23, 59),
     ["2026-05-10 09:00", "2026-05-11 09:00", "2026-05-12 09:00"]),
    (_row("2026-05-04T09:00", "weekly:2"), datetime(2026, 5, 1), datetime(2026, 6, 15, 23, 59),
     ["2026-05-04 09:00", "2026-05-18 09:00", "2026-06-01 09:00", "2026-06-15 09:00"]),
    (_row("2026-05-04T08:00", "dow:0,2,4"), datetime(2026, 5, 4), datetime(2026, 5, 10, 23, 59),
     ["2026-05-04 08:00", "2026-05-06 08:00", "2026-05-08 08:00"]),
    (_row("2026-01-15T12:00", "monthly"), datetime(2026, 5, 1), datetime(2026, 7, 31, 23, 59),
     ["2026-05-15 12:00", "2026-06-15 12:00", "2026-07-15 12:00"]),
    (_row("2026-05-04T09:00", "weekly", until="2026-05-31T23:59"), datetime(2026, 5, 1), datetime(2026, 7, 1),
     ["2026-05-04 09:00", "2026-05-11 09:00", "2026-05-18 09:00", "2026-05-25 09:00"]),
    (_row("2026-05-20T10:00", ""), datetime(2026, 6, 1), datetime(2026, 6, 30), []),
]


def test_parse_when_expected():
    for phrase, expected in EXPECTED.items():
        assert parse_when(phrase, NOW).isoformat(timespec="minutes") == expected


def test_parse_when_refuses_unresolved_past():
    for phrase in MUST_REFUSE:
        with pytest.raises(ValueError):
            parse_when(phrase, NOW)


def test_parse_recurrence_phrases():
    for phrase, expected in RECUR.items():
        assert parse_recurrence_phrase(phrase) == expected


def test_parse_lead_minutes():
    for phrase, expected in LEADS.items():
        assert parse_lead_minutes(phrase) == expected


def test_expand_rows():
    for row, ws, we, expected in EXPAND:
        assert _starts(_expand_row(row, ws, we)) == expected


def run():
    failures = []
    for phrase, expected in EXPECTED.items():
        got = parse_when(phrase, NOW).isoformat(timespec="minutes")
        status = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append((phrase, expected, got))
        print(f"{status} {phrase!r:32} -> {got}")
    for phrase in MUST_REFUSE:
        try:
            parse_when(phrase, NOW)
            failures.append((phrase, "ValueError", "no error"))
            print(f"FAIL {phrase!r:32} -> expected refusal")
        except ValueError:
            print(f"OK   {phrase!r:32} -> refused")
    for phrase, expected in RECUR.items():
        got = parse_recurrence_phrase(phrase)
        status = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append((phrase, expected, got))
        print(f"{status} recur {phrase!r:30} -> {got}")
    for phrase, expected in LEADS.items():
        got = parse_lead_minutes(phrase)
        status = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append((phrase, expected, got))
        print(f"{status} lead  {phrase!r:30} -> {got}")
    for row, ws, we, expected in EXPAND:
        got = _starts(_expand_row(row, ws, we))
        status = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append((row["recurrence"] or "one-off", expected, got))
        print(f"{status} expand {(row['recurrence'] or 'one-off'):12} -> {len(got)} occ")
    if failures:
        print(f"\n{len(failures)} FAILED")
        for ph, exp, got in failures:
            print(f"  {ph!r}: expected {exp}, got {got}")
        raise SystemExit(1)
    print("\nAll scheduler parser tests passed.")


if __name__ == "__main__":
    run()
