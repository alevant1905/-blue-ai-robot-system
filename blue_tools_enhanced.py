"""Backing implementation for the enhanced tool family used by bluetools.py.

Exposes 10 manager classes whose static methods are invoked from
bluetools.py:_execute_tool_internal via Manager.method(**tool_args).
Storage: SQLite at data/enhanced.db. Created on first call.
"""

import os
import re
import json
import math
import sqlite3
import threading
import subprocess
import platform
import shutil
import glob as _glob
from datetime import datetime, date, time, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from dateutil import parser as _dateutil_parser
    from dateutil.relativedelta import relativedelta as _relativedelta
    from dateutil.rrule import (
        rrule as _rrule, DAILY as _FREQ_DAILY, WEEKLY as _FREQ_WEEKLY,
        MONTHLY as _FREQ_MONTHLY, YEARLY as _FREQ_YEARLY,
    )
    _HAS_DATEUTIL = True
except ImportError:
    _HAS_DATEUTIL = False

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    from PIL import ImageGrab
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ===== Storage =====

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_DB_PATH = os.path.join(_DB_DIR, "enhanced.db")
_DB_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    os.makedirs(_DB_DIR, exist_ok=True)
    c = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    with _DB_LOCK, _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                title TEXT NOT NULL,
                when_iso TEXT NOT NULL,
                description TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                alerted_email INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                end_iso TEXT,
                recurrence TEXT
            );
            CREATE INDEX IF NOT EXISTS reminders_user_when
                ON reminders(user_name, when_iso);

            -- Per-occurrence alert ledger. A one-off reminder alerts once; a
            -- recurring reminder alerts once PER occurrence, so a row-level
            -- flag isn't enough. (reminder_id, occurrence_iso, channel) is the
            -- idempotency key the heartbeat checks before firing.
            CREATE TABLE IF NOT EXISTS reminder_alerts (
                reminder_id INTEGER NOT NULL,
                occurrence_iso TEXT NOT NULL,
                channel TEXT NOT NULL,
                alerted_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (reminder_id, occurrence_iso, channel)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                category TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS tasks_user_status
                ON tasks(user_name, status);

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS notes_user
                ON notes(user_name);
        """)


_init_db()


def _migrate_reminders_columns() -> None:
    """Add columns introduced after the original reminders schema.

    `CREATE TABLE IF NOT EXISTS` doesn't add columns to an existing table,
    so on upgrade they're missing. ALTER TABLE ADD COLUMN is safe and
    idempotent per column — a re-run raises OperationalError ('duplicate
    column'), which we swallow. `end_iso` gives reminders a duration so
    conflict detection can do true overlap; `recurrence` ('weekly' or NULL)
    lets a single row stand for a repeating event.
    """
    for stmt in (
        "ALTER TABLE reminders ADD COLUMN alerted_email INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE reminders ADD COLUMN end_iso TEXT",
        "ALTER TABLE reminders ADD COLUMN recurrence TEXT",
        # Lead time: minutes BEFORE the start to fire the alert (0 = at start).
        "ALTER TABLE reminders ADD COLUMN remind_before_min INTEGER NOT NULL DEFAULT 0",
        # Optional end date for a recurrence ('every Monday until 2026-12-31').
        "ALTER TABLE reminders ADD COLUMN until_iso TEXT",
    ):
        try:
            with _DB_LOCK, _conn() as c:
                c.execute(stmt)
        except sqlite3.OperationalError:
            pass


_migrate_reminders_columns()


# ===== Natural language time parsing =====
# Accepts the phrasing in the create_reminder schema:
#   "tomorrow at 3pm", "in 2 hours", "next Monday at 9am", "tonight"
# plus ISO/common formats as a final fallback via dateutil.

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_clock(raw: str) -> Optional[time]:
    """Parse '3pm', '15:30', '9 am', '7:45pm' etc. to a time object."""
    s = raw.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", s)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2)) if m.group(2) else 0
    suffix = m.group(3)
    if suffix == "pm" and h < 12:
        h += 12
    elif suffix == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return time(hour=h, minute=mi)


def _next_weekday(target_idx: int, base: datetime) -> date:
    """The next FUTURE occurrence of a weekday (never today)."""
    days_ahead = (target_idx - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (base + timedelta(days=days_ahead)).date()


def _prev_weekday(target_idx: int, base: datetime) -> date:
    """The most recent PAST occurrence of a weekday (never today)."""
    days_behind = (base.weekday() - target_idx) % 7
    if days_behind == 0:
        days_behind = 7
    return (base - timedelta(days=days_behind)).date()


def _this_weekday(target_idx: int, base: datetime) -> date:
    """The weekday within the CURRENT (Mon–Sun) week — may be past or future."""
    monday = base.date() - timedelta(days=base.weekday())
    return monday + timedelta(days=target_idx)


# Past/relative cues that, if they survive to the dateutil fallback, mean we
# failed to resolve them — dateutil silently ignores these words and fabricates
# a (usually wrong) date, so we refuse rather than guess.
_PAST_CUE_RE = re.compile(r"\b(last|previous|prev|ago|yesterday)\b")


def parse_when(raw: str, now: Optional[datetime] = None) -> datetime:
    """Parse a natural-language time string to a datetime. Raises on failure.

    Handles relative days (today/tomorrow/yesterday), qualified weekdays
    (next/this/last <weekday>), "in N units", and explicit dates. Never
    silently resolves a past-reference phrase to a future date.
    """
    if not raw or not raw.strip():
        raise ValueError("empty time string")
    now = now or datetime.now()
    s = raw.strip().lower()

    if s in ("now", "right now"):
        return now

    if s == "tonight":
        return datetime.combine(now.date(), time(20, 0))
    if s == "this morning":
        return datetime.combine(now.date(), time(9, 0))
    if s == "this afternoon":
        return datetime.combine(now.date(), time(14, 0))
    if s == "this evening":
        return datetime.combine(now.date(), time(18, 0))

    m = re.match(r"^in\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)$", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(("sec",)):
            return now + timedelta(seconds=n)
        if unit.startswith(("min",)):
            return now + timedelta(minutes=n)
        if unit.startswith(("hour", "hr")):
            return now + timedelta(hours=n)
        if unit.startswith("day"):
            return now + timedelta(days=n)
        if unit.startswith("week"):
            return now + timedelta(weeks=n)

    m = re.match(r"^(today|tomorrow|tonight|yesterday)(?:\s+at\s+(.+))?$", s)
    if m:
        word = m.group(1)
        clock_raw = m.group(2)
        if word == "tonight":
            base = now.date()
            t = _parse_clock(clock_raw) if clock_raw else time(20, 0)
        elif word == "today":
            base = now.date()
            t = _parse_clock(clock_raw) if clock_raw else time(9, 0)
        elif word == "tomorrow":
            base = now.date() + timedelta(days=1)
            t = _parse_clock(clock_raw) if clock_raw else time(9, 0)
        else:  # yesterday
            base = now.date() - timedelta(days=1)
            t = _parse_clock(clock_raw) if clock_raw else time(9, 0)
        if t is None:
            raise ValueError(f"could not parse clock from {clock_raw!r}")
        return datetime.combine(base, t)

    # Qualified weekdays. Order in the alternation matters: multi-word
    # qualifiers ("this coming") must precede their single-word prefixes.
    m = re.match(
        r"^(?:(last|previous|past|this coming|this|next|coming|on)\s+)?"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"(?:\s+at\s+(.+))?$",
        s,
    )
    if m:
        qualifier = (m.group(1) or "").strip()
        day_name = m.group(2)
        clock_raw = m.group(3)
        target = _DAY_NAMES.index(day_name)
        if qualifier in ("last", "previous", "past"):
            target_date = _prev_weekday(target, now)
        elif qualifier == "this":
            target_date = _this_weekday(target, now)
        else:  # "", "on", "next", "coming", "this coming" → upcoming
            target_date = _next_weekday(target, now)
        t = _parse_clock(clock_raw) if clock_raw else time(9, 0)
        if t is None:
            raise ValueError(f"could not parse clock from {clock_raw!r}")
        return datetime.combine(target_date, t)

    if _HAS_DATEUTIL:
        # If a past/relative cue is still present here, we didn't resolve it
        # above — dateutil would ignore the word and invent a date. Refuse.
        if _PAST_CUE_RE.search(s):
            raise ValueError(
                f"ambiguous past-relative time {raw!r}; give a specific date "
                f"(e.g. 'May 18 at 10am')"
            )
        try:
            # Default with zeroed minutes/seconds so a time that only states
            # the hour ('10am') doesn't inherit the current minute.
            default = now.replace(hour=9, minute=0, second=0, microsecond=0)
            return _dateutil_parser.parse(raw, fuzzy=True, default=default)
        except (ValueError, OverflowError) as e:
            raise ValueError(f"could not parse {raw!r}: {e}")
    raise ValueError(f"could not parse {raw!r}")


# ===== Recurrence model =====
# A reminder's `recurrence` column holds a small canonical string:
#   ""/None        one-off
#   "daily"        every day            "daily:2"   every 2 days
#   "weekly"       every week (on the reference weekday)   "weekly:2" biweekly
#   "monthly"      every month (same day-of-month)         "monthly:3" quarterly
#   "yearly"       every year
#   "weekdays"     Mon–Fri              "weekends"  Sat+Sun
#   "dow:0,2,4"    specific weekdays (0=Mon … 6=Sun); optional ":N" week interval
# `until_iso` (separate column) optionally bounds when the recurrence stops.

_WEEKLY = "weekly"  # legacy value still stored on older rows

_WEEKDAY_NAME = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]
_WEEKDAY_IDX = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "weds": 2, "thursday": 3, "thu": 3,
    "thurs": 3, "thur": 3, "friday": 4, "fri": 4, "saturday": 5,
    "sat": 5, "sunday": 6, "sun": 6,
}


def _parse_recurrence(rec: Optional[str]) -> Optional[Dict[str, Any]]:
    """Normalize a recurrence string into a spec, or None for one-off.

    spec = {freq: 'daily'|'weekly'|'monthly'|'yearly', interval: int,
            byweekday: list[int] | None}
    Unknown strings return None (treated as one-off) rather than raising.
    """
    if not rec:
        return None
    r = rec.strip().lower()
    if r in ("", "none", "once", "one-off", "oneoff", "no", "never"):
        return None
    if r in ("weekdays", "weekday"):
        return {"freq": "weekly", "interval": 1, "byweekday": [0, 1, 2, 3, 4]}
    if r in ("weekends", "weekend"):
        return {"freq": "weekly", "interval": 1, "byweekday": [5, 6]}
    if r in ("annually", "annual"):
        return {"freq": "yearly", "interval": 1, "byweekday": None}
    m = re.match(r"^(daily|weekly|monthly|yearly)(?::(\d+))?$", r)
    if m:
        return {"freq": m.group(1),
                "interval": max(1, int(m.group(2) or 1)),
                "byweekday": None}
    m = re.match(r"^dow:([0-6](?:,[0-6])*)(?::(\d+))?$", r)
    if m:
        days = sorted({int(x) for x in m.group(1).split(",")})
        return {"freq": "weekly",
                "interval": max(1, int(m.group(2) or 1)),
                "byweekday": days}
    return None


def recurrence_label(rec: Optional[str], ref_start: Optional[datetime] = None) -> str:
    """Human phrase for a recurrence string, e.g. 'every Monday', 'every 2
    weeks', 'every weekday', 'monthly'. '' for one-off."""
    spec = _parse_recurrence(rec)
    if spec is None:
        return ""
    n = spec["interval"]
    freq = spec["freq"]
    byday = spec["byweekday"]
    if byday == [0, 1, 2, 3, 4]:
        return "every weekday"
    if byday == [5, 6]:
        return "every weekend"
    if freq == "weekly" and byday:
        names = ", ".join(_WEEKDAY_NAME[d] for d in byday)
        every = "every week" if n == 1 else f"every {n} weeks"
        return f"{every} on {names}"
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[freq]
    if n == 1:
        if freq == "weekly" and ref_start is not None:
            return f"every {_WEEKDAY_NAME[ref_start.weekday()]}"
        return {"daily": "every day", "weekly": "every week",
                "monthly": "every month", "yearly": "every year"}[freq]
    return f"every {n} {unit}s"


def _intersects(start_dt: datetime, end_dt: Optional[datetime],
                window_start: datetime, window_end: datetime) -> bool:
    """True if event [start, end-or-start] overlaps [window_start, window_end]."""
    effective_end = end_dt or start_dt
    return start_dt <= window_end and effective_end >= window_start


def _occurrence(row, start_dt: datetime, end_dt: Optional[datetime],
                recurring: bool) -> Dict[str, Any]:
    # row may be a sqlite Row (no .get); pull optional cols defensively.
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "id": row["id"],
        "user_name": row["user_name"],
        "title": row["title"],
        "description": row["description"] or "",
        "start": start_dt,
        "end": end_dt,
        "recurring": recurring,
        "recurrence": (row["recurrence"] if "recurrence" in keys else None) or "",
        "remind_before_min": (row["remind_before_min"]
                              if "remind_before_min" in keys else 0) or 0,
    }


def _freq_const(freq: str):
    return {"daily": _FREQ_DAILY, "weekly": _FREQ_WEEKLY,
            "monthly": _FREQ_MONTHLY, "yearly": _FREQ_YEARLY}[freq]


def _expand_row(row, window_start: datetime,
                window_end: datetime) -> List[Dict[str, Any]]:
    """Expand one reminder row into the concrete occurrences that fall in
    [window_start, window_end]. One-shot rows yield at most one; recurring
    rows yield every occurrence in the window (via dateutil.rrule)."""
    try:
        ref_start = datetime.fromisoformat(row["when_iso"])
    except (ValueError, TypeError):
        return []
    ref_end = None
    if row["end_iso"]:
        try:
            ref_end = datetime.fromisoformat(row["end_iso"])
        except (ValueError, TypeError):
            ref_end = None
    duration = (ref_end - ref_start) if (ref_end and ref_end > ref_start) else None

    spec = _parse_recurrence(row["recurrence"])
    if spec is None:
        occ_end = (ref_start + duration) if duration else None
        if _intersects(ref_start, occ_end, window_start, window_end):
            return [_occurrence(row, ref_start, occ_end, False)]
        return []

    # Recurrence end bound (optional).
    until_dt = None
    keys = row.keys() if hasattr(row, "keys") else []
    if "until_iso" in keys and row["until_iso"]:
        try:
            until_dt = datetime.fromisoformat(row["until_iso"])
        except (ValueError, TypeError):
            until_dt = None

    occurrences: List[Dict[str, Any]] = []
    if _HAS_DATEUTIL:
        kwargs: Dict[str, Any] = {"dtstart": ref_start, "interval": spec["interval"]}
        if spec["byweekday"] is not None:
            kwargs["byweekday"] = spec["byweekday"]
        if until_dt is not None:
            kwargs["until"] = until_dt
        rule = _rrule(_freq_const(spec["freq"]), **kwargs)
        # Start scanning a duration earlier so a long event that began before
        # the window but still overlaps is included.
        after = window_start - (duration or timedelta()) - timedelta(seconds=1)
        for occ_start in rule.between(after, window_end, inc=True):
            occ_end = (occ_start + duration) if duration else None
            if _intersects(occ_start, occ_end, window_start, window_end):
                occurrences.append(_occurrence(row, occ_start, occ_end, True))
    else:
        # Minimal fallback (weekly only) if dateutil is unavailable.
        if spec["freq"] == "weekly":
            wanted = spec["byweekday"] or [ref_start.weekday()]
            day = window_start.date()
            last = window_end.date()
            while day <= last:
                if day.weekday() in wanted:
                    occ_start = datetime.combine(day, ref_start.time())
                    occ_end = (occ_start + duration) if duration else None
                    if _intersects(occ_start, occ_end, window_start, window_end):
                        occurrences.append(_occurrence(row, occ_start, occ_end, True))
                day += timedelta(days=1)
    return occurrences


def occurrences_in_window(window_start: datetime, window_end: datetime,
                          user_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Concrete reminder occurrences overlapping [window_start, window_end],
    earliest first.

    One-shot reminders appear once; recurring reminders are expanded to every
    occurrence in the window. Each occurrence is a dict with datetime `start`,
    datetime-or-None `end`, plus id/title/description/user_name/recurring/
    recurrence/remind_before_min. This is the single source of truth for
    "what's on the schedule" — the daily briefing, the system-prompt schedule
    block, the calendar GUI, and get_upcoming_reminders all build on it.
    """
    clause = "WHERE completed = 0"
    params: List[Any] = []
    if user_name:
        clause += " AND user_name = ?"
        params.append(user_name)
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT id, user_name, title, description, when_iso, end_iso, "
            "recurrence, remind_before_min, until_iso FROM reminders " + clause,
            params,
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.extend(_expand_row(row, window_start, window_end))
    out.sort(key=lambda o: o["start"])
    return out


# ===== Natural-language recurrence + lead-time parsing =====

def parse_recurrence_phrase(text: Optional[str]) -> Optional[str]:
    """Map a natural-language recurrence phrase to a canonical recurrence
    string (see the recurrence model above). Returns None for one-off / no
    recurrence. Tolerant: unknown phrasing yields None rather than raising."""
    if not text:
        return None
    t = text.strip().lower()
    if t in ("", "none", "once", "one time", "one-time", "no", "never", "no repeat"):
        return None

    # Explicit weekday sets, e.g. "every monday and wednesday", "mon/wed/fri".
    found_days = []
    for name, idx in _WEEKDAY_IDX.items():
        # word-ish boundary so 'sun' doesn't match 'sunday' twice etc.
        if re.search(rf"\b{name}\b", t):
            if idx not in found_days:
                found_days.append(idx)

    if "weekday" in t and "every" in t or t in ("weekdays", "every weekday"):
        return "weekdays"
    if "weekend" in t:
        return "weekends"

    # Explicit weekday SET, e.g. "every monday and wednesday", "mon/wed/fri".
    if len(found_days) >= 2 or (found_days and ("and" in t or "," in t or "/" in t)):
        wk = 1
        mo = re.search(r"every\s+(other|\d+)\s*weeks?", t)
        if mo:
            wk = 2 if mo.group(1) == "other" else max(1, int(mo.group(1)))
        days = ",".join(str(d) for d in sorted(set(found_days)))
        return f"dow:{days}" + (f":{wk}" if wk > 1 else "")

    # General "every [other|N] <unit>" (covers "every other day", "every 2
    # weeks", "every 3 months", etc.).
    interval = 1
    unit = None
    m = re.search(r"every\s+(other\s+|\d+\s*)?(day|week|month|year)s?\b", t)
    if m:
        q = (m.group(1) or "").strip()
        if q == "other":
            interval = 2
        elif q.isdigit():
            interval = max(1, int(q))
        unit = m.group(2)
    if unit is None:
        if re.search(r"\bdaily\b", t):
            unit = "day"
        elif re.search(r"\bweekly\b", t):
            unit = "week"
        elif re.search(r"\bmonthly\b", t):
            unit = "month"
        elif re.search(r"\b(yearly|annually|annual)\b", t):
            unit = "year"
    if unit:
        base = {"day": "daily", "week": "weekly",
                "month": "monthly", "year": "yearly"}[unit]
        return base + (f":{interval}" if interval > 1 else "")

    # A lone weekday with "every" → weekly on that day.
    if found_days and "every" in t:
        return f"dow:{found_days[0]}"
    return None


def normalize_recurrence(text: Optional[str]) -> Optional[str]:
    """Accept either an already-canonical recurrence string (from the GUI) or
    a natural-language phrase (from the LLM) and return the canonical form, or
    None for one-off."""
    if not text:
        return None
    if _parse_recurrence(text) is not None:
        return text.strip().lower()
    return parse_recurrence_phrase(text)


def parse_lead_minutes(text: Optional[str]) -> int:
    """Parse a 'remind me N before' lead time to minutes. 0 if none/at-start.

    Accepts '30 minutes before', '2 hours before', '1 day before', 'a day
    before', '1 week before', 'the day before', etc. Also tolerates a bare
    integer (interpreted as minutes)."""
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return max(0, int(text))
    t = str(text).strip().lower()
    if not t or t in ("0", "at start", "at time", "on time", "none"):
        return 0
    if t.isdigit():
        return int(t)
    units = {"minute": 1, "min": 1, "hour": 60, "hr": 60, "day": 1440,
             "week": 10080}
    m = re.search(r"(\d+)\s*(minute|min|hour|hr|day|week)s?", t)
    if m:
        return int(m.group(1)) * units[m.group(2)]
    # Word quantities: "a/the day before", "an hour before".
    if re.search(r"\b(a|an|the)\s+day\b", t):
        return 1440
    if re.search(r"\b(a|an|the)\s+(hour|hr)\b", t):
        return 60
    if re.search(r"\b(a|an|the)\s+week\b", t):
        return 10080
    return 0


def _humanize_lead(minutes: int) -> str:
    """Minutes → 'the right phrase' for confirmations: '30 minutes', '2 hours',
    '1 day', '1 week'."""
    if minutes <= 0:
        return ""
    if minutes % 10080 == 0:
        n = minutes // 10080
        return f"{n} week" + ("s" if n > 1 else "")
    if minutes % 1440 == 0:
        n = minutes // 1440
        return f"{n} day" + ("s" if n > 1 else "")
    if minutes % 60 == 0:
        n = minutes // 60
        return f"{n} hour" + ("s" if n > 1 else "")
    return f"{minutes} minute" + ("s" if minutes != 1 else "")


def archive_past_oneoffs(now: Optional[datetime] = None,
                         grace_min: int = 120) -> int:
    """Mark one-off reminders whose time has fully passed as completed.

    Past one-offs that linger as completed=0 clutter the table and risk
    resurfacing; archiving them keeps the schedule clean and is the backstop
    that stops a stale reminder from ever being re-announced. Recurring rows
    are exempt (their when_iso is a repeating anchor). The grace window is
    wider than the email scanner's, so a just-due reminder still gets its
    email before this archives it. Returns the number archived.
    """
    now = now or datetime.now()
    cutoff = (now - timedelta(minutes=grace_min)).isoformat(timespec="minutes")
    with _DB_LOCK, _conn() as c:
        cur = c.execute(
            "UPDATE reminders SET completed = 1 "
            "WHERE completed = 0 "
            "AND (recurrence IS NULL OR recurrence = '') "
            "AND COALESCE(NULLIF(end_iso, ''), when_iso) < ?",
            (cutoff,),
        )
        c.commit()
        return cur.rowcount


# ===== Per-occurrence alert ledger =====
# Used by the proactive heartbeat so a recurring event alerts once per
# occurrence (not once ever) and a lead time fires at start - lead.

def is_occurrence_alerted(reminder_id: int, occurrence_iso: str,
                          channel: str) -> bool:
    with _DB_LOCK, _conn() as c:
        row = c.execute(
            "SELECT 1 FROM reminder_alerts "
            "WHERE reminder_id = ? AND occurrence_iso = ? AND channel = ?",
            (reminder_id, occurrence_iso, channel),
        ).fetchone()
    return row is not None


def mark_occurrence_alerted(reminder_id: int, occurrence_iso: str,
                            channel: str) -> None:
    with _DB_LOCK, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO reminder_alerts "
            "(reminder_id, occurrence_iso, channel) VALUES (?, ?, ?)",
            (reminder_id, occurrence_iso, channel),
        )
        c.commit()


def due_occurrence_alerts(now: Optional[datetime] = None, *, channel: str,
                          grace_min: int = 10,
                          horizon_days: int = 8) -> List[Dict[str, Any]]:
    """Occurrences whose alert moment (start - lead) has just arrived and that
    haven't been alerted yet on `channel`.

    The grace window absorbs heartbeat gaps and brief downtime; anything whose
    alert moment is older than that is skipped (no spam after the host was
    off), and since it's never recorded it simply won't fire. Lead times up to
    a week are covered by expanding `horizon_days` ahead.
    """
    now = now or datetime.now()
    lower = now - timedelta(minutes=grace_min)
    occs = occurrences_in_window(
        now - timedelta(minutes=grace_min + 2),
        now + timedelta(days=horizon_days),
    )
    due: List[Dict[str, Any]] = []
    for o in occs:
        lead = int(o.get("remind_before_min") or 0)
        alert_at = o["start"] - timedelta(minutes=lead)
        if lower <= alert_at <= now:
            occ_iso = o["start"].isoformat(timespec="minutes")
            if not is_occurrence_alerted(o["id"], occ_iso, channel):
                o = dict(o)
                o["occurrence_iso"] = occ_iso
                o["alert_at"] = alert_at
                due.append(o)
    return due


# ===== Calendar / Reminders =====

class CalendarManager:
    """Reminders backed by SQLite."""

    @staticmethod
    def create_reminder(user_name: str, title: str, when: str,
                        description: str = "", end: str = "",
                        recurrence: str = "", remind_before: str = "",
                        until: str = "") -> Dict[str, Any]:
        try:
            target = parse_when(when)
        except ValueError as e:
            return {"success": False, "message": f"Could not parse time '{when}': {e}"}

        when_iso = target.isoformat(timespec="minutes")
        now = datetime.now()

        # Optional end time gives the reminder a duration, so conflict
        # detection can spot true overlaps instead of just proximity.
        # Accept a bare clock ("7pm", combined with the start's date) or a
        # full phrase ("wednesday at 7pm").
        end_iso = None
        if end and end.strip():
            end_dt = None
            t = _parse_clock(end.strip())
            if t is not None:
                end_dt = datetime.combine(target.date(), t)
            else:
                try:
                    end_dt = parse_when(end)
                except ValueError:
                    end_dt = None
            if end_dt and end_dt > target:
                end_iso = end_dt.isoformat(timespec="minutes")

        # Recurrence: canonical string (daily/weekly/monthly/yearly/intervals/
        # weekday-sets) or None. Accepts either a natural-language phrase
        # ("every other Monday") or an already-canonical value from the GUI.
        recur = normalize_recurrence(recurrence)
        # Lead time: fire the alert this many minutes before the start.
        lead_min = parse_lead_minutes(remind_before)
        # Optional recurrence end date. Store as end-of-that-day so the final
        # occurrence on that date is still included.
        until_iso = None
        if until and str(until).strip():
            try:
                _u = parse_when(until)
                until_iso = _u.replace(hour=23, minute=59, second=0,
                                       microsecond=0).isoformat(timespec="minutes")
            except ValueError:
                until_iso = None

        # Past-time guard: a one-off reminder resolved to the past would either
        # fire instantly or never — almost always a parse/intent slip (e.g.
        # "last Monday"). Don't silently schedule it; ask the user to confirm a
        # future time. (Weekly rows legitimately anchor on a past reference
        # date, so they're exempt.)
        if recur != "weekly" and target < now - timedelta(minutes=1):
            when_human = target.strftime("%A %b %d, %Y at %I:%M %p").lstrip("0")
            return {
                "success": False,
                "past": True,
                "parsed_when": when_iso,
                "message": (
                    f"That time — {when_human} — is in the past, so I didn't set "
                    f"a reminder. Did you mean an upcoming date?"
                ),
                "_instruction": (
                    f"The requested time, {when_human}, is already in the past. "
                    f"Do NOT claim a reminder was set. Tell the user it's in the "
                    f"past and ask which upcoming date/time they meant (for "
                    f"example the next {target.strftime('%A')}), then call "
                    f"create_reminder again with the corrected time."
                ),
            }

        # Duplicate guard: if an active reminder with the same user + title
        # at the same minute was created in the last 5 minutes, return that
        # one instead of inserting a second. Stops the LLM from creating
        # back-to-back duplicates when a turn loops or the user repeats
        # themselves.
        with _DB_LOCK, _conn() as c:
            five_min_ago = (now - timedelta(minutes=5)).isoformat(
                sep=" ", timespec="seconds")
            dup = c.execute(
                "SELECT id, when_iso FROM reminders "
                "WHERE completed = 0 AND user_name = ? "
                "AND LOWER(title) = LOWER(?) AND when_iso = ? "
                "AND created_at >= ? "
                "ORDER BY id DESC LIMIT 1",
                (user_name, title, when_iso, five_min_ago),
            ).fetchone()
        if dup is not None:
            when_human = target.strftime("%A %b %d, %Y at %I:%M %p").lstrip("0")
            return {
                "success": True,
                "duplicate": True,
                "reminder_id": dup["id"],
                "when": dup["when_iso"],
                "message": (
                    f"Already have that one for {user_name}: '{title}' on "
                    f"{when_human}. Not creating a duplicate."
                ),
                "_instruction": (
                    f"You already created this reminder seconds ago. Tell the "
                    f"user it's set for {when_human} — do not act surprised "
                    f"and do not say you're creating a new one."
                ),
            }

        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                "INSERT INTO reminders "
                "(user_name, title, when_iso, description, end_iso, recurrence, "
                "remind_before_min, until_iso) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_name, title, when_iso, description or None,
                 end_iso, recur, lead_min, until_iso),
            )
            rid = cur.lastrowid

        lead_phrase = ""
        if lead_min:
            lead_phrase = " (reminding you " + _humanize_lead(lead_min) + " before)"

        end_clock = ""
        if end_iso:
            end_clock = " to " + datetime.fromisoformat(end_iso).strftime(
                "%I:%M %p").lstrip("0")

        # Recurring events repeat, so a one-time date would be misleading —
        # confirm them with the repeat phrase ("every Monday", "every weekday",
        # "every 2 weeks", etc.).
        if recur:
            label = recurrence_label(recur, target)
            clock_str = target.strftime("%I:%M %p").lstrip("0")
            until_phrase = ""
            if until_iso:
                until_phrase = " until " + datetime.fromisoformat(
                    until_iso).strftime("%b %d, %Y").lstrip("0")
            when_human = f"{label} at {clock_str}{end_clock}{until_phrase}{lead_phrase}"
            return {
                "success": True,
                "message": (
                    f"Recurring reminder set for {user_name}: '{title}' "
                    f"{when_human}."
                ),
                "reminder_id": rid,
                "when": when_iso,
                "end": end_iso,
                "recurrence": recur,
                "recurrence_human": label,
                "remind_before_min": lead_min,
                "until": until_iso,
                "when_human": when_human,
                "_instruction": (
                    f"Confirm this back to the user: '{title}' is now set to "
                    f"repeat {when_human}. Make clear how often it recurs."
                ),
            }

        delta = target - now
        # Full date + day-of-week + year so the LLM can never paraphrase
        # the date away. Includes the year because users sometimes set
        # things months out and "May 12" is ambiguous across years.
        when_human = target.strftime("%A %b %d, %Y at %I:%M %p").lstrip("0") + end_clock
        # Relative day so the confirmation echoes back the same vocab the
        # user used ("tomorrow", "today", "next Monday").
        days_diff = (target.date() - now.date()).days
        if days_diff == 0:
            rel_day = "today"
        elif days_diff == 1:
            rel_day = "tomorrow"
        elif days_diff == -1:
            rel_day = "yesterday (already past)"
        elif 1 < days_diff <= 7:
            rel_day = f"this coming {target.strftime('%A')}"
        elif days_diff < 0:
            rel_day = f"{abs(days_diff)} days ago (already past)"
        else:
            rel_day = f"in {days_diff} days"
        return {
            "success": True,
            "message": (
                f"Reminder set for {user_name}: '{title}' on {when_human} "
                f"({rel_day}){lead_phrase}."
            ),
            "reminder_id": rid,
            "when": when_iso,
            "end": end_iso,
            "when_human": when_human,
            "relative_day": rel_day,
            "remind_before_min": lead_min,
            "minutes_from_now": int(delta.total_seconds() // 60),
            "_instruction": (
                "Confirm this reminder back to the user with the EXPLICIT day "
                f"and date — say '{rel_day}, {when_human}' (or a natural "
                "rephrasing that keeps both the day-of-week and the date). "
                "Do NOT drop the date. The user needs to hear the date you "
                "picked so they can correct you if you assumed the wrong day."
            ),
        }

    @staticmethod
    def get_upcoming_reminders(user_name: str, hours_ahead: int = 168) -> Dict[str, Any]:
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        # occurrences_in_window expands weekly recurring reminders, so a
        # standing class shows up here just like a one-off.
        items = []
        for o in occurrences_in_window(now, cutoff, user_name=user_name):
            item = {
                "id": o["id"],
                "title": o["title"],
                "when": o["start"].isoformat(timespec="minutes"),
                "description": o["description"],
            }
            if o["end"]:
                item["end"] = o["end"].isoformat(timespec="minutes")
            if o["recurring"]:
                item["recurring"] = True
            items.append(item)
        return {
            "success": True,
            "count": len(items),
            "reminders": items,
            "message": f"{len(items)} upcoming reminder(s) for {user_name} in the next {hours_ahead}h",
        }

    @staticmethod
    def complete_reminder(reminder_id: int) -> Dict[str, Any]:
        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                "UPDATE reminders SET completed = 1 WHERE id = ? AND completed = 0",
                (reminder_id,),
            )
            changed = cur.rowcount
        if changed == 0:
            return {"success": False, "message": f"No active reminder with id {reminder_id}"}
        return {"success": True, "message": f"Reminder {reminder_id} marked complete"}

    @staticmethod
    def cancel_reminder(reminder_id: Optional[int] = None,
                        title_query: Optional[str] = None,
                        user_name: Optional[str] = None) -> Dict[str, Any]:
        """Cancel an upcoming reminder.

        Two modes:
        - By id: pass `reminder_id` directly.
        - By search: pass `title_query` (and optionally `user_name`) and we
          look for an active reminder whose title contains that substring
          (case-insensitive). If exactly one matches, cancel it. If multiple
          match, return them so the caller can disambiguate.

        Cancellation is implemented as `completed = 1` — same as
        `complete_reminder`, since both remove the row from upcoming views.
        """
        if reminder_id is None and not title_query:
            return {"success": False, "message": "Pass reminder_id or title_query"}

        if reminder_id is not None:
            with _DB_LOCK, _conn() as c:
                cur = c.execute(
                    "UPDATE reminders SET completed = 1 "
                    "WHERE id = ? AND completed = 0",
                    (reminder_id,),
                )
                changed = cur.rowcount
            if changed == 0:
                return {"success": False,
                        "message": f"No active reminder with id {reminder_id}"}
            return {"success": True,
                    "message": f"Cancelled reminder {reminder_id}"}

        like = f"%{title_query.strip().lower()}%"
        with _DB_LOCK, _conn() as c:
            if user_name:
                rows = c.execute(
                    "SELECT id, user_name, title, when_iso FROM reminders "
                    "WHERE completed = 0 AND user_name = ? "
                    "AND LOWER(title) LIKE ? "
                    "ORDER BY when_iso ASC",
                    (user_name, like),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT id, user_name, title, when_iso FROM reminders "
                    "WHERE completed = 0 AND LOWER(title) LIKE ? "
                    "ORDER BY when_iso ASC",
                    (like,),
                ).fetchall()

        if not rows:
            return {"success": False,
                    "message": f"No active reminder matching '{title_query}'"}

        if len(rows) > 1:
            matches = [
                {"id": r["id"], "user_name": r["user_name"],
                 "title": r["title"], "when": r["when_iso"]}
                for r in rows
            ]
            return {
                "success": False,
                "needs_disambiguation": True,
                "matches": matches,
                "message": (
                    f"{len(rows)} reminders match '{title_query}'. "
                    "Ask the user which one or call again with reminder_id."
                ),
            }

        rid = rows[0]["id"]
        with _DB_LOCK, _conn() as c:
            c.execute(
                "UPDATE reminders SET completed = 1 WHERE id = ?", (rid,),
            )
        return {
            "success": True,
            "reminder_id": rid,
            "message": f"Cancelled '{rows[0]['title']}'",
        }

    @staticmethod
    def update_reminder(reminder_id: int, title: Optional[str] = None,
                        when: Optional[str] = None, end: Optional[str] = None,
                        description: Optional[str] = None,
                        recurrence: Optional[str] = None,
                        remind_before: Optional[str] = None,
                        until: Optional[str] = None) -> Dict[str, Any]:
        """Edit / reschedule a reminder. Only the fields you pass are changed.
        recurrence='none' makes a repeating event one-off; end='' clears the
        duration; until='' clears the recurrence end. Changing the timing
        re-arms alerts so the new schedule notifies again."""
        with _DB_LOCK, _conn() as c:
            row = c.execute("SELECT * FROM reminders WHERE id = ?",
                            (reminder_id,)).fetchone()
        if row is None:
            return {"success": False, "message": f"No reminder with id {reminder_id}"}

        sets: List[str] = []
        params: List[Any] = []
        rearm = False
        try:
            base_date = datetime.fromisoformat(row["when_iso"]).date()
        except Exception:
            base_date = datetime.now().date()

        if when is not None and str(when).strip():
            try:
                tgt = parse_when(when)
            except ValueError as e:
                return {"success": False,
                        "message": f"Could not parse time '{when}': {e}"}
            sets.append("when_iso = ?")
            params.append(tgt.isoformat(timespec="minutes"))
            base_date = tgt.date()
            rearm = True
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if description is not None:
            sets.append("description = ?")
            params.append(description or None)
        if end is not None:
            if str(end).strip():
                t = _parse_clock(str(end).strip())
                end_dt = datetime.combine(base_date, t) if t is not None else None
                if end_dt is None:
                    try:
                        end_dt = parse_when(end)
                    except ValueError:
                        end_dt = None
                sets.append("end_iso = ?")
                params.append(end_dt.isoformat(timespec="minutes") if end_dt else None)
            else:
                sets.append("end_iso = ?")
                params.append(None)
        if recurrence is not None:
            sets.append("recurrence = ?")
            params.append(normalize_recurrence(recurrence))
            rearm = True
        if remind_before is not None:
            sets.append("remind_before_min = ?")
            params.append(parse_lead_minutes(remind_before))
            rearm = True
        if until is not None:
            if str(until).strip():
                try:
                    u = parse_when(until).replace(hour=23, minute=59, second=0,
                                                  microsecond=0)
                    sets.append("until_iso = ?")
                    params.append(u.isoformat(timespec="minutes"))
                except ValueError:
                    sets.append("until_iso = ?")
                    params.append(None)
            else:
                sets.append("until_iso = ?")
                params.append(None)

        if not sets:
            return {"success": False, "message": "Nothing to update"}
        if rearm:
            sets.append("alerted_email = 0")
        params.append(reminder_id)
        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                f"UPDATE reminders SET {', '.join(sets)} WHERE id = ?", params)
            if rearm:
                c.execute("DELETE FROM reminder_alerts WHERE reminder_id = ?",
                          (reminder_id,))
            c.commit()
            changed = cur.rowcount
        if changed == 0:
            return {"success": False, "message": f"No reminder with id {reminder_id}"}
        return {"success": True, "reminder_id": reminder_id,
                "message": f"Updated reminder {reminder_id}."}

    @staticmethod
    def delete_reminder(reminder_id: int) -> Dict[str, Any]:
        """Permanently delete a reminder (and its alert ledger). Unlike cancel
        (which marks completed), this removes the row entirely — used by the
        calendar GUI's delete action."""
        with _DB_LOCK, _conn() as c:
            cur = c.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            c.execute("DELETE FROM reminder_alerts WHERE reminder_id = ?",
                      (reminder_id,))
            c.commit()
            changed = cur.rowcount
        if changed == 0:
            return {"success": False, "message": f"No reminder with id {reminder_id}"}
        return {"success": True, "message": f"Deleted reminder {reminder_id}."}

    @staticmethod
    def list_events(start: str, end: str,
                    user_name: Optional[str] = None) -> Dict[str, Any]:
        """Occurrences between start and end (ISO or natural language) for the
        calendar GUI. Recurring events are expanded to concrete occurrences."""
        def _coerce(s, default):
            if not s:
                return default
            try:
                return datetime.fromisoformat(s)
            except (ValueError, TypeError):
                try:
                    return parse_when(s)
                except ValueError:
                    return default
        now = datetime.now()
        ws = _coerce(start, now)
        we = _coerce(end, ws + timedelta(days=31))
        events = []
        for o in occurrences_in_window(ws, we, user_name=user_name):
            events.append({
                "id": o["id"],
                "title": o["title"],
                "start": o["start"].isoformat(timespec="minutes"),
                "end": o["end"].isoformat(timespec="minutes") if o["end"] else None,
                "description": o["description"],
                "recurring": o["recurring"],
                "recurrence": o.get("recurrence") or "",
                "recurrence_human": recurrence_label(o.get("recurrence"), o["start"]),
                "remind_before_min": o.get("remind_before_min") or 0,
            })
        return {"success": True, "count": len(events), "events": events}


# ===== Tasks =====

class TaskManager:
    """Tasks/to-dos backed by SQLite."""

    @staticmethod
    def create_task(user_name: str, title: str, description: str = "",
                    priority: str = "medium", due_date: str = "",
                    category: str = "") -> Dict[str, Any]:
        priority = (priority or "medium").lower()
        if priority not in ("low", "medium", "high"):
            priority = "medium"

        due_iso = None
        if due_date:
            try:
                due_iso = parse_when(due_date).isoformat(timespec="minutes")
            except ValueError:
                due_iso = due_date

        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                "INSERT INTO tasks (user_name, title, description, priority, "
                "due_date, category) VALUES (?, ?, ?, ?, ?, ?)",
                (user_name, title, description or None, priority,
                 due_iso, category or None),
            )
            tid = cur.lastrowid
        return {
            "success": True,
            "message": f"Task created for {user_name}: '{title}'",
            "task_id": tid,
            "priority": priority,
            "due_date": due_iso,
        }

    @staticmethod
    def get_tasks(user_name: str, status: str = "pending") -> Dict[str, Any]:
        status = (status or "pending").lower()
        if status not in ("pending", "completed"):
            status = "pending"
        with _DB_LOCK, _conn() as c:
            rows = c.execute(
                "SELECT id, title, description, priority, due_date, category, "
                "       status, created_at, completed_at "
                "FROM tasks WHERE user_name = ? AND status = ? "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' "
                "         THEN 1 ELSE 2 END, COALESCE(due_date, created_at) ASC",
                (user_name, status),
            ).fetchall()
        items = [dict(r) for r in rows]
        return {
            "success": True,
            "count": len(items),
            "tasks": items,
            "message": f"{len(items)} {status} task(s) for {user_name}",
        }

    @staticmethod
    def complete_task(task_id: int) -> Dict[str, Any]:
        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                "UPDATE tasks SET status = 'completed', "
                "completed_at = datetime('now') "
                "WHERE id = ? AND status = 'pending'",
                (task_id,),
            )
            changed = cur.rowcount
        if changed == 0:
            return {"success": False, "message": f"No pending task with id {task_id}"}
        return {"success": True, "message": f"Task {task_id} marked complete"}


# ===== Notes =====

class NoteManager:
    """Free-form notes backed by SQLite. Search is keyword LIKE."""

    @staticmethod
    def create_note(user_name: str, title: str, content: str,
                    category: str = "") -> Dict[str, Any]:
        with _DB_LOCK, _conn() as c:
            cur = c.execute(
                "INSERT INTO notes (user_name, title, content, category) "
                "VALUES (?, ?, ?, ?)",
                (user_name, title, content, category or None),
            )
            nid = cur.lastrowid
        return {
            "success": True,
            "message": f"Note saved for {user_name}: '{title}'",
            "note_id": nid,
        }

    @staticmethod
    def search_notes(user_name: str, query: str) -> Dict[str, Any]:
        like = f"%{query}%"
        with _DB_LOCK, _conn() as c:
            rows = c.execute(
                "SELECT id, title, content, category, created_at FROM notes "
                "WHERE user_name = ? AND (title LIKE ? OR content LIKE ? "
                "      OR COALESCE(category,'') LIKE ?) "
                "ORDER BY created_at DESC LIMIT 20",
                (user_name, like, like, like),
            ).fetchall()
        items = [dict(r) for r in rows]
        return {
            "success": True,
            "count": len(items),
            "results": items,
            "message": f"{len(items)} note(s) matching '{query}' for {user_name}",
        }


# ===== Timers =====

class TimerManager:
    """In-memory countdown timers using threading.Timer.

    State lives in process memory; check_timers reports remaining time.
    On expiry, prints a notice (and optionally a desktop notification via
    plyer if available).
    """

    _lock = threading.Lock()
    _next_id = 1
    _active: Dict[int, Dict[str, Any]] = {}

    @staticmethod
    def _on_expire(timer_id: int) -> None:
        with TimerManager._lock:
            entry = TimerManager._active.pop(timer_id, None)
        if not entry:
            return
        label = entry.get("label") or f"timer #{timer_id}"
        print(f"[TIMER] Expired: {label} (id {timer_id})")
        try:
            from plyer import notification
            notification.notify(title="Timer", message=label, timeout=5)
        except Exception:
            pass

    @staticmethod
    def set_timer(duration_minutes: int, label: str = "") -> Dict[str, Any]:
        try:
            secs = int(float(duration_minutes) * 60)
        except (TypeError, ValueError):
            return {"success": False, "message": "duration_minutes must be a number"}
        if secs <= 0:
            return {"success": False, "message": "duration_minutes must be > 0"}

        with TimerManager._lock:
            tid = TimerManager._next_id
            TimerManager._next_id += 1
            t = threading.Timer(secs, TimerManager._on_expire, args=(tid,))
            t.daemon = True
            t.start()
            TimerManager._active[tid] = {
                "label": label,
                "started_at": datetime.now(),
                "duration_seconds": secs,
                "timer": t,
            }
        return {
            "success": True,
            "message": f"Timer started for {duration_minutes} minute(s)" +
                       (f" — {label}" if label else ""),
            "timer_id": tid,
        }

    @staticmethod
    def check_timers() -> Dict[str, Any]:
        now = datetime.now()
        items = []
        with TimerManager._lock:
            for tid, e in TimerManager._active.items():
                elapsed = (now - e["started_at"]).total_seconds()
                remaining = max(0, e["duration_seconds"] - elapsed)
                items.append({
                    "id": tid,
                    "label": e["label"] or "",
                    "remaining_seconds": int(remaining),
                    "remaining_human": f"{int(remaining // 60)}m {int(remaining % 60)}s",
                })
        return {
            "success": True,
            "count": len(items),
            "timers": items,
            "message": f"{len(items)} active timer(s)",
        }


# ===== System control =====

class SystemController:
    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        if not _HAS_PSUTIL:
            return {"success": False, "message": "psutil not installed"}
        vm = psutil.virtual_memory()
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "mount": part.mountpoint,
                    "total_gb": round(u.total / (1024 ** 3), 1),
                    "used_gb": round(u.used / (1024 ** 3), 1),
                    "percent": u.percent,
                })
            except (PermissionError, OSError):
                continue
        return {
            "success": True,
            "platform": platform.platform(),
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "cpu_count": psutil.cpu_count(),
            "memory": {
                "total_gb": round(vm.total / (1024 ** 3), 1),
                "used_gb": round(vm.used / (1024 ** 3), 1),
                "percent": vm.percent,
            },
            "disks": disks,
            "message": (
                f"CPU {psutil.cpu_percent(interval=None):.0f}% | "
                f"RAM {vm.percent:.0f}% used"
            ),
        }

    @staticmethod
    def take_screenshot(filename: str = "") -> Dict[str, Any]:
        if not _HAS_PIL:
            return {"success": False, "message": "Pillow not installed"}
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "uploaded_documents")
        os.makedirs(out_dir, exist_ok=True)
        if not filename:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            filename += ".png"
        path = os.path.join(out_dir, filename)
        try:
            img = ImageGrab.grab()
            img.save(path)
        except Exception as e:
            return {"success": False, "message": f"screenshot failed: {e}"}
        return {
            "success": True,
            "path": path,
            "size": img.size,
            "message": f"Saved screenshot to {path}",
        }

    @staticmethod
    def launch_application(app_name: str) -> Dict[str, Any]:
        name = (app_name or "").strip().lower()
        if not name:
            return {"success": False, "message": "app_name required"}
        is_windows = platform.system() == "Windows"
        is_mac = platform.system() == "Darwin"

        win_aliases = {
            "chrome": "chrome.exe",
            "firefox": "firefox.exe",
            "edge": "msedge.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "notepad": "notepad.exe",
            "terminal": "wt.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "vscode": "code",
            "code": "code",
            "spotify": "spotify.exe",
            "explorer": "explorer.exe",
        }
        try:
            if is_windows:
                target = win_aliases.get(name, name)
                subprocess.Popen(target, shell=True)
            elif is_mac:
                subprocess.Popen(["open", "-a", app_name])
            else:
                subprocess.Popen([name])
        except FileNotFoundError:
            return {"success": False, "message": f"Application not found: {app_name}"}
        except Exception as e:
            return {"success": False, "message": f"launch failed: {e}"}
        return {"success": True, "message": f"Launched {app_name}"}

    @staticmethod
    def set_volume(level: int) -> Dict[str, Any]:
        try:
            level = int(level)
        except (TypeError, ValueError):
            return {"success": False, "message": "level must be an integer"}
        level = max(0, min(100, level))

        system = platform.system()
        try:
            if system == "Windows":
                try:
                    from ctypes import cast, POINTER
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    vol = cast(interface, POINTER(IAudioEndpointVolume))
                    vol.SetMasterVolumeLevelScalar(level / 100.0, None)
                except ImportError:
                    ps = (
                        "$obj = New-Object -ComObject WScript.Shell;"
                        f"1..50 | %{{$obj.SendKeys([char]174)}};"
                        f"1..{int(level/2)} | %{{$obj.SendKeys([char]175)}}"
                    )
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                   check=False, capture_output=True)
            elif system == "Darwin":
                subprocess.run(["osascript", "-e",
                                f"set volume output volume {level}"], check=False)
            else:
                subprocess.run(["amixer", "-q", "-D", "pulse",
                                "sset", "Master", f"{level}%"], check=False)
        except Exception as e:
            return {"success": False, "message": f"volume change failed: {e}"}
        return {"success": True, "level": level, "message": f"Volume set to {level}%"}


# ===== File operations =====

class FileOperations:
    @staticmethod
    def _safe_resolve(path: str) -> str:
        return os.path.abspath(os.path.expanduser(path or "."))

    @staticmethod
    def list_files(directory: str = ".", pattern: str = "*",
                   recursive: bool = False) -> Dict[str, Any]:
        base = FileOperations._safe_resolve(directory)
        if not os.path.isdir(base):
            return {"success": False, "message": f"Not a directory: {base}"}
        pat = pattern or "*"
        try:
            if recursive:
                matches = _glob.glob(os.path.join(base, "**", pat), recursive=True)
            else:
                matches = _glob.glob(os.path.join(base, pat))
        except Exception as e:
            return {"success": False, "message": f"glob failed: {e}"}

        files = []
        for m in matches[:200]:
            try:
                st = os.stat(m)
                files.append({
                    "path": m,
                    "name": os.path.basename(m),
                    "is_dir": os.path.isdir(m),
                    "size_bytes": st.st_size,
                })
            except OSError:
                continue
        return {
            "success": True,
            "directory": base,
            "count": len(files),
            "files": files,
            "message": f"{len(files)} entries in {base}",
        }

    @staticmethod
    def read_file(filepath: str) -> Dict[str, Any]:
        path = FileOperations._safe_resolve(filepath)
        if not os.path.isfile(path):
            return {"success": False, "message": f"Not a file: {path}"}
        if os.path.getsize(path) > 5 * 1024 * 1024:
            return {"success": False, "message": "File too large (>5 MB)"}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "message": f"read failed: {e}"}
        return {
            "success": True,
            "path": path,
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
            "message": f"Read {path}",
        }

    @staticmethod
    def write_file(filepath: str, content: str) -> Dict[str, Any]:
        path = FileOperations._safe_resolve(filepath)
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return {"success": False, "message": f"write failed: {e}"}
        return {
            "success": True,
            "path": path,
            "size_bytes": len(content.encode("utf-8")),
            "message": f"Wrote {len(content)} chars to {path}",
        }

    @staticmethod
    def get_file_info(filepath: str) -> Dict[str, Any]:
        path = FileOperations._safe_resolve(filepath)
        if not os.path.exists(path):
            return {"success": False, "message": f"Not found: {path}"}
        try:
            st = os.stat(path)
        except OSError as e:
            return {"success": False, "message": f"stat failed: {e}"}
        return {
            "success": True,
            "path": path,
            "is_dir": os.path.isdir(path),
            "is_file": os.path.isfile(path),
            "size_bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "created": datetime.fromtimestamp(st.st_ctime).isoformat(timespec="seconds"),
            "message": f"Info for {path}",
        }


# ===== Storytelling / educational =====

class StorytellingTools:
    @staticmethod
    def story_prompt(child_name: str, theme: str = "",
                     moral: str = "", length: str = "short") -> Dict[str, Any]:
        ages = {"Emmy": 10, "Athena": 8, "Vilda": 5}
        age = ages.get(child_name, 8)
        length = (length or "short").lower()
        if length not in ("short", "medium", "long"):
            length = "short"
        word_targets = {"short": "200-300", "medium": "400-600", "long": "800-1200"}

        parts = [
            f"Write an age-appropriate story for {child_name} (age {age}).",
            f"Length: {length} ({word_targets[length]} words).",
        ]
        if theme:
            parts.append(f"Theme: {theme}.")
        if moral:
            parts.append(f"Lesson/moral to convey: {moral}.")
        parts.append("Use simple, vivid language. Include dialogue. Avoid scary content.")

        return {
            "success": True,
            "prompt": " ".join(parts),
            "child": child_name,
            "age": age,
            "length": length,
            "message": f"Story prompt prepared for {child_name}",
        }

    @staticmethod
    def educational_activity(child_name: str, subject: str) -> Dict[str, Any]:
        ages = {"Emmy": 10, "Athena": 8, "Vilda": 5}
        age = ages.get(child_name, 8)
        subject = (subject or "").lower()

        ideas = {
            "math": {
                5: "Counting bears or buttons up to 20 — group them by color, then count each pile.",
                8: "Multiplication arrays with cereal: lay out 4 rows of 6 and count by 6s.",
                10: "Estimate the area of a room in square tiles, then measure to check.",
            },
            "science": {
                5: "Sink-or-float experiment with kitchen objects. Predict before testing.",
                8: "Build a simple circuit with a battery, wire, and bulb. Try adding a switch.",
                10: "Track moon phases for two weeks and sketch what you see each night.",
            },
            "reading": {
                5: "Picture-walk through a familiar book and tell the story in your own words.",
                8: "Read a chapter aloud, then write three questions for a younger sibling.",
                10: "Read a short article and summarize the main idea in two sentences.",
            },
            "art": {
                5: "Paint a self-portrait using only three colors.",
                8: "Draw your bedroom from memory, then look and find five things you missed.",
                10: "Recreate a famous painting in your own style with materials at home.",
            },
            "writing": {
                5: "Dictate a story about a pet that flies, then illustrate it.",
                8: "Write a 5-sentence postcard to a future-you that you'll open in a year.",
                10: "Write a one-page mystery — start with a missing object.",
            },
        }
        if subject not in ideas:
            return {"success": False, "message": f"Unknown subject: {subject}"}
        # Pick the closest age bucket
        bucket = min(ideas[subject].keys(), key=lambda k: abs(k - age))
        return {
            "success": True,
            "subject": subject,
            "age": age,
            "activity": ideas[subject][bucket],
            "message": f"Activity for {child_name}: {subject}",
        }


# ===== Location & time =====

# User location (Kitchener, ON) per memory; override via env if needed.
_DEFAULT_LAT = float(os.environ.get("BLUE_LATITUDE", "43.4516"))
_DEFAULT_LON = float(os.environ.get("BLUE_LONGITUDE", "-80.4925"))


def _sun_event(d: date, lat: float, lon: float, sunrise: bool) -> Optional[datetime]:
    """Compute sunrise (sunrise=True) or sunset for the given local date.

    NOAA general solar position algorithm. Returns naive local datetime or
    None if there is no event that day (polar latitudes).
    """
    n = d.toordinal() - date(d.year, 1, 1).toordinal() + 1
    lng_hour = lon / 15.0
    t = n + (((6 if sunrise else 18) - lng_hour) / 24.0)
    M = (0.9856 * t) - 3.289
    L = M + (1.916 * math.sin(math.radians(M))) + \
        (0.020 * math.sin(math.radians(2 * M))) + 282.634
    L = L % 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    L_quad = math.floor(L / 90) * 90
    RA_quad = math.floor(RA / 90) * 90
    RA = (RA + (L_quad - RA_quad)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(90.833)) - (sin_dec * math.sin(math.radians(lat)))) \
            / (cos_dec * math.cos(math.radians(lat)))
    if cos_h > 1 or cos_h < -1:
        return None
    H = (360 - math.degrees(math.acos(cos_h))) if sunrise \
        else math.degrees(math.acos(cos_h))
    H /= 15.0
    T = H + RA - (0.06571 * t) - 6.622
    UT = (T - lng_hour) % 24

    # Convert UT to local time using current local-UTC offset.
    now = datetime.now()
    offset_hours = (datetime.now() - datetime.utcnow()).total_seconds() / 3600.0
    local_hours = (UT + offset_hours) % 24
    h = int(local_hours)
    m = int((local_hours - h) * 60)
    return datetime.combine(d, time(hour=h, minute=m))


class LocationServices:
    @staticmethod
    def get_local_time() -> Dict[str, Any]:
        now = datetime.now()
        return {
            "success": True,
            "iso": now.isoformat(timespec="seconds"),
            "date": now.strftime("%A, %B %d, %Y"),
            "time": now.strftime("%I:%M %p").lstrip("0"),
            "timezone": datetime.now().astimezone().tzname() or "local",
            "message": now.strftime("It's %I:%M %p on %A, %B %d, %Y").replace(" 0", " "),
        }

    @staticmethod
    def get_sunrise_sunset() -> Dict[str, Any]:
        today = date.today()
        sr = _sun_event(today, _DEFAULT_LAT, _DEFAULT_LON, sunrise=True)
        ss = _sun_event(today, _DEFAULT_LAT, _DEFAULT_LON, sunrise=False)
        if sr is None or ss is None:
            return {"success": False, "message": "No sunrise/sunset for this date/latitude"}
        return {
            "success": True,
            "date": today.isoformat(),
            "sunrise": sr.strftime("%I:%M %p").lstrip("0"),
            "sunset": ss.strftime("%I:%M %p").lstrip("0"),
            "latitude": _DEFAULT_LAT,
            "longitude": _DEFAULT_LON,
            "message": f"Sunrise {sr.strftime('%I:%M %p').lstrip('0')}, "
                       f"sunset {ss.strftime('%I:%M %p').lstrip('0')}",
        }


# ===== Stubs (imported by bluetools but not invoked there) =====

class SmartHomeController:
    """Placeholder. bluetools.py imports the symbol but routes smart-home
    actions through the dedicated Hue integration, not this class."""


class MusicController:
    """Placeholder. bluetools.py imports the symbol but routes music
    actions through the dedicated YouTube Music / system-keys path."""


__all__ = [
    "CalendarManager", "TaskManager", "NoteManager",
    "SystemController", "FileOperations", "TimerManager",
    "StorytellingTools", "LocationServices",
    "SmartHomeController", "MusicController",
    "parse_when",
]
