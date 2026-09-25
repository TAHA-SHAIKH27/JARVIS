"""gmail_notify.py — proactive Gmail watcher for J.A.R.V.I.S.

Normal (non-agentic) JARVIS announces important mail as it arrives:
"Sir, important mail from X: <subject>." — spoken aloud via the voice
system plus an on-screen toast, without being asked.

Design:
- Gmail REST API via `requests` (already a dependency) + OAuth 2.0 desktop
  flow. Uses its OWN scope set (gmail.readonly) and its OWN token file
  (token_gmail.json) so the Gemini OAuth token is never touched.
- Polling: once shortly after backend start (restart check) and then every
  `poll_minutes` (default 30). No push infra, no paid services.
- Important-only: a message is announced only when the sender is in the VIP
  list OR subject/snippet carries an urgent keyword. Everything else is
  silently marked seen.
- Seen-state (`backend/data/gmail_seen.json`) survives restarts, so mail is
  never announced twice and a restart check only covers new arrivals.
- Every public function returns a dict and never raises — the background
  worker must never crash the backend.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from email.utils import getaddresses
from typing import Any, Dict, List, Optional

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token_gmail.json")

DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
WATCH_PATH = os.path.join(DATA_DIR, "gmail_watch.json")
SEEN_PATH = os.path.join(DATA_DIR, "gmail_seen.json")

DEFAULT_WATCH = {
    "vip_senders": [],
    "urgent_keywords": [
        "urgent", "asap", "action required", "important", "emergency",
        "deadline", "meeting", "interview", "offer letter",
    ],
    "poll_minutes": 30,
    "announce_on_restart": True,
    "max_results": 20,
}

_LOCK = threading.RLock()


# ── config / state ────────────────────────────────────────────────────────────
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


def load_watch() -> Dict[str, Any]:
    """VIP list + keywords + schedule. Creates defaults on first run."""
    with _LOCK:
        raw = _read_json(WATCH_PATH, None)
        if not isinstance(raw, dict):
            _write_json(WATCH_PATH, dict(DEFAULT_WATCH))
            return dict(DEFAULT_WATCH)
        merged = dict(DEFAULT_WATCH)
        merged.update({k: v for k, v in raw.items() if k in DEFAULT_WATCH})
        return merged


def load_seen() -> Dict[str, Any]:
    with _LOCK:
        raw = _read_json(SEEN_PATH, None)
        if not isinstance(raw, dict):
            return {"seen_ids": [], "last_check": 0.0}
        ids = raw.get("seen_ids")
        return {"seen_ids": list(ids) if isinstance(ids, list) else [],
                "last_check": float(raw.get("last_check") or 0.0)}


def _remember_seen(new_ids: List[str]) -> None:
    with _LOCK:
        state = load_seen()
        known = set(state["seen_ids"])
        known.update(new_ids)
        state["seen_ids"] = sorted(known)[-500:]  # bounded history
        state["last_check"] = time.time()
        _write_json(SEEN_PATH, state)


# ── auth (Gmail scope, own token — Gemini token untouched) ────────────────────
def is_gmail_linked() -> bool:
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
        return bool(creds and (creds.valid or (creds.expired and creds.refresh_token)))
    except Exception:
        return False


def start_gmail_oauth_flow() -> Dict[str, Any]:
    if not os.path.exists(CLIENT_SECRET_FILE):
        return {"status": "error",
                "message": "client_secret.json not found. Download an OAuth 'Desktop app' "
                           "client from Google Cloud Console first, sir."}
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as handle:
            handle.write(creds.to_json())
        return {"status": "success", "message": "Gmail linked successfully, sir."}
    except Exception as exc:
        return {"status": "error", "message": f"Gmail OAuth flow failed: {exc}"}


def logout_gmail() -> Dict[str, Any]:
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
    except OSError:
        pass
    return {"status": "success", "message": "Gmail unlinked, sir."}


def _access_token() -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as handle:
                handle.write(creds.to_json())
        return creds.token if creds and creds.valid else ""
    except Exception:
        return ""


# ── Gmail REST ────────────────────────────────────────────────────────────────
def _api_get(path: str, params: Optional[Dict[str, Any]] = None,
             timeout: int = 20) -> Optional[Dict[str, Any]]:
    try:
        import requests
        token = _access_token()
        if not token:
            return None
        resp = requests.get(f"{GMAIL_API_BASE}{path}",
                            headers={"Authorization": f"Bearer {token}"},
                            params=params or {}, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _headers_of(payload: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for header in (payload.get("headers") or []):
        name = str(header.get("name") or "").lower()
        if name in ("from", "subject", "date"):
            out[name] = str(header.get("value") or "")
    return out


def parse_sender(from_header: str) -> Dict[str, str]:
    """Split 'Name <addr>' into display name + address (never raises)."""
    try:
        pairs = getaddresses([from_header or ""])
        name, addr = pairs[0] if pairs else ("", "")
        name = (name or "").strip().strip('"')
        addr = (addr or "").strip()
        if not name:
            name = addr
        return {"name": name or "Unknown sender", "email": addr}
    except Exception:
        return {"name": (from_header or "Unknown sender")[:120], "email": ""}


def fetch_unread(limit: int = 20) -> List[Dict[str, Any]]:
    """Unread mail from the last 2 days (metadata only — no bodies)."""
    listing = _api_get("/messages",
                       {"q": "is:unread newer_than:2d", "maxResults": max(1, min(int(limit or 20), 50))})
    if not listing:
        return []
    messages: List[Dict[str, Any]] = []
    for entry in listing.get("messages") or []:
        mid = entry.get("id")
        if not mid:
            continue
        full = _api_get(f"/messages/{mid}",
                        {"format": "metadata",
                         "metadataHeaders": ["From", "Subject", "Date"]})
        if not full:
            continue
        headers = _headers_of(full.get("payload") or {})
        sender = parse_sender(headers.get("from", ""))
        messages.append({"id": mid,
                         "from_name": sender["name"],
                         "from_email": sender["email"],
                         "subject": headers.get("subject", "(no subject)"),
                         "date": headers.get("date", ""),
                         "snippet": str(full.get("snippet") or "")})
    return messages


# ── importance filter ─────────────────────────────────────────────────────────
def is_important(message: Dict[str, Any], watch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Important-only gate: VIP sender OR urgent keyword. Returns reason."""
    watch = watch or load_watch()
    sender_name = str(message.get("from_name") or "").casefold()
    sender_email = str(message.get("from_email") or "").casefold()
    for vip in watch.get("vip_senders") or []:
        needle = str(vip or "").strip().casefold()
        if needle and (needle in sender_email or needle in sender_name):
            return {"important": True, "reason": f"VIP sender ({vip})"}
    haystack = f"{message.get('subject', '')} {message.get('snippet', '')}".casefold()
    for keyword in watch.get("urgent_keywords") or []:
        needle = str(keyword or "").strip().casefold()
        if needle and needle in haystack:
            return {"important": True, "reason": f"urgent keyword ({keyword})"}
    return {"important": False, "reason": "not VIP, no urgent keyword"}


def announcement_text(message: Dict[str, Any], reason: str = "") -> str:
    sender = str(message.get("from_name") or "Unknown sender").strip()
    subject = str(message.get("subject") or "(no subject)").strip()
    if len(subject) > 140:
        subject = subject[:140].rstrip() + "…"
    return f"Sir, important mail from {sender}: {subject}."


# ── one poll cycle ────────────────────────────────────────────────────────────
def check_for_important() -> Dict[str, Any]:
    """Single cycle: fetch unread, announce only unseen+important, remember IDs.

    Never raises. Statuses: ok / not_linked / error."""
    try:
        if not is_gmail_linked():
            return {"status": "not_linked",
                    "message": "Gmail is not linked. Link it in Settings, sir.",
                    "announced": [], "checked": 0}
        watch = load_watch()
        seen = set(load_seen()["seen_ids"])
        messages = fetch_unread(limit=int(watch.get("max_results") or 20))
        announced: List[Dict[str, Any]] = []
        for message in messages:
            mid = message.get("id", "")
            verdict = is_important(message, watch)
            message["important"] = verdict["important"]
            message["reason"] = verdict["reason"]
            if verdict["important"] and mid and mid not in seen:
                message["speak"] = announcement_text(message, verdict["reason"])
                announced.append(message)
        _remember_seen([m.get("id", "") for m in messages if m.get("id")])
        return {"status": "ok", "announced": announced,
                "checked": len(messages), "important": len(announced)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200],
                "announced": [], "checked": 0}
