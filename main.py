from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
import os
import asyncio
import json
import base64
import tempfile
import struct
import numpy as np
import wave
import io
import uuid
import threading
import time
import sys
import re
import faulthandler

# Dump a Python traceback to stderr on a segfault/access violation instead
# of dying silently (exit 3221225477). The watchdog pipes stderr into
# watchdog_crash.log, so the next native crash arrives with evidence.
faulthandler.enable()

# Import local helper modules
from system_ops import (
    get_system_stats, 
    open_application, 
    close_application, 
    list_files, 
    read_file, 
    write_file, 
    delete_file, 
    take_screenshot,
    create_folder,
    create_word_document,
    check_pc_health,
    adjust_volume,
    media_control,
    search_web,
    launch_any_app,
    save_generated_image,
    # New capabilities
    shutdown_pc,
    restart_pc,
    cancel_shutdown,
    sleep_pc,
    lock_screen,
    get_clipboard,
    set_clipboard,
    get_battery_info,
    get_network_info,
    get_weather,
    get_datetime_info,
    open_url,
    open_folder,
    empty_recycle_bin,
    clean_temp_files,
)
from agent import get_gemini_actions, generate_image_huggingface, conversation_history, stream_chat_response, stream_gemini_actions, stream_image_analysis, stream_document_analysis
import document_intel
import google_oauth
import phone_control
import whatsapp_ops
import code_core
from backend.startup_engine import get_startup_engine

from backend.agent.core import AgentCore
from backend.agent.state import TaskState
from backend.agent.voice import get_voice_system, get_command_processor, TTSState

app = FastAPI(title="J.A.R.V.I.S. Core", description="API Service for Windows OS Automation")

# Configure CORS so our React frontend can make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins in local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _start_ws_scrcpy():
    """Launch ws-scrcpy on port 8080 for the embedded phone mirror.
    Runs here (not just in the `python main.py` __main__ block) so it also
    starts when uvicorn is invoked directly, e.g. via start_jarvis.py's
    `python -m uvicorn main:app` subprocess call."""
    import subprocess
    ws_scrcpy_dir = os.path.join(os.path.dirname(__file__), "ws-scrcpy")
    if not os.path.exists(ws_scrcpy_dir):
        print("[ws-scrcpy] Directory not found, skipping (phone mirror embed will be unavailable).")
        return
    env = os.environ.copy()
    env["PORT"] = "8080"
    env["ADB"] = os.getenv("JARVIS_ADB_PATH", "adb")
    try:
        subprocess.Popen(
            ["npm", "start"],
            cwd=ws_scrcpy_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )
        print("[ws-scrcpy] Started on port 8080")
    except Exception as e:
        print(f"[ws-scrcpy] Failed to start: {e}")


# ── Startup Code Audit (automatic, read-only) ────────────────────────────────────
# After boot, a background worker performs a zero-mutation source scan (AST +
# py_compile - no Nemotron) and publishes the report so the UI can notify the
# user about problem files (with line ranges) and ask whether to apply fixes.

_STARTUP_AUDIT_LOCK = threading.Lock()
_startup_audit_report = None
_STARTUP_AUDIT_WAIT_SECONDS = 15


def _audit_report_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "data", "last_audit.json")


def _run_startup_audit_worker():
    """Run real codebase audit promptly upon boot and persist the report."""
    global _startup_audit_report
    time.sleep(1.0)
    with _STARTUP_AUDIT_LOCK:
        try:
            engine = get_startup_engine()
            audit_res = engine.run_real_audit()
            # Also fetch full code_core report for backwards compatibility
            report = code_core.audit_codebase()
            _startup_audit_report = report
            print(
                f"[startup-audit] Codebase scan finished: health {report['health_score']}%, "
                f"{report['total_files_checked']} files checked, {report['issues_count']} issue(s) "
                f"reported to the UI.",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[startup-audit] Startup scan failed: {e}", file=sys.stderr)


@app.on_event("startup")
def _start_startup_code_audit():
    """Launch the automatic read-only source audit shortly after boot."""
    try:
        threading.Thread(target=_run_startup_audit_worker, daemon=True).start()
        print("[startup-audit] Startup code check armed - running in background.", file=sys.stderr)
    except Exception as e:
        print(f"[startup-audit] Could not start audit thread: {e}", file=sys.stderr)


def _is_proactor_reset_noise(context: dict) -> bool:
    """True only for the known Windows proactor wart: an abrupt browser /
    health-poll disconnect surfacing as ConnectionResetError inside
    _call_connection_lost. Harmless — the server keeps serving."""
    try:
        exc = context.get("exception")
        if not isinstance(exc, ConnectionResetError):
            return False
        blob = f"{context.get('callback', '')} {context.get('message', '')}"
        return "_call_connection_lost" in blob or "connection_lost" in blob
    except Exception:
        return False


@app.on_event("startup")
def _quiet_proactor_disconnects():
    """Swallow exactly the proactor-reset noise; every other asyncio error
    still goes to the default handler untouched."""
    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        prev = loop.get_exception_handler()
    except Exception:
        prev = None

    def _handler(loop, context):
        try:
            if _is_proactor_reset_noise(context):
                return
        except Exception:
            pass
        try:
            if prev is not None:
                prev(loop, context)
            else:
                loop.default_exception_handler(context)
        except Exception:
            pass

    try:
        loop.set_exception_handler(_handler)
    except Exception:
        pass

# Configuration persistence
CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "config.json"))

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("gemini_project_id", "")
                data.setdefault("groq_api_key", "")
                return data
        except Exception:
            pass
    return {"gemini_api_key": "", "huggingface_api_key": "", "gemini_project_id": "", "groq_api_key": ""}

def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ── Notes & Todos persistence ──────────────────────────────────────────────
NOTES_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "notes.json"))
TODOS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "todos.json"))

def _load_json_list(path: str) -> list:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _save_json_list(path: str, data: list):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# Input data models
class CommandRequest(BaseModel):
    prompt: str
    apiKey: Optional[str] = None

class FileWriteRequest(BaseModel):
    filename: str
    content: str

class ChatStreamRequest(BaseModel):
    prompt: str
    apiKey: Optional[str] = None

class ImageAnalysisRequest(BaseModel):
    image_base64: str
    mime_type: str
    prompt: Optional[str] = ""
    apiKey: Optional[str] = None

class DocumentAnalysisRequest(BaseModel):
    document_text: str
    filename: str
    prompt: Optional[str] = ""
    apiKey: Optional[str] = None

class ConfigModel(BaseModel):
    gemini_api_key: str
    huggingface_api_key: str
    gemini_project_id: Optional[str] = ""
    groq_api_key: str = ""
    nvidia_api_key: Optional[str] = ""
    nvidia_model: Optional[str] = "z-ai/glm-5.3-flash"

# ── Code Core request models ────────────────────────────────────────────────
class CodePreviewFixRequest(BaseModel):
    file: str
    issue: Optional[str] = ""

class CodeApplyFixRequest(BaseModel):
    file: str
    proposed_content: str

class CodeProcessFileRequest(BaseModel):
    filename: str
    content: str
    instructions: Optional[str] = ""

# ── Phone control request models ────────────────────────────────────────────
class PhoneTapRequest(BaseModel):
    x: int
    y: int

class PhoneSwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: Optional[int] = 300

class PhoneTextRequest(BaseModel):
    text: str

class PhoneKeyRequest(BaseModel):
    key: str

class PhoneLaunchAppRequest(BaseModel):
    package: str

class PhoneUnlockRequest(BaseModel):
    pin: Optional[str] = None

class PhoneTestPinTapRequest(BaseModel):
    digit: str

@app.get("/api/config")
def get_config():
    return load_config()

@app.post("/api/config")
def post_config(req: ConfigModel):
    # Merge into existing config so Nemotron tuning keys survive this write
    cfg = load_config()
    cfg.update({
        "gemini_api_key": req.gemini_api_key,
        "huggingface_api_key": req.huggingface_api_key,
        "gemini_project_id": req.gemini_project_id or "",
        "groq_api_key": req.groq_api_key or "",
        "nvidia_api_key": req.nvidia_api_key or "",
        "nvidia_model": req.nvidia_model or "z-ai/glm-5.3-flash"
    })
    save_config(cfg)
    return {"status": "success", "message": "Configuration saved."}


# ── Code Core Endpoints ─────────────────────────────────────────────────────

@app.post("/api/code/audit")
def code_audit():
    return code_core.audit_codebase()

@app.get("/api/code/audit/latest")
def code_audit_latest():
    """Return the most recent startup self-audit report (read-only, no mutations).

    If the background startup worker hasn't published yet, run a fresh audit
    synchronously so early frontend polls always get a complete report.
    """
    global _startup_audit_report
    if _startup_audit_report is None:
        with _STARTUP_AUDIT_LOCK:
            if _startup_audit_report is None:
                try:
                    _startup_audit_report = code_core.audit_codebase()
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Audit failed: {e}")
    return _startup_audit_report

class CodeAuditFixRequest(BaseModel):
    issues: Optional[List[dict]] = None

@app.post("/api/code/audit/fix")
def code_audit_fix(req: CodeAuditFixRequest = None):
    """Apply fixes for the startup audit report issues (per-file, with backups,
    validation and auto-rollback). Returns per-file results including download
    URLs for each corrected file."""
    global _startup_audit_report
    if req and req.issues is not None:
        report = {"issues": req.issues}
    elif _startup_audit_report is not None:
        report = _startup_audit_report
    else:
        try:
            report = code_core.audit_codebase()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Audit failed: {e}")
    return code_core.apply_reported_fixes(report)

@app.post("/api/code/preview-fix")
def code_preview_fix(req: CodePreviewFixRequest):
    try:
        return code_core.preview_file_fix(req.file, req.issue)
    except code_core.NemotronUnavailableError as e:
        return {"status": "error", "error_type": "nemotron_unavailable", "file": req.file, "message": str(e)}

@app.post("/api/code/apply-fix")
def code_apply_fix(req: CodeApplyFixRequest):
    return code_core.apply_file_fix(req.file, req.proposed_content)

@app.post("/api/code/process-file")
def code_process_file(req: CodeProcessFileRequest):
    return code_core.process_uploaded_code_file(req.filename, req.content, req.instructions)

@app.get("/api/code/download/{filename}")
def code_download(filename: str):
    file_path = os.path.join(code_core.DOWNLOADS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)


# ── Cinematic Startup & Real Initialization Endpoints ──────────────────────

@app.get("/api/startup/stream")
async def startup_stream():
    """Stream real-time startup events (SSE) as initialization progresses."""
    engine = get_startup_engine()
    return StreamingResponse(
        engine.stream_startup_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/startup/init")
async def startup_init():
    """Execute full verified startup initialization and return state."""
    engine = get_startup_engine()
    return engine.initialize_full_system()


@app.get("/api/startup/status")
async def startup_status():
    """Get current startup status without triggering another full scan unless uninitialized."""
    engine = get_startup_engine()
    if not engine._initialized:
        return engine.initialize_full_system()
    return engine._last_state



# ===== Google OAuth (alternative to the raw Gemini API key) =====

@app.get("/api/oauth/status")
def oauth_status():
    """Report whether Jarvis currently has a linked, usable Google account."""
    return {"authenticated": google_oauth.is_authenticated()}


@app.post("/api/oauth/login")
def oauth_login():
    """
    Kick off the OAuth consent flow. This opens a local browser window for
    the user to sign in with Google and approve access; blocks until the
    flow completes or fails.
    """
    res = google_oauth.start_oauth_flow()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/oauth/logout")
def oauth_logout():
    """Unlink the Google account, forcing the app back to API-key/offline mode."""
    return google_oauth.logout()


# ── Proactive Gmail watcher (normal-mode announcements) ──────────────────────
# Background thread: one check shortly after start (restart check) + every
# poll_minutes. Important mail → voice announcement (queued, never cuts off
# current speech) + on-screen toast via /api/notifications. Same guarded
# worker pattern as the startup audit: never raises, never blocks boot.
import collections as _collections

_NOTIFICATIONS = _collections.deque(maxlen=20)
_NOTIFICATIONS_LOCK = threading.Lock()
_GMAIL_WORKER_STARTED = False


def _push_notification(kind: str, title: str, body: str, speak: str = "",
                       center_id: str = "") -> Dict[str, Any]:
    item = {"id": str(uuid.uuid4()), "kind": kind, "title": title, "body": body,
            "speak": speak, "dismissed": False, "ts": time.time(),
            "center_id": center_id}
    with _NOTIFICATIONS_LOCK:
        _NOTIFICATIONS.append(item)
    return item


def _announce_mail(message: Dict[str, Any], voice: bool = True) -> None:
    """Queue one mail arrival: toast + Notification Center always, voice only
    for important mail (or when explicitly asked). Best-effort only."""
    speak_text = message.get("speak") or message.get("toast") or ""
    important = bool(message.get("important"))
    title = (f"Important mail from {message.get('from_name', 'Unknown sender')}"
             if important else f"New mail from {message.get('from_name', 'Unknown sender')}")
    mid = str(message.get("id") or "").strip()
    center_id = f"gmail:{mid}" if mid else str(uuid.uuid4())
    _push_notification("gmail", title, str(message.get("subject", "")), speak_text,
                       center_id=center_id)
    try:
        from backend.agent import notifications as _nc
        _nc.upsert_notification(center_id,
                                "gmail", title, str(message.get("subject", "")),
                                speak_text if voice else "",
                                priority="important" if important else "normal",
                                ref_type="gmail", ref_id=mid)
    except Exception as exc:
        print(f"[gmail] persist announce failed: {exc}")
    if not voice or not message.get("speak"):
        return
    try:
        voice_sys = get_voice_system()
        # Priority -10, no interrupt: announcements truly wait behind any
        # active reply AND behind any queued reply (PriorityQueue pops the
        # highest number first, so a low number sorts last). The old value
        # of 5 did the opposite — it jumped AHEAD of normal replies
        # (priority 0), delaying answers and sounding like a duplicate TTS
        # ~30s later.
        voice_sys.speak(speak_text, priority=-10, interrupt=False)
    except Exception as exc:
        print(f"[gmail] TTS announce failed: {exc}")


def _gmail_check_cycle(reason: str) -> Dict[str, Any]:
    """Run one poll cycle + announce. Returns the raw cycle result."""
    try:
        from backend.tools import gmail_notify
        result = gmail_notify.check_for_important()
    except Exception as exc:
        print(f"[gmail] check failed ({reason}): {exc}")
        return {"status": "error", "announced": []}
    if result.get("status") == "not_linked":
        print("[gmail] Not linked — link Gmail in Settings to enable mail announcements.")
        return result
    for message in result.get("announced", []):
        _announce_mail(message, voice=True)
        print(f"[gmail] Announced ({reason}): {message.get('from_name', '?')} — "
              f"{str(message.get('subject', ''))[:80]}")
    for message in result.get("notified", []):
        _announce_mail(message, voice=False)
        print(f"[gmail] Toast ({reason}): {message.get('from_name', '?')} — "
              f"{str(message.get('subject', ''))[:80]}")
    return result


def _gmail_watch_worker() -> None:
    """Restart check after grace, then every poll_minutes. Never raises."""
    try:
        time.sleep(60)  # let TTS + UI settle before the first announcement
        from backend.tools import gmail_notify
        watch = gmail_notify.load_watch()
        if watch.get("announce_on_restart", True):
            _gmail_check_cycle("restart")
        while True:
            try:
                minutes = float(gmail_notify.load_watch().get("poll_minutes") or 30)
            except (TypeError, ValueError):
                minutes = 30
            time.sleep(max(60.0, minutes * 60.0))
            _gmail_check_cycle("scheduled")
    except Exception as exc:
        print(f"[gmail] watcher stopped: {exc}")


def _ensure_gmail_worker() -> None:
    global _GMAIL_WORKER_STARTED
    if _GMAIL_WORKER_STARTED:
        return
    _GMAIL_WORKER_STARTED = True
    thread = threading.Thread(target=_gmail_watch_worker,
                              name="jarvis-gmail-watch", daemon=True)
    thread.start()


_ensure_gmail_worker()


@app.get("/api/gmail/status")
def gmail_status():
    """Gmail link state + watcher schedule for the Settings UI."""
    try:
        from backend.tools import gmail_notify
        watch = gmail_notify.load_watch()
        seen = gmail_notify.load_seen()
        return {"linked": gmail_notify.is_gmail_linked(),
                "poll_minutes": watch.get("poll_minutes", 30),
                "vip_senders": watch.get("vip_senders", []),
                "last_check": seen.get("last_check", 0.0)}
    except Exception as exc:
        return {"linked": False, "error": str(exc)[:160]}


@app.post("/api/gmail/login")
def gmail_login():
    """Link Gmail (read-only). Opens the browser for consent; blocks like /api/oauth/login."""
    from backend.tools import gmail_notify
    res = gmail_notify.start_gmail_oauth_flow()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/gmail/logout")
def gmail_logout():
    from backend.tools import gmail_notify
    return gmail_notify.logout_gmail()


@app.post("/api/gmail/check")
def gmail_check_now():
    """Manual 'check mail now' — same cycle the scheduler runs."""
    return _gmail_check_cycle("manual")


@app.get("/api/notifications")
def list_notifications():
    """Undismissed toasts for the UI (polled alongside /api/status).

    Shape preserved for the existing toast stack; unread_count (persistent
    notifications + unread triggered reminders) added for the badge."""
    with _NOTIFICATIONS_LOCK:
        items = [dict(n) for n in _NOTIFICATIONS if not n.get("dismissed")]
    return {"notifications": items, "count": len(items),
            "unread_count": _center_unread_count()}


class DismissRequest(BaseModel):
    id: str = ""
    all: bool = False


@app.post("/api/notifications/dismiss")
def dismiss_notification(req: DismissRequest):
    center_ids: list = []
    with _NOTIFICATIONS_LOCK:
        removed = 0
        for item in _NOTIFICATIONS:
            if req.all or (req.id and item.get("id") == req.id):
                if not item.get("dismissed"):
                    item["dismissed"] = True
                    removed += 1
                cid = str(item.get("center_id") or "").strip()
                if cid:
                    center_ids.append(cid)
    persistent = {"status": "skipped"}
    if req.id:
        # Toast ids are ephemeral uuids; the linked Notification Center id
        # lives in center_id. Dismiss both so a toast never resurrects via
        # the Center badge, and dismissing never 404s on a random uuid.
        if center_ids:
            outs = [_do_center_action("dismiss", cid) for cid in center_ids]
            persistent = outs[0] if outs else {"status": "skipped"}
            if persistent.get("status") != "success":
                persistent = _do_center_action("dismiss", req.id)
        else:
            persistent = _do_center_action("dismiss", req.id)
    elif req.all:
        try:
            from backend.agent import notifications as _nc
            from backend.agent.phase1_runtime import runtime as _rt
            for item in _nc.list_notifications():
                _nc.dismiss(item["id"])
            for reminder in _rt.reminders.active_for_bar():
                _rt.reminders.dismiss(reminder["id"])
            persistent = {"status": "success"}
        except Exception as exc:
            persistent = {"status": "error", "message": str(exc)[:160]}
    return {"status": "success", "dismissed": removed, "persistent": persistent,
            "unread_count": _center_unread_count()}


# ── Notification Center (persistent, stable IDs) ─────────────────────────────
# Reminders + scheduled messages are VIEWS over their own stores (no second
# reminder system, no duplicate records). Only gmail/whatsapp/system
# notifications live in the notification store. The backend is the source of
# truth: every action mutates backend state first, the frontend mirrors it.
def _center_unread_count() -> int:
    total = 0
    try:
        from backend.agent import notifications as _nc
        total += _nc.unread_count()
    except Exception:
        pass
    try:
        from backend.agent.phase1_runtime import runtime as _rt
        total += _rt.reminders.unread_count()
    except Exception:
        pass
    return total


def _split_center_id(nid: str):
    nid = (nid or "").strip()
    for prefix in ("reminder:", "scheduled:"):
        if nid.startswith(prefix):
            return prefix[:-1], nid[len(prefix):]
    return "notification", nid


def _reminder_to_item(reminder: Dict[str, Any]) -> Dict[str, Any]:
    rid = str(reminder.get("id") or "")
    ts = (reminder.get("notified_at") or reminder.get("due_at")
          or reminder.get("created_at") or "")
    return {"id": f"reminder:{rid}", "kind": "reminder", "title": "Reminder",
            "body": str(reminder.get("text") or ""),
            "ts": ts, "due_at": reminder.get("due_at"),
            "read": bool(reminder.get("read")),
            "dismissed": bool(reminder.get("dismissed")),
            "priority": reminder.get("priority") or "normal",
            "status": reminder.get("status") or "scheduled",
            "ref_id": rid}


def _job_to_item(job: Dict[str, Any]) -> Dict[str, Any]:
    jid = str(job.get("id") or "")
    status = str(job.get("status") or "pending")
    return {"id": f"scheduled:{jid}", "kind": "scheduled",
            "title": f"WhatsApp to {job.get('contact') or 'Unknown'}",
            "body": str(job.get("message") or ""),
            "ts": job.get("send_at") or job.get("created_at") or "",
            "due_at": job.get("send_at"),
            "read": status != "pending", "dismissed": False,
            "priority": "normal", "status": status, "ref_id": jid,
            "contact": job.get("contact") or ""}


def _do_center_action(action: str, nid: str,
                       minutes: float = 10.0,
                       when_iso: str = "") -> Dict[str, Any]:
    """Route one read/unread/dismiss/delete/snooze by stable id prefix."""
    kind, bare = _split_center_id(nid)
    try:
        if kind == "reminder":
            from backend.agent.phase1_runtime import runtime as _rt
            store = _rt.reminders
            if action == "read":
                return store.mark_read(bare)
            if action == "unread":
                return store.mark_unread(bare)
            if action == "dismiss":
                return store.dismiss(bare)
            if action == "delete":
                return store.remove(bare)
            if action == "snooze":
                return store.snooze(bare, minutes=minutes,
                                    when_iso=when_iso or None)
            return {"status": "error", "message": f"Unknown action '{action}'."}
        if kind == "scheduled":
            from backend.tools import scheduler as _sched
            if action == "delete":
                job = _sched.get_job(bare)
                if job is not None and job.get("status") == "pending":
                    return _sched.cancel_job_by_id(bare)
                return _sched.delete_job_by_id(bare)
            if action in ("read", "dismiss"):
                return {"status": "success", "message": "Noted, sir."}
            if action == "snooze" or action == "reschedule":
                return {"status": "error",
                        "message": "Reschedule a message with a new time, sir."}
            if action == "unread":
                return {"status": "error",
                        "message": "Scheduled messages have no unread state, sir."}
            return {"status": "error", "message": f"Unknown action '{action}'."}
        from backend.agent import notifications as _nc
        if action == "read":
            return _nc.mark_read(bare if bare != nid else nid)
        if action == "unread":
            return _nc.mark_unread(bare if bare != nid else nid)
        if action == "dismiss":
            return _nc.dismiss(bare if bare != nid else nid)
        if action == "delete":
            return _nc.delete(bare if bare != nid else nid)
        return {"status": "error", "message": f"Unknown action '{action}'."}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160]}


class CenterActionRequest(BaseModel):
    id: str = ""


class SnoozeRequest(BaseModel):
    id: str = ""
    minutes: float = 10.0
    when: str = ""


class RescheduleRequest(BaseModel):
    when: str = ""


@app.get("/api/notifications/unread-count")
def notifications_unread_count():
    return {"unread": _center_unread_count()}


@app.get("/api/notifications/center")
def notification_center():
    """Aggregated snapshot for the Notification Center panel."""
    try:
        from backend.agent import notifications as _nc
        _nc.purge_expired()
        standalone = _nc.list_notifications(include_dismissed=True)
    except Exception:
        standalone = []
    try:
        from backend.agent.phase1_runtime import runtime as _rt
        history = _rt.reminders.history()
        active = [r for r in history if r.get("status") == "triggered"
                  and not r.get("read") and not r.get("dismissed")]
        upcoming = [r for r in history
                    if r.get("status") in ("scheduled", "snoozed")
                    and not r.get("completed")]
        past = [r for r in history
                if r.get("status") in ("triggered", "dismissed", "done")]
    except Exception:
        active, upcoming, past = [], [], []
    try:
        from backend.tools import scheduler as _sched
        jobs = _sched.list_scheduled(include_done=True)
    except Exception:
        jobs = []
    return {"notifications": standalone,
            "reminders": {"active": [_reminder_to_item(r) for r in active],
                          "upcoming": [_reminder_to_item(r) for r in upcoming],
                          "history": [_reminder_to_item(r) for r in past]},
            "scheduled": [_job_to_item(j) for j in jobs],
            "unread_count": _center_unread_count()}


@app.get("/api/reminders")
def list_reminders_api():
    try:
        from backend.agent.phase1_runtime import runtime as _rt
        history = _rt.reminders.history()
        return {"active": [_reminder_to_item(r) for r in _rt.reminders.active_for_bar()],
                "upcoming": [_reminder_to_item(r) for r in history
                             if r.get("status") in ("scheduled", "snoozed")
                             and not r.get("completed")],
                "history": [_reminder_to_item(r) for r in history
                            if r.get("status") in ("triggered", "dismissed", "done")],
                "unread": _rt.reminders.unread_count()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])


@app.get("/api/scheduled")
def list_scheduled_api():
    try:
        from backend.tools import scheduler as _sched
        jobs = _sched.list_scheduled(include_done=True)
        return {"jobs": [_job_to_item(j) for j in jobs],
                "pending": sum(1 for j in jobs if j.get("status") == "pending")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])


@app.post("/api/notifications/read")
def notification_read(req: CenterActionRequest):
    if not req.id.strip():
        raise HTTPException(status_code=400, detail="Notification id required.")
    res = _do_center_action("read", req.id)
    if res.get("status") != "success":
        raise HTTPException(status_code=404, detail=res.get("message", "Not found."))
    return {**res, "unread_count": _center_unread_count()}


@app.post("/api/notifications/unread")
def notification_unread(req: CenterActionRequest):
    if not req.id.strip():
        raise HTTPException(status_code=400, detail="Notification id required.")
    res = _do_center_action("unread", req.id)
    if res.get("status") != "success":
        raise HTTPException(status_code=404, detail=res.get("message", "Not found."))
    return {**res, "unread_count": _center_unread_count()}


@app.post("/api/notifications/read-all")
def notification_read_all():
    try:
        from backend.agent import notifications as _nc
        result = _nc.mark_all_read()
    except Exception as exc:
        result = {"status": "error", "message": str(exc)[:160]}
    try:
        from backend.agent.phase1_runtime import runtime as _rt
        marked = 0
        for reminder in _rt.reminders.active_for_bar():
            if _rt.reminders.mark_read(reminder["id"]).get("status") == "success":
                marked += 1
        result["reminders_marked"] = marked
    except Exception:
        pass
    return {**result, "unread_count": _center_unread_count()}


@app.post("/api/notifications/delete")
def notification_delete(req: CenterActionRequest):
    if not req.id.strip():
        raise HTTPException(status_code=400, detail="Notification id required.")
    res = _do_center_action("delete", req.id)
    if res.get("status") != "success":
        raise HTTPException(status_code=404, detail=res.get("message", "Not found."))
    return {**res, "unread_count": _center_unread_count()}


@app.post("/api/notifications/clear-history")
def notification_clear_history():
    """Delete read notification history. Never touches unread items, future
    reminders, or scheduled messages (different stores by construction)."""
    try:
        from backend.agent import notifications as _nc
        result = _nc.clear_read_history()
    except Exception as exc:
        result = {"status": "error", "message": str(exc)[:160]}
    return {**result, "unread_count": _center_unread_count()}


@app.post("/api/notifications/snooze")
def notification_snooze(req: SnoozeRequest):
    if not req.id.strip():
        raise HTTPException(status_code=400, detail="Notification id required.")
    kind, _ = _split_center_id(req.id)
    if kind != "reminder":
        raise HTTPException(status_code=400,
                            detail="Only reminders can be snoozed, sir.")
    res = _do_center_action("snooze", req.id, minutes=req.minutes,
                            when_iso=(req.when or "").strip())
    if res.get("status") != "success":
        raise HTTPException(status_code=400, detail=res.get("message", "Snooze failed."))
    wake = str(res.get("wake_at") or "")
    try:
        from backend.tools.scheduler import describe_when as _describe
        from datetime import datetime as _dt
        human = _describe(_dt.fromisoformat(wake)) if wake else wake
    except Exception:
        human = wake
    return {**res, "human": human, "unread_count": _center_unread_count()}


@app.delete("/api/reminders/{reminder_id}")
def delete_reminder_api(reminder_id: str):
    if not reminder_id.strip():
        raise HTTPException(status_code=400, detail="Reminder id required.")
    _, bare = _split_center_id(reminder_id)
    try:
        from backend.agent.phase1_runtime import runtime as _rt
        res = _rt.reminders.remove(bare)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])
    if res.get("status") != "success":
        raise HTTPException(status_code=404, detail=res.get("message", "Not found."))
    return {**res, "unread_count": _center_unread_count()}


@app.delete("/api/scheduled/{job_id}")
def delete_scheduled_api(job_id: str):
    """Cancel a pending message (kept as history) or delete a history entry."""
    if not job_id.strip():
        raise HTTPException(status_code=400, detail="Scheduled message id required.")
    _, bare = _split_center_id(job_id)
    try:
        res = _do_center_action("delete", f"scheduled:{bare}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])
    if res.get("status") != "success":
        raise HTTPException(status_code=404, detail=res.get("message", "Not found."))
    return res


@app.post("/api/scheduled/{job_id}/reschedule")
def reschedule_scheduled_api(job_id: str, req: RescheduleRequest):
    if not (req.when or "").strip():
        raise HTTPException(status_code=400, detail="New time required.")
    try:
        from datetime import datetime as _dt
        when = _dt.fromisoformat(req.when.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid time format.")
    _, bare = _split_center_id(job_id)
    try:
        from backend.tools import scheduler as _sched
        res = _sched.reschedule_job_by_id(bare, when)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])
    if res.get("status") != "success":
        raise HTTPException(status_code=400, detail=res.get("message", "Reschedule failed."))
    return res


# ── Normal-mode scheduler ticker (reminders + scheduled WhatsApp) ────────────
# Fires due reminders (voice + toast, exactly once) and sends due scheduled
# WhatsApp messages via the existing desktop sender. Same guarded daemon
# pattern as the Gmail watcher; stores are file-backed so jobs survive
# backend/PC restarts.
def _on_reminder_due(payload: Dict[str, Any]) -> None:
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    speak_text = f"Sir, reminder: {text[:200]}."
    rid = ""
    try:
        rid = str((payload.get("reminder") or {}).get("id") or payload.get("id") or "").strip()
    except Exception:
        rid = ""
    _push_notification("reminder", "Reminder", text[:200], speak_text,
                       center_id=f"reminder:{rid}" if rid else "")
    try:
        # Low priority so live replies always jump ahead of queued reminders.
        get_voice_system().speak(speak_text, priority=-10, interrupt=False)
    except Exception as exc:
        print(f"[scheduler] reminder TTS failed: {exc}")


def _send_scheduled_whatsapp(contact: str, message: str) -> Dict[str, Any]:
    try:
        return whatsapp_ops.send_whatsapp_message(contact, message)
    except Exception as exc:
        return {"status": "error", "message": f"Scheduled send failed: {exc}"}


def _on_whatsapp_result(job: Dict[str, Any], result: Dict[str, Any]) -> None:
    contact = str(job.get("contact") or "Unknown")
    ok = result.get("status") == "success"
    jid_early = str(job.get("id") or "").strip()
    wa_center = f"wa:{jid_early}" if jid_early else ""
    if ok:
        speak_text = f"Scheduled WhatsApp delivered to {contact}, sir."
        _push_notification("whatsapp", "WhatsApp delivered",
                           f"To {contact}: {str(job.get('message') or '')[:120]}",
                           speak_text, center_id=wa_center)
    else:
        speak_text = (f"Sir, the scheduled WhatsApp to {contact} failed: "
                      f"{str(result.get('message') or 'unknown error')[:160]}")
        _push_notification("whatsapp", "WhatsApp failed", speak_text, speak_text,
                           center_id=wa_center)
    try:
        from backend.agent import notifications as _nc
        jid = str(job.get("id") or "").strip()
        _nc.upsert_notification(f"wa:{jid}" if jid else str(uuid.uuid4()),
                                "whatsapp",
                                "WhatsApp delivered" if ok else "WhatsApp failed",
                                (f"To {contact}: {str(job.get('message') or '')[:120]}"
                                 if ok else speak_text),
                                speak_text,
                                priority="normal" if ok else "urgent",
                                ref_type="scheduled", ref_id=jid)
    except Exception as exc:
        print(f"[scheduler] persist whatsapp result failed: {exc}")
    try:
        # Low priority so live replies always jump ahead of status chatter.
        get_voice_system().speak(speak_text, priority=-10, interrupt=False)
    except Exception as exc:
        print(f"[scheduler] whatsapp TTS failed: {exc}")


def _ensure_scheduler_worker() -> None:
    try:
        from backend.tools import scheduler as _scheduler
        _scheduler.ensure_scheduler_worker(_on_reminder_due, _on_whatsapp_result,
                                           _send_scheduled_whatsapp)
    except Exception as exc:
        print(f"[scheduler] worker failed to start: {exc}")


_ensure_scheduler_worker()

@app.get("/api/status")
async def read_status():
    return {"status": "online", "system": "J.A.R.V.I.S.", "message": "All systems operational, sir."}


@app.get("/api/network/status")
def network_status():
    """Live connectivity snapshot for the HUD (cached ~10s in net_diagnostics).

    Lets the frontend distinguish backend-down vs Wi-Fi-off vs
    router-no-internet vs Google-unreachable instead of one generic OFFLINE.
    """
    try:
        from net_diagnostics import STATE_LABELS, get_connectivity_snapshot
        snap = get_connectivity_snapshot()
        state = snap.get("state", "wifi_off")
        return {
            "status": "success",
            "state": state,
            "state_label": STATE_LABELS.get(state, state),
            "online": state == "online",
            "internet": bool(snap.get("internet")),
            "dns": bool(snap.get("dns")),
            "gemini_reachable": bool(snap.get("gemini_reachable")),
            "ssid": snap.get("ssid", ""),
            "local_ips": snap.get("local_ips", []),
            "up_interfaces": snap.get("up_interfaces", []),
        }
    except Exception as e:
        return {"status": "error", "state": "unknown", "message": str(e)}


# ── Voice Command Endpoint (for native voice service) ──────────────────────
class VoiceCommandRequest(BaseModel):
    prompt: str


class TTSRequest(BaseModel):
    text: str
    priority: int = 0
    interrupt: bool = True
    lang: Optional[str] = None


@app.post("/api/voice/command")
async def voice_command(req: VoiceCommandRequest):
    """Endpoint for the native voice service to send recognized commands.

    The classification step is instant (no I/O); the full command runs in a
    worker thread via asyncio.to_thread so this endpoint never blocks the
    event loop either (same watchdog-timeout root cause as /api/command).
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt")

    # Get command processor and process the voice command
    processor = get_command_processor()
    processor.set_agent_core(AgentCore())

    # Create a temporary task state for context checking
    temp_state = TaskState()
    temp_state.task = getattr(temp_state, 'task', '') or ''

    result = await processor.process_command(req.prompt.strip(), temp_state)

    if result.get("status") == "interrupted":
        return {"status": "interrupted", "speak": "Interrupted, sir."}
    elif result.get("status") == "mid_task_instruction":
        return {"status": "mid_task_instruction", "speak": "Instruction noted, sir. Updating task."}
    elif result.get("status") == "task_queued":
        return {"status": "task_queued", "speak": "Noted, sir — queued to run after the current task."}
    elif result.get("status") == "new_command":
        # Process as new command — process_command is sync (threadpool),
        # so offload it instead of awaiting a coroutine.
        command_req = CommandRequest(prompt=req.prompt.strip(), apiKey=None)
        return await asyncio.to_thread(process_command, command_req)

    return result


@app.post("/api/voice/tts")
async def voice_tts(req: TTSRequest):
    """Text-to-speech endpoint with interruption support."""
    voice = get_voice_system()
    success = voice.speak(req.text, priority=req.priority, interrupt=req.interrupt, lang=req.lang)
    return {"status": "success" if success else "error", "speaking": voice.is_speaking()}


@app.post("/api/voice/tts/interrupt")
async def voice_tts_interrupt():
    """Interrupt current TTS playback."""
    voice = get_voice_system()
    interrupted = voice.interrupt()
    return {"status": "success", "interrupted": interrupted}


@app.get("/api/voice/tts/state")
async def voice_tts_state():
    """Get current TTS state."""
    voice = get_voice_system()
    return {"status": "success", "state": voice.get_state().value, "speaking": voice.is_speaking(), "muted": voice.is_muted()}


@app.get("/api/voice/voices")
async def voice_list():
    """Installed TTS voices (SAPI) with genders + which one JARVIS uses.

    Reads only worker-maintained state — never touches the SAPI COM object
    from a request thread (that cross-thread access crashes the backend)."""
    voice = get_voice_system()
    try:
        ready = voice._sapi_ready
        if not ready.is_set():
            await asyncio.to_thread(ready.wait, 8.0)
    except Exception:
        pass
    return {
        "status": "success",
        "active_voice_id": getattr(voice, "_active_voice_id", ""),
        "voices": voice.get_available_voices(),
    }


class VoiceMuteRequest(BaseModel):
    muted: bool = False


@app.get("/api/voice/mute")
async def voice_mute_state():
    """Whether backend speech (reminders, announcements) is muted."""
    return {"status": "success", "muted": get_voice_system().is_muted()}


@app.post("/api/voice/mute")
async def voice_mute(req: VoiceMuteRequest):
    """Mute/unmute backend speech. Muting stops in-flight speech and drops
    queued announcements (toasts/notifications are unaffected)."""
    muted = get_voice_system().set_muted(req.muted)
    return {"status": "success", "muted": muted}


# ── Notes endpoints ───────────────────────────────────────────────────────
@app.get("/api/notes")
def get_notes():
    return {"notes": _load_json_list(NOTES_FILE)}

@app.post("/api/notes")
def add_note(req: dict):
    text = (req.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Note text cannot be empty.")
    from datetime import datetime
    notes = _load_json_list(NOTES_FILE)
    note = {"id": int(datetime.now().timestamp() * 1000), "text": text,
            "time": datetime.now().strftime("%b %d %H:%M")}
    notes.append(note)
    _save_json_list(NOTES_FILE, notes)
    return {"status": "success", "note": note}

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    notes = _load_json_list(NOTES_FILE)
    notes = [n for n in notes if n.get("id") != note_id]
    _save_json_list(NOTES_FILE, notes)
    return {"status": "success"}

# ── Todos endpoints ───────────────────────────────────────────────────────
@app.get("/api/todos")
def get_todos():
    return {"todos": _load_json_list(TODOS_FILE)}

@app.post("/api/todos")
def add_todo(req: dict):
    text = (req.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Todo text cannot be empty.")
    from datetime import datetime
    todos = _load_json_list(TODOS_FILE)
    todo = {"id": int(datetime.now().timestamp() * 1000), "text": text, "done": False}
    todos.append(todo)
    _save_json_list(TODOS_FILE, todos)
    return {"status": "success", "todo": todo}

@app.patch("/api/todos/{todo_id}")
def toggle_todo(todo_id: int):
    todos = _load_json_list(TODOS_FILE)
    for t in todos:
        if t.get("id") == todo_id:
            t["done"] = not t.get("done", False)
            break
    _save_json_list(TODOS_FILE, todos)
    return {"status": "success"}

@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: int):
    todos = _load_json_list(TODOS_FILE)
    todos = [t for t in todos if t.get("id") != todo_id]
    _save_json_list(TODOS_FILE, todos)
    return {"status": "success"}

@app.get("/api/stats")
def read_stats():
    stats = get_system_stats()
    if "error" in stats:
        raise HTTPException(status_code=500, detail=stats["error"])
    return stats

@app.get("/api/files")
def get_files(subdir: str = ""):
    res = list_files(subdir)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res

@app.get("/api/files/read")
def get_file_content(filename: str):
    res = read_file(filename)
    if res["status"] == "error":
        raise HTTPException(status_code=404, detail=res["message"])
    return res

@app.post("/api/files/write")
def post_file_content(req: FileWriteRequest):
    res = write_file(req.filename, req.content)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res

@app.delete("/api/files/delete")
def remove_file(filename: str):
    res = delete_file(filename)
    if res["status"] == "error":
        raise HTTPException(status_code=404, detail=res["message"])
    return res

# Serve generated images from work_files
@app.get("/api/images/{filename}")
def serve_image(filename: str):
    work_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "work_files"))
    img_path = os.path.join(work_dir, "images", filename)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img_path, media_type="image/png")


# ===== Phone Control (ADB / scrcpy) =====

@app.get("/api/phone/devices")
def phone_devices():
    """List connected Android devices and their authorization status."""
    return phone_control.list_devices()


@app.post("/api/phone/mirror")
def phone_mirror():
    """Launch scrcpy to open a live, interactive mirror window of the phone."""
    res = phone_control.start_mirror()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/screenshot")
def phone_screenshot():
    """Capture the phone's current screen and return it as base64 for preview."""
    res = phone_control.screenshot_as_base64()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.get("/api/phone/stream")
def phone_stream():
    """Live-ish mirror: streams repeated screencap frames as multipart/x-mixed-replace,
    which browsers render natively in an <img> tag without any client-side decoding."""
    dev = phone_control.get_primary_device()
    if not dev:
        raise HTTPException(status_code=400, detail="No authorized Android device found, sir.")

    def generate():
        boundary = "jarvisframe"
        for frame in phone_control.stream_frames(dev):
            yield (
                f"--{boundary}\r\nContent-Type: image/png\r\nContent-Length: {len(frame)}\r\n\r\n"
            ).encode() + frame + b"\r\n"

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=jarvisframe")


@app.get("/api/phone/screenshot/{filename}")
def serve_phone_screenshot(filename: str):
    """Serve a previously captured phone screenshot from work_files/phone."""
    path = os.path.join(phone_control.PHONE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/phone/tap")
def phone_tap(req: PhoneTapRequest):
    res = phone_control.tap(req.x, req.y)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/swipe")
def phone_swipe(req: PhoneSwipeRequest):
    res = phone_control.swipe(req.x1, req.y1, req.x2, req.y2, req.duration_ms or 300)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/text")
def phone_text(req: PhoneTextRequest):
    res = phone_control.input_text(req.text)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/key")
def phone_key(req: PhoneKeyRequest):
    res = phone_control.press_key(req.key)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.get("/api/phone/apps")
def phone_apps():
    res = phone_control.list_installed_packages()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/launch_app")
def phone_launch_app(req: PhoneLaunchAppRequest):
    res = phone_control.launch_app(req.package)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/unlock")
def phone_unlock(req: PhoneUnlockRequest):
    """Wake the phone and dismiss the lock screen, optionally entering a PIN."""
    res = phone_control.unlock_phone(req.pin)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/test_pin_tap")
def phone_test_pin_tap(req: PhoneTestPinTapRequest):
    """Calibration helper: wake the screen and tap where a single digit
    should be on the lock screen's PIN pad, without swiping or submitting
    anything. Use this to verify/tune JARVIS_PIN_Y_OFFSET / JARVIS_PIN_X_OFFSET."""
    res = phone_control.test_pin_digit_tap(req.digit)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/phone/ocr")
def phone_ocr():
    """OCR the most recent phone screenshot (requires pytesseract + Pillow + Tesseract binary)."""
    res = phone_control.ocr_last_screenshot()
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/chat/stream")
def chat_stream(req: ChatStreamRequest):
    """Free-form conversational endpoint (Chat mode) - streams plain text
    back as it's generated, unlike /api/command which waits for a full
    JSON action list. Foundation for the upcoming image/document Q&A."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    api_key_to_use = req.apiKey
    config = load_config()
    if not api_key_to_use:
        api_key_to_use = config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")

    return StreamingResponse(
        stream_chat_response(req.prompt, api_key_to_use, gemini_project_id),
        media_type="text/plain; charset=utf-8"
    )


@app.post("/api/command/stream")
def command_stream(req: ChatStreamRequest):
    """Command execution endpoint - streams JSON actions as they're generated.
    Unlike /api/command which waits for complete response, this streams
    actions as they're parsed, enabling immediate execution."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    api_key_to_use = req.apiKey
    config = load_config()
    if not api_key_to_use:
        api_key_to_use = config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")

    return StreamingResponse(
        stream_gemini_actions(req.prompt, api_key_to_use, gemini_project_id),
        media_type="text/plain; charset=utf-8"
    )


@app.post("/api/vision/stream")
def vision_stream(req: ImageAnalysisRequest):
    """Image understanding endpoint - streams a description/answer about an
    uploaded image, using the same SSE streaming approach as /api/chat/stream."""
    if not req.image_base64.strip():
        raise HTTPException(status_code=400, detail="No image data received.")
    if not req.mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File does not appear to be an image.")

    api_key_to_use = req.apiKey
    config = load_config()
    if not api_key_to_use:
        api_key_to_use = config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")

    return StreamingResponse(
        stream_image_analysis(req.image_base64, req.mime_type, req.prompt or "", api_key_to_use, gemini_project_id),
        media_type="text/plain; charset=utf-8"
    )


@app.post("/api/document/extract")
async def extract_document(file: UploadFile = File(...)):
    """Upload a PDF/DOCX/PPTX/TXT/MD, extract its plain text, and hand it
    back to the frontend to hold onto until the user sends a question about
    it (see /api/document/stream). Nothing is persisted to disk afterward."""
    filename = file.filename or "document"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in document_intel.SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext or 'unknown'}', sir. Try PDF, DOCX, PPTX, TXT, or MD.")

    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {str(e)}")

    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="That file is over the 25MB limit, sir.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        result = document_intel.extract_text(tmp_path, filename)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/api/document/stream")
def document_stream(req: DocumentAnalysisRequest):
    """Ask a question about (or request a summary of) previously-extracted
    document text - streams the answer back like /api/chat/stream."""
    if not req.document_text.strip():
        raise HTTPException(status_code=400, detail="No document text received.")

    api_key_to_use = req.apiKey
    config = load_config()
    if not api_key_to_use:
        api_key_to_use = config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")

    return StreamingResponse(
        stream_document_analysis(req.document_text, req.filename, req.prompt or "", api_key_to_use, gemini_project_id),
        media_type="text/plain; charset=utf-8"
    )


@app.post("/api/command")
def process_command(req: CommandRequest):
    """Sync (threadpool) endpoint — NEVER block the event loop.

    Previously `async def` with blocking Gemini/WhatsApp/phone/screenshot
    calls inline, which stalled the loop for 10-30s per command. During that
    window /api/status + watchdog health checks timed out, the UI looked
    frozen, dismiss POSTs failed, and queued TTS fired late (perceived as a
    duplicate reply). As a plain `def`, FastAPI runs this in its threadpool
    so /api/status stays snappy even mid-reply.
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Command prompt cannot be empty.")

    # Check for chat reset keywords
    prompt_lower = req.prompt.lower().strip()
    if prompt_lower in ["clear chat", "reset history", "forget everything", "clear memory", "reset"]:
        import agent
        agent.clear_history()
        try:
            from backend.agent import phase1_memory, phase1_runtime
            if prompt_lower in ["clear memory", "forget everything", "reset"]:
                phase1_memory.clear()
            phase1_runtime.runtime.conversation.clear()
        except Exception:
            pass
        return {
            "speak": "Memory banks cleared, sir. Starting fresh.",
            "speak_lang": "en",
            "logs": ["ACTION: Cleared conversation history"],
            "file_data": None,
            "refresh_files": False,
            "image_data": None
        }

    # Normal-mode deterministic handlers: reminders + scheduled WhatsApp are
    # answered instantly without an LLM round-trip (same style as the reset
    # keywords above). Immediate WhatsApp sends fall through to Gemini below.
    try:
        from backend.tools import scheduler as _scheduler
        _direct = _scheduler.handle_schedule_command(req.prompt)
        if _direct is not None:
            return _direct
    except Exception as exc:
        print(f"[scheduler] direct handler failed: {exc}")

    # ── Deterministic identity memory (never LLM-dependent) ──────────────
    # "My name is Taha" / "I live in Pune" / "Pune only for weather" are
    # saved here on EVERY command — even offline or rate-limited — so the
    # facts are already in memory context before the LLM call below.
    # Name/city QUESTIONS are answered straight from memory too.
    _memory_note = ""
    try:
        from backend.agent import phase1_runtime as _rt
        _saved = _rt.capture_implicit_memories(req.prompt)
        if _saved:
            try:
                from backend.agent import phase1_memory as _pm
                _nick = _pm.get_user_name()
                _city = _pm.get_home_city()
                _bits = []
                try:
                    from backend.agent import marathi as _mmod
                    _mr_mode = _mmod.is_marathi(req.prompt)
                except Exception:
                    _mr_mode = False
                try:
                    from backend.agent import hindi as _hmod
                    _hi_mode = (not _mr_mode) and _hmod.is_hindi(req.prompt)
                except Exception:
                    _hi_mode = False
                for _item in _saved:
                    _k = str((_item or {}).get("key", "")).casefold()
                    if _k == "name" and _nick:
                        _bits.append(f"तुमचं नाव ({_nick}) लक्षात ठेवीन" if _mr_mode
                                     else f"आपका नाम ({_nick}) याद रखूँगा" if _hi_mode
                                     else f"noted your name ({_nick})")
                    elif _k in ("default city", "weather city", "city", "location",
                                "home city") and _city:
                        _bits.append(f"{_city} — हवामान तिथलंच सांगेन" if _mr_mode
                                     else f"{_city} — मौसम वहीं का बताऊँगा" if _hi_mode
                                     else f"locked in {_city} for weather")
                if _bits:
                    _memory_note = ("नोंदवलं — " if _mr_mode
                                    else "नोट किया — " if _hi_mode else "Noted — ") \
                        + (" आणि ".join(_bits) if _mr_mode else " और ".join(_bits)) \
                        + ("।" if (_mr_mode or _hi_mode) else ".")
            except Exception:
                pass
        _mem_answer = _rt.answer_from_memory(req.prompt)
        if _mem_answer:
            try:
                import agent as _agent_mod
                _agent_mod.add_to_history("user", req.prompt)
                _agent_mod.add_to_history("assistant", _mem_answer)
            except Exception:
                pass
            try:
                _rt.runtime.conversation.add("user", req.prompt, {"intent": "question"})
                _rt.runtime.conversation.add("assistant", _mem_answer, {})
            except Exception:
                pass
            try:
                from backend.agent.lang_detect import detect_lang as _dl
                _mem_lang = _dl(_mem_answer, req.prompt)
            except Exception:
                _mem_lang = "en"
            return {
                "speak": _mem_answer,
                "speak_lang": _mem_lang,
                "logs": [f"INPUT RECEIVED: \"{req.prompt}\"", "MEMORY: Answered from stored memory"],
                "file_data": None,
                "refresh_files": False,
                "image_data": None,
                "timer_data": None,
                "clarification_needed": None,
                "narration_steps": [],
            }
    except Exception as exc:
        print(f"[memory] deterministic handler failed: {exc}")

    # Load config once
    config = load_config()
    api_key_to_use = req.apiKey or config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")
    hf_key = config.get("huggingface_api_key", "")

    # Gather files context
    files_context = list_files()

    # Sync endpoint => already on a worker thread, direct blocking call is fine
    # and keeps the asyncio event loop free for /api/status + watchdog.
    actions = get_gemini_actions(req.prompt, api_key_to_use, files_context, gemini_project_id)

    # Home-city override: a bare "weather" (or the model's example-biased
    # "London" / "your location") resolves to the remembered default city.
    # An explicitly named city always wins and is left untouched.
    try:
        if isinstance(actions, list):
            _home = ""
            try:
                from backend.agent import phase1_memory as _pm2
                _home = (_pm2.get_home_city() or "").strip()
            except Exception:
                _home = ""
            if _home:
                for _a in actions:
                    if isinstance(_a, dict) and _a.get("type") == "weather":
                        _c = str(_a.get("city", "") or "").strip()
                        if _c.casefold() in ("", "london", "your location",
                                              "my location", "here", "local"):
                            _a["city"] = _home
    except Exception:
        pass
    
    execution_logs = []
    speak_text = ""
    file_data = None
    refresh_files = False
    image_data = None  # For generated images
    clarification_needed = None  # Populated when JARVIS needs to ask a follow-up
    narration_steps = []  # Sequential spoken updates for multi-step tasks
    
    execution_logs.append(f"INPUT RECEIVED: \"{req.prompt}\"")
    
    for action in actions:
        # A malformed action (e.g. a bare string from the model) must never
        # 500 the whole command into a bare "Command failed".
        if not isinstance(action, dict):
            execution_logs.append(f"ACTION: Skipping malformed action {str(action)[:80]}")
            continue
        try:
            act_type = action.get("type", "unknown")
        except Exception:
            execution_logs.append("ACTION: Skipping unreadable action")
            continue
        
        if act_type == "speak":
            speak_text = action.get("text", "")
            execution_logs.append(f"JARVIS: {speak_text}")

        elif act_type == "shutdown":
            try:
                delay = int(action.get("delay_seconds", 0))
            except (TypeError, ValueError):
                delay = 0
            res = shutdown_pc(delay)
            execution_logs.append(f"ACTION: Shutdown initiated")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "restart":
            try:
                delay = int(action.get("delay_seconds", 0))
            except (TypeError, ValueError):
                delay = 0
            res = restart_pc(delay)
            execution_logs.append(f"ACTION: Restart initiated")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "cancel_shutdown":
            res = cancel_shutdown()
            execution_logs.append(f"ACTION: Cancel shutdown")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "sleep":
            res = sleep_pc()
            execution_logs.append("ACTION: Sleep PC")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "lock_screen":
            res = lock_screen()
            execution_logs.append("ACTION: Lock screen")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "clipboard_read":
            res = get_clipboard()
            execution_logs.append("ACTION: Reading clipboard")
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override speak_text with actual clipboard content
            speak_text = res["message"]

        elif act_type == "clipboard_write":
            text = action.get("text", "")
            res = set_clipboard(text)
            execution_logs.append(f"ACTION: Writing to clipboard")
            execution_logs.append(f"RESULT: {res['message']}")
            speak_text = res["message"]

        elif act_type == "battery":
            res = get_battery_info()
            execution_logs.append("ACTION: Checking battery")
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual battery data
            speak_text = res["message"]

        elif act_type == "network_info":
            res = get_network_info()
            execution_logs.append("ACTION: Getting network info")
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual network data
            speak_text = res["message"]

        elif act_type == "weather":
            city = (action.get("city", "") or "").strip()
            if not city:
                try:
                    from backend.agent import phase1_memory as _wmem
                    city = _wmem.get_home_city() or ""
                except Exception:
                    city = ""
            try:
                day = int(action.get("day", 0) or 0)
            except (TypeError, ValueError):
                day = 0
            execution_logs.append(f"ACTION: Fetching weather for {city or 'home city'} (day+{day})")
            res = get_weather(city, day)
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual weather data (replaces any prior 'retrieving' placeholder)
            speak_text = res["message"]

        elif act_type == "calculate":
            expr = str(action.get("expression", "") or "")
            execution_logs.append(f"ACTION: Calculating \"{expr[:80]}\"")
            try:
                from backend.tools import knowledge as _know
                res = _know.calculate(expr or req.prompt)
            except Exception as exc:
                res = {"status": "error", "message": f"Couldn't crunch that: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "Couldn't crunch that.")

        elif act_type == "convert":
            ctext = str(action.get("text", "") or "")
            execution_logs.append(f"ACTION: Converting \"{ctext[:80]}\"")
            try:
                from backend.tools import knowledge as _know
                res = _know.convert_units(ctext or req.prompt)
            except Exception as exc:
                res = {"status": "error", "message": f"Couldn't convert that: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "Couldn't convert that.")

        elif act_type == "define":
            word = str(action.get("word", "") or "")
            execution_logs.append(f"ACTION: Defining \"{word[:40]}\"")
            try:
                from backend.tools import knowledge as _know
                res = _know.define_word(word or req.prompt)
            except Exception as exc:
                res = {"status": "error", "message": f"Dictionary lookup failed: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "Couldn't define that.")

        elif act_type == "joke":
            joke_lang = str(action.get("lang", "") or "")
            execution_logs.append(f"ACTION: Telling a joke (lang={joke_lang or 'en'})")
            try:
                from backend.tools import knowledge as _know
                res = _know.get_joke(joke_lang or "en")
            except Exception:
                res = {"status": "success", "message": "Why do programmers prefer dark mode? Because light attracts bugs."}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "")

        elif act_type == "fact":
            fact_lang = str(action.get("lang", "") or "")
            execution_logs.append(f"ACTION: Sharing a fact (lang={fact_lang or 'en'})")
            try:
                from backend.tools import knowledge as _know
                res = _know.get_fact(fact_lang or "en")
            except Exception:
                res = {"status": "success", "message": "Honey never spoils — 3,000-year-old pots found in tombs were still edible."}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "")

        elif act_type == "empty_recycle":
            execution_logs.append("ACTION: Emptying Recycle Bin")
            res = empty_recycle_bin()
            execution_logs.append(f"RESULT: {res['message']}")
            speak_text = res["message"]

        elif act_type == "clean_temp":
            execution_logs.append("ACTION: Cleaning temp folders")
            res = clean_temp_files()
            execution_logs.append(f"RESULT: {res['message']}")
            speak_text = res["message"]

        elif act_type == "datetime_info":
            res = get_datetime_info()
            execution_logs.append("ACTION: Getting date/time")
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual datetime data
            speak_text = res["message"]

        elif act_type == "read_email":
            try:
                count = int(action.get("count", 1))
            except (TypeError, ValueError):
                count = 1
            sender = (action.get("sender", "") or "").strip()
            unread_only = bool(action.get("unread_only", False))
            try:
                days = int(action.get("days", 0) or 0)
            except (TypeError, ValueError):
                days = 0
            try:
                older_than_days = int(action.get("older_than_days", 0) or 0)
            except (TypeError, ValueError):
                older_than_days = 0
            execution_logs.append(
                f"ACTION: Reading mail via Gmail API "
                f"(count={count}, sender={sender or 'any'}, "
                f"unread_only={unread_only}, days={days})")
            try:
                from backend.tools import gmail_notify
                # Sync endpoint => direct call (already off the event loop).
                res = gmail_notify.read_latest_mail(
                    count, sender, unread_only, days, older_than_days)
            except Exception as exc:
                res = {"status": "error",
                       "message": f"Couldn't reach Gmail, sir: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            # Always override with the real mail content — read aloud, never
            # by opening an app.
            speak_text = res.get("message", "Couldn't read your mail, sir.")

        elif act_type == "send_email":
            to = (action.get("to", "") or "").strip()
            subject = (action.get("subject", "") or "").strip()
            body = (action.get("body", "") or "").strip()
            execution_logs.append(f"ACTION: Sending mail to \"{to}\"")
            try:
                from backend.tools import gmail_notify
                res = gmail_notify.send_email(to, subject, body)
            except Exception as exc:
                res = {"status": "error",
                       "message": f"Couldn't send that mail, sir: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            speak_text = res.get("message", "Couldn't send that mail, sir.")

        elif act_type == "gmail_vip":
            op = (action.get("op", "add") or "add").strip().lower()
            contact = (action.get("contact", "") or "").strip()
            execution_logs.append(f"ACTION: Gmail VIP {op} \"{contact}\"")
            try:
                from backend.tools import gmail_notify
                if op == "remove":
                    res = gmail_notify.remove_vip(contact)
                elif op == "list":
                    vips = gmail_notify.load_watch().get("vip_senders", [])
                    res = {"status": "success",
                           "message": ("No VIP senders yet, sir — say 'treat mail "
                                       "from X as important' to add one.")
                           if not vips else
                           "Your VIP senders, sir: " + ", ".join(vips) + "."}
                else:
                    res = gmail_notify.add_vip(contact)
            except Exception as exc:
                res = {"status": "error",
                       "message": f"Couldn't update VIPs, sir: {exc}"}
            execution_logs.append(f"RESULT: {res.get('message', '')[:200]}")
            if not speak_text:
                speak_text = res.get("message", "")

        elif act_type == "open_url":
            url = action.get("url", "")
            res = open_url(url)
            execution_logs.append(f"ACTION: Opening URL {url}")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "set_timer":
            try:
                seconds = int(action.get("seconds", 60))
            except (TypeError, ValueError):
                seconds = 60
            label = action.get("label", "Timer")
            execution_logs.append(f"ACTION: Setting timer for {seconds} seconds")
            # Timer is purely frontend-driven; we pass the data back
            if not speak_text:
                minutes = seconds // 60
                secs = seconds % 60
                time_str = f"{minutes}m {secs}s" if minutes else f"{secs}s"
                speak_text = f"Timer set for {time_str}, sir."

        elif act_type == "add_note":
            note_text = action.get("text", "")
            execution_logs.append(f"ACTION: Adding note")
            from datetime import datetime as dt
            notes = _load_json_list(NOTES_FILE)
            note = {"id": int(dt.now().timestamp() * 1000), "text": note_text,
                    "time": dt.now().strftime("%b %d %H:%M")}
            notes.append(note)
            _save_json_list(NOTES_FILE, notes)
            execution_logs.append(f"RESULT: Note added")

        elif act_type == "add_todo":
            todo_text = action.get("text", "")
            execution_logs.append(f"ACTION: Adding todo")
            from datetime import datetime as dt
            todos = _load_json_list(TODOS_FILE)
            todo = {"id": int(dt.now().timestamp() * 1000), "text": todo_text, "done": False}
            todos.append(todo)
            _save_json_list(TODOS_FILE, todos)
            execution_logs.append(f"RESULT: Todo added")

        elif act_type == "remember":
            mem_text = (action.get("text", "") or "").strip()
            execution_logs.append(f"ACTION: Storing memory \"{mem_text[:80]}\"")
            # Guard: questions are NOT facts ("tumhara naam kya hai?" must
            # never be stored as a memory, nor spoken back as one).
            _is_question = (not mem_text or mem_text.rstrip().endswith("?")
                            or bool(re.search(
                                r"\b(kya|kaun|kab|kahan|kaise|kitna|what|who|whom|whose|which|when|where|why|how)\b",
                                mem_text, re.I)))
            if _is_question:
                # Logged as MEMORY: (not RESULT:) so it can never leak into
                # the spoken reply via the humanize result extractor.
                execution_logs.append(
                    f"MEMORY: Skipped save — question, not a fact: \"{mem_text[:80]}\"")
            else:
                try:
                    from backend.agent import phase1_memory
                    saved = phase1_memory.remember(
                        mem_text, category="general", source="jarvis-command")
                    # Internal status only (MEMORY:, not RESULT:) — the user
                    # hears Gemini's speak line, never "Memory stored (ok)".
                    execution_logs.append(
                        f"MEMORY: Stored ({saved.get('status', 'ok')}): \"{mem_text[:80]}\"")
                except Exception as exc:
                    execution_logs.append(f"MEMORY: Store failed: {exc}")
            
            
        elif act_type == "open_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Opening application \"{app_name}\"")
            res = launch_any_app(app_name) or {"status": "error",
                "message": f"Couldn't launch {app_name}, sir."}
            execution_logs.append(f"RESULT: {res['message']}")
            
        elif act_type == "close_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Closing application \"{app_name}\"")
            res = close_application(app_name) or {"status": "error",
                "message": f"Couldn't close {app_name}, sir."}
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "launch_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Launching application \"{app_name}\"")
            res = launch_any_app(app_name) or {"status": "error",
                "message": f"Couldn't launch {app_name}, sir."}
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "open_folder":
            target = action.get("folder", action.get("path", ""))
            execution_logs.append(f"ACTION: Opening folder \"{target}\"")
            res = open_folder(target)
            execution_logs.append(f"RESULT: {res['message']}")
            if not speak_text:
                speak_text = res["message"]
            
        elif act_type == "write_file":
            filename = action.get("filename", "")
            content = action.get("content", "")
            execution_logs.append(f"ACTION: Writing file \"{filename}\"")
            res = write_file(filename, content)
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True
            
        elif act_type == "read_file":
            filename = action.get("filename", "")
            execution_logs.append(f"ACTION: Reading file \"{filename}\"")
            res = read_file(filename)
            execution_logs.append(f"RESULT: {res.get('message') or 'Success'}")
            if res["status"] == "success":
                file_data = {
                    "filename": res["filename"],
                    "content": res["content"]
                }
                if not speak_text and res.get("message"):
                    speak_text = res["message"]
            elif res["status"] == "clarify":
                clarification_needed = {
                    "question": res["message"],
                    "context": "read_file",
                    "options": res.get("options", []),
                }
                speak_text = res["message"]
                
        elif act_type == "delete_file":
            filename = action.get("filename", "")
            execution_logs.append(f"ACTION: Deleting file \"{filename}\"")
            res = delete_file(filename)
            execution_logs.append(f"RESULT: {res['message']}")
            if res["status"] == "clarify":
                clarification_needed = {
                    "question": res["message"],
                    "context": "delete_file",
                    "options": res.get("options", []),
                }
            if not speak_text:
                speak_text = res["message"]
            refresh_files = True
            
        elif act_type == "take_screenshot":
            execution_logs.append("ACTION: Taking screenshot")
            res = take_screenshot()
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True
            
        elif act_type == "show_stats":
            execution_logs.append("ACTION: Loading HUD diagnostics...")
            try:
                stats = get_system_stats()
                if isinstance(stats, dict) and "error" not in stats:
                    procs = stats.get("processes", []) or []
                    # Name the hungriest apps first so "what's running" gets a real answer.
                    top = ", ".join(
                        p.get("name", "?") for p in procs[:5] if p.get("name")
                    ) or "no processes sampled"
                    speak_text = (
                        f"CPU at {stats.get('cpu', '?')} percent, memory at "
                        f"{stats.get('memory', '?')} percent, disk at "
                        f"{stats.get('disk', '?')} percent, sir. "
                        f"Busiest applications: {top}."
                    )
                    execution_logs.append(f"RESULT: {speak_text}")
                else:
                    speak_text = "I couldn't sample the system stats, sir."
            except Exception as exc:
                speak_text = f"Diagnostics failed, sir: {exc}"
                execution_logs.append(f"RESULT: {speak_text}")

        elif act_type == "create_folder":
            folder_name = action.get("folder_name", "")
            execution_logs.append(f"ACTION: Creating directory \"{folder_name}\"")
            res = create_folder(folder_name)
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True

        elif act_type == "create_word_doc":
            filename = action.get("filename", "")
            content = action.get("content", "")
            execution_logs.append(f"ACTION: Generating Word document \"{filename}\"")
            res = create_word_document(filename, content)
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True

        elif act_type == "check_pc_health":
            execution_logs.append("ACTION: Performing system diagnosis health check")
            res = check_pc_health()
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "volume_up":
            execution_logs.append("ACTION: Increasing system volume")
            res = adjust_volume("up")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "volume_down":
            execution_logs.append("ACTION: Decreasing system volume")
            res = adjust_volume("down")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "mute_volume":
            execution_logs.append("ACTION: Toggling system mute")
            res = adjust_volume("mute")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "play_pause":
            execution_logs.append("ACTION: Toggling media playback")
            res = media_control("play")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "next_track":
            execution_logs.append("ACTION: Skipping media track")
            res = media_control("next")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "prev_track":
            execution_logs.append("ACTION: Playing previous media track")
            res = media_control("prev")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "search_web":
            query = action.get("query", "")
            execution_logs.append(f"ACTION: Searching web for \"{query}\"")
            res = search_web(query)
            execution_logs.append(f"RESULT: {res['message']}")
            # Speak the short answer aloud when one was found (browser
            # still opens for depth) — searching now answers, not just shows.
            if res.get("status") == "success" and res.get("answer"):
                speak_text = res["message"]

        elif act_type == "generate_image":
            img_prompt = action.get("prompt", "")
            save_name = action.get("save_name", "")
            execution_logs.append(f"ACTION: Generating image for \"{img_prompt}\"")
            res = generate_image_huggingface(img_prompt, hf_key, save_name)
            execution_logs.append(f"RESULT: {res['message']}")
            if res["status"] == "success":
                image_data = {
                    "filename": res.get("filename", ""),
                    "image_base64": res.get("image_base64", "")
                }
                refresh_files = True

        elif act_type == "save_image":
            save_name = action.get("save_name", "")
            destination = action.get("destination", "desktop")
            execution_logs.append(f"ACTION: Saving image as \"{save_name}\" to {destination}")
            res = save_generated_image(save_name, destination)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "clear_history":
            import agent
            agent.clear_history()
            try:
                from backend.agent import phase1_runtime
                phase1_runtime.runtime.conversation.clear()
            except Exception:
                pass
            execution_logs.append("ACTION: Cleared conversation history")

        # --- Phone Control (ADB / scrcpy) -------------------------------
        elif act_type == "phone_devices":
            execution_logs.append("ACTION: Checking connected Android devices")
            res = phone_control.list_devices()
            execution_logs.append(f"RESULT: {res['message']}")
            if not speak_text:
                speak_text = res["message"]

        elif act_type == "phone_mirror":
            execution_logs.append("ACTION: Launching phone mirror (scrcpy)")
            res = phone_control.start_mirror()
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_screenshot":
            execution_logs.append("ACTION: Capturing phone screenshot")
            res = phone_control.screenshot_as_base64()
            execution_logs.append(f"RESULT: {res['message']}")
            if res["status"] == "success" and res.get("image_base64"):
                image_data = {
                    "filename": res.get("filename", ""),
                    "image_base64": res.get("image_base64", "")
                }

        elif act_type == "phone_tap":
            x = action.get("x", 0)
            y = action.get("y", 0)
            execution_logs.append(f"ACTION: Tapping phone at ({x}, {y})")
            res = phone_control.tap(x, y)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_swipe":
            x1, y1 = action.get("x1", 0), action.get("y1", 0)
            x2, y2 = action.get("x2", 0), action.get("y2", 0)
            duration_ms = int(action.get("duration_ms", 300))
            execution_logs.append(f"ACTION: Swiping phone from ({x1},{y1}) to ({x2},{y2})")
            res = phone_control.swipe(x1, y1, x2, y2, duration_ms)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_text":
            text = action.get("text", "")
            execution_logs.append("ACTION: Typing text on phone")
            res = phone_control.input_text(text)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_key":
            key = action.get("key", "")
            execution_logs.append(f"ACTION: Sending key '{key}' to phone")
            res = phone_control.press_key(key)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_launch_app":
            package = action.get("package", "")
            execution_logs.append(f"ACTION: Launching app '{package}' on phone")
            res = phone_control.launch_app(package)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_unlock":
            pin = action.get("pin")
            execution_logs.append("ACTION: Unlocking phone")
            res = phone_control.unlock_phone(pin)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "phone_test_pin_tap":
            digit = str(action.get("digit", ""))
            execution_logs.append(f"ACTION: Test-tapping digit '{digit}' on phone PIN pad")
            res = phone_control.test_pin_digit_tap(digit)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "add_whatsapp_contact":
            name = action.get("name", "")
            phone = action.get("phone", "")
            execution_logs.append(f"ACTION: Saving WhatsApp contact '{name}' ({phone})")
            res = whatsapp_ops.add_contact(name, phone)
            execution_logs.append(f"RESULT: {res['message']}")
            if not speak_text:
                speak_text = res["message"]

        elif act_type == "ask_clarification":
            question = action.get("question", "What would you like me to do, sir?")
            context = action.get("context", "general")
            options = action.get("options", [])
            execution_logs.append(f"ACTION: Asking for clarification — {question}")
            # Store clarification data to return to frontend
            clarification_needed = {
                "question": question,
                "context": context,
                "options": options,
            }
            speak_text = question  # Jarvis speaks the question too

        elif act_type == "send_whatsapp":
            contact = action.get("contact", "")
            message = action.get("message", "")
            execution_logs.append(f"ACTION: Sending WhatsApp message to '{contact}' (desktop)")
            # Add progressive narration steps
            narration_steps.append(f"Right away, sir. Opening WhatsApp and searching for {contact}.")
            res = whatsapp_ops.send_whatsapp_message(contact, message)
            execution_logs.append(f"RESULT: {res['message']}")
            if res.get("status") == "success":
                narration_steps.append(f"Message sent to {contact} on WhatsApp, sir. Done.")
                speak_text = f"Done, sir. Message delivered to {contact} on WhatsApp."
            else:
                speak_text = res["message"]

        elif act_type == "send_whatsapp_phone":
            contact = action.get("contact", "")
            message = action.get("message", "")
            execution_logs.append(f"ACTION: Sending WhatsApp message to '{contact}' (phone)")
            narration_steps.append(f"On it, sir. Sending via your phone to {contact}.")
            res = whatsapp_ops.send_whatsapp_message_via_phone(contact, message)
            execution_logs.append(f"RESULT: {res['message']}")
            if res.get("status") == "success":
                narration_steps.append(f"Message sent to {contact} via your phone, sir.")
                speak_text = f"Done, sir. Message sent to {contact} from your phone."
            else:
                speak_text = res["message"]

        elif act_type == "code_audit":
            execution_logs.append("ACTION: Running complete read-only codebase self-audit")
            audit_res = code_core.audit_codebase()
            execution_logs.append(f"RESULT: Codebase audit finished. Health score: {audit_res['health_score']}% ({audit_res['issues_count']} issues found).")
            if audit_res["issues_count"] == 0:
                speak_text = f"Codebase audit complete, sir. All {audit_res['total_files_checked']} source files are completely healthy with zero syntax errors."
            else:
                speak_text = f"Audit complete, sir. I detected {audit_res['issues_count']} potential issues. I have not applied any modifications. You can review and approve fixes in the Code Core tab."

        elif act_type == "code_fix":
            target = action.get("target", "all")
            execution_logs.append(f"ACTION: Applying safe patch and validation to: {target}")
            if target in ["all", "errors", "issues"]:
                audit_res = code_core.audit_codebase()
                fixed_count = 0
                failed_count = 0
                for issue in audit_res.get("issues", []):
                    fpath = issue["file"]
                    try:
                        preview = code_core.preview_file_fix(fpath, issue.get("message", ""))
                    except code_core.NemotronUnavailableError as e:
                        failed_count += 1
                        execution_logs.append(f"RESULT: {fpath} skipped - Nemotron unavailable: {e}")
                        continue
                    if preview.get("status") == "success":
                        try:
                            app_res = code_core.apply_file_fix(fpath, preview["proposed_content"])
                        except code_core.NemotronUnavailableError as e:
                            failed_count += 1
                            execution_logs.append(f"RESULT: {fpath} skipped - Nemotron unavailable during repair: {e}")
                            continue
                        if app_res.get("status") == "success":
                            fixed_count += 1
                            execution_logs.append(f"RESULT: Repaired {fpath} with validation verified.")
                        else:
                            failed_count += 1
                    else:
                        failed_count += 1
                tail = f" {failed_count} could not be auto-fixed." if failed_count else ""
                speak_text = f"Self-repair complete, sir. Successfully fixed and validated {fixed_count} files with automatic rollback safety enabled.{tail}"
            else:
                preview = code_core.preview_file_fix(target, action.get("issue", ""))
                if preview.get("status") == "success":
                    app_res = code_core.apply_file_fix(target, preview["proposed_content"])
                    if app_res.get("status") == "success":
                        speak_text = f"File {target} has been successfully repaired and validated, sir."
                        execution_logs.append(f"RESULT: {app_res['message']}")
                    else:
                        speak_text = f"Could not safely apply fix to {target}. Automatic rollback was executed."
                        execution_logs.append(f"RESULT: {app_res['message']}")
                else:
                    speak_text = f"Could not generate patch for {target}: {preview.get('message')}"

        elif act_type == "code_test":
            execution_logs.append("ACTION: Executing comprehensive self-validation suite")
            audit_res = code_core.audit_codebase()
            if audit_res["status"] == "healthy":
                speak_text = "All system validation tests passed, sir. Python syntax, AST trees, and frontend builds are nominal."
            else:
                speak_text = f"Validation completed with warnings, sir. {audit_res['issues_count']} warnings detected."
            execution_logs.append(f"RESULT: Self-validation finished. Health Score: {audit_res['health_score']}%.")

        else:
            execution_logs.append(f"ACTION: Unknown command type \"{act_type}\"")
            execution_logs.append(
                f"RESULT: Skipped — no handler for \"{act_type}\".")
            if not speak_text:
                speak_text = (
                    "I understood the words, sir, but that particular trick "
                    "isn't wired up yet.")
    # Default fallback if no voice response was generated
    if not speak_text:
        speak_text = "I have completed your request, sir."

    # ── Human polish: make every reply sound like a real human butler ──
    # Facts (times, temps, paths, mail bodies) are preserved verbatim;
    # only the framing gets warmed up. Never breaks the reply.
    try:
        from backend.agent import human_replies as _hr
        # Smalltalk first (hi / thanks / morning…) — no tools needed.
        _small = _hr.smalltalk(req.prompt)
        # Last non-speak action decides the human category; its RESULT
        # message carries the facts. Gemini's speak is the personality.
        _gemini_speak = ""
        _last_tool = ""
        _last_result = ""
        try:
            for _a in (actions or []):
                if isinstance(_a, dict) and _a.get("type") == "speak" and not _gemini_speak:
                    _gemini_speak = str(_a.get("text", "") or "")
        except Exception:
            pass
        # Internal-only statuses must NEVER reach the spoken reply
        # (this is what once leaked "Memory stored (success)" into chat).
        _INTERNAL_RESULTS = ("memory stored", "memory store failed",
                             "memory saved", "action: skipping")
        try:
            for _line in reversed(execution_logs or []):
                if isinstance(_line, str) and _line.startswith("RESULT:"):
                    _cand = _line[len("RESULT:"):].strip()
                    if _cand.casefold().startswith(_INTERNAL_RESULTS):
                        continue
                    _last_result = _cand
                    break
        except Exception:
            pass
        try:
            for _a in reversed(actions or []):
                if isinstance(_a, dict) and _a.get("type") not in ("speak", "unknown"):
                    _last_tool = str(_a.get("type", "") or "")
                    break
        except Exception:
            pass
        if _small and not _last_tool:
            speak_text = _small
        elif clarification_needed:
            # Questions to the user stay exactly as asked (plus gentle frame).
            pass
        else:
            speak_text = _hr.humanize_normal(_last_tool, _gemini_speak or speak_text, _last_result or speak_text, req.prompt)
    except Exception:
        pass

    # Confirm freshly stored identity facts (once — never stacked twice).
    try:
        if _memory_note and _memory_note.casefold() not in (speak_text or "").casefold():
            speak_text = f"{_memory_note} {speak_text}".strip()
    except Exception:
        pass

    # Collect extra structured data for the frontend
    timer_data = None
    weather_data_out = None
    for action in actions:
        if isinstance(action, dict) and action.get("type") == "set_timer":
            try:
                timer_data = {
                    "seconds": int(action.get("seconds", 60)),
                    "label": action.get("label", "Timer")
                }
            except Exception:
                timer_data = {"seconds": 60, "label": "Timer"}
        if isinstance(action, dict) and action.get("type") == "weather":
            city = action.get("city", "London")
            # Already fetched above; grab from last weather result if available
        
    try:
        from backend.agent.lang_detect import detect_lang
        speak_lang = detect_lang(speak_text, req.prompt)
    except Exception:
        speak_lang = "en"
    return {
        "speak": speak_text,
        "speak_lang": speak_lang,
        "logs": execution_logs,
        "file_data": file_data,
        "refresh_files": refresh_files,
        "image_data": image_data,
        "timer_data": timer_data,
        "clarification_needed": clarification_needed,
        "narration_steps": narration_steps,
    }


# ── Gallery endpoints ─────────────────────────────────────────────────────────

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_DOC_EXTS = {".docx", ".pptx", ".ppt", ".xlsx", ".xls", ".pdf", ".csv", ".txt", ".md", ".html", ".htm", ".rtf"}

@app.get("/api/gallery")
def get_gallery():
    """Recursively scan work_files for images and documents, returning metadata
    for each file. Categorises into: pc_screenshot, phone, generated, document,
    other. Documents (docx/pptx/pdf/...) persist across restarts and always show."""
    work_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "work_files"))
    if not os.path.exists(work_dir):
        return {"images": []}

    items = []
    for root, dirs, files in os.walk(work_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            is_image = ext in _IMAGE_EXTS
            is_doc = ext in _DOC_EXTS
            if not is_image and not is_doc:
                continue
            full_path = os.path.join(root, fname)
            rel = os.path.relpath(full_path, work_dir).replace("\\", "/")
            size = 0
            mtime = 0
            try:
                st = os.stat(full_path)
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                pass

            # Categorise based on folder / filename prefix
            rel_lower = rel.lower()
            kind = "image" if is_image else "document"
            if not is_image:
                category = "document"
            elif rel_lower.startswith("phone/") or fname.startswith("phone_"):
                category = "phone"
            elif rel_lower.startswith("images/") or fname.startswith("gen_") or fname.startswith("image_"):
                category = "generated"
            elif rel_lower.startswith("screenshots/") or fname.startswith("screenshot_") or fname.startswith("screen_"):
                category = "pc_screenshot"
            else:
                category = "other"

            items.append({
                "filename": fname,
                "path": rel,
                "size": size,
                "mtime": mtime,
                "category": category,
                "kind": kind,
                "ext": ext.lstrip("."),
            })

    # Newest first
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"images": items}


@app.get("/api/files/serve")
def serve_work_file(path: str):
    """Serve a file from work_files by its relative path (safe — refuses path traversal)."""
    work_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "work_files"))
    full_path = os.path.abspath(os.path.join(work_dir, path))
    # Guard against path traversal
    if not full_path.startswith(work_dir + os.sep) and full_path != work_dir:
        raise HTTPException(status_code=403, detail="Access denied.")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found.")
    ext = os.path.splitext(full_path)[1].lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".rtf": "application/rtf",
    }
    media_type = mime_map.get(ext, "application/octet-stream")
    return FileResponse(full_path, media_type=media_type)


# ── Agent endpoints ───────────────────────────────────────────────────────
# Each task owns its state and tools. Sharing an Executor also shares its
# Playwright browser, which lets concurrent tasks corrupt each other.
agent_runs = {}


class AgentRunRequest(BaseModel):
    text: str
    apiKey: Optional[str] = None


@app.post("/api/agent/run")
async def agent_run(req: AgentRunRequest):
    """
    Real Agent Mode endpoint — SSE streaming.
    Runs the full AgentCore loop and emits live execution events to the frontend.
    Each SSE line: data: {json}\n\n
    """
    task = req.text.strip()
    if not task:
        raise HTTPException(status_code=400, detail="Task cannot be empty.")

    # Create a per-request event queue
    event_queue: asyncio.Queue = asyncio.Queue()
    state = TaskState()
    run_id = str(uuid.uuid4())
    core = AgentCore()
    agent_runs[run_id] = {"state": state, "core": core, "task": task}

    async def run_agent():
        """Run agent in background, putting results into the queue."""
        try:
            await event_queue.put({
                "type": "run_started", "message": "Agent run started", "icon": ">",
                "data": {"run_id": run_id}, "ts": __import__('time').time()
            })
            await core.process(task, state, event_queue)
        except Exception as e:
            await event_queue.put({
                "type": "error",
                "message": f"Agent error: {str(e)}",
                "icon": "✗",
                "data": {"error": str(e)},
                "ts": __import__('time').time()
            })
        finally:
            # A human-blocked run must remain addressable by /resume. Finished
            # runs are removed promptly and their browser is closed by AgentCore.
            if not state.waiting_for_user:
                agent_runs.pop(run_id, None)
            # Sentinel to signal end of stream
            await event_queue.put(None)

    async def event_generator():
        """Consume the event queue and yield SSE-formatted strings."""
        # Start the agent task
        agent_task = asyncio.create_task(run_agent())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield "data: " + json.dumps({"type": "error", "message": "Agent timed out", "icon": "✗"}) + "\n\n"
                    break

                if event is None:
                    # End of stream sentinel
                    yield "data: " + json.dumps({"type": "done", "message": "Stream complete"}) + "\n\n"
                    break

                yield "data: " + json.dumps(event) + "\n\n"
        finally:
            if not agent_task.done():
                agent_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/agent/execute")
async def agent_execute(req: dict):
    """Execute a natural language task through the agent core (non-streaming legacy)."""
    task = req.get("text", "")
    state = TaskState()
    result = await AgentCore().process(task, state)
    return {"status": result.get("status", "error"), "data": result}


@app.get("/api/agent/status")
async def agent_status(run_id: str = ""):
    """Get status for an active agent run."""
    run = agent_runs.get(run_id)
    state = run["state"] if run else TaskState()
    return {
        "run_id": run_id,
        "active": bool(run),
        "task": state.task,
        "completed_steps": state.completed_steps,
        "errors": state.errors,
        "retry_count": state.retry_count,
        "completion_status": state.completion_status
    }


@app.post("/api/agent/plan")
async def agent_plan(req: dict):
    """Generate a plan for a task."""
    task = req.get("text", "")
    state = TaskState()
    from backend.agent.planner import Planner
    planner = Planner()
    steps = planner.plan_task(task, state)
    return {"status": "success", "steps": [{"type": s.type, "description": s.description, "parameters": s.parameters} for s in steps], "task": task}


@app.post("/api/agent/resume")
async def agent_resume(req: dict):
    """Resume agent after human intervention."""
    run_id = req.get("run_id", "")
    run = agent_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="No paused agent run found for this run_id.")
    state = run["state"]
    if not state.waiting_for_user:
        raise HTTPException(status_code=409, detail="This agent run is not waiting for human intervention.")
    result = await run["core"].resume_after_human(state, req.get("resolution", {}))
    return {"status": "success", "run_id": run_id, "data": result}


@app.post("/api/agent/instruct")
async def agent_instruct(req: dict):
    """Send a new command to a running agent: related changes merge into
    the live plan (restart from the top); independent work is queued next.
    Interruptions ("stop", "cancel") halt the run."""
    from backend.agent.clarify import is_interruption
    run_id = req.get("run_id", "")
    text = (req.get("text", "") or "").strip()
    run = agent_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="No active agent run found for this run_id.")
    if not text:
        raise HTTPException(status_code=400, detail="Instruction text is empty.")
    core, state = run["core"], run["state"]
    if is_interruption(text):
        core.request_interrupt(f"User interruption: {text}")
        return {"status": "interrupted", "run_id": run_id,
                "speak": "Stopping, sir."}
    verdict = core.enqueue_instruction(text, getattr(state, "task", ""))
    return {"status": verdict["verdict"], "run_id": run_id,
            "speak": verdict["message"],
            "queued": list(getattr(state, "queued_tasks", []) or [])}


# ── Agent endpoints end ───────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
