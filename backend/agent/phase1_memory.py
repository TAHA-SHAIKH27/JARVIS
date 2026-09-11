"""Persistent memory foundation for JARVIS Phase 1.

Stores only explicit memories supplied by the agent/user. The store is kept
outside the source tree when possible and is safe to use from concurrent
requests via an in-process lock.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional


_LOCK = threading.RLock()


def _memory_path() -> str:
    # Keep runtime data beside the application data rather than hard-coding
    # a developer's Windows path into the agent.
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "memory.json")


def _load() -> List[Dict[str, Any]]:
    path = _memory_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    path = _memory_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(items, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def remember(text: str, category: str = "general", source: str = "user") -> Dict[str, Any]:
    """Persist an explicit memory and return its record."""
    text = (text or "").strip()
    category = (category or "general").strip().lower()
    if not text:
        return {"status": "error", "message": "Memory text cannot be empty."}

    with _LOCK:
        items = _load()
        # Avoid creating duplicates when the same memory is repeated.
        for item in items:
            if item.get("text", "").casefold() == text.casefold():
                item["updated_at"] = time.time()
                _save(items)
                return {"status": "success", "message": "Memory already existed; timestamp updated.", "memory": item}

        item = {
            "id": str(uuid.uuid4()),
            "text": text,
            "category": category,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        items.append(item)
        _save(items)
        return {"status": "success", "message": "Memory saved.", "memory": item}


def recall(query: str = "", category: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Recall explicit memories matching a query/category."""
    query = (query or "").strip().casefold()
    category = (category or "").strip().lower()
    limit = max(1, min(int(limit or 20), 100))

    with _LOCK:
        items = _load()
        matches = [
            item for item in items
            if (not category or item.get("category", "").lower() == category)
            and (not query or query in item.get("text", "").casefold())
        ]
        matches.sort(key=lambda item: item.get("updated_at", item.get("created_at", 0)), reverse=True)
        return {"status": "success", "memories": matches[:limit], "count": len(matches)}


def forget(memory_id: str) -> Dict[str, Any]:
    """Delete one explicit memory by ID."""
    memory_id = (memory_id or "").strip()
    with _LOCK:
        items = _load()
        kept = [item for item in items if item.get("id") != memory_id]
        if len(kept) == len(items):
            return {"status": "error", "message": "Memory not found."}
        _save(kept)
        return {"status": "success", "message": "Memory deleted.", "memory_id": memory_id}


def clear() -> Dict[str, Any]:
    """Clear all explicit persistent memories."""
    with _LOCK:
        _save([])
    return {"status": "success", "message": "Persistent memory cleared."}


def memory_context(query: str = "", limit: int = 8) -> str:
    """Return a compact text context suitable for an LLM prompt."""
    result = recall(query=query, limit=limit)
    memories = result.get("memories", [])
    if not memories:
        return "No stored memories relevant to this task."
    return "\n".join(f"- [{m.get('category', 'general')}] {m.get('text', '')}" for m in memories)
