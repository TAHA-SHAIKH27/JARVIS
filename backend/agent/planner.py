"""
Agent Planner — uses Gemini to convert a natural-language task into a
structured list of executable action dicts, each with:
  {
    "type":        "<action_type>",   # e.g. "open_app", "browser_search"
    "description": "<human label>",  # displayed in the live event feed
    ... task-specific params ...
  }
"""
import json
import re
import os
from typing import List, Dict, Any, Optional

from backend.agent.state import TaskState


# ── Prompt sent to the LLM ────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are the JARVIS Agent Planner. Convert the user's task into a JSON array of executable steps.

RULES:
1. Output ONLY a valid JSON array. No markdown fences, no explanation.
2. Each element is an action object with a "type" field and a "description" field.
3. Use the EXACT action types listed below — no invented types.
4. Be precise: include all required parameters for each action type.
5. Break complex tasks into the minimal necessary ordered steps.
6. For browser research tasks, plan: browser_search → multiple browser_navigate → browser_extract → summarize → create_docx
7. For app tasks, plan: open_app_wait → type_in_app (if needed) → verify_window
8. Always end with a "speak" action summarising the result.

AVAILABLE ACTION TYPES AND THEIR PARAMETERS:

// Desktop automation
{"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad", "description": "Open Notepad"}
{"type": "type_in_app",   "text": "Hello world",  "window_title": "Notepad", "description": "Type text in Notepad"}
{"type": "press_key",     "key": "ctrl+s",        "description": "Press Ctrl+S to save"}
{"type": "calculator_compute", "expression": "125 * 48", "expected": "6000", "description": "Calculate 125 × 48"}

// File system
{"type": "create_folder_verified", "path": "C:/Users/username/Desktop/FOLDER_NAME", "description": "Create folder on Desktop"}
{"type": "write_file_verified",    "path": "C:/full/path/file.txt", "content": "text", "description": "Create file"}
{"type": "verify_file",           "path": "C:/full/path/file.txt", "description": "Verify file exists"}
{"type": "create_docx",           "path": "C:/full/path/doc.docx", "title": "Title", "content": "body text with sources", "description": "Create Word document"}

// Browser (uses visible Playwright Chromium)
{"type": "browser_search",   "query": "National Science Day India", "description": "Search Google"}
{"type": "browser_navigate", "url": "https://example.com",          "description": "Navigate to page"}
{"type": "browser_extract",  "description": "Extract text from current page"}
{"type": "browser_get_title","description": "Get current page title"}

// System info
{"type": "open_app_wait", "app_name": "chrome", "window_title": "Chrome", "description": "Open Chrome"}

// Final response
{"type": "speak", "text": "Done, sir. Here are the results...", "description": "Final response"}

IMPORTANT NOTES:
- For Desktop paths: use the actual Windows user Desktop path. If unknown, use "C:/Users/user/Desktop/" as placeholder — the executor will resolve it.
- For Calculator: use type="calculator_compute" with the math expression as a string.
- For 'type in Notepad': first open_app_wait, then type_in_app.
- For browser research: do browser_search first, then multiple browser_navigate + browser_extract for each source, then create_docx.
- For 'Open Chrome and search': use browser_search (it opens the browser automatically).
- Keep "description" short — it shows in the UI live feed.
"""


def _call_gemini_for_plan(task: str, api_key: str) -> Optional[List[Dict[str, Any]]]:
    """Call the Gemini API to get a structured action plan."""
    import urllib.request
    import urllib.error
    import time
    import google_oauth

    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if not use_oauth and not api_key:
        return None

    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    base_url = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:generateContent"

    payload = {
        "system_instruction": {"parts": [{"text": PLANNER_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Task: {task}"}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
        }
    }

    headers = {"Content-Type": "application/json"}
    if use_oauth:
        headers["Authorization"] = f"Bearer {access_token}"

    for model in models:
        try:
            url = base_url.replace("__MODEL__", model)
            if not use_oauth:
                url += f"?key={api_key}"

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            text = (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
            )
            if not text:
                continue

            # Strip markdown fences if any
            text = re.sub(r"^```(?:json)?\s*", "", text.strip())
            text = re.sub(r"\s*```$", "", text.strip())

            actions = json.loads(text)
            if isinstance(actions, list):
                return actions

        except (urllib.error.HTTPError, json.JSONDecodeError, Exception):
            continue

    return None


def _resolve_desktop_path(path: str) -> str:
    """Replace placeholder desktop path with the actual one."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    path = path.replace("C:/Users/user/Desktop", desktop)
    path = path.replace("C:\\Users\\user\\Desktop", desktop)
    # Handle any generic user placeholder
    import re
    path = re.sub(r"C:[/\\]Users[/\\][^/\\]+[/\\]Desktop", desktop.replace("\\", "/"), path)
    return path


def _rule_based_plan(task: str) -> List[Dict[str, Any]]:
    """Simple rule-based fallback when no API key is available."""
    task_lower = task.lower()
    actions = []

    if "notepad" in task_lower and ("type" in task_lower or "write" in task_lower):
        text_match = re.search(r"['\"]([^'\"]+)['\"]", task)
        text = text_match.group(1) if text_match else task
        actions = [
            {"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad",
             "description": "Open Notepad"},
            {"type": "type_in_app", "text": text, "window_title": "Notepad",
             "description": f"Type: {text[:40]}"},
            {"type": "speak", "text": f"Notepad is open and I have typed the text, sir.",
             "description": "Done"},
        ]
    elif "calculator" in task_lower or "calc" in task_lower:
        expr_match = re.search(r"(\d[\d\s×*x\+\-÷/\.]+\d)", task)
        expr = expr_match.group(1).replace("×", "*").replace("÷", "/").replace("x", "*") if expr_match else ""
        actions = [
            {"type": "calculator_compute", "expression": expr, "expected": "",
             "description": f"Calculate {expr}"},
            {"type": "speak", "text": f"Calculation complete, sir.", "description": "Done"},
        ]
    elif "chrome" in task_lower or "search" in task_lower or "browser" in task_lower:
        query_match = re.search(r"(?:search for|google|find)\s+(.+)", task_lower)
        query = query_match.group(1).strip() if query_match else task
        actions = [
            {"type": "browser_search", "query": query, "description": f"Search: {query}"},
            {"type": "browser_get_title", "description": "Get page title"},
            {"type": "speak", "text": "Browser task complete, sir.", "description": "Done"},
        ]
    elif "folder" in task_lower or "directory" in task_lower:
        folder_match = re.search(r"(?:called|named)\s+([A-Za-z0-9_\-\.]+)", task)
        folder = folder_match.group(1) if folder_match else "NewFolder"
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        actions = [
            {"type": "create_folder_verified", "path": os.path.join(desktop, folder),
             "description": f"Create folder {folder}"},
            {"type": "speak", "text": f"Folder {folder} created on your Desktop, sir.",
             "description": "Done"},
        ]
    else:
        actions = [
            {"type": "speak", "text": f"I'll process your request: {task[:80]}", "description": "Processing"},
        ]

    return actions


class Planner:
    def plan_task(self, task: str, state: TaskState) -> List[Dict[str, Any]]:
        """Convert a natural language task into a structured action list via LLM."""
        state.task = task
        state.completed_steps = []
        state.current_step = 0
        state.retry_count = 0

        # Load API key
        api_key = ""
        try:
            import json as _json
            import os as _os
            cfg_path = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "..", "config.json"))
            if _os.path.exists(cfg_path):
                with open(cfg_path, "r") as f:
                    api_key = _json.load(f).get("gemini_api_key", "")
        except Exception:
            pass

        # Try LLM planning first
        actions = _call_gemini_for_plan(task, api_key)
        if actions:
            # Resolve any placeholder desktop paths
            for action in actions:
                for key in ("path", "save_path"):
                    if key in action and isinstance(action[key], str):
                        action[key] = _resolve_desktop_path(action[key])
            return actions

        # Fallback to rule-based
        return _rule_based_plan(task)