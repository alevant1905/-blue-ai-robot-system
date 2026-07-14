"""Regression tests for the agree/disagree -> head-gesture detector.

Run: python test_agreement.py
"""

from blue.agreement import agreement_gesture, NOD, SHAKE

NODS = [
    # strong
    "Yes, absolutely. I completely agree with your point.",
    "Absolutely. That is exactly right.",
    "I completely agree that sovereignty matters here.",
    "You are absolutely right about that.",
    "Exactly! That is a great point.",
    "Agreed. The material infrastructure is what counts.",
    "Definitely. That's spot on.",
    "Alex, I wholeheartedly agree.",
    "**Absolutely** — well said.",
    # milder (sensitivity)
    "Yes, I think that is a good way to look at it.",
    "Right, that makes sense given the local setup.",
    "Sure. That is a fair point about extraction.",
    "I think you are right about the infrastructure.",
    "That makes a lot of sense.",
    "Indeed, the material reality matters here.",
]

SHAKES = [
    # strong
    "No, that is not right. The theft narrative misses the point.",
    "I strongly disagree with that framing.",
    "I have to disagree here.",
    "Absolutely not. That is a misconception.",
    "On the contrary, local hosting changes everything.",
    "I don't agree with that at all.",
    "You are not right about the data flow.",
    "That's simply not true.",
    "I beg to differ.",
    # milder (sensitivity)
    "No, I see it differently.",
    "Not quite. The picture is more complicated.",
    "I do not think so, actually.",
    "Not necessarily true in this case.",
    "I am not sure I agree with that framing.",
    "Hmm, no. That misses something.",
]

NEITHER = [
    "That is an interesting question. Let me think about it.",
    "I am not sure exactly what you mean by that.",
    "The weather today is mild and cloudy.",
    "Here is what I found in your documents.",
    "Maybe, but there are a few things to consider first.",
    "I can help you with that. What would you like to know?",
    "It depends on how you define extraction.",
    "There are good arguments on both sides of this.",
    # polite false friends must NOT shake
    "No problem, I can help with that.",
    "No worries at all.",
    "No need to apologize.",
    "",
]


def main():
    failures = []
    for t in NODS:
        if agreement_gesture(t) != NOD:
            failures.append(("expected nod", t, agreement_gesture(t)))
    for t in SHAKES:
        if agreement_gesture(t) != SHAKE:
            failures.append(("expected shake", t, agreement_gesture(t)))
    for t in NEITHER:
        if agreement_gesture(t) is not None:
            failures.append(("expected none", t, agreement_gesture(t)))

    for label, t, got in failures:
        print(f"[FAIL] {label}: got {got!r} <- {t[:55]}")
    total = len(NODS) + len(SHAKES) + len(NEITHER)
    if failures:
        print(f"\n{len(failures)}/{total} FAILED")
        raise SystemExit(1)
    print(f"All {total} cases passed.")


if __name__ == "__main__":
    main()
