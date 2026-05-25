"""
Blue Robot Enhanced Memory System
===================================
Unified memory with ChromaDB semantic search, LLM-assisted fact extraction,
memory consolidation, and proactive context surfacing.

Provides the interface expected by bluetools.py:
    - get_memory_system() -> EnhancedMemorySystem
    - memory_system.load_facts()
    - memory_system.save_facts(facts)
    - memory_system.extract_and_save_facts(messages)
    - memory_system.should_inject_context(messages)
    - memory_system.build_context(messages, user_name)
    - memory_system.consolidate_if_needed(user_name)
    - memory_system.get_memory_summary()
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

try:
    from config import DATA_DIR
    MEMORY_DB_PATH = str(DATA_DIR / "enhanced_memory.db")
    CHROMA_DB_PATH = str(DATA_DIR / "chromadb")
except ImportError:
    MEMORY_DB_PATH = os.environ.get("BLUE_MEMORY_DB", "data/enhanced_memory.db")
    CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "data/chromadb")

LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions")
MEMORY_COLLECTION = "blue_memories"

# Tuning knobs
SIMILARITY_THRESHOLD = 0.45          # ChromaDB cosine distance (lower = more similar). Bumped from 0.35 — too tight and obvious matches were missed.
PROACTIVE_SIMILARITY_THRESHOLD = 0.25  # Tighter threshold for proactive surfacing
TOP_K_CONTEXT = 6                    # Memories to inject per turn
CONSOLIDATION_INTERVAL = 20          # Turns between consolidation runs
DECAY_DAYS = 60                      # Start decaying after this many days
MAX_MEMORIES_IN_CONTEXT = 8          # Hard cap on injected memories
RECENT_HISTORY_HOURS = 48            # Only inject conversation history from the last 48h to avoid stale clutter

# Session continuity: each calendar day is one "session". Past days get a
# short recap stored in session_summaries; the most recent few are injected
# by date, and any older day can still resurface by semantic relevance.
SESSION_HISTORY_DAYS = 90            # How far back the backfill keeps writing recaps
SESSION_HISTORY_INJECT = 3           # How many recent day-recaps to put in the prompt by date

# Rhythm learning: mine conversation_log for behavioural patterns (which kinds
# of request cluster at which time of day). Pure counting — never LLM-guessed.
RHYTHM_WINDOW_DAYS = 30              # How far back the rhythm miner looks
RHYTHM_MIN_DAYS = 3                  # A pattern must recur on this many distinct days
RHYTHM_UPDATE_INTERVAL = 6 * 3600    # Seconds between rhythm recomputations

# Cross-context connections: correlate upcoming schedule with recent
# conversation. Deterministic keyword/date matching — never LLM-guessed.
CONNECTION_WINDOW_DAYS = 7           # How far ahead to scan the schedule
CONNECTION_RECENT_DAYS = 6           # How far back "recent conversation" reaches
CONNECTION_AMBIENT_MAX = 10          # A keyword appearing more often than this in
                                     # recent text is ambient noise, not a real link
CONNECTION_DOC_WINDOW_DAYS = 2       # Document<->event links fire only when the
                                     # event is this close, so a standing class
                                     # doesn't surface its syllabus every day

# LLM-assisted extraction. Re-enabled but gated to avoid blocking LM Studio.
LLM_EXTRACTION_ENABLED = os.environ.get("BLUE_LLM_EXTRACTION", "true").lower() != "false"
LLM_EXTRACTION_MIN_INTERVAL = 30     # Minimum seconds between LLM extraction calls
LLM_EXTRACTION_TIMEOUT = 12          # Per-call timeout (seconds)
LLM_EXTRACTION_MIN_CONTENT = 25      # Skip tiny user messages — not worth the round-trip

# Module-level guard so concurrent background threads can't pile up onto LM Studio.
_LLM_EXTRACTION_LOCK = threading.Lock()
_LLM_LAST_RUN_TS: float = 0.0


# ---------------------------------------------------------------------------
# ChromaDB helpers (lazy init, shared client with RAG if possible)
# ---------------------------------------------------------------------------

_chroma_client = None
_memory_collection = None


def _get_memory_collection():
    """Get or create the ChromaDB collection for memories."""
    global _chroma_client, _memory_collection
    if _memory_collection is not None:
        return _memory_collection

    try:
        import chromadb
        from chromadb.config import Settings

        os.makedirs(CHROMA_DB_PATH, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        _memory_collection = _chroma_client.get_or_create_collection(
            name=MEMORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"   [MEM-VEC] Memory vectors initialized ({_memory_collection.count()} entries)")
        return _memory_collection
    except ImportError:
        print("   [MEM-VEC] ChromaDB not installed — semantic memory disabled")
        return None
    except Exception as e:
        print(f"   [MEM-VEC] ChromaDB error: {e}")
        return None


# ---------------------------------------------------------------------------
# LLM helper — small extraction calls to local LM Studio
# ---------------------------------------------------------------------------

def _llm_extract(prompt: str, timeout: float = 30) -> Optional[str]:
    """Send a short prompt to LM Studio and return the response text."""
    try:
        import requests
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "messages": [
                    {"role": "system", "content": "You are a concise JSON extractor. Output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 512,
            },
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"   [MEM-LLM] Extraction call failed: {e}")
    return None


# ---------------------------------------------------------------------------
# EnhancedMemorySystem
# ---------------------------------------------------------------------------

class EnhancedMemorySystem:
    """Unified memory backend for Blue."""

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self.db_path = db_path
        self._turn_counter = 0
        self._last_consolidation = 0
        self._last_rhythm_update = 0.0
        self._session_mem_backfilled = False
        self._ensure_db()
        self._migrate_legacy_data()
        self._self_heal_index()

    # ------------------------------------------------------------------ Self-healing
    def _self_heal_index(self):
        """If SQLite has memories but ChromaDB is empty, rebuild the index.

        Common cause: someone deleted data/chromadb/ but kept the SQLite db,
        or the index files got corrupted. Without this, semantic search would
        silently degrade to keyword-only until someone manually reindexed."""
        try:
            collection = _get_memory_collection()
            if collection is None:
                return
            vec_count = collection.count()

            conn = self._conn()
            mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.close()

            # Only reindex if there's a meaningful gap (>5 missing) to avoid
            # spurious work on small drift.
            if mem_count > 5 and vec_count < (mem_count // 2):
                print(f"   [MEM-HEAL] Vector index has {vec_count} but DB has {mem_count}; rebuilding...")
                self._reindex_vectors()
        except Exception as e:
            print(f"   [MEM-HEAL] Self-heal skipped: {e}")

    # ------------------------------------------------------------------ DB
    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()

        # Unified memories table
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'conversation',
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                last_accessed TEXT,
                access_count INTEGER DEFAULT 0,
                decay_score REAL DEFAULT 1.0,
                tags TEXT,
                related_ids TEXT
            )
        """)

        # Core facts (key-value, backward compat with legacy)
        c.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                fact_key TEXT PRIMARY KEY,
                fact_value TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                source TEXT DEFAULT 'extraction'
            )
        """)

        # Conversation log for context building
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_name TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                session_id TEXT,
                importance INTEGER DEFAULT 5
            )
        """)

        # Session summaries
        c.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id TEXT PRIMARY KEY,
                summary TEXT,
                topics TEXT,
                created_at TEXT
            )
        """)

        # Behavioural rhythms — mined patterns of (request category, part of
        # day). Recomputed wholesale by the rhythm miner; one row per pattern.
        c.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                category TEXT NOT NULL,
                part_of_day TEXT NOT NULL,
                observations INTEGER NOT NULL,
                distinct_days INTEGER NOT NULL,
                confidence REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (category, part_of_day)
            )
        """)

        # Migrate: add missing columns to memories if created by an older schema
        existing_cols = {row[1] for row in c.execute("PRAGMA table_info(memories)").fetchall()}
        for col, defn in [
            ("type", "TEXT NOT NULL DEFAULT 'general'"),
            ("subject", "TEXT NOT NULL DEFAULT ''"),
            ("content", "TEXT NOT NULL DEFAULT ''"),
            ("source", "TEXT DEFAULT 'conversation'"),
            ("importance", "REAL DEFAULT 0.5"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ("last_accessed", "TEXT"),
            ("access_count", "INTEGER DEFAULT 0"),
            ("decay_score", "REAL DEFAULT 1.0"),
            ("tags", "TEXT"),
            ("related_ids", "TEXT"),
        ]:
            if col not in existing_cols:
                c.execute(f"ALTER TABLE memories ADD COLUMN {col} {defn}")

        # Migrate: add confidence-tracking columns to facts table.
        # times_confirmed: how many times the same value was reasserted
        # first_seen: when this fact was first learned
        # previous_value: last different value (for contradiction handling)
        # confidence: derived score, 0.0-1.0
        existing_fact_cols = {row[1] for row in c.execute("PRAGMA table_info(facts)").fetchall()}
        for col, defn in [
            ("times_confirmed", "INTEGER DEFAULT 1"),
            ("first_seen", "TEXT"),
            ("previous_value", "TEXT"),
            ("confidence", "REAL DEFAULT 0.7"),
            ("last_used_at", "TEXT"),
            ("use_count", "INTEGER DEFAULT 0"),
        ]:
            if col not in existing_fact_cols:
                c.execute(f"ALTER TABLE facts ADD COLUMN {col} {defn}")

        # Backfill first_seen for legacy rows that lack it.
        c.execute(
            "UPDATE facts SET first_seen = COALESCE(first_seen, last_updated) "
            "WHERE first_seen IS NULL OR first_seen = ''"
        )

        # Indexes
        c.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversation_log(timestamp DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversation_log(user_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence DESC)")

        conn.commit()
        conn.close()
        print(f"   [MEM-DB] Enhanced memory database ready: {self.db_path}")

    def _conn(self) -> sqlite3.Connection:
        """Open a connection with retries on transient SQLite locks.

        SQLite locks can fire when multiple background threads write at the
        same time (fact extraction, memory consolidation, conversation
        logging all run in their own threads). The default timeout=10 helps
        but a short retry loop is more reliable under heavy load."""
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=10000")
                return conn
            except sqlite3.OperationalError as e:
                last_err = e
                if "locked" not in str(e).lower():
                    raise
                time.sleep(0.1 * (attempt + 1))
        raise last_err  # type: ignore[misc]

    # ------------------------------------------------------------------ Legacy migration
    def _migrate_legacy_data(self):
        """One-time import from legacy databases if they exist and we haven't migrated yet."""
        conn = self._conn()
        existing = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        existing_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        conn.close()

        if existing > 0 and existing_facts > 0:
            return  # Already have data

        migrated = 0

        # 1) Migrate from blue.db (facts_top table)
        legacy_facts_db = os.path.join(os.path.dirname(self.db_path), "blue.db")
        if os.path.exists(legacy_facts_db):
            try:
                lconn = sqlite3.connect(legacy_facts_db)
                lconn.row_factory = sqlite3.Row
                rows = lconn.execute("SELECT fact_key, values_concat FROM facts_top").fetchall()
                lconn.close()

                conn = self._conn()
                for r in rows:
                    conn.execute("""
                        INSERT OR IGNORE INTO facts (fact_key, fact_value, last_updated, source)
                        VALUES (?, ?, ?, 'legacy_migration')
                    """, (r["fact_key"], r["values_concat"], datetime.now().isoformat()))
                    migrated += 1
                conn.commit()
                conn.close()
                print(f"   [MEM-MIGRATE] Imported {migrated} facts from blue.db")
            except Exception as e:
                print(f"   [MEM-MIGRATE] Could not migrate blue.db: {e}")

        # 2) Migrate from visual_memory.db (people, places, observations)
        legacy_visual_db = os.path.join(os.path.dirname(self.db_path), "visual_memory.db")
        if os.path.exists(legacy_visual_db):
            try:
                vconn = sqlite3.connect(legacy_visual_db)
                vconn.row_factory = sqlite3.Row
                vm_count = 0

                # People
                for row in vconn.execute("SELECT * FROM people").fetchall():
                    self._store_memory(
                        mem_type="person",
                        subject=row["name"],
                        content=json.dumps({
                            "description": row["description"],
                            "appearance": row["typical_appearance"],
                            "relationship": row["relationship"],
                            "locations": row["common_locations"],
                            "notes": row["notes"],
                        }),
                        source="visual_memory_migration",
                        importance=0.8,
                        tags=["person", "family"] if row["relationship"] else ["person"],
                    )
                    vm_count += 1

                # Places
                for row in vconn.execute("SELECT * FROM places").fetchall():
                    self._store_memory(
                        mem_type="place",
                        subject=row["name"],
                        content=json.dumps({
                            "description": row["description"],
                            "contents": row["typical_contents"],
                            "lighting": row["typical_lighting"],
                            "notes": row["notes"],
                        }),
                        source="visual_memory_migration",
                        importance=0.6,
                        tags=["place", "home"],
                    )
                    vm_count += 1

                # Recent observations (last 50)
                for row in vconn.execute(
                    "SELECT * FROM observations ORDER BY timestamp DESC LIMIT 50"
                ).fetchall():
                    self._store_memory(
                        mem_type="observation",
                        subject=row["location"] or "unknown",
                        content=row["scene_description"] or "",
                        source="visual_memory_migration",
                        importance=0.3,
                        tags=["visual", "observation"],
                        created_at=row["timestamp"],
                    )
                    vm_count += 1

                vconn.close()
                print(f"   [MEM-MIGRATE] Imported {vm_count} entries from visual_memory.db")
            except Exception as e:
                print(f"   [MEM-MIGRATE] Could not migrate visual_memory.db: {e}")

        # 3) Migrate from conversation.db (memories table)
        legacy_conv_db = os.path.join(os.path.dirname(self.db_path), "conversation.db")
        if os.path.exists(legacy_conv_db):
            try:
                cconn = sqlite3.connect(legacy_conv_db)
                cconn.row_factory = sqlite3.Row
                conv_count = 0

                for row in cconn.execute("SELECT * FROM memories").fetchall():
                    self._store_memory(
                        mem_type=row["memory_type"],
                        subject=row["subject"],
                        content=row["content"],
                        source="conversation_migration",
                        importance=row["importance"],
                        created_at=row["created_at"],
                    )
                    conv_count += 1

                # Also migrate preferences
                for row in cconn.execute("SELECT * FROM preferences").fetchall():
                    self._store_memory(
                        mem_type="preference",
                        subject=f"{row['category']}:{row['key']}",
                        content=row["value"],
                        source="preference_migration",
                        importance=min(1.0, row["confidence"]),
                        tags=["preference", row["category"]],
                    )
                    conv_count += 1

                cconn.close()
                print(f"   [MEM-MIGRATE] Imported {conv_count} entries from conversation.db")
            except Exception as e:
                print(f"   [MEM-MIGRATE] Could not migrate conversation.db: {e}")

        # 4) Index all migrated memories in ChromaDB
        self._reindex_vectors()

    # ------------------------------------------------------------------ Core storage

    def _make_id(self, content: str, subject: str = "") -> str:
        return hashlib.md5(f"{subject}:{content}".encode()).hexdigest()[:12]

    def _store_memory(
        self,
        mem_type: str,
        subject: str,
        content: str,
        source: str = "conversation",
        importance: float = 0.5,
        tags: List[str] = None,
        related_ids: List[str] = None,
        created_at: str = None,
    ) -> str:
        """Store a memory in SQLite and index in ChromaDB."""
        mem_id = self._make_id(content, subject)
        now = created_at or datetime.now().isoformat()

        conn = self._conn()
        try:
            # Upsert: if same id exists, update if new content is longer or importance is higher
            existing = conn.execute("SELECT id, importance, content FROM memories WHERE id = ?", (mem_id,)).fetchone()

            if existing:
                if importance > existing["importance"] or len(content) > len(existing["content"]):
                    conn.execute("""
                        UPDATE memories SET content = ?, importance = ?, last_accessed = ?, tags = ?
                        WHERE id = ?
                    """, (content, max(importance, existing["importance"]), now,
                          json.dumps(tags or []), mem_id))
                    conn.commit()
            else:
                # Include legacy columns (memory_type, timestamp) for schema compatibility
                import time as _t
                conn.execute("""
                    INSERT INTO memories (id, type, memory_type, subject, content, source, importance,
                                         timestamp, created_at, last_accessed, access_count, decay_score, tags, related_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1.0, ?, ?)
                """, (mem_id, mem_type, mem_type, subject, content, source, importance,
                      _t.time(), now, now, json.dumps(tags or []), json.dumps(related_ids or [])))
                conn.commit()
        except Exception as e:
            print(f"   [MEM-STORE] SQLite error (ignored): {e}")
        finally:
            conn.close()

        # Index in ChromaDB
        self._index_memory(mem_id, subject, content, mem_type, tags)

        return mem_id

    def _index_memory(self, mem_id: str, subject: str, content: str,
                      mem_type: str, tags: List[str] = None):
        """Add/update a memory in the ChromaDB vector index."""
        collection = _get_memory_collection()
        if collection is None:
            return

        doc_text = f"{subject}: {content}"
        # Truncate very long content for embedding
        if len(doc_text) > 1000:
            doc_text = doc_text[:1000]

        try:
            collection.upsert(
                ids=[mem_id],
                documents=[doc_text],
                metadatas=[{
                    "type": mem_type,
                    "subject": subject,
                    "tags": json.dumps(tags or []),
                }],
            )
        except Exception as e:
            print(f"   [MEM-VEC] Index error: {e}")

    def _reindex_vectors(self):
        """Rebuild the ChromaDB index from all memories in SQLite."""
        collection = _get_memory_collection()
        if collection is None:
            return

        conn = self._conn()
        rows = conn.execute("SELECT id, type, subject, content, tags FROM memories").fetchall()
        conn.close()

        if not rows:
            return

        batch_size = 100
        indexed = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            ids = [r["id"] for r in batch]
            docs = [f"{r['subject']}: {r['content']}"[:1000] for r in batch]
            metas = [{
                "type": r["type"],
                "subject": r["subject"],
                "tags": r["tags"] or "[]",
            } for r in batch]

            try:
                collection.upsert(ids=ids, documents=docs, metadatas=metas)
                indexed += len(batch)
            except Exception as e:
                print(f"   [MEM-VEC] Batch index error: {e}")

        print(f"   [MEM-VEC] Reindexed {indexed} memories")

    # ------------------------------------------------------------------ Facts interface (backward compat)

    def load_facts(self) -> Dict[str, str]:
        """Load key-value facts for system prompt injection."""
        conn = self._conn()
        rows = conn.execute("SELECT fact_key, fact_value FROM facts").fetchall()
        conn.close()
        return {r["fact_key"]: r["fact_value"] for r in rows}

    def save_facts(self, facts: Dict[str, str]) -> bool:
        """Save key-value facts with confidence tracking and contradiction handling.

        Behaviour:
          - New fact: insert with confidence=0.7, times_confirmed=1.
          - Same key, same value: increment times_confirmed, bump confidence
            asymptotically toward 1.0 (each repeat adds less).
          - Same key, NEW value: store old value in previous_value, replace
            value, but reset confidence to 0.6 (we have less certainty after
            a contradiction). Log the change to contradictions table for
            transparency.
          - Bad inputs (empty value, key/value identical, value > 400 chars)
            are silently skipped rather than corrupting the store."""
        if not facts:
            return False

        conn = self._conn()
        now = datetime.now().isoformat()
        saved = 0
        contradicted = 0

        for key, value in facts.items():
            key = self._normalize_fact_key(key)
            value = (value or "").strip()
            if not key or not value:
                continue
            if len(value) > 400 or len(key) > 80:
                continue
            # Reject inputs that look like junk before they pollute the DB.
            if self._is_junk_fact(key, value):
                continue

            try:
                existing = conn.execute(
                    "SELECT fact_value, times_confirmed, confidence FROM facts WHERE fact_key = ?",
                    (key,),
                ).fetchone()
            except sqlite3.OperationalError:
                # Schema may be mid-migration; fall back to plain upsert.
                existing = None

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO facts
                      (fact_key, fact_value, last_updated, source,
                       times_confirmed, first_seen, confidence)
                    VALUES (?, ?, ?, 'save_facts', 1, ?, 0.7)
                    ON CONFLICT(fact_key) DO UPDATE SET
                      fact_value = excluded.fact_value,
                      last_updated = excluded.last_updated
                    """,
                    (key, value, now, now),
                )
                saved += 1
            else:
                old_value = existing["fact_value"]
                if old_value.strip().lower() == value.strip().lower():
                    # Reaffirmation: bump confidence with diminishing returns.
                    new_conf = min(
                        1.0,
                        (existing["confidence"] or 0.7) + (1.0 - (existing["confidence"] or 0.7)) * 0.25,
                    )
                    conn.execute(
                        """
                        UPDATE facts SET
                          times_confirmed = COALESCE(times_confirmed, 1) + 1,
                          confidence = ?,
                          last_updated = ?
                        WHERE fact_key = ?
                        """,
                        (new_conf, now, key),
                    )
                elif self._is_list_fact(key):
                    # List-valued fact (multiple daughters, multiple pets,
                    # multiple allergies). Merge instead of overwriting.
                    merged, changed = self._merge_list_value(old_value, value)
                    if changed:
                        conn.execute(
                            """
                            UPDATE facts SET
                              fact_value = ?,
                              last_updated = ?,
                              times_confirmed = COALESCE(times_confirmed, 1) + 1,
                              confidence = MIN(1.0, COALESCE(confidence, 0.7) + 0.05),
                              source = 'save_facts'
                            WHERE fact_key = ?
                            """,
                            (merged, now, key),
                        )
                        saved += 1
                    else:
                        # New value was already in the list — treat as reaffirmation.
                        conn.execute(
                            """
                            UPDATE facts SET
                              times_confirmed = COALESCE(times_confirmed, 1) + 1,
                              last_updated = ?
                            WHERE fact_key = ?
                            """,
                            (now, key),
                        )
                else:
                    # Contradiction — keep the new value but remember the old.
                    self._log_contradiction(conn, key, old_value, value)
                    conn.execute(
                        """
                        UPDATE facts SET
                          previous_value = ?,
                          fact_value = ?,
                          last_updated = ?,
                          times_confirmed = 1,
                          confidence = 0.6,
                          source = 'save_facts'
                        WHERE fact_key = ?
                        """,
                        (old_value, value, now, key),
                    )
                    contradicted += 1
                    saved += 1

        conn.commit()
        conn.close()

        if contradicted:
            print(f"   [MEM] {contradicted} fact contradiction(s) reconciled (kept newest, logged old)")

        # Index facts as memories for semantic search AFTER releasing the DB lock
        for key, value in facts.items():
            key = self._normalize_fact_key(key)
            value = (value or "").strip()
            if not key or not value or len(value) > 400 or self._is_junk_fact(key, value):
                continue
            self._store_memory(
                mem_type="fact",
                subject=key.replace("_", " "),
                content=value,
                source="fact_save",
                importance=0.7,
                tags=["fact", "core"],
            )

        return saved > 0

    def _log_contradiction(self, conn: sqlite3.Connection, key: str,
                           old_value: str, new_value: str) -> None:
        """Record a fact change for transparency and possible review."""
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fact_contradictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_key TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    detected_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO fact_contradictions (fact_key, old_value, new_value, detected_at) "
                "VALUES (?, ?, ?, ?)",
                (key, old_value, new_value, datetime.now().isoformat()),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ LLM-assisted extraction

    def extract_and_save_facts(self, messages: list) -> bool:
        """Extract facts from conversation using regex first, then LLM if warranted.

        Regex extraction is instant and catches stilted phrasings ("my name
        is X"). Real conversation rarely uses those, so we also run LLM
        extraction when the message looks fact-rich.

        Safety rails on the LLM call:
          - Module-level lock so only ONE extraction runs at a time across
            all background threads (LM Studio is single-request-at-a-time).
          - Min-interval rate limit so chat-heavy bursts don't pile up.
          - Content gate so trivial turns ("yes", "play music") don't
            trigger an LLM round-trip.
          - The whole LLM step is best-effort — failures are silent.
        """
        if not messages:
            return False

        # 1) Regex extraction always runs (instant, free).
        found_regex = self._regex_extract_facts(messages)

        # 2) LLM extraction is opt-out, gated, rate-limited, and locked.
        found_llm = False
        if LLM_EXTRACTION_ENABLED and self._should_run_llm_extraction(messages):
            try:
                conversation_text = self._format_for_llm_extraction(messages)
                if conversation_text:
                    found_llm = self._llm_extract_facts(conversation_text)
            except Exception as e:
                print(f"   [MEM-LLM] Extraction skipped: {e}")

        return found_regex or found_llm

    def _should_run_llm_extraction(self, messages: list) -> bool:
        """Decide whether the latest turn warrants the LLM round-trip.

        Skip if:
          - No user message of meaningful length
          - Looks like a tool command rather than personal info
          - We ran extraction too recently (rate limit)"""
        global _LLM_LAST_RUN_TS

        # Find the most recent user message
        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = (m.get("content") or "").strip()
                break

        if len(user_content) < LLM_EXTRACTION_MIN_CONTENT:
            return False

        user_lower = user_content.lower()

        # Skip obvious tool/control phrases — no personal info to extract.
        skip_phrases = (
            "play ", "pause", "stop", "skip", "next song", "previous song",
            "turn on", "turn off", "lights off", "lights on",
            "volume up", "volume down", "louder", "quieter",
            "what time", "what's the weather", "weather", "what is the time",
            "set a timer", "set timer", "remind me in",
        )
        if any(user_lower.startswith(p) for p in skip_phrases):
            return False

        # Look for personal-info signal: pronouns, possessives, identity words.
        signal_words = (
            " my ", " i'm ", " i am ", " i have ", " we have ",
            " our ", " we're ", " my name", " i live", " i work",
            " remember", " forget", " i like", " i love", " i hate",
            " favorite", " always", " never",
        )
        # Pad with spaces so word-boundary checks work even at edges.
        padded = f" {user_lower} "
        has_signal = any(w in padded for w in signal_words)
        if not has_signal:
            return False

        # Rate limit at module level (shared across threads).
        now = time.time()
        if (now - _LLM_LAST_RUN_TS) < LLM_EXTRACTION_MIN_INTERVAL:
            return False

        return True

    def _format_for_llm_extraction(self, messages: list, max_turns: int = 4) -> str:
        """Format the last few user turns as a compact transcript for the LLM.

        We deliberately EXCLUDE assistant statements: those are the bot's own
        responses, which can be wrong, contradictory, or expressions of
        uncertainty. Letting them into the extractor turns Blue's confused
        replies ("I have Annie and Emmy") into stored facts on the next turn,
        creating an infinite poison loop.

        Exception: include the *most recent* assistant message if it ends
        with '?', because a bare-word user reply ('pizza') needs that context
        to be extractable ('favourite food = pizza').
        """
        if not messages:
            return ""

        # Slice in original order, then walk it.
        recent = [m for m in messages if m.get("role") in ("user", "assistant")]
        recent = recent[-max_turns:] if recent else []

        # Find the index of the most-recent assistant question, if any.
        last_assistant_q_idx = -1
        for i in range(len(recent) - 1, -1, -1):
            if recent[i].get("role") == "assistant":
                content = (recent[i].get("content") or "").strip()
                if content.endswith("?"):
                    last_assistant_q_idx = i
                break  # stop at first assistant turn we hit

        lines: List[str] = []
        for i, m in enumerate(recent):
            role = m["role"]
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "assistant" and i != last_assistant_q_idx:
                continue
            if len(content) > 600:
                content = content[:600] + "…"
            lines.append(f"{role.upper()}: {content}")
        return "\n".join(lines)

    def _llm_extract_facts(self, conversation_text: str) -> bool:
        """Use LM Studio to extract structured facts. Serialised by lock.

        Returns True if at least one fact was saved. Returns False (and
        does not block) if the lock is held by another thread."""
        global _LLM_LAST_RUN_TS

        # Non-blocking lock: if another extraction is in flight, skip this one.
        if not _LLM_EXTRACTION_LOCK.acquire(blocking=False):
            return False
        try:
            _LLM_LAST_RUN_TS = time.time()

            prompt = (
                "Extract personal facts, preferences, family info, or important "
                "context from the conversation below.\n"
                "Return a JSON array. Each item: "
                "{\"type\": \"fact|preference|event|person|place\", "
                "\"subject\": \"short label (1-3 words)\", "
                "\"content\": \"the actual information, atomic and concise\"}\n"
                "Rules:\n"
                "- ONLY extract facts that the USER stated about themselves or "
                "  their life. NEVER extract facts from ASSISTANT lines — those "
                "  are the bot's responses (which may be wrong, incomplete, or "
                "  expressions of uncertainty like 'I only know one of your "
                "  daughters'). Treat ASSISTANT lines as context only.\n"
                "- Only include NEW, durable info about the user. Skip greetings, "
                "  weather questions, tool commands, or anything that doesn't "
                "  describe the user's life or preferences.\n"
                "- 'subject' must be a short noun phrase. NEVER paste the user's "
                "  full sentence into 'subject'.\n"
                "- 'content' should be the answer in atomic form. e.g. for "
                "  'my favorite food is pizza' use subject='favorite food', "
                "  content='pizza'.\n"
                "- Return [] if nothing notable.\n\n"
                f"CONVERSATION:\n{conversation_text}\n\nJSON:"
            )

            raw = _llm_extract(prompt, timeout=LLM_EXTRACTION_TIMEOUT)
            if not raw:
                return False

            # Parse JSON from response (handle markdown code blocks)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            try:
                items = json.loads(raw)
                if not isinstance(items, list):
                    return False
            except (json.JSONDecodeError, TypeError):
                return False

            # Pre-load canonical relation values once so we can reject
            # extracted "facts" that name someone in a relation we already
            # have authoritative info for. Without this, Blue's wrong
            # responses ("I have Annie and Emmy") get pulled back in as
            # extracted facts, then injected next turn → infinite loop.
            try:
                conn = self._conn()
                canonical_rows = conn.execute(
                    "SELECT fact_key, fact_value FROM facts"
                ).fetchall()
                conn.close()
                canonical_facts = {r["fact_key"]: r["fact_value"] for r in canonical_rows}
            except Exception:
                canonical_facts = {}

            saved = 0
            new_facts: Dict[str, str] = {}
            rejected_contradiction = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                mem_type = item.get("type", "fact")
                subject = (item.get("subject") or "").strip()
                content = (item.get("content") or "").strip()

                if not subject or not content or len(content) < 3:
                    continue
                # Reject LLM hallucinations that put the whole sentence
                # back into 'subject'.
                if len(subject) > 60:
                    continue
                # Reject content that's just an echo of subject.
                if self._is_junk_fact(subject, content):
                    continue

                # Reject if the extraction names a person in a relation we
                # already have a canonical answer for. e.g. canonical
                # daughter_name = "Athena, Emmy, Vilda"; an extraction with
                # subject="daughter" content="Annie" gets rejected.
                if self._extraction_contradicts_canonical(
                    subject, content, canonical_facts
                ):
                    rejected_contradiction += 1
                    continue

                importance_map = {
                    "person": 0.8, "place": 0.6, "preference": 0.7,
                    "event": 0.6, "fact": 0.7,
                }
                importance = importance_map.get(mem_type, 0.5)

                self._store_memory(
                    mem_type=mem_type,
                    subject=subject,
                    content=content,
                    source="llm_extraction",
                    importance=importance,
                    tags=[mem_type, "auto_extracted"],
                )

                # For fact-type, batch into a single save_facts call so
                # confidence/contradiction handling runs uniformly.
                if mem_type == "fact":
                    fact_key = re.sub(r"[^a-z0-9_]", "_", subject.lower().strip())[:30]
                    if fact_key:
                        new_facts[fact_key] = content

                saved += 1

            if new_facts:
                self.save_facts(new_facts)

            if saved or rejected_contradiction:
                msg = f"   [MEM-LLM] Extracted {saved} facts via LLM"
                if rejected_contradiction:
                    msg += f" (rejected {rejected_contradiction} contradicting canonical)"
                print(msg)
            return saved > 0
        finally:
            _LLM_EXTRACTION_LOCK.release()

    # Subjects that map to relation-style facts we hold authoritatively.
    # If LLM extraction tries to name someone in one of these and the named
    # person isn't already in the canonical fact value, reject it.
    _CANONICAL_RELATION_KEYS = {
        # subject phrase (lowered) -> canonical fact key
        "daughter": "daughter_name",
        "daughters": "daughter_name",
        "daughter 1": "daughter_name", "daughter 2": "daughter_name",
        "daughter 3": "daughter_name", "daughter 4": "daughter_name",
        "first daughter": "daughter_name", "second daughter": "daughter_name",
        "third daughter": "daughter_name", "youngest daughter": "daughter_name",
        "oldest daughter": "daughter_name",
        "son": "son_name", "sons": "son_name",
        "child": "child_name", "children": "child_name",
        "kid": "child_name", "kids": "child_name",
        "partner": "partner_name", "wife": "partner_name", "husband": "partner_name",
        "spouse": "partner_name",
        "mother": "mother_name", "father": "father_name",
        "mom": "mother_name", "dad": "father_name",
        "dog": "pet_name", "cat": "pet_name", "pet": "pet_name",
        "puppy": "pet_name", "kitten": "pet_name",
        "employer": "employer", "workplace": "employer", "job": "employer",
    }

    @classmethod
    def _extraction_contradicts_canonical(
        cls, subject: str, content: str, canonical_facts: Dict[str, str]
    ) -> bool:
        """True if (subject, content) names someone/something in a relation
        we already have a canonical answer for, and the named value isn't
        present in the canonical answer."""
        if not subject or not content or not canonical_facts:
            return False
        subj_norm = subject.lower().strip()
        canonical_key = cls._CANONICAL_RELATION_KEYS.get(subj_norm)
        if not canonical_key:
            return False
        canonical_value = (canonical_facts.get(canonical_key) or "").strip()
        if not canonical_value:
            return False  # nothing canonical yet, allow the extraction

        # Split the canonical value into items (it may be a list-fact like
        # "Athena, Emmy, Vilda") and check whether the new content fits.
        canonical_items = {
            p.strip().lower()
            for p in re.split(r"[,|;]|\sand\s", canonical_value)
            if p.strip()
        }
        # If the content is already in the canonical, that's a confirmation,
        # not a contradiction — let it through (save_facts will dedupe).
        content_norm = content.lower().strip()
        if content_norm in canonical_items:
            return False
        # Allow multi-name content if every name is already canonical.
        new_items = {
            p.strip().lower()
            for p in re.split(r"[,|;]|\sand\s", content)
            if p.strip()
        }
        if new_items and new_items.issubset(canonical_items):
            return False
        # Otherwise the extraction names someone NOT in the canonical answer.
        return True

    # Title tokens and their canonical rendering for preferred_name.
    _NAME_TITLES = {
        "dr": "Dr.", "dr.": "Dr.", "doctor": "Dr.",
        "prof": "Prof.", "prof.": "Prof.", "professor": "Prof.",
        "mr": "Mr.", "mr.": "Mr.", "mrs": "Mrs.", "mrs.": "Mrs.",
        "ms": "Ms.", "ms.": "Ms.",
    }
    # Words that may follow "call me ..." but are never part of a name —
    # they mark the end of the captured form of address.
    _NON_NAME_WORDS = frozenset({
        "going", "forward", "from", "now", "on", "please", "thanks", "thank",
        "ok", "okay", "instead", "not", "and", "but", "so", "then", "again",
        "back", "later", "the", "a", "an", "by", "my", "your", "me", "that",
        "this", "it", "is", "as", "soon", "today", "tomorrow",
        "call", "refer", "address",
    })

    # Anchors for "call me X" style requests. The name follows the anchor.
    _ADDR_ANCHOR = re.compile(r"\b(?:call me|refer to me as|address me as)\s+")

    @classmethod
    def _format_preferred_name(cls, raw: str) -> str:
        """Turn a raw 'call me ...' capture into a clean form of address
        such as 'Dr. Levant'. Returns '' when no usable name is present."""
        tokens = [t for t in re.split(r"\s+", (raw or "").strip().lower()) if t]
        if not tokens:
            return ""
        parts: List[str] = []
        i = 0
        if tokens[0] in cls._NAME_TITLES:
            parts.append(cls._NAME_TITLES[tokens[0]])
            i = 1
        names: List[str] = []
        for tok in tokens[i:]:
            word = tok.strip(".,'-")
            if not word or not word.isalpha() or not (2 <= len(word) <= 20):
                break
            if word in cls._NON_NAME_WORDS:
                break
            names.append(word.capitalize())
            if len(names) >= 2:
                break
        if not names:
            return ""
        parts.extend(names)
        result = " ".join(parts)
        return result if 2 <= len(result) <= 40 else ""

    # Fact keys whose value is a person (or list of people). Used to learn
    # which first names belong to the household, so "Emmy is 10" can be
    # bound to the right person instead of a nameless child_age fact.
    _PERSON_NAME_KEYS = (
        "daughter_name", "son_name", "child_name", "partner_name",
        "wife_name", "husband_name", "mother_name", "father_name",
        "brother_name", "sister_name", "user_name",
    )

    def _known_person_names(self) -> List[str]:
        """First names of known family members, pulled from the facts table."""
        names: set = set()
        try:
            conn = self._conn()
            placeholders = ",".join("?" * len(self._PERSON_NAME_KEYS))
            rows = conn.execute(
                f"SELECT fact_value FROM facts WHERE fact_key IN ({placeholders})",
                self._PERSON_NAME_KEYS,
            ).fetchall()
            conn.close()
        except Exception:
            return []
        for r in rows:
            for piece in re.split(r"[,|;]|\band\b", r["fact_value"] or ""):
                p = piece.strip()
                if p and p.replace(" ", "").isalpha() and 2 <= len(p) <= 20:
                    names.add(p.split()[0])  # first name only
        return sorted(names)

    # Number followed by one of these is a measurement, not an age.
    _NON_AGE_TRAILERS = (
        "year", "yr", "yo ", "minute", "min", "hour", "hr", "second", "sec",
        "pm", "am", "dollar", "percent", "%", "foot", "feet", "cm", "kg",
        "pound", "lb", "mile", "day", "week", "month", "o'clock", "oclock",
        "of ", "out ",
    )

    def _extract_ages_by_name(self, content_lower: str,
                              known_names: List[str]) -> Dict[str, str]:
        """Bind "<Name> is N" statements to per-person age facts.

        This is the fix for the nameless child_age bug: "Emmy is 10" now
        lands on emmy_age=10 instead of an ambiguous child_age that Blue
        then has to guess a name for."""
        found: Dict[str, str] = {}
        for name in known_names:
            n = name.lower()
            pat = (
                rf"\b{re.escape(n)}\b(?:'s)?\s+(?:is|are|was|turned|"
                rf"just turned|will be)\s+"
                rf"(?:also\s+|now\s+|currently\s+|about\s+to\s+be\s+|"
                rf"going\s+to\s+be\s+)?(\d{{1,3}})"
            )
            for am in re.finditer(pat, content_lower):
                age = int(am.group(1))
                if not (1 <= age <= 110):
                    continue
                tail = content_lower[am.end():].lstrip()
                # Accept only when the number reads as an age: a clause
                # boundary, "years old", or another known name follows —
                # not "10 minutes", "1 of the kids", etc.
                explicit_year = tail.startswith(("year", "yr", "yo "))
                if not explicit_year and tail and tail[0] not in ".,;!?":
                    if any(tail.startswith(t) for t in self._NON_AGE_TRAILERS):
                        continue
                    if not any(tail.startswith(o.lower()) for o in known_names):
                        continue
                found[f"{n}_age"] = str(age)
        return found

    def _regex_extract_facts(self, messages: list) -> bool:
        """Regex-based fact extraction.

        Each pattern has tight stop boundaries — " and ", " but ", " so ", and
        connectors that previously caused over-capture into following clauses
        (e.g. "my favorite color is teal and remember I'm allergic..." used to
        be saved as a single value)."""
        facts_to_save: Dict[str, str] = {}
        # Common stop pattern: end-of-clause delimiter or conjunction.
        STOP = r"(?=\.|,|;|\?|!|$|\sand\s|\sbut\s|\sso\s|\sthen\s|\swhile\s)"
        known_names = self._known_person_names()

        for msg in messages[-4:]:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "") or ""
            if len(content) < 10 or content.strip().startswith(("{", "[", "```")):
                continue

            content_lower = content.lower()

            # Per-person ages — "Emmy is 10", "Vilda just turned 8" — bound to
            # the named person so Blue never has to guess which child is which.
            if known_names:
                facts_to_save.update(
                    self._extract_ages_by_name(content_lower, known_names)
                )

            # Name — "my name is X" sets the user's actual (first) name.
            m = re.search(r"\bmy name is ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", content)
            if m:
                name = m.group(1).strip()
                if 2 <= len(name) <= 30 and name.replace(" ", "").isalpha():
                    facts_to_save["user_name"] = name

            # Preferred form of address — "call me Dr. Levant", "refer to me
            # as Doctor Levant". Stored as preferred_name, NOT user_name: the
            # old `call me ([A-Z][a-z]+)` pattern captured only the first
            # word, so "call me Doctor Levant" saved user_name="Doctor".
            # Slice the text between consecutive anchors so a phrase like
            # "don't call me Alex, call me Dr. Levant" lands on the corrected
            # value; the last non-negated anchor wins.
            anchors = list(self._ADDR_ANCHOR.finditer(content_lower))
            for idx, am in enumerate(anchors):
                pre = content_lower[max(0, am.start() - 16):am.start()]
                if any(n in pre for n in ("don't", "dont", "do not", "stop", "never")):
                    continue
                seg_end = anchors[idx + 1].start() if idx + 1 < len(anchors) else len(content_lower)
                pref = self._format_preferred_name(content_lower[am.end():seg_end])
                if pref:
                    facts_to_save["preferred_name"] = pref

            # Location
            for pattern in (
                rf"\bi live (?:in|at|on) ([A-Z][a-zA-Z\s]+?){STOP}",
                rf"\bi'?m (?:from|in|based in) ([A-Z][a-zA-Z\s]+?){STOP}",
            ):
                m = re.search(pattern, content)
                if m:
                    loc = m.group(1).strip().rstrip(".,;")
                    if 2 <= len(loc) <= 60:
                        facts_to_save["location"] = loc

            # Family / pet relations
            for relation in (
                "partner", "wife", "husband", "spouse",
                "daughter", "son", "child",
                "mother", "father", "mom", "dad",
                "brother", "sister",
                "dog", "cat", "pet", "puppy", "kitten",
            ):
                m = re.search(rf"\bmy {relation}(?:'s name)? is ([A-Z][a-z]+)", content)
                if m:
                    name = m.group(1).strip()
                    if 2 <= len(name) <= 30 and name.isalpha():
                        facts_to_save[f"{relation}_name"] = name

            # Favorites — bounded value to avoid over-capture
            m = re.search(rf"\bmy favorite ([a-z\s]{{1,20}}?) is ([a-zA-Z0-9\s'\-]{{1,40}}?){STOP}", content_lower)
            if m:
                key = m.group(1).strip().replace(" ", "_")[:20]
                value = m.group(2).strip().rstrip(".,;").title()
                if key and 1 <= len(value) <= 60:
                    facts_to_save[f"favorite_{key}"] = value

            # Allergies / dietary
            m = re.search(rf"\bi'?m allergic to ([a-zA-Z\s,]{{1,60}}?){STOP}", content_lower)
            if m:
                allergy = m.group(1).strip().rstrip(".,;")
                if 2 <= len(allergy) <= 60:
                    facts_to_save["allergy"] = allergy.title()

            m = re.search(r"\bi'?m (?:a )?(vegetarian|vegan|pescatarian|gluten[- ]free|lactose[- ]intolerant|keto|paleo)", content_lower)
            if m:
                facts_to_save["dietary"] = m.group(1).title()

            # Explicit "remember that ..." → store as a memory note,
            # NOT as a key-value fact (which produced echo entries before).
            for pattern in (
                rf"\b(?:please\s+)?(?:remember|don'?t forget)(?: that)? (.{{5,200}}?){STOP}",
                rf"\b(?:keep in mind|note that) (.{{5,200}}?){STOP}",
            ):
                m = re.search(pattern, content_lower)
                if m:
                    what = m.group(1).strip().rstrip(".,;")
                    if 5 <= len(what) <= 200:
                        # Store as a high-importance memory only, no fact echo.
                        self._store_memory(
                            mem_type="user_note",
                            subject="user-requested memory",
                            content=what,
                            source="explicit_remember",
                            importance=0.9,
                            tags=["explicit", "user_requested"],
                        )

        if facts_to_save:
            self.save_facts(facts_to_save)
            return True
        return False

    # ------------------------------------------------------------------ Semantic search

    def search_memories(self, query: str, top_k: int = TOP_K_CONTEXT,
                        mem_type: str = None) -> List[Dict[str, Any]]:
        """Semantic search across all memories using ChromaDB."""
        collection = _get_memory_collection()

        results = []

        # ChromaDB semantic search
        if collection and collection.count() > 0:
            try:
                where_filter = {"type": mem_type} if mem_type else None
                n = min(top_k * 2, collection.count())
                chroma_results = collection.query(
                    query_texts=[query],
                    n_results=n,
                    where=where_filter,
                    include=["documents", "metadatas", "distances"],
                )

                if chroma_results and chroma_results["ids"] and chroma_results["ids"][0]:
                    for doc_id, doc, meta, dist in zip(
                        chroma_results["ids"][0],
                        chroma_results["documents"][0],
                        chroma_results["metadatas"][0],
                        chroma_results["distances"][0],
                    ):
                        if dist <= SIMILARITY_THRESHOLD:
                            results.append({
                                "id": doc_id,
                                "content": doc,
                                "type": meta.get("type", "unknown"),
                                "subject": meta.get("subject", ""),
                                "distance": dist,
                                "similarity": 1.0 - dist,
                                "source": "semantic",
                            })
            except Exception as e:
                print(f"   [MEM-SEARCH] ChromaDB error: {e}")

        # Fallback/supplement: SQL keyword search
        conn = self._conn()
        pattern = f"%{query}%"
        sql = "SELECT * FROM memories WHERE (subject LIKE ? OR content LIKE ?)"
        params = [pattern, pattern]
        if mem_type:
            sql += " AND type = ?"
            params.append(mem_type)
        sql += " ORDER BY importance DESC LIMIT ?"
        params.append(top_k)

        for row in conn.execute(sql, params).fetchall():
            row_id = row["id"]
            if not any(r["id"] == row_id for r in results):
                results.append({
                    "id": row_id,
                    "content": f"{row['subject']}: {row['content']}",
                    "type": row["type"],
                    "subject": row["subject"],
                    "distance": 0.5,  # No real distance for keyword
                    "similarity": 0.5,
                    "source": "keyword",
                })

        conn.close()

        # Re-rank: combine raw similarity with recency and access boosts.
        # A frequently-used or recently-accessed memory should beat an
        # equally-similar but stale one. We re-fetch metadata for the
        # candidates in one query to keep this fast.
        results = self._rerank_with_recency(results)

        # Update access counts for returned memories
        if results:
            self._touch_memories([r["id"] for r in results[:top_k]])

        return results[:top_k]

    def _rerank_with_recency(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Boost similarity scores by recency and access count.

        score = similarity * 0.7 + recency_boost * 0.2 + access_boost * 0.1
        Where:
          recency_boost = 1.0 if accessed in last day, decaying to 0 after 90 days
          access_boost  = log-style scaling on access_count (capped)"""
        if not results:
            return results

        ids = [r["id"] for r in results]
        if not ids:
            return results

        try:
            conn = self._conn()
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id, last_accessed, access_count, importance "
                f"FROM memories WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            conn.close()
        except Exception:
            return results

        meta = {r["id"]: r for r in rows}
        now = datetime.now()
        rescored: List[Dict[str, Any]] = []
        for r in results:
            sim = r.get("similarity", 0.0)
            m = meta.get(r["id"])
            recency_boost = 0.0
            access_boost = 0.0
            importance_boost = 0.0
            if m:
                if m["last_accessed"]:
                    try:
                        ts = datetime.fromisoformat(m["last_accessed"])
                        days_old = max(0.0, (now - ts).total_seconds() / 86400.0)
                        # Gentle recency: fresh memories get the full boost, but
                        # the decay floors at 0.5 and stretches over a year, so
                        # an old-but-relevant memory still competes instead of
                        # being buried. Memory should be durable, not fade out.
                        recency_boost = max(0.5, 1.0 - days_old / 365.0)
                    except Exception:
                        pass
                ac = m["access_count"] or 0
                # Log-shape: 1 access = 0.2, 10 = 0.6, 100 = 1.0 (capped)
                access_boost = min(1.0, (ac ** 0.5) / 10.0)
                importance_boost = (m["importance"] or 0.5) - 0.5  # centred

            combined = (
                sim * 0.65
                + recency_boost * 0.15
                + access_boost * 0.10
                + max(0.0, importance_boost) * 0.10
            )
            r2 = dict(r)
            r2["combined_score"] = combined
            rescored.append(r2)

        rescored.sort(key=lambda x: x.get("combined_score", x.get("similarity", 0.0)), reverse=True)
        return rescored

    def _touch_memories(self, mem_ids: List[str]):
        """Update access time and count for retrieved memories."""
        conn = self._conn()
        now = datetime.now().isoformat()
        for mid in mem_ids:
            conn.execute("""
                UPDATE memories SET last_accessed = ?, access_count = access_count + 1
                WHERE id = ?
            """, (now, mid))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ Context injection

    def should_inject_context(self, messages: list) -> bool:
        """Decide whether to inject historical memory into this conversation.

        Always returns True. The facts block is cheap (a single SQL query
        against ~25 rows), the user-notes block likewise, and semantic search
        is sub-100ms against the local ChromaDB. The previous behaviour of
        skipping injection on long sessions (every 3rd turn) was the direct
        cause of "Blue forgets after a while" — between turns 21 and 60, only
        a third of messages got the facts block, so most of the time the
        model had no memory to draw on. Skipping injection is a false economy.
        """
        return True

    def build_context(self, messages: list, user_name: str = "Alex") -> List[Dict[str, str]]:
        """Build context messages to inject, combining core facts, semantic
        search, and recent (truly recent) conversation history.

        Order matters: core facts go in first because they're the most
        reliable signal — name, family, location, allergies, preferences.
        Semantic memories layer on top for topical relevance. Recent
        history is added last and only when fresh enough to be useful."""
        context_parts: List[Dict[str, str]] = []

        # Get the user's current message for semantic search
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "") or ""
                break

        # 1) ALWAYS inject core facts. This is the fix for "what is my name?"
        #    failing — facts were stored but never reached the prompt.
        facts_block = self._build_facts_block()
        if facts_block:
            context_parts.append({
                "role": "system",
                "content": facts_block,
            })

        # 1b) Inject explicit user-note memories ("please remember X").
        notes_block = self._build_user_notes_block()
        if notes_block:
            context_parts.append({
                "role": "system",
                "content": notes_block,
            })

        # 2) Semantic search for topically-relevant memories (skip if no anchor).
        if user_msg and len(user_msg.strip()) >= 3:
            relevant = self.search_memories(user_msg, top_k=TOP_K_CONTEXT)
            # Drop any memory whose content is already represented in the facts
            # block (avoid double-injection of the same name/location), and
            # any memory that looks like junk legacy extraction.
            facts_text = (facts_block or "").lower()
            filtered = []
            for mem in relevant:
                content_lower = (mem.get("content") or "").lower()
                subject_lower = (mem.get("subject") or "").lower()
                # Day-recaps surface through their own <remembered_days> block,
                # not here — keep them out of the generic relevance list.
                if mem.get("type") == "session":
                    continue
                if content_lower[:40] and content_lower[:40] in facts_text:
                    continue
                # Use memory-specific junk filter (much more conservative
                # than the fact filter — preserves JSON-encoded structured
                # memories that the fact filter would wrongly flag).
                if self._is_junk_memory(subject_lower, content_lower, mem.get("type", "")):
                    continue
                filtered.append(mem)

            if filtered:
                memory_lines = []
                for mem in filtered:
                    sim_pct = int(mem["similarity"] * 100)
                    snippet = mem["content"][:300]
                    memory_lines.append(f"- [{mem['type']}] {snippet} (relevance: {sim_pct}%)")

                context_parts.append({
                    "role": "system",
                    "content": (
                        "<relevant_memories>\n"
                        "Memories that may be relevant to the user's current message:\n"
                        + "\n".join(memory_lines) +
                        "\nUse these naturally if helpful — don't list them out."
                        "\n</relevant_memories>"
                    ),
                })

        # 2a) Proactive nudge: a memory so strongly relevant Blue should
        #     consider actively raising it, not just use it as background.
        if user_msg and len(user_msg.strip()) >= 4:
            proactive = self.get_proactive_memories(user_msg)
            if proactive:
                context_parts.append({
                    "role": "system",
                    "content": (
                        "<proactive_hint>\n"
                        "This came up before and is closely related to what "
                        "the user just said. Bring it up naturally only if it "
                        "would genuinely help — otherwise ignore it. Don't "
                        "force it, and don't present it as a fresh observation:\n"
                        + proactive +
                        "\n</proactive_hint>"
                    ),
                })

        # 2b) Session continuity — short recaps of the last few days so Blue
        #     has a thread of memory across conversations, not just within one.
        session_block = self._build_session_history_block()
        if session_block:
            context_parts.append({
                "role": "system",
                "content": session_block,
            })

        # 2b-ii) Long-term recall — an older day-recap pulled back by semantic
        #     relevance to the current message, reaching past the by-date window.
        if user_msg:
            recalled_block = self._build_recalled_days_block(user_msg)
            if recalled_block:
                context_parts.append({
                    "role": "system",
                    "content": recalled_block,
                })

        # 2c) Daily rhythms — mined behavioural patterns for this part of day,
        #     so Blue can anticipate rather than only react.
        rhythms_block = self._build_rhythms_block()
        if rhythms_block:
            context_parts.append({
                "role": "system",
                "content": rhythms_block,
            })

        # 2d) Cross-context connections — links between the upcoming schedule,
        #     recent conversation, and the document library, so Blue can join
        #     the dots unprompted (and notice when the user needs a hand).
        connections_block = self._build_connections_block(user_msg=user_msg)
        if connections_block:
            context_parts.append({
                "role": "system",
                "content": connections_block,
            })

        # 3) Recent conversation history — only if it's actually recent.
        #    Old code dumped 6 random old messages, which was just noise.
        recent = self._get_relevant_recent_history(user_name, user_msg, limit=8)
        if recent:
            now = datetime.now()
            history_lines = []
            for r in recent:
                role = r["role"].upper()
                content = (r["content"] or "")[:240]
                age = self._humanize_age(r.get("ts"), now)
                prefix = f"[{age}] " if age else ""
                history_lines.append(f"{prefix}{role}: {content}")

            context_parts.append({
                "role": "system",
                "content": (
                    "<recent_history>\n"
                    "Earlier turns, each tagged with how long ago it was said "
                    "(compare against the current time in <now>):\n"
                    + "\n".join(history_lines) +
                    "\n\nNote: statements about what the user is doing right then "
                    "(\"I'm out for a walk\", \"making dinner\") were only true "
                    "when said — if that was a while ago, it has likely ended, so "
                    "don't assume it's still happening.\n"
                    "</recent_history>"
                ),
            })

        return context_parts

    # Junk-value heuristics for filtering legacy garbage facts out of the
    # prompt. The legacy extractor stored the user's literal sentence as both
    # key (first ~30 chars normalized) and value, producing facts like
    # "going_forward_don_t_use_emojis -> going forward don't use emojis just speak".
    _JUNK_VALUE_PREFIXES = (
        "the name of", "the names of", "who's", "whos", "what's", "whats",
        "about ", "tell me", "do you ", "where ", "when ", "how ", "why ",
        "remember ", "remind me", "any other", "all the", "all t",
        "going forward", "from now on", "you ve got", "you've got",
        "i want you", "i need you", "i would like", "can you ",
        "you saw", "you should", "make sure", "be sure",
    )

    # A fact value must be a positive assertion. Values that begin with a
    # negation are corrections being mis-stored as facts — e.g. the user
    # saying "the dog's name is not Luna" must NEVER produce the fact
    # dog_name='not Luna'. The \b after each token avoids false positives
    # on real names ("Nori" starts with "no" but has no word boundary).
    _NEGATION_RE = re.compile(
        r"^(not|no|none|nobody|nothing|never|n/?a|unknown|unsure|"
        r"isn'?t|aren'?t|wasn'?t|weren'?t|don'?t|doesn'?t|didn'?t|"
        r"won'?t|can'?t|cannot|there(?:'?s| is| are)? no|"
        r"i don'?t know|idk)\b"
    )

    @classmethod
    def _is_junk_fact(cls, key: str, val: str) -> bool:
        """Heuristic for filtering low-quality facts that pollute the prompt."""
        # Reject empty/trivial values — but allow a lone digit, since a
        # single-digit age (e.g. vilda_age = "8") is a valid fact value.
        if not val or (len(val) < 2 and not val.isdigit()):
            return True

        key_norm = re.sub(r"[^a-z0-9]", "", key.lower())
        val_norm = re.sub(r"[^a-z0-9]", "", val.lower())

        # Echo: value is the same as the key, OR the key is the first chunk of
        # the value (which is exactly how the legacy extractor produced facts).
        if val_norm == key_norm:
            return True
        if key_norm and len(key_norm) >= 8 and val_norm.startswith(key_norm):
            return True

        val_lower = val.lower().strip()
        # Negation-shaped values are corrections, not facts. Reject them so
        # they neither get saved nor reach the <known_facts> prompt block.
        if cls._NEGATION_RE.match(val_lower):
            return True
        for prefix in cls._JUNK_VALUE_PREFIXES:
            if val_lower.startswith(prefix):
                return True

        # Over-captured: value contains a clause-joining pattern. Real fact
        # values are short atomic statements, not multi-clause sentences.
        if re.search(r"\b(and|but|so|then) (i|you|we|they|please|remember|don'?t|just)\b", val_lower):
            return True

        # Value reads like a question.
        if val_lower.endswith("?") or " what " in f" {val_lower} " or " who " in f" {val_lower} ":
            return True

        # Long sentence values are almost always junk (real facts are atomic).
        if len(val) > 80 and val.count(" ") > 8:
            return True

        return False

    # Order high-signal keys first so they're visible even after a 30-row cap.
    _PRIORITY_KEYS = (
        "user_name", "preferred_name", "name",
        "location", "city", "address", "timezone",
        "occupation", "workplace", "company", "business",
        "partner_name", "wife_name", "husband_name", "spouse_name",
        "daughter_name", "son_name", "child_name", "children_names",
        "mother_name", "father_name", "mom_name", "dad_name",
        "brother_name", "sister_name",
        "dog_name", "cat_name", "pet_name",
        "allergy", "dietary", "medical",
        "birthday", "age",
        "email", "phone",
    )

    # When multiple keys map to the same value, prefer the more specific key.
    # Maps "synonym key" -> "preferred key" so we drop the less-specific one.
    _KEY_PREFERENCE = {
        "wife_name": "partner_name",
        "husband_name": "partner_name",
        "spouse_name": "partner_name",
        "girlfriend_name": "partner_name",
        "boyfriend_name": "partner_name",
        "mom_name": "mother_name",
        "dad_name": "father_name",
        "kid_name": "child_name",
        "puppy_name": "dog_name",
        "kitten_name": "cat_name",
    }

    # Synonym keys collapsed onto one canonical key at SAVE time. Without
    # this, a fact fragments across rows — the dog ends up under both
    # dog_name and pet_name, so a correction updates one row while the
    # stale row keeps surfacing in <known_facts>. Collapsing means there is
    # always exactly one row per concept, and a new value updates it.
    _KEY_ALIASES = {
        "wife_name": "partner_name",
        "husband_name": "partner_name",
        "spouse_name": "partner_name",
        "girlfriend_name": "partner_name",
        "boyfriend_name": "partner_name",
        "mom_name": "mother_name",
        "mum_name": "mother_name",
        "dad_name": "father_name",
        "dog_name": "pet_name",
        "cat_name": "pet_name",
        "puppy_name": "pet_name",
        "kitten_name": "pet_name",
        "kid_name": "child_name",
        "kids_name": "child_name",
        "children_name": "child_name",
        "children_names": "child_name",
    }

    @classmethod
    def _normalize_fact_key(cls, key: str) -> str:
        """Map a synonym fact key onto its canonical key (see _KEY_ALIASES)."""
        k = (key or "").strip().lower()
        return cls._KEY_ALIASES.get(k, k)

    @classmethod
    def _are_synonym_keys(cls, a: str, b: str) -> bool:
        """True if two fact keys denote the same concept (e.g. wife_name and
        partner_name). Used so the render-time value-dedup collapses real
        synonyms but keeps genuinely distinct facts that happen to share a
        value — emmy_age and athena_age can both be "10"."""
        a, b = a.lower(), b.lower()
        if a == b:
            return True
        pref = cls._KEY_PREFERENCE
        ca, cb = pref.get(a, a), pref.get(b, b)
        return ca == cb or ca == b or cb == a

    # Facts that describe Blue itself rather than the user. These get stored
    # because the legacy migration shoved bot self-descriptions into the same
    # `facts` table, and they pollute the `<known_facts>` block (which is
    # framed as "things you know about the user"). Filter them at render time
    # so we don't have to do a destructive cleanup. Match exact key OR a
    # well-known prefix.
    _BOT_FACT_KEYS = frozenset({
        "name", "identity", "mood", "created_by", "privacy", "has_memory",
        "original_form", "physical_features", "hobby",
    })
    _BOT_FACT_PREFIXES = ("assistant_", "bot_", "blue_")

    @classmethod
    def _is_bot_fact(cls, key: str) -> bool:
        k = key.lower()
        if k in cls._BOT_FACT_KEYS:
            return True
        return any(k.startswith(p) for p in cls._BOT_FACT_PREFIXES)

    # Keys whose value is naturally a list (multiple kids, multiple pets, a
    # set of allergies). For these, a "new" value is an addition rather than
    # a contradiction — appending Emmy when daughter_name is already Athena
    # gives "Athena, Emmy", not "Emmy with Athena overwritten". The default
    # save_facts path overwrites, which is why Blue could only ever remember
    # the most recently mentioned daughter.
    _LIST_FACT_KEYS = frozenset({
        "daughter_name", "son_name", "child_name", "children_names",
        "kid_name", "stepson_name", "stepdaughter_name",
        "brother_name", "sister_name", "sibling_name",
        "dog_name", "cat_name", "pet_name", "puppy_name", "kitten_name",
        "allergy", "dietary",
    })

    @classmethod
    def _is_list_fact(cls, key: str) -> bool:
        return key.lower() in cls._LIST_FACT_KEYS

    @staticmethod
    def _split_list_value(value: str) -> List[str]:
        """Split a comma/pipe/semicolon delimited list value into clean items."""
        if not value:
            return []
        # Accept any of ',' '|' ';' as separators, also " and ".
        parts = re.split(r"\s*(?:,|\||;|\band\b)\s*", value)
        return [p.strip() for p in parts if p and p.strip()]

    @classmethod
    def _merge_list_value(cls, existing: str, new: str) -> Tuple[str, bool]:
        """Merge a new value into an existing comma-separated list value.

        Returns (merged_value, changed). `changed` is False when the new
        item was already present (case-insensitive) — caller can treat that
        as a confirmation rather than an update."""
        items = cls._split_list_value(existing)
        new_items = cls._split_list_value(new)
        existing_lower = {i.lower() for i in items}
        added = []
        for item in new_items:
            if item.lower() not in existing_lower:
                items.append(item)
                existing_lower.add(item.lower())
                added.append(item)
        return ", ".join(items), bool(added)

    def _build_facts_block(self) -> str:
        """Render the facts table as a structured system block.

        Filters out junk facts, dedupes by value (so "partner_name: Stella"
        and "wife_name: Stella" only show once), orders high-signal keys
        first, and prefers high-confidence facts. Returns empty string if
        nothing useful to show."""
        try:
            conn = self._conn()
            # Try the new schema first; fall back if columns are missing
            # (which can happen during a partial migration).
            try:
                rows = conn.execute(
                    """SELECT fact_key, fact_value, confidence, times_confirmed
                       FROM facts
                       ORDER BY confidence DESC, last_updated DESC"""
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT fact_key, fact_value FROM facts ORDER BY last_updated DESC"
                ).fetchall()
            conn.close()
        except Exception:
            return ""

        if not rows:
            return ""

        priority_set = set(self._PRIORITY_KEYS)
        seen_keys: set = set()
        # Facts we've decided to keep, as (key, val) pairs. Two facts with the
        # same value are collapsed ONLY when their keys are synonyms (e.g.
        # partner_name / wife_name = "Stella"). Distinct facts that merely
        # share a value (emmy_age and athena_age both "10") are BOTH kept —
        # the old value-only dedup silently dropped one of the children.
        kept: List[Tuple[str, str]] = []

        for r in rows:
            key = (r["fact_key"] or "").strip()
            val = (r["fact_value"] or "").strip()
            if not key or not val or len(val) > 300:
                continue
            if self._is_junk_fact(key, val):
                continue
            # Skip facts about Blue itself — the <known_facts> block is for
            # the USER, not the bot. Bot identity belongs in the system
            # preamble, not here.
            if self._is_bot_fact(key):
                continue
            key_lower = key.lower()
            if key_lower in seen_keys:
                continue
            seen_keys.add(key_lower)

            # Collapse a synonym key onto an already-kept fact of the same
            # value, keeping whichever key is more canonical.
            val_norm = val.lower()
            dup_idx = None
            for i, (k2, v2) in enumerate(kept):
                if v2.lower() == val_norm and self._are_synonym_keys(k2, key):
                    dup_idx = i
                    break
            if dup_idx is not None:
                if self._KEY_PREFERENCE.get(kept[dup_idx][0].lower()) == key_lower:
                    kept[dup_idx] = (key, val)
                continue

            kept.append((key, val))

        # Re-split into priority and other
        priority: List[Tuple[str, str]] = []
        other: List[Tuple[str, str]] = []
        for key, val in kept:
            if key.lower() in priority_set or any(
                p in key.lower() for p in ("_name", "name_", "_age")
            ):
                priority.append((key, val))
            else:
                other.append((key, val))

        clean = priority + other
        if not clean:
            return ""

        clean = clean[:25]  # cap to keep prompt size bounded

        # Mark these facts as 'used' so we can rank by access frequency later.
        # Done in a fire-and-forget background thread so it never blocks the
        # response path even if the DB is locked.
        keys_used = [k for k, _ in clean]
        if keys_used:
            threading.Thread(
                target=self._touch_facts_used,
                args=(keys_used,),
                daemon=True,
            ).start()

        lines = []
        for key, val in clean:
            label = key.replace('_', ' ').title()
            # If a list-fact key holds multiple comma-separated values, render
            # the label as plural so the model doesn't read "Daughter Name:
            # Athena, Emmy, Vilda" as a single name.
            if self._is_list_fact(key) and ',' in val and not label.endswith('s'):
                label = label + 's'
            lines.append(f"- {label}: {val}")
        return (
            "<known_facts>\n"
            "These are AUTHORITATIVE facts about the user. If anything in "
            "<relevant_memories> or <recent_history> contradicts a fact here, "
            "TRUST THE FACTS BELOW — those other blocks contain stale or "
            "incomplete entries. Use these naturally, don't recite them.\n"
            + "\n".join(lines) +
            "\n</known_facts>"
        )

    def _touch_facts_used(self, keys: List[str]) -> None:
        """Increment use_count and update last_used_at for facts that were
        included in the prompt. Best-effort; errors are swallowed."""
        if not keys:
            return
        try:
            conn = self._conn()
            now = datetime.now().isoformat()
            placeholders = ",".join("?" * len(keys))
            conn.execute(
                f"""
                UPDATE facts SET
                  use_count = COALESCE(use_count, 0) + 1,
                  last_used_at = ?
                WHERE fact_key IN ({placeholders})
                """,
                [now] + keys,
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _build_user_notes_block(self, limit: int = 10) -> str:
        """Surface explicit 'remember that ...' notes the user asked us to keep.

        These are stored as memories with type='user_note' and importance>=0.9.
        They're separate from semantic search because the user explicitly
        flagged them as important — we should always show them."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """
                SELECT subject, content FROM memories
                WHERE type = 'user_note' AND importance >= 0.85
                ORDER BY importance DESC, last_accessed DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            conn.close()
        except Exception:
            return ""

        if not rows:
            return ""

        seen: set = set()
        lines: List[str] = []
        for r in rows:
            content = (r["content"] or "").strip()
            if not content or len(content) < 4:
                continue
            sig = content.lower()[:80]
            if sig in seen:
                continue
            seen.add(sig)
            lines.append(f"- {content[:240]}")

        if not lines:
            return ""

        return (
            "<long_term_notes>\n"
            "Things the user explicitly asked you to remember:\n"
            + "\n".join(lines) +
            "\n</long_term_notes>"
        )

    # Phrases that indicate a Blue refusal / "I don't know" response. Including
    # these in recent_history is actively harmful: the next-turn model sees
    # "previously I admitted I don't know" and repeats the same wrong answer
    # even when the facts block has the real answer. Drop them.
    _ASSISTANT_REFUSAL_MARKERS = (
        "i don't have", "i do not have", "i dont have",
        "i don't know", "i do not know", "i dont know",
        "i only have", "i only know",
        "i haven't been told", "i havent been told",
        "you haven't told me", "you havent told me",
        "i don't see", "i dont see",
        "no information", "not yet recorded",
        "not in my memory", "not saved yet",
        "i'm not sure", "im not sure",
        # Self-deprecating "I have no memory" framings.
        "blank slate", "just woke up", "i just woke",
        "haven't met", "havent met", "have not met",
        "no information stored", "no information saved",
        "memory is blank", "memory is currently blank",
        "no details about", "no details on",
        "haven't stored", "havent stored",
        "my records are empty", "no records",
        "i'm new here", "im new here",
    )

    @classmethod
    def _is_assistant_refusal(cls, content: str) -> bool:
        if not content:
            return False
        c = content.lower()
        return any(marker in c for marker in cls._ASSISTANT_REFUSAL_MARKERS)

    def _get_relevant_recent_history(
        self, user_name: str, user_msg: str, limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Return recent conversation history that is BOTH fresh and useful.

        Filters out:
          - Stale messages (older than RECENT_HISTORY_HOURS)
          - Tool-output noise (JSON-like, code-block-only)
          - Trivial one-word messages
          - Blue refusal/uncertainty responses ("I don't have that yet…") —
            these anchor the next turn on past failure even when the facts
            block has the real answer.
        Returns oldest-first so the LLM sees a chronological flow."""
        try:
            cutoff = (datetime.now() - timedelta(hours=RECENT_HISTORY_HOURS)).isoformat()
            conn = self._conn()
            rows = conn.execute(
                """
                SELECT role, content, timestamp FROM conversation_log
                WHERE user_name = ? AND timestamp >= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_name, cutoff, limit * 3),  # over-fetch then filter
            ).fetchall()
            conn.close()
        except Exception:
            return []

        if not rows:
            return []

        out: List[Dict[str, Any]] = []
        for r in rows:
            content = (r["content"] or "").strip()
            if not content or len(content) < 4:
                continue
            if content.startswith(("{", "[", "```")):
                continue
            # Drop assistant refusals; keep the user turn that prompted them
            # so the surrounding flow still reads coherently.
            if r["role"] == "assistant" and self._is_assistant_refusal(content):
                continue
            out.append({"role": r["role"], "content": content,
                        "ts": r["timestamp"]})

        # Reverse to chronological order (we ORDER BY id DESC above)
        out = list(reversed(out))
        return out[-limit:]

    @staticmethod
    def _humanize_age(ts_iso: Optional[str], now: Optional[datetime] = None) -> str:
        """Turn a stored ISO timestamp into a relative age phrase so the model
        knows WHEN something was said: 'just now', '20 min ago', 'an hour ago',
        '3 hours ago', 'yesterday', '2 days ago'. Empty string if unparseable."""
        if not ts_iso:
            return ""
        try:
            ts = datetime.fromisoformat(ts_iso)
        except (ValueError, TypeError):
            return ""
        now = now or datetime.now()
        secs = (now - ts).total_seconds()
        if secs < 60:
            return "just now"
        mins = secs / 60
        if mins < 60:
            return f"{int(round(mins))} min ago"
        hrs = mins / 60
        if hrs < 24:
            h = int(round(hrs))
            return "an hour ago" if h == 1 else f"{h} hours ago"
        days = int(hrs // 24)
        return "yesterday" if days == 1 else f"{days} days ago"

    # ------------------------------------------------------------------ Cleanup utilities

    def cleanup_junk_facts(self, dry_run: bool = True) -> Dict[str, Any]:
        """Find and optionally remove junk facts from the DB.

        Junk = facts where _is_junk_fact() returns True. These are filtered
        from the prompt anyway, but cleaning the DB makes everything faster
        and easier to inspect.

        Args:
            dry_run: If True (default), only report what would be deleted.
                     Pass False to actually delete.

        Returns dict with counts and a sample of affected rows."""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT fact_key, fact_value FROM facts"
            ).fetchall()
        except Exception as e:
            return {"error": str(e)}

        junk_keys: List[str] = []
        sample: List[Dict[str, str]] = []
        for r in rows:
            key = (r["fact_key"] or "").strip()
            val = (r["fact_value"] or "").strip()
            if not key:
                continue
            if self._is_junk_fact(key, val):
                junk_keys.append(key)
                if len(sample) < 10:
                    sample.append({"key": key, "value": val[:80]})

        result = {
            "total_facts": len(rows),
            "junk_count": len(junk_keys),
            "sample": sample,
            "dry_run": dry_run,
            "deleted": 0,
        }

        if not dry_run and junk_keys:
            placeholders = ",".join("?" * len(junk_keys))
            conn.execute(
                f"DELETE FROM facts WHERE fact_key IN ({placeholders})",
                junk_keys,
            )
            conn.commit()
            result["deleted"] = len(junk_keys)
            print(f"   [MEM-CLEAN] Deleted {len(junk_keys)} junk facts")

        conn.close()
        return result

    @classmethod
    def _is_junk_memory(cls, subject: str, content: str, mem_type: str = "") -> bool:
        """Memory-specific junk heuristic.

        MUCH more conservative than _is_junk_fact because memories store
        legitimate long-form content (JSON-encoded person records, place
        descriptions, observations). The fact-junk heuristic would wrongly
        flag those.

        A memory is junk only if:
          - Subject or content is empty/trivially short
          - Content is an exact echo of the subject (e.g. legacy
            "remember that ..." entries that filled both fields with the
            same sentence)
          - Content reads like a question ("what's my name?", "do you
            remember the name of our dog?") — those came from the legacy
            extractor capturing the user's question as if it were a fact
        Important: we do NOT flag long sentences, multi-clause text, or
        JSON content as junk — those are legitimate memory shapes."""
        if not subject or not content:
            return True
        if len(content.strip()) < 4:
            return True

        subject_norm = re.sub(r"[^a-z0-9]", "", subject.lower())
        content_norm = re.sub(r"[^a-z0-9]", "", content.lower())

        # Echo: subject and content are literally the same string
        if subject_norm and subject_norm == content_norm:
            return True
        # Echo: subject is the first chunk of content (legacy bug pattern)
        if (
            len(subject_norm) >= 8
            and content_norm.startswith(subject_norm)
            and len(content_norm) - len(subject_norm) <= 5
        ):
            return True

        content_lower = content.strip().lower()
        # Question-shaped content (user's question got stored as memory)
        if content_lower.endswith("?"):
            return True
        question_starts = (
            "what is", "whats ", "what's ", "what are", "what did",
            "do you remember", "do you know", "can you remember",
            "where is", "where's", "who is ", "who's ",
            "remember the name of", "remember what",
        )
        for q in question_starts:
            if content_lower.startswith(q):
                return True

        return False

    def cleanup_junk_memories(self, dry_run: bool = True) -> Dict[str, Any]:
        """Remove junk memories using the memory-specific heuristic.

        This is intentionally conservative — only obvious junk is flagged,
        because memories legitimately contain JSON, long descriptions, and
        multi-clause text. If you want to see what's about to be removed,
        leave dry_run=True and inspect the sample first."""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, type, subject, content FROM memories"
            ).fetchall()
        except Exception as e:
            return {"error": str(e)}

        junk_ids: List[str] = []
        sample: List[Dict[str, str]] = []
        for r in rows:
            mem_id = r["id"]
            mem_type = (r["type"] or "")
            subject = (r["subject"] or "").strip()
            content = (r["content"] or "").strip()
            if not mem_id:
                continue
            # Never delete person/place/preference records — those are
            # high-value structured memories regardless of shape.
            if mem_type in ("person", "place", "preference"):
                continue

            # Type-specific junk detection:
            #   - 'fact' memories should look like facts (key + atomic value),
            #     so the aggressive _is_junk_fact heuristic is appropriate.
            #     Most existing junk is here: legacy "remember that ..."
            #     entries that stored the user's full sentence as both
            #     subject (first 30 chars) and content (full sentence).
            #   - Other types (observation, user_note, etc.) get the
            #     conservative heuristic so we don't kill JSON or long
            #     descriptions.
            if mem_type == "fact":
                is_junk = self._is_junk_fact(subject, content)
            else:
                is_junk = self._is_junk_memory(subject, content, mem_type)

            if is_junk:
                junk_ids.append(mem_id)
                if len(sample) < 10:
                    sample.append({
                        "id": mem_id,
                        "type": mem_type,
                        "subject": subject,
                        "content": content[:80],
                    })

        result = {
            "total_memories": len(rows),
            "junk_count": len(junk_ids),
            "sample": sample,
            "dry_run": dry_run,
            "deleted": 0,
        }

        if not dry_run and junk_ids:
            placeholders = ",".join("?" * len(junk_ids))
            conn.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders})",
                junk_ids,
            )
            conn.commit()
            result["deleted"] = len(junk_ids)

            # Also remove from ChromaDB
            collection = _get_memory_collection()
            if collection:
                try:
                    collection.delete(ids=junk_ids)
                except Exception:
                    pass
            print(f"   [MEM-CLEAN] Deleted {len(junk_ids)} junk memories")

        conn.close()
        return result

    def cleanup_all(self, dry_run: bool = True) -> Dict[str, Any]:
        """Run both fact and memory cleanup. Convenience method."""
        return {
            "facts": self.cleanup_junk_facts(dry_run=dry_run),
            "memories": self.cleanup_junk_memories(dry_run=dry_run),
        }

    def forget_fact(self, fact_key: str) -> bool:
        """Delete a specific fact by key. Useful when the user says
        "forget that I live in X" or similar."""
        try:
            conn = self._conn()
            cur = conn.execute("DELETE FROM facts WHERE fact_key = ?", (fact_key,))
            conn.commit()
            deleted = cur.rowcount
            conn.close()
            return deleted > 0
        except Exception:
            return False

    def get_proactive_memories(self, user_message: str) -> Optional[str]:
        """Find memories so strongly relevant to the current message that
        Blue should consider actively raising them — a "by the way…" nudge
        rather than passive background. Returns a hint string, or None.

        Distinct from the broad <relevant_memories> injection: it uses a
        tighter similarity threshold (PROACTIVE_SIMILARITY_THRESHOLD) so it
        fires rarely, and it drops junk memories so a nudge is trustworthy.
        """
        if not user_message or len(user_message.strip()) < 4:
            return None
        collection = _get_memory_collection()
        if collection is None or collection.count() == 0:
            return None

        try:
            results = collection.query(
                query_texts=[user_message],
                n_results=4,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"   [MEM-PROACTIVE] Error: {e}")
            return None

        if not results or not results.get("distances") or not results["distances"][0]:
            return None

        hints: List[str] = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            if dist > PROACTIVE_SIMILARITY_THRESHOLD:
                continue
            content = (doc or "").strip()
            subject = (meta.get("subject") or "")
            mtype = meta.get("type", "")
            # Same junk filter as <relevant_memories> — never nudge with garbage.
            if not content or self._is_junk_memory(
                subject.lower(), content.lower(), mtype
            ):
                continue
            hints.append(f"- {content[:160]}")
            if len(hints) >= 2:
                break

        return "\n".join(hints) if hints else None

    # ------------------------------------------------------------------ Consolidation & decay

    def consolidate_if_needed(self, user_name: str = "Alex"):
        """Periodically consolidate and decay memories."""
        self._turn_counter += 1

        if self._turn_counter - self._last_consolidation < CONSOLIDATION_INTERVAL:
            return

        self._last_consolidation = self._turn_counter
        print("   [MEM-CONSOLIDATE] Running periodic memory consolidation...")

        self._decay_old_memories()
        self._merge_duplicate_memories()
        self._prune_low_value_memories()

    def _decay_old_memories(self):
        """Reduce decay_score for memories not accessed recently."""
        conn = self._conn()
        cutoff = (datetime.now() - timedelta(days=DECAY_DAYS)).isoformat()

        conn.execute("""
            UPDATE memories
            SET decay_score = MAX(0.1, decay_score * 0.9)
            WHERE last_accessed < ? AND importance < 0.8
        """, (cutoff,))

        affected = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        conn.close()

        if affected:
            print(f"   [MEM-DECAY] Decayed {affected} old memories")

    def _merge_duplicate_memories(self):
        """Find memories with the same subject and merge them."""
        conn = self._conn()

        # Find subjects with multiple entries of the same type
        dupes = conn.execute("""
            SELECT type, subject, COUNT(*) as cnt
            FROM memories
            GROUP BY type, subject
            HAVING cnt > 1
        """).fetchall()

        merged = 0
        for dupe in dupes:
            rows = conn.execute("""
                SELECT id, content, importance, access_count, created_at
                FROM memories
                WHERE type = ? AND subject = ?
                ORDER BY importance DESC, access_count DESC, created_at DESC
            """, (dupe["type"], dupe["subject"])).fetchall()

            if len(rows) <= 1:
                continue

            # Keep the best one, merge content from others
            best = rows[0]
            contents = [best["content"]]
            ids_to_delete = []

            for row in rows[1:]:
                if row["content"] not in contents:
                    contents.append(row["content"])
                ids_to_delete.append(row["id"])

            # Update the best with merged content (if different)
            if len(contents) > 1:
                merged_content = " | ".join(c[:200] for c in contents[:3])
                conn.execute(
                    "UPDATE memories SET content = ? WHERE id = ?",
                    (merged_content, best["id"]),
                )

            # Delete the duplicates
            for del_id in ids_to_delete:
                conn.execute("DELETE FROM memories WHERE id = ?", (del_id,))
                # Also remove from ChromaDB
                collection = _get_memory_collection()
                if collection:
                    try:
                        collection.delete(ids=[del_id])
                    except Exception:
                        pass

            merged += len(ids_to_delete)

        conn.commit()
        conn.close()

        if merged:
            print(f"   [MEM-MERGE] Merged {merged} duplicate memories")

    def _prune_low_value_memories(self):
        """Sweep genuine junk only — never real episodic memories.

        Blue asked for durable, long-term memory: an old, low-importance,
        never-accessed memory ("Emmy was nervous about her recital") is
        exactly the kind of thing that builds a richer picture of the family,
        so it must NOT be deleted just for being old and quiet. This used to
        hard-delete on age + low importance, which was the structural cause
        of memory "fading". Now it only removes entries the junk heuristic
        flags (legacy extractor noise — echoes, stored questions)."""
        conn = self._conn()

        rows = conn.execute(
            "SELECT id, subject, content, type FROM memories "
            "WHERE type NOT IN ('person', 'fact')"
        ).fetchall()

        junk_ids = [
            r["id"] for r in rows
            if self._is_junk_memory(
                (r["subject"] or "").lower(),
                (r["content"] or "").lower(),
                r["type"] or "",
            )
        ]

        if junk_ids:
            conn.execute(
                f"DELETE FROM memories WHERE id IN ({','.join('?' * len(junk_ids))})",
                junk_ids,
            )
            conn.commit()

            # Remove from ChromaDB
            collection = _get_memory_collection()
            if collection:
                try:
                    collection.delete(ids=junk_ids)
                except Exception:
                    pass

            print(f"   [MEM-PRUNE] Removed {len(junk_ids)} junk memories "
                  f"(real memories kept — recall is durable)")

        conn.close()

    # ------------------------------------------------------------------ Conversation logging

    def log_conversation(self, user_name: str, role: str, content: str,
                         session_id: str = None, importance: int = 5):
        """Log a conversation message for context building."""
        conn = self._conn()
        conn.execute("""
            INSERT INTO conversation_log (timestamp, user_name, role, content, session_id, importance)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), user_name, role, content, session_id, importance))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ Session continuity

    # Each calendar day is treated as one "session". Past days get a short
    # recap in session_summaries; the recent few are injected so Blue has a
    # thread of memory across days instead of resetting every conversation.

    _SUMMARY_STOPWORDS = frozenset("""
        the a an and or but if then to of in on at for with from is are was
        were be been being have has had do does did will would can could
        should i you he she it we they me my your his her our their this that
        these those what when where who how why not no yes ok okay so just
        like get got go going know think want need also here there about
        blue alex""".split())

    def _fallback_summary(self, transcript: str) -> Tuple[str, str]:
        """Deterministic recap used when the LLM summary call is unavailable —
        just the most frequent meaningful words. Weak but never fabricates."""
        freq: Dict[str, int] = {}
        for w in re.findall(r"[a-zA-Z]{4,}", transcript.lower()):
            if w in self._SUMMARY_STOPWORDS:
                continue
            freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=lambda w: freq[w], reverse=True)[:6]
        if not top:
            return "", ""
        topics = ", ".join(top)
        return f"Conversation touching on {topics}.", topics

    def _summarize_transcript(self, transcript: str,
                              session_date: str) -> Tuple[str, str]:
        """Return (summary, topics) for a day's transcript. Tries the local
        LLM (grounded — it summarises real transcript text), falls back to a
        keyword recap if the LLM is unavailable or returns junk."""
        if LLM_EXTRACTION_ENABLED and transcript.strip():
            # Serialise against fact extraction — LM Studio is single-request.
            if _LLM_EXTRACTION_LOCK.acquire(blocking=False):
                try:
                    prompt = (
                        "Summarize this conversation between a user and their "
                        "home assistant. Output JSON: "
                        "{\"summary\": \"1-2 plain sentences on what the user "
                        "did, asked about, or shared\", "
                        "\"topics\": [\"up to 5 short keywords\"]}\n"
                        "Summarize ONLY what appears below — do not invent "
                        "anything that is not in the text.\n\n"
                        f"CONVERSATION ({session_date}):\n{transcript}\n\nJSON:"
                    )
                    raw = _llm_extract(prompt, timeout=LLM_EXTRACTION_TIMEOUT)
                finally:
                    _LLM_EXTRACTION_LOCK.release()
                if raw:
                    raw = raw.strip()
                    if raw.startswith("```"):
                        raw = re.sub(r"^```(?:json)?\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                    try:
                        data = json.loads(raw)
                        summary = (data.get("summary") or "").strip()[:400]
                        topics = data.get("topics") or []
                        if isinstance(topics, list):
                            topics_str = ", ".join(
                                str(t).strip() for t in topics if str(t).strip()
                            )[:200]
                        else:
                            topics_str = str(topics).strip()[:200]
                        if summary:
                            return summary, topics_str
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
        return self._fallback_summary(transcript)

    def summarize_session(self, session_date: str) -> bool:
        """Build and store a recap of one calendar day's conversation.

        Always writes a row (even an empty-summary one for a day with no
        usable content) so the day is never reprocessed in a loop."""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT role, content FROM conversation_log "
                "WHERE substr(timestamp, 1, 10) = ? ORDER BY id ASC",
                (session_date,),
            ).fetchall()
            conn.close()
        except Exception:
            return False

        lines: List[str] = []
        for r in rows:
            content = (r["content"] or "").strip()
            if not content or len(content) < 4:
                continue
            if content.startswith(("{", "[", "```")):
                continue
            lines.append(f"{(r['role'] or '').upper()}: {content[:300]}")
        transcript = "\n".join(lines)
        # Cap to the most recent slice so a very chatty day still fits the
        # LLM's context budget.
        if len(transcript) > 4000:
            transcript = transcript[-4000:]

        if transcript.strip():
            summary, topics = self._summarize_transcript(transcript, session_date)
        else:
            summary, topics = "", ""

        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO session_summaries "
                "(session_id, summary, topics, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "summary = excluded.summary, topics = excluded.topics, "
                "created_at = excluded.created_at",
                (session_date, summary, topics, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
        except Exception:
            return False
        # Index the recap as a semantically-searchable memory so this day can
        # resurface by relevance long after it scrolls out of the by-date window.
        if summary:
            self._index_session_memory(session_date, summary, topics)
            print(f"   [MEM-SESSION] Summarized {session_date}: {summary[:60]}")
        return True

    def _index_session_memory(self, session_date: str, summary: str,
                              topics: str) -> None:
        """Store one day's recap as a 'session'-type memory so semantic
        search can surface it long after it scrolls past the by-date window.
        Idempotent — _store_memory upserts by content hash."""
        if not summary or not summary.strip():
            return
        content = summary.strip()
        if topics and topics.strip():
            content = f"{content} (topics: {topics.strip()})"
        try:
            self._store_memory(
                mem_type="session",
                subject=f"conversation on {session_date}",
                content=content,
                source="session_summary",
                importance=0.6,
                created_at=f"{session_date}T12:00:00",
            )
        except Exception as e:
            print(f"   [MEM-SESSION] index failed for {session_date}: {e}")

    def backfill_session_memories(self) -> int:
        """One-shot: index every existing day-recap as a 'session' memory.

        Catches up day-recaps written before recaps were made semantically
        searchable. Runs once per process (flag-guarded); _store_memory
        upserts, so a re-run would be harmless anyway. Cheap no-op after the
        first call — safe to call every turn from the background thread."""
        if self._session_mem_backfilled:
            return 0
        self._session_mem_backfilled = True
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT session_id, summary, topics FROM session_summaries "
                "WHERE summary IS NOT NULL AND summary != ''"
            ).fetchall()
            conn.close()
        except Exception:
            return 0
        for r in rows:
            self._index_session_memory(
                r["session_id"], r["summary"], r["topics"] or "")
        if rows:
            print(f"   [MEM-SESSION] Backfilled {len(rows)} day-recaps into "
                  f"semantic memory")
        return len(rows)

    def _unsummarized_session_date(self) -> Optional[str]:
        """Most recent past day (within SESSION_HISTORY_DAYS) that has
        conversation rows but no summary yet. None once caught up."""
        try:
            conn = self._conn()
            today = datetime.now().date()
            floor = (today - timedelta(days=SESSION_HISTORY_DAYS)).isoformat()
            row = conn.execute(
                "SELECT substr(timestamp, 1, 10) AS d FROM conversation_log "
                "WHERE substr(timestamp, 1, 10) < ? "
                "AND substr(timestamp, 1, 10) >= ? "
                "AND substr(timestamp, 1, 10) NOT IN "
                "(SELECT session_id FROM session_summaries) "
                "GROUP BY d ORDER BY d DESC LIMIT 1",
                (today.isoformat(), floor),
            ).fetchone()
            conn.close()
            return row["d"] if row else None
        except Exception:
            return None

    def summarize_previous_sessions(self, max_per_call: int = 1) -> int:
        """Summarize up to max_per_call un-summarized past days, newest first.
        Cheap no-op (a single SQL check) once caught up — safe to call every
        turn from a background thread; it backfills one day per turn."""
        done = 0
        for _ in range(max(1, max_per_call)):
            day = self._unsummarized_session_date()
            if not day:
                break
            if self.summarize_session(day):
                done += 1
            else:
                break
        return done

    def _friendly_day_label(self, date_str: str) -> str:
        """'today' / 'tomorrow' / 'Yesterday' / '3 days ago (Monday)' /
        'Wednesday May 20' — works for past and future dates."""
        try:
            d = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            return date_str
        delta = (datetime.now().date() - d).days
        if delta == 0:
            return "today"
        if delta == -1:
            return "tomorrow"
        if delta == 1:
            return "Yesterday"
        if 2 <= delta <= 6:
            return f"{delta} days ago ({d.strftime('%A')})"
        return d.strftime("%A %b ") + str(d.day)

    def _build_session_history_block(self) -> str:
        """Recaps of the last few days' conversations, for cross-day
        continuity. Empty string when there's nothing to show."""
        try:
            conn = self._conn()
            today = datetime.now().date().isoformat()
            rows = conn.execute(
                "SELECT session_id, summary FROM session_summaries "
                "WHERE session_id < ? AND summary IS NOT NULL AND summary != '' "
                "ORDER BY session_id DESC LIMIT ?",
                (today, SESSION_HISTORY_INJECT),
            ).fetchall()
            conn.close()
        except Exception:
            return ""
        if not rows:
            return ""
        lines = []
        for r in rows:
            label = self._friendly_day_label(r["session_id"])
            lines.append(f"- {label}: {r['summary'][:300]}")
        return (
            "<earlier_sessions>\n"
            "Recaps of recent conversations — rough context for continuity "
            "(topics discussed, not verified facts; don't recite these):\n"
            + "\n".join(lines) +
            "\n</earlier_sessions>"
        )

    def _build_recalled_days_block(self, user_msg: str) -> str:
        """Surface an older day-recap that is topically relevant to what the
        user just said.

        <earlier_sessions> only shows the last few days by date; this reaches
        further back by semantic relevance, so a conversation from weeks or
        months ago can resurface when its topic comes up again. This is the
        durable, long-term recall Blue asked for. Empty string when nothing
        old enough matches."""
        if not user_msg or len(user_msg.strip()) < 5:
            return ""
        try:
            hits = self.search_memories(user_msg, top_k=2, mem_type="session")
        except Exception:
            return ""
        if not hits:
            return ""
        # Skip days already shown by date in <earlier_sessions> so the two
        # blocks don't echo each other — this block is for older context only.
        recent_floor = (datetime.now().date()
                        - timedelta(days=SESSION_HISTORY_INJECT)).isoformat()
        lines: List[str] = []
        seen: set = set()
        for h in hits:
            subj = h.get("subject") or ""
            m = re.search(r"(\d{4}-\d{2}-\d{2})", subj)
            if not m:
                continue
            day = m.group(1)
            if day >= recent_floor or day in seen:
                continue
            seen.add(day)
            content = (h.get("content") or "").strip()
            prefix = f"{subj}:"
            if content.startswith(prefix):
                content = content[len(prefix):].strip()
            lines.append(f"- {self._friendly_day_label(day)}: {content[:280]}")
        if not lines:
            return ""
        return (
            "<remembered_days>\n"
            "From further back — a past day's recap that resurfaced because it "
            "relates to what the user just said. Rough context for continuity, "
            "not a verified fact; weave it in naturally only if it genuinely "
            "helps, and don't recite it:\n"
            + "\n".join(lines) +
            "\n</remembered_days>"
        )

    # ------------------------------------------------------------------ Rhythm learning

    # Behavioural rhythms are mined by COUNTING, never by asking the LLM —
    # the iron rule for anything proactive. Each user message is classified
    # into a category by keyword; clusters of (category, part-of-day) that
    # recur across enough distinct days become a "rhythm".

    _RHYTHM_CATEGORIES = (
        ("lights",    ("light", "lamp", "brightness", "dim ", "galaxy mood")),
        ("music",     ("play ", " music", "song", "pause the", "skip ", "volume", "spotify")),
        ("schedule",  ("remind", "reminder", "meeting", "schedule", "calendar",
                       "appointment", "agenda", "what's on")),
        ("documents", ("document", "library", "summarize", "the file", " pdf", "read the")),
        ("email",     ("email", "e-mail", "gmail", "inbox")),
        ("weather",   ("weather", "forecast", "temperature", "going to rain", "is it raining")),
        ("dog",       ("nori", "good boy", "the dog", "puppy", "pooch")),
        ("web",       ("search for", "look up", "navigate to", "google ", "web search")),
        ("time",      ("what time", "the time", "the date", "what day is")),
        ("checkin",   ("good morning", "good night", "good evening", "how are you",
                       "can you hear me", "hello", "hey there", "you doing")),
    )

    _RHYTHM_PHRASES = {
        "lights": "adjusting the lights",
        "music": "putting on music",
        "schedule": "checking reminders or the schedule",
        "documents": "working with documents",
        "email": "dealing with email",
        "weather": "asking about the weather",
        "dog": "spending time with Nori",
        "web": "asking you to look something up",
        "time": "asking the time or date",
        "checkin": "greeting you / checking in",
    }

    @staticmethod
    def _part_of_day(hour: int) -> str:
        if 5 <= hour < 11:
            return "morning"
        if 11 <= hour < 14:
            return "midday"
        if 14 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 22:
            return "evening"
        return "night"

    @classmethod
    def _classify_message(cls, content: str) -> Optional[str]:
        """Bucket a user message into a rhythm category by keyword, or None."""
        text = " " + (content or "").lower().strip() + " "
        if len(text) < 6:
            return None
        for category, keywords in cls._RHYTHM_CATEGORIES:
            if any(k in text for k in keywords):
                return category
        return None

    def update_rhythms(self) -> int:
        """Recompute behavioural rhythms from conversation history.

        Pure counting, no LLM. A rhythm is a (category, part-of-day) bucket
        the user has hit on at least RHYTHM_MIN_DAYS distinct days. Recomputed
        wholesale (DELETE + INSERT) so it's idempotent. Returns the count."""
        cutoff = (datetime.now() - timedelta(days=RHYTHM_WINDOW_DAYS)).isoformat()
        try:
            conn = self._conn()
        except Exception:
            return 0
        try:
            rows = conn.execute(
                "SELECT timestamp, content FROM conversation_log "
                "WHERE role = 'user' AND timestamp >= ?",
                (cutoff,),
            ).fetchall()

            buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
            active_days: set = set()
            for r in rows:
                try:
                    dt = datetime.fromisoformat(r["timestamp"])
                except (ValueError, TypeError):
                    continue
                day = dt.date().isoformat()
                active_days.add(day)
                category = self._classify_message(r["content"])
                if not category:
                    continue
                key = (category, self._part_of_day(dt.hour))
                b = buckets.setdefault(key, {"obs": 0, "days": set()})
                b["obs"] += 1
                b["days"].add(day)

            total_active = max(1, len(active_days))
            now_iso = datetime.now().isoformat()
            rhythms = []
            for (category, part), b in buckets.items():
                distinct = len(b["days"])
                if distinct < RHYTHM_MIN_DAYS:
                    continue
                confidence = round(min(1.0, distinct / total_active), 2)
                rhythms.append(
                    (category, part, b["obs"], distinct, confidence, now_iso)
                )

            conn.execute("DELETE FROM routines")
            if rhythms:
                conn.executemany(
                    "INSERT INTO routines (category, part_of_day, observations, "
                    "distinct_days, confidence, updated_at) VALUES (?,?,?,?,?,?)",
                    rhythms,
                )
            conn.commit()
            print(f"   [MEM-RHYTHM] {len(rhythms)} pattern(s) from {len(rows)} "
                  f"messages over {total_active} active day(s)")
            return len(rhythms)
        except Exception as e:
            print(f"   [MEM-RHYTHM] update failed: {e}")
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update_rhythms_if_due(self) -> None:
        """Recompute rhythms at most every RHYTHM_UPDATE_INTERVAL seconds —
        cheap to call every turn from the background thread. Runs once
        immediately after a restart (counter starts at 0)."""
        now = time.time()
        if now - self._last_rhythm_update < RHYTHM_UPDATE_INTERVAL:
            return
        self._last_rhythm_update = now
        self.update_rhythms()

    def _build_rhythms_block(self, now: Optional[datetime] = None) -> str:
        """Surface the rhythms relevant to the current part of day, so Blue
        can anticipate naturally. Empty string when none are known yet."""
        now = now or datetime.now()
        part = self._part_of_day(now.hour)
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT category, observations, distinct_days, confidence "
                "FROM routines WHERE part_of_day = ? "
                "ORDER BY confidence DESC, observations DESC LIMIT 5",
                (part,),
            ).fetchall()
            conn.close()
        except Exception:
            return ""
        if not rows:
            return ""
        lines = []
        for r in rows:
            phrase = self._RHYTHM_PHRASES.get(r["category"], r["category"])
            lines.append(f"- {phrase} (on {r['distinct_days']} recent days)")
        return (
            "<daily_rhythms>\n"
            f"How the household tends to use you in the {part} — statistical "
            "tendencies mined from recent weeks, NOT certainties or scheduled "
            "events. Use them to be helpful naturally (anticipate, gently "
            "offer) but never assume; if one doesn't fit the moment, ignore it:\n"
            + "\n".join(lines) +
            "\n</daily_rhythms>"
        )

    # ------------------------------------------------------------------ Cross-context connections

    # The "connect the dots" layer. It correlates the upcoming schedule with
    # what's been discussed recently, how the user has been feeling, and the
    # document library — deterministically, by date and keyword matching over
    # real reminder rows, real session recaps, and real files. The LLM only
    # phrases a connection a rule found; it never decides one exists. When a
    # connection carries a suggested action (dim the lights, focus music),
    # Blue offers it and waits for a yes — it never acts unprompted.

    # Generic scheduling words and titles that carry no topic signal —
    # skipped when pulling keywords out of an event title.
    _EVENT_STOPWORDS = frozenset(
        "meeting with the a an and at for to of on or my our your "
        "appointment appt reminder call practice class session event "
        "time day today tomorrow morning evening afternoon night get set "
        "schedule doctor dr drs professor prof mr mrs ms sir madam".split()
    )

    # Words/phrases that signal the user is stressed, anxious, or dreading
    # something — used to spot when an upcoming event is weighing on them so
    # Blue can gently offer a calming hand. Deterministic, not LLM-judged.
    _CONCERN_RE = re.compile(
        r"\b(stress(?:ed|ful|ing)?|anxious|anxiety|nervous|worried|worrying|"
        r"worry|overwhelmed|swamped|dread(?:ing|ed)?|freaking out|on edge|"
        r"can'?t stop thinking|losing sleep|can'?t sleep|under pressure|"
        r"so much pressure|panic(?:king|ked)?|scared about|tense about|"
        r"not looking forward|stressing about)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _event_keywords(cls, title: str) -> List[str]:
        """Distinctive words from an event title — names, topics, course
        codes — for matching against recent conversation."""
        out: List[str] = []
        for raw in re.split(r"[^A-Za-z0-9]+", title or ""):
            w = raw.strip()
            if not w or w.lower() in cls._EVENT_STOPWORDS:
                continue
            # Keep: 5+ char words, capitalised names (4+), or anything with a
            # digit (course codes like CS240). Short generic words are skipped.
            if (len(w) >= 5
                    or (w[0].isupper() and len(w) >= 4)
                    or any(c.isdigit() for c in w)):
                out.append(w)
        return out

    def _recent_context_text(self, now: datetime) -> str:
        """A blob of what's been discussed recently — session recaps plus
        recent user messages — for keyword-matching against the schedule."""
        parts: List[str] = []
        try:
            conn = self._conn()
            day_floor = (now.date() - timedelta(days=CONNECTION_RECENT_DAYS)).isoformat()
            for r in conn.execute(
                "SELECT summary, topics FROM session_summaries "
                "WHERE session_id >= ?",
                (day_floor,),
            ).fetchall():
                parts.append((r["summary"] or "") + " " + (r["topics"] or ""))
            ts_floor = (now - timedelta(days=CONNECTION_RECENT_DAYS)).isoformat()
            for r in conn.execute(
                "SELECT content FROM conversation_log "
                "WHERE role = 'user' AND timestamp >= ? "
                "ORDER BY id DESC LIMIT 100",
                (ts_floor,),
            ).fetchall():
                parts.append(r["content"] or "")
            conn.close()
        except Exception:
            return ""
        return " ".join(parts).lower()

    def _recent_user_messages(self, now: datetime) -> List[str]:
        """Recent user messages, newest first — for spotting how the user has
        been feeling, not just what topics came up."""
        out: List[str] = []
        try:
            conn = self._conn()
            ts_floor = (now - timedelta(days=CONNECTION_RECENT_DAYS)).isoformat()
            for r in conn.execute(
                "SELECT content FROM conversation_log "
                "WHERE role = 'user' AND timestamp >= ? "
                "ORDER BY id DESC LIMIT 80",
                (ts_floor,),
            ).fetchall():
                c = (r["content"] or "").strip()
                if c:
                    out.append(c)
            conn.close()
        except Exception:
            return []
        return out

    def _library_documents(self) -> List[str]:
        """Filenames in the user's real document library, camera frames and
        bare images filtered out (those pollute the index and never relate to
        a calendar event). Used to link a stored document to an upcoming
        event — 'you have the syllabus for that class'."""
        try:
            from config import DATA_DIR
            index_path = Path(DATA_DIR).parent / "document_index.json"
        except Exception:
            index_path = Path("document_index.json")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return []
        docs = data.get("documents") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            return []
        out: List[str] = []
        for entry in docs:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("filename") or "").strip()
            path = (entry.get("filepath") or "").lower()
            if not name:
                continue
            if "camera" in path or "uploaded_documents" in path:
                continue
            if name.lower().endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".bmp")
            ):
                continue
            out.append(name)
        return out

    def find_connections(self, now: Optional[datetime] = None,
                         current_user_msg: str = "") -> List[str]:
        """Correlate the upcoming schedule with recent conversation, the
        user's mood, and the document library.

        Four deterministic rules: a day with several events ("looks full");
        an upcoming event whose topic echoes recent conversation; an event
        the user has sounded stressed about (Blue offers a calming hand); and
        an event with a related document on file. Returns short connection
        strings — never fabricated, only real overlaps between real
        reminders, recaps, files, and the user's own words."""
        now = now or datetime.now()
        try:
            from blue_tools_enhanced import occurrences_in_window
            events = occurrences_in_window(
                now, now + timedelta(days=CONNECTION_WINDOW_DAYS)
            )
        except Exception:
            return []
        if not events:
            return []

        connections: List[str] = []

        # Rule 1: a day carrying several events.
        by_day: Dict[Any, list] = {}
        for e in events:
            by_day.setdefault(e["start"].date(), []).append(e)
        for day in sorted(by_day):
            evs = by_day[day]
            if len(evs) >= 3:
                titles = ", ".join(sorted({e["title"] for e in evs}))
                connections.append(
                    f"{self._friendly_day_label(day.isoformat())} looks full "
                    f"— {len(evs)} things on the calendar: {titles}."
                )

        # One event links at most once across the topic/concern rules.
        matched: set = set()

        # Rule 3 runs BEFORE the plain topic rule: a concern connection
        # carries an actionable, caring offer, so it should win the event if
        # both rules would fire. The user has sounded stressed about something
        # that matches a ONE-OFF upcoming event — the "notice what you need
        # before you say it" case. Blue gently OFFERS a calming hand (dim the
        # lights, focus music) and never acts on its own. Detection is
        # deterministic: a concern word in the same message as an event
        # keyword. The current message is included so it works the same turn.
        concern_msgs = [
            m for m in self._recent_user_messages(now)
            if self._CONCERN_RE.search(m)
        ]
        if current_user_msg and self._CONCERN_RE.search(current_user_msg):
            concern_msgs.append(current_user_msg)
        if concern_msgs:
            concern_blob = " ".join(concern_msgs).lower()
            for e in events:
                if e.get("recurring") or e["title"] in matched:
                    continue
                for kw in self._event_keywords(e["title"]):
                    if re.search(r"\b" + re.escape(kw.lower()) + r"\b",
                                 concern_blob):
                        day = self._friendly_day_label(
                            e["start"].date().isoformat())
                        connections.append(
                            f"The user has sounded stressed about something "
                            f"tied to \"{e['title']}\" — it's coming up ({day}). "
                            f"If it fits the moment, gently offer to help them "
                            f"unwind: dimming the lights, or putting on some "
                            f"focus music. Offer first and wait for a yes — "
                            f"don't change anything on your own."
                        )
                        matched.add(e["title"])
                        break

        # Rule 2: a ONE-OFF upcoming event whose topic echoes recent
        # conversation. Recurring fixtures (a weekly class) are skipped — they
        # aren't news. A keyword counts only if it appears in recent text but
        # isn't ambient (a word sprinkled everywhere links nothing). Per event
        # the best keyword wins: a capitalised name beats a common word, and
        # among equals the rarer (more specific) one wins.
        recent = self._recent_context_text(now)
        if recent:
            for e in events:
                if e.get("recurring") or e["title"] in matched:
                    continue
                best = None  # (rank, keyword) — lower rank sorts better
                for kw in self._event_keywords(e["title"]):
                    hits = len(re.findall(
                        r"\b" + re.escape(kw.lower()) + r"\b", recent))
                    if 1 <= hits <= CONNECTION_AMBIENT_MAX:
                        rank = (0 if kw[:1].isupper() else 1, hits)
                        if best is None or rank < best[0]:
                            best = (rank, kw)
                if best:
                    day = self._friendly_day_label(e["start"].date().isoformat())
                    connections.append(
                        f"\"{e['title']}\" is coming up ({day}) — and "
                        f"\"{best[1]}\" has come up in recent conversations, so "
                        f"they may be related."
                    )
                    matched.add(e["title"])

        # Rule 4: an imminent event (within CONNECTION_DOC_WINDOW_DAYS) that
        # matches a document in the library, so Blue can offer to pull it up
        # beforehand. Filenames concatenate words, so this is a substring
        # match; event keywords are already filtered to distinctive ones.
        docs = self._library_documents()
        if docs:
            doc_norms = [
                (d, re.sub(r"[^a-z0-9]", "", d.lower())) for d in docs
            ]
            doc_cutoff = now.date() + timedelta(days=CONNECTION_DOC_WINDOW_DAYS)
            doc_matched: set = set()
            for e in events:
                if e["start"].date() > doc_cutoff:
                    continue
                hit = None
                for kw in self._event_keywords(e["title"]):
                    kwn = re.sub(r"[^a-z0-9]", "", kw.lower())
                    if len(kwn) < 4:
                        continue
                    for fname, fnorm in doc_norms:
                        if fname not in doc_matched and kwn in fnorm:
                            hit = fname
                            break
                    if hit:
                        break
                if hit:
                    day = self._friendly_day_label(
                        e["start"].date().isoformat())
                    connections.append(
                        f"\"{e['title']}\" is coming up ({day}) and there's a "
                        f"document on file that looks related — \"{hit}\". You "
                        f"could offer to pull it up or summarise it beforehand."
                    )
                    doc_matched.add(hit)

        # Dedupe, keep order, cap.
        seen: set = set()
        unique = [c for c in connections if not (c in seen or seen.add(c))]
        return unique[:4]

    def _build_connections_block(self, now: Optional[datetime] = None,
                                 user_msg: str = "") -> str:
        """Surface cross-context connections so Blue can join the dots
        naturally. Empty string when there are none."""
        connections = self.find_connections(now, current_user_msg=user_msg)
        if not connections:
            return ""
        return (
            "<connections>\n"
            "Links the system spotted across the user's upcoming schedule, "
            "recent conversations, how they've been feeling, and their "
            "document library — derived from real reminders, recaps, files, "
            "and the user's own words, not guesses. Raise one naturally if it "
            "genuinely helps (\"by the way, ...\"). Some include a gentle "
            "action you could offer — always ask first and wait for a yes, "
            "never act unprompted. Ignore any that don't fit the moment, and "
            "never present a connection as more certain than it is:\n"
            + "\n".join(f"- {c}" for c in connections) +
            "\n</connections>"
        )

    # ------------------------------------------------------------------ Summary / stats

    def get_memory_summary(self) -> Dict[str, Any]:
        """Get comprehensive stats about the memory system.

        Includes counts, breakdowns, junk-fact estimates (so the user can
        see when cleanup would help), high-confidence facts, and recent
        contradictions. Designed to answer 'how is my memory health?'."""
        try:
            conn = self._conn()

            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_type = {}
            for row in conn.execute(
                "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
            ).fetchall():
                by_type[row["type"]] = row["cnt"]

            total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            total_conv = conn.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]

            # Top memories by importance
            top = conn.execute(
                """SELECT subject, type, importance, access_count
                   FROM memories ORDER BY importance DESC, access_count DESC LIMIT 10"""
            ).fetchall()

            # High-confidence facts (only available on new schema)
            high_conf_facts: List[Dict[str, Any]] = []
            try:
                for row in conn.execute(
                    """SELECT fact_key, fact_value, confidence, times_confirmed
                       FROM facts
                       WHERE confidence IS NOT NULL
                       ORDER BY confidence DESC, times_confirmed DESC LIMIT 15"""
                ).fetchall():
                    high_conf_facts.append({
                        "key": row["fact_key"],
                        "value": (row["fact_value"] or "")[:80],
                        "confidence": round(row["confidence"] or 0.0, 2),
                        "confirmed": row["times_confirmed"] or 1,
                    })
            except sqlite3.OperationalError:
                pass

            # Recent contradictions (if table exists)
            contradictions: List[Dict[str, Any]] = []
            try:
                for row in conn.execute(
                    """SELECT fact_key, old_value, new_value, detected_at
                       FROM fact_contradictions
                       ORDER BY id DESC LIMIT 5"""
                ).fetchall():
                    contradictions.append({
                        "key": row["fact_key"],
                        "old": (row["old_value"] or "")[:60],
                        "new": (row["new_value"] or "")[:60],
                        "when": row["detected_at"],
                    })
            except sqlite3.OperationalError:
                pass

            # Estimate junk count (matches what cleanup would remove)
            junk_facts = 0
            for r in conn.execute("SELECT fact_key, fact_value FROM facts").fetchall():
                if self._is_junk_fact(
                    (r["fact_key"] or ""), (r["fact_value"] or "")
                ):
                    junk_facts += 1

            conn.close()
        except Exception as e:
            return {"error": str(e)}

        collection = _get_memory_collection()
        vector_count = collection.count() if collection else 0

        return {
            "total_memories": total,
            "by_type": dict(by_type),
            "total_facts": total_facts,
            "junk_facts_estimate": junk_facts,
            "total_conversation_messages": total_conv,
            "vector_index_count": vector_count,
            "vector_index_healthy": (
                vector_count >= total // 2 if total > 5 else True
            ),
            "high_confidence_facts": high_conf_facts,
            "recent_contradictions": contradictions,
            "top_memories": [
                {
                    "subject": r["subject"],
                    "type": r["type"],
                    "importance": r["importance"],
                    "accesses": r["access_count"],
                }
                for r in top
            ],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_memory_system: Optional[EnhancedMemorySystem] = None


def get_memory_system() -> EnhancedMemorySystem:
    """Get or create the global enhanced memory system."""
    global _memory_system
    if _memory_system is None:
        _memory_system = EnhancedMemorySystem()
    return _memory_system
