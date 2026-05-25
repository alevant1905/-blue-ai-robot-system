"""Proactive alert queue + heartbeat scanner.

Blue is reactive by default — he only speaks when the Ohbot client posts to
him. This module makes him agentic *to the extent possible without modifying
the Ohbot client*: a background thread scans the reminders DB every minute
and pushes alerts onto a queue. The next time Ohbot calls in, the response
path drains the queue and prepends the alerts to Blue's reply, so the user
hears them via Ohbot's normal TTS path.

Tradeoff: not truly proactive — alerts wait for the next inbound turn. If
the user never speaks, alerts pile up. For a "Blue speaks first" channel,
the Ohbot client would need a callback or polling endpoint.
"""

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional


# Reuse the SQLite path/lock from the enhanced module so both halves see the
# same reminders DB without duplicating connection setup. occurrences_in_window
# expands recurring reminders and applies durations — the single source of
# truth for "what's on the schedule".
from blue_tools_enhanced import (
    _DB_PATH, _DB_LOCK, occurrences_in_window, archive_past_oneoffs,
)


# ===== Config =====

ALERT_WINDOW_MIN = int(os.environ.get("BLUE_PROACTIVE_WINDOW_MIN", "15"))
HEARTBEAT_PERIOD_SEC = int(os.environ.get("BLUE_PROACTIVE_PERIOD_SEC", "60"))
# Quiet hours as (start_hour, end_hour). Wraps around midnight if start > end.
_QH_START = int(os.environ.get("BLUE_PROACTIVE_QUIET_START", "23"))
_QH_END = int(os.environ.get("BLUE_PROACTIVE_QUIET_END", "6"))

# Email-fire path: when a reminder comes due, send an email to this address.
# Independent of the in-memory queue / Ohbot path — works without the user
# ever talking to Blue. Set BLUE_REMINDER_EMAIL='' to disable.
REMINDER_EMAIL = os.environ.get("BLUE_REMINDER_EMAIL", "alevant1905@gmail.com")
# Only fire emails if the reminder is due within this many seconds of now.
# Tighter than the queue window so emails come AT the due time, not 15 min
# early. The lower bound also caps how far back we'll fire after a restart —
# anything older than this is marked alerted silently to avoid spam.
EMAIL_WINDOW_SEC = int(os.environ.get("BLUE_REMINDER_EMAIL_WINDOW_SEC", "120"))
# How long after the due time we still send (covers heartbeat gaps + brief
# downtime). Anything older than this gets silently marked alerted_email=1.
EMAIL_GRACE_SEC = int(os.environ.get("BLUE_REMINDER_EMAIL_GRACE_SEC", "600"))


def _in_quiet_hours(now: datetime) -> bool:
    h = now.hour
    if _QH_START < _QH_END:
        return _QH_START <= h < _QH_END
    return h >= _QH_START or h < _QH_END


# ===== Queue =====

class ProactiveQueue:
    """Thread-safe FIFO of pending alert strings, with per-source dedup.

    Dedup keys (e.g. 'reminder:42') prevent the same upcoming reminder from
    being queued every heartbeat tick. The set is in-memory; on restart all
    in-window reminders re-fire once, which is intentional — better noisy
    than silent after a crash.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._messages: List[Dict] = []
        self._alerted_keys: set = set()

    def push(self, text: str, key: str) -> bool:
        with self._lock:
            if key in self._alerted_keys:
                return False
            self._alerted_keys.add(key)
            self._messages.append({
                "text": text,
                "key": key,
                "queued_at": datetime.now().isoformat(timespec="seconds"),
            })
            return True

    def drain(self) -> List[str]:
        with self._lock:
            msgs = [m["text"] for m in self._messages]
            self._messages = []
            return msgs

    def reset_dedup(self, key: str) -> None:
        with self._lock:
            self._alerted_keys.discard(key)

    def stats(self) -> Dict:
        with self._lock:
            return {
                "pending": len(self._messages),
                "alerted_keys": len(self._alerted_keys),
            }


QUEUE = ProactiveQueue()


# ===== Scanners =====

def _scan_reminders(now: datetime) -> int:
    """Push alerts for any unfinished reminder due within the alert window.

    Skips reminders that have already been delivered by email — otherwise
    Blue would verbally announce a reminder that already landed in the
    user's inbox.
    """
    cutoff = now + timedelta(minutes=ALERT_WINDOW_MIN)
    with _DB_LOCK:
        c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
        try:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT id, user_name, title, when_iso "
                "FROM reminders "
                "WHERE completed = 0 AND alerted_email = 0 "
                "AND (recurrence IS NULL OR recurrence = '') "
                "AND when_iso <= ? AND when_iso >= ? "
                "ORDER BY when_iso",
                (cutoff.isoformat(timespec="minutes"),
                 (now - timedelta(minutes=2)).isoformat(timespec="minutes")),
            ).fetchall()
        finally:
            c.close()

    pushed = 0
    for r in rows:
        try:
            when = datetime.fromisoformat(r["when_iso"])
        except ValueError:
            continue
        delta_min = int((when - now).total_seconds() / 60)
        title = r["title"]
        who = r["user_name"]
        if delta_min <= 0:
            text = f"Heads up, {who} — '{title}' is starting now."
        elif delta_min == 1:
            text = f"Heads up, {who} — '{title}' in 1 minute."
        else:
            text = f"Heads up, {who} — '{title}' in {delta_min} minutes."
        if QUEUE.push(text, key=f"reminder:{r['id']}"):
            pushed += 1
    return pushed


# ===== Email scanner =====

def _build_email_body(user_name: str, title: str, when: datetime,
                      description: Optional[str]) -> str:
    when_human = when.strftime("%A %b %d at %I:%M %p").lstrip("0")
    lines = [
        f"Hi {user_name},",
        "",
        f"This is your reminder: {title}",
        f"Scheduled for: {when_human}",
    ]
    if description:
        lines += ["", description.strip()]
    lines += ["", "— Blue"]
    return "\n".join(lines)


def _mark_alerted(reminder_id: int) -> None:
    with _DB_LOCK:
        c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
        try:
            c.execute(
                "UPDATE reminders SET alerted_email = 1 WHERE id = ?",
                (reminder_id,),
            )
            c.commit()
        finally:
            c.close()


def _send_reminder_email(row) -> bool:
    """Send one reminder email. Returns True on success.

    Lazy imports Gmail bits from bluetools — that module imports this one,
    so we can't import at module top without a cycle.
    """
    try:
        from bluetools import get_gmail_service, GMAIL_AVAILABLE
    except Exception as e:
        print(f"[REMINDER-EMAIL] gmail import failed: {e}", flush=True)
        return False
    if not GMAIL_AVAILABLE:
        return False
    try:
        service = get_gmail_service()
        if service is None:
            return False
        try:
            when = datetime.fromisoformat(row["when_iso"])
        except ValueError:
            when = datetime.now()
        body = _build_email_body(
            row["user_name"], row["title"], when, row["description"],
        )
        from email.mime.text import MIMEText
        import base64 as _b64
        msg = MIMEText(body, "plain")
        msg["To"] = REMINDER_EMAIL
        msg["Subject"] = f"Reminder: {row['title']}"
        raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me", body={"raw": raw},
        ).execute()
        return True
    except Exception as e:
        print(f"[REMINDER-EMAIL] send failed for id={row['id']}: {e}",
              flush=True)
        return False


def _scan_reminders_email(now: datetime) -> int:
    """Fire emails for any due, un-alerted reminder within the window."""
    if not REMINDER_EMAIL:
        return 0
    lower = now - timedelta(seconds=EMAIL_GRACE_SEC)
    upper = now + timedelta(seconds=EMAIL_WINDOW_SEC)
    with _DB_LOCK:
        c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
        try:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT id, user_name, title, when_iso, description "
                "FROM reminders "
                "WHERE completed = 0 AND alerted_email = 0 "
                "AND (recurrence IS NULL OR recurrence = '') "
                "AND when_iso <= ?",
                (upper.isoformat(timespec="minutes"),),
            ).fetchall()
        finally:
            c.close()

    sent = 0
    for r in rows:
        try:
            when = datetime.fromisoformat(r["when_iso"])
        except ValueError:
            # Bad timestamp — mark alerted so we don't retry forever.
            _mark_alerted(r["id"])
            continue
        if when < lower:
            # Past the grace window — silently mark alerted to avoid a
            # spam dump after server downtime.
            _mark_alerted(r["id"])
            print(
                f"[REMINDER-EMAIL] stale (skip): id={r['id']} "
                f"when={r['when_iso']}",
                flush=True,
            )
            continue
        if _send_reminder_email(r):
            _mark_alerted(r["id"])
            sent += 1
            print(
                f"[REMINDER-EMAIL] sent: id={r['id']} '{r['title']}' -> "
                f"{REMINDER_EMAIL}",
                flush=True,
            )
    return sent


# ===== Heartbeat =====

_started = False


def heartbeat_loop():
    while True:
        try:
            now = datetime.now()
            if not _in_quiet_hours(now):
                pushed = _scan_reminders(now)
                if pushed:
                    print(f"[PROACTIVE] queued {pushed} alert(s)", flush=True)
            # Email path runs even during quiet hours — silent delivery,
            # no interruption, so the user still gets the reminder.
            sent = _scan_reminders_email(now)
            if sent:
                print(f"[PROACTIVE] emailed {sent} reminder(s)", flush=True)
            # Backstop: retire one-off reminders whose time has fully passed so
            # they can't linger as 'active' or resurface in any view.
            archived = archive_past_oneoffs(now)
            if archived:
                print(f"[PROACTIVE] archived {archived} past reminder(s)", flush=True)
        except Exception as e:
            print(f"[PROACTIVE] heartbeat error: {e}", flush=True)
        # Keep the Ohbot .ocf conversation file from growing unbounded —
        # rate-limited internally, so this is a cheap no-op most ticks.
        try:
            import blue_ocf
            blue_ocf.compact_ocf_if_due()
        except Exception as e:
            print(f"[OCF] heartbeat compaction error: {e}", flush=True)
        time.sleep(HEARTBEAT_PERIOD_SEC)


def start() -> None:
    """Start the heartbeat thread. Idempotent — safe to call twice."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(
        target=heartbeat_loop,
        daemon=True,
        name="proactive-heartbeat",
    )
    t.start()
    email_status = (
        f"email -> {REMINDER_EMAIL}" if REMINDER_EMAIL else "email disabled"
    )
    print(
        f"[OK] Proactive heartbeat started "
        f"(check {HEARTBEAT_PERIOD_SEC}s, queue-window {ALERT_WINDOW_MIN}min, "
        f"quiet {_QH_START:02d}:00-{_QH_END:02d}:00, {email_status})",
        flush=True,
    )


def drain_for_response() -> str:
    """Drain queued alerts into a single string. Empty if none pending."""
    msgs = QUEUE.drain()
    return " ".join(msgs) if msgs else ""


# ===== Daily briefing + conflict detection =====

# Persisted so the briefing fires at most once per calendar day and survives
# a server restart — an in-memory flag would re-brief after every restart,
# and the user restarts often.
_STATE_PATH = os.path.join(os.path.dirname(_DB_PATH), "proactive_state.json")
_STATE_LOCK = threading.Lock()

# Point-in-time reminders scheduled within this many minutes of each other
# are treated as a clash. Events that have both a start and an end time use
# true interval overlap instead, so this gap only applies to bare reminders.
CONFLICT_GAP_MIN = int(os.environ.get("BLUE_CONFLICT_GAP_MIN", "30"))


def _load_state() -> Dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _save_state(state: Dict) -> None:
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as e:
        print(f"[PROACTIVE] state save failed: {e}", flush=True)


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _fmt_occurrence(occ: Dict) -> str:
    """'Title from 4:00 PM to 7:00 PM', or 'Title at 10:30 AM' when it has
    no end time."""
    start = _fmt_time(occ["start"])
    if occ.get("end"):
        return f"{occ['title']} from {start} to {_fmt_time(occ['end'])}"
    return f"{occ['title']} at {start}"


def detect_conflicts(occurrences, gap_min: int = CONFLICT_GAP_MIN) -> List:
    """Find clashing occurrences.

    Each input is an occurrence dict (see occurrences_in_window) with a
    datetime `start` and a datetime-or-None `end`. Two occurrences clash if
    their time intervals truly overlap; two point-in-time reminders also
    clash if scheduled within gap_min of each other. Near-duplicate titles
    (the same event entered twice) are skipped. Returns (occ_a, occ_b,
    phrase) tuples where phrase describes the clash.
    """
    items = sorted(occurrences, key=lambda o: o["start"])
    conflicts: List = []
    for i in range(len(items)):
        a = items[i]
        a_end = a["end"] or a["start"]
        for j in range(i + 1, len(items)):
            b = items[j]
            b_end = b["end"] or b["start"]
            # items are start-sorted — once b begins beyond a's reach, stop.
            if b["start"] > a_end + timedelta(minutes=gap_min):
                break
            n1, n2 = _norm_title(a["title"]), _norm_title(b["title"])
            if n1 and n2 and (n1 == n2 or n1 in n2 or n2 in n1):
                continue  # same event entered twice — a duplicate, not a clash
            if a["start"] < b_end and b["start"] < a_end:
                conflicts.append((a, b, "overlap on your schedule"))
            elif a["end"] is None and b["end"] is None:
                gap = int(round((b["start"] - a["start"]).total_seconds() / 60))
                if gap <= 0:
                    conflicts.append((a, b, "are scheduled at the same time"))
                elif gap <= gap_min:
                    conflicts.append((a, b, f"are only {gap} min apart"))
    return conflicts


def build_daily_briefing(now: datetime) -> str:
    """A plain-language rundown of what's left on today's schedule, with any
    overlaps or close-together items flagged. Returns '' when nothing is
    scheduled. Weekly recurring events (a class, a standing practice) are
    expanded onto today by occurrences_in_window, so they appear here too.
    """
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    occs = occurrences_in_window(now, end_of_day)
    if not occs:
        return ""

    items = [_fmt_occurrence(o) for o in occs]
    if len(items) == 1:
        parts = [f"Here's your day — one thing on the calendar: {items[0]}."]
    else:
        parts = [
            f"Here's your day — {len(items)} things on the calendar: "
            + "; ".join(items) + "."
        ]
    for a, b, phrase in detect_conflicts(occs):
        parts.append(
            f"Heads up — \"{a['title']}\" and \"{b['title']}\" {phrase}."
        )
    return " ".join(parts)


def daily_briefing_if_due() -> str:
    """Return the daily briefing the first time it's requested each calendar
    day, '' otherwise. The date is persisted so a restart doesn't re-brief,
    and the day is marked done even when the briefing is empty so a quiet
    morning doesn't trigger a stale briefing in the afternoon."""
    now = datetime.now()
    today = now.date().isoformat()
    with _STATE_LOCK:
        state = _load_state()
        if state.get("last_briefing_date") == today:
            return ""
        briefing = build_daily_briefing(now)
        state["last_briefing_date"] = today
        _save_state(state)
    if briefing:
        print(f"[PROACTIVE] daily briefing delivered ({len(briefing)} chars)",
              flush=True)
    return briefing


__all__ = [
    "QUEUE", "ProactiveQueue",
    "start", "drain_for_response",
    "detect_conflicts", "build_daily_briefing", "daily_briefing_if_due",
    "ALERT_WINDOW_MIN", "HEARTBEAT_PERIOD_SEC", "CONFLICT_GAP_MIN",
]
