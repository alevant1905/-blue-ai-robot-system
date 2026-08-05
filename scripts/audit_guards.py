"""Survey the output guards against every reply Blue has actually given.

The guards are patterns, and patterns are written for the phrasing someone
imagined. This runs them over `conversation_log` instead and prints what got
through — which is how the clock denials, the "no record of a Felix" gap and
the "contents of files" gap were found.

    python scripts/audit_guards.py            # summary + uncaught sample
    python scripts/audit_guards.py --all      # every uncaught denial

Anything it surfaces that is genuinely WRONG belongs in
test_guards_against_recorded_replies.py as a case, with the guard widened
until it passes. Anything it surfaces that is HONEST ("I don't see it in the
syllabus") belongs in that file's LEGITIMATE list, so a later widening cannot
start flagging it.

Reads the live database; prints to the terminal only. Nothing is written.
"""

from __future__ import annotations

import collections
import pathlib
import re
import sqlite3
import sys

# Run from anywhere: scripts/ is not on the path by default.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bluetools as bt
from blue.server import turn_completion as tc
from blue_identity import is_recorded_recall_denial

DB = "data/enhanced_memory.db"

# First-person negative constructions — how a refusal actually opens.
DENIAL = re.compile(
    r"\bi (?:do ?n[o']?t|don't|cannot|can't|couldn't|could not|haven't|"
    r"have not|am not able|do not)\b[^.!?]{0,90}", re.I)


def guards():
    return {
        "family": lambda t: (tc._family_refusal_re.search(t)
                             or tc.denies_a_known_person(t)),
        "flat_denial": lambda t: tc._flat_denial_re.search(t),
        "voice": lambda t: bt._VOICE_DENIAL_RE.search(t),
        "clock": lambda t: bt._CLOCK_DENIAL_RE.search(t),
        "temporal": lambda t: bt._TEMPORAL_DENIAL_RE.search(t),
        "document": lambda t: bt._DOCUMENT_REFUSAL_RE.search(t),
        "web": lambda t: bt._WEB_REFUSAL_RE.search(t),
        "calendar": lambda t: bt._CALENDAR_DENIAL_RE.search(t),
        "robot_chat": lambda t: bt._ROBOT_CHAT_DENIAL_RE.search(t),
        "robot_relation": lambda t: bt._ROBOT_RELATIONSHIP_DENIAL_RE.search(t),
        "recall": lambda t: is_recorded_recall_denial(t),
        "inbound_refusal": lambda t: any(
            m in t.lower().replace("’", "'")
            for m in bt._ASSISTANT_REFUSAL_MARKERS),
    }


def main() -> int:
    show_all = "--all" in sys.argv
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    replies = [r["content"] or "" for r in conn.execute(
        "select content from conversation_log where role='assistant'")]

    checks = guards()
    verdicts, uncaught = {}, collections.Counter()
    by_guard = collections.Counter()
    for reply in replies:
        for match in DENIAL.finditer(reply[:600]):
            phrase = re.sub(r"\s+", " ", match.group(0).strip())
            key = phrase.lower()
            if key in verdicts:
                continue
            fired = [name for name, fn in checks.items() if fn(phrase)]
            verdicts[key] = fired
            by_guard.update(fired)
            if not fired:
                uncaught[phrase] += 1

    caught = sum(1 for v in verdicts.values() if v)
    total = len(verdicts)
    print(f"replies on record          : {len(replies)}")
    print(f"distinct denial phrasings  : {total}")
    print(f"claimed by some guard      : {caught} ({caught / max(total,1):.0%})")
    print(f"uncaught                   : {total - caught}\n")
    print("which guard claimed them:")
    for name, n in by_guard.most_common():
        print(f"   {name:18s} {n:5d}")

    # A denial mentioning something Blue demonstrably has is the interesting
    # kind; the rest is mostly honest "I can't predict the future".
    SUSPECT = re.compile(
        r"memor|record|stor|remember|ages?|famil|email|calendar|camera|"
        r"music|document|pdf|library|clock|time|date|contact", re.I)
    interesting = [p for p in uncaught if SUSPECT.search(p)]
    print(f"\nuncaught and worth reading ({len(interesting)}):")
    for phrase in (interesting if show_all else interesting[:30]):
        print(f"   {phrase[:100]}")
    if not show_all and len(interesting) > 30:
        print(f"   ... {len(interesting) - 30} more (--all)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
