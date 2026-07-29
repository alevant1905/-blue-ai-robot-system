"""
Blue Robot Visual Memory System
Allows Blue to recognize and remember people, places, and objects he sees.
"""

import sqlite3
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

# Visual memory database location
try:
    from config import VISUAL_MEMORY_DB_PATH
    VISUAL_MEMORY_DB = str(VISUAL_MEMORY_DB_PATH)
except ImportError:
    VISUAL_MEMORY_DB = os.environ.get("BLUE_VISUAL_MEMORY_DB", "data/visual_memory.db")

# Where reference photos for recognition are stored. Under data/ (gitignored),
# so personal images never leave the machine.
VISUAL_REF_DIR = os.path.join(os.path.dirname(VISUAL_MEMORY_DB) or "data", "visual_refs")

# entity_type -> (table, editable columns) for the generic GUI CRUD helpers.
_ENTITY_TABLES = {
    "person": ("people", ["name", "description", "typical_appearance",
                          "relationship", "common_locations", "notes"]),
    "place": ("places", ["name", "description", "typical_contents",
                         "typical_lighting", "notes"]),
    "object": ("objects", ["name", "category", "description",
                          "typical_location", "notes"]),
}

# Historical edits created a few duplicate display names for the same person.
# Keep the old rows for audit/UI purposes, but use one stable name in face
# matching, observations, and each robot's continuity record.
_DEFAULT_PERSON_ALIASES = {
    "alex (doctor levant)": "Alex",
    "doctor levant": "Alex",
    "dr. levant": "Alex",
    "felix levant": "Felix",
}


class VisualMemory:
    """Manages Blue's visual memory - what he knows about people, places, and things."""

    def __init__(self, db_path: str = VISUAL_MEMORY_DB):
        self.db_path = db_path
        self._ensure_database()

    # ---- Generic, id-keyed CRUD used by the Visual Memory GUI ----

    def list_entities(self, entity_type: str) -> List[Dict[str, Any]]:
        table = _ENTITY_TABLES[entity_type][0]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY name COLLATE NOCASE").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_entity(self, entity_type: str, entity_id: int) -> Optional[Dict[str, Any]]:
        table = _ENTITY_TABLES[entity_type][0]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def add_entity(self, entity_type: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        table, cols = _ENTITY_TABLES[entity_type]
        data = {k: (fields.get(k) or None) for k in cols if k in fields}
        if not (str(data.get("name") or "").strip()):
            return {"success": False, "message": "A name is required."}
        keys = list(data.keys())
        placeholders = ", ".join("?" for _ in keys)
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})",
                [data[k] for k in keys])
            conn.commit()
            eid = cur.lastrowid
        except sqlite3.IntegrityError:
            return {"success": False, "message": f"{data.get('name')} already exists."}
        finally:
            conn.close()
        return {"success": True, "id": eid}

    def update_entity(self, entity_type: str, entity_id: int,
                      fields: Dict[str, Any]) -> Dict[str, Any]:
        table, cols = _ENTITY_TABLES[entity_type]
        sets, params = [], []
        for k in cols:
            if k in fields:
                sets.append(f"{k} = ?")
                v = fields[k]
                params.append((v.strip() or None) if isinstance(v, str) else v)
        if not sets:
            return {"success": False, "message": "Nothing to update."}
        params.append(entity_id)
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if not changed:
            return {"success": False, "message": "Not found."}
        return {"success": True, "id": entity_id}

    def delete_entity(self, entity_type: str, entity_id: int) -> Dict[str, Any]:
        table = _ENTITY_TABLES[entity_type][0]
        conn = sqlite3.connect(self.db_path)
        # Remove the reference image file too, if any.
        row = conn.execute(
            f"SELECT image_path FROM {table} WHERE id = ?", (entity_id,)).fetchone()
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if row and row[0]:
            try:
                os.remove(row[0])
            except OSError:
                pass
        if not changed:
            return {"success": False, "message": "Not found."}
        return {"success": True}

    def set_entity_image(self, entity_type: str, entity_id: int,
                         image_path: str) -> Dict[str, Any]:
        table = _ENTITY_TABLES[entity_type][0]
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            f"UPDATE {table} SET image_path = ? WHERE id = ?",
            (image_path, entity_id))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        return {"success": bool(changed)}

    def entities_with_images(self, entity_type: str) -> List[Dict[str, Any]]:
        """Known entities that have a reference photo on disk — the candidates
        for visual recognition matching."""
        out = []
        rows = (
            self.get_recognition_people()
            if entity_type == "person" else self.list_entities(entity_type)
        )
        for e in rows:
            p = e.get("image_path")
            if p and os.path.exists(p):
                out.append(e)
        return out
    
    def _ensure_database(self):
        """Create the visual memory database if it doesn't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # People Blue knows
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                typical_appearance TEXT,
                relationship TEXT,
                common_locations TEXT,
                notes TEXT,
                last_seen TIMESTAMP,
                times_seen INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Places Blue recognizes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                typical_contents TEXT,
                typical_lighting TEXT,
                notes TEXT,
                last_seen TIMESTAMP,
                times_seen INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Objects Blue knows about
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                description TEXT,
                typical_location TEXT,
                notes TEXT,
                last_seen TIMESTAMP,
                times_seen INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Observation log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scene_description TEXT,
                people_present TEXT,
                location TEXT,
                notable_objects TEXT,
                context TEXT
            )
        """)

        # Migration: add image_path and image_hash columns if missing
        for col, col_type in [
            ("image_path", "TEXT"),
            ("image_hash", "TEXT"),
            ("observer", "TEXT"),
            ("recognition_json", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE observations ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Migration: a reference photo per known person/place/object, used to
        # recognize them by visual comparison (not just text description).
        for tbl in ("people", "places", "objects"):
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN image_path TEXT")
            except sqlite3.OperationalError:
                pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS person_aliases (
                alias TEXT PRIMARY KEY COLLATE NOCASE,
                canonical_name TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS person_sightings (
                observer TEXT NOT NULL,
                person_name TEXT NOT NULL COLLATE NOCASE,
                last_seen TIMESTAMP NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 0,
                last_confidence REAL,
                last_observation_id INTEGER,
                PRIMARY KEY (observer, person_name)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_observations_observer_time "
            "ON observations(observer, timestamp DESC)"
        )
        for alias, canonical in _DEFAULT_PERSON_ALIASES.items():
            cursor.execute(
                "INSERT OR IGNORE INTO person_aliases(alias, canonical_name) "
                "VALUES (?, ?)",
                (alias, canonical),
            )

        conn.commit()
        conn.close()
    
    def add_person(self, name: str, description: str = None, 
                   typical_appearance: str = None, relationship: str = None,
                   common_locations: str = None, notes: str = None) -> bool:
        """Add or update a person in visual memory."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO people
                (name, description, typical_appearance, relationship,
                 common_locations, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = COALESCE(excluded.description, people.description),
                    typical_appearance = COALESCE(
                        excluded.typical_appearance, people.typical_appearance),
                    relationship = COALESCE(excluded.relationship, people.relationship),
                    common_locations = COALESCE(
                        excluded.common_locations, people.common_locations),
                    notes = COALESCE(excluded.notes, people.notes)
            """, (name, description, typical_appearance, relationship,
                  common_locations, notes))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error adding person: {e}")
            return False
    
    def add_place(self, name: str, description: str = None,
                  typical_contents: str = None, typical_lighting: str = None,
                  notes: str = None) -> bool:
        """Add or update a place in visual memory."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO places
                (name, description, typical_contents, typical_lighting, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = COALESCE(excluded.description, places.description),
                    typical_contents = COALESCE(
                        excluded.typical_contents, places.typical_contents),
                    typical_lighting = COALESCE(
                        excluded.typical_lighting, places.typical_lighting),
                    notes = COALESCE(excluded.notes, places.notes)
            """, (name, description, typical_contents, typical_lighting, notes))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error adding place: {e}")
            return False
    
    def add_object(self, name: str, category: str = None, description: str = None,
                   typical_location: str = None, notes: str = None) -> bool:
        """Add or update an object in visual memory."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO objects 
                (name, category, description, typical_location, notes, last_seen, times_seen)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (name, category, description, typical_location, notes, datetime.now()))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error adding object: {e}")
            return False
    
    def register_person_alias(self, alias: str, canonical_name: str) -> bool:
        """Map an old/display name onto the stable recognition identity."""
        alias = str(alias or "").strip()
        canonical_name = str(canonical_name or "").strip()
        if not alias or not canonical_name:
            return False
        with sqlite3.connect(self.db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM people WHERE name = ? COLLATE NOCASE",
                (canonical_name,),
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                "INSERT INTO person_aliases(alias, canonical_name) VALUES (?, ?) "
                "ON CONFLICT(alias) DO UPDATE SET canonical_name = excluded.canonical_name",
                (alias, exists[0]),
            )
        return True

    def resolve_person_name(self, name: str) -> str:
        """Return the canonical stored name for a recognition/display alias."""
        clean = str(name or "").strip()
        if not clean:
            return ""
        with sqlite3.connect(self.db_path) as conn:
            alias = conn.execute(
                "SELECT canonical_name FROM person_aliases WHERE alias = ? COLLATE NOCASE",
                (clean,),
            ).fetchone()
            if alias:
                canonical = conn.execute(
                    "SELECT name FROM people WHERE name = ? COLLATE NOCASE",
                    (alias[0],),
                ).fetchone()
                if canonical:
                    return str(canonical[0])
            exact = conn.execute(
                "SELECT name FROM people WHERE name = ? COLLATE NOCASE", (clean,)
            ).fetchone()
            if exact:
                return str(exact[0])
            base = re.sub(r"\s*\([^)]*\)\s*$", "", clean).strip()
            if base != clean:
                base_row = conn.execute(
                    "SELECT name FROM people WHERE name = ? COLLATE NOCASE", (base,)
                ).fetchone()
                if base_row:
                    return str(base_row[0])
        return clean

    def canonicalize_people(self, names: List[str]) -> List[str]:
        """Resolve aliases and de-duplicate names without changing order."""
        out = []
        seen = set()
        for name in names or []:
            canonical = self.resolve_person_name(str(name))
            key = canonical.casefold()
            if canonical and key not in seen:
                seen.add(key)
                out.append(canonical)
        return out

    def update_seen(self, entity_type: str, name: str, observer: str = None,
                    confidence: float = None, observation_id: int = None):
        """Update aggregate and per-robot sighting history for an entity."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            singular = entity_type.rstrip("s")
            if singular == "person":
                name = self.resolve_person_name(name)
            table_info = _ENTITY_TABLES.get(singular)
            if not table_info:
                raise ValueError(f"Unknown visual entity type: {entity_type}")
            table = table_info[0]
            now = datetime.now().isoformat(timespec="seconds")
            cursor.execute(f"""
                UPDATE {table}
                SET last_seen = ?, times_seen = times_seen + 1
                WHERE name = ?
            """, (now, name))
            if observer and singular == "person" and cursor.rowcount:
                cursor.execute("""
                    INSERT INTO person_sightings
                    (observer, person_name, last_seen, times_seen,
                     last_confidence, last_observation_id)
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(observer, person_name) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        times_seen = person_sightings.times_seen + 1,
                        last_confidence = COALESCE(
                            excluded.last_confidence, person_sightings.last_confidence),
                        last_observation_id = COALESCE(
                            excluded.last_observation_id,
                            person_sightings.last_observation_id)
                """, (str(observer).strip().lower(), name, now,
                      confidence, observation_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error updating seen status: {e}")
            return False
    
    def log_observation(self, scene_description: str, people_present: List[str] = None,
                       location: str = None, notable_objects: List[str] = None,
                       context: str = None, image_path: str = None,
                       image_hash: str = None, observer: str = None,
                       recognition: List[Dict[str, Any]] = None):
        """Log what Blue observes, optionally linked to an image file."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            people_present = self.canonicalize_people(people_present or [])
            cursor.execute("""
                INSERT INTO observations
                (scene_description, people_present, location, notable_objects,
                 context, image_path, image_hash, observer, recognition_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scene_description,
                json.dumps(people_present) if people_present else None,
                location,
                json.dumps(notable_objects) if notable_objects else None,
                context,
                image_path,
                image_hash,
                str(observer or "").strip().lower() or None,
                json.dumps(recognition) if recognition else None,
            ))
            observation_id = cursor.lastrowid
            conn.commit()
            conn.close()
            print(f"[VISUAL-MEMORY] Saved observation{' with image' if image_path else ''}")
            return observation_id
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error logging observation: {e}")
            return None
    
    # ==================== Visual Memory Retrieval ====================

    def get_recent_observations(self, limit: int = 10,
                                observer: str = None) -> List[Dict[str, Any]]:
        """Get recent observations, optionally limited to one robot's camera."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if observer:
                rows = cursor.execute(
                    "SELECT * FROM observations WHERE observer = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (str(observer).strip().lower(), limit),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM observations ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error fetching recent observations: {e}")
            return []

    def search_observations(self, query: str, limit: int = 5,
                            observer: str = None) -> List[Dict[str, Any]]:
        """Search observations by keyword across description, people, location, objects."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            pattern = f"%{query}%"
            observer_clause = " AND observer = ?" if observer else ""
            params = [pattern, pattern, pattern, pattern]
            if observer:
                params.append(str(observer).strip().lower())
            params.append(limit)
            rows = cursor.execute("""
                SELECT * FROM observations
                WHERE (scene_description LIKE ?
                   OR people_present LIKE ?
                   OR location LIKE ?
                   OR notable_objects LIKE ?)
                """ + observer_clause + " ORDER BY timestamp DESC LIMIT ?", params).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error searching observations: {e}")
            return []

    def get_last_camera_observation(self, observer: str = None) -> Optional[Dict[str, Any]]:
        """Get the most recent observation linked to a camera image."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if observer:
                row = cursor.execute(
                    "SELECT * FROM observations WHERE image_path IS NOT NULL "
                    "AND observer = ? ORDER BY timestamp DESC LIMIT 1",
                    (str(observer).strip().lower(),),
                ).fetchone()
            else:
                row = cursor.execute(
                    "SELECT * FROM observations WHERE image_path IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error fetching last camera observation: {e}")
            return None

    def get_visual_timeline(self, hours: int = 24,
                            observer: str = None) -> List[Dict[str, Any]]:
        """Get all observations from the last N hours, chronologically."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            observer_clause = " AND observer = ?" if observer else ""
            params = [f"-{hours}"]
            if observer:
                params.append(str(observer).strip().lower())
            rows = cursor.execute("""
                SELECT * FROM observations
                WHERE timestamp >= datetime('now', ? || ' hours')
            """ + observer_clause + " ORDER BY timestamp ASC", params).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[VISUAL-MEMORY] Error fetching visual timeline: {e}")
            return []

    def get_visual_history_context(self, limit: int = 3,
                                   observer: str = None) -> str:
        """Format recent observations as text context for LLM injection."""
        observations = self.get_recent_observations(limit, observer=observer)
        if not observations:
            return ""

        lines = ["=== RECENT VISUAL MEMORY ==="]
        for obs in observations:
            # Calculate relative time
            try:
                ts = datetime.fromisoformat(obs['timestamp'])
                delta = datetime.now() - ts
                minutes = int(delta.total_seconds() / 60)
                if minutes < 1:
                    ago = "just now"
                elif minutes < 60:
                    ago = f"{minutes} min ago"
                else:
                    hours = minutes // 60
                    ago = f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"
            except (ValueError, TypeError):
                ago = "unknown time"

            location = obs.get('location') or 'Unknown location'
            desc = obs.get('scene_description', '')
            # Truncate long descriptions for context injection
            if len(desc) > 200:
                desc = desc[:200] + "..."

            people = ""
            if obs.get('people_present'):
                try:
                    names = json.loads(obs['people_present'])
                    if names:
                        people = f" People: {', '.join(names)}."
                except (json.JSONDecodeError, TypeError):
                    pass

            objects_str = ""
            if obs.get('notable_objects'):
                try:
                    objs = json.loads(obs['notable_objects'])
                    if objs:
                        objects_str = f" Objects: {', '.join(objs[:5])}."
                except (json.JSONDecodeError, TypeError):
                    pass

            lines.append(f"[{ago}] {location} - {desc}{people}{objects_str}")

        return "\n".join(lines)

    def detect_scene_changes(self, current_description: str = "",
                             observer: str = None) -> Dict[str, Any]:
        """Compare current scene to the last camera observation to detect changes."""
        last_obs = self.get_last_camera_observation(observer=observer)
        if not last_obs:
            return {"has_previous": False}

        # Time since last observation
        try:
            ts = datetime.fromisoformat(last_obs['timestamp'])
            delta = datetime.now() - ts
            minutes = int(delta.total_seconds() / 60)
            if minutes < 60:
                time_since = f"{minutes} minutes"
            else:
                hours = minutes // 60
                time_since = f"{hours} hour{'s' if hours != 1 else ''}"
        except (ValueError, TypeError):
            time_since = "unknown time"

        # Extract people from previous observation
        prev_people = set()
        if last_obs.get('people_present'):
            try:
                prev_people = set(json.loads(last_obs['people_present']))
            except (json.JSONDecodeError, TypeError):
                pass

        # Extract people mentioned in current description using known people names
        known_people = self.get_all_people()
        known_names = {p['name'].lower(): p['name'] for p in known_people}
        current_people = set()
        current_lower = current_description.lower()
        for name_lower, name in known_names.items():
            if name_lower in current_lower:
                current_people.add(name)

        people_changed = prev_people != current_people

        # Location comparison
        prev_location = (last_obs.get('location') or '').lower()
        location_keywords = ['office', 'kitchen', 'living room', 'studio', 'bedroom', 'bathroom', 'outside', 'garden']
        prev_loc = next((kw for kw in location_keywords if kw in prev_location), '')
        curr_loc = next((kw for kw in location_keywords if kw in current_lower), '')
        location_changed = bool(prev_loc and curr_loc and prev_loc != curr_loc)

        # Build changes summary
        changes = []
        if people_changed:
            arrived = current_people - prev_people
            left = prev_people - current_people
            if arrived:
                changes.append(f"{', '.join(arrived)} appeared")
            if left:
                changes.append(f"{', '.join(left)} left")
        if location_changed:
            changes.append(f"location changed from {prev_loc} to {curr_loc}")

        return {
            "has_previous": True,
            "previous_description": last_obs.get('scene_description', '')[:300],
            "previous_location": last_obs.get('location'),
            "time_since": time_since,
            "people_changed": people_changed,
            "location_changed": location_changed,
            "changes_summary": "; ".join(changes) if changes else "no major changes detected"
        }

    def get_all_people(self) -> List[Dict[str, Any]]:
        """Get all people Blue knows."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        rows = cursor.execute("SELECT * FROM people ORDER BY name").fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

    def get_recognition_people(self) -> List[Dict[str, Any]]:
        """Canonical person profiles, merging reference photos from aliases."""
        grouped: Dict[str, Dict[str, Any]] = {}
        for raw in self.get_all_people():
            raw_name = str(raw.get("name") or "").strip()
            if not raw_name:
                continue
            canonical = self.resolve_person_name(raw_name)
            key = canonical.casefold()
            current = grouped.get(key)
            row = dict(raw)
            row["name"] = canonical
            row["source_name"] = raw_name
            if current is None or raw_name.casefold() == canonical.casefold():
                if current:
                    for field in (
                        "image_path", "typical_appearance", "description",
                        "relationship", "common_locations", "notes",
                    ):
                        if not row.get(field) and current.get(field):
                            row[field] = current[field]
                grouped[key] = row
            else:
                for field in (
                    "image_path", "typical_appearance", "description",
                    "relationship", "common_locations", "notes",
                ):
                    if not current.get(field) and row.get(field):
                        current[field] = row[field]
        return sorted(grouped.values(), key=lambda row: row["name"].casefold())

    def get_person_sighting(self, name: str, observer: str) -> Optional[Dict[str, Any]]:
        canonical = self.resolve_person_name(name)
        if not canonical or not observer:
            return None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM person_sightings WHERE observer = ? "
            "AND person_name = ? COLLATE NOCASE",
            (str(observer).strip().lower(), canonical),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_person_observations(self, name: str, observer: str = None,
                                limit: int = 2) -> List[Dict[str, Any]]:
        """Recent visual descriptions that actually include this person."""
        canonical = self.resolve_person_name(name)
        if not canonical:
            return []
        # Pull a bounded recent window then parse the JSON names exactly; LIKE
        # alone would confuse short names or aliases embedded in prose.
        observations = self.get_recent_observations(
            max(30, int(limit) * 12), observer=observer)
        matched = []
        for observation in observations:
            try:
                people = json.loads(observation.get("people_present") or "[]")
            except (TypeError, ValueError):
                people = []
            canonical_people = self.canonicalize_people(
                people if isinstance(people, list) else [])
            if canonical.casefold() in {person.casefold() for person in canonical_people}:
                matched.append(observation)
                if len(matched) >= max(1, int(limit)):
                    break
        return matched

    def get_people_memory_context(self, observer: str,
                                  max_people: int = 16) -> str:
        """Compact bridge from the shared face gallery into one robot's memory."""
        observer = str(observer or "").strip().lower()
        if not observer:
            return ""
        lines = []
        for person in self.get_recognition_people():
            name = person["name"]
            bits = []
            relationship = str(person.get("relationship") or "").strip()
            appearance = str(
                person.get("typical_appearance")
                or person.get("description")
                or ""
            ).strip()
            if relationship:
                bits.append(relationship[:120])
            if appearance:
                bits.append(f"appearance profile: {appearance[:180]}")
            enrolled = bool(
                person.get("image_path") and os.path.exists(person["image_path"])
            )
            bits.append(
                "visual reference stored; the face engine may name them only "
                "after it extracts and matches a usable human-face embedding"
                if enrolled else
                "no face reference enrolled; appearance notes alone must not be used to guess"
            )
            sighting = self.get_person_sighting(name, observer)
            if sighting:
                bits.append(
                    f"you last saw them {sighting['last_seen']} "
                    f"({sighting['times_seen']} recognized sighting"
                    f"{'s' if int(sighting['times_seen']) != 1 else ''})"
                )
                recent = self.get_person_observations(name, observer=observer, limit=1)
                if recent and recent[0].get("scene_description"):
                    desc = re.sub(
                        r"\s+", " ", str(recent[0]["scene_description"])
                    ).strip()
                    bits.append(f"latest visual description: {desc[:240]}")
            else:
                bits.append("you have no robot-specific sighting recorded yet")
            lines.append(f"- {name}: " + "; ".join(bits))
            if len(lines) >= max(1, int(max_people)):
                break
        if not lines:
            return ""
        return (
            f'<visual_people_memory observer="{observer}">\n'
            "Shared appearance profiles and face references are semantic household "
            "memory. Sighting times below are YOUR camera history only. Name someone "
            "from a live image only when face recognition reports an enrolled match; "
            "never guess from age, gender, clothing, or these text descriptions.\n"
            + "\n".join(lines)
            + "\n</visual_people_memory>"
        )
    
    def get_all_places(self) -> List[Dict[str, Any]]:
        """Get all places Blue recognizes."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        rows = cursor.execute("SELECT * FROM places ORDER BY name").fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_person(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific person."""
        name = self.resolve_person_name(name)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        row = cursor.execute("SELECT * FROM people WHERE name = ?", (name,)).fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_place(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific place."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        row = cursor.execute("SELECT * FROM places WHERE name = ?", (name,)).fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_recognition_context(self) -> str:
        """Get formatted context for visual recognition."""
        people = self.get_recognition_people()
        places = self.get_all_places()
        
        context_parts = []
        
        if people:
            context_parts.append("=== PEOPLE YOU KNOW ===")
            for person in people:
                parts = [f"• {person['name']}"]
                if person['relationship']:
                    parts.append(f"({person['relationship']})")
                if person['typical_appearance']:
                    parts.append(f"- Appearance: {person['typical_appearance']}")
                if person['description']:
                    parts.append(f"- {person['description']}")
                if person['common_locations']:
                    parts.append(f"- Often found: {person['common_locations']}")
                context_parts.append(" ".join(parts))
        
        if places:
            context_parts.append("\n=== PLACES YOU RECOGNIZE ===")
            for place in places:
                parts = [f"• {place['name']}"]
                if place['description']:
                    parts.append(f"- {place['description']}")
                if place['typical_contents']:
                    parts.append(f"- Typically contains: {place['typical_contents']}")
                context_parts.append(" ".join(parts))
        
        return "\n".join(context_parts)
    
    def seed_family_data(self):
        """Seed the database with Alex's family information."""
        # Add family members
        self.add_person(
            name="Alex",
            relationship="Your creator and primary user",
            typical_appearance="Man with beard and glasses, often in casual clothing",
            description="Teaches at York University and Wilfrid Laurier University. Works on AI ethics and runs The Circumference Centre. Very knowledgeable about technology and philosophy.",
            common_locations="Office, living room, kitchen",
            notes="Built you with Stella. Cares deeply about privacy and local AI systems."
        )
        
        self.add_person(
            name="Stella",
            relationship="Alex's partner, artist and teacher",
            typical_appearance="Woman, artistic style",
            description="Creative and thoughtful. Works as an artist and teacher.",
            common_locations="Art studio, living room, kitchen",
            notes="Co-created your identity with Alex."
        )
        
        self.add_person(
            name="Emmy",
            relationship="Alex and Stella's daughter",
            typical_appearance="Young girl",
            description="One of the three daughters.",
            common_locations="Living room, playroom, throughout the house"
        )
        
        self.add_person(
            name="Athena",
            relationship="Alex and Stella's daughter",
            typical_appearance="Young girl",
            description="One of the three daughters.",
            common_locations="Living room, playroom, throughout the house"
        )
        
        self.add_person(
            name="Vilda",
            relationship="Alex and Stella's daughter",
            typical_appearance="Young girl",
            description="One of the three daughters.",
            common_locations="Living room, playroom, throughout the house"
        )
        
        # Add common places
        self.add_place(
            name="Alex's Office",
            description="Where Alex works on his computer, teaches, and develops AI projects",
            typical_contents="Desktop computer with high-end specs (Intel i9-13900K, RTX 5090), monitors, desk, books, papers",
            typical_lighting="Natural light during day, desk lamp at night"
        )
        
        self.add_place(
            name="Stella's Studio",
            description="Stella's creative workspace",
            typical_contents="Art supplies, canvases, projects in progress, creative materials",
            typical_lighting="Good natural light for artwork"
        )
        
        self.add_place(
            name="Living Room",
            description="Main family gathering space",
            typical_contents="Couch, chairs, often toys from the kids, comfortable seating",
            typical_lighting="Varies - bright during day, warm lamps in evening"
        )
        
        self.add_place(
            name="Kitchen",
            description="Where meals are prepared and family often gathers",
            typical_contents="Appliances, coffee maker, dining table, dishes",
            typical_lighting="Bright overhead lighting, natural light from windows"
        )
        
        print("[VISUAL-MEMORY] Seeded family and location data")


def initialize_visual_memory():
    """Initialize the visual memory system and seed with family data if needed."""
    vm = VisualMemory()
    
    # Check if we need to seed data
    if not vm.get_all_people():
        print("[VISUAL-MEMORY] No existing data, seeding family information...")
        vm.seed_family_data()
    
    return vm


# Global instance
_visual_memory_instance = None

def get_visual_memory() -> VisualMemory:
    """Get the global visual memory instance."""
    global _visual_memory_instance
    if _visual_memory_instance is None:
        _visual_memory_instance = initialize_visual_memory()
    return _visual_memory_instance
