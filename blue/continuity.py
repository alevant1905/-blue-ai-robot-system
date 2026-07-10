"""Durable autobiographical continuity for the experimental Blue-J surface.

The store keeps normal experience records append-only. Explicit owner actions
may correct an episode by appending a superseding record, or permanently delete
one for privacy. A compact workspace and bounded attentional drives are derived
state: useful continuity scaffolding, not a claim about subjective experience.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_DRIVES: Dict[str, float] = {
    "curiosity": 0.55,
    "uncertainty": 0.35,
    "connection": 0.50,
    "commitment": 0.60,
    "energy": 0.65,
}

DRIVE_LABELS: Dict[str, str] = {
    "curiosity": "pull toward unresolved or novel things",
    "uncertainty": "how much currently feels unresolved",
    "connection": "attention to relationships and shared context",
    "commitment": "pressure from promises and unfinished intentions",
    "energy": "available attention for continued work",
}

_EPISODE_KINDS = {
    "exchange",
    "action",
    "perception",
    "tool",
    "reflection",
    "idle",
    "correction",
    "deletion",
    "system",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _bounded(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if not math.isfinite(number):
        number = low
    return max(low, min(high, number))


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


class ContinuityStore:
    """SQLite-backed journal, derived workspace, drives, and reflection queue."""

    def __init__(self, root_dir: os.PathLike[str] | str, seed_workspace: str):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "continuity.db"
        self.legacy_workspace_path = self.root_dir / "workspace.json"
        self.seed_workspace = _clip(seed_workspace, 6000)
        self._lock = threading.RLock()
        self._initialize()
        self._migrate_legacy_workspace()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    def _initialize(self) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspace (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    born_at TEXT NOT NULL,
                    passes INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS drives (
                    name TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    salience REAL NOT NULL DEFAULT 0.5,
                    valence REAL NOT NULL DEFAULT 0.0,
                    parent_id TEXT,
                    supersedes_id TEXT,
                    provenance TEXT NOT NULL DEFAULT '',
                    external_key TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_time
                    ON episodes(occurred_at DESC, seq DESC);
                CREATE INDEX IF NOT EXISTS idx_episodes_kind
                    ON episodes(kind, seq DESC);
                CREATE INDEX IF NOT EXISTS idx_episodes_parent
                    ON episodes(parent_id);
                CREATE INDEX IF NOT EXISTS idx_episodes_supersedes
                    ON episodes(supersedes_id);

                CREATE TABLE IF NOT EXISTS reflection_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    episode_ids_json TEXT NOT NULL DEFAULT '[]',
                    prompt_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_reflection_jobs_status
                    ON reflection_jobs(status, id);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO workspace "
                "(id, content, updated_at, born_at, passes, version) "
                "VALUES (1, ?, ?, ?, 0, 0)",
                (self.seed_workspace, now, now),
            )
            for name, value in DEFAULT_DRIVES.items():
                conn.execute(
                    "INSERT OR IGNORE INTO drives(name, value, updated_at) "
                    "VALUES (?, ?, ?)",
                    (name, value, now),
                )

    def _migrate_legacy_workspace(self) -> None:
        if not self.legacy_workspace_path.exists():
            return
        with self._lock, self._connect() as conn:
            done = conn.execute(
                "SELECT value FROM meta WHERE key = 'legacy_workspace_migrated'"
            ).fetchone()
            if done:
                return
            try:
                data = json.loads(self.legacy_workspace_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            content = _clip(data.get("workspace"), 6000)
            if content:
                updated = _clip(data.get("updated"), 64) or _now()
                born = _clip(data.get("born"), 64) or updated
                passes = max(0, int(data.get("passes") or 0))
                conn.execute(
                    "UPDATE workspace SET content = ?, updated_at = ?, born_at = ?, "
                    "passes = ?, version = version + 1 WHERE id = 1",
                    (content, updated, born, passes),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES "
                "('legacy_workspace_migrated', ?)",
                (_now(),),
            )

    @staticmethod
    def _decode_json(raw: Any, fallback: Any) -> Any:
        try:
            return json.loads(raw or "")
        except (TypeError, ValueError):
            return fallback

    def _episode_from_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "seq": int(row["seq"]),
            "id": row["id"],
            "occurred_at": row["occurred_at"],
            "kind": row["kind"],
            "source": row["source"],
            "summary": row["summary"],
            "details": self._decode_json(row["details_json"], {}),
            "participants": self._decode_json(row["participants_json"], []),
            "salience": float(row["salience"]),
            "valence": float(row["valence"]),
            "parent_id": row["parent_id"],
            "supersedes_id": row["supersedes_id"],
            "provenance": row["provenance"],
            "external_key": row["external_key"],
            "created_at": row["created_at"],
        }

    def _insert_episode(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        source: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        participants: Optional[Iterable[str]] = None,
        salience: float = 0.5,
        valence: float = 0.0,
        parent_id: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        provenance: str = "",
        external_key: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_kind = kind if kind in _EPISODE_KINDS else "system"
        episode_id = uuid.uuid4().hex
        now = _now()
        people = [_clip(x, 80) for x in (participants or []) if _clip(x, 80)]
        payload = _json_object(details)
        try:
            details_json = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            details_json = "{}"
        if len(details_json) > 12000:
            details_json = json.dumps(
                {"truncated": True, "preview": _clip(details_json, 11000)},
                ensure_ascii=False,
            )
        values = (
            episode_id,
            _clip(occurred_at, 64) or now,
            clean_kind,
            _clip(source, 100) or "unknown",
            _clip(summary, 1800) or "(empty episode)",
            details_json,
            json.dumps(people, ensure_ascii=False),
            _bounded(salience),
            _bounded(valence, -1.0, 1.0),
            _clip(parent_id, 64) or None,
            _clip(supersedes_id, 64) or None,
            _clip(provenance, 500),
            _clip(external_key, 240) or None,
            now,
        )
        try:
            conn.execute(
                "INSERT INTO episodes "
                "(id, occurred_at, kind, source, summary, details_json, "
                "participants_json, salience, valence, parent_id, "
                "supersedes_id, provenance, external_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        except sqlite3.IntegrityError:
            if external_key:
                existing = conn.execute(
                    "SELECT * FROM episodes WHERE external_key = ?",
                    (_clip(external_key, 240),),
                ).fetchone()
                if existing:
                    episode = self._episode_from_row(existing)
                    episode["created"] = False
                    return episode
            raise
        row = conn.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        episode = self._episode_from_row(row)
        episode["created"] = True
        return episode

    def append_episode(self, **kwargs: Any) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            return self._insert_episode(conn, **kwargs)

    def get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (_clip(episode_id, 64),)
            ).fetchone()
            return self._episode_from_row(row) if row else None

    def list_episodes(
        self,
        limit: int = 40,
        before_seq: Optional[int] = None,
        kind: Optional[str] = None,
        include_superseded: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses = ["1 = 1"]
        params: List[Any] = []
        if before_seq is not None:
            clauses.append("e.seq < ?")
            params.append(int(before_seq))
        if kind:
            clauses.append("e.kind = ?")
            params.append(kind)
        if not include_superseded:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM episodes newer "
                "WHERE newer.supersedes_id = e.id)"
            )
        params.append(max(1, min(int(limit), 200)))
        sql = (
            "SELECT e.* FROM episodes e WHERE "
            + " AND ".join(clauses)
            + " ORDER BY e.seq DESC LIMIT ?"
        )
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._episode_from_row(row) for row in rows]

    def correct_episode(
        self,
        episode_id: str,
        replacement: str,
        reason: str = "",
        actor: str = "Alex",
    ) -> Dict[str, Any]:
        target = self.get_episode(episode_id)
        if not target:
            raise KeyError("episode not found")
        clean = _clip(replacement, 1800)
        if not clean:
            raise ValueError("replacement is required")
        return self.append_episode(
            kind="correction",
            source="owner_correction",
            summary=clean,
            details={
                "reason": _clip(reason, 500),
                "target_kind": target["kind"],
            },
            participants=[actor],
            salience=max(0.75, target["salience"]),
            supersedes_id=target["id"],
            provenance="Explicit correction by the owner",
        )

    def delete_episode(
        self,
        episode_id: str,
        reason: str = "",
        actor: str = "Alex",
    ) -> Dict[str, Any]:
        clean_id = _clip(episode_id, 64)
        with self._lock:
            with self._connect() as conn:
                target = conn.execute(
                    "SELECT id, kind, supersedes_id FROM episodes WHERE id = ?",
                    (clean_id,),
                ).fetchone()
                if not target:
                    raise KeyError("episode not found")
                root_id = target["id"]
                parent_id = target["supersedes_id"]
                seen = {root_id}
                while parent_id and parent_id not in seen:
                    seen.add(parent_id)
                    parent = conn.execute(
                        "SELECT id, supersedes_id FROM episodes WHERE id = ?",
                        (parent_id,),
                    ).fetchone()
                    if not parent:
                        break
                    root_id = parent["id"]
                    parent_id = parent["supersedes_id"]
                chain_count = conn.execute(
                    "WITH RECURSIVE chain(id) AS ("
                    "SELECT ? UNION ALL "
                    "SELECT e.id FROM episodes e JOIN chain c "
                    "ON e.supersedes_id = c.id"
                    ") SELECT COUNT(*) AS n FROM chain",
                    (root_id,),
                ).fetchone()["n"]
                conn.execute(
                    "WITH RECURSIVE chain(id) AS ("
                    "SELECT ? UNION ALL "
                    "SELECT e.id FROM episodes e JOIN chain c "
                    "ON e.supersedes_id = c.id"
                    ") DELETE FROM episodes WHERE id IN (SELECT id FROM chain)",
                    (root_id,),
                )
                deletion = self._insert_episode(
                    conn,
                    kind="deletion",
                    source="owner_deletion",
                    summary=f"An episode was deleted by {actor}.",
                    details={
                        "deleted_id": clean_id,
                        "deleted_kind": target["kind"],
                        "deleted_chain_count": int(chain_count),
                        "reason": _clip(reason, 500),
                    },
                    participants=[actor],
                    salience=0.8,
                    provenance=(
                        "Owner privacy control; deleted content is not retained here"
                    ),
                )
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return deletion

    def get_workspace(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
            return {
                "workspace": row["content"],
                "updated": row["updated_at"],
                "born": row["born_at"],
                "passes": int(row["passes"]),
                "version": int(row["version"]),
            }

    def update_workspace(
        self, content: str, expected_version: int
    ) -> Tuple[bool, Dict[str, Any]]:
        clean = _clip(content, 6000)
        if not clean:
            return False, self.get_workspace()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "UPDATE workspace SET content = ?, updated_at = ?, "
                "passes = passes + 1, version = version + 1 "
                "WHERE id = 1 AND version = ?",
                (clean, _now(), int(expected_version)),
            )
            row = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
            state = {
                "workspace": row["content"],
                "updated": row["updated_at"],
                "born": row["born_at"],
                "passes": int(row["passes"]),
                "version": int(row["version"]),
            }
            return result.rowcount == 1, state

    def get_drives(self) -> Dict[str, float]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT name, value FROM drives").fetchall()
        values = dict(DEFAULT_DRIVES)
        values.update({row["name"]: _bounded(row["value"]) for row in rows})
        return values

    def _apply_drive_deltas_conn(
        self,
        conn: sqlite3.Connection,
        deltas: Optional[Dict[str, Any]],
        elapsed_hours: float,
    ) -> Dict[str, float]:
        requested = _json_object(deltas)
        elapsed = max(0.0, min(float(elapsed_hours or 0.0), 168.0))
        decay = math.pow(0.985, elapsed)
        now = _now()
        rows = conn.execute("SELECT name, value FROM drives").fetchall()
        current = dict(DEFAULT_DRIVES)
        current.update({row["name"]: _bounded(row["value"]) for row in rows})
        for name, baseline in DEFAULT_DRIVES.items():
            value = baseline + (current[name] - baseline) * decay
            delta = _bounded(requested.get(name, 0.0), -0.15, 0.15)
            value = _bounded(value + delta)
            conn.execute(
                "INSERT INTO drives(name, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (name, value, now),
            )
            current[name] = value
        return current

    def apply_drive_deltas(
        self, deltas: Optional[Dict[str, Any]], elapsed_hours: float = 0.0
    ) -> Dict[str, float]:
        with self._lock, self._connect() as conn:
            return self._apply_drive_deltas_conn(conn, deltas, elapsed_hours)

    def commit_reflection(
        self,
        *,
        job_id: int,
        workspace_content: str,
        expected_version: int,
        drive_deltas: Optional[Dict[str, Any]],
        elapsed_hours: float,
        episode_kind: str,
        episode_summary: str,
        episode_details: Optional[Dict[str, Any]] = None,
        salience: float = 0.5,
        valence: float = 0.0,
        parent_id: Optional[str] = None,
        provenance: str = "",
    ) -> Tuple[bool, Dict[str, Any], Dict[str, float], Optional[Dict[str, Any]]]:
        """Commit all derived reflection state as one reset-safe transaction."""
        clean_workspace = _clip(workspace_content, 6000)
        if not clean_workspace:
            return False, self.get_workspace(), self.get_drives(), None
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "UPDATE workspace SET content = ?, updated_at = ?, "
                "passes = passes + 1, version = version + 1 "
                "WHERE id = 1 AND version = ?",
                (clean_workspace, _now(), int(expected_version)),
            )
            row = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
            workspace = {
                "workspace": row["content"],
                "updated": row["updated_at"],
                "born": row["born_at"],
                "passes": int(row["passes"]),
                "version": int(row["version"]),
            }
            if result.rowcount != 1:
                drives = dict(DEFAULT_DRIVES)
                drives.update({
                    drive["name"]: _bounded(drive["value"])
                    for drive in conn.execute("SELECT name, value FROM drives").fetchall()
                })
                return False, workspace, drives, None
            drives = self._apply_drive_deltas_conn(
                conn, drive_deltas, elapsed_hours
            )
            details = dict(episode_details or {})
            details["drive_deltas"] = _json_object(drive_deltas)
            details["drives_after"] = drives
            details["workspace_version"] = workspace["version"]
            episode = self._insert_episode(
                conn,
                kind=episode_kind,
                source="continuity_worker",
                summary=episode_summary,
                details=details,
                salience=salience,
                valence=valence,
                parent_id=parent_id,
                provenance=provenance,
            )
            conn.execute(
                "UPDATE reflection_jobs SET status = 'done', completed_at = ?, "
                "error = '' WHERE id = ?",
                (_now(), int(job_id)),
            )
            return True, workspace, drives, episode

    def enqueue_reflection(
        self,
        trigger: str,
        episode_ids: Optional[Iterable[str]] = None,
        prompt_text: str = "",
    ) -> int:
        ids = [_clip(x, 64) for x in (episode_ids or []) if _clip(x, 64)]
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reflection_jobs "
                "(trigger, episode_ids_json, prompt_text, status, attempts, created_at) "
                "VALUES (?, ?, ?, 'pending', 0, ?)",
                (
                    _clip(trigger, 40) or "event",
                    json.dumps(ids),
                    _clip(prompt_text, 4000),
                    _now(),
                ),
            )
            return int(cur.lastrowid)

    def claim_reflection(self) -> Optional[Dict[str, Any]]:
        stale_before = (
            datetime.now(timezone.utc) - timedelta(minutes=15)
        ).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE reflection_jobs SET status = 'pending', claimed_at = NULL, "
                "error = 'Recovered stale processing job' "
                "WHERE status = 'processing' AND claimed_at < ? AND attempts < 3",
                (stale_before,),
            )
            active = conn.execute(
                "SELECT id FROM reflection_jobs WHERE status = 'processing' "
                "LIMIT 1"
            ).fetchone()
            if active:
                conn.commit()
                return None
            row = conn.execute(
                "SELECT * FROM reflection_jobs WHERE status = 'pending' "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if not row:
                conn.commit()
                return None
            claimed_at = _now()
            conn.execute(
                "UPDATE reflection_jobs SET status = 'processing', "
                "attempts = attempts + 1, claimed_at = ? WHERE id = ?",
                (claimed_at, row["id"]),
            )
            conn.commit()
            return {
                "id": int(row["id"]),
                "trigger": row["trigger"],
                "episode_ids": self._decode_json(row["episode_ids_json"], []),
                "prompt_text": row["prompt_text"],
                "attempts": int(row["attempts"]) + 1,
                "created_at": row["created_at"],
                "claimed_at": claimed_at,
            }

    def finish_reflection(self, job_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE reflection_jobs SET status = 'done', completed_at = ?, "
                "error = '' WHERE id = ?",
                (_now(), int(job_id)),
            )

    def fail_reflection(self, job_id: int, error: str, retry: bool = True) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM reflection_jobs WHERE id = ?", (int(job_id),)
            ).fetchone()
            attempts = int(row["attempts"]) if row else 3
            status = "pending" if retry and attempts < 3 else "failed"
            conn.execute(
                "UPDATE reflection_jobs SET status = ?, error = ?, "
                "completed_at = ? WHERE id = ?",
                (status, _clip(error, 1000), _now(), int(job_id)),
            )

    def pending_reflections(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM reflection_jobs "
                "WHERE status IN ('pending', 'processing')"
            ).fetchone()
            return int(row["n"])

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()["n"]
            by_kind = conn.execute(
                "SELECT kind, COUNT(*) AS n FROM episodes GROUP BY kind"
            ).fetchall()
            first = conn.execute(
                "SELECT occurred_at FROM episodes ORDER BY seq ASC LIMIT 1"
            ).fetchone()
            latest = conn.execute(
                "SELECT occurred_at FROM episodes ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return {
            "episodes": int(total),
            "by_kind": {row["kind"]: int(row["n"]) for row in by_kind},
            "first_episode": first["occurred_at"] if first else None,
            "latest_episode": latest["occurred_at"] if latest else None,
            "pending_reflections": self.pending_reflections(),
        }

    def archive_and_reset(self, archive: bool = True) -> Optional[Path]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_path = self.root_dir / f"continuity-{stamp}.db" if archive else None
        now = _now()
        with self._lock:
            if archive_path:
                source = self._connect()
                destination = sqlite3.connect(str(archive_path))
                try:
                    source.backup(destination)
                finally:
                    destination.close()
                    source.close()
            with self._connect() as conn:
                old = conn.execute(
                    "SELECT version FROM workspace WHERE id = 1"
                ).fetchone()
                next_version = int(old["version"] if old else 0) + 1
                conn.execute("DELETE FROM reflection_jobs")
                conn.execute("DELETE FROM episodes")
                conn.execute("DELETE FROM drives")
                conn.execute("DELETE FROM workspace")
                conn.execute(
                    "INSERT INTO workspace "
                    "(id, content, updated_at, born_at, passes, version) "
                    "VALUES (1, ?, ?, ?, 0, ?)",
                    (self.seed_workspace, now, now, next_version),
                )
                for name, value in DEFAULT_DRIVES.items():
                    conn.execute(
                        "INSERT INTO drives(name, value, updated_at) VALUES (?, ?, ?)",
                        (name, value, now),
                    )
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if not archive:
                with self._connect() as conn:
                    conn.execute("VACUUM")
        return archive_path
