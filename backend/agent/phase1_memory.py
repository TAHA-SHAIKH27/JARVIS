"""Persistent memory foundation for JARVIS Phase 1.

Stores explicit user memories in a normalized, searchable form. The store is
kept beside the application data and protected by an in-process lock.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "has", "have", "how", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "please", "that", "the", "this",
    "to", "was", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your", "remember", "recall", "tell", "about", "know", "think",
}


def _memory_path() -> str:
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
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(items, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        last_error = None
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(0.15)
        if last_error is not None:
            raise last_error
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = text.rstrip(".!?; ")
    return text


def _normalize_memory(text: str) -> Dict[str, str]:
    """Turn common personal-fact sentences into compact searchable facts."""
    cleaned = _clean_text(text)
    lower = cleaned.casefold()

    # Common personal-fact form: "my favorite color is blue" ->
    # "favorite color: blue". Keep the original text as source_text.
    match = re.match(r"^(?:my|i(?:'m| am)?)\s+(.+?)\s+(?:is|are|=)\s+(.+)$", cleaned, re.I)
    if match:
        key = _clean_text(match.group(1))
        value = _clean_text(match.group(2))
        key = re.sub(r"^(?:my|i)\s+", "", key, flags=re.I)
        return {"text": f"{key}: {value}", "key": key.casefold(), "value": value}

    match = re.match(r"^(?:i)\s+(?:prefer|like|love|use|own|have)\s+(.+)$", cleaned, re.I)
    if match:
        value = _clean_text(match.group(1))
        return {"text": cleaned, "key": "preference", "value": value}

    # Generic memory: preserve the fact, but normalize whitespace/punctuation.
    return {"text": cleaned, "key": "", "value": cleaned}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_'-]*", (text or "").casefold())
    return {word for word in words if word not in _STOP_WORDS and len(word) > 1}


def remember(text: str, category: str = "general", source: str = "user") -> Dict[str, Any]:
    """Persist an explicit memory in normalized, searchable form."""
    original = _clean_text(text)
    category = (category or "general").strip().lower()
    if not original:
        return {"status": "error", "message": "Memory text cannot be empty."}

    normalized = _normalize_memory(original)
    stored_text = normalized["text"]
    now = time.time()

    with _LOCK:
        items = _load()
        for item in items:
            same_text = item.get("text", "").casefold() == stored_text.casefold()
            same_key_value = (
                normalized["key"]
                and item.get("key", "").casefold() == normalized["key"].casefold()
                and item.get("value", "").casefold() == normalized["value"].casefold()
            )
            if same_text or same_key_value:
                item["updated_at"] = now
                item.setdefault("source_text", original)
                item["key"] = normalized["key"]
                item["value"] = normalized["value"]
                _save(items)
                return {"status": "success", "message": "Memory already existed; timestamp updated.", "memory": item}

        item = {
            "id": str(uuid.uuid4()),
            "text": stored_text,
            "source_text": original,
            "key": normalized["key"],
            "value": normalized["value"],
            "category": category,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        _save(items)
        return {"status": "success", "message": "Memory saved.", "memory": item}


def recall(query: str = "", category: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Recall the most relevant explicit memories using token/field matching."""
    query = _clean_text(query)
    query_tokens = _tokens(query)
    category = (category or "").strip().lower()
    limit = max(1, min(int(limit or 20), 100))

    with _LOCK:
        items = _load()
        candidates = [item for item in items if not category or item.get("category", "").lower() == category]

        if not query_tokens:
            candidates.sort(key=lambda item: item.get("updated_at", item.get("created_at", 0)), reverse=True)
            matches = candidates[:limit]
        else:
            scored = []
            for item in candidates:
                searchable = " ".join([
                    str(item.get("text", "")),
                    str(item.get("source_text", "")),
                    str(item.get("key", "")),
                    str(item.get("value", "")),
                ])
                item_tokens = _tokens(searchable)
                overlap = query_tokens & item_tokens
                score = len(overlap)
                key = str(item.get("key", "")).casefold()
                if key and any(token in key for token in query_tokens):
                    score += 2
                if score:
                    scored.append((score, item.get("updated_at", item.get("created_at", 0)), item))
            scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
            matches = [entry[2] for entry in scored[:limit]]

        return {"status": "success", "memories": matches, "count": len(matches)}


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
    """Return compact memory facts suitable for an LLM prompt."""
    result = recall(query=query, limit=limit)
    memories = result.get("memories", [])
    if not memories:
        return "No stored memories relevant to this task."
    return "\n".join(f"- [{m.get('category', 'general')}] {m.get('text', '')}" for m in memories)
