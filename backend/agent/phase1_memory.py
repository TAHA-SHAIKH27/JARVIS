"""Persistent memory foundation for JARVIS Phase 1.

Stores explicit user memories in a normalized, structured, and searchable form.
Persistent memory is saved in backend/data/persistent_memory.json.
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
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "how's", "hows",
    "i", "if", "in", "is", "isn't", "isnt", "it", "it's", "its", "me", "my", "of",
    "on", "or", "our", "please", "so", "that", "that's", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "was", "wasn't",
    "we", "were", "what", "what's", "whats", "when", "where", "where's", "which",
    "who", "who's", "whom", "why", "will", "with", "won't", "would", "you", "your",
    "you're", "youre", "remember", "recall", "tell", "about", "know", "think",
    "mind", "say", "said", "ask", "asked", "mention", "mentioned", "again", "sir",
}

_MEMORY_PREFIX_REGEX = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:i\s+want\s+you\s+to\s+)?"
    r"(?:remember\s+that|remember\s+this:?|remember:?|remember|"
    r"don't\s+forget\s+that|don't\s+forget|do\s+not\s+forget\s+that|do\s+not\s+forget|"
    r"keep\s+in\s+mind\s+that|keep\s+in\s+mind|"
    r"save\s+(?:this\s+)?to\s+memory:?|save\s+to\s+memory:?|"
    r"note\s+that|note:?)\s*",
    re.IGNORECASE,
)


def _memory_path() -> str:
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "persistent_memory.json")


def _load() -> List[Dict[str, Any]]:
    path = _memory_path()
    legacy_path = os.path.join(os.path.dirname(path), "memory.json")

    items = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            items = data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            items = []
    elif os.path.exists(legacy_path):
        try:
            with open(legacy_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            items = data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            items = []

    # Ensure backward compatibility and structured fields on all loaded items
    for item in items:
        if not isinstance(item, dict):
            continue
        if "source_text" not in item:
            item["source_text"] = item.get("text", "")
        if "key" not in item or "value" not in item:
            normalized = _normalize_memory(item.get("text", ""))
            item.setdefault("key", normalized["key"])
            item.setdefault("value", normalized["value"])
            if not item.get("text"):
                item["text"] = normalized["text"]

    return items


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
    """Turn explicit memory text into structured (key, value, text) format.
    
    Examples:
      - "Remember my favorite color is blue" -> key: "favorite color", value: "blue", text: "favorite color: blue"
      - "My favorite food is pizza" -> key: "favorite food", value: "pizza", text: "favorite food: pizza"
      - "I live in London" -> key: "location", value: "London", text: "location: London"
      - "favorite color: blue" -> key: "favorite color", value: "blue", text: "favorite color: blue"
    """
    cleaned = _clean_text(text)
    if not cleaned:
        return {"text": "", "key": "", "value": ""}

    # Strip conversational prefixes ("Remember that", "Please remember", etc.)
    stripped = _MEMORY_PREFIX_REGEX.sub("", cleaned).strip()
    stripped = stripped.rstrip(".!?; ")
    if not stripped:
        stripped = cleaned

    # 1. Pre-formatted "key: value" or "key = value"
    match = re.match(r"^([a-z0-9\s'_/-]+?)\s*[:=]\s*(.+)$", stripped, re.I)
    if match:
        key = _clean_text(match.group(1))
        value = _clean_text(match.group(2))
        key = re.sub(r"^(?:my|i)\s+", "", key, flags=re.I).strip()
        return {"text": f"{key}: {value}", "key": key.casefold(), "value": value}

    # 2. Personal fact pattern: "my [key] is [value]" or "i am / i'm [value]"
    match = re.match(r"^(?:my|i(?:'m| am)?)\s+(.+?)\s+(?:is|are|was|were|=)\s+(.+)$", stripped, re.I)
    if match:
        raw_key = _clean_text(match.group(1))
        value = _clean_text(match.group(2))
        key = re.sub(r"^(?:my|i)\s+", "", raw_key, flags=re.I).strip()
        if key:
            return {"text": f"{key}: {value}", "key": key.casefold(), "value": value}

    # 3. Location / workplace patterns
    match = re.match(r"^i\s+(?:live\s+in|reside\s+in|am\s+located\s+in)\s+(.+)$", stripped, re.I)
    if match:
        value = _clean_text(match.group(1))
        return {"text": f"location: {value}", "key": "location", "value": value}

    match = re.match(r"^i\s+(?:work\s+at|work\s+for)\s+(.+)$", stripped, re.I)
    if match:
        value = _clean_text(match.group(1))
        return {"text": f"workplace: {value}", "key": "workplace", "value": value}

    match = re.match(r"^i(?:'m| am)\s+(?:a|an)\s+(.+)$", stripped, re.I)
    if match:
        value = _clean_text(match.group(1))
        return {"text": f"profession: {value}", "key": "profession", "value": value}

    # 4. Preferences: "I prefer / like / love / use ..."
    match = re.match(r"^i\s+(?:prefer|like|love|use|own|have)\s+(.+)$", stripped, re.I)
    if match:
        value = _clean_text(match.group(1))
        return {"text": f"preference: {value}", "key": "preference", "value": value}

    # Generic fact
    return {"text": stripped, "key": "", "value": stripped}


def _tokens(text: str) -> set[str]:
    """Tokenize text into lowercase words, stripping apostrophes and stop words."""
    norm = (text or "").casefold().replace("’", "'")
    # Replace common contractions
    norm = re.sub(r"'(?:s|re|ve|d|ll|m|t)\b", "", norm)
    words = re.findall(r"[a-z0-9]+", norm)
    return {word for word in words if word not in _STOP_WORDS and len(word) > 1}


def remember(text: str, category: str = "general", source: str = "user", source_text: Optional[str] = None) -> Dict[str, Any]:
    """Persist an explicit memory in normalized, structured, and searchable form."""
    original = _clean_text(text)
    raw_source = _clean_text(source_text or text)
    category = (category or "general").strip().lower()
    if not original:
        return {"status": "error", "message": "Memory text cannot be empty."}

    normalized = _normalize_memory(original)
    stored_text = normalized["text"]
    stored_key = normalized["key"]
    stored_value = normalized["value"]
    now = time.time()

    with _LOCK:
        items = _load()
        for item in items:
            same_text = item.get("text", "").casefold() == stored_text.casefold()
            same_source = item.get("source_text", "").casefold() == raw_source.casefold()
            same_key_value = (
                stored_key
                and item.get("key", "").casefold() == stored_key.casefold()
                and item.get("value", "").casefold() == stored_value.casefold()
            )
            if same_text or same_source or same_key_value:
                item["updated_at"] = now
                if raw_source:
                    item["source_text"] = raw_source
                item["key"] = stored_key
                item["value"] = stored_value
                item["text"] = stored_text
                _save(items)
                return {"status": "success", "message": "Memory already existed; timestamp updated.", "memory": item}

            # If same key exists with a different value (and not generic 'preference'), update the value
            if stored_key and stored_key != "preference" and item.get("key", "").casefold() == stored_key.casefold():
                item["updated_at"] = now
                item["source_text"] = raw_source or original
                item["value"] = stored_value
                item["text"] = stored_text
                _save(items)
                return {"status": "success", "message": "Memory updated.", "memory": item}

        item = {
            "id": str(uuid.uuid4()),
            "text": stored_text,
            "source_text": raw_source or original,
            "key": stored_key,
            "value": stored_value,
            "category": category,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        _save(items)
        return {"status": "success", "message": "Memory saved.", "memory": item}


def recall(query: str = "", category: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Recall the most relevant memories using field-aware token and phrase matching."""
    clean_query = _clean_text(query).casefold().replace("’", "'")
    query_tokens = _tokens(clean_query)
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
                key = str(item.get("key", "")).casefold()
                val = str(item.get("value", "")).casefold()
                text = str(item.get("text", "")).casefold()
                src = str(item.get("source_text", "")).casefold()

                key_tokens = _tokens(key)
                val_tokens = _tokens(val)
                all_item_tokens = _tokens(f"{text} {src} {key} {val}")

                score = 0

                # 1. Key phrase substring in query (e.g. "favorite color" in "what is my favorite color")
                if key and key in clean_query:
                    score += 15

                # 2. Key tokens subset matching (e.g. both 'favorite' and 'color' are in query)
                if key_tokens and key_tokens.issubset(query_tokens):
                    score += 10

                # 3. Key token overlap
                key_overlap = len(key_tokens & query_tokens)
                score += key_overlap * 4

                # 4. Value token overlap
                val_overlap = len(val_tokens & query_tokens)
                score += val_overlap * 2

                # 5. General token overlap across text and source_text
                general_overlap = len(all_item_tokens & query_tokens)
                score += general_overlap

                if score > 0:
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
        legacy_path = os.path.join(os.path.dirname(_memory_path()), "memory.json")
        if os.path.exists(legacy_path):
            try:
                os.remove(legacy_path)
            except OSError:
                pass
    return {"status": "success", "message": "Persistent memory cleared."}


def memory_context(query: str = "", limit: int = 8) -> str:
    """Return compact memory facts suitable for an LLM prompt."""
    result = recall(query=query, limit=limit)
    memories = result.get("memories", [])
    if not memories:
        return "No stored memories relevant to this task."
    return "\n".join(f"- [{m.get('category', 'general')}] {m.get('text', '')}" for m in memories)
