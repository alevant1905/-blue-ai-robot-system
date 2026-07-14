"""Map the sentiment of Blue's spoken reply to an eye-LED colour.

Blue's Ohbot eyes are RGB LEDs (see blue/head.py eye_color, 0-10 per channel;
the G/R swap is handled in the driver, so here we speak plain R,G,B). When Blue
talks, the chat page tints his eyes to match the mood of what he's saying —
red when something warrants it, a warm cheer when he's pleased, blue when
he's somber, and so on — reverting to a calm rest colour when he stops.

Design rules learned the hard way elsewhere in this codebase (see the
tool-selector detectors): match WHOLE WORDS, never substrings ("mad" must not
fire on "made"), and check for negation ("not angry", "no danger") before
counting a hit. The function is pure and deterministic so it can be unit
tested without importing the server.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Each mood: an eye colour on the 0-10 LED scale plus the cue words/emoji that
# vote for it. Order matters only for tie-breaking (earlier = higher priority),
# so the strong signals Alex asked about — anger/warning → red — win ties.
# (name, (r, g, b), keywords, emoji)
_MOODS: List[Tuple[str, Tuple[int, int, int], Tuple[str, ...], Tuple[str, ...]]] = [
    ("alert", (10, 0, 0), (
        "angry", "anger", "furious", "fury", "rage", "enraged", "mad",
        "outraged", "outrage", "livid", "appalling", "appalled",
        "danger", "dangerous", "warning", "warn", "urgent", "emergency",
        "alarm", "alarming", "threat", "threatening", "unacceptable",
        "forbidden", "hazard", "hazardous", "beware", "careful", "caution",
        "critical", "severe", "stop",
    ), ("😠", "😡", "🤬", "⚠", "🚨", "🛑")),
    ("somber", (0, 2, 10), (
        "sad", "sadly", "sorrow", "sorrowful", "grief", "grieving", "mourn",
        "mourning", "lonely", "loneliness", "heartbroken", "heartbreaking",
        "tragic", "tragedy", "unfortunate", "unfortunately", "regret",
        "regretful", "disappointed", "disappointing", "gloomy", "somber",
        "sombre", "despair", "miserable", "sorry", "apologize", "apologise",
        "apologies", "condolences", "hurts", "painful",
    ), ("😢", "😞", "😔", "😟", "💙", "🥺", "😥")),
    ("affection", (8, 0, 9), (
        "love", "loved", "lovely", "adore", "adored", "cherish", "cherished",
        "beloved", "affection", "affectionate", "fond", "dear", "sweetheart",
        "darling", "care", "caring", "tender", "warmth", "grateful",
        "gratitude", "thankful",
    ), ("❤", "💜", "💖", "💕", "🥰", "😍", "🤗")),
    ("cheerful", (9, 7, 0), (
        "happy", "glad", "delighted", "delight", "excited", "exciting",
        "thrilled", "joy", "joyful", "joyous", "yay", "hooray", "hurray",
        "wonderful", "fantastic", "amazing", "awesome", "great", "brilliant",
        "excellent", "celebrate", "celebration", "congratulations", "congrats",
        "cheer", "cheerful", "fun", "delightful", "wow",
    ), ("😀", "😃", "😄", "😁", "😊", "🎉", "✨", "🥳", "🙌", "🌟")),
    ("curious", (0, 7, 9), (
        "curious", "curiosity", "wonder", "wondering", "intrigued",
        "intriguing", "interesting", "fascinating", "fascinated", "hmm",
        "puzzling", "puzzled", "mysterious", "mystery", "explore", "discover",
        "imagine", "ponder", "consider",
    ), ("🤔", "🧐", "❓", "🔍")),
    ("positive", (0, 9, 2), (
        "absolutely", "certainly", "definitely", "gladly", "sure", "success",
        "successful", "succeeded", "done", "ready", "perfect", "fixed",
        "solved", "works", "working", "confirmed", "agreed", "reassured",
        "reassuring", "welcome", "no problem", "of course", "all set",
        "you got it", "happy to", "glad to",
    ), ("👍", "✅", "👌", "💚")),
]

# Calm rest colour when nothing stands out — a soft cool white. The browser
# also reverts to a rest colour when Blue stops talking.
_NEUTRAL = ("neutral", (5, 5, 6))

# Negators immediately before a cue word flip its meaning ("not angry", "no
# danger", "isn't sad"). Small window, mirroring the detectors' approach.
_NEGATORS = (
    "not", "no", "never", "without", "isnt", "isn't", "arent", "aren't",
    "dont", "don't", "cant", "can't", "wont", "won't", "nothing", "hardly",
    "barely", "neither", "nor",
)

_WORD_RE = re.compile(r"[a-z']+")


def _negated(tokens: List[str], idx: int) -> bool:
    """True if a negator sits within the two tokens before position idx."""
    for j in (idx - 1, idx - 2):
        if 0 <= j < len(tokens) and tokens[j] in _NEGATORS:
            return True
    return False


def mood_eye_color(text: str) -> Dict[str, object]:
    """Return {'r','g','b','name'} eye-LED colour (0-10) for the reply's mood.

    Scores each mood by whole-word keyword hits (negated hits don't count) plus
    emoji, and returns the winner; ties break toward the earliest/strongest
    mood in _MOODS. An exclamation mark nudges the expressive moods, a lone
    question mark nudges curiosity. Falls back to the calm neutral rest colour.
    """
    text = text or ""
    low = text.lower()
    tokens = _WORD_RE.findall(low)
    positions: Dict[str, List[int]] = {}
    for i, tok in enumerate(tokens):
        positions.setdefault(tok, []).append(i)

    scores: Dict[str, float] = {}
    for name, _rgb, keywords, emoji in _MOODS:
        s = 0.0
        for kw in keywords:
            if " " in kw:
                # Multi-word cue: count occurrences, ignore negation (rare).
                if kw in low:
                    s += low.count(kw)
                continue
            for idx in positions.get(kw, ()):  # whole-word only
                if not _negated(tokens, idx):
                    s += 1.0
        for em in emoji:
            if em in text:
                s += 1.5  # emoji are a deliberate, strong mood signal
        if s:
            scores[name] = s

    # Punctuation nudges — only enough to break a near-tie, never to invent a
    # mood from nothing.
    if scores:
        if "!" in text:
            for n in ("cheerful", "alert", "affection"):
                if n in scores:
                    scores[n] += 0.4
        if "?" in text and "curious" in scores:
            scores["curious"] += 0.4

    if not scores:
        name, (r, g, b) = _NEUTRAL
        return {"r": r, "g": g, "b": b, "name": name}

    # Highest score wins; ties resolved by _MOODS order (priority).
    order = {name: i for i, (name, *_rest) in enumerate(_MOODS)}
    best = max(scores, key=lambda n: (scores[n], -order[n]))
    rgb = next(rgb for name, rgb, *_ in _MOODS if name == best)
    return {"r": rgb[0], "g": rgb[1], "b": rgb[2], "name": best}


def rest_eye_color() -> Dict[str, object]:
    """The calm colour Blue's eyes return to when he stops talking."""
    name, (r, g, b) = _NEUTRAL
    return {"r": r, "g": g, "b": b, "name": name}
