"""Intelligent OCF (Ohbot conversation file) compaction.

The Ohbot client appends every exchange to a `.ocf` XML file and ships the
whole file to Blue on each prompt. Left alone the file grows without bound
and bloats every request. This module compacts it WITHOUT losing anything
important:

  - the most recent KEEP_TAIL conversations are kept verbatim (exact recent
    context);
  - older conversations have pure noise removed — connection-failure
    replies ("I'm having trouble connecting") and content-free greetings
    ("how are you doing", "can you hear me");
  - exact duplicate exchanges are collapsed (Blue introduced himself to the
    same person ten times with identical text — one copy carries the same
    information as ten);
  - a character budget keeps the file small: the recent tail is always
    kept, then older survivors are added newest-first until the budget is
    reached.

Why this is safe to be aggressive: the `.ocf` is only a rolling short-term
window. Every message is also in the server's `conversation_log`, and each
day is recapped in `session_summaries` — those are the permanent record. So
trimming the `.ocf` cannot lose anything that matters.

Compaction is fully deterministic — no LLM — so it can never fabricate or
distort a conversation while "summarizing" it.
"""

import glob
import html
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET

# --- Tuning knobs (env-overridable) ---------------------------------------
KEEP_TAIL = int(os.environ.get("BLUE_OCF_KEEP_TAIL", "12"))        # recent convos always kept verbatim
MAX_CHARS = int(os.environ.get("BLUE_OCF_MAX_CHARS", "14000"))     # char budget for the kept conversations (~3500 tokens)
SIZE_THRESHOLD = int(os.environ.get("BLUE_OCF_SIZE_THRESHOLD", "50000"))   # bytes before auto-compaction acts
COMPACT_INTERVAL = int(os.environ.get("BLUE_OCF_COMPACT_INTERVAL", "1800"))  # seconds between auto runs

_DEFAULT_DIR = r"C:\Users\jfsebastian\OneDrive\Documents\OhBot\Conversations"

# Assistant replies that carry no information — drop the whole exchange.
_FAILURE_MARKERS = (
    "having trouble connecting",
    "couldnt complete your request",
    "i couldnt complete",
    "something went wrong on my end",
)

# Greeting / audio-check phrases. A user turn made up only of these is
# pleasantry with no durable content. Sorted longest-first so the longest
# match is removed before its shorter substrings.
_GREETING_PHRASES = tuple(sorted({
    "how are you doing today", "how are you doing", "how are you",
    "how is it going", "hows it going", "how you doing today",
    "how you doing", "are you able to hear me ok", "are you able to hear me",
    "can you hear me ok", "can you hear me", "can you still hear me",
    "are you there", "you there", "are you working", "you working",
    "good morning", "good evening", "good afternoon", "good night",
    "hey there", "hello there", "hi there", "hello", "hey",
    "you doing ok", "are you ok", "is everything ok", "everything ok",
    "you feeling ok", "feeling ok", "whats up", "you doing",
    "still there", "you ok", "you alright",
}, key=len, reverse=True))

# Filler words left behind after greeting phrases are stripped.
_GREETING_FILLER = frozenset(
    "ok okay alright today now right my little friend blue there well good "
    "fine still hey hi so just doing you i am are it is and the a how".split()
)

_last_compaction = 0.0


# --- Text helpers ---------------------------------------------------------

def _norm(s: str) -> str:
    """Normalised form for comparison: unescaped, lowercased, alphanumerics
    and single spaces only."""
    t = html.unescape(s or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def _is_failure(assistant_raw: str) -> bool:
    n = _norm(assistant_raw)
    return any(m in n for m in _FAILURE_MARKERS)


def _is_greeting_only(user_raw: str) -> bool:
    """True if the user turn is nothing but a greeting / audio check."""
    n = _norm(user_raw)
    if not n or len(n) > 70:
        return False
    for phrase in _GREETING_PHRASES:
        n = n.replace(phrase, " ")
    leftover = [w for w in n.split() if w not in _GREETING_FILLER]
    return sum(len(w) for w in leftover) < 4


def _conversation_texts(block: str):
    """Pull (user, assistant) raw text out of one <Conversation> block."""
    u = re.search(r"<UserContent>(.*?)</UserContent>", block, re.DOTALL)
    a = re.search(r"<AssistantContent>(.*?)</AssistantContent>", block, re.DOTALL)
    return (u.group(1) if u else ""), (a.group(1) if a else "")


# --- Core compaction ------------------------------------------------------

def compact_ocf_text(raw: str):
    """Compact OCF XML text. Returns (new_text, stats_dict).

    new_text == raw when there is nothing to compact (caller can skip the
    write). The XML structure is preserved byte-for-byte except that whole
    <Conversation> blocks are removed."""
    stats = {
        "original": 0, "kept": 0, "dropped_failure": 0,
        "dropped_greeting": 0, "dropped_duplicate": 0, "dropped_cap": 0,
    }
    open_tag, close_tag = "<ConversationList>", "</ConversationList>"
    i, j = raw.find(open_tag), raw.find(close_tag)
    if i == -1 or j == -1 or j < i:
        return raw, stats  # not the expected structure — leave it untouched

    header = raw[:i + len(open_tag)]
    footer = raw[j:]
    middle = raw[i + len(open_tag):j]

    blocks = re.findall(r"<Conversation>.*?</Conversation>", middle, re.DOTALL)
    stats["original"] = len(blocks)
    if len(blocks) <= KEEP_TAIL:
        return raw, stats  # already short — nothing to do

    first = middle.find("<Conversation>")
    indent_before = middle[:first]
    last_end = middle.rfind("</Conversation>") + len("</Conversation>")
    indent_after = middle[last_end:]

    n = len(blocks)
    tail_start = n - KEEP_TAIL

    # Seed the seen-sets with the verbatim tail so an OLDER exchange that
    # duplicates a recent one is the copy that gets dropped.
    #  - `seen`: exact (user, assistant) exchanges.
    #  - `long_seen`: substantial assistant answers on their own. Blue
    #    repeats canned long replies (the same self-introduction given to
    #    the same person ten times) where only the user's wording differs,
    #    so an identical long answer is a reliable duplicate signal.
    _LONG_ANSWER = 240
    seen = set()
    long_seen = set()
    for b in blocks[tail_start:]:
        u, a = _conversation_texts(b)
        a_norm = _norm(a)
        seen.add(_norm(u) + " ||| " + a_norm)
        if len(a_norm) > _LONG_ANSWER:
            long_seen.add(a_norm)

    kept = []
    for idx, block in enumerate(blocks):
        if idx >= tail_start:
            kept.append(block)            # recent tail — always verbatim
            continue
        user, assistant = _conversation_texts(block)
        if _is_failure(assistant):
            stats["dropped_failure"] += 1
            continue
        if _is_greeting_only(user):
            stats["dropped_greeting"] += 1
            continue
        u_norm, a_norm = _norm(user), _norm(assistant)
        key = u_norm + " ||| " + a_norm
        if key in seen or (len(a_norm) > _LONG_ANSWER and a_norm in long_seen):
            stats["dropped_duplicate"] += 1
            continue
        seen.add(key)
        if len(a_norm) > _LONG_ANSWER:
            long_seen.add(a_norm)
        kept.append(block)

    # Character-budget cap. The recent tail is always kept (even if it
    # alone exceeds the budget); older survivors are then added newest-first
    # until MAX_CHARS is reached. Dropping old conversations is safe — the
    # full history lives permanently in conversation_log + session_summaries.
    if len(kept) > KEEP_TAIL:
        tail_blocks = kept[-KEEP_TAIL:]
        older = kept[:-KEEP_TAIL]
    else:
        tail_blocks, older = kept, []
    budget = MAX_CHARS - sum(len(b) for b in tail_blocks)
    keep_older = []
    for block in reversed(older):          # newest of the older first
        if budget - len(block) < 0:
            break
        budget -= len(block)
        keep_older.append(block)
    keep_older.reverse()
    stats["dropped_cap"] = len(older) - len(keep_older)
    kept = keep_older + tail_blocks

    stats["kept"] = len(kept)
    if len(kept) == n:
        return raw, stats  # nothing was removed

    new_middle = "".join(indent_before + b for b in kept) + indent_after
    return header + new_middle + footer, stats


# --- File-level operations ------------------------------------------------

def find_ocf_file():
    """Locate the active .ocf file. BLUE_OCF_PATH pins an exact file;
    otherwise the newest *.ocf in BLUE_OCF_DIR (or the default folder)."""
    explicit = os.environ.get("BLUE_OCF_PATH")
    if explicit and os.path.isfile(explicit):
        return explicit
    folder = os.environ.get("BLUE_OCF_DIR", _DEFAULT_DIR)
    try:
        candidates = glob.glob(os.path.join(folder, "*.ocf"))
    except Exception:
        return None
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def compact_ocf_file(path: str = None) -> dict:
    """Compact one .ocf file in place: back up, write atomically, verify.

    Returns a stats dict. Never raises — a failure leaves the file
    untouched. Skips the write if the file changed underneath us (the
    Ohbot client wrote concurrently) or if the result wouldn't parse."""
    path = path or find_ocf_file()
    if not path or not os.path.isfile(path):
        return {"status": "no_file"}

    try:
        mtime_before = os.path.getmtime(path)
        data = open(path, "rb").read()
    except Exception as e:
        return {"status": "read_error", "error": str(e)}

    bom = data.startswith(b"\xef\xbb\xbf")
    raw = data.decode("utf-8-sig", errors="replace")

    new_raw, stats = compact_ocf_text(raw)
    stats["status"] = "ok"
    stats["path"] = path
    stats["orig_chars"] = len(raw)
    stats["new_chars"] = len(new_raw)
    if new_raw == raw:
        stats["status"] = "noop"
        return stats

    # Verify the compacted XML before trusting it.
    try:
        root = ET.fromstring(new_raw)
        if len(root.findall(".//Conversation")) != stats["kept"]:
            stats["status"] = "verify_mismatch"
            return stats
    except ET.ParseError as e:
        stats["status"] = "verify_failed"
        stats["error"] = str(e)
        return stats

    # Bail if the client wrote to the file while we were working.
    try:
        if os.path.getmtime(path) != mtime_before:
            stats["status"] = "skipped_concurrent_write"
            return stats
    except Exception:
        pass

    out = (b"\xef\xbb\xbf" if bom else b"") + new_raw.encode("utf-8")
    try:
        shutil.copy2(path, path + ".autobackup")  # single rolling backup
        folder = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".ocftmp")
        with os.fdopen(fd, "wb") as f:
            f.write(out)
        os.replace(tmp, path)  # atomic on the same volume
    except Exception as e:
        stats["status"] = "write_error"
        stats["error"] = str(e)
        return stats
    return stats


def compact_ocf_if_due() -> None:
    """Rate-limited auto-compaction for the background heartbeat. A cheap
    no-op until the file is large AND enough time has passed."""
    global _last_compaction
    now = time.time()
    if now - _last_compaction < COMPACT_INTERVAL:
        return
    path = find_ocf_file()
    if not path:
        return
    try:
        if os.path.getsize(path) < SIZE_THRESHOLD:
            _last_compaction = now  # small enough — don't re-check for a while
            return
    except Exception:
        return
    _last_compaction = now
    stats = compact_ocf_file(path)
    if stats.get("status") == "ok":
        print(
            f"[OCF] compacted {os.path.basename(path)}: "
            f"{stats['original']}->{stats['kept']} conversations "
            f"({stats['orig_chars']}->{stats['new_chars']} chars; "
            f"dropped {stats['dropped_failure']} failure, "
            f"{stats['dropped_greeting']} greeting, "
            f"{stats['dropped_duplicate']} duplicate, "
            f"{stats['dropped_cap']} over-cap)",
            flush=True,
        )
    elif stats.get("status") not in ("noop", "no_file"):
        print(f"[OCF] compaction skipped: {stats.get('status')}", flush=True)


if __name__ == "__main__":
    # Manual one-off compaction: `python blue_ocf.py`
    result = compact_ocf_file()
    print(result)
