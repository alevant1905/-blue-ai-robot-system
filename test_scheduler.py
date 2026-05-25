"""Regression tests for the scheduler's date parser.

Run with: python test_scheduler.py   (or under pytest)

These pin the behaviour that caused a real bug: "last Monday at 10am" used to
fall through to dateutil's fuzzy parser, which ignored "last" and fabricated a
future date with the current minute leaked in — so a past meeting fired today.
"""

from datetime import datetime

from blue_tools_enhanced import parse_when

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
    if failures:
        print(f"\n{len(failures)} FAILED")
        for ph, exp, got in failures:
            print(f"  {ph!r}: expected {exp}, got {got}")
        raise SystemExit(1)
    print("\nAll scheduler parser tests passed.")


if __name__ == "__main__":
    run()
