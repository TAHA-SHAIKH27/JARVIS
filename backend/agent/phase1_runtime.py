"""JARVIS Phase 1 runtime foundation.

Provides a small, dependency-light state layer for memory, conversation
context, reminders, intent normalization, and task lifecycle tracking. The
module is intentionally independent from the UI and from any model provider
so the existing AgentCore can consume it without coupling Phase 1 to Gemini.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.agent import phase1_memory

_LOCK = threading.RLock()


def _data_dir() -> str:
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(path, exist_ok=True)
    return path


def _conversation_path() -> str:
    return os.path.join(_data_dir(), "conversation_context.json")


def _reminder_path() -> str:
    return os.path.join(_data_dir(), "reminders.json")


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: str, value: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_intent(text: str) -> Dict[str, Any]:
    """Normalize common natural-language intent without changing the command."""
    original = (text or "").strip()
    lower = original.casefold()
    intent = "conversation"
    if any(k in lower for k in ("remember", "don't forget", "do not forget", "keep in mind")):
        intent = "remember"
    elif any(k in lower for k in ("remind me", "reminder", "remind")):
        intent = "reminder"
    elif any(k in lower for k in ("clear memory", "forget everything", "forget this")):
        intent = "forget"
    elif any(k in lower for k in ("search", "research", "look up", "find online")):
        intent = "research"
    elif any(k in lower for k in ("create a word", "make a word", "docx", "document")):
        intent = "document"
    elif any(k in lower for k in ("calculate", "compute", "calculator")):
        intent = "calculation"
    elif any(k in lower for k in ("open ", "close ", "launch ", "type ", "click ")):
        intent = "computer_action"
    return {"text": original, "normalized": lower, "intent": intent}


class ConversationContext:
    """Persistent bounded conversation context for continuity between requests."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max(2, int(max_turns))

    def _load(self) -> List[Dict[str, Any]]:
        with _LOCK:
            value = _read_json(_conversation_path(), [])
            return value if isinstance(value, list) else []

    def add(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        content = (content or "").strip()
        role = (role or "user").strip().lower()
        if not content:
            return {"status": "error", "message": "Conversation content cannot be empty."}
        item = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": utc_now(),
        }
        with _LOCK:
            turns = self._load()
            turns.append(item)
            _write_json(_conversation_path(), turns[-self.max_turns:])
        return {"status": "success", "turn": item}

    def list(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        turns = self._load()
        return turns[-max(1, int(limit or self.max_turns)):]

    def clear(self) -> Dict[str, Any]:
        with _LOCK:
            _write_json(_conversation_path(), [])
        return {"status": "success", "message": "Conversation context cleared."}

    def prompt_context(self, limit: int = 12) -> str:
        turns = self.list(limit)
        if not turns:
            return "No previous conversation context."
        return "\n".join(f"{t['role']}: {t['content']}" for t in turns)


class ReminderStore:
    """Persistent reminder records; scheduling is intentionally external."""

    def _load(self) -> List[Dict[str, Any]]:
        value = _read_json(_reminder_path(), [])
        return value if isinstance(value, list) else []

    def add(self, text: str, due_at: Optional[str] = None, repeat: Optional[str] = None) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"status": "error", "message": "Reminder text cannot be empty."}
        item = {
            "id": str(uuid.uuid4()),
            "text": text,
            "due_at": due_at,
            "repeat": repeat,
            "completed": False,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with _LOCK:
            reminders = self._load()
            reminders.append(item)
            _write_json(_reminder_path(), reminders)
        return {"status": "success", "message": "Reminder saved.", "reminder": item}

    def list(self, include_completed: bool = False) -> List[Dict[str, Any]]:
        reminders = self._load()
        if include_completed:
            return reminders
        return [r for r in reminders if not r.get("completed")]

    def complete(self, reminder_id: str) -> Dict[str, Any]:
        with _LOCK:
            reminders = self._load()
            for reminder in reminders:
                if reminder.get("id") == reminder_id:
                    reminder["completed"] = True
                    reminder["updated_at"] = utc_now()
                    _write_json(_reminder_path(), reminders)
                    return {"status": "success", "reminder": reminder}
        return {"status": "error", "message": "Reminder not found."}

    def remove(self, reminder_id: str) -> Dict[str, Any]:
        with _LOCK:
            reminders = self._load()
            kept = [r for r in reminders if r.get("id") != reminder_id]
            if len(kept) == len(reminders):
                return {"status": "error", "message": "Reminder not found."}
            _write_json(_reminder_path(), kept)
            return {"status": "success", "message": "Reminder deleted."}


class Phase1Runtime:
    """Unified Phase 1 state facade used by the agent runtime."""

    def __init__(self, max_turns: int = 20):
        self.conversation = ConversationContext(max_turns=max_turns)
        self.reminders = ReminderStore()

    def begin_task(self, task: str) -> Dict[str, Any]:
        normalized = normalize_intent(task)
        self.conversation.add("user", task, {"intent": normalized["intent"]})
        return {
            "task_id": str(uuid.uuid4()),
            "started_at": utc_now(),
            "intent": normalized,
            "memory_context": phase1_memory.memory_context(task, limit=8),
            "conversation_context": self.conversation.prompt_context(limit=8),
        }

    def finish_task(self, task: str, result: Dict[str, Any]) -> None:
        status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
        summary = result.get("speak", "") if isinstance(result, dict) else ""
        self.conversation.add("assistant", summary or f"Task finished with status: {status}", {"task": task, "status": status})

    def context_for(self, task: str) -> Dict[str, str]:
        return {
            "memory": phase1_memory.memory_context(task, limit=8),
            "conversation": self.conversation.prompt_context(limit=12),
        }


runtime = Phase1Runtime()
