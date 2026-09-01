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
6. For browser research tasks, plan: browser_search → browser_extract → browser_navigate (to result URL) → browser_extract → create_docx
7. For app tasks, plan: open_app_wait → type_in_app (if needed) → verify_window
8. For file/folder creation: create_folder_verified/write_file_verified → verify_file
9. Always end with a "speak" action summarising the result.

AVAILABLE ACTION TYPES AND THEIR PARAMETERS:

// Desktop automation
{"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad", "description": "Open Notepad"}
{"type": "type_in_app",   "text": "Hello world",  "window_title": "Notepad", "description": "Type text in Notepad"}
{"type": "press_key",     "key": "ctrl+s",        "description": "Press Ctrl+S to save"}
{"type": "calculator_compute", "expression": "125 * 48", "expected": "6000", "description": "Calculate 125 × 48"}

// File system (VERIFIED versions - these check actual filesystem)
{"type": "create_folder_verified", "path": "C:/Users/username/Desktop/FOLDER_NAME", "description": "Create folder on Desktop"}
{"type": "write_file_verified",    "path": "C:/full/path/file.txt", "content": "text", "description": "Create file"}
{"type": "verify_file",           "path": "C:/full/path/file.txt", "description": "Verify file/folder exists"}
{"type": "create_docx",           "path": "C:/full/path/doc.docx", "title": "Title", "content": "body text with sources", "headings": ["Heading 1", "Heading 2"], "description": "Create Word document"}

// Browser (uses visible Playwright Chromium, headless=False)
{"type": "browser_search",   "query": "National Science Day India", "description": "Search Google"}
{"type": "browser_extract_search_results", "description": "Extract result links from search page"}
{"type": "browser_navigate", "url": "https://example.com",          "description": "Navigate to page"}
{"type": "browser_extract",  "description": "Extract text from current page"}
{"type": "browser_get_title","description": "Get current page title"}

// System info (legacy - prefer verified versions above)
{"type": "open_app_wait", "app_name": "chrome", "window_title": "Chrome", "description": "Open Chrome"}

// Final response
{"type": "speak", "text": "Done, sir. Here are the results...", "description": "Final response"}

IMPORTANT NOTES:
- For Desktop paths: use the actual Windows user Desktop path. If unknown, use "C:/Users/user/Desktop/" as placeholder — the executor will resolve it.
- For Calculator: use type="calculator_compute" with the math expression as a string. The agent will operate Windows Calculator and verify the displayed result.
- For 'type in Notepad': first open_app_wait, then type_in_app.
- For browser research: do browser_search first, then browser_extract_search_results to get result links, then browser_navigate to each result URL, then browser_extract for each source, then create_docx with collected content.
- For 'Open Chrome and search': use browser_search (it opens the browser automatically).
- Keep "description" short — it shows in the UI live feed.
- NEVER use vague descriptions like "open the requested application" — always specify exact app_name and window_title.
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
    elif "research" in task_lower and ("word" in task_lower or "document" in task_lower or "docx" in task_lower):
        # Research task - extract topic
        # Pattern: "research X and create word document" or "research X from multiple websites and create..."
        topic_match = re.search(r"research\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)", task_lower)
        if not topic_match:
            topic_match = re.search(r"research\s+(.+?)\s+(?:and|from|into|create)", task_lower)
        if not topic_match:
            topic_match = re.search(r"research\s+(.+)", task_lower)
        topic = topic_match.group(1).strip() if topic_match else task
        # Clean up topic
        topic = re.sub(r'\s+(and|from|into|create)\s+(word\s+)?(document|docx).*$', '', topic, flags=re.I).strip()
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        safe_topic = topic.replace(' ', '_')
        actions = [
            {"type": "browser_search", "query": topic, "description": f"Search for {topic}"},
            {"type": "browser_extract_search_results", "description": "Extract search result links"},
            {"type": "browser_navigate", "url": "", "description": "Navigate to first source"},
            {"type": "browser_extract", "description": "Extract from first source"},
            {"type": "browser_navigate", "url": "", "description": "Navigate to second source"},
            {"type": "browser_extract", "description": "Extract from second source"},
            {"type": "create_docx", "path": os.path.join(desktop, f"{safe_topic}_research.docx"),
             "title": f"Research: {topic}", "content": "", "headings": ["Overview", "Key Findings", "Sources"], "description": "Create research document"},
            {"type": "verify_file", "path": os.path.join(desktop, f"{safe_topic}_research.docx"),
             "description": "Verify document created"},
            {"type": "speak", "text": f"Research on {topic} complete and saved to Desktop, sir.", "description": "Done"},
        ]
    elif (("chrome" in task_lower or "search" in task_lower) and 
          ("word" in task_lower or "docx" in task_lower or "document" in task_lower)):
        # Search + create Word document (e.g., "search for X and create a Word document")
        # Extract query: look for "search for X" or "google X" pattern, stop at "and create" or "and calculate" or end
        query_match = re.search(r"(?:search for|google|find)\s+(.+?)(?:\s+(?:and|then)\s+(?:create|calculate)|$)", task_lower)
        query = query_match.group(1).strip() if query_match else task
        # Extract filename if specified
        filename_match = re.search(r"(?:named|called)\s+([^\s.]+)", task_lower)
        filename = filename_match.group(1).strip() if filename_match else query.replace(' ', '_')
        if not filename.endswith('.docx'):
            filename += '.docx'
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        actions = [
            {"type": "browser_search", "query": query, "description": f"Search for {query}"},
            {"type": "browser_extract_search_results", "description": "Extract search result links"},
            {"type": "browser_navigate", "url": "", "description": "Navigate to first source"},
            {"type": "browser_extract", "description": "Extract from first source"},
            {"type": "create_docx", "path": os.path.join(desktop, filename),
             "title": f"Report: {query}", "content": "", "headings": ["Findings", "Sources"], "description": "Create Word document"},
            {"type": "verify_file", "path": os.path.join(desktop, filename),
             "description": "Verify document created"},
            {"type": "speak", "text": f"Search complete and saved as {filename} on Desktop, sir.", "description": "Done"},
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