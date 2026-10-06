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


def describe_when_auto(text: str, when: datetime) -> str:
    """describe_when, but in Hindi/Marathi when the user's text is."""
    try:
        from backend.agent import marathi as _mmod
        if _mmod.is_marathi(text):
            mr = _mmod.describe_when_marathi(when)
            if mr:
                return mr
    except Exception:
        pass
    try:
        from backend.agent import hindi as _hmod
        if _hmod.is_hindi(text):
            hi = _hmod.describe_when_hindi(when)
            if hi:
                return hi
    except Exception:
        pass
    return describe_when(when)


# ── Hindi time expressions ("10 minute me", "kal subah 9 baje") ──────────────
_HI_NUM = {"ek": 1, "do": 2, "teen": 3, "chaar": 4, "char": 4, "paanch": 5,
           "panch": 5, "che": 6, "chhah": 6, "saat": 7, "aath": 8, "aath": 8,
           "nau": 9, "nau": 9, "das": 10, "gyarah": 11, "barah": 12}
_HI_REL_RE = re.compile(
    r"\b(\d+|[a-zA-Z]+)\s*(seconds?|mints?|minutes?|ghante?|ghanta|hours?)\s*"
    r"(me|mein|baad|ke\s*baad)\b", re.I)
_HI_HALF_RE = re.compile(r"\baadh[ae]\s+ghante?\s*(me|mein|baad|ke\s*baad)\b", re.I)
_HI_CLOCK_RE = re.compile(
    r"(?:\b(aaj|kal|parson)\b)?\s*(?:\b(subah|savere|dopahar|shaam|raat|raatri)\b)?\s*"
    r"(?:\bke\b\s*)?(\d{1,2})(?::(\d{2}))?\s*(baje|bajje)\b", re.I)


def _hi_amount(token: str) -> Optional[int]:
    token = (token or "").strip().lower()
    if token.isdigit():
        return int(token)
    return _HI_NUM.get(token)


def parse_when_hindi(text: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Parse Hindi due times. Returns {"ok", "when", "span"} like parse_when."""
    now = now or _now()
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "message": "no time given"}

    half = _HI_HALF_RE.search(raw)
    if half:
        return {"ok": True, "when": now + timedelta(minutes=30), "span": half.span()}

    rel = _HI_REL_RE.search(raw)
    if rel:
        amount = _hi_amount(rel.group(1))
        unit = (rel.group(2) or "").lower()
        if amount is not None and amount > 0:
            if unit.startswith("ghant") or unit.startswith("hour"):
                delta = timedelta(hours=amount)
            elif unit.startswith("sec"):
                delta = timedelta(seconds=amount)
            else:
                delta = timedelta(minutes=amount)
            return {"ok": True, "when": now + delta, "span": rel.span()}

    clock = _HI_CLOCK_RE.search(raw)
    if clock:
        day_word = (clock.group(1) or "").lower()
        part = (clock.group(2) or "").lower()
        hour = int(clock.group(3))
        minute = int(clock.group(4) or 0)
        if hour > 24 or minute > 59:
            return {"ok": False, "message": "bad time"}
        if part in ("shaam", "raat", "raatri", "dopahar") and hour < 12:
            hour += 12
        if hour == 24:
            hour = 0
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_word == "parson":
            candidate = (now + timedelta(days=2)).replace(
                hour=hour, minute=minute, second=0, microsecond=0)
        elif day_word == "kal":
            if candidate <= now + timedelta(minutes=1):
                candidate += timedelta(days=1)
            elif candidate.date() <= now.date():
                candidate += timedelta(days=1)
        elif candidate <= now:
            candidate += timedelta(days=1)
        if candidate - now > timedelta(days=366):
            return {"ok": False, "message": "that is more than a year away"}
        return {"ok": True, "when": candidate, "span": clock.span()}

    return {"ok": False, "message": "no time found"}


def _looks_hindi_time(text: str) -> bool:
    t = (text or "").casefold()
    if re.search(r"[\u0900-\u097F]", text or ""):
        return True
    return bool(re.search(
        r"\b(baje|bajje|yaad dila|yaad dilao|aadhe|subah|savere|dopahar|shaam|raat|aaj|kal|parson|roz|ghante|ghanta|minute me|minute baad)\b", t))


# ── reminder commands (normal mode) ───────────────────────────────────────────
_REMIND_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:set\s+(?:a\s+|an\s+)?|add\s+(?:a\s+|an\s+)?|create\s+(?:a\s+|an\s+)?)?"
    r"remind\s+me\b\s*", re.I)
_CONNECTOR_RE = re.compile(r"^(?:to|about|that|of)\b\s*", re.I)


_REPEAT_RES_EN = (
    (re.compile(r"\bevery\s+weekday\b|\bweekdays\b|\bevery\s+morning\b", re.I), "weekdays", "every weekday"),
    (re.compile(r"\bevery\s+day\b|\bdaily\b|\beach\s+day\b", re.I), "daily", "every day"),
    (re.compile(r"\bevery\s+week\b|\bweekly\b", re.I), "weekly", "every week"),
)
# Hindi repeats ("roz", "har din") only apply to Hindi text — bare "roz"
# would otherwise eat the English name "Roz" out of reminder text.
_REPEAT_RES_HI = (
    (re.compile(r"\broz\b|\bhar\s+din\b|\brozana\b|रोज़|रोज|हर दिन", re.I), "daily", "रोज़"),
    (re.compile(r"\bhar\s+hafte\b|हर हफ्ते", re.I), "weekly", "हर हफ्ते"),
)


def _detect_repeat(body: str) -> tuple:
    """Return (repeat_code, repeat_label, body_without_repeat)."""
    for rx, code, label in _REPEAT_RES_EN:
        if rx.search(body):
            return code, label, rx.sub(" ", body).strip()
    if _marathi_score(body) >= 2:
        for rx, code, label in (
                (re.compile(r"\bdarroj\b|दररोज", re.I), "daily", "रोज"),
                (re.compile(r"\bdar\s+aathvad[a-z]*|दर\s+आठवड्याला", re.I), "weekly", "दर आठवड्याला")):
            if rx.search(body):
                return code, label, rx.sub(" ", body).strip()
    if _hindi_score(body) >= 2:
        for rx, code, label in _REPEAT_RES_HI:
            if rx.search(body):
                return code, label, rx.sub(" ", body).strip()
    return "", "", body


_HI_SCORE_RES = (
    re.compile(r"[\u0900-\u097F]"),
    re.compile(r"\b(baje|bajje|subah|savere|dopahar|shaam|raat|aaj|kal|parson|roz|rozana|ghante|ghanta|yaad|aadhe|har\s+din|har\s+hafte|minute\s+me|minute\s+baad|chutkula|sunao)\b", re.I),
)


def _hindi_score(text: str) -> int:
    """Hindi confidence for scheduler paths: Devanagari (without a Marathi
    marker win) = certain (99), otherwise the count of distinct Hinglish
    time markers. Scheduling decisions need >= 2 so English names ("Roz",
    "Kal") never misfire."""
    try:
        t = text or ""
        if _HI_SCORE_RES[0].search(t):
            try:
                from backend.agent.lang_detect import prefer_marathi
                if prefer_marathi(t):
                    return 0
            except Exception:
                pass
            return 99
        found = set()
        for m in _HI_SCORE_RES[1].finditer(t):
            found.add(m.group(1).casefold() if m.lastindex else m.group(0).casefold())
        return len(found)
    except Exception:
        return 0


_MR_SCORE_RES = (
    re.compile(r"\b(vajta|vajle|sakali|dupari|sandhyakali|ratri|udya|parva|aathvan|darroj|minit\w*|tas\w*|aaj\s+sakali)\b", re.I),
)


def _marathi_score(text: str) -> int:
    """Marathi confidence, same contract as _hindi_score."""
    try:
        t = text or ""
        if _HI_SCORE_RES[0].search(t):
            try:
                from backend.agent.lang_detect import prefer_marathi
                return 99 if prefer_marathi(t) else 0
            except Exception:
                return 0
        found = {m.group(0).casefold() for m in _MR_SCORE_RES[0].finditer(t)}
        return len(found)
    except Exception:
        return 0


def _indic_score(text: str) -> int:
    """Max of Hindi/Marathi scheduling confidence."""
    try:
        return max(_hindi_score(text), _marathi_score(text))
    except Exception:
        return 0


_MR_REL_RE = re.compile(
    r"\b(\d+|[a-zA-Z]+)\s*(minit\w*|seconds?|tas\w*|hours?)\s*"
    r"(nantar|ne|madhye|me)\b", re.I)
_MR_REL_FUSED_RE = re.compile(r"\b(\d+)\s*(minitanni|minitat|tasant|tasanni)\b", re.I)
_MR_CLOCK_RE = re.compile(
    r"(?:\b(aaj|udya|parva|आज|उद्या|परवा)\b)?\s*"
    r"(?:\b(sakali|dupari|sandhyakali|ratri|सकाळी|दुपारी|संध्याकाळी|रात्री)\b)?\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(vajta|vajle|वाजता)\b", re.I)

_MR_NUM = {"ek": 1, "don": 2, "teen": 3, "chaar": 4, "paach": 5,
           "saha": 6, "saat": 7, "aath": 8, "nau": 9, "dha": 10}


def parse_when_marathi(text: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Parse Marathi due times. Returns {"ok", "when", "span"}."""
    now = now or _now()
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "message": "no time given"}

    fused = _MR_REL_FUSED_RE.search(raw)
    if fused:
        amount = int(fused.group(1))
        unit = fused.group(2).lower()
        delta = timedelta(hours=amount) if unit.startswith("tas") else timedelta(minutes=amount)
        return {"ok": True, "when": now + delta, "span": fused.span()}

    rel = _MR_REL_RE.search(raw)
    if rel:
        tok = (rel.group(1) or "").lower()
        amount = int(tok) if tok.isdigit() else _MR_NUM.get(tok)
        unit = (rel.group(2) or "").lower()
        if amount is not None and amount > 0:
            if unit.startswith("tas") or unit.startswith("hour"):
                delta = timedelta(hours=amount)
            elif unit.startswith("sec"):
                delta = timedelta(seconds=amount)
            else:
                delta = timedelta(minutes=amount)
            return {"ok": True, "when": now + delta, "span": rel.span()}

    clock = _MR_CLOCK_RE.search(raw)
    if clock:
        day_word = (clock.group(1) or "").lower()
        part = (clock.group(2) or "").lower()
        hour = int(clock.group(3))
        minute = int(clock.group(4) or 0)
        if hour > 24 or minute > 59:
            return {"ok": False, "message": "bad time"}
        if part in ("sandhyakali", "ratri", "dupari", "संध्याकाळी", "रात्री", "दुपारी") and hour < 12:
            hour += 12
        if hour == 24:
            hour = 0
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_word in ("parva", "परवा"):
            candidate = (now + timedelta(days=2)).replace(
                hour=hour, minute=minute, second=0, microsecond=0)
        elif day_word in ("udya", "उद्या"):
            if candidate <= now + timedelta(minutes=1):
                candidate += timedelta(days=1)
            elif candidate.date() <= now.date():
                candidate += timedelta(days=1)
        elif candidate <= now:
            candidate += timedelta(days=1)
        if candidate - now > timedelta(days=366):
            return {"ok": False, "message": "that is more than a year away"}
        return {"ok": True, "when": candidate, "span": clock.span()}

    return {"ok": False, "message": "no time found"}


def _next_repeat_due(repeat: str, from_dt: datetime) -> Optional[datetime]:
    try:
        if repeat == "daily":
            return from_dt + timedelta(days=1)
        if repeat == "weekly":
            return from_dt + timedelta(days=7)
        if repeat == "weekdays":
            nxt = from_dt + timedelta(days=1)
            while nxt.weekday() >= 5:  # skip Sat/Sun
                nxt += timedelta(days=1)
            return nxt
    except Exception:
        pass
    return None


_HI_REMIND_TRIG = re.compile(
    r"\b(yaad\s+dila\w*|yaad\s+kara\w*|याद\s+दिला\w*|याद\s+करा\w*|"
    r"reminder\s+laga\w*|रिमाइंडर\s+लगा\w*)\b", re.I)
_HI_CONN_LEAD = re.compile(r"^(?:ke\s+liye|ki|ko|ka)\b\s*", re.I)
_HI_CONN_TAIL = re.compile(r"\s*\b(?:ke\s+liye|ko)\s*$", re.I)


def _is_hindi_reminder(raw: str) -> bool:
    if _HI_REMIND_TRIG.search(raw or ""):
        return True
    return _hindi_score(raw) >= 2 and bool(
        re.search(r"\byaad\b|याद", raw or "", re.I))


_MR_REMIND_TRIG = re.compile(
    r"\b(aathvan\s+karun\s+de\w*|aathvan\s+kara\w*|आठवण\s+करून\s+दे\w*|"
    r"आठवण\s+करा\w*|reminder\s+lava\w*|रिमाइंडर\s+लावा\w*)\b", re.I)
# Trailing "chi/cha" is the Marathi genitive ("gym chi aathvan" = gym's
# reminder) — grammar, not content. Standalone words only, so "Ranchi"
# can never be damaged (its "chi" isn't space-separated).
_MR_CONN_LEAD = re.compile(r"^(?:sathi|साठी)\b\s*", re.I)
_MR_CONN_TAIL = re.compile(r"\s*\b(?:sathi|साठी|chi|che|cha|ची|चे|चा)\s*$", re.I)


def _is_marathi_reminder(raw: str) -> bool:
    if _MR_REMIND_TRIG.search(raw or ""):
        return True
    return _marathi_score(raw) >= 2 and bool(
        re.search(r"\baathvan\b|आठवण", raw or "", re.I))


def parse_reminder(text: str) -> Optional[Dict[str, Any]]:
    """Parse reminders (English + Hindi + Marathi) — {text, when, repeat?}."""
    raw = (text or "").strip()
    mr_mode = _is_marathi_reminder(raw)
    hi_mode = (not mr_mode) and _is_hindi_reminder(raw)
    if not hi_mode and not mr_mode and not re.search(
            r"\bremind\s+me\b|\bset\s+(?:a\s+)?reminder\b|\badd\s+(?:a\s+)?reminder\b",
            raw, re.I):
        return None
    lang = "mr" if mr_mode else ("hi" if hi_mode else "en")
    body = _REMIND_LEAD.sub("", raw).strip()
    body = re.sub(r"^(?:a\s+reminder\s+(?:to|about|that|for)\s+|reminder\s*:\s*)", "", body, flags=re.I).strip()
    if hi_mode:
        # "mujhe X yaad dilao" = "remind ME X" — mujhe is grammar, not content.
        body = re.sub(r"^(?:mujhe|mujhko|मुझे)\b\s*", "", body, flags=re.I).strip()
        body = _HI_REMIND_TRIG.sub(" ", body).strip()
    if mr_mode:
        # "mala X chi aathvan karun de" — mala is grammar, not content.
        body = re.sub(r"^(?:mala|मला)\b\s*", "", body, flags=re.I).strip()
        body = _MR_REMIND_TRIG.sub(" ", body).strip()
    if not body:
        return {"error": (
            "सांगा, कशाबद्दल आठवण करून देऊ? जसं: उद्या सकाळी 9 वाजता gym आठवण करून दे।"
            if mr_mode else
            "बताइए, किस बारे में याद दिलाऊँ? जैसे: कल सुबह 9 बजे gym याद दिलाओ।"
            if hi_mode else
            "Please tell me what to remind you about, sir. For example: remind me in 10 minutes to call mom.")}
    repeat, repeat_label, body = _detect_repeat(body)
    # Score the ORIGINAL text: repeat-stripping above may have eaten the
    # very markers ("roz", "darroj") the fallback check looks for.
    _raw_hi = _hindi_score(raw) >= 2
    _raw_mr = _marathi_score(raw) >= 2
    parsed = parse_when(body)
    if not parsed.get("ok") and (hi_mode or _raw_hi):
        hi_mode = True
        lang = "hi"
        parsed = parse_when_hindi(body)
    if not parsed.get("ok") and (mr_mode or _raw_mr):
        mr_mode = True
        lang = "mr"
        parsed = parse_when_marathi(body)
    if not parsed.get("ok"):
        if mr_mode:
            hint = " — जसं: रोज सकाळी 9 वाजता gym आठवण करून दे" if repeat else ""
            return {"error": f"कधी आठवण करून देऊ{((' ' + repeat_label) if repeat else '')}?{hint}"}
        if hi_mode:
            hint = " — जैसे: रोज़ सुबह 9 बजे gym याद दिलाओ" if repeat else ""
            return {"error": f"कब याद दिलाऊँ{((' ' + repeat_label) if repeat else '')}?{hint}"}
        hint = " — e.g. 'remind me every day at 9am to stretch'" if repeat else ""
        return {"error": f"When should I remind you{(' ' + repeat_label) if repeat else ''}, sir?{hint}"}
    reminder_text = _CONNECTOR_RE.sub("", _strip_span(body, parsed.get("span"))).strip(" .,-:")
    reminder_text = _CONNECTOR_RE.sub("", reminder_text).strip()
    if hi_mode or mr_mode:
        reminder_text = (_MR_CONN_LEAD if mr_mode else _HI_CONN_LEAD).sub("", reminder_text).strip()
        reminder_text = (_MR_CONN_TAIL if mr_mode else _HI_CONN_TAIL).sub("", reminder_text).strip()
        reminder_text = (_MR_REMIND_TRIG if mr_mode else _HI_REMIND_TRIG).sub(" ", reminder_text).strip(" .,-:")
        reminder_text = re.sub(r"\s+", " ", reminder_text).strip()
    # The repeat phrase must not leak into the reminder text itself.
    if repeat:
        _, _, reminder_text = _detect_repeat(reminder_text)
        reminder_text = _CONNECTOR_RE.sub("", reminder_text.strip(" .,-:")).strip()
        if hi_mode or mr_mode:
            reminder_text = (_MR_CONN_TAIL if mr_mode else _HI_CONN_TAIL).sub("", reminder_text).strip()
    if not reminder_text:
        return {"error": ("सांगा, कशाबद्दल आठवण करून देऊ?" if mr_mode
                          else "बताइए, किस बारे में याद दिलाऊँ?" if hi_mode
                          else "Please tell me what to remind you about, sir.")}
    out = {"text": reminder_text, "when": parsed["when"]}
    if repeat:
        out["repeat"] = repeat
        out["repeat_label"] = repeat_label
    return out


def add_reminder(text: str, when: datetime, repeat: str = "") -> Dict[str, Any]:
    try:
        from backend.agent.phase1_runtime import runtime
        kwargs = {"due_at": when.isoformat()}
        if repeat in ("daily", "weekdays", "weekly"):
            kwargs["repeat"] = repeat
        return runtime.reminders.add(text, **kwargs)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160]}


def list_reminders() -> List[Dict[str, Any]]:
    try:
        from backend.agent.phase1_runtime import runtime
        return runtime.reminders.list()
    except Exception:
        return []


# "the one I just created", "the last one", "the latest" — all mean the
# most recent item. list_reminders() is newest-first, so [0] is the target.
_RECENCY_RE = re.compile(
    r"\bjust\s+(created|made|added|set)|most\s+recent|\blatest\b|\blast\b|"
    r"that\s+one|this\s+one\b", re.I)


def _is_recency_fragment(fragment: str) -> bool:
    return bool(_RECENCY_RE.search(fragment or ""))


def cancel_reminder(fragment: str) -> Dict[str, Any]:
    fragment = (fragment or "").strip()
    folded = fragment.casefold()
    try:
        from backend.agent.phase1_runtime import runtime
        items = runtime.reminders.list()
        if not items:
            return {"status": "error", "message": "No active reminders, sir."}
        if not folded:
            if len(items) == 1:
                runtime.reminders.remove(items[0]["id"])
                return {"status": "success",
                        "message": f"Cancelled, sir: '{items[0].get('text', '')[:120]}'.",
                        "reminder": items[0]}
            options = "; ".join(f"'{m.get('text', '')[:60]}'" for m in items[:5])
            return {"status": "error",
                    "message": f"Which one, sir? {options}."}
        if _is_recency_fragment(fragment):
            latest = items[0]
            runtime.reminders.remove(latest["id"])
            return {"status": "success",
                    "message": f"Cancelled the latest, sir: '{latest.get('text', '')[:120]}'.",
                    "reminder": latest}
        matches = [r for r in items
                   if folded in str(r.get("text") or "").casefold()
                   or folded == str(r.get("id") or "").casefold()]
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
    """Speak+toast every due reminder exactly once. Returns fired count.

    Firing marks the reminder TRIGGERED/UNREAD in ReminderStore (stable id,
    persisted) instead of the legacy completed-only flag, so restarts can
    never mint a second identity for the same reminder and the Notification
    Center can show it as unread history."""
    fired = 0
    try:
        from backend.agent.phase1_runtime import runtime
        for reminder in runtime.reminders.due():
            try:
                marked = runtime.reminders.mark_triggered(reminder.get("id", ""))
                live = marked.get("reminder", reminder) if marked.get("status") == "success" else reminder
                on_fire({"kind": "reminder", "text": str(live.get("text") or ""),
                         "reminder": live})
                fired += 1
                # Recurring reminders re-arm themselves for the next cycle
                # (same stable text, new due date) instead of dying silently.
                try:
                    rep = str(live.get("repeat") or "").strip().lower()
                    if rep in ("daily", "weekdays", "weekly"):
                        cur = live.get("due_at") or live.get("snoozed_until") or ""
                        base = datetime.fromisoformat(str(cur).replace("Z", "+00:00"))
                        nxt = _next_repeat_due(rep, base)
                        if nxt is not None:
                            runtime.reminders.add(str(live.get("text") or ""),
                                                  due_at=nxt.isoformat(),
                                                  repeat=rep)
                except Exception:
                    pass
            except Exception:
                continue
    except Exception:
        pass
    return fired


def delete_job_by_id(job_id: str) -> Dict[str, Any]:
    """Hard-delete a non-pending job record (history cleanup only). Pending
    jobs must go through cancel so the audit trail is kept; refused here."""
    jobs = _load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            if job.get("status") == "pending":
                return {"status": "error",
                        "message": "That message is still pending, sir — cancel it instead."}
            _save_jobs([j for j in jobs if j.get("id") != job_id])
            return {"status": "success", "message": "History entry deleted, sir.",
                    "job": job}
    return {"status": "error", "message": "Scheduled message not found, sir."}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    for job in _load_jobs():
        if job.get("id") == job_id:
            return job
    return None


def cancel_job_by_id(job_id: str) -> Dict[str, Any]:
    """Cancel one scheduled WhatsApp by stable id. Keeps the record as
    cancelled history (never refires, never disappears silently)."""
    jobs = _load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            if job.get("status") != "pending":
                return {"status": "error",
                        "message": f"That message is already {job.get('status')}, sir."}
            job["status"] = "cancelled"
            _save_jobs(jobs)
            return {"status": "success",
                    "message": f"Cancelled the scheduled WhatsApp to {job.get('contact')}, sir.",
                    "job": job}
    return {"status": "error", "message": "Scheduled message not found, sir."}


def reschedule_job_by_id(job_id: str, when: datetime) -> Dict[str, Any]:
    """Move one pending job to a new future time (stable id, history kept)."""
    if when.tzinfo is None:
        return {"status": "error", "message": "I need a timezone-aware time, sir."}
    if when <= _now():
        return {"status": "error",
                "message": "That time has already passed, sir. Please pick a future time."}
    if (when - _now()) > timedelta(days=366):
        return {"status": "error", "message": "That is more than a year away, sir."}
    jobs = _load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            if job.get("status") != "pending":
                return {"status": "error",
                        "message": f"That message is already {job.get('status')}, sir."}
            job["send_at"] = when.isoformat()
            _save_jobs(jobs)
            return {"status": "success",
                    "message": f"Rescheduled, sir. WhatsApp to {job.get('contact')} "
                               f"now sends {describe_when(when)}.",
                    "job": job}
    return {"status": "error", "message": "Scheduled message not found, sir."}


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
    fragment = (fragment or "").strip()
    folded = fragment.casefold()
    jobs = _load_jobs()
    pending = [j for j in jobs if j.get("status") == "pending"]
    if not pending:
        return {"status": "error", "message": "No scheduled messages to cancel, sir."}
    if not folded:
        if len(pending) == 1:
            pending[0]["status"] = "cancelled"
            _save_jobs(jobs)
            return {"status": "success",
                    "message": f"Cancelled the scheduled WhatsApp to {pending[0].get('contact')}, sir."}
        options = "; ".join(f"to {j.get('contact')}" for j in pending[:5])
        return {"status": "error",
                "message": f"Multiple scheduled messages, sir: {options}. Say which one to cancel."}
    if _is_recency_fragment(fragment):
        latest = max(pending, key=lambda j: str(j.get("created_at") or ""))
        latest["status"] = "cancelled"
        _save_jobs(jobs)
        return {"status": "success",
                "message": f"Cancelled the latest scheduled WhatsApp to {latest.get('contact')}, sir.",
                "job": latest}
    matches = [j for j in pending if
               folded in str(j.get("contact") or "").casefold()
               or folded in str(j.get("message") or "").casefold()
               or folded == str(j.get("id") or "").casefold()]
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


def delete_notification(fragment: str) -> Dict[str, Any]:
    """Delete a Notification Center entry by text fragment, or the latest one
    for recency fragments ('just created', 'last', ...)."""
    from backend.agent import notifications as _nc
    fragment = (fragment or "").strip()
    folded = fragment.casefold()
    items = _nc.list_notifications()
    if not items:
        return {"status": "error", "message": "No notifications to delete, sir."}
    if not folded or _is_recency_fragment(fragment):
        latest = items[0]  # list_notifications() is newest-first
        result = _nc.delete(latest.get("id", ""))
        if result.get("status") == "success":
            label = latest.get("title") or latest.get("body") or "notification"
            return {"status": "success",
                    "message": f"Deleted the latest notification, sir: '{str(label)[:120]}'."}
        return result
    matches = [n for n in items
               if folded in str(n.get("title") or "").casefold()
               or folded in str(n.get("body") or "").casefold()
               or folded == str(n.get("id") or "").casefold()]
    if not matches:
        return {"status": "error",
                "message": "I found no notification matching that, sir."}
    if len(matches) > 1:
        options = "; ".join(
            f"'{str(m.get('title') or m.get('body') or '')[:60]}'" for m in matches[:5])
        return {"status": "error",
                "message": f"Multiple match, sir: {options}. Please be more specific."}
    result = _nc.delete(matches[0].get("id", ""))
    if result.get("status") == "success":
        label = matches[0].get("title") or matches[0].get("body") or "notification"
        return {"status": "success",
                "message": f"Deleted, sir: '{str(label)[:120]}'."}
    return result


def delete_note(fragment: str) -> Dict[str, Any]:
    """Delete a Notes-panel entry by text fragment, or the latest note."""
    import json as _json
    import os as _os
    notes_path = _os.path.abspath(_os.path.join(
        _os.path.dirname(__file__), "..", "..", "notes.json"))
    try:
        with open(notes_path, "r", encoding="utf-8") as fh:
            notes = _json.load(fh)
        notes = notes if isinstance(notes, list) else []
    except (OSError, ValueError):
        notes = []
    if not notes:
        return {"status": "error", "message": "No notes to delete, sir."}
    fragment = (fragment or "").strip()
    folded = fragment.casefold()
    if not folded or _is_recency_fragment(fragment):
        latest = notes[-1]
        kept = notes[:-1]
    else:
        matches = [n for n in notes
                   if folded in str(n.get("text") or "").casefold()]
        if not matches:
            return {"status": "error",
                    "message": "I found no note matching that, sir."}
        if len(matches) > 1:
            options = "; ".join(
                f"'{str(m.get('text') or '')[:60]}'" for m in matches[:5])
            return {"status": "error",
                    "message": f"Multiple match, sir: {options}. Please be more specific."}
        latest = matches[0]
        kept = [n for n in notes if n is not latest]
    try:
        tmp = notes_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(kept, fh, indent=2, ensure_ascii=False)
        _os.replace(tmp, notes_path)
    except OSError as exc:
        return {"status": "error", "message": f"Couldn't save notes, sir: {exc}"}
    return {"status": "success",
            "message": f"Deleted the note, sir: '{str(latest.get('text') or '')[:120]}'."}


def _mark_job(job_id: str, status: str, result: str = "") -> None:
    jobs = _load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job["status"] = status
            job["result"] = result[:300]
            break
    _save_jobs(jobs)


def reschedule_scheduled(fragment: str, when: datetime) -> Dict[str, Any]:
    """Move a pending job to a new future time. Survives restart (same store).

    Never touches sent/failed/cancelled jobs, so execution history is never
    rewritten and a delivered message can never be duplicated by rescheduling.
    """
    fragment = (fragment or "").strip().casefold()
    if not fragment:
        return {"status": "error",
                "message": "Which scheduled message should I move, sir?"}
    if when <= _now():
        return {"status": "error",
                "message": "That time has already passed, sir. Please pick a future time."}
    if (when - _now()) > timedelta(days=366):
        return {"status": "error", "message": "That is more than a year away, sir."}
    jobs = _load_jobs()
    matches = [j for j in jobs if j.get("status") == "pending" and
               (fragment in str(j.get("contact") or "").casefold()
                or fragment in str(j.get("message") or "").casefold()
                or fragment == str(j.get("id") or "").casefold())]
    if not matches:
        return {"status": "error",
                "message": "No pending scheduled message matches that, sir."}
    if len(matches) > 1:
        options = "; ".join(f"to {j.get('contact')}" for j in matches[:5])
        return {"status": "error",
                "message": f"Multiple match, sir: {options}. Please be more specific."}
    matches[0]["send_at"] = when.isoformat()
    _save_jobs(jobs)
    return {"status": "success",
            "message": f"Rescheduled, sir. WhatsApp to {matches[0].get('contact')} "
                       f"now sends {describe_when(when)}.",
            "job": matches[0]}


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
_GENERIC_MESSAGE_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:schedule|send)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+", re.I)
_SAY_SPLIT = re.compile(
    r"\b(?:saying|that\s+says|with\s+(?:the\s+)?message|message\s*:|as)\b\s*:?\s*|:\s*", re.I)


def _parse_flexible_order(raw: str) -> Optional[Dict[str, Any]]:
    """Order-independent fallback: time anywhere, contact after 'to', message
    after saying/as/:/etc. Handles e.g.
    'schedule a message at 11 am to +91... as HELLO' (time before contact)."""
    parsed_time = parse_when(raw)
    if not parsed_time.get("ok"):
        return {"error": "I need a time, sir. For example: send whatsapp to Mom at 6pm saying happy birthday."}
    when = parsed_time["when"]
    if when <= _now():
        return {"error": "That time has already passed, sir. Please pick a future time."}
    remainder = _strip_span(raw, parsed_time.get("span")).strip()
    if not remainder:
        return {"error": "Who should I send the WhatsApp to, sir?"}
    say_parts = _SAY_SPLIT.split(remainder, maxsplit=1)
    if len(say_parts) != 2:
        return {"error": "What should the message say, sir? Add 'saying …' (or 'as …') after the time."}
    left, message = say_parts[0].strip(), say_parts[1].strip(" .,-:")
    if not message:
        return {"error": "What should the message say, sir? Add 'saying …' (or 'as …') after the time."}
    # Contact is whatever follows the LAST 'to' in the left part, so leading
    # verbs ('schedule a message', 'send whatsapp', ...) never leak into it.
    contact_match = re.search(r"\bto\s+(.+)$", left.strip(), re.I | re.S)
    if not contact_match:
        return {"error": "Who should I send the WhatsApp to, sir? Add 'to …' with a name or number."}
    contact = contact_match.group(1).strip(" .,-:")
    # Strip any leftover leading verbs if 'to' was missing earlier (defensive).
    contact = re.sub(
        r"^(?:please\s+)?(?:schedule\s+(?:a\s+)?|send\s+(?:a\s+)?)?"
        r"(?:whatsapp\s+(?:message\s+)?|message\s+)?", "", contact, flags=re.I).strip()
    if not contact:
        return {"error": "Who should I send the WhatsApp to, sir?"}
    return {"contact": contact, "message": message, "when": when}


def parse_scheduled_whatsapp(text: str) -> Optional[Dict[str, Any]]:
    """Parse 'send/schedule whatsapp to X at <time> saying Y'.

    Also accepts the generic alias 'schedule (a) [whatsapp] message …'
    (treated as WhatsApp — the only scheduled-messaging channel) and
    time-before-contact order ('… at 11 am to +91… as HELLO').

    Returns None when this is NOT a scheduling request (e.g. an immediate
    send with no time expression → falls through to the normal sender)."""
    raw = (text or "").strip()
    has_whatsapp = bool(re.search(r"\bwhatsapp\b", raw, re.I))
    # Generic "schedule/send a message …" (no explicit 'whatsapp') is treated
    # as a WhatsApp schedule — the only scheduled-messaging channel JARVIS has.
    has_generic_message = bool(
        re.search(r"\bmessage\b", raw, re.I)
        and re.search(r"\b(schedul\w*|send)\b", raw, re.I))
    if not (has_whatsapp or has_generic_message):
        return None
    if not re.search(r"\b(schedule|at\s+|in\s+\d|in\s+an?\s+|tomorrow|today|tonight|on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", raw, re.I):
        return None  # no time expression → immediate send, not our business
    body = _SCHEDULE_LEAD.sub("", raw).strip()
    if not body or body == raw.strip():
        body = _GENERIC_MESSAGE_LEAD.sub("", raw).strip()
    if not body or body == raw.strip():
        # "whatsapp Mom at 6pm saying hi" without send/schedule verb
        body = re.sub(r"^\s*(?:please\s+)?whatsapp\s+(?:message\s+)?to\s+", "", raw, flags=re.I).strip()
        if not body or body == raw.strip():
            # Time-before-contact order ("… at 11 am to +91… as HELLO") never
            # fits the contact-first split below — use the flexible parser.
            return _parse_flexible_order(raw)
    at_split = re.split(r"\s+at\s+", body, maxsplit=1, flags=re.I)
    if len(at_split) == 2:
        contact, rest = at_split[0].strip(), at_split[1].strip()
    else:
        in_split = re.split(r"\s+(in\s+(?:\d|an?\b|half))", body, maxsplit=1, flags=re.I)
        if len(in_split) >= 3:
            contact, rest = in_split[0].strip(), (in_split[1] + in_split[2]).strip()
        else:
            # Contact-first split failed (e.g. time-before-contact order) —
            # retry with the order-independent parser before giving up.
            flexible = _parse_flexible_order(raw)
            if flexible is not None and "error" not in flexible:
                return flexible
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
        return {"error": "What should the message say, sir? Add 'saying …' (or 'as …') after the time."}
    parsed = parse_when(time_part if len(say_parts) == 2 else rest)
    if not parsed.get("ok"):
        return {"error": "I could not understand the time, sir. Try 'at 6pm' or 'in 2 hours'."}
    if parsed["when"] <= _now():
        return {"error": "That time has already passed, sir. Please pick a future time."}
    return {"contact": contact, "message": message, "when": parsed["when"]}


# ── normal-mode command router ────────────────────────────────────────────────
def _response(speak: str, log: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = {"speak": speak, "speak_lang": "en", "logs": [log], "file_data": None,
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

    # -- delete a Notification Center entry ("delete the notification ...") --
    notif_del = re.match(
        r"^\s*(?:please\s+)?(?:cancel|delete|remove|dismiss|clear)\s+"
        r"(?:the\s+|my\s+|that\s+)?notifications?\s*(.*)$", raw, re.I)
    if notif_del:
        raw_frag = (notif_del.group(1) or "").strip()
        if _is_recency_fragment(raw_frag):
            raw_frag = "latest"
        else:
            raw_frag = re.sub(r"^(?:i\s+)?just\s+created\.?\s*(?:about\s+)?", "",
                              raw_frag, flags=re.I).strip()
        result = delete_notification(raw_frag)
        return _response(result.get("message", ""),
                         f"NOTIFICATION delete: {result.get('status')}", result)

    # -- delete a Notes-panel entry ("delete the note ...") --
    note_del = re.match(
        r"^\s*(?:please\s+)?(?:delete|remove)\s+"
        r"(?:the\s+|my\s+|that\s+)?notes?\s*(.*)$", raw, re.I)
    if note_del:
        raw_frag = (note_del.group(1) or "").strip()
        if _is_recency_fragment(raw_frag):
            raw_frag = "latest"
        result = delete_note(raw_frag)
        return _response(result.get("message", ""),
                         f"NOTE delete: {result.get('status')}", result)

    # -- list / cancel reminders (English + Hindi) --
    if re.match(r"^\s*(?:please\s+)?(?:list|show)\s+(?:all\s+)?(?:my\s+)?reminders?\s*$", raw, re.I) or \
            re.match(r"^\s*what\s+are\s+my\s+reminders?\s*\??\s*$", raw, re.I) or \
            re.search(r"(mere|मेरे)\s+(saare\s+|सारे\s+)?reminders?\s+(batao|dikhao|दिखाओ|बताओ)", raw, re.I):
        items = list_reminders()
        if not items:
            return _response("No active reminders, sir.", "REMINDERS: none active")
        lines = []
        for item in items[:10]:
            try:
                when = datetime.fromisoformat(str(item.get("due_at", "")))
                when_s = describe_when_auto(raw, when)
            except (ValueError, TypeError):
                when_s = "unscheduled"
            rep = str(item.get("repeat") or "").strip()
            rep_say = f" (repeats {rep})" if rep in ("daily", "weekdays", "weekly") else ""
            lines.append(f"'{item.get('text', '')[:80]}' — {when_s}{rep_say}")
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

    # -- new reminder (English + Hindi + Marathi) --
    if re.search(r"\bremind\s+me\b|\bset\s+(?:a\s+)?reminder\b|\badd\s+(?:a\s+)?reminder\b", lowered) \
            or _is_hindi_reminder(raw) or _is_marathi_reminder(raw):
        parsed = parse_reminder(raw)
        if parsed is None:
            return None
        if "error" in parsed:
            return _response(parsed["error"], f"REMINDER parse failed: {parsed['error']}")
        saved = add_reminder(parsed["text"], parsed["when"],
                               repeat=parsed.get("repeat", ""))
        try:
            from backend.agent import marathi as _mmod
            _mr_err = _mmod.is_marathi(raw)
        except Exception:
            _mr_err = False
        if saved.get("status") != "success":
            try:
                from backend.agent import hindi as _hmod
                _hi_err = (not _mr_err) and _hmod.is_hindi(raw)
            except Exception:
                _hi_err = False
            _err_say = ("आठवण जतन करता आली नाही।" if _mr_err
                        else "याददाश्त सहेज न सका।" if _hi_err
                        else "I could not save that reminder, sir.")
            return _response(_err_say, f"REMINDER ERROR: {saved.get('message')}")
        try:
            from backend.agent import hindi as _hmod
            _hi_conf = (not _mr_err) and _hmod.is_hindi(raw)
        except Exception:
            _hi_conf = False
        when_s = describe_when_auto(raw, parsed["when"])
        rep_label = parsed.get("repeat_label", "")
        if _mr_err:
            rep_say = f", {rep_label} पुन्हा सांगेन" if rep_label else ""
            return _response(f"{when_s} आठवण करून देईन{rep_say}: {parsed['text'][:160]}।",
                             f"REMINDER SET: '{parsed['text'][:80]}' for {when_s}{rep_say}",
                             {"reminder": saved.get("reminder")})
        if _hi_conf:
            rep_say = f", {rep_label} दोहराऊँगा" if rep_label else ""
            return _response(f"{when_s} याद दिलाऊँगा{rep_say}: {parsed['text'][:160]}।",
                             f"REMINDER SET: '{parsed['text'][:80]}' for {when_s}{rep_say}",
                             {"reminder": saved.get("reminder")})
        rep_say = f", repeating {rep_label}" if rep_label else ""
        return _response(f"Reminder set for {when_s}{rep_say}, sir: {parsed['text'][:160]}.",
                         f"REMINDER SET: '{parsed['text'][:80]}' for {when_s}{rep_say}",
                         {"reminder": saved.get("reminder")})

    # -- reschedule scheduled whatsapp ("reschedule/move/postpone X to <time>") --
    if re.search(r"\b(reschedul\w*|move|postpone|shift|change)\b", lowered) and \
            ("schedul" in lowered or "whatsapp" in lowered):
        # Strip the leading verb FIRST so the time span offsets below refer
        # to the same string they are applied to.
        frag = re.sub(r"^\s*(?:please\s+)?(?:reschedule|move|postpone|shift|change)\b\s*",
                      "", raw, flags=re.I).strip()
        frag = re.sub(r"\b(?:the\s+)?scheduled(\s+whatsapp)?(\s+message)?\b\s*(to\s+)?",
                      "", frag, flags=re.I).strip()
        frag = re.sub(r"^whatsapp\s+(?:message\s+)?to\s+", "", frag, flags=re.I).strip()
        parsed_when = parse_when(frag)
        if not parsed_when.get("ok"):
            return _response("When should I move it to, sir? Try 'at 6pm' or 'in 2 hours'.",
                             "SCHEDULED WA reschedule: no time found")
        # Fragment = text minus the time span.
        span = parsed_when.get("span")
        if span:
            frag = _strip_span(frag, span).strip(" .,-:")
        frag = re.sub(r"\s+to\s*$", "", frag, flags=re.I).strip()
        result = reschedule_scheduled(frag, parsed_when["when"])
        return _response(result.get("message", ""),
                         f"SCHEDULED WA reschedule: {result.get('status')}", result)

    # -- new scheduled whatsapp (incl. generic "schedule a message …" alias) --
    _is_wa = "whatsapp" in lowered
    _is_generic_msg = ("message" in lowered
                       and ("schedul" in lowered or "send" in lowered))
    if (_is_wa or _is_generic_msg) and re.search(r"\b(schedule|at\b|in\s+\d|tomorrow|today|tonight)\b", lowered):
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
