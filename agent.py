import os
import json
import re
import time
import urllib.request
import urllib.error
import base64
from datetime import datetime
from system_ops import list_files, read_file, write_file
import google_oauth

# Simple system commands keyword mapping for local offline fallback
OFFLINE_RESPONSES = {
    "hello": "Hello, sir. Systems are online and operating at peak efficiency. What can I do for you today?",
    "hi": "Hello, sir. I am at your disposal.",
    "how are you": "All metrics are stable, sir. My core processors are performing optimally. Thank you for asking.",
    "who are you": "I am J.A.R.V.I.S., your home automation and desktop digital assistant. I am designed to control systems, manage files, and keep you informed.",
    "status": "All systems nominal, sir. CPU, memory, and disk space are within safe operating limits.",
    "goodbye": "Goodbye, sir. Standing by on low power mode."
}

# ===== CONVERSATION HISTORY (in-memory, per-session) =====
# Stores the last N conversation messages to give Gemini context (5 turns = 10 messages)
MAX_HISTORY = 10
conversation_history = []  # list of {"role": "user"|"assistant", "text": str}


def add_to_history(role: str, text: str):
    """Add a message to conversation history, keeping it bounded to last 5 queries (10 messages)."""
    global conversation_history
    conversation_history.append({"role": role, "text": text})
    # Trim to last MAX_HISTORY entries
    if len(conversation_history) > MAX_HISTORY:
        conversation_history = conversation_history[-MAX_HISTORY:]


def get_history_text() -> str:
    """Format conversation history for the AI prompt."""
    if not conversation_history:
        return "No previous conversation."
    
    lines = []
    for entry in conversation_history:
        prefix = "User" if entry["role"] == "user" else "Jarvis"
        lines.append(f"{prefix}: {entry['text']}")
    return "\n".join(lines)


def parse_local_command(prompt: str) -> list:
    """Fallback rule-based command interpreter for offline/no-API-key mode."""
    prompt_clean = prompt.lower().strip()
    actions = []
    
    # Screenshot Command (PC display — phone screenshot requests are handled
    # in _parse_new_commands, checked below, so exclude anything mentioning "phone")
    if ("screenshot" in prompt_clean or "capture screen" in prompt_clean) and "phone" not in prompt_clean:
        actions.append({"type": "take_screenshot"})
        actions.append({"type": "speak", "text": "I have taken a screenshot of your display, sir. It is saved in the screenshots folder."})
        return actions

    # Try new capability patterns first
    new_cmd = _parse_new_commands(prompt)
    if new_cmd:
        return new_cmd

    # 2. System diagnostics health check
    if "health" in prompt_clean or "diagnose" in prompt_clean or "diagnostic" in prompt_clean or "pc working good" in prompt_clean:
        actions.append({"type": "check_pc_health"})
        actions.append({"type": "speak", "text": "Running hardware and connectivity diagnostics now, sir."})
        return actions

    # 3. System Stats
    if "system stats" in prompt_clean or "status" in prompt_clean or "hardware" in prompt_clean or "cpu" in prompt_clean:
        actions.append({"type": "speak", "text": "Displaying system diagnostics on your holographic HUD, sir. CPU and RAM usage look stable."})
        return actions

    # 4. Volume control
    if "volume up" in prompt_clean or "louder" in prompt_clean or "increase volume" in prompt_clean:
        actions.append({"type": "volume_up"})
        actions.append({"type": "speak", "text": "Increasing system volume, sir."})
        return actions
    if "volume down" in prompt_clean or "quieter" in prompt_clean or "decrease volume" in prompt_clean:
        actions.append({"type": "volume_down"})
        actions.append({"type": "speak", "text": "Decreasing system volume, sir."})
        return actions
    if "mute" in prompt_clean:
        actions.append({"type": "mute_volume"})
        actions.append({"type": "speak", "text": "Toggling volume mute, sir."})
        return actions

    # 5. Media controls
    if ("play" in prompt_clean and "pause" in prompt_clean) or "toggle media" in prompt_clean or "media play" in prompt_clean or "media pause" in prompt_clean:
        actions.append({"type": "play_pause"})
        actions.append({"type": "speak", "text": "Toggling playback, sir."})
        return actions
    if "next track" in prompt_clean or "skip song" in prompt_clean or "skip track" in prompt_clean:
        actions.append({"type": "next_track"})
        actions.append({"type": "speak", "text": "Skipping to the next track, sir."})
        return actions
    if "previous track" in prompt_clean or "prev track" in prompt_clean or "go back a track" in prompt_clean:
        actions.append({"type": "prev_track"})
        actions.append({"type": "speak", "text": "Playing the previous track, sir."})
        return actions

    # 6. Web Search
    search_match = re.search(r'(?:search for|google|search web for)\s+(.+)', prompt_clean)
    if search_match:
        query = search_match.group(1).strip()
        actions.append({"type": "search_web", "query": query})
        actions.append({"type": "speak", "text": f"Searching Google for {query}, sir."})
        return actions

    # 7. Folder Creation
    folder_match = re.search(r'(?:create|make)(?:\s+a)?\s+folder\s+(?:named|called)?\s*([a-zA-Z0-9_\-\.\s]+)', prompt_clean)
    if folder_match:
        folder_name = folder_match.group(1).strip()
        actions.append({"type": "create_folder", "folder_name": folder_name})
        actions.append({"type": "speak", "text": f"Creating the folder {folder_name} for you, sir."})
        return actions

    # 8. Word Document Creation
    word_match = re.search(r'(?:create|make|generate)(?:\s+a)?\s+(?:word document|document|word doc)\s+(?:named|called)?\s*([a-zA-Z0-9_\-\.\s]+)(?:\s+with|\s+containing)?\s*(.*)?', prompt_clean)
    if word_match:
        filename = word_match.group(1).strip()
        content = word_match.group(2).strip() if word_match.group(2) else "Generated by J.A.R.V.I.S."
        if not filename.endswith('.docx') and not filename.endswith('.doc'):
            filename += '.docx'
        actions.append({"type": "create_word_doc", "filename": filename, "content": content})
        actions.append({"type": "speak", "text": f"Generating the Word document {filename}, sir."})
        return actions

    # 9. File Operations (fallback for raw text file creation)
    write_match = re.search(r'(?:create|write|make)(?:\s+a)?\s+file\s+(?:named|called)?\s*([a-zA-Z0-9_\-\.]+)(?:\s+with|\s+containing|\s+to)?\s*(?:content|text)?\s*[\'"`]?([^\'"`]+)[\'"`]?', prompt_clean)
    if write_match:
        filename = write_match.group(1).strip()
        content = write_match.group(2).strip()
        content = re.sub(r'^(with|containing|text)\s+', '', content)
        actions.append({"type": "write_file", "filename": filename, "content": content})
        actions.append({"type": "speak", "text": f"I have written the specified contents to {filename}, sir."})
        return actions
        
    read_match = re.search(r'(?:read|view|show|print)\s+file\s+([a-zA-Z0-9_\-\.]+)', prompt_clean)
    if read_match:
        filename = read_match.group(1).strip()
        actions.append({"type": "read_file", "filename": filename})
        actions.append({"type": "speak", "text": f"Reading contents of {filename} now, sir."})
        return actions

    # Image generation (offline fallback)
    img_match = re.search(r'(?:generate|create|make|draw)(?:\s+an?)?\s+image\s+(?:of|about|for)?\s*(.+)', prompt_clean)
    if img_match:
        img_prompt = img_match.group(1).strip()
        actions.append({"type": "generate_image", "prompt": img_prompt})
        actions.append({"type": "speak", "text": f"Generating an image of {img_prompt} for you, sir."})
        return actions

    # Save image (offline fallback)
    save_match = re.search(r'(?:save|copy)\s+(?:this\s+|the\s+|last\s+)?image\s+(?:to\s+)?(?:(?:my\s+)?desktop\s+)?(?:as|named|called)?\s*([a-zA-Z0-9_\-\.\s]+)', prompt_clean)
    if save_match:
        save_name = save_match.group(1).strip()
        actions.append({"type": "save_image", "save_name": save_name, "destination": "desktop"})
        actions.append({"type": "speak", "text": f"Saving the image as {save_name} to your desktop, sir."})
        return actions

    # Launch app (offline fallback)
    launch_match = re.search(r'(?:launch|open|start|run)\s+(.+)', prompt_clean)
    if launch_match:
        app_name = launch_match.group(1).strip()
        actions.append({"type": "launch_app", "app_name": app_name})
        actions.append({"type": "speak", "text": f"Launching {app_name} for you, sir."})
        return actions

    # 10. Basic conversations matching
    for key, response in OFFLINE_RESPONSES.items():
        if key in prompt_clean:
            actions.append({"type": "speak", "text": response})
            return actions

    # Default reply if nothing matches
    actions.append({
        "type": "speak", 
        "text": "I'm sorry sir, I couldn't process that command locally. Please configure your Gemini API Key in the Settings HUD to give me full cognitive capabilities."
    })
    return actions


# ===== OFFLINE FALLBACKS FOR NEW CAPABILITIES =====

def _parse_new_commands(prompt: str) -> list:
    """Extended offline fallback for new capabilities."""
    prompt_clean = prompt.lower().strip()
    actions = []

    # --- Weather ---
    weather_match = re.search(r'(?:weather|temperature|forecast|how(?:\'s| is) the weather)(?:\s+in|\s+for|\s+at)?\s+([\w\s]+)', prompt_clean)
    if weather_match or 'weather' in prompt_clean:
        city = weather_match.group(1).strip() if weather_match else 'London'
        # Filter out common noise words
        city = re.sub(r'\b(today|now|currently|please|right now)\b', '', city, flags=re.I).strip()
        actions.append({"type": "weather", "city": city or "London"})
        actions.append({"type": "speak", "text": f"Fetching weather for {city}, sir."})
        return actions

    # --- Date/Time ---
    if any(x in prompt_clean for x in ['what time', 'what\'s the time', 'current time', 'what day', 'what\'s the date', 'current date', 'today\'s date']):
        actions.append({"type": "datetime_info"})
        actions.append({"type": "speak", "text": "Checking the chronometer, sir."})
        return actions

    # --- Battery ---
    if any(x in prompt_clean for x in ['battery', 'charge level', 'power level', 'battery life']):
        actions.append({"type": "battery"})
        actions.append({"type": "speak", "text": "Checking power cell status, sir."})
        return actions

    # --- Network ---
    if any(x in prompt_clean for x in ['ip address', 'my ip', 'network info', 'wifi', 'internet connection', 'am i connected', 'network status']):
        actions.append({"type": "network_info"})
        actions.append({"type": "speak", "text": "Scanning network interfaces, sir."})
        return actions

    # --- Shutdown ---
    if any(x in prompt_clean for x in ['shut down', 'shutdown', 'turn off the pc', 'power off']):
        delay_match = re.search(r'in\s+(\d+)\s*min', prompt_clean)
        delay = int(delay_match.group(1)) * 60 if delay_match else 0
        actions.append({"type": "shutdown", "delay_seconds": delay})
        actions.append({"type": "speak", "text": "Initiating shutdown sequence, sir." if not delay else f"PC will shut down in {delay//60} minutes, sir."})
        return actions

    # --- Restart ---
    if any(x in prompt_clean for x in ['restart', 'reboot', 'restart the pc']):
        delay_match = re.search(r'in\s+(\d+)\s*min', prompt_clean)
        delay = int(delay_match.group(1)) * 60 if delay_match else 0
        actions.append({"type": "restart", "delay_seconds": delay})
        actions.append({"type": "speak", "text": "Rebooting systems, sir."})
        return actions

    # --- Cancel shutdown ---
    if any(x in prompt_clean for x in ['cancel shutdown', 'abort shutdown', 'cancel restart']):
        actions.append({"type": "cancel_shutdown"})
        actions.append({"type": "speak", "text": "Shutdown aborted, sir."})
        return actions

    # --- Sleep ---
    if any(x in prompt_clean for x in ['sleep', 'hibernate', 'put pc to sleep', 'sleep mode']):
        actions.append({"type": "sleep"})
        actions.append({"type": "speak", "text": "Initiating sleep mode, sir. Good night."})
        return actions

    # --- Lock screen ---
    if any(x in prompt_clean for x in ['lock', 'lock screen', 'lock the screen', 'lock pc', 'lock computer']):
        actions.append({"type": "lock_screen"})
        actions.append({"type": "speak", "text": "Locking your workstation, sir."})
        return actions

    # --- Clipboard read ---
    if any(x in prompt_clean for x in ['clipboard', 'what\'s in my clipboard', 'read clipboard', 'show clipboard']):
        actions.append({"type": "clipboard_read"})
        actions.append({"type": "speak", "text": "Reading clipboard contents, sir."})
        return actions

    # --- Clipboard write ---
    clip_write = re.search(r'(?:copy|add to clipboard|write to clipboard)\s+(?:this\s+)?[:"]?(.+)', prompt_clean)
    if clip_write:
        text = clip_write.group(1).strip()
        actions.append({"type": "clipboard_write", "text": text})
        actions.append({"type": "speak", "text": "Copied to clipboard, sir."})
        return actions

    # --- Timer ---
    timer_match = re.search(r'(?:set(?:\s+a)?\s+timer|timer)(?:\s+for)?\s+(\d+)\s*(second|minute|hour|sec|min|hr)s?', prompt_clean)
    if timer_match:
        amount = int(timer_match.group(1))
        unit = timer_match.group(2)
        if unit in ('hour', 'hr'):
            seconds = amount * 3600
        elif unit in ('minute', 'min'):
            seconds = amount * 60
        else:
            seconds = amount
        actions.append({"type": "set_timer", "seconds": seconds, "label": "Timer"})
        actions.append({"type": "speak", "text": f"Timer set for {amount} {unit}{'s' if amount > 1 else ''}, sir."})
        return actions

    # --- Add note ---
    note_match = re.search(r'(?:add(?:\s+a)?\s+note|note(?:\s+that)?|remember(?:\s+that)?)\s*[:"]?\s*(.+)', prompt_clean)
    if note_match:
        text = note_match.group(1).strip()
        actions.append({"type": "add_note", "text": text})
        actions.append({"type": "speak", "text": "Note added, sir."})
        return actions

    # --- Add todo ---
    todo_match = re.search(r'(?:add(?:\s+a)?\s+todo|todo(?:\s+item)?|remind me to|task)\s*[:"]?\s*(.+)', prompt_clean)
    if todo_match:
        text = todo_match.group(1).strip()
        actions.append({"type": "add_todo", "text": text})
        actions.append({"type": "speak", "text": "Todo added, sir."})
        return actions

    # --- WhatsApp: save/remember a contact ---
    save_contact_match = re.search(
        r'(?:save|add|remember)\s+(?:contact\s+)?([a-zA-Z0-9_\-\s]+?)(?:\'s)?\s+(?:number|contact|whatsapp)?\s*(?:as|is|:)?\s*(\+\d[\d\s\-]{6,15})',
        prompt, re.I
    )
    if save_contact_match:
        name = save_contact_match.group(1).strip()
        phone = save_contact_match.group(2).strip()
        actions.append({"type": "add_whatsapp_contact", "name": name, "phone": phone})
        actions.append({"type": "speak", "text": f"Saved {name}'s number, sir. I'll remember it for WhatsApp."})
        return actions

    # --- WhatsApp ---
    wa_match = re.search(
        r'(?:send\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to|whatsapp|text)\s+([a-zA-Z0-9_\-\+\s]+?)\s+(?:saying|as|:|that says)\s+(.+)',
        prompt, re.I
    )
    if wa_match:
        contact = wa_match.group(1).strip()
        message = wa_match.group(2).strip()
        # Distinguish "message X on my phone" (route via ADB) from a plain
        # WhatsApp Desktop send. "phone" appearing in the contact chunk itself
        # (e.g. "text +919876543210") is a phone NUMBER, not this keyword —
        # only trust "phone" mentioned outside the captured contact/message.
        mentions_phone = bool(re.search(r'\bphone\b', prompt_clean)) and 'phone' not in contact.lower()
        if mentions_phone:
            contact_clean = re.sub(r'\s*\bon\s+(?:my\s+)?phone\b\s*', ' ', contact, flags=re.I).strip()
            actions.append({"type": "send_whatsapp_phone", "contact": contact_clean, "message": message})
            actions.append({"type": "speak", "text": f"Sending that WhatsApp message to {contact_clean} from your phone, sir."})
        else:
            actions.append({"type": "send_whatsapp", "contact": contact, "message": message})
            actions.append({"type": "speak", "text": f"Sending that WhatsApp message to {contact}, sir."})
        return actions

    # --- Phone Control (ADB / scrcpy) ---
    if any(x in prompt_clean for x in ['mirror my phone', 'mirror phone', 'screen mirror', 'cast my phone',
                                        'show my phone screen', 'phone mirror']):
        actions.append({"type": "phone_mirror"})
        actions.append({"type": "speak", "text": "Launching the phone mirror window now, sir."})
        return actions

    if any(x in prompt_clean for x in ['screenshot my phone', 'phone screenshot', 'capture phone screen',
                                        'screenshot the phone', "take a screenshot of my phone"]):
        actions.append({"type": "phone_screenshot"})
        actions.append({"type": "speak", "text": "Capturing your phone's screen, sir."})
        return actions

    if 'unlock' in prompt_clean and 'phone' in prompt_clean:
        pin_match = re.search(r'pin\s*(?:is|:)?\s*(\d{4,8})', prompt_clean)
        pin = pin_match.group(1) if pin_match else None
        action = {"type": "phone_unlock"}
        if pin:
            action["pin"] = pin
        actions.append(action)
        actions.append({"type": "speak", "text": "Unlocking your phone now, sir."})
        return actions

    test_tap_match = re.search(r'test\s*tap\s+(\d)\s+on\s+(?:the\s+)?(?:phone|pin\s*pad)', prompt_clean)
    if test_tap_match:
        digit = test_tap_match.group(1)
        actions.append({"type": "phone_test_pin_tap", "digit": digit})
        actions.append({"type": "speak", "text": f"Test-tapping digit {digit} on your phone's PIN pad, sir."})
        return actions

    if 'phone' in prompt_clean and any(x in prompt_clean for x in ['connected', 'devices', 'check connection', 'is my phone']):
        actions.append({"type": "phone_devices"})
        actions.append({"type": "speak", "text": "Checking connected Android devices, sir."})
        return actions

    phone_tap_match = re.search(r'tap\s+(\d+)[,\s]+(\d+)\s+on\s+(?:my\s+)?phone', prompt_clean)
    if phone_tap_match:
        x, y = int(phone_tap_match.group(1)), int(phone_tap_match.group(2))
        actions.append({"type": "phone_tap", "x": x, "y": y})
        actions.append({"type": "speak", "text": f"Tapping ({x}, {y}) on your phone, sir."})
        return actions

    phone_key_match = re.search(r'(?:press|send)\s+(back|home|enter|power|menu)\s+(?:button\s+)?on\s+(?:my\s+)?phone', prompt_clean)
    if phone_key_match:
        key = phone_key_match.group(1)
        actions.append({"type": "phone_key", "key": key})
        actions.append({"type": "speak", "text": f"Sending {key} to your phone, sir."})
        return actions

    phone_launch_match = re.search(r'(?:open|launch)\s+(.+?)\s+on\s+(?:my\s+)?phone', prompt_clean)
    if phone_launch_match:
        app_hint = phone_launch_match.group(1).strip()
        actions.append({"type": "speak", "text": f"I need the exact Android package name to launch {app_hint}, sir (e.g. com.whatsapp). Please provide it or use a Gemini-connected session."})
        return actions

    return []



def generate_image_huggingface(prompt: str, hf_api_key: str, save_name: str = "") -> dict:
    """Generate an image using HuggingFace Inference API and save it to work_files."""
    if not hf_api_key:
        return {"status": "error", "message": "No Hugging Face API key configured. Please add it in Settings."}
    
    # Use a fast, high-quality model
    model_id = "black-forest-labs/FLUX.1-schnell"
    url = f"https://api-inference.huggingface.co/models/{model_id}"
    
    payload = json.dumps({"inputs": prompt}).encode("utf-8")
    
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {hf_api_key}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            image_bytes = response.read()
            
            # Determine filename
            if not save_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_name = f"generated_{timestamp}.png"
            elif not save_name.endswith(('.png', '.jpg', '.jpeg')):
                save_name += ".png"
            
            # Save to work_files/images directory
            work_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "work_files"))
            img_dir = os.path.join(work_dir, "images")
            os.makedirs(img_dir, exist_ok=True)
            
            save_path = os.path.join(img_dir, save_name)
            with open(save_path, "wb") as f:
                f.write(image_bytes)
            
            # Return base64 for frontend preview
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            
            return {
                "status": "success",
                "message": f"Image generated and saved as images/{save_name}",
                "filename": f"images/{save_name}",
                "image_base64": b64_image
            }
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except:
            pass
        if e.code == 503:
            return {"status": "error", "message": "The image model is currently loading. Please try again in a moment, sir."}
        elif e.code == 401 or e.code == 403:
            return {"status": "error", "message": "Your Hugging Face API key appears to be invalid. Please check it in Settings."}
        return {"status": "error", "message": f"Image generation failed (HTTP {e.code}): {error_body[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Image generation failed: {str(e)}"}


# Models tried in priority order. If one is rate-limited (429) or unavailable
# (404 / 503), the next one is attempted automatically.
# List confirmed by querying the API key's available models.
_GEMINI_MODELS = [
    "gemini-2.0-flash",       # fastest + highest quality
    "gemini-1.5-flash",       # fast fallback
    "gemini-2.0-flash-lite",  # lightweight fallback
    "gemini-flash-latest",    # alias fallback
]


def _call_gemini(url: str, headers: dict, payload: dict, max_retries: int = 1, backoff_seconds: float = 3.0):
    """
    POST to the Gemini API with a small amount of resilience built in:
    on a 429 (rate limited) response, wait `backoff_seconds` and retry up
    to `max_retries` additional times before giving up. Any other HTTP
    error, or a 429 on the final attempt, is re-raised for the caller to
    turn into a user-facing message.
    """
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                attempt += 1
                time.sleep(backoff_seconds)
                continue
            raise


_GEMINI_WORKING_MODEL: str | None = None  # Cached last-working model for fast startup


def _call_gemini_with_fallback(base_url_template: str, headers_template: dict, payload: dict, api_key: str, use_oauth: bool):
    """
    Try each model in _GEMINI_MODELS in order. Skips a model on 429 (quota)
    or 404 (unavailable/deprecated) and moves to the next. Raises the last
    error if all models are exhausted.

    Caches the last working model so subsequent calls skip straight to it,
    eliminating redundant 404 round-trips each time JARVIS starts up.
    """
    global _GEMINI_WORKING_MODEL
    # Build ordered list: try last-known-good model first
    ordered = list(_GEMINI_MODELS)
    if _GEMINI_WORKING_MODEL and _GEMINI_WORKING_MODEL in ordered:
        ordered.remove(_GEMINI_WORKING_MODEL)
        ordered.insert(0, _GEMINI_WORKING_MODEL)

    last_error = None
    for model in ordered:
        try:
            if use_oauth:
                url = base_url_template.replace("__MODEL__", model)
                headers = headers_template.copy()
            else:
                url = base_url_template.replace("__MODEL__", model) + f"?key={api_key}"
                headers = headers_template.copy()
            result = _call_gemini(url, headers, payload, max_retries=1, backoff_seconds=2.0)
            _GEMINI_WORKING_MODEL = model  # Remember the winner
            return result, model
        except urllib.error.HTTPError as e:
            last_error = e
            # 429 = quota, 404 = model not found/deprecated, 503 = overloaded — try next
            if e.code in (429, 404, 503):
                continue
            # Any other error (400, 401, 403, etc.) is a hard stop
            raise
    raise last_error


def _describe_rate_limit(error_body: str) -> str:
    """Turn a Gemini 429 error body into a message that tells the user
    whether they're hitting a per-minute limit (wait seconds) or a
    per-day limit (wait hours), instead of one generic 'rate limited' line."""
    body_lower = (error_body or "").lower()
    if "perday" in body_lower or "per_day" in body_lower or "daily" in body_lower:
        return ("I've hit my daily Gemini quota, sir. That resets at midnight Pacific time "
                "(the free tier is capped per day) — I'll need to run offline or wait until "
                "then, unless you'd like to attach a billing account to lift the cap.")
    if "perminute" in body_lower or "per_minute" in body_lower:
        return ("I'm being rate-limited by Google on a per-minute basis, sir — I already retried "
                "once. Please wait about a minute before your next command.")
    return ("I'm being rate-limited by Google, sir. I retried automatically but it's still "
            "throttling requests — please wait a moment and try again.")


def get_gemini_actions(prompt: str, api_key: str, context: dict = None, project_id: str = "") -> list:
    """Use Gemini API to process natural language into system control actions, with conversation memory.

    Auth priority:
      1. Google OAuth (if a linked account / valid token is available)
      2. Raw Gemini API key
      3. Offline rule-based fallback
    """
    
    # Record user message in history
    add_to_history("user", prompt)

    # 1. Prefer OAuth if the user has linked a Google account
    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            # Token existed but couldn't be refreshed - fall through to API key/offline
            use_oauth = False

    if not use_oauth and not api_key:
        return parse_local_command(prompt)

    # Check if Gemini API key format is valid (only relevant when not using OAuth)
    # Google issues keys in two valid formats: the legacy "AIzaSy..." format
    # and the newer project-scoped "AQ...." format. Both are accepted.
    if not use_oauth:
        api_key_clean = api_key.strip()
        if not (api_key_clean.startswith("AIzaSy") or api_key_clean.startswith("AQ.")):
            warning_msg = "Sir, your Gemini API key appears to be invalid or incorrectly formatted (it should start with 'AIzaSy' or 'AQ.'). I will process your command offline using local pattern matching."
            add_to_history("assistant", warning_msg)
            return [
                {"type": "speak", "text": warning_msg},
                *parse_local_command(prompt)
            ]
        
    # Build conversation history context
    history_text = get_history_text()
    
    # Build prompt instructions with available system operations
    system_instruction = """
    You are J.A.R.V.I.S., a witty, respectful, and advanced AI assistant like the one from Iron Man.
    Your task is to analyze the user's natural language command and convert it into a list of actions to execute.
    You MUST output a valid JSON array of actions and NOTHING else. No markdown block wrapper, no explanations.
    
    CRITICAL RULES FOR SPEED AND CONTEXT:
    - You have CONVERSATION HISTORY below. Use it to understand follow-up commands!
    - If the user says something related to a previous command, use context to figure out what they mean.
    - Keep responses SHORT and snappy. Don't ask for clarification if context makes it obvious.
    - Be decisive. If you can reasonably infer what the user wants, DO IT.
    
    Available actions format:
    [
      {"type": "speak", "text": "Jarvis voice response - polite, British, calls user 'sir', concise"},

      // --- Apps & System ---
      {"type": "open_app", "app_name": "notepad"},
      {"type": "close_app", "app_name": "notepad"},
      {"type": "launch_app", "app_name": "exact app name like 'Visual Studio Code' or 'Spotify'"},
      {"type": "open_url", "url": "https://example.com"},
      {"type": "take_screenshot"},
      {"type": "show_stats"},
      {"type": "check_pc_health"},

      // --- Power & Security ---
      {"type": "shutdown", "delay_seconds": 0},
      {"type": "restart", "delay_seconds": 0},
      {"type": "cancel_shutdown"},
      {"type": "sleep"},
      {"type": "lock_screen"},

      // --- Volume & Media ---
      {"type": "volume_up"},
      {"type": "volume_down"},
      {"type": "mute_volume"},
      {"type": "play_pause"},
      {"type": "next_track"},
      {"type": "prev_track"},

      // --- Files & Workspace ---
      {"type": "write_file", "filename": "hello.txt", "content": "text to write"},
      {"type": "read_file", "filename": "hello.txt"},
      {"type": "delete_file", "filename": "hello.txt"},
      {"type": "create_folder", "folder_name": "folder name relative to workspace or specifying 'on Desktop'"},
      {"type": "create_word_doc", "filename": "report.docx", "content": "detailed document content text"},

      // --- Intelligence & Info ---
      {"type": "weather", "city": "London"},
      {"type": "datetime_info"},
      {"type": "battery"},
      {"type": "network_info"},
      {"type": "search_web", "query": "search term"},

      // --- Clipboard ---
      {"type": "clipboard_read"},
      {"type": "clipboard_write", "text": "text to copy"},

      // --- Timer ---
      {"type": "set_timer", "seconds": 300, "label": "Pasta timer"},

      // --- Notes & Todos (persistent panels in the UI) ---
      {"type": "add_note", "text": "note content here"},
      {"type": "add_todo", "text": "todo item here"},

      // --- Images ---
      {"type": "generate_image", "prompt": "detailed image description", "save_name": "optional_filename.png"},
      {"type": "save_image", "save_name": "filename", "destination": "desktop or workspace"},

      // --- Phone Control (ADB / scrcpy - requires a connected, USB-debugging-enabled Android phone) ---
      {"type": "phone_devices"},
      {"type": "phone_mirror"},
      {"type": "phone_screenshot"},
      {"type": "phone_tap", "x": 500, "y": 800},
      {"type": "phone_swipe", "x1": 500, "y1": 1500, "x2": 500, "y2": 500, "duration_ms": 300},
      {"type": "phone_text", "text": "text to type into the currently focused phone field"},
      {"type": "phone_key", "key": "back"},
      {"type": "phone_launch_app", "package": "com.whatsapp"},
      {"type": "phone_unlock", "pin": "optional PIN digits if the user gave one, omit field entirely if not"},
      {"type": "phone_test_pin_tap", "digit": "5"},

      // --- WhatsApp ---
      {"type": "add_whatsapp_contact", "name": "contact display name", "phone": "+countrycode number"},
      {"type": "send_whatsapp", "contact": "contact name or phone number with country code", "message": "message text to send"},
      {"type": "send_whatsapp_phone", "contact": "contact name or phone number with country code", "message": "message text to send"},

      // --- Memory ---
      {"type": "clear_history"}
    ]
    
    Rules:
    1. Always pick the most precise action. If user says "what time is it" use datetime_info. If they say "weather in Paris" use weather with city="Paris".
    2. ALWAYS include a 'speak' action so Jarvis responds verbally.
    3. For shutdown/restart/sleep: if user says "in X minutes", set delay_seconds = X*60.
    4. For timers: convert to seconds. "5 minutes" = 300 seconds. "1 hour" = 3600 seconds. Extract a sensible label.
    5. For notes: "add a note" or "remember that" -> add_note. For todos: "add todo" or "remind me to" -> add_todo.
    6. For weather: extract city name. If not specified, use "your location" as city (backend will handle it).
    7. For files: use clean filenames inside 'work_files'. Only use absolute paths if user says 'on Desktop'.
    8. Maintain Jarvis persona (British, witty, calls user 'sir'). Keep speak text SHORT (1-2 sentences max).
    9. For image generation: use generate_image with a detailed prompt.
    10. For launching apps: use launch_app. This searches Start Menu shortcuts and Program Files automatically.
    11. USE THE CONVERSATION HISTORY to understand context. Be smart about follow-ups.
    12. For "clear chat" or "forget everything": use clear_history.
    13. For URLs/websites: if user gives a domain or URL, use open_url. If they say "search for X", use search_web.
    14. For phone control: "mirror my phone" / "show my phone screen" -> phone_mirror (opens a live scrcpy window). "screenshot my phone" -> phone_screenshot. Touch input -> phone_tap/phone_swipe with pixel coordinates the user gives you. "type X on my phone" -> phone_text. "press back/home/enter on my phone" -> phone_key. "open <app> on my phone" -> phone_launch_app with the Android package name if you know it (e.g. com.whatsapp, com.spotify.music, com.google.android.youtube, com.instagram.android); if unsure, ask for the package name via speak instead of guessing wrong. "is my phone connected" -> phone_devices.
    15. For "unlock my phone" / "unlock phone": use phone_unlock. If the user includes a PIN in the same sentence (e.g. "unlock my phone with pin 1234" or "unlock my phone, pin is 8842"), extract just the digits into the "pin" field. If no PIN is mentioned, omit the "pin" field entirely — the backend will fall back to a saved default PIN (if configured) or a plain swipe-unlock.
    16. For "test tap X on phone" / "test tap X on the pin pad" (calibration only, X being a single digit 0-9): use phone_test_pin_tap with that digit — this just taps where that digit should be, without swiping or submitting a full PIN.
    17. For "send message to X saying/as Y" / "whatsapp X saying Y" / "text X on whatsapp: Y": use send_whatsapp with contact=X (name or phone number) and message=Y. If the user explicitly says "on my phone" / "from my phone" (e.g. "message X on my phone saying Y", "whatsapp X on my phone: Y"), use send_whatsapp_phone instead — same fields, but sent via the connected Android device over ADB rather than WhatsApp Desktop. Do NOT invent any other action type for WhatsApp.
    18. For "save/add/remember X's number as +91..." / "remember X is +91...": use add_whatsapp_contact with name=X and phone=the full number including country code. This saves the contact permanently so future send_whatsapp/send_whatsapp_phone calls can resolve X by name alone.
    
    CONVERSATION HISTORY (most recent messages):
    """ + history_text + """
    
    Current workspace files context:
    """ + json.dumps(context or {})

    # Use Gemini API (v1beta endpoint) with automatic model fallback.
    # Models are tried in order defined by _GEMINI_MODELS (see top of file).
    base_model_url = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:generateContent"

    if use_oauth:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        if project_id:
            headers["x-goog-user-project"] = project_id
    else:
        headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_instruction}\n\nUser request: {prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3
        }
    }
    
    try:
        res_data, used_model = _call_gemini_with_fallback(base_model_url, headers, payload, api_key, use_oauth)

        # Extract text content from Gemini's response
        text_response = res_data['candidates'][0]['content']['parts'][0]['text']

        # Parse the text response as JSON
        try:
            actions = json.loads(text_response.strip())
            if isinstance(actions, list):
                # Record Jarvis response in history
                for act in actions:
                    if act.get("type") == "speak":
                        add_to_history("assistant", act.get("text", ""))
                        break
                return actions
            elif isinstance(actions, dict) and "actions" in actions:
                result = actions["actions"]
                for act in result:
                    if act.get("type") == "speak":
                        add_to_history("assistant", act.get("text", ""))
                        break
                return result
            else:
                return [{"type": "speak", "text": "I parsed your query but couldn't structure the tasks, sir. Let me try again."}, {"type": "speak", "text": text_response}]
        except json.JSONDecodeError:
            # Fallback if AI didn't output strict JSON
            add_to_history("assistant", text_response)
            return [{"type": "speak", "text": text_response}]
                
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode('utf-8')
        except:
            pass
        print(f"Gemini API Error (HTTP {e.code}): {error_body[:300]}")
        if e.code == 400:
            # Check if it's an API key issue or a bad request
            if 'API_KEY_INVALID' in error_body or 'API key not valid' in error_body:
                msg = "Sir, your Gemini API Key appears to be invalid. Please reconfigure it in the settings dashboard."
            else:
                msg = f"The request was malformed, sir. Error: {error_body[:150]}"
        elif e.code == 403:
            if use_oauth:
                msg = "Sir, my linked Google account doesn't have permission to call the Generative Language API. Please check the project's API access and, if applicable, the configured project ID."
            else:
                msg = "Sir, your Gemini API Key does not have permission. Please check it in the settings dashboard."
        elif e.code == 401 and use_oauth:
            msg = "Sir, my Google OAuth session appears to have expired or been revoked. Please re-link the account in Settings."
        elif e.code == 429:
            msg = _describe_rate_limit(error_body)
        else:
            msg = f"Communication error with my neural processors (HTTP {e.code}), sir."
        return [{"type": "speak", "text": msg}]
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        msg = "I encountered a network issue communicating with my neural processors, sir. Please check your internet connection and API key."
        return [{"type": "speak", "text": msg}]


# ===== STREAMING CONVERSATIONAL CHAT =====
# Separate pipeline from get_gemini_actions(): that one always forces a JSON
# action array (right for "shutdown the pc"), this one is free-form plain
# text, streamed token-by-token (right for "explain how RAID works" or,
# soon, "what's in this photo?" / "summarize this PDF"). Shares the same
# conversation_history so context carries across both modes.

CHAT_SYSTEM_INSTRUCTION = (
    "You are J.A.R.V.I.S., a witty, respectful, advanced AI assistant like the one from Iron Man. "
    "Respond conversationally in plain text — no JSON, no action lists, no markdown code fences "
    "unless you are actually showing code. Keep the British, polite, 'sir'-calling persona. "
    "Use the conversation history below for context on follow-up questions."
)


def stream_chat_response(prompt: str, api_key: str, project_id: str = ""):
    """Generator that yields plain-text chunks of a conversational reply as
    they arrive from Gemini's streaming endpoint. Auth priority mirrors
    get_gemini_actions(): Google OAuth > Gemini API key > local error message
    (there is no offline fallback for free-form chat, unlike command mode)."""

    add_to_history("user", prompt)

    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if not use_oauth and not api_key:
        msg = "I need a Gemini API key or a linked Google account for free conversation, sir. Please configure one in Settings."
        add_to_history("assistant", msg)
        yield msg
        return

    if not use_oauth:
        api_key_clean = api_key.strip()
        if not (api_key_clean.startswith("AIzaSy") or api_key_clean.startswith("AQ.")):
            msg = "Sir, your Gemini API key appears to be invalid or incorrectly formatted (it should start with 'AIzaSy' or 'AQ.')."
            add_to_history("assistant", msg)
            yield msg
            return

    history_text = get_history_text()
    full_prompt = f"{CHAT_SYSTEM_INSTRUCTION}\n\nCONVERSATION HISTORY:\n{history_text}\n\nUser: {prompt}"

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.6}
    }

    base_url_template = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:streamGenerateContent?alt=sse"

    if use_oauth:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        if project_id:
            headers["x-goog-user-project"] = project_id
    else:
        headers = {"Content-Type": "application/json"}

    full_reply = ""
    last_error = None

    for model in _GEMINI_MODELS:
        url = base_url_template.replace("__MODEL__", model)
        if not use_oauth:
            url += f"&key={api_key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        parts = chunk["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    for part in parts:
                        text_piece = part.get("text", "")
                        if text_piece:
                            full_reply += text_piece
                            yield text_piece
            # Streamed successfully (even if the model returned nothing) - don't try other models.
            add_to_history("assistant", full_reply or "(no response)")
            return
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 404, 503) and not full_reply:
                continue  # quota/unavailable before anything streamed - try next model
            break
        except Exception as e:
            last_error = e
            break

    if not full_reply:
        if isinstance(last_error, urllib.error.HTTPError):
            if last_error.code == 429:
                msg = "I'm being rate-limited by Google right now, sir. Please wait a moment and try again."
            elif last_error.code in (401, 403):
                msg = "My credentials for the Generative Language API seem to be invalid or lack permission, sir."
            else:
                msg = f"Communication error with my neural processors (HTTP {last_error.code}), sir."
        else:
            msg = "I encountered a network issue communicating with my neural processors, sir."
        add_to_history("assistant", msg)
        yield {"type": "speak", "text": msg}


def extract_first_json_action(buffer: str):
    """Extract the first complete JSON object from a buffer string.
    Returns (action_dict, remaining_buffer) or (None, buffer) if no complete object found."""
    depth = 0
    in_string = False
    escape_next = False
    start = -1
    
    for i, char in enumerate(buffer):
        if not in_string:
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    json_str = buffer[start:i+1]
                    remaining = buffer[i+1:]
                    try:
                        action = json.loads(json_str)
                        return action, remaining
                    except json.JSONDecodeError:
                        return None, buffer
            elif char == '"' and not escape_next:
                in_string = True
            elif char == '\\' and in_string:
                escape_next = True
        elif char == '"' and not escape_next:
            in_string = False
        elif char == '\\' and in_string and not escape_next:
            escape_next = True
        else:
            escape_next = False
    
    return None, buffer


# ===== STREAMING COMMAND ACTIONS =====
# Streams JSON actions as they're parsed from Gemini's response,
# enabling immediate execution of actions without waiting for full response.

COMMAND_STREAM_SYSTEM_INSTRUCTION = """
You are J.A.R.V.I.S., a witty, respectful, and advanced AI assistant like the one from Iron Man.
Your task is to analyze the user's natural language command and convert it into a stream of actions to execute.
You MUST output a stream of JSON objects, one per line, each being a valid action.
Available actions are the same as in get_gemini_actions().

CRITICAL RULES FOR STREAMING:
- Output ONE JSON action per line, no other text
- Each line must be valid JSON
- Actions will be executed immediately as they arrive
- Always include a 'speak' action for verbal responses
- Be decisive - if you can reasonably infer what the user wants, DO IT
- Keep responses SHORT and snappy

Example output:
{"type": "action", "action": {"type": "launch_app", "app_name": "chrome"}}
{"type": "action", "action": {"type": "speak", "text": "Opening Chrome for you, sir."}}
{"type": "speak", "text": "Opening Chrome for you, sir."}
"""

def stream_gemini_actions(prompt: str, api_key: str, project_id: str = ""):
    """Generator that yields JSON action objects as they arrive from Gemini's streaming endpoint.
    Each yielded object is a complete action that can be executed immediately.
    Auth priority mirrors get_gemini_actions(): Google OAuth > Gemini API key > local error message."""
    
    add_to_history("user", prompt)

    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if not use_oauth and not api_key:
        msg = "I need a Gemini API key or a linked Google account for command execution, sir. Please configure one in Settings."
        add_to_history("assistant", msg)
        yield {"type": "speak", "text": msg}
        return

    if not use_oauth:
        api_key_clean = api_key.strip()
        if not (api_key_clean.startswith("AIzaSy") or api_key_clean.startswith("AQ.")):
            msg = "Sir, your Gemini API key appears to be invalid or incorrectly formatted (it should start with 'AIzaSy' or 'AQ.')."
            add_to_history("assistant", msg)
            yield {"type": "speak", "text": msg}
            return

    history_text = get_history_text()
    full_prompt = f"{COMMAND_STREAM_SYSTEM_INSTRUCTION}\n\nCONVERSATION HISTORY:\n{history_text}\n\nUser request: {prompt}"

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"
        }
    }

    base_url_template = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:streamGenerateContent?alt=sse"

    if use_oauth:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        if project_id:
            headers["x-goog-user-project"] = project_id
    else:
        headers = {"Content-Type": "application/json"}

    action_buffer = ""
    full_reply = ""
    last_error = None

    for model in _GEMINI_MODELS:
        url = base_url_template.replace("__MODEL__", model)
        if not use_oauth:
            url += f"&key={api_key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        parts = chunk["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    for part in parts:
                        text_piece = part.get("text", "")
                        if text_piece:
                            full_reply += text_piece
                            action_buffer += text_piece
                            
                            # Try to extract complete JSON actions from buffer
                            while True:
                                try:
                                    action, remaining = extract_first_json_action(action_buffer)
                                    if action is None:
                                        break
                                    action_buffer = remaining
                                    # Execute speak actions immediately
                                    if action.get("type") == "speak":
                                        add_to_history("assistant", action.get("text", ""))
                                    yield action
                                except (json.JSONDecodeError, ValueError):
                                    break
                # Streamed successfully
                add_to_history("assistant", full_reply or "(no response)")
                return
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 404, 503) and not action_buffer:
                continue  # quota/unavailable before anything streamed - try next model
            break
        except Exception as e:
            last_error = e
            break

    if not action_buffer and not full_reply:
        if isinstance(last_error, urllib.error.HTTPError):
            if last_error.code == 429:
                msg = "I'm being rate-limited by Google right now, sir. Please wait a moment and try again."
            elif last_error.code in (401, 403):
                msg = "My credentials for the Generative Language API seem to be invalid or lack permission, sir."
            else:
                msg = f"Communication error with my neural processors (HTTP {last_error.code}), sir."
        else:
            msg = "I encountered a network issue communicating with my neural processors, sir."
        add_to_history("assistant", msg)
        yield {"type": "speak", "text": msg}


# ===== IMAGE UNDERSTANDING =====
# Same streaming SSE mechanics as stream_chat_response(), but the request
# includes an inline_data image part alongside the text prompt. Gemini's
# multimodal models (2.5-flash, 2.0-flash) handle vision natively - no
# separate vision-specific model needed.

VISION_SYSTEM_INSTRUCTION = (
    "You are J.A.R.V.I.S., a witty, respectful, advanced AI assistant like the one from Iron Man. "
    "The user has shared an image and a question about it. Look at the image carefully and answer "
    "in plain conversational text - no JSON, no action lists. Keep the British, polite, "
    "'sir'-calling persona. Be specific about what you actually see."
)


def stream_image_analysis(image_base64: str, mime_type: str, prompt: str, api_key: str, project_id: str = ""):
    """Generator that yields plain-text chunks describing/answering questions
    about an uploaded image, streamed as they arrive from Gemini."""

    question = prompt.strip() or "Describe this image in detail, sir."
    add_to_history("user", f"[image attached] {question}")

    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if not use_oauth and not api_key:
        msg = "I need a Gemini API key or a linked Google account to look at images, sir. Please configure one in Settings."
        add_to_history("assistant", msg)
        yield msg
        return

    if not use_oauth:
        api_key_clean = api_key.strip()
        if not (api_key_clean.startswith("AIzaSy") or api_key_clean.startswith("AQ.")):
            msg = "Sir, your Gemini API key appears to be invalid or incorrectly formatted (it should start with 'AIzaSy' or 'AQ.')."
            add_to_history("assistant", msg)
            yield msg
            return

    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                {"text": f"{VISION_SYSTEM_INSTRUCTION}\n\nUser's question: {question}"}
            ]
        }],
        "generationConfig": {"temperature": 0.4}
    }

    base_url_template = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:streamGenerateContent?alt=sse"

    if use_oauth:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        if project_id:
            headers["x-goog-user-project"] = project_id
    else:
        headers = {"Content-Type": "application/json"}

    full_reply = ""
    last_error = None

    for model in _GEMINI_MODELS:
        url = base_url_template.replace("__MODEL__", model)
        if not use_oauth:
            url += f"&key={api_key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        parts = chunk["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    for part in parts:
                        text_piece = part.get("text", "")
                        if text_piece:
                            full_reply += text_piece
                            yield text_piece
            add_to_history("assistant", full_reply or "(no response)")
            return
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 404, 503) and not full_reply:
                continue
            break
        except Exception as e:
            last_error = e
            break

    if not full_reply:
        if isinstance(last_error, urllib.error.HTTPError):
            if last_error.code == 429:
                msg = "I'm being rate-limited by Google right now, sir. Please wait a moment and try again."
            elif last_error.code in (401, 403):
                msg = "My credentials for the Generative Language API seem to be invalid or lack permission, sir."
            elif last_error.code == 400:
                msg = "Sir, that image couldn't be processed - it may be too large or in an unsupported format."
            else:
                msg = f"Communication error with my neural processors (HTTP {last_error.code}), sir."
        else:
            msg = "I encountered a network issue analyzing that image, sir."
        add_to_history("assistant", msg)
        yield msg


# ===== DOCUMENT UNDERSTANDING =====
# Same streaming SSE mechanics again, but the "attachment" is extracted
# document text (from document_intel.py) inserted directly into the prompt
# rather than inline binary data. Works for summaries, Q&A, key-point
# extraction, study notes, etc. - all just different phrasing of `prompt`.

DOCUMENT_SYSTEM_INSTRUCTION = (
    "You are J.A.R.V.I.S., a witty, respectful, advanced AI assistant like the one from Iron Man. "
    "The user has shared a document. Base your answer ONLY on the document content provided below - "
    "if the answer isn't in the document, say so honestly rather than guessing or inventing details. "
    "Respond in plain conversational text, no JSON. Keep the British, polite, 'sir'-calling persona."
)


def stream_document_analysis(document_text: str, filename: str, prompt: str, api_key: str, project_id: str = ""):
    """Generator that yields plain-text chunks answering a question about
    (or summarizing) an uploaded document's extracted text."""

    question = prompt.strip() or "Summarize this document for me, sir, and note any key points."
    add_to_history("user", f"[document attached: {filename}] {question}")

    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if not use_oauth and not api_key:
        msg = "I need a Gemini API key or a linked Google account to read documents, sir. Please configure one in Settings."
        add_to_history("assistant", msg)
        yield msg
        return

    if not use_oauth:
        api_key_clean = api_key.strip()
        if not (api_key_clean.startswith("AIzaSy") or api_key_clean.startswith("AQ.")):
            msg = "Sir, your Gemini API key appears to be invalid or incorrectly formatted (it should start with 'AIzaSy' or 'AQ.')."
            add_to_history("assistant", msg)
            yield msg
            return

    full_prompt = (
        f"{DOCUMENT_SYSTEM_INSTRUCTION}\n\n"
        f"--- DOCUMENT: {filename} ---\n{document_text}\n--- END DOCUMENT ---\n\n"
        f"User's question: {question}"
    )

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }

    base_url_template = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:streamGenerateContent?alt=sse"

    if use_oauth:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        if project_id:
            headers["x-goog-user-project"] = project_id
    else:
        headers = {"Content-Type": "application/json"}

    full_reply = ""
    last_error = None

    for model in _GEMINI_MODELS:
        url = base_url_template.replace("__MODEL__", model)
        if not use_oauth:
            url += f"&key={api_key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        parts = chunk["candidates"][0]["content"]["parts"]
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    for part in parts:
                        text_piece = part.get("text", "")
                        if text_piece:
                            full_reply += text_piece
                            yield text_piece
            add_to_history("assistant", full_reply or "(no response)")
            return
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 404, 503) and not full_reply:
                continue
            break
        except Exception as e:
            last_error = e
            break

    if not full_reply:
        if isinstance(last_error, urllib.error.HTTPError):
            if last_error.code == 429:
                msg = "I'm being rate-limited by Google right now, sir. Please wait a moment and try again."
            elif last_error.code in (401, 403):
                msg = "My credentials for the Generative Language API seem to be invalid or lack permission, sir."
            elif last_error.code == 400:
                msg = "Sir, that document couldn't be processed - it may be too large for a single request."
            else:
                msg = f"Communication error with my neural processors (HTTP {last_error.code}), sir."
        else:
            msg = "I encountered a network issue analyzing that document, sir."
        add_to_history("assistant", msg)
        yield msg
