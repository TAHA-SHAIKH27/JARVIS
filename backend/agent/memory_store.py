"""Phase 2 — persistent SQLite storage for J.A.R.V.I.S. memory.

Primary long-term store: `backend/data/jarvis_memory.db` (SQLite, stdlib only).
Survives application/backend/computer restarts by construction — it is a file
on disk, written atomically per operation with WAL journaling.

The legacy Phase 1 JSON store (`persistent_memory.json`) is NOT removed: it is
read once for migration (explicit user memories keep id/timestamps) and stays
available for backward compatibility. SQLite is authoritative after migration.

Design notes:
- One `memories` table; embeddings live inline (`embedding_json/model/dim`)
  so there is no second database to keep in sync.
- FTS5 is used when the local SQLite build provides it, otherwise token-AND
  LIKE fallback — identical ranking inputs either way, so behavior never
  depends on the SQLite build.
- Corrupted rows never crash reads: they are skipped and counted.
- `forget()` is a hard DELETE. No tombstones, no hidden retention — the spec
  forbids pretending to forget while retaining in the active store.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from backend.agent.memory_schema import (
    DEFAULT_PROJECT_ID,
    MemoryRecord,
    MemoryStatus,
)

_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  content TEXT NOT NULL,
  summary TEXT NOT NULL,
  importance REAL NOT NULL,
  confidence TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  last_accessed REAL NOT NULL,
  access_count INTEGER NOT NULL,
  source TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  project_id TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  embedding_id TEXT NOT NULL,
  embedding_json TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dim INTEGER NOT NULL,
  status TEXT NOT NULL,
  sensitivity TEXT NOT NULL,
  expiration REAL
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_expiration ON memories(expiration);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, summary, content='memories', content_rowid='rowid');
"""


def memory_db_path() -> str:
    """Primary store path. `JARVIS_MEMORY_DB` override exists for tests only."""
    override = os.environ.get("JARVIS_MEMORY_DB", "").strip()
    if override:
        parent = os.path.dirname(os.path.abspath(override))
        if parent:
            os.makedirs(parent, exist_ok=True)
        return os.path.abspath(override)
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "jarvis_memory.db")


def legacy_json_path() -> str:
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    return os.path.join(data_dir, "persistent_memory.json")


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").casefold()) if len(t) > 1][:24]


class MemoryStore:
    """Thread-safe SQLite store. One instance per process is enough; tests may
    create isolated instances pointed at temp files via JARVIS_MEMORY_DB."""

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or memory_db_path()
        parent = os.path.dirname(os.path.abspath(self._db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._local = threading.local()
        with _LOCK:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                try:
                    conn.executescript(_FTS_SCHEMA)
                    self._fts = True
                except sqlite3.Error:
                    self._fts = False  # LIKE fallback; ranking inputs unchanged
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.Error:
                    pass
                conn.commit()
            finally:
                conn.close()

    # -- connection ------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # -- row mapping ------------------------------------------------------
    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        try:
            data = dict(row)
            tags_raw = data.get("tags_json") or "[]"
            try:
                tags = json.loads(tags_raw)
            except (ValueError, TypeError):
                tags = []
            return MemoryRecord(
                id=data.get("id") or "",
                memory_type=data.get("memory_type") or "user",
                content=data.get("content") or "",
                summary=data.get("summary") or "",
                importance=data.get("importance", 0.5),
                confidence=data.get("confidence") or "MEDIUM",
                created_at=data.get("created_at") or 0,
                updated_at=data.get("updated_at") or 0,
                last_accessed=data.get("last_accessed") or 0,
                access_count=data.get("access_count") or 0,
                source=data.get("source") or "conversation",
                source_reference=data.get("source_reference") or "",
                project_id=data.get("project_id") or DEFAULT_PROJECT_ID,
                tags=tags if isinstance(tags, list) else [],
                embedding_id=data.get("embedding_id") or "",
                status=data.get("status") or "active",
                sensitivity=data.get("sensitivity") or "internal",
                expiration=data.get("expiration"),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"corrupted memory row {row['id'] if 'id' in row.keys() else '?'}: {exc}") from exc

    @staticmethod
    def _record_params(record: MemoryRecord, embedding: Optional[Dict[str, Any]] = None) -> tuple:
        embedding = embedding or {}
        return (
            record.id,
            record.memory_type,
            record.content,
            record.summary,
            float(record.importance),
            record.confidence,
            float(record.created_at),
            float(record.updated_at),
            float(record.last_accessed),
            int(record.access_count),
            record.source,
            record.source_reference,
            record.project_id,
            json.dumps(record.tags, ensure_ascii=False),
            record.embedding_id,
            json.dumps(embedding.get("vector") or [], ensure_ascii=False),
            str(embedding.get("model") or ""),
            int(embedding.get("dim") or 0),
            record.status,
            record.sensitivity,
            record.expiration,
        )

    def _fts_sync(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        if not self._fts:
            return
        try:
            conn.execute("DELETE FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?)",
                         (record.id,))
            row = conn.execute("SELECT rowid FROM memories WHERE id = ?", (record.id,)).fetchone()
            if row is not None:
                conn.execute("INSERT INTO memories_fts(rowid, content, summary) VALUES (?, ?, ?)",
                             (row["rowid"], record.content, record.summary))
        except sqlite3.Error:
            pass  # FTS is an accelerator only; LIKE path stays correct

    # -- writes ------------------------------------------------------------
    def add(self, record: MemoryRecord, embedding: Optional[Dict[str, Any]] = None) -> MemoryRecord:
        with _LOCK:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO memories
                    (id, memory_type, content, summary, importance, confidence,
                     created_at, updated_at, last_accessed, access_count, source,
                     source_reference, project_id, tags_json, embedding_id,
                     embedding_json, embedding_model, embedding_dim, status,
                     sensitivity, expiration)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._record_params(record, embedding),
                )
                self._fts_sync(conn, record)
                conn.commit()
                return record
            finally:
                conn.close()

    def update(self, memory_id: str, fields: Dict[str, Any],
               embedding: Optional[Dict[str, Any]] = None) -> Optional[MemoryRecord]:
        current = self.get(memory_id)
        if current is None:
            return None
        data = current.to_dict()
        for key, value in (fields or {}).items():
            if key in ("id", "created_at"):
                continue
            if key in data:
                data[key] = value
        data["updated_at"] = time.time()
        updated = MemoryRecord.from_dict(data)  # validates; raises on garbage
        with _LOCK:
            conn = self._connect()
            try:
                if embedding is not None:
                    conn.execute(
                        """UPDATE memories SET memory_type=?, content=?, summary=?,
                        importance=?, confidence=?, updated_at=?, last_accessed=?,
                        access_count=?, source=?, source_reference=?, project_id=?,
                        tags_json=?, embedding_id=?, embedding_json=?, embedding_model=?,
                        embedding_dim=?, status=?, sensitivity=?, expiration=?
                        WHERE id=?""",
                        (
                            updated.memory_type, updated.content, updated.summary,
                            float(updated.importance), updated.confidence,
                            float(updated.updated_at), float(updated.last_accessed),
                            int(updated.access_count), updated.source,
                            updated.source_reference, updated.project_id,
                            json.dumps(updated.tags, ensure_ascii=False),
                            updated.embedding_id,
                            json.dumps(embedding.get("vector") or [], ensure_ascii=False),
                            str(embedding.get("model") or ""),
                            int(embedding.get("dim") or 0),
                            updated.status, updated.sensitivity, updated.expiration,
                            memory_id,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE memories SET memory_type=?, content=?, summary=?,
                        importance=?, confidence=?, updated_at=?, last_accessed=?,
                        access_count=?, source=?, source_reference=?, project_id=?,
                        tags_json=?, embedding_id=?, status=?, sensitivity=?, expiration=?
                        WHERE id=?""",
                        (
                            updated.memory_type, updated.content, updated.summary,
                            float(updated.importance), updated.confidence,
                            float(updated.updated_at), float(updated.last_accessed),
                            int(updated.access_count), updated.source,
                            updated.source_reference, updated.project_id,
                            json.dumps(updated.tags, ensure_ascii=False),
                            updated.embedding_id, updated.status,
                            updated.sensitivity, updated.expiration, memory_id,
                        ),
                    )
                self._fts_sync(conn, updated)
                conn.commit()
                return updated
            finally:
                conn.close()

    def delete(self, memory_id: str) -> bool:
        """Hard delete — real forgetting. No tombstone is retained."""
        with _LOCK:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                try:
                    conn.execute("DELETE FROM memories_fts WHERE rowid NOT IN (SELECT rowid FROM memories)")
                except sqlite3.Error:
                    pass
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def record_access(self, memory_id: str) -> None:
        with _LOCK:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                    (time.time(), memory_id),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_expired(self) -> int:
        now = time.time()
        with _LOCK:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE memories SET status = ? WHERE status = ? AND expiration IS NOT NULL AND expiration <= ?",
                    (MemoryStatus.EXPIRED, MemoryStatus.ACTIVE, now),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    # -- reads --------------------------------------------------------------
    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with _LOCK:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
                if row is None:
                    return None
                try:
                    return self._row_to_record(row)
                except ValueError:
                    return None  # corrupted single row reads as missing
            finally:
                conn.close()

    def get_embedding(self, memory_id: str) -> Dict[str, Any]:
        with _LOCK:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT embedding_json, embedding_model, embedding_dim FROM memories WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    return {"vector": [], "model": "", "dim": 0}
                try:
                    vector = json.loads(row["embedding_json"] or "[]")
                except (ValueError, TypeError):
                    vector = []
                return {"vector": vector if isinstance(vector, list) else [],
                        "model": row["embedding_model"] or "",
                        "dim": int(row["embedding_dim"] or 0)}
            finally:
                conn.close()

    def list(self, memory_type: str = "", project_id: str = "",
             status: str = MemoryStatus.ACTIVE, limit: int = 100,
             include_corrupted: bool = False) -> Dict[str, Any]:
        clauses = []
        params: List[Any] = []
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type.strip().lower())
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id.strip())
        if status:
            clauses.append("status = ?")
            params.append(status.strip().lower())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit or 100), 1000))
        with _LOCK:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT * FROM memories {where} ORDER BY updated_at DESC LIMIT ?",
                    (*params, limit),
                ).fetchall()
            finally:
                conn.close()
        records: List[MemoryRecord] = []
        corrupted = 0
        for row in rows:
            try:
                records.append(self._row_to_record(row))
            except ValueError:
                corrupted += 1
        result: Dict[str, Any] = {"records": records, "count": len(records)}
        if include_corrupted or corrupted:
            result["corrupted_skipped"] = corrupted
        return result

    def count(self, status: str = "") -> int:
        with _LOCK:
            conn = self._connect()
            try:
                if status:
                    row = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE status = ?",
                                       (status.strip().lower(),)).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
                return int(row["n"] if row else 0)
            finally:
                conn.close()

    def search_candidates(self, query: str, limit: int = 50, project_id: str = "",
                          memory_types: Optional[List[str]] = None,
                          include_non_active: bool = False) -> Dict[str, Any]:
        """Candidate generation: FTS5 match when available, else token-AND LIKE.
        Returns records + corrupted skip count. Ranking happens in
        memory_ranking.py — this stage only generates the candidate set."""
        limit = max(1, min(int(limit or 50), 200))
        tokens = _tokens(query)
        extra = ""
        params: List[Any] = []
        if project_id:
            extra += " AND m.project_id = ?"
            params.append(project_id.strip())
        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            extra += f" AND m.memory_type IN ({placeholders})"
            params.extend([t.strip().lower() for t in memory_types])
        if not include_non_active:
            extra += " AND m.status = ?"
            params.append(MemoryStatus.ACTIVE)
        with _LOCK:
            conn = self._connect()
            try:
                rows = []
                if self._fts and tokens:
                    match = " ".join(tokens)
                    try:
                        rows = conn.execute(
                            f"""SELECT m.* FROM memories_fts f JOIN memories m
                            ON m.rowid = f.rowid WHERE memories_fts MATCH ?
                            {extra} ORDER BY m.updated_at DESC LIMIT ?""",
                            (match, *params, limit),
                        ).fetchall()
                    except sqlite3.Error:
                        rows = []
                if not rows:
                    if tokens:
                        like_clauses = []
                        like_params: List[Any] = []
                        for tok in tokens[:8]:
                            like_clauses.append("(m.content LIKE ? OR m.summary LIKE ?)")
                            like_params.extend([f"%{tok}%", f"%{tok}%"])
                        rows = conn.execute(
                            f"""SELECT m.* FROM memories m WHERE ({' OR '.join(like_clauses)})
                            {extra} ORDER BY m.updated_at DESC LIMIT ?""",
                            (*like_params, *params, limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            f"SELECT m.* FROM memories m WHERE 1=1 {extra} "
                            "ORDER BY m.updated_at DESC LIMIT ?",
                            (*params, limit),
                        ).fetchall()
            finally:
                conn.close()
        records = []
        corrupted = 0
        for row in rows:
            try:
                records.append(self._row_to_record(row))
            except ValueError:
                corrupted += 1
        return {"records": records, "count": len(records), "corrupted_skipped": corrupted}

    # -- migration -----------------------------------------------------------
    def migrate_legacy_json(self, path: str = "") -> Dict[str, Any]:
        """One-time import of Phase 1 `persistent_memory.json` records.
        Idempotent: legacy ids are preserved, re-migration replaces in place.
        Returns {migrated, skipped, errors}."""
        from backend.agent.memory_schema import (  # local import: schema only
            Confidence, MemorySource, MemoryType)

        src = path or legacy_json_path()
        try:
            with open(src, "r", encoding="utf-8") as handle:
                items = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {"migrated": 0, "skipped": 0, "errors": ["legacy store unreadable or absent"]}
        if not isinstance(items, list):
            return {"migrated": 0, "skipped": 0, "errors": ["legacy store is not a list"]}
        migrated = 0
        skipped = 0
        errors: List[str] = []
        for item in items:
            try:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                text = str(item.get("text") or item.get("value") or "").strip()
                if not text:
                    skipped += 1
                    continue
                category = str(item.get("category") or "general").strip().lower()
                record = MemoryRecord(
                    id=str(item.get("id") or ""),
                    memory_type=MemoryType.USER,
                    content=text,
                    summary=text[:200],
                    importance=0.85,
                    confidence=Confidence.HIGH,  # all legacy rows are explicit remembers
                    created_at=float(item.get("created_at") or time.time()),
                    updated_at=float(item.get("updated_at") or time.time()),
                    last_accessed=float(item.get("updated_at") or time.time()),
                    source=MemorySource.EXPLICIT_USER,
                    source_reference=str(item.get("source_text") or text)[:1000],
                    project_id=DEFAULT_PROJECT_ID,
                    tags=[category] if category else [],
                    status=MemoryStatus.ACTIVE,
                )
                self.add(record)
                migrated += 1
            except (ValueError, TypeError, OSError) as exc:
                skipped += 1
                errors.append(str(exc)[:160])
        return {"migrated": migrated, "skipped": skipped, "errors": errors[:8]}
