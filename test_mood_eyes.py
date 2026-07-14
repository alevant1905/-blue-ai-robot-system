"""Regression tests for the reply-sentiment -> eye-LED colour mapper.

Run: python test_mood_eyes.py
Covers the flagship case Alex asked about (anger/warning -> red), each mood,
and the two failure modes this codebase keeps relearning: substring matches
("made" != "mad", "stopped" != "stop") and un-negated hits ("not angry").
"""

from blue.mood_eyes import mood_eye_color, rest_eye_color

RED = (10, 0, 0)
NEUTRAL = (5, 5, 6)


def _rgb(text):
    c = mood_eye_color(text)
    return (c["r"], c["g"], c["b"]), c["name"]


CASES = [
    # (reply text, expected mood name)
    ("Please be careful, that is dangerous and you could get hurt.", "alert"),
    ("I am absolutely furious. This is unacceptable.", "alert"),
    ("Warning: that is a serious hazard.", "alert"),
    ("That is wonderful news! I am so happy for you.", "cheerful"),
    ("I am sorry, that is really unfortunate.", "somber"),
    ("I love you, Alex. You mean so much to me.", "affection"),
    ("Hmm, what a fascinating question. I wonder why.", "curious"),
    ("Sure, done! I fixed it and everything works now.", "positive"),
    ("The meeting is scheduled for 3pm on Wednesday.", "neutral"),
    # Negation must not trigger the emotional mood.
    ("I am not angry at all, everything is fine.", "neutral"),
    ("There is no danger here.", "neutral"),
    # Substrings must not trigger (whole-word matching).
    ("I made a cake yesterday and stopped by the store.", "neutral"),
]


def main():
    failures = []
    for text, expected in CASES:
        (rgb, name) = _rgb(text)
        ok = name == expected
        if not ok:
            failures.append((text, expected, name))
        print(f"[{'ok ' if ok else 'FAIL'}] {name:9} (exp {expected:9}) <- {text[:50]}")

    # The headline promise: anger/warning lights the eyes red.
    assert _rgb("Careful, that is dangerous!")[0] == RED, "warning should be red"
    assert _rgb("I am furious about this.")[0] == RED, "anger should be red"
    # Empty / whitespace falls back to neutral, never crashes.
    assert mood_eye_color("")["name"] == "neutral"
    assert mood_eye_color(None)["name"] == "neutral"
    # Every channel stays within the LED's 0-10 range.
    for text, _ in CASES:
        c = mood_eye_color(text)
        assert all(0 <= c[ch] <= 10 for ch in ("r", "g", "b")), text
    r = rest_eye_color()
    assert set(r) == {"r", "g", "b", "name"}

    if failures:
        print(f"\n{len(failures)} FAILED")
        raise SystemExit(1)
    print(f"\nAll {len(CASES)} cases passed.")


if __name__ == "__main__":
    main()
