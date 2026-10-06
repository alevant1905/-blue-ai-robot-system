"""How long Blue's visible reply may be: the length follows the user's turn.

A short message got an essay. Live after 09-27 the median chat reply was 196
words, and 21 of 29 turns without an attachment ran over 100 ("Is autoGPT a
type of harness" -> 253 words). On the 10-05 harness 20 of 98 turns of
twelve words or fewer got more than 100 words, every one of them a turn that
thought first, up to 618.

So a message of twelve words or fewer that asks for nothing long gets a cap on
the visible reply — about 220 tokens typed, 120 spoken — and a typed question
gets SHORT_TURN_NOTE beside the user's words. Asking for length in so many
words lifts both: a document, a list, a draft, a plan, a report, a story,
"explain in detail", "go on", "tell me more", "keep going", "what were those
ideas?". The cap is on the words he says; the reasoning allowance
(thinking.THINKING_ALLOWANCE_TOKENS) is added on top of it when the turn
thinks, and the words themselves are then held to it as they arrive
(bluetools.call_lm_studio).

The cap alone would cut those essays off mid-thought; the note is what makes
the model write a short answer that fits. It does not offer to go deeper:
asked to ("offer to go deeper in one clause if there's more"), one reply in
four closed on "If you want, I can…" or "Happy to go deeper…" — against
ENDINGS — and the lengths were the same without it ("what could go wrong?"
116-166 words with the offer, 133-146 without). "go on" lifts the cap.

Pure text in, a number out — no bluetools import.
"""

from __future__ import annotations

import re
from typing import Optional

from blue.server import thinking as _thinking

# Messages of this many words or fewer get a short reply, as for thinking's
# short replies (thinking.SHORT_REPLY_WORDS).
SHORT_TURN_WORDS = 12
# The visible reply's cap, in tokens: about 170 words typed (five sentences
# with room to finish the last one) and 90 spoken (SPOKEN REPLY asks for one
# or two sentences).
TYPED_REPLY_TOKENS = 220
SPOKEN_REPLY_TOKENS = 120
# Characters of visible reply per token on qwen3.8-27b: the median over 209
# harness replies on 10-05 (p10 3.6, p90 4.7). A thinking turn's reasoning
# shares max_tokens with the reply, so its cap is counted in characters.
CHARS_PER_TOKEN = 4.3

# Beside the user's words in the live turn (see short_turn_note). Replayed on
# qwen3.8-27b over the 10-05 harness payloads, n=3 a turn: as one more line at
# the end of STYLE, three wordings changed nothing — "what could go wrong?"
# in the topic_development thread got 205-408 words in 9 replays of 9 (391,
# 266 and 189 in the runs). Pinned in the turn, "…about 100 words, as plain
# paragraphs." gave 116-166 words, each a finished answer, and 78-151 words
# over six other turns that had run to 95-398 ("would you do it
# differently?" 392, 398, 226 -> 83-97). Without "as plain paragraphs" one
# reply in three was a bulleted list of 340 words. "about 100 words" is a
# target a one-line answer can be padded to, so the note gives a ceiling:
# "where are you right now?" stayed at 28-47 words (24-39 before).
SHORT_TURN_NOTE = ("A short message: answer it in at most five sentences and "
                   "under 100 words, as plain paragraphs.")

# Something whose length is the point, asked for by name.
_ARTIFACT_RE = re.compile(
    r"\b(?:documents?|essays?|reports?|letters?|memos?|articles?|summary|summaries"
    r"|outlines?|drafts?|lists?|syllabus|syllabi|rubrics?|agendas?|itinerary"
    r"|scripts?|story|stories|poems?|lyrics|speech|recipes?|quiz(?:zes)?"
    r"|worksheets?|handouts?|slides?|presentations?|bibliography|proposals?"
    r"|cover letter|resume|cv|timeline|overview|breakdown|transcripts?"
    r"|instructions|pros and cons|step[- ]by[- ]step|walkthrough"
    # a day's or a week's events are a list
    r"|schedule|calendar|timetable)\b"
    # a plan as a thing, not "I plan to"
    r"|\b(?:a|the|my|your|our|his|her|lesson|study|course|teaching|weekly"
    r"|daily|game|action|project|lecture) plans?\b|\bplan (?:out|for|my|the|a)\b")
# Writing it is the reply: "write me…", "summarise the chapter", "list them".
_WRITE_RE = re.compile(
    r"\b(?:write|rewrite|draft|compose|translate|summari[sz]e|outline"
    r"|transcribe|proofread|brainstorm|enumerate|list|itemi[sz]e|tabulate"
    r"|paraphrase)\b")
# Depth asked for in so many words.
_DEPTH_RE = re.compile(
    r"\bin (?:more |much more |great |full |greater |real )?(?:detail|depth)\b"
    r"|\b(?:detailed|thorough(?:ly)?|exhaustive|comprehensive|at length|in full)\b"
    r"|\bexplain (?:it |this |that )?fully\b"
    r"|\b(?:go|dig|dive) deeper\b|\bdeep[- ]dive\b"
    r"|\blong(?:er)? (?:version|answer|explanation|reply)\b"
    r"|\bfull (?:version|story|list|text|details?|explanation|answer|picture|rundown)\b"
    r"|\bthe whole (?:thing|story|list|text|document|picture|paper|chapter)\b"
    r"|\btell (?:me|us) (?:everything|all about)\b|\beverything (?:about|you know)\b"
    r"|\bwalk (?:me|us|them|him|her) through\b"
    r"|\bgo (?:over|through) (?:it|this|that|them|the|each|all|every)\b"
    r"|\bbreak (?:it|this|that|them) down\b|\bspell (?:it|this|that) out\b"
    r"|\b(?:tell|say|show|explain|give) (?:me |us )?(?:a (?:bit|little) |some )?more\b"
    r"|\bmore (?:about|on|detail|details)\b|\belaborate\b|\bexpand\b"
    r"|\bkeep going\b|\b(?:please |ok(?:ay)? |so |and )?go on[\s.!?]*$"
    r"|\bcontinue (?:with|the|it|that|where|from)\b|\bwhat else\b"
    r"|\bfinish (?:it|that|this|the)\b")
# "give me 5 examples", "three ideas": a count of things.
_COUNT_RE = re.compile(
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|fifteen|twenty)\s+(?:\w+\s+)?(?:ideas|examples|ways|reasons|questions"
    r"|tips|options|steps|things|points|suggestions|titles|books|papers"
    r"|articles|activities|exercises|prompts|names|topics|sources|readings"
    r"|recommendations|paragraphs|sentences|pages|bullets|bullet points"
    r"|words|lines|items)\b")
# Recall of something long he said: "what were those ideas?", "what were the
# lab ideas you gave me last night?" (<earlier_answers> must come back whole).
_RECALL_RE = re.compile(
    r"\b(?:you|we) (?:gave|told|said|suggested|mentioned|wrote|listed"
    r"|recommended|came up with|talked about|discussed|went over|covered"
    r"|decided|planned|agreed on)\b"
    r"|\bdid (?:you|we) (?:say|tell|suggest|write|recommend|mention|talk|discuss"
    r"|decide|come up|list|give|cover|go over)\b"
    r"|\bremind me (?:what|of|about|how|why|where|when|who)\b"
    r"|\b(?:those|these|the|your|that) (?:ideas|suggestions|examples|options"
    r"|points|tips|steps|recommendations|names|questions|reasons|readings)\b")
# Reading something out: the text is the reply.
_READ_RE = re.compile(
    r"\bread (?:me|us|it|that|this|the|them|out|aloud|back|him|her)\b")


def asks_for_length(text: str) -> bool:
    """Does the message ask for something long — a document, a list, depth,
    more of the last answer, or the recall of a long one?"""
    t = _thinking._normalise(text)
    if not t:
        return False
    bare = _thinking._FILLER_PREFIX_RE.sub(
        "", _thinking._GREETING_PREFIX_RE.sub(
            "", _thinking._LEADING_NAME_RE.sub("", t))).strip()
    if _thinking._CONTINUE_RE.match(bare) or _thinking._AGAIN_RE.search(t):
        return True
    return any(rx.search(t) for rx in (
        _ARTIFACT_RE, _WRITE_RE, _DEPTH_RE, _COUNT_RE, _RECALL_RE, _READ_RE))


def reply_budget(text: str, *, voice: bool = False,
                 has_attachment: bool = False,
                 depth_cue: bool = False) -> Optional[int]:
    """The visible reply's cap in tokens for this turn, or None for no cap.

    `text` is the user's own words (attachments stripped). `voice` means the
    reply will be spoken. `has_attachment` covers a document, a long paste or
    an image. `depth_cue` is the caller's own sign that length is wanted:
    accepting an offer of real work ("sure" after "want me to draft it?").
    """
    if has_attachment or depth_cue:
        return None
    t = _thinking._normalise(text)
    if not t or len(t.split()) > SHORT_TURN_WORDS:
        return None
    if _thinking._URL_RE.search(t) or asks_for_length(t):
        return None
    return SPOKEN_REPLY_TOKENS if voice else TYPED_REPLY_TOKENS


def short_turn_note(text: str, *, voice: bool = False, kid: bool = False,
                    thinking: Optional[str] = None) -> str:
    """SHORT_TURN_NOTE for a capped turn that needs it, else "".

    Only where the long replies were: a typed question or request the turn
    thinks about (all 20 of the 10-05 harness's were). A greeting, an
    acknowledgement or a correction is short already, and a size in the
    note could pad it ("hi blue" got 27-40 words with one, 12-15 in the
    runs). Spoken turns have SPOKEN REPLY, and the kids' page its own STYLE.
    """
    if voice or kid or thinking != _thinking.THINK_ON:
        return ""
    return SHORT_TURN_NOTE if _thinking.asks_something(text) else ""


def visible_chars(cap_tokens: int) -> int:
    """The cap in characters of visible reply."""
    return int(cap_tokens * CHARS_PER_TOKEN)
