"""Durable task checkpoint and history persistence for J.A.R.V.I.S.

Uses the existing SQLite memory database so task continuity does not create a
second persistence system. Checkpoints are versioned, atomic, bounded, and
redacted before persistence. This module is intentionally independent of the
agent loop; AgentCore integration is a later verified step.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
SCHEMA_VERSION = 1
_DEFAULT_DB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "jarvis_memory.db")
)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
]


def db_path() -> str:
    override = os.getenv("JARVIS_MEMORY_DB", "").strip()
    return os.path.abspath(override) if override else _DEFAULT_DB


def redact(value: Any, max_chars: int = 4000) -> Any:
    """Redact likely secrets and bound persisted text."""
    if isinstance(value, dict):
        return {str(k): redact(v, max_chars) for k, v in value.items()
                if str(k).casefold() not in {"password", "secret", "api_key",
                                               "access_token", "refresh_token",
                                               "token", "authorization"}}
    if isinstance(value, list):
        return [redact(v, max_chars) for v in value[:100]]
    if isinstance(value, str):
        text = value[:max_chars]
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(lambda m: m.group(1) + ": [REDACTED]", text)
        return text
    return value


def _json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, separators=(",", ":"))


class CheckpointStore:
    """Atomic durable store for task runs, checkpoints, and task events."""

    def __init__(self, database_path: str = ""):
        self.database_path = os.path.abspath(database_path or db_path())
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        with _LOCK:
            conn = self._connect()
            try:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_version INTEGER NOT NULL DEFAULT 1,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_steps_json TEXT NOT NULL DEFAULT '[]',
                    pending_steps_json TEXT NOT NULL DEFAULT '[]',
                    state_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    checkpoint_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    state_json TEXT NOT NULL,
                    UNIQUE(task_id, checkpoint_version),
                    FOREIGN KEY(task_id) REFERENCES task_runs(task_id)
                );
                CREATE TABLE IF NOT EXISTS task_history_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    step_index INTEGER,
                    created_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_status_updated
                    ON task_runs(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_checkpoints_task_version
                    ON task_checkpoints(task_id, checkpoint_version DESC);
                CREATE INDEX IF NOT EXISTS idx_history_task_sequence
                    ON task_history_events(task_id, sequence);
                """)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        def loads(value: str, fallback: Any):
            try:
                result = json.loads(value or "")
                return result
            except (ValueError, TypeError):
                return fallback
        return {
            "task_id": row["task_id"],
            "task": row["task"],
            "status": row["status"],
            "plan_version": int(row["plan_version"]),
            "current_step": int(row["current_step"]),
            "schema_version": int(row["schema_version"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "completed_steps": loads(row["completed_steps_json"], []),
            "pending_steps": loads(row["pending_steps_json"], []),
            "state": loads(row["state_json"], {}),
        }

    def create_or_update_run(self, task_id: str, task: str, status: str,
                             current_step: int = 0,
                             completed_steps: Optional[List[int]] = None,
                             pending_steps: Optional[List[int]] = None,
                             state: Optional[Dict[str, Any]] = None,
                             plan_version: int = 1) -> Dict[str, Any]:
        if not task_id:
            task_id = str(uuid.uuid4())
        now = time.time()
        safe_state = redact(state or {})
        with _LOCK:
            conn = self._connect()
            try:
                conn.execute("""
                    INSERT INTO task_runs
                    (task_id, task, status, plan_version, current_step, schema_version,
                     created_at, updated_at, completed_steps_json, pending_steps_json, state_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      task=excluded.task, status=excluded.status,
                      plan_version=excluded.plan_version, current_step=excluded.current_step,
                      schema_version=excluded.schema_version, updated_at=excluded.updated_at,
                      completed_steps_json=excluded.completed_steps_json,
                      pending_steps_json=excluded.pending_steps_json, state_json=excluded.state_json
                """, (task_id, str(task or "")[:2000], str(status or "running"),
                      int(plan_version), int(current_step), SCHEMA_VERSION, now, now,
                      _json(completed_steps or []), _json(pending_steps or []), _json(safe_state)))
                conn.commit()
                row = conn.execute("SELECT * FROM task_runs WHERE task_id=?", (task_id,)).fetchone()
                return self._decode(row)
            finally:
                conn.close()

    def save_checkpoint(self, task_id: str, kind: str, step_index: int,
                        state: Dict[str, Any], verified: bool = False) -> Dict[str, Any]:
        """Atomically append a checkpoint and update the current run."""
        now = time.time()
        safe_state = redact(state or {})
        with _LOCK:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT COALESCE(MAX(checkpoint_version), 0) AS v FROM task_checkpoints WHERE task_id=?",
                    (task_id,)).fetchone()
                version = int(row["v"] or 0) + 1
                conn.execute("""
                    INSERT INTO task_checkpoints
                    (task_id, checkpoint_version, kind, step_index, verified, created_at, state_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (task_id, version, str(kind or "unknown")[:80], int(step_index),
                      1 if verified else 0, now, _json(safe_state)))
                conn.execute(
                    "UPDATE task_runs SET current_step=?, updated_at=?, state_json=? WHERE task_id=?",
                    (int(step_index), now, _json(safe_state), task_id))
                conn.commit()
                return {"task_id": task_id, "checkpoint_version": version,
                        "kind": str(kind or "unknown"), "step_index": int(step_index),
                        "verified": bool(verified), "created_at": now}
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def latest_valid_checkpoint(self, task_id: str) -> Optional[Dict[str, Any]]:
        with _LOCK:
            conn = self._connect()
            try:
                row = conn.execute("""
                    SELECT * FROM task_checkpoints
                    WHERE task_id=? AND verified=1
                    ORDER BY checkpoint_version DESC LIMIT 1
                """, (task_id,)).fetchone()
                if row is None:
                    return None
                try:
                    state = json.loads(row["state_json"] or "{}")
                except (ValueError, TypeError):
                    return None
                if not isinstance(state, dict):
                    return None
                return {
                    "task_id": row["task_id"],
                    "checkpoint_version": int(row["checkpoint_version"]),
                    "kind": row["kind"],
                    "step_index": int(row["step_index"]),
                    "verified": bool(row["verified"]),
                    "created_at": float(row["created_at"]),
                    "state": redact(state),
                }
            finally:
                conn.close()

    def append_event(self, task_id: str, event_type: str,
                     payload: Optional[Dict[str, Any]] = None,
                     step_index: Optional[int] = None) -> Dict[str, Any]:
        with _LOCK:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS n FROM task_history_events WHERE task_id=?",
                    (task_id,)).fetchone()
                sequence = int(row["n"] or 0) + 1
                now = time.time()
                conn.execute("""
                    INSERT INTO task_history_events
                    (task_id, sequence, event_type, step_index, created_at, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (task_id, sequence, str(event_type or "event")[:80],
                      step_index, now, _json(payload or {})))
                conn.commit()
                return {"task_id": task_id, "sequence": sequence,
                        "event_type": str(event_type or "event"), "created_at": now}
            finally:
                conn.close()

    def get_run(self, task_id: str) -> Optional[Dict[str, Any]]:
        with _LOCK:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM task_runs WHERE task_id=?", (task_id,)).fetchone()
                return self._decode(row) if row else None
            finally:
                conn.close()

    def list_resumable(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 100))
        with _LOCK:
            conn = self._connect()
            try:
                rows = conn.execute("""
                    SELECT * FROM task_runs
                    WHERE status IN ('running','paused','interrupted','recovering')
                    ORDER BY updated_at DESC LIMIT ?
                """, (limit,)).fetchall()
                return [self._decode(row) for row in rows]
            finally:
                conn.close()

    def history(self, task_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 1000))
        with _LOCK:
            conn = self._connect()
            try:
                rows = conn.execute("""
                    SELECT task_id, sequence, event_type, step_index, created_at, payload_json
                    FROM task_history_events WHERE task_id=?
                    ORDER BY sequence ASC LIMIT ?
                """, (task_id, limit)).fetchall()
                result = []
                for row in rows:
                    try:
                        payload = json.loads(row["payload_json"] or "{}")
                    except (ValueError, TypeError):
                        payload = {}
                    result.append({
                        "task_id": row["task_id"], "sequence": int(row["sequence"]),
                        "event_type": row["event_type"], "step_index": row["step_index"],
                        "created_at": float(row["created_at"]), "payload": redact(payload),
                    })
                return result
            finally:
                conn.close()
