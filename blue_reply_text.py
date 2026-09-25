"""Pure text helpers for Blue's own reply wording.

Blue's past replies are quoted back to him in up to five memory blocks
(<conversation_memory>, the J-space episodes, <remembered_days>,
<earlier_answers>, <recent_history>), and whatever those quotes carry, he says
again. Three kinds of debris travel with them:

- instruction-block citations: "…Scarborough [known_facts]." (17 of 5,000
  logged replies, every one a citation of a prompt block);
- self-talk paragraphs: "Wait, I should also check…", "One more thing: …"
  after the real answer. The 2026-09-23 Clover reply ran to 99,666 characters
  this way and was later read aloud from <earlier_answers>;
- closing asks: "Do you want me to dim the hallway lights…, or are we calling
  it a night completely?" — quoted, an old menu becomes the next reply's menu.

Stdlib only and at the repo top level on purpose: blue_memory_improved imports
this, and importing anything under blue/ runs blue/__init__ → blue.memory →
blue_memory_improved, which is a cycle (and, outside the server, starts the
live memory system).
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

# ================================================================================
# INSTRUCTION-BLOCK CITATIONS
# ================================================================================

# The prompt's own block names. A bracket holding only these (one or several)
# is the model citing its instructions. Filenames ("[DH399_AL_2026F.docx]"),
# footnotes ("[1]") and sources ("[theguardian.com]") are not block names.
_BLOCK_NAMES = (
    "known_facts|long_term_notes|earlier_answers|earlier_sessions|"
    "remembered_days|conversation_memory|recent_history|relevant_memories|"
    "last_conversation|j_space|visual_people_memory|visual_memory|"
    "daily_rhythms|connections|expertise|current_activity|upcoming_schedule|"
    "recent_schedule|location|now|family|self_history|recent_duet|"
    "proactive_hint|focused_documents|web_research|wikipedia|syllabus_day|"
    "owner_email|duet_continuity|dated_episode_recall|untrusted_source"
)
_BLOCK_CITE_RE = re.compile(
    r"\s*\[\s*<?/?(?:%s)>?(?:\s*[,;/&]\s*(?:and\s+)?<?/?(?:%s)>?)*\s*\]"
    % (_BLOCK_NAMES, _BLOCK_NAMES),
    re.I,
)


def strip_block_citations(text: str) -> str:
    """Remove bracketed prompt-block names: "[known_facts]", "[<j_space>]"."""
    return _BLOCK_CITE_RE.sub("", text) if isinstance(text, str) else text


# ================================================================================
# SELF-TALK PARAGRAPHS
# ================================================================================

# A paragraph that opens by talking to itself. Over 5,000 logged replies this
# cut 4 (360, 9456, 9910, 10028), all defects; over both harness runs, 1 of
# 114 (run1 camera_face[2], 1,214 → 530 chars).
_SELF_TALK_LIVE = (
    r"wait[,.!—–-]+\s*(?:i\b|let me\b|actually\b|if\b|no\b)"
    r"|oh,? wait\b|actually,? wait\b"
    r"|one more thing\b|oh,? and one more thing\b"
    r"|also,? just a reminder\b"
    r"|let me (?:double[- ]check|re-?check|reconsider|correct myself)\b"
)
# Ordinary teaching openers too ("Let's assume a small lab…"), so these cut
# only what is quoted back from memory, never a reply about to be shown.
_SELF_TALK_READ = (
    r"|let['’]s (?:step back|try this|assume)\b|i['’]ll go with\b|this is good\."
)
# Used with .match() at a paragraph's start, so no "^".
_SELF_TALK_LIVE_RE = re.compile(r"\s*(?:\*\*)?(?:" + _SELF_TALK_LIVE + r")", re.I)
_SELF_TALK_READ_RE = re.compile(
    r"\s*(?:\*\*)?(?:" + _SELF_TALK_LIVE + _SELF_TALK_READ + r")", re.I)
_PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n\s*")
_FENCE_RE = re.compile(r"```.*?(?:```|$)", re.S)


def cut_self_talk(text: str, live: bool = True) -> str:
    """Cut the reply at the first later paragraph that opens with self-talk.

    The first paragraph is the answer and is never cut. Paragraphs inside a
    ``` fence are code or a quoted script, not the model thinking aloud.
    `live=False` is the wider read-side pattern for quoting stored replies.
    """
    if not text or not isinstance(text, str):
        return text
    pattern = _SELF_TALK_LIVE_RE if live else _SELF_TALK_READ_RE
    fences = [m.span() for m in _FENCE_RE.finditer(text)]
    first_para = len(text) - len(text.lstrip())
    for brk in _PARAGRAPH_BREAK_RE.finditer(text):
        start = brk.end()
        if brk.start() < first_para or any(a <= start < b for a, b in fences):
            continue
        if pattern.match(text, start):
            return text[:brk.start()].rstrip()
    return text


# ================================================================================
# CLOSING ASKS
# ================================================================================

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # pictographs, emoticons, symbols
    "\U0001F000-\U0001F0FF"
    "☀-➿"           # misc symbols and dingbats
    "️‍"            # variation selectors, ZWJ
    "]+"
)
# Offers and either/or menus put to the listener.
_ASK_RE = re.compile(
    r"\b(?:do you want me to|want me to|would you like me to|should I|shall I|"
    r"or would you|or should (?:I|we)|or are (?:we|you)|or do you|or just\b|"
    r"want to hear another|anything else|let me know)",
    re.I,
)
_DEVICE_OFFER_RE = re.compile(
    r"\bI (?:can|could) (?:also )?(?:dim|play|put on|set a reminder|pull up|"
    r"turn (?:on|off|down|up))\b",
    re.I,
)
# Sentence ends inside a line: punctuation + spaces, not after a title.
_ASK_BOUNDARY_RE = re.compile(
    r"((?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bSt\.)(?<=[.!?])[ \t]+)")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+•]\s|\d+[.)]\s)")
_TO_LISTENER_RE = re.compile(r"\b(?:you|your|we)\b", re.I)
_SHORT_CLOSER_CHARS = 80


def strip_closing_asks(text: str) -> str:
    """Blue's words minus offers, either/or menus and one closing question.

    For quoting a past reply in a memory block. Content sentences, list items
    and mid-reply questions stay, so "what were those ideas?" still has its
    source. Over Blue's 4,302 logged replies this changes 36% of them beyond
    emoji and removes 3.9% of the characters, almost all closing questions; a
    numbered list of discussion questions comes through intact. Never returns
    empty.
    """
    if not text or not text.strip():
        return text
    t = _EMOJI_RE.sub("", text).rstrip()
    sents, seps = [], []
    lines = t.split("\n")
    for li, line in enumerate(lines):
        nl = "\n" if li < len(lines) - 1 else ""
        if _LIST_ITEM_RE.match(line) or not line.strip():
            sents.append(line)
            seps.append(nl)
            continue
        parts = _ASK_BOUNDARY_RE.split(line)
        sents.extend(parts[0::2])
        seps.extend(parts[1::2] + [nl])
    keep = []
    for s, sep in zip(sents, seps):
        st = s.strip()
        if not _LIST_ITEM_RE.match(s) and (
                (st.endswith("?") and _ASK_RE.search(st))
                or _DEVICE_OFFER_RE.search(st)):
            continue
        keep.append([s, sep])
    # Blank trailing lines left by a dropped closer.
    while keep and not keep[-1][0].strip():
        keep.pop()
    # At most ONE more closing question put to the listener, and only a short
    # one; anything matching _ASK_RE is already gone. A long final question is
    # usually content ("what was that question you suggested?" needs it).
    if len(keep) > 1:
        last = keep[-1][0].strip()
        if (last.endswith("?") and not _LIST_ITEM_RE.match(keep[-1][0])
                and _TO_LISTENER_RE.search(last)
                and len(last) < _SHORT_CLOSER_CHARS):
            keep.pop()
    out = "".join(s + sep for s, sep in keep).rstrip()
    return out or text.strip()


# ================================================================================
# WHOLE-REPLY CHECKS
# ================================================================================

_RUNAWAY_CHARS = 8000
_cut_repeats = None


def _load_cut_repeats():
    """blue.server.runaway.cut_repeats, without importing the blue package.

    `import blue.server.runaway` runs blue/__init__, which starts the memory
    system against the live data folder — in an offline script, that is a
    write to the real ChromaDB. runaway.py itself is stdlib only, so when the
    server hasn't already loaded it, load the file directly.
    """
    global _cut_repeats
    if _cut_repeats is None:
        mod = sys.modules.get("blue.server.runaway")
        if mod is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "blue", "server", "runaway.py")
            spec = importlib.util.spec_from_file_location(
                "_blue_reply_text_runaway", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        _cut_repeats = mod.cut_repeats
    return _cut_repeats


def is_runaway_text(text: str) -> bool:
    """A stored reply too broken to quote: huge, self-talking or looping.

    Self-talk here is the live pattern only: "Let's assume…" or "I'll go
    with…" opens a worked example, and a teaching reply that uses one is
    still worth recalling. quotable_reply trims those paragraphs instead.
    """
    if not text or not isinstance(text, str):
        return False
    if len(text) > _RUNAWAY_CHARS or cut_self_talk(text) != text:
        return True
    try:
        cut_repeats = _load_cut_repeats()
    except Exception:
        return False
    return cut_repeats(text) != text


def quotable_reply(text: str) -> str:
    """Blue's past reply as a memory block may quote it."""
    return strip_closing_asks(strip_block_citations(cut_self_talk(text, live=False)))
