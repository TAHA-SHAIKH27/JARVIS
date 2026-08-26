from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import asyncio
import json
import base64
import tempfile
import struct
import numpy as np
import wave
import io

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
)
from agent import get_gemini_actions, generate_image_huggingface, conversation_history, stream_chat_response, stream_gemini_actions, stream_image_analysis, stream_document_analysis
import document_intel
import google_oauth
import phone_control
import whatsapp_ops
import json

app = FastAPI(title="J.A.R.V.I.S. Core", description="API Service for Windows OS Automation")

# Configure CORS so our React frontend can make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins in local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    save_config({
        "gemini_api_key": req.gemini_api_key,
        "huggingface_api_key": req.huggingface_api_key,
        "gemini_project_id": req.gemini_project_id or "",
        "groq_api_key": req.groq_api_key or ""
    })
    return {"status": "success", "message": "Configuration saved."}


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

@app.get("/api/status")
def read_status():
    return {"status": "online", "system": "J.A.R.V.I.S.", "message": "All systems operational, sir."}


# ── Voice Command Endpoint (for native voice service) ──────────────────────
class VoiceCommandRequest(BaseModel):
    prompt: str


@app.post("/api/voice/command")
def voice_command(req: VoiceCommandRequest):
    """Endpoint for the native voice service to send recognized commands."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt")
    
    # Reuse the existing command processing logic
    # Create a mock CommandRequest and process it
    from agent import conversation_history
    command_req = CommandRequest(prompt=req.prompt.strip(), apiKey=None)
    return process_command(command_req)





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
    work_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "work_files"))
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
async def process_command(req: CommandRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Command prompt cannot be empty.")

    # Check for chat reset keywords
    prompt_lower = req.prompt.lower().strip()
    if prompt_lower in ["clear chat", "reset history", "forget everything", "clear memory", "reset"]:
        import agent
        agent.conversation_history.clear()
        return {
            "speak": "Memory banks cleared, sir. Starting fresh.",
            "logs": ["ACTION: Cleared conversation history"],
            "file_data": None,
            "refresh_files": False,
            "image_data": None
        }

    # Load config once
    config = load_config()
    api_key_to_use = req.apiKey or config.get("gemini_api_key")
    gemini_project_id = config.get("gemini_project_id", "")

    # Gather files context
    files_context = list_files()

    # Run blocking Gemini network call in a thread pool so we don't block the event loop
    loop = asyncio.get_event_loop()
    actions = await loop.run_in_executor(
        None, get_gemini_actions, req.prompt, api_key_to_use, files_context, gemini_project_id
    )
    
    execution_logs = []
    speak_text = ""
    file_data = None
    refresh_files = False
    image_data = None  # For generated images
    
    execution_logs.append(f"INPUT RECEIVED: \"{req.prompt}\"")
    
    for action in actions:
        act_type = action.get("type", "unknown")
        
        if act_type == "speak":
            speak_text = action.get("text", "")
            execution_logs.append(f"JARVIS: {speak_text}")

        elif act_type == "shutdown":
            delay = int(action.get("delay_seconds", 0))
            res = shutdown_pc(delay)
            execution_logs.append(f"ACTION: Shutdown initiated")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "restart":
            delay = int(action.get("delay_seconds", 0))
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
            city = action.get("city", "London")
            execution_logs.append(f"ACTION: Fetching weather for {city}")
            res = get_weather(city)
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual weather data (replaces any prior 'retrieving' placeholder)
            speak_text = res["message"]

        elif act_type == "datetime_info":
            res = get_datetime_info()
            execution_logs.append("ACTION: Getting date/time")
            execution_logs.append(f"RESULT: {res['message']}")
            # Always override with actual datetime data
            speak_text = res["message"]

        elif act_type == "open_url":
            url = action.get("url", "")
            res = open_url(url)
            execution_logs.append(f"ACTION: Opening URL {url}")
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "set_timer":
            seconds = int(action.get("seconds", 60))
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
            
            
        elif act_type == "open_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Opening application \"{app_name}\"")
            res = launch_any_app(app_name)
            execution_logs.append(f"RESULT: {res['message']}")
            
        elif act_type == "close_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Closing application \"{app_name}\"")
            res = close_application(app_name)
            execution_logs.append(f"RESULT: {res['message']}")

        elif act_type == "launch_app":
            app_name = action.get("app_name", "")
            execution_logs.append(f"ACTION: Launching application \"{app_name}\"")
            res = launch_any_app(app_name)
            execution_logs.append(f"RESULT: {res['message']}")
            
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
                
        elif act_type == "delete_file":
            filename = action.get("filename", "")
            execution_logs.append(f"ACTION: Deleting file \"{filename}\"")
            res = delete_file(filename)
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True
            
        elif act_type == "take_screenshot":
            execution_logs.append("ACTION: Taking screenshot")
            res = take_screenshot()
            execution_logs.append(f"RESULT: {res['message']}")
            refresh_files = True
            
        elif act_type == "show_stats":
            execution_logs.append("ACTION: Loading HUD diagnostics...")

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
            agent.conversation_history.clear()
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

        elif act_type == "send_whatsapp":
            contact = action.get("contact", "")
            message = action.get("message", "")
            execution_logs.append(f"ACTION: Sending WhatsApp message to '{contact}' (desktop)")
            res = whatsapp_ops.send_whatsapp_message(contact, message)
            execution_logs.append(f"RESULT: {res['message']}")
            if not speak_text:
                speak_text = res["message"]

        elif act_type == "send_whatsapp_phone":
            contact = action.get("contact", "")
            message = action.get("message", "")
            execution_logs.append(f"ACTION: Sending WhatsApp message to '{contact}' (phone)")
            res = whatsapp_ops.send_whatsapp_message_via_phone(contact, message)
            execution_logs.append(f"RESULT: {res['message']}")
            if not speak_text:
                speak_text = res["message"]

        else:
            execution_logs.append(f"ACTION: Unknown command type \"{act_type}\"")
            
    # Default fallback if no voice response was generated
    if not speak_text:
        speak_text = "I have completed your request, sir."

    # Collect extra structured data for the frontend
    timer_data = None
    weather_data_out = None
    for action in actions:
        if action.get("type") == "set_timer":
            timer_data = {
                "seconds": int(action.get("seconds", 60)),
                "label": action.get("label", "Timer")
            }
        if action.get("type") == "weather":
            city = action.get("city", "London")
            # Already fetched above; grab from last weather result if available
        
    return {
        "speak": speak_text,
        "logs": execution_logs,
        "file_data": file_data,
        "refresh_files": refresh_files,
        "image_data": image_data,
        "timer_data": timer_data,
    }

if __name__ == "__main__":
    import uvicorn
    import subprocess
    import os
    
    # Start ws-scrcpy in the background
    ws_scrcpy_dir = os.path.join(os.path.dirname(__file__), "ws-scrcpy")
    if os.path.exists(ws_scrcpy_dir):
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
                shell=True
            )
            print("Started ws-scrcpy on port 8080")
        except Exception as e:
            print(f"Failed to start ws-scrcpy: {e}")

    # Run server on port 8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
