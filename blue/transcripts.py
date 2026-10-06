"""Chat transcripts: every conversation on a chat page, kept whole.

The chat page lists these down its left side so Alex can reopen any past
conversation, read it, and carry on where it stopped. A transcript is a
conversation as the page saw it, not as memory digested it: the
conversation_log in blue_memory_improved is one undivided stream that recall
reads from, and the continuity journal keeps episodes, not exchanges.

Each conversation belongs to one robot and one speaker. The page invents the
id when a conversation starts and sends it with every turn; an id that already
belongs to someone else's conversation is refused rather than appended to.

Every message keeps two texts. `content` is what the model was sent (a typed
question with any attached document's text spliced in), so a reopened
conversation continues with the same history it had. `text` is what the page
showed: the words typed or spoken, with attachments listed by name.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = os.environ.get("BLUE_TRANSCRIPTS_DB",
                         os.path.join("data", "chat_transcripts.db"))

# Ids are made by the page (a UUID, or a random fallback on old Safari).
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TITLE_CHARS = 60
_MAX_ATTACHMENTS = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,
    robot TEXT NOT NULL,
    user_name TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transcripts_by_owner
    ON transcripts (robot, user_name, updated_at);

CREATE TABLE IF NOT EXISTS transcript_messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    text TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transcript_messages_by_transcript
    ON transcript_messages (transcript_id, seq);
"""

_ready: set = set()
_lock = threading.Lock()


def _now() -> str:
    # UTC sorts as text and the page reads the offset into local time.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    path = str(DB_PATH)
    if path not in _ready:
        with _lock:
            if path not in _ready:
                folder = os.path.dirname(path)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                with closing(sqlite3.connect(path, timeout=30)) as conn:
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.executescript(_SCHEMA)
                    conn.commit()
                _ready.add(path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def valid_id(conversation_id: Any) -> bool:
    return isinstance(conversation_id, str) and bool(_ID_RE.match(conversation_id))


def _title(text: str, attachments: List[str]) -> str:
    """The first thing said, cut at a word near 60 characters."""
    words = " ".join((text or "").split())
    if not words:
        return attachments[0][:_TITLE_CHARS] if attachments else "Conversation"
    if len(words) <= _TITLE_CHARS:
        return words
    cut = words[:_TITLE_CHARS]
    space = cut.rfind(" ")
    if space > _TITLE_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"


def _names(attachments: Optional[Iterable[Any]]) -> List[str]:
    if not isinstance(attachments, (list, tuple)):
        return []
    return [str(a).strip()[:200] for a in attachments
            if isinstance(a, str) and a.strip()][:_MAX_ATTACHMENTS]


def record_turn(conversation_id: str, robot: str, user_name: str,
                said: str, reply: str, shown: Optional[str] = None,
                attachments: Optional[Iterable[Any]] = None) -> bool:
    """Append one exchange to a conversation, starting it if it is new.

    `said` is the user's message as the model received it and `shown` what
    the page displayed for it (defaults to `said`). False, with nothing
    written, for an unusable id, an empty exchange, or an id that belongs to
    another robot's or another speaker's conversation.
    """
    if not valid_id(conversation_id):
        return False
    if not isinstance(said, str) or not said.strip():
        return False
    if not isinstance(reply, str) or not reply.strip():
        return False
    shown = said if not isinstance(shown, str) else shown
    names = _names(attachments)
    now = _now()
    with closing(_connect()) as conn, conn:
        owner = conn.execute(
            "SELECT robot, user_name FROM transcripts WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if owner is None:
            conn.execute(
                "INSERT INTO transcripts (id, robot, user_name, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, robot, user_name, _title(shown, names), now, now),
            )
        elif (owner["robot"], owner["user_name"]) != (robot, user_name):
            return False
        else:
            conn.execute("UPDATE transcripts SET updated_at = ? WHERE id = ?",
                         (now, conversation_id))
        conn.executemany(
            "INSERT INTO transcript_messages "
            "(transcript_id, role, content, text, attachments, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (conversation_id, "user", said, shown, json.dumps(names), now),
                (conversation_id, "assistant", reply, reply, "[]", now),
            ],
        )
    return True


def list_transcripts(robot: str, user_name: str, limit: int = 500) -> List[Dict[str, Any]]:
    """One speaker's conversations with one robot, most recently spoken in
    first. Ordered by the last message, not updated_at: two turns in the
    same second would tie on the timestamp."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT t.id, t.title, t.created_at, t.updated_at, "
            "       (SELECT COUNT(*) FROM transcript_messages m "
            "        WHERE m.transcript_id = t.id AND m.role = 'user') AS turns, "
            "       (SELECT MAX(seq) FROM transcript_messages m "
            "        WHERE m.transcript_id = t.id) AS last_seq "
            "FROM transcripts t WHERE t.robot = ? AND t.user_name = ? "
            "ORDER BY last_seq DESC LIMIT ?",
            (robot, user_name, max(1, int(limit))),
        ).fetchall()
    return [{k: row[k] for k in ("id", "title", "created_at", "updated_at", "turns")}
            for row in rows]


def get_transcript(conversation_id: str, robot: str,
                   user_name: str) -> Optional[Dict[str, Any]]:
    """The whole conversation, or None if it is not this speaker's."""
    if not valid_id(conversation_id):
        return None
    with closing(_connect()) as conn:
        head = conn.execute(
            "SELECT id, title, created_at, updated_at FROM transcripts "
            "WHERE id = ? AND robot = ? AND user_name = ?",
            (conversation_id, robot, user_name),
        ).fetchone()
        if head is None:
            return None
        rows = conn.execute(
            "SELECT role, content, text, attachments, created_at "
            "FROM transcript_messages WHERE transcript_id = ? ORDER BY seq",
            (conversation_id,),
        ).fetchall()
    messages = []
    for row in rows:
        try:
            names = json.loads(row["attachments"] or "[]")
        except ValueError:
            names = []
        messages.append({
            "role": row["role"],
            "content": row["content"],
            "text": row["text"],
            "attachments": names if isinstance(names, list) else [],
            "at": row["created_at"],
        })
    return {**dict(head), "messages": messages}


def delete_transcript(conversation_id: str, robot: str, user_name: str) -> bool:
    """Remove a conversation for good. False if it is not this speaker's."""
    if not valid_id(conversation_id):
        return False
    with closing(_connect()) as conn, conn:
        gone = conn.execute(
            "DELETE FROM transcripts WHERE id = ? AND robot = ? AND user_name = ?",
            (conversation_id, robot, user_name),
        ).rowcount
        if gone:
            conn.execute("DELETE FROM transcript_messages WHERE transcript_id = ?",
                         (conversation_id,))
    return bool(gone)
