"""scheduler.py — normal-mode reminders + scheduled WhatsApp for J.A.R.V.I.S.

Normal (non-agentic) chat mode understands:

  Reminders (they actually FIRE — voice + toast when due):
    "remind me in 10 minutes to call mom"
    "remind me at 6pm to take a break"
    "remind me tomorrow at 9am to send the report"
    "list reminders" / "cancel reminder <text>"

  Scheduled WhatsApp (sent later via the existing desktop sender):
    "send whatsapp to Mom at 6pm saying happy birthday"
    "schedule whatsapp to +919876543210 in 2 hours saying on my way"
    "list scheduled messages" / "cancel scheduled whatsapp to Mom"

Design:
- Reminders reuse the Phase 1 ReminderStore (backend/data/reminders.json);
  the missing piece — a ticker that fires them — lives here.
- Scheduled WhatsApp has its own small store
  (backend/data/scheduled_whatsapp.json); file-backed so jobs survive
  backend/PC restarts.
- One daemon ticker thread (30s) checks both queues. Every public function
  returns a dict and never raises.
- Time expressions are parsed with stdlib only (no new dependencies) and
  stored as timezone-aware ISO strings so firing is exact.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
WHATSAPP_JOBS_PATH = os.path.join(DATA_DIR, "scheduled_whatsapp.json")

_LOCK = threading.RLock()
_WORKER_STARTED = False
_TICK_SECONDS = 30

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_RELATIVE_RE = re.compile(
    r"\bin\s+(?:(\d+)\s*)?(half\s+an\s+|an?\s+)?(second|minute|hour|day)s?\b", re.I)
_AT_TIME_RE = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_TODAY_TOMORROW_RE = re.compile(r"\b(today|tomorrow|tonight)\b", re.I)
_WEEKDAY_RE = re.compile(r"\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)


def _now() -> datetime:
    return datetime.now().astimezone()


# ── JSON helpers ──────────────────────────────────────────────────────────────
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


# ── time parsing ──────────────────────────────────────────────────────────────
def parse_when(text: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Parse a due time out of free text. Returns {"ok", "when"|"message"}.

    Understands: "in 10 minutes", "in an hour", "in half an hour",
    "at 6pm", "at 18:30", "tomorrow at 9am", "tonight at 9", "today at 5pm",
    "on friday at 5pm" (weekday without time → 9:00 AM). Past times roll to
    tomorrow; anything over a year out is refused."""
    now = now or _now()
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "message": "no time given"}

    rel = _RELATIVE_RE.search(raw)
    if rel:
        amount = int(rel.group(1)) if rel.group(1) else 1
        if rel.group(2) and "half" in rel.group(2).lower():
            amount = 30
            unit = "minute"
        else:
            unit = (rel.group(3) or "minute").lower()
        delta = {"second": timedelta(seconds=amount),
                 "minute": timedelta(minutes=amount),
                 "hour": timedelta(hours=amount),
                 "day": timedelta(days=amount)}.get(unit, timedelta(minutes=amount))
        when = now + delta
        span = rel.span()
        return {"ok": True, "when": when, "span": span}

    day_match = _TODAY_TOMORROW_RE.search(raw)
    weekday_match = _WEEKDAY_RE.search(raw)
    at_match = None
    for match in _AT_TIME_RE.finditer(raw):
        hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").lower()
        if hour > 24 or minute > 59:
            continue
        # Bare numbers ("call mom at work") are not times unless they look
        # like one: needs minutes, meridiem, or an explicit "at".
        has_at = raw[max(0, match.start() - 3):match.start()].lower().rstrip().endswith("at")
        if not (has_at or match.group(2) or meridiem):
            continue
        at_match = match
        break

    if weekday_match and not day_match:
        target = _WEEKDAYS[weekday_match.group(1).lower()]
        if at_match:
            hour = int(at_match.group(1)) % 24
            minute = int(at_match.group(2) or 0)
            meridiem = (at_match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
        else:
            hour, minute = 9, 0
        days_ahead = (target - now.weekday()) % 7
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        start = weekday_match.start()
        end = at_match.end() if at_match else weekday_match.end()
        return {"ok": True, "when": candidate, "span": (start, end)}

    if at_match:
        hour = int(at_match.group(1)) % 24
        minute = int(at_match.group(2) or 0)
        meridiem = (at_match.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if hour == 24:
            hour = 0
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        day_word = day_match.group(1).lower() if day_match else ""
        if day_word in ("tomorrow", "tonight") and candidate <= now + timedelta(minutes=1):
            candidate += timedelta(days=1)
        elif not day_word and candidate <= now:
            candidate += timedelta(days=1)  # "at 6pm" after 6pm → tomorrow
        if candidate - now > timedelta(days=366):
            return {"ok": False, "message": "that is more than a year away"}
        start = day_match.start() if day_match else at_match.start()
        end = at_match.end()
        # swallow a trailing "at <time>" correctly when day word came first
        if day_match and day_match.end() <= at_match.start():
            end = at_match.end()
        return {"ok": True, "when": candidate, "span": (start, end)}

    return {"ok": False, "message": "no time found"}


def _strip_span(text: str, span) -> str:
    if not span:
        return text
    start, end = span
    return (text[:start] + " " + text[end:]).strip()


def describe_when(when: datetime) -> str:
    """Human-friendly: 'today at 6:00 PM', 'tomorrow at 9:30 AM', 'Friday at 5:00 PM'."""
    now = _now()
    try:
        local = when.astimezone(now.tzinfo)
    except Exception:
        local = when
    time_part = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == now.date():
        return f"today at {time_part}"
    if local.date() == (now + timedelta(days=1)).date():
        return f"tomorrow at {time_part}"
    return f"{local.strftime('%A')} at {time_part}"


# ── reminder commands (normal mode) ───────────────────────────────────────────
_REMIND_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:set\s+(?:a\s+|an\s+)?|add\s+(?:a\s+|an\s+)?|create\s+(?:a\s+|an\s+)?)?"
    r"remind\s+me\b\s*", re.I)
_CONNECTOR_RE = re.compile(r"^(?:to|about|that|of)\b\s*", re.I)


def parse_reminder(text: str) -> Optional[Dict[str, Any]]:
    """Parse 'remind me ...' — returns {text, when} or None (not a reminder)."""
    raw = (text or "").strip()
    if not re.search(r"\bremind\s+me\b|\bset\s+(?:a\s+)?reminder\b|\badd\s+(?:a\s+)?reminder\b", raw, re.I):
        return None
    body = _REMIND_LEAD.sub("", raw).strip()
    body = re.sub(r"^(?:a\s+reminder\s+(?:to|about|that|for)\s+|reminder\s*:\s*)", "", body, flags=re.I).strip()
    if not body:
        return {"error": "Please tell me what to remind you about, sir. For example: remind me in 10 minutes to call mom."}
    parsed = parse_when(body)
    if not parsed.get("ok"):
        return {"error": "When should I remind you, sir? For example: remind me in 10 minutes to stretch."}
    reminder_text = _CONNECTOR_RE.sub("", _strip_span(body, parsed.get("span"))).strip(" .,-:")
    reminder_text = _CONNECTOR_RE.sub("", reminder_text).strip()
    if not reminder_text:
        return {"error": "Please tell me what to remind you about, sir."}
    return {"text": reminder_text, "when": parsed["when"]}


def add_reminder(text: str, when: datetime) -> Dict[str, Any]:
    try:
        from backend.agent.phase1_runtime import runtime
        return runtime.reminders.add(text, due_at=when.isoformat())
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160]}


def list_reminders() -> List[Dict[str, Any]]:
    try:
        from backend.agent.phase1_runtime import runtime
        return runtime.reminders.list()
    except Exception:
        return []


def cancel_reminder(fragment: str) -> Dict[str, Any]:
    fragment = (fragment or "").strip().casefold()
    if not fragment:
        return {"status": "error", "message": "Which reminder should I cancel, sir?"}
    try:
        from backend.agent.phase1_runtime import runtime
        matches = [r for r in runtime.reminders.list()
                   if fragment in str(r.get("text") or "").casefold()
                   or fragment == str(r.get("id") or "").casefold()]
        if not matches:
            return {"status": "error",
                    "message": "I found no reminder matching that, sir."}
        if len(matches) > 1:
            options = "; ".join(f"'{m.get('text', '')[:60]}'" for m in matches[:5])
            return {"status": "error",
                    "message": f"Multiple reminders match, sir: {options}. Please be more specific."}
        runtime.reminders.remove(matches[0]["id"])
        return {"status": "success", "message": f"Cancelled, sir: '{matches[0].get('text', '')[:120]}'.",
                "reminder": matches[0]}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160]}


def fire_due_reminders(on_fire: Callable[[Dict[str, Any]], None]) -> int:
    """Speak+toast every due reminder exactly once. Returns fired count."""
    fired = 0
    try:
        from backend.agent.phase1_runtime import runtime
        for reminder in runtime.reminders.due():
            try:
                on_fire({"kind": "reminder", "text": str(reminder.get("text") or ""),
                         "reminder": reminder})
                runtime.reminders.complete(reminder.get("id", ""))
                fired += 1
            except Exception:
                continue
    except Exception:
        pass
    return fired


# ── scheduled WhatsApp store ──────────────────────────────────────────────────
def _load_jobs() -> List[Dict[str, Any]]:
    with _LOCK:
        raw = _read_json(WHATSAPP_JOBS_PATH, [])
        return raw if isinstance(raw, list) else []


def _save_jobs(jobs: List[Dict[str, Any]]) -> None:
    with _LOCK:
        _write_json(WHATSAPP_JOBS_PATH, jobs)


def schedule_whatsapp(contact: str, message: str, when: datetime) -> Dict[str, Any]:
    if (when - _now()) > timedelta(days=366):
        return {"status": "error", "message": "That is more than a year away, sir."}
    job = {"id": str(uuid.uuid4()), "contact": contact.strip(),
           "message": message.strip(), "send_at": when.isoformat(),
           "status": "pending", "created_at": _now().isoformat(),
           "result": ""}
    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)
    return {"status": "success", "job": job}


def list_scheduled(include_done: bool = False) -> List[Dict[str, Any]]:
    jobs = [j for j in _load_jobs() if isinstance(j, dict)]
    return jobs if include_done else [j for j in jobs if j.get("status") == "pending"]


def cancel_scheduled(fragment: str) -> Dict[str, Any]:
    fragment = (fragment or "").strip().casefold()
    jobs = _load_jobs()
    if not fragment:
        pending = [j for j in jobs if j.get("status") == "pending"]
        if not pending:
            return {"status": "error", "message": "No scheduled messages to cancel, sir."}
        if len(pending) == 1:
            pending[0]["status"] = "cancelled"
            _save_jobs(jobs)
            return {"status": "success",
                    "message": f"Cancelled the scheduled WhatsApp to {pending[0].get('contact')}, sir."}
        options = "; ".join(f"to {j.get('contact')}" for j in pending[:5])
        return {"status": "error",
                "message": f"Multiple scheduled messages, sir: {options}. Say which one to cancel."}
    matches = [j for j in jobs if j.get("status") == "pending" and
               (fragment in str(j.get("contact") or "").casefold()
                or fragment in str(j.get("message") or "").casefold()
                or fragment == str(j.get("id") or "").casefold())]
    if not matches:
        return {"status": "error", "message": "No scheduled message matches that, sir."}
    if len(matches) > 1:
        options = "; ".join(f"to {j.get('contact')}" for j in matches[:5])
        return {"status": "error",
                "message": f"Multiple match, sir: {options}. Please be more specific."}
    matches[0]["status"] = "cancelled"
    _save_jobs(jobs)
    return {"status": "success",
            "message": f"Cancelled the scheduled WhatsApp to {matches[0].get('contact')}, sir.",
            "job": matches[0]}


def _mark_job(job_id: str, status: str, result: str = "") -> None:
    jobs = _load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job["status"] = status
            job["result"] = result[:300]
            break
    _save_jobs(jobs)


def fire_due_whatsapp(send_fn: Callable[[str, str], Dict[str, Any]],
                      on_result: Callable[[Dict[str, Any], Dict[str, Any]], None]) -> int:
    """Send every due job via send_fn(contact, message). Returns fired count."""
    fired = 0
    try:
        now = _now()
        for job in list_scheduled():
            try:
                due_at = datetime.fromisoformat(str(job.get("send_at", "")))
                if due_at.tzinfo is None:
                    continue  # never fire timeless jobs
                if due_at > now:
                    continue
                result = send_fn(str(job.get("contact") or ""), str(job.get("message") or ""))
                ok = result.get("status") == "success"
                _mark_job(job.get("id", ""), "sent" if ok else "failed",
                          str(result.get("message") or ""))
                on_result(job, result)
                fired += 1
            except Exception:
                continue
    except Exception:
        pass
    return fired


# ── WhatsApp schedule parsing (normal mode) ───────────────────────────────────
_SCHEDULE_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:schedule\s+(?:a\s+)?|send\s+(?:a\s+)?)?"
    r"whatsapp\s+(?:message\s+)?to\s+", re.I)
_SAY_SPLIT = re.compile(r"\b(?:saying|that\s+says|with\s+(?:the\s+)?message|message\s*:|:)\s*", re.I)


def parse_scheduled_whatsapp(text: str) -> Optional[Dict[str, Any]]:
    """Parse 'send/schedule whatsapp to X at <time> saying Y'.

    Returns None when this is NOT a scheduling request (e.g. an immediate
    send with no time expression → falls through to the normal sender)."""
    raw = (text or "").strip()
    if not re.search(r"\bwhatsapp\b", raw, re.I):
        return None
    if not re.search(r"\b(schedule|at\s+|in\s+\d|in\s+an?\s+|tomorrow|today|tonight|on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", raw, re.I):
        return None  # no time expression → immediate send, not our business
    body = _SCHEDULE_LEAD.sub("", raw).strip()
    if not body or body == raw.strip():
        # "whatsapp Mom at 6pm saying hi" without send/schedule verb
        body = re.sub(r"^\s*(?:please\s+)?whatsapp\s+(?:message\s+)?to\s+", "", raw, flags=re.I).strip()
        if not body or body == raw.strip():
            return None
    at_split = re.split(r"\s+at\s+", body, maxsplit=1, flags=re.I)
    if len(at_split) == 2:
        contact, rest = at_split[0].strip(), at_split[1].strip()
    else:
        in_split = re.split(r"\s+(in\s+(?:\d|an?\b|half))", body, maxsplit=1, flags=re.I)
        if len(in_split) >= 3:
            contact, rest = in_split[0].strip(), (in_split[1] + in_split[2]).strip()
        else:
            return {"error": "I need a time, sir. For example: send whatsapp to Mom at 6pm saying happy birthday."}
    if not contact:
        return {"error": "Who should I send the WhatsApp to, sir?"}
    say_parts = _SAY_SPLIT.split(rest, maxsplit=1)
    if len(say_parts) == 2:
        time_part, message = say_parts[0].strip(), say_parts[1].strip()
    else:
        # "...at 6pm happy birthday" — parse time from the front, rest is message
        time_part, message = rest, ""
        parsed_probe = parse_when(rest)
        if parsed_probe.get("ok") and parsed_probe.get("span"):
            message = _strip_span(rest, parsed_probe.get("span")).strip(" .,-:")
    if not message:
        return {"error": "What should the message say, sir? Add 'saying …' after the time."}
    parsed = parse_when(time_part if len(say_parts) == 2 else rest)
    if not parsed.get("ok"):
        return {"error": "I could not understand the time, sir. Try 'at 6pm' or 'in 2 hours'."}
    if parsed["when"] <= _now():
        return {"error": "That time has already passed, sir. Please pick a future time."}
    return {"contact": contact, "message": message, "when": parsed["when"]}


# ── normal-mode command router ────────────────────────────────────────────────
def _response(speak: str, log: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = {"speak": speak, "logs": [log], "file_data": None,
                "refresh_files": False, "image_data": None}
    if extra:
        response.update(extra)
    return response


def handle_schedule_command(text: str) -> Optional[Dict[str, Any]]:
    """Direct normal-mode handler. Returns a /api/command-shaped response or
    None when the text is not a reminder/scheduling command."""
    raw = (text or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()

    # -- list / cancel reminders --
    if re.match(r"^\s*(?:please\s+)?(?:list|show)\s+(?:all\s+)?(?:my\s+)?reminders?\s*$", raw, re.I) or \
            re.match(r"^\s*what\s+are\s+my\s+reminders?\s*\??\s*$", raw, re.I):
        items = list_reminders()
        if not items:
            return _response("No active reminders, sir.", "REMINDERS: none active")
        lines = []
        for item in items[:10]:
            try:
                when = datetime.fromisoformat(str(item.get("due_at", "")))
                when_s = describe_when(when)
            except (ValueError, TypeError):
                when_s = "unscheduled"
            lines.append(f"'{item.get('text', '')[:80]}' — {when_s}")
        return _response(f"{len(items)} reminder(s), sir: " + "; ".join(lines) + ".",
                         f"REMINDERS listed: {len(items)}", {"reminders": items})
    cancel_rem = re.match(r"^\s*(?:please\s+)?(?:cancel|delete|remove)\s+(?:the\s+|my\s+)?reminder\s*(.*)$", raw, re.I)
    if cancel_rem:
        result = cancel_reminder(cancel_rem.group(1))
        ok = result.get("status") == "success"
        return _response(result.get("message", ""), f"REMINDER cancel: {result.get('status')}", result)

    # -- list / cancel scheduled whatsapp --
    if re.match(r"^\s*(?:please\s+)?(?:list|show)\s+(?:all\s+)?(?:my\s+)?scheduled(\s+whatsapp)?(\s+messages?)?\s*$", raw, re.I):
        jobs = list_scheduled()
        if not jobs:
            return _response("No scheduled WhatsApp messages, sir.", "SCHEDULED WA: none")
        lines = []
        for job in jobs[:10]:
            try:
                when_s = describe_when(datetime.fromisoformat(str(job.get("send_at", ""))))
            except (ValueError, TypeError):
                when_s = "unscheduled"
            lines.append(f"to {job.get('contact')} {when_s}: '{job.get('message', '')[:60]}'")
        return _response(f"{len(jobs)} scheduled, sir: " + "; ".join(lines) + ".",
                         f"SCHEDULED WA listed: {len(jobs)}", {"jobs": jobs})
    cancel_wa = re.match(r"^\s*(?:please\s+)?(?:cancel|delete|remove)\s+(?:the\s+)?scheduled(\s+whatsapp)?(\s+message)?\s*(.*)$", raw, re.I)
    if cancel_wa and ("schedul" in lowered or "whatsapp" in lowered):
        fragment = re.sub(r"^(?:to|for)\s+", "", (cancel_wa.group(3) or "").strip(), flags=re.I)
        result = cancel_scheduled(fragment)
        return _response(result.get("message", ""), f"SCHEDULED WA cancel: {result.get('status')}", result)

    # -- new reminder --
    if re.search(r"\bremind\s+me\b|\bset\s+(?:a\s+)?reminder\b|\badd\s+(?:a\s+)?reminder\b", lowered):
        parsed = parse_reminder(raw)
        if parsed is None:
            return None
        if "error" in parsed:
            return _response(parsed["error"], f"REMINDER parse failed: {parsed['error']}")
        saved = add_reminder(parsed["text"], parsed["when"])
        if saved.get("status") != "success":
            return _response("I could not save that reminder, sir.",
                             f"REMINDER ERROR: {saved.get('message')}")
        when_s = describe_when(parsed["when"])
        return _response(f"Reminder set for {when_s}, sir: {parsed['text'][:160]}.",
                         f"REMINDER SET: '{parsed['text'][:80]}' for {when_s}",
                         {"reminder": saved.get("reminder")})

    # -- new scheduled whatsapp --
    if "whatsapp" in lowered and re.search(r"\b(schedule|at\b|in\s+\d|tomorrow|today|tonight)\b", lowered):
        parsed = parse_scheduled_whatsapp(raw)
        if parsed is None:
            return None  # immediate send → normal sender path
        if "error" in parsed:
            return _response(parsed["error"], f"SCHEDULED WA parse failed: {parsed['error']}")
        saved = schedule_whatsapp(parsed["contact"], parsed["message"], parsed["when"])
        if saved.get("status") != "success":
            return _response(saved.get("message", "Could not schedule, sir."),
                             f"SCHEDULED WA ERROR: {saved.get('message')}")
        when_s = describe_when(parsed["when"])
        return _response(f"Scheduled, sir. WhatsApp to {parsed['contact']} {when_s}: {parsed['message'][:160]}.",
                         f"SCHEDULED WA: to {parsed['contact']} for {when_s}",
                         {"job": saved.get("job")})

    return None


# ── background ticker ─────────────────────────────────────────────────────────
def ensure_scheduler_worker(on_reminder: Callable[[Dict[str, Any]], None],
                            on_whatsapp: Callable[[Dict[str, Any], Dict[str, Any]], None],
                            send_fn: Callable[[str, str], Dict[str, Any]]) -> None:
    """Start the 30s daemon ticker once. Never raises."""
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def _tick() -> None:
        while True:
            try:
                time.sleep(_TICK_SECONDS)
                try:
                    fire_due_reminders(on_reminder)
                except Exception:
                    pass
                try:
                    fire_due_whatsapp(send_fn, on_whatsapp)
                except Exception:
                    pass
            except Exception:
                time.sleep(_TICK_SECONDS)

    threading.Thread(target=_tick, name="jarvis-scheduler", daemon=True).start()
