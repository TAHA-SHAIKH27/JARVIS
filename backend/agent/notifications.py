"""notifications.py — persistent notification store for J.A.R.V.I.S.

Owns ONLY standalone notifications (gmail / whatsapp results / system).
Reminders and scheduled WhatsApp messages are NOT duplicated here — the
Notification Center reads those as views over ReminderStore and the scheduler
job store (single source of truth per entity).

Persistence: backend/data/notifications.json (atomic writes, corrupt-tolerant).
Every record has a caller-supplied stable id (e.g. "gmail:<msgid>",
"wa:<job-id>") so restarts and re-fires upsert instead of duplicating.

Retention: purge_expired() removes ONLY notifications that are read AND older
than max_age_days (default 30). Unread notifications are never auto-removed,
and future reminders / scheduled messages live in other stores, so they can
never be touched by cleanup here.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()

KINDS = ("gmail", "whatsapp", "system")
PRIORITIES = ("normal", "important", "urgent")

NOTIFICATION_RETENTION_DAYS = 30


def _data_dir() -> str:
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(path, exist_ok=True)
    return path


def _store_path() -> str:
    return os.path.join(_data_dir(), "notifications.json")


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: str, value: Any) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return item
    item.setdefault("id", str(uuid.uuid4()))
    if item.get("kind") not in KINDS:
        item["kind"] = "system"
    item.setdefault("title", "")
    item.setdefault("body", "")
    item.setdefault("speak", "")
    item.setdefault("created_at", utc_now_iso())
    item.setdefault("updated_at", item.get("created_at") or utc_now_iso())
    item.setdefault("read", False)
    item.setdefault("dismissed", False)
    if item.get("priority") not in PRIORITIES:
        item["priority"] = "normal"
    item.setdefault("ref_type", "")
    item.setdefault("ref_id", "")
    if not isinstance(item.get("meta"), dict):
        item["meta"] = {}
    return item


def _load() -> List[Dict[str, Any]]:
    value = _read_json(_store_path(), [])
    items = value if isinstance(value, list) else []
    return [_normalize(r) for r in items if isinstance(r, dict)]


def _save(items: List[Dict[str, Any]]) -> None:
    _write_json(_store_path(), [_normalize(r) for r in items])


def upsert_notification(notification_id: str, kind: str, title: str, body: str = "",
                         speak: str = "", priority: str = "normal",
                         ref_type: str = "", ref_id: str = "",
                         meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create or refresh a notification by stable id. Refreshing an existing
    unread record updates its content/timestamp; a previously read+dismissed
    record re-firing (e.g. same Gmail id) re-opens as unread so genuinely new
    arrivals are never silently swallowed."""
    notification_id = (notification_id or "").strip() or str(uuid.uuid4())
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == notification_id:
                item["kind"] = kind if kind in KINDS else item.get("kind", "system")
                item["title"] = title
                item["body"] = body
                if speak:
                    item["speak"] = speak
                if priority in PRIORITIES:
                    item["priority"] = priority
                if ref_type:
                    item["ref_type"] = ref_type
                if ref_id:
                    item["ref_id"] = ref_id
                if isinstance(meta, dict):
                    item["meta"].update(meta)
                item["updated_at"] = utc_now_iso()
                if item.get("read") and item.get("dismissed"):
                    item["read"] = False
                    item["dismissed"] = False
                _save(items)
                return {"status": "success", "notification": item, "created": False}
        item = _normalize({"id": notification_id, "kind": kind, "title": title,
                           "body": body, "speak": speak, "priority": priority,
                           "ref_type": ref_type, "ref_id": ref_id,
                           "meta": meta or {}})
        items.append(item)
        _save(items)
        return {"status": "success", "notification": item, "created": True}


def get(notification_id: str) -> Optional[Dict[str, Any]]:
    for item in _load():
        if item.get("id") == notification_id:
            return item
    return None


def list_notifications(include_dismissed: bool = False, kind: str = "",
                        unread_only: bool = False,
                        limit: int = 200) -> List[Dict[str, Any]]:
    items = _load()
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    if unread_only:
        items = [i for i in items if not i.get("read")]
    if not include_dismissed:
        items = [i for i in items if not i.get("dismissed")]
    items.sort(key=lambda i: str(i.get("updated_at") or i.get("created_at") or ""),
               reverse=True)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 200
    return items[:limit]


def unread_count() -> int:
    return sum(1 for i in _load() if not i.get("read") and not i.get("dismissed"))


def mark_read(notification_id: str) -> Dict[str, Any]:
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == notification_id:
                item["read"] = True
                item["updated_at"] = utc_now_iso()
                _save(items)
                return {"status": "success", "notification": item}
    return {"status": "error", "message": "Notification not found."}


def mark_unread(notification_id: str) -> Dict[str, Any]:
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == notification_id:
                item["read"] = False
                item["dismissed"] = False
                item["updated_at"] = utc_now_iso()
                _save(items)
                return {"status": "success", "notification": item}
    return {"status": "error", "message": "Notification not found."}


def mark_all_read() -> Dict[str, Any]:
    with _LOCK:
        items = _load()
        changed = 0
        for item in items:
            if not item.get("read"):
                item["read"] = True
                changed += 1
        if changed:
            _save(items)
    return {"status": "success", "marked": changed}


def dismiss(notification_id: str) -> Dict[str, Any]:
    """Hide from active views; the record stays for history."""
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == notification_id:
                item["dismissed"] = True
                item["updated_at"] = utc_now_iso()
                _save(items)
                return {"status": "success", "notification": item}
    return {"status": "error", "message": "Notification not found."}


def delete(notification_id: str) -> Dict[str, Any]:
    with _LOCK:
        items = _load()
        kept = [i for i in items if i.get("id") != notification_id]
        if len(kept) == len(items):
            return {"status": "error", "message": "Notification not found."}
        _save(items[:0] + kept)
    return {"status": "success", "message": "Notification deleted."}


def clear_read_history() -> Dict[str, Any]:
    """Delete notifications the user has read. Never touches unread items.
    Future reminders / scheduled messages live in other stores and are
    unaffected by construction."""
    with _LOCK:
        items = _load()
        kept = [i for i in items if not i.get("read")]
        removed = len(items) - len(kept)
        if removed:
            _save(kept)
    return {"status": "success", "cleared": removed}


def purge_expired(max_age_days: int = NOTIFICATION_RETENTION_DAYS) -> Dict[str, Any]:
    """Remove read notifications older than max_age_days. Unread notifications
    are NEVER removed. Returns counts for transparency."""
    try:
        max_age_days = max(1, int(max_age_days))
    except (TypeError, ValueError):
        max_age_days = NOTIFICATION_RETENTION_DAYS
    now = time.time()
    with _LOCK:
        items = _load()
        kept = []
        removed = 0
        for item in items:
            if item.get("read"):
                try:
                    ts = datetime.fromisoformat(
                        str(item.get("updated_at") or item.get("created_at") or "").replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    kept.append(item)
                    continue
                if now - ts > max_age_days * 86400:
                    removed += 1
                    continue
            kept.append(item)
        if removed:
            _save(kept)
    return {"status": "success", "purged": removed,
            "retention_days": max_age_days}
