"""Detect a strong agree / disagree stance at the START of a reply, so the robot
can nod (agreement) or shake its head side-to-side (disagreement) as it begins
to speak.

Only STRONG, clear stances fire — mild or neutral openings produce no gesture —
and, following the rule the tool-selector detectors learned the hard way,
disagreement is checked BEFORE agreement (its phrasings routinely contain the
word "agree"/"right": "I don't agree", "you're not right"), and negated
agreement counts as disagreement.

Pure and deterministic so it can be unit tested without importing the server.
"""

from __future__ import annotations

import re
from typing import Optional

# Return values are the exact head-action names the head route + Web Serial
# driver already accept.
NOD = "nod_yes"
SHAKE = "shake_no"


def _opening(text: str) -> str:
    """The first ~240 characters, where an opening stance lives. Leading
    markdown/quote punctuation is stripped so '**Absolutely**' still reads as an
    opener."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    s = s.lstrip("*_#>~`-–—•\"' \t")
    return s[:240]


# ---- Disagreement (checked first) ------------------------------------------
_SHAKE_OPENER_RE = re.compile(
    r"^(?:no[,!. ]+|nope[,!. ]+|absolutely not|definitely not|certainly not|"
    r"of course not|not at all|not really|not quite|on the contrary)\b",
    re.IGNORECASE,
)
_SHAKE_PHRASE_RE = re.compile(
    r"\bi (?:strongly |completely |totally |respectfully |really |have to |must )?"
    r"disagree\b"
    r"|\bi couldn['’]?t disagree more\b"
    r"|\bi (?:really |completely |entirely )?(?:do not|don['’]?t|can['’]?t|cannot|"
    r"couldn['’]?t) agree\b"
    r"|\bi don['’]?t think (?:so|that(?:['’]?s| is) (?:right|correct|true))\b"
    r"|\bthat(?:['’]?s| is) (?:not (?:right|correct|true|quite right|the case)|"
    r"wrong|incorrect|false|mistaken|a myth|a misconception)\b"
    r"|\byou(?:['’]?re| are) (?:not (?:right|correct)|mistaken|wrong)\b"
    r"|\bi beg to differ\b|\bfar from (?:it|true|the truth)\b"
    r"|\bthat(?:['’]?s| is) (?:simply |just |plainly )?(?:not|untrue)\b",
    re.IGNORECASE,
)

# ---- Agreement -------------------------------------------------------------
_NOD_OPENER_RE = re.compile(
    r"^(?:yes[,!. ]+)?(?:absolutely|definitely|exactly|precisely|of course|"
    r"certainly|agreed|indeed|for sure|totally|100%|couldn['’]?t agree more)\b",
    re.IGNORECASE,
)
_NOD_PHRASE_RE = re.compile(
    r"\bi (?:completely |totally |wholeheartedly |absolutely |fully |strongly |"
    r"really |whole-?heartedly )?agree\b"
    r"|\bi couldn['’]?t agree more\b"
    r"|\byou(?:['’]?re| are) (?:absolutely |completely |so |quite |exactly |"
    r"entirely )?right\b"
    r"|\bthat(?:['’]?s| is) (?:absolutely |exactly |completely |so |quite |"
    r"very |entirely )?(?:right|correct|true|spot[- ]on)\b"
    r"|\bspot[- ]on\b|\bwell said\b|\bno doubt about it\b"
    r"|\bwithout (?:a |any )?doubt\b|\bcouldn['’]?t be more true\b"
    r"|\bthat(?:['’]?s| is) a (?:great|excellent|fair|valid|good) point\b",
    re.IGNORECASE,
)


def agreement_gesture(text: str) -> Optional[str]:
    """Return 'nod_yes' for a strong agreement opener, 'shake_no' for a strong
    disagreement opener, or None. Disagreement wins ties (it often contains
    'agree'/'right')."""
    opening = _opening(text)
    if not opening:
        return None
    if _SHAKE_OPENER_RE.search(opening) or _SHAKE_PHRASE_RE.search(opening):
        return SHAKE
    if _NOD_OPENER_RE.search(opening) or _NOD_PHRASE_RE.search(opening):
        return NOD
    return None
