"""Persistent task checkpoints and universal execution history.

Stdlib-only reliability layer. It is intentionally independent of the agent
planner/executor so it can be integrated without creating a second agent.
SQLite is used for atomic persistence across JARVIS/backend restarts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

DB_ENV = "JARVIS_TASK_DB"
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "..", "jarvis_tasks.db")


def _db_path() -> str:
    return os.path.abspath(os.environ.get(DB_ENV, DEFAULT_DB))


class TaskCheckpointStore:
    """Durable task/checkpoint/history store with atomic writes."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = os.path.abspath(db_path or _db_path())
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, self._connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                plan_json TEXT NOT NULL DEFAULT '{}',
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                action_json TEXT NOT NULL,
                observation_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                verification_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(task_id, step_index),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                step_index INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, step_index);
            CREATE INDEX IF NOT EXISTS idx_history_task ON task_history(task_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_history_type ON task_history(event_type);
            """)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, default=str, ensure_ascii=False)

    @staticmethod
    def _loads(value: str, default):
        try:
            return json.loads(value)
        except Exception:
            return default

    def start_or_resume(self, task: str, task_id: Optional[str] = None,
                        plan: Optional[Dict[str, Any]] = None,
                        state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a task or return its durable resume point."""
        now = time.time()
        with self._lock, self._connect() as c:
            if task_id:
                row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM tasks WHERE task=? AND status IN ('running','paused','interrupted','failed') "
                    "ORDER BY updated_at DESC LIMIT 1", (task,)).fetchone()
            if row:
                return self._task_row(c, row)
            task_id = task_id or str(uuid.uuid4())
            c.execute(
                "INSERT INTO tasks(task_id,task,status,current_step,plan_json,state_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (task_id, task, "running", 0, self._json(plan or {}), self._json(state or {}), now, now))
            self._history_conn(c, task_id, "task_started", None, {"task": task})
            return {"task_id": task_id, "status": "running", "current_step": 0,
                    "plan": plan or {}, "state": state or {}, "checkpoints": []}

    def _task_row(self, c, row) -> Dict[str, Any]:
        checkpoints = c.execute(
            "SELECT * FROM checkpoints WHERE task_id=? ORDER BY step_index", (row["task_id"],)
        ).fetchall()
        return {
            "task_id": row["task_id"], "task": row["task"], "status": row["status"],
            "current_step": row["current_step"], "plan": self._loads(row["plan_json"], {}),
            "state": self._loads(row["state_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "checkpoints": [dict(x) | {
                "action": self._loads(x["action_json"], {}),
                "observation": self._loads(x["observation_json"], {}),
                "result": self._loads(x["result_json"], {}),
                "verification": self._loads(x["verification_json"], {}),
            } for x in checkpoints]
        }

    def save_state(self, task_id: str, status: str, current_step: int,
                   plan: Optional[Dict[str, Any]] = None,
                   state: Optional[Dict[str, Any]] = None,
                   event_type: str = "state_updated",
                   payload: Optional[Dict[str, Any]] = None):
        now = time.time()
        completed = now if status == "completed" else None
        with self._lock, self._connect() as c:
            c.execute(
                "UPDATE tasks SET status=?,current_step=?,plan_json=COALESCE(?,plan_json),"
                "state_json=COALESCE(?,state_json),updated_at=?,completed_at=COALESCE(?,completed_at) "
                "WHERE task_id=?",
                (status, int(current_step), self._json(plan) if plan is not None else None,
                 self._json(state) if state is not None else None, now, completed, task_id))
            self._history_conn(c, task_id, event_type, current_step, payload or {})

    def checkpoint(self, task_id: str, step_index: int, action: Dict[str, Any],
                   observation: Optional[Dict[str, Any]], result: Optional[Dict[str, Any]],
                   verification: Optional[Dict[str, Any]], state: Optional[Dict[str, Any]] = None):
        """Atomically record a VERIFIED step and advance the task."""
        now = time.time()
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT INTO checkpoints(task_id,step_index,action_json,observation_json,result_json,"
                "verification_json,status,created_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(task_id,step_index) DO UPDATE SET observation_json=excluded.observation_json,"
                "result_json=excluded.result_json,verification_json=excluded.verification_json,status=excluded.status",
                (task_id, int(step_index), self._json(action or {}), self._json(observation or {}),
                 self._json(result or {}), self._json(verification or {}), "verified", now))
            c.execute(
                "UPDATE tasks SET status='running',current_step=?,state_json=COALESCE(?,state_json),updated_at=? "
                "WHERE task_id=?",
                (int(step_index) + 1, self._json(state) if state is not None else None, now, task_id))
            self._history_conn(c, task_id, "checkpoint_verified", step_index,
                               {"verification": verification or {}, "result": result or {}})

    def mark(self, task_id: str, status: str, step_index: Optional[int] = None,
             payload: Optional[Dict[str, Any]] = None):
        self.save_state(task_id, status, int(step_index or 0), event_type=status, payload=payload)

    def last_verified_step(self, task_id: str) -> Optional[int]:
        with self._lock, self._connect() as c:
            row = c.execute(
                "SELECT step_index FROM checkpoints WHERE task_id=? AND status='verified' "
                "ORDER BY step_index DESC LIMIT 1", (task_id,)).fetchone()
            return int(row["step_index"]) if row else None

    def is_verified(self, task_id: str, step_index: int) -> bool:
        with self._lock, self._connect() as c:
            row = c.execute(
                "SELECT 1 FROM checkpoints WHERE task_id=? AND step_index=? AND status='verified'",
                (task_id, int(step_index))).fetchone()
            return row is not None

    def recoverable_tasks(self, stale_after_s: float = 120.0) -> List[Dict[str, Any]]:
        cutoff = time.time() - max(1.0, stale_after_s)
        with self._lock, self._connect() as c:
            rows = c.execute(
                "SELECT * FROM tasks WHERE status='running' AND updated_at < ? ORDER BY updated_at",
                (cutoff,)).fetchall()
            return [self._task_row(c, r) for r in rows]

    def search_history(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as c:
            if query.strip():
                like = f"%{query.strip()}%"
                rows = c.execute(
                    "SELECT * FROM task_history WHERE payload_json LIKE ? OR event_type LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?", (like, like, int(limit))).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM task_history ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(r) | {"payload": self._loads(r["payload_json"], {})} for r in rows]

    def history_for_task(self, task_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        return self.search_history(task_id, limit)

    def _history_conn(self, c, task_id: str, event_type: str,
                      step_index: Optional[int], payload: Dict[str, Any]):
        c.execute(
            "INSERT INTO task_history(task_id,event_type,step_index,payload_json,created_at) VALUES(?,?,?,?,?)",
            (task_id, event_type, step_index, self._json(payload), time.time()))


_default_store: Optional[TaskCheckpointStore] = None
_default_lock = threading.RLock()


def get_task_store() -> TaskCheckpointStore:
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = TaskCheckpointStore()
        return _default_store
