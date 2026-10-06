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

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send"]
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
    # Toast (on-screen + Notification Center) for EVERY new arrival, not just
    # important ones. Voice announcements stay important-only so newsletters
    # never start talking; set "speak_all": true to voice everything.
    "notify_all": True,
    "speak_all": False,
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
# _LAST_API_ERROR lets readers tell "empty inbox" apart from "API failed":
# None = last call worked (possibly zero results), otherwise one of
# "no_token" | "http_<code>" | "network".
# _LAST_API_DETAIL holds the Gmail error reason/message body (e.g.
# "accessNotConfigured" / "SERVICE_DISABLED" when the Gmail API itself is
# disabled in the Google Cloud project) so we can tell the user the real
# fix instead of a generic "re-link" line.
_LAST_API_ERROR: Optional[str] = None
_LAST_API_DETAIL: str = ""


def last_api_error() -> Optional[str]:
    """Why the last Gmail call failed, or None if it succeeded."""
    return _LAST_API_ERROR


def last_api_detail() -> str:
    """Raw Gmail error reason/message from the last failed call ('' if none)."""
    return _LAST_API_DETAIL


def _record_api_failure(status_code: int, resp: Any = None) -> None:
    """Store http_<code> plus any machine-readable Gmail reason."""
    global _LAST_API_ERROR, _LAST_API_DETAIL
    _LAST_API_ERROR = f"http_{status_code}"
    _LAST_API_DETAIL = ""
    try:
        data = resp.json() if resp is not None else None
        err = (data or {}).get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            bits: List[str] = []
            for entry in err.get("errors") or []:
                if isinstance(entry, dict):
                    for key in ("reason", "message"):
                        val = str(entry.get(key) or "").strip()
                        if val:
                            bits.append(val)
            for detail in err.get("details") or []:
                if isinstance(detail, dict):
                    reason = str(detail.get("reason") or "").strip()
                    if reason:
                        bits.append(reason)
            msg = str(err.get("message") or "").strip()
            if msg:
                bits.append(msg)
            _LAST_API_DETAIL = " | ".join(bits)[:2000]
    except Exception:
        pass


def _api_get(path: str, params: Optional[Dict[str, Any]] = None,
             timeout: int = 20) -> Optional[Dict[str, Any]]:
    global _LAST_API_ERROR, _LAST_API_DETAIL
    _LAST_API_ERROR = None
    _LAST_API_DETAIL = ""
    try:
        import requests
        token = _access_token()
        if not token:
            _LAST_API_ERROR = "no_token"
            return None
        resp = requests.get(f"{GMAIL_API_BASE}{path}",
                            headers={"Authorization": f"Bearer {token}"},
                            params=params or {}, timeout=timeout)
        if resp.status_code != 200:
            _record_api_failure(resp.status_code, resp)
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        if not _LAST_API_ERROR:
            _LAST_API_ERROR = "network"
        return None


def _api_post(path: str, payload: Dict[str, Any],
              timeout: int = 20) -> Optional[Dict[str, Any]]:
    """POST helper (used for sending). Same error tracking as _api_get."""
    global _LAST_API_ERROR, _LAST_API_DETAIL
    _LAST_API_ERROR = None
    _LAST_API_DETAIL = ""
    try:
        import requests
        token = _access_token()
        if not token:
            _LAST_API_ERROR = "no_token"
            return None
        resp = requests.post(f"{GMAIL_API_BASE}{path}",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json"},
                             json=payload, timeout=timeout)
        if resp.status_code not in (200, 201):
            _record_api_failure(resp.status_code, resp)
            return None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}
    except Exception:
        if not _LAST_API_ERROR:
            _LAST_API_ERROR = "network"
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


def _fetch_messages(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch message metadata for a Gmail search query (newest first).

    Detail GETs run in parallel (threads) — sequential fetches stalled
    replies ~12s for 10 mails and tripped the watchdog health check.
    Order is preserved (newest first). Never raises.
    """
    listing = _api_get("/messages",
                       {"q": query, "maxResults": max(1, min(int(limit or 20), 50))})
    if not listing:
        return []
    entries = [e for e in (listing.get("messages") or []) if e.get("id")]
    if not entries:
        return []

    def _detail(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        mid = entry.get("id")
        try:
            full = _api_get(f"/messages/{mid}",
                            {"format": "metadata",
                             "metadataHeaders": ["From", "Subject", "Date"]})
        except Exception:
            return None
        if not full:
            return None
        try:
            headers = _headers_of(full.get("payload") or {})
            sender = parse_sender(headers.get("from", ""))
            return {"id": mid,
                    "from_name": sender["name"],
                    "from_email": sender["email"],
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "snippet": str(full.get("snippet") or "")}
        except Exception:
            return None

    messages: List[Dict[str, Any]] = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(10, len(entries)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for msg in pool.map(_detail, entries):
                if msg:
                    messages.append(msg)
    except Exception:
        # Fallback: sequential (never break callers if threads fail).
        for entry in entries:
            try:
                msg = _detail(entry)
                if msg:
                    messages.append(msg)
            except Exception:
                continue
    # Parallel _api_get calls race on the global error flag; normalize it:
    # messages present => success, none => preserve the failure signal.
    global _LAST_API_ERROR
    try:
        if messages:
            _LAST_API_ERROR = None
        elif not _LAST_API_ERROR:
            _LAST_API_ERROR = "network"
    except Exception:
        pass
    return messages


def count_messages(query: str) -> int:
    """resultSizeEstimate for a query (for 'how many' questions). -1 if unknown."""
    listing = _api_get("/messages", {"q": query, "maxResults": 1})
    if not listing:
        return -1
    try:
        return max(0, int(listing.get("resultSizeEstimate", 0)))
    except (TypeError, ValueError):
        return -1


def _inbox_query(unread: bool = False, days: int = 0, older_than_days: int = 0) -> str:
    """'in:inbox' plus optional is:unread / newer_than:Nd / older_than:Md."""
    parts = ["in:inbox"]
    if unread:
        parts.append("is:unread")
    try:
        if int(days or 0) > 0:
            parts.append(f"newer_than:{int(days)}d")
        if int(older_than_days or 0) > 0:
            parts.append(f"older_than:{int(older_than_days)}d")
    except (TypeError, ValueError):
        pass
    return " ".join(parts)


def fetch_unread(limit: int = 20) -> List[Dict[str, Any]]:
    """Unread mail from the last 2 days (metadata only — no bodies)."""
    return _fetch_messages("is:unread newer_than:2d", limit)


def fetch_latest(limit: int = 5, query: str = "") -> List[Dict[str, Any]]:
    """Most recent inbox mail regardless of read state (metadata only)."""
    return _fetch_messages(query.strip() or "in:inbox", limit)


def _short_date(date_header: str) -> str:
    """'Mon, 29 Sep 2026 14:22:10 +0530' -> 'Mon 29 Sep, 2:22 PM' (best-effort)."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(str(date_header or ""))
        return dt.strftime("%a %d %b, %-I:%M %p")
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(str(date_header or ""))
            return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
        except Exception:
            return (date_header or "").strip()[:40]


def _api_error_message() -> str:
    """Honest user-facing line for the last API failure (never 'inbox clear')."""
    err = last_api_error()
    detail = last_api_detail().lower()
    if "accessnotconfigured" in detail or "service_disabled" in detail or \
            "has not been used in project" in detail or "gmail api has not been used" in detail:
        return ("The Gmail API is disabled in your Google Cloud project, sir — "
                "so Google blocks every request before it even checks my login. "
                "Enable it here: console.cloud.google.com/apis/library/gmail.googleapis.com "
                "(click Enable, wait 2-3 minutes), then ask me to check mail again. "
                "No re-login needed — your linked account already has the right permission.")
    if err in ("http_401", "http_403"):
        return ("Gmail refused the request, sir — my permission likely expired. "
                "Please re-link Gmail in Settings.")
    if err == "no_token":
        return ("My Gmail session has expired, sir — please re-link Gmail in Settings.")
    return ("I couldn't reach Gmail just now, sir — network or Google hiccup. "
            "Please try again in a moment.")


def read_latest_mail(count: int = 1, sender: str = "",
                     unread_only: bool = False, days: int = 0,
                     older_than_days: int = 0) -> Dict[str, Any]:
    """Answer mail questions via the Gmail API — no app is opened.

    days/older_than_days scope the window ("last 5 days" -> days=5,
    "yesterday" -> days=2 + older_than_days=1). Never raises. Statuses:
    ok / not_linked / empty / error. `total` = inbox count for the query.
    """
    try:
        if not is_gmail_linked():
            return {"status": "not_linked",
                    "message": "Gmail isn't linked yet, sir. Link it in Settings and I'll read your inbox directly.",
                    "messages": [], "total": 0}
        try:
            count = max(1, min(int(count or 1), 10))
        except (TypeError, ValueError):
            count = 1
        sender = (sender or "").strip()
        ranged = False
        try:
            ranged = int(days or 0) > 0 or int(older_than_days or 0) > 0
        except (TypeError, ValueError):
            pass
        if ranged:
            query = _inbox_query(unread=unread_only, days=days,
                                 older_than_days=older_than_days)
            # Sender filtering happens locally after fetch, so pull a wide
            # window only when filtering; otherwise fetch just what we speak
            # (each message costs an extra detail GET — 50 was stalling replies).
            messages = _fetch_messages(query, 50 if sender else count)
            total = count_messages(query)
        elif unread_only:
            messages = fetch_unread(limit=50 if sender else count)
            total = len(messages)
        else:
            messages = fetch_latest(limit=50 if sender else count)
            total = -1
        if not messages:
            if last_api_error():
                return {"status": "error", "message": _api_error_message(),
                        "messages": [], "total": 0}
            if unread_only and not ranged:
                # Fall back to latest read mail rather than a dead end.
                latest = fetch_latest(limit=1)
                if latest:
                    m = latest[0]
                    return {"status": "ok",
                            "message": (f"No unread mail, sir — your latest is from "
                                        f"{m.get('from_name')}: {m.get('subject')}."),
                            "messages": [m], "total": 0}
            if sender:
                return {"status": "empty",
                        "message": f"No mail from {sender} in your inbox, sir.",
                        "messages": [], "total": 0}
            if ranged:
                try:
                    span = f"last {int(days)} days" if int(days or 0) > 0 else "that window"
                except (TypeError, ValueError):
                    span = "that window"
                return {"status": "empty",
                        "message": f"No mail in the {span}, sir.",
                        "messages": [], "total": 0}
            return {"status": "empty",
                    "message": "No mail at all, sir. Inbox is clear.",
                    "messages": [], "total": 0}
        if sender:
            needle = sender.casefold()
            messages = [m for m in messages
                        if needle in str(m.get("from_name") or "").casefold()
                        or needle in str(m.get("from_email") or "").casefold()]
            if not messages:
                return {"status": "empty",
                        "message": f"No mail from {sender} in your inbox, sir.",
                        "messages": [], "total": 0}
            messages = messages[:count]
        else:
            messages = messages[:count]
        if len(messages) == 1:
            m = messages[0]
            snippet = str(m.get("snippet") or "")[:160]
            body = fetch_message_body(str(m.get("id") or ""))
            if body:
                m["body"] = body
            lead = "Latest mail, sir" if not ranged else "One mail in that window, sir"
            spoken = (f"{lead} — from {m.get('from_name')} "
                      f"({_short_date(m.get('date', ''))}): "
                      f"{m.get('subject')}.")
            if body:
                # Snippet usually repeats the body's opening — don't read it twice.
                if not snippet or snippet[:40] in body[:80]:
                    spoken += f" It reads: {body[:500]}"
                else:
                    spoken += f" {snippet} It reads: {body[:500]}"
            elif snippet:
                spoken += f" {snippet}"
            return {"status": "ok", "message": spoken, "messages": messages,
                    "total": total if isinstance(total, int) and total >= 0 else len(messages)}
        if sender:
            head = f"Mail from {sender}, sir"
        elif ranged:
            try:
                span = f"the last {int(days)} days" if int(days or 0) > 0 else "that window"
            except (TypeError, ValueError):
                span = "that window"
            head = f"You received {total} mail in {span}, sir" if total == 1 else \
                f"You received {total} mails in {span}, sir" if total >= 0 else \
                f"Your mail from {span}, sir"
        else:
            head = "Your latest mail, sir"
        lines = [f"{i + 1}. {m.get('from_name')}: {m.get('subject')}"
                 for i, m in enumerate(messages)]
        return {"status": "ok",
                "message": head + " — " + " ".join(lines) + ".",
                "messages": messages,
                "total": total if isinstance(total, int) and total >= 0 else len(messages)}
    except Exception as exc:
        return {"status": "error", "message": f"Couldn't read mail, sir: {str(exc)[:160]}",
                "messages": [], "total": 0}


def _decode_part_body(data: str) -> str:
    try:
        import base64
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pick_text_part(payload: Dict[str, Any]) -> str:
    """Prefer text/plain; fall back to stripped text/html. Recursive."""
    try:
        mime = str(payload.get("mimeType") or "")
        data = (payload.get("body") or {}).get("data")
        if data:
            if mime.startswith("text/plain"):
                return _decode_part_body(str(data))
            if mime.startswith("text/html"):
                return _strip_html(_decode_part_body(str(data)))
        html_fallback = ""
        for part in payload.get("parts") or []:
            pmime = str(part.get("mimeType") or "")
            found = _pick_text_part(part)
            if not found:
                continue
            if pmime.startswith("text/plain"):
                return found
            if not html_fallback and (pmime.startswith("text/html") or pmime.startswith("multipart/")):
                html_fallback = found
        return html_fallback
    except Exception:
        pass
    return ""


def fetch_message_body(mid: str, max_chars: int = 2000) -> str:
    """Readable body excerpt for one message. Empty string on failure."""
    try:
        full = _api_get(f"/messages/{mid}", {"format": "full"})
        if not full:
            return ""
        text = _pick_text_part(full.get("payload") or {})
        if not text:
            text = str(full.get("snippet") or "")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        return text
    except Exception:
        return ""


# ── VIP list management ─────────────────────────────────────────────────────
def add_vip(sender: str) -> Dict[str, Any]:
    """Treat mail from this sender/address as important from now on."""
    sender = (sender or "").strip().strip("\"'")
    if not sender:
        return {"status": "error",
                "message": "Whose mail should count as important, sir?"}
    with _LOCK:
        watch = load_watch()
        vips = [str(v or "") for v in (watch.get("vip_senders") or [])]
        if sender.casefold() in (v.casefold() for v in vips):
            return {"status": "success",
                    "message": f"{sender} is already on your VIP list, sir."}
        vips.append(sender)
        watch["vip_senders"] = vips
        _write_json(WATCH_PATH, watch)
    return {"status": "success",
            "message": f"Done, sir — mail from {sender} will now be announced as important."}


def remove_vip(sender: str) -> Dict[str, Any]:
    """Stop treating this sender as important."""
    sender = (sender or "").strip().strip("\"'")
    with _LOCK:
        watch = load_watch()
        vips = [str(v or "") for v in (watch.get("vip_senders") or [])]
        kept = [v for v in vips if v.casefold() != sender.casefold()]
        if len(kept) == len(vips):
            return {"status": "error",
                    "message": f"{sender or 'They'} were never on your VIP list, sir."}
        watch["vip_senders"] = kept
        _write_json(WATCH_PATH, watch)
    return {"status": "success",
            "message": f"Removed, sir — {sender} is off your VIP list."}


# ── sending ───────────────────────────────────────────────────────────────────
def send_email(to: str, subject: str = "", body: str = "") -> Dict[str, Any]:
    """Send a plain-text mail via the Gmail API. Never raises.

    Needs the gmail.send scope: tokens linked before send existed get a 403,
    answered with a re-link instruction instead of a cryptic error."""
    to = (to or "").strip().strip("\"'<>'")
    # "mail tshaikh2478@gmail.com" / "John <john@x.com>" -> address only.
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", to)
    if not m:
        return {"status": "error",
                "message": "I need a valid email address to send to, sir — who should receive it?"}
    to_addr = m.group(0)
    body = (body or "").strip()
    if not body:
        return {"status": "error",
                "message": "There's nothing to send, sir — what should the mail say?"}
    if not is_gmail_linked():
        return {"status": "not_linked",
                "message": "Gmail isn't linked, sir. Link it in Settings and I'll send that."}
    try:
        from email.mime.text import MIMEText
        import base64
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to_addr
        msg["Subject"] = (subject or "").strip()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = _api_post("/messages/send", {"raw": raw})
        if not sent:
            if last_api_error() == "http_403":
                return {"status": "needs_relink",
                        "message": ("Gmail refused sending, sir — my permission predates "
                                    "the send feature. Please re-link Gmail in Settings "
                                    "(it now asks for read + send), then I'll send it.")}
            return {"status": "error", "message": _api_error_message()}
        subj = (subject or "").strip() or "(no subject)"
        return {"status": "success",
                "message": f"Mail sent to {to_addr}, sir — subject '{subj[:80]}'.",
                "id": sent.get("id", "")}
    except Exception as exc:
        return {"status": "error",
                "message": f"Couldn't send that mail, sir: {str(exc)[:160]}"}


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
    """Single cycle: fetch unread, announce unseen+important by voice, toast
    every other unseen arrival (notify_all), remember all IDs.

    Never raises. Statuses: ok / not_linked / error. `announced` = spoken,
    `notified` = toast-only (Notification Center + HUD toast, no voice).
    """
    try:
        if not is_gmail_linked():
            return {"status": "not_linked",
                    "message": "Gmail is not linked. Link it in Settings, sir.",
                    "announced": [], "notified": [], "checked": 0}
        watch = load_watch()
        notify_all = bool(watch.get("notify_all", True))
        speak_all = bool(watch.get("speak_all", False))
        seen = set(load_seen()["seen_ids"])
        messages = fetch_unread(limit=int(watch.get("max_results") or 20))
        if not messages and last_api_error():
            return {"status": "error", "message": _api_error_message(),
                    "announced": [], "notified": [], "checked": 0}
        announced: List[Dict[str, Any]] = []
        notified: List[Dict[str, Any]] = []
        for message in messages:
            mid = message.get("id", "")
            if not mid or mid in seen:
                continue
            verdict = is_important(message, watch)
            message["important"] = verdict["important"]
            message["reason"] = verdict["reason"]
            if verdict["important"] or speak_all:
                message["speak"] = announcement_text(message, verdict["reason"])
                announced.append(message)
            elif notify_all:
                sender = str(message.get("from_name") or "Unknown sender").strip()
                subject = str(message.get("subject") or "(no subject)").strip()
                if len(subject) > 140:
                    subject = subject[:140].rstrip() + "…"
                message["speak"] = ""
                message["toast"] = f"Sir, new mail from {sender}: {subject}."
                notified.append(message)
        _remember_seen([m.get("id", "") for m in messages if m.get("id")])
        return {"status": "ok", "announced": announced, "notified": notified,
                "checked": len(messages), "important": len(announced)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200],
                "announced": [], "notified": [], "checked": 0}
