"""Cut a reply that has started looping.

The chat call ran with no token limit, and on 2026-09-23 a reply about a TA
named Clover came back at 99,666 characters: one real answer, then "One more
thing..." / "Also..." / "And since we're on the topic..." paragraphs repeated
verbatim until the model gave up. That text was logged, spoken and replayed as
history on later turns.

The token cap in bluetools._lm_studio_payload bounds the damage; this trims
what the cap lets through. A degenerate loop repeats itself word for word, so
the cut is made at the first sentence the reply has already said. A reply cut
off by the cap is also pulled back to its last complete sentence.

Pure text in, text out — no bluetools import, so it can be tested without
starting the server's background threads.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# A sentence ends at punctuation FOLLOWED BY WHITESPACE, so the dots in
# file names, URLs and "Blue_update_2510.pdf" citations don't split it.
_SENTENCE_RE = re.compile(r".+?(?:[.!?]+[\"'”’)\]]*(?=\s|$)|\n|$)", re.S)
_FENCE_RE = re.compile(r"```.*?(?:```|$)", re.S)
# Shorter sentences ("Got it.", "Let me know!") legitimately recur.
_MIN_REPEAT_CHARS = 25
# A loop repeats a long run of text. A song's chorus, a citation used twice
# or two reminder alerts repeat less than this, and are left alone — measured
# over 4,933 logged replies, all 16 single-sentence repeats were legitimate.
_MIN_RUN_CHARS = 300
_SENTENCE_END_RE = re.compile(r"[.!?][\"'”’)\]]*(?=\s|$)")


def _norm(sentence: str) -> str:
    text = re.sub(r"[*_`#>\-]+", " ", sentence.lower())
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _fenced_spans(text: str) -> List[Tuple[int, int]]:
    return [m.span() for m in _FENCE_RE.finditer(text)]


def cut_repeats(text: str) -> str:
    """Return `text` up to the start of the first long repeated run."""
    fences = _fenced_spans(text)
    seen = set()
    run_start, run_chars = None, 0
    for match in _SENTENCE_RE.finditer(text):
        start = match.start()
        # Code legitimately repeats lines; leave fenced blocks alone.
        if any(a <= start < b for a, b in fences):
            continue
        key = _norm(match.group())
        if len(key) < _MIN_REPEAT_CHARS:
            continue  # short lines neither start nor break a run
        if key in seen:
            if run_start is None:
                run_start = start
            run_chars += len(key)
            if run_chars >= _MIN_RUN_CHARS:
                return text[:run_start].rstrip()
        else:
            run_start, run_chars = None, 0
            seen.add(key)
    return text


def to_last_sentence(text: str) -> str:
    """Drop a trailing fragment left by the token cap."""
    stripped = text.rstrip()
    if not stripped or _SENTENCE_END_RE.search(stripped[-3:] + " "):
        return stripped
    ends = list(_SENTENCE_END_RE.finditer(stripped))
    if ends and ends[-1].end() >= len(stripped) * 0.5:
        return stripped[:ends[-1].end()]
    return stripped + "…"


def trim_runaway(text: str, truncated: bool = False) -> str:
    """Cut a looping reply; `truncated` means the model hit its token cap."""
    if not text or not isinstance(text, str):
        return text
    out = cut_repeats(text)
    if out is text and not truncated:
        return text
    return to_last_sentence(out)
