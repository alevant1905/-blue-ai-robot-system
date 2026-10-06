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

The first two also clean the live reply before it is shown, spoken or stored
(turn_completion.finish, with the narrower live self-talk pattern), so the
debris is not made in the first place.

Three more judge a reply before it goes out at all: strip_reasoning_tags drops
a reasoning pass that leaked into the text ("…</think>"), written_tool_calls
finds a tool call the model wrote out as text instead of making it
("<tool_call><function=web_search>…"), and reads_as_deliberation spots a
forced tool call that wrote the model arguing with itself instead of the call.

Stdlib only and at the repo top level on purpose: blue_memory_improved imports
this, and importing anything under blue/ runs blue/__init__ → blue.memory →
blue_memory_improved, which is a cycle (and, outside the server, starts the
live memory system).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from typing import List, NamedTuple

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
# LEAKED REASONING
# ================================================================================

_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.I)
_THINK_OPEN_RE = re.compile(r"<think\s*>", re.I)


def strip_reasoning_tags(text: str) -> str:
    """Drop a reasoning pass that leaked into a reply's text.

    Everything up to and including the LAST "</think>" is the model thinking,
    and a stray "<think>" is removed. On 2026-10-05 a forced create_reminder
    came back as 6,976 characters with three literal "</think>" tags in it,
    and every character was shown. Text without the tags is returned as is.
    """
    if not text or not isinstance(text, str) or "think" not in text.lower():
        return text
    closes = list(_THINK_CLOSE_RE.finditer(text))
    out = text[closes[-1].end():] if closes else text
    out = _THINK_OPEN_RE.sub("", out)
    return out.strip() if out != text else text


# The model deciding what to say instead of saying it. All from forced tool
# calls that came back as words: "remind me to call the dentist" (2026-10-05
# harness: "Hmm, that's two questions. Let me clean this up.", "Final
# answer:", "I keep second-guessing", "Sending it now for real this time")
# and the send_gmail statement on 09-27 (conversation_log 10048: "Actually, I
# shouldn't assume — you asked me about structure").
_DELIBERATION_RE = re.compile(
    r"</?think\s*>"
    r"|\bfinal (?:final|answer|reply)\s*:"
    r"|\bsecond[- ]guessing\b"
    r"|\blet me (?:clean (?:this|that) up|rethink|re-?read|make sure i['’]m not)\b"
    r"|\b(?:the|my) (?:system prompt|style (?:guide|rules)|instructions? (?:is|are|says?))\b"
    r"|\bi(?:['’]m| am) (?:told|instructed) to\b"
    r"|\bsending (?:it|that|this) now\b"
    r"|\bi shouldn['’]t assume\b"
    r"|\binternal monologue\b",
    re.I,
)
# A later paragraph opening on second thoughts: "Hmm, that's two questions.",
# "No — one question, no menu.", "Wait — you mentioned…".
_SECOND_THOUGHT_RE = re.compile(
    r"\s*(?:\*\*)?(?:wait|hmm+|actually|no)\s*[,.!—–-]", re.I)


def reads_as_deliberation(text: str) -> bool:
    """Does this text argue with itself about what to reply?

    For judging the words a forced tool call wrote instead of calling, which
    are never meant as a reply. Not for ordinary replies: a teaching answer
    may well open its second paragraph with "Actually, ...".
    """
    if not text or not isinstance(text, str):
        return False
    if _DELIBERATION_RE.search(text) or cut_self_talk(text, live=False) != text:
        return True
    first_para = len(text) - len(text.lstrip())
    return any(brk.start() > first_para
               and _SECOND_THOUGHT_RE.match(text, brk.end())
               for brk in _PARAGRAPH_BREAK_RE.finditer(text))


# ================================================================================
# TOOL CALLS WRITTEN AS TEXT
# ================================================================================

# A tool call the model wrote into its reply instead of making it. Twelve of
# Blue's logged replies are one (conversation_log 481 to 9392, July and
# August), and the 2026-10-05 harness made another. All are the Qwen form:
#   <tool_call>
#   <function=search_documents>
#   <parameter=query>
#   reading report requirements assignment instructions format DH399
#   </parameter>
#   </function>
#   </tool_call>
# The Hermes form puts a JSON object inside <tool_call>; a bare
# <function=NAME>…</function>, and a reply that is nothing but
# {"name": …, "arguments": {…}}, are the same thing. Each logged one ended
# the reply. Seven came after a sentence announcing it ("Let me try again
# with the right term."), and one was a create_document carrying a whole
# reading report. A call cut off by the token cap stops inside its body.
#
# Not a call: "<tool_call>" named in prose ("Qwen wraps each call in
# <tool_call> tags"). A call has a body, <function=NAME> or a JSON object, or
# nothing at all after the tag. Nor is markup inside a ``` fence or `code`:
# that is an example being shown, unless the reply is nothing else.

class WrittenCall(NamedTuple):
    name: str        # "" when the body names no tool
    args: dict
    start: int
    end: int
    complete: bool   # every tag closed and the arguments read whole


# A function tag opens a call only when a body follows it: "<function=x>
# names the tool and <parameter=query> holds the query" is prose. A body may
# be a tag the token cap cut off at the very end ("<tool_call>\n<funct").
_CUT_TAG = r"<[\w=./\-]*\Z"
_FUNCTION_TAG = (r"<function=[\w.\-]+>(?=\s*(?:<parameter=|\{|</function|"
                 + _CUT_TAG + r"|\Z))")
_CALL_OPEN_RE = re.compile(
    r"<tool_call\s*>(?=\s*(?:" + _FUNCTION_TAG + r"|\{|" + _CUT_TAG + r"|\Z))|"
    + _FUNCTION_TAG,
    re.I)
_CALL_CLOSE_RE = re.compile(r"</tool_call\s*>", re.I)
_FUNCTION_OPEN_RE = re.compile(r"\s*<function=([\w.\-]+)>", re.I)
_FUNCTION_CLOSE_RE = re.compile(r"</function\s*>", re.I)
_PARAM_OPEN_RE = re.compile(r"<parameter=[\w.\-]+>", re.I)
_PARAM_RE = re.compile(
    r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter\s*>", re.I | re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_JSON_REPLY_RE = re.compile(r"\A\s*(?:```(?:json)?\s*)?(\{.*\})\s*(?:```)?\s*\Z",
                            re.I | re.S)
# The sentence before a call that ended the reply, announcing it: "Let me try
# again with the right term.", "First, I will look up the first one." With
# the call gone it promises a lookup that never comes. Only a sentence about
# looking something up: "Let me explain why…" or "I'll summarize: …" is an
# answer.
_ANNOUNCES_CALL_RE = re.compile(
    r"(?:(?:(?<=[.!?…:])|(?<=[.!?…:][\"'”’)\]]))[ \t]+|\n\s*|\A\s*)"
    r"(?:(?:now|first|so|ok(?:ay)?|alright|next)\s*,?\s+)?"
    r"(?:let me|let['’]s|i['’]ll|i will|i['’]m going to|i am going to)\s+"
    r"(?:\w+\s+){0,3}?"
    r"(?:try|search|look|check|correct|fix|find|pull|fetch|query|run|re-?run"
    r"|read|browse|open|grab|dig|refine|redo|retry|google|call"
    r"|do (?:that|this|a|another|one))\w*\b"
    r"[^.!?\n:]{0,200}[.!?…:]*\s*\Z",
    re.I)


def _quoted_spans(text):
    spans = [m.span() for m in _FENCE_RE.finditer(text)]
    spans += [m.span() for m in _INLINE_CODE_RE.finditer(text)
              if not any(a <= m.start() < b for a, b in spans)]
    return spans


def _call_arguments(body):
    """(args, whole) from a call body: <parameter=KEY> pairs or a JSON object."""
    if _PARAM_OPEN_RE.search(body):
        pairs = _PARAM_RE.findall(body)
        return ({k: v.strip() for k, v in pairs},
                len(pairs) == len(_PARAM_OPEN_RE.findall(body)))
    if not body.strip():
        return {}, True
    try:
        start = body.index("{")
        args, _ = json.JSONDecoder().raw_decode(body, start)
    except ValueError:
        return {}, False
    return (args, True) if isinstance(args, dict) else ({}, False)


def _json_call(payload, *, needs_arguments=False):
    """(name, args) from {"name": …, "arguments": {…}}; None if not that.

    Outside a <tool_call> tag the object must carry its arguments too:
    {"name": "Ada", "role": "TA"} is not a call."""
    if not isinstance(payload, dict):
        return None
    if needs_arguments and not ({"arguments", "parameters"} & payload.keys()):
        return None
    name = payload.get("name")
    args = payload.get("arguments", payload.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = None
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip(), args if isinstance(args, dict) else {}


def _read_call(text, start, end_of_open):
    """The WrittenCall that opens at `start` ("<tool_call>" or "<function=")."""
    tool_call = text[start:end_of_open].lower().startswith("<tool_call")
    close = _CALL_CLOSE_RE.search(text, end_of_open) if tool_call else None
    limit = close.start() if close else len(text)
    fn = _FUNCTION_OPEN_RE.match(text, end_of_open if tool_call else start)
    if fn and fn.end() <= limit:
        fclose = _FUNCTION_CLOSE_RE.search(text, fn.end(), limit)
        args, whole = _call_arguments(
            text[fn.end():fclose.start() if fclose else limit])
        end = close.end() if close else (fclose.end() if fclose else len(text))
        return WrittenCall(fn.group(1), args, start, end, bool(fclose and whole))
    # <tool_call>{"name": …}</tool_call>, or "<tool_call>" and nothing after.
    body = text[end_of_open:limit]
    parsed = None
    try:
        brace = body.index("{")
        payload, used = json.JSONDecoder().raw_decode(body, brace)
        parsed = _json_call(payload)
        if not close:
            limit = end_of_open + used
    except ValueError:
        pass
    end = close.end() if close else limit
    if parsed:
        return WrittenCall(parsed[0], parsed[1], start, end, bool(close))
    return WrittenCall("", {}, start, end, False)


def written_tool_calls(text) -> List[WrittenCall]:
    """The tool calls written out in `text` instead of being made, in order.

    Markup quoted in a code fence or `code` is not counted, unless the reply
    has no words outside it.
    """
    if not text or not isinstance(text, str):
        return []
    low = text.lower()
    calls = []
    if "<tool_call" in low or "<function=" in low:
        quoted = _quoted_spans(text)
        if quoted:
            outside = list(text)
            for a, b in quoted:
                outside[a:b] = [" "] * (b - a)
            if not re.search(r"\w", "".join(outside)):
                quoted = []
        pos = 0
        while True:
            m = _CALL_OPEN_RE.search(text, pos)
            if not m:
                break
            if any(a <= m.start() < b for a, b in quoted):
                pos = m.end()
                continue
            call = _read_call(text, m.start(), m.end())
            calls.append(call)
            pos = max(call.end, m.end())
    if not calls:
        whole = _JSON_REPLY_RE.match(text)
        if whole:
            try:
                parsed = _json_call(json.loads(whole.group(1)),
                                    needs_arguments=True)
            except ValueError:
                parsed = None
            if parsed:
                calls.append(WrittenCall(parsed[0], parsed[1], 0, len(text), True))
    return calls


def has_tool_markup(text) -> bool:
    """Does `text` hold a tool call written out instead of made?"""
    return bool(written_tool_calls(text))


def strip_tool_markup(text):
    """`text` without the tool calls written into it.

    When a call ended the reply, the sentence announcing it goes too ("Let me
    try again with the right term."): nothing follows it now. Text without a
    call is returned as is; a reply that was only a call comes back "".
    """
    calls = written_tool_calls(text)
    if not calls:
        return text
    pieces, pos = [], 0
    for call in calls:
        pieces.append(text[pos:call.start])
        pos = call.end
    tail = text[pos:]
    if not tail.strip():
        for _ in range(2):
            cut = _ANNOUNCES_CALL_RE.sub("", pieces[-1], count=1)
            if cut == pieces[-1]:
                break
            pieces[-1] = cut
    out = "".join(pieces) + tail
    out = re.sub(r"```[\w-]*\s*```", "", out)   # the fence a call was in
    out = re.sub(r"[ \t]+\n", "\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


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
