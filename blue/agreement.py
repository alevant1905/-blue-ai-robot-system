"""Detect an agree / disagree stance near the START of a reply, so the robot can
nod (agreement) or shake its head side-to-side (disagreement) as it begins to
speak.

Tuned to fire readily — a plain "Yes,"/"No," opener or a "that makes sense" /
"I don't think so" anywhere in the first few sentences is enough — while still
staying quiet on neutral replies. Following the rule the tool-selector
detectors learned the hard way, disagreement is checked BEFORE agreement (its
phrasings routinely contain "agree"/"right": "I don't agree", "you're not
right"), and negated agreement counts as disagreement.

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
    """The first few sentences (~400 chars), where a reply's stance lives.
    Leading markdown/quote punctuation is stripped so '**Yes**' still opens."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    s = s.lstrip("*_#>~`-–—•\"' \t")
    # Up to the end of the 3rd sentence, capped at 400 chars.
    ends = [m.end() for m in re.finditer(r"[.!?]", s)]
    if len(ends) >= 3:
        return s[: min(ends[2], 400)]
    return s[:400]


# ---- Disagreement (checked first) ------------------------------------------
# Bare "no/nope/nah" opener, minus the polite "no problem / no worries / no
# need" that isn't disagreement.
_SHAKE_OPENER_RE = re.compile(
    r"^(?:no|nope|nah|not really|not quite|not at all|on the contrary|"
    r"absolutely not|definitely not|certainly not|of course not|"
    r"hmm,? no|well,? no|actually,? no)\b",
    re.IGNORECASE,
)
_SHAKE_OPENER_FALSE_FRIEND_RE = re.compile(
    r"^no[,! ]+(?:problem|worries|worry|need|trouble|rush|doubt)\b",
    re.IGNORECASE,
)
_SHAKE_PHRASE_RE = re.compile(
    r"\bi (?:strongly |completely |totally |respectfully |really |have to |must |"
    r"would |'?d )?disagree\b"
    r"|\bi couldn['’]?t disagree more\b"
    r"|\bi (?:really |completely |entirely |quite )?(?:do not|don['’]?t|can['’]?t|"
    r"cannot|couldn['’]?t|wouldn['’]?t) (?:agree|think so|think that)\b"
    r"|\bi don['’]?t think (?:so|that(?:['’]?s| is) (?:right|correct|true))\b"
    r"|\bi(?:['’]?m| am) not (?:so )?sure (?:i agree|about that|that(?:['’]?s| is) "
    r"(?:right|correct|true))\b"
    r"|\bthat(?:['’]?s| is) (?:(?:simply |just |plainly |clearly |really )?not "
    r"(?:right|correct|true|quite right|the case|accurate)|wrong|incorrect|false|"
    r"mistaken|a myth|a misconception|questionable|untrue|off)\b"
    r"|\byou(?:['’]?re| are) (?:not (?:right|correct)|mistaken|wrong)\b"
    r"|\bi beg to differ\b|\bfar from (?:it|true|the truth)\b"
    r"|\bnot (?:necessarily|exactly|entirely) (?:true|right|correct)\b"
    r"|\bi(?:['’]?d| would) (?:have to )?push back\b|\bi(?:['’]?m| am) skeptical\b",
    re.IGNORECASE,
)

# ---- Agreement -------------------------------------------------------------
_NOD_OPENER_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|right|correct|true|sure|indeed|agreed|absolutely|"
    r"definitely|exactly|precisely|of course|certainly|totally|100%|"
    r"couldn['’]?t agree more|well said|good point|fair enough|for sure|"
    r"that(?:['’]?s| is) right|that(?:['’]?s| is) true)\b",
    re.IGNORECASE,
)
_NOD_PHRASE_RE = re.compile(
    r"\bi (?:completely |totally |wholeheartedly |absolutely |fully |strongly |"
    r"really |whole-?heartedly |certainly |'?d |would )?agree\b"
    r"|\bi couldn['’]?t agree more\b"
    r"|\bi (?:think|do think|would say|'?d say) (?:you(?:['’]?re| are)|that(?:['’]?s| is)) "
    r"(?:right|correct|true)\b"
    r"|\byou(?:['’]?re| are) (?:absolutely |completely |so |quite |exactly |"
    r"entirely |certainly )?right\b"
    r"|\bthat(?:['’]?s| is) (?:absolutely |exactly |completely |so |quite |"
    r"very |entirely |certainly )?(?:right|correct|true|spot[- ]on)\b"
    r"|\bspot[- ]on\b|\bwell said\b|\bno doubt about it\b"
    r"|\bwithout (?:a |any )?doubt\b|\bcouldn['’]?t be more true\b"
    r"|\bthat(?:['’]?s| is) (?:a )?(?:great|excellent|fair|valid|good|really good) point\b"
    r"|\bthat makes (?:a lot of )?sense\b|\bmakes sense\b"
    r"|\bfair (?:enough|point)\b|\bexactly right\b|\bcompletely agree\b",
    re.IGNORECASE,
)


def agreement_gesture(text: str) -> Optional[str]:
    """Return 'nod_yes' for an agreement opener, 'shake_no' for a disagreement
    opener, or None. Disagreement wins ties (it often contains 'agree'/'right')."""
    opening = _opening(text)
    if not opening:
        return None
    if (_SHAKE_OPENER_RE.search(opening)
            and not _SHAKE_OPENER_FALSE_FRIEND_RE.search(opening)):
        return SHAKE
    if _SHAKE_PHRASE_RE.search(opening):
        return SHAKE
    if _NOD_OPENER_RE.search(opening) or _NOD_PHRASE_RE.search(opening):
        return NOD
    return None
