"""
Agent Planner — converts natural-language tasks into structured executable action plans.
Supports data passing through TaskState for browser research workflows.
"""
import json
import re
import os
from typing import List, Dict, Any, Optional

from backend.agent.state import TaskState, TaskType, ActionSpec, Plan, VerificationMethod


# ── Prompt sent to the LLM ────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are the JARVIS Agent Planner. Convert the user's task into a JSON array of executable steps.

RULES:
1. Output ONLY a valid JSON array. No markdown fences, no explanation.
2. Each element is an action object with these fields:
   - "type": action type (required)
   - "description": short human-readable description (required)
   - "expected_outcome": what should be true after this action (required)
   - "required_context_keys": state keys needed before this action (optional, default [])
   - "goal": the specific sub-goal this action achieves (optional)
   - "tool": the tool that executes this action (optional, auto-filled)
   - "expected_state": description of expected system state after action (optional)
   - "verification_method": how to verify - "uia", "browser_dom", "screenshot_vision", "file_system", "process_check", "ocr" (optional)
   - "fallback": fallback strategy if action fails (optional)
   - "max_attempts": maximum retry attempts (optional, default 3)
   - "confidence_threshold": minimum confidence for verification (optional, default 0.8)
3. Use the EXACT action types listed below — no invented types.
4. Be precise: include all required parameters for each action type.
5. Break complex tasks into the minimal necessary ordered steps.
6. For browser research tasks, plan: browser_search → (results auto-stored in state) → browser_navigate to each source → browser_extract → create_docx
7. For app tasks, plan: open_app_wait → type_in_app (if needed) → verify_window
8. For file/folder creation: create_folder_verified/write_file_verified → verify_file
9. Always end with a "speak" action summarising the result.
10. For multi-source research: browser_search stores results in state.search_results; subsequent browser_navigate actions should use URLs from those results.
11. For calculator tasks: calculator_compute with expression, then use collected_numbers from state if needed.

AVAILABLE ACTION TYPES AND THEIR PARAMETERS:

// Desktop automation
{"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad", "description": "Open Notepad", "expected_outcome": "Notepad application is running and visible", "required_context_keys": [], "goal": "Launch Notepad", "tool": "computer.open_app", "expected_state": "Notepad window visible and focused", "verification_method": "uia", "fallback": "retry_with_longer_timeout", "max_attempts": 3}
{"type": "type_in_app", "text": "Hello world", "window_title": "Notepad", "description": "Type text in Notepad", "expected_outcome": "The text 'Hello world' is typed into Notepad", "required_context_keys": [], "goal": "Enter text into Notepad", "tool": "computer.type_text", "expected_state": "Text appears in Notepad edit control", "verification_method": "uia", "fallback": "pyautogui_type", "max_attempts": 2}
{"type": "press_key", "key": "ctrl+s", "description": "Press Ctrl+S to save", "expected_outcome": "Save dialog is opened or file is saved", "required_context_keys": [], "goal": "Trigger save shortcut", "tool": "computer.press_key", "expected_state": "Save dialog visible", "verification_method": "uia", "fallback": "retry", "max_attempts": 2}
{"type": "calculator_compute", "expression": "125 * 48", "expected": "6000", "description": "Calculate 125 × 48", "expected_outcome": "Calculation result is computed", "required_context_keys": [], "goal": "Compute mathematical expression", "tool": "computer.calculator", "expected_state": "Calculator displays result 6000", "verification_method": "process_check", "fallback": "retry", "max_attempts": 3}

// General Windows UI automation. Use find_ui_element before click_ui whenever a label is available.
{"type": "inspect_ui", "target": "Settings", "description": "Inspect visible UI", "expected_outcome": "Matching UI controls are discovered", "required_context_keys": [], "goal": "Discover UI elements", "tool": "computer.inspect_ui", "expected_state": "UI elements list available", "verification_method": "uia", "fallback": "screenshot_vision", "max_attempts": 2}
{"type": "find_ui_element", "text": "Save", "description": "Find the Save button", "expected_outcome": "The requested control is located", "required_context_keys": [], "goal": "Locate Save button", "tool": "computer.find_element", "expected_state": "Save button element found with bounds", "verification_method": "uia", "fallback": "coordinate_click", "max_attempts": 3}
{"type": "click_ui", "text": "Save", "description": "Click Save", "expected_outcome": "The requested control is clicked", "required_context_keys": [], "goal": "Click Save button", "tool": "computer.click", "expected_state": "Save dialog opens", "verification_method": "uia", "fallback": "coordinate_click", "max_attempts": 3}
{"type": "type_ui", "text": "Hello", "description": "Type into the focused control", "expected_outcome": "Text is entered", "required_context_keys": [], "goal": "Type text into focused control", "tool": "computer.type_text", "expected_state": "Text appears in target control", "verification_method": "uia", "fallback": "pyautogui_type", "max_attempts": 2}
{"type": "screenshot_ui", "description": "Capture the current screen", "expected_outcome": "A screenshot file is saved", "required_context_keys": [], "goal": "Capture screen", "tool": "computer.screenshot", "expected_state": "Screenshot file exists", "verification_method": "file_system", "fallback": "retry", "max_attempts": 2}

// File system (VERIFIED versions - these check actual filesystem)
{"type": "create_folder_verified", "path": "C:/Users/username/Desktop/FOLDER_NAME", "description": "Create folder on Desktop", "expected_outcome": "Folder exists at the specified path", "required_context_keys": [], "goal": "Create folder", "tool": "filesystem.create_folder", "expected_state": "Folder exists on disk", "verification_method": "file_system", "fallback": "retry", "max_attempts": 2}
{"type": "write_file_verified", "path": "C:/full/path/file.txt", "content": "text", "description": "Create file", "expected_outcome": "File exists with the correct content", "required_context_keys": [], "goal": "Write file", "tool": "filesystem.write_file", "expected_state": "File exists with content", "verification_method": "file_system", "fallback": "retry", "max_attempts": 2}
{"type": "verify_file", "path": "C:/full/path/file.txt", "description": "Verify file/folder exists", "expected_outcome": "File presence is confirmed", "required_context_keys": [], "goal": "Verify file exists", "tool": "filesystem.verify_file", "expected_state": "File confirmed on disk", "verification_method": "file_system", "fallback": "retry", "max_attempts": 2}
{"type": "create_docx", "path": "C:/full/path/doc.docx", "title": "Title", "content": "body text with sources, markdown tables (| a | b |) and optional [CHART:bar] Title / label: value blocks are supported", "headings": ["Heading 1", "Heading 2"], "description": "Create Word document", "expected_outcome": "Word document is created", "required_context_keys": [], "goal": "Generate Word document", "tool": "office.create_docx", "expected_state": "DOCX file exists with content", "verification_method": "file_system", "fallback": "simplified_document", "max_attempts": 2}
{"type": "create_pptx", "path": "C:/full/path/deck.pptx", "title": "Deck Title", "slides": [{"title": "Slide 1 Title", "bullets": ["Point one", "Point two"], "table": [["Header", "Value"], ["A", "1"]], "chart": {"type": "bar", "title": "Chart", "labels": ["Jan", "Feb"], "values": [30, 60]}, "image_subject": "topic-specific visual subject (only where a picture genuinely supports the slide, max 2 slides)", "image_url": "https://.../relevant.jpg", "notes": "Speaker notes"}], "description": "Create PowerPoint presentation. Bullets must be concise (max 8 words each) - slides are never dumps of scraped webpage text. When the task involves research, JARVIS builds the deck from the analyzed findings automatically.", "expected_outcome": "PowerPoint presentation is created", "required_context_keys": [], "goal": "Generate PowerPoint", "tool": "office.create_pptx", "expected_state": "PPTX file exists with slides", "verification_method": "file_system", "fallback": "simplified_presentation", "max_attempts": 2}

// Browser (uses visible Playwright Chromium, headless=False)
// browser_search automatically extracts and stores results in state.search_results
// If Google blocks with CAPTCHA, browser_search automatically falls back to Bing — no special handling needed
{"type": "browser_search", "query": "National Science Day India", "description": "Search Google", "expected_outcome": "Search results are retrieved", "required_context_keys": [], "goal": "Search web for topic", "tool": "browser.search", "expected_state": "Search results page with results", "verification_method": "browser_dom", "fallback": "fallback_to_bing", "max_attempts": 3}
// browser_navigate: navigate to a URL (use from state.search_results)
{"type": "browser_navigate", "url": "https://example.com", "source_index": 0, "description": "Navigate to source 1", "expected_outcome": "Browser navigates to the specified URL", "required_context_keys": ["search_results"], "goal": "Open search result", "tool": "browser.navigate", "expected_state": "Target page loaded", "verification_method": "browser_dom", "fallback": "retry_navigation", "max_attempts": 3}
// browser_extract: extracts text from current page, stores in state.extracted_sources
{"type": "browser_extract", "description": "Extract text from current page", "expected_outcome": "Text is extracted from the page", "required_context_keys": ["current_page_url"], "goal": "Extract page content", "tool": "browser.extract", "expected_state": "Page text stored in state", "verification_method": "browser_dom", "fallback": "retry_extraction", "max_attempts": 2}
{"type": "browser_get_title", "description": "Get current page title", "expected_outcome": "Page title is retrieved", "required_context_keys": [], "goal": "Get page title", "tool": "browser.get_title", "expected_state": "Page title available", "verification_method": "browser_dom", "fallback": "retry", "max_attempts": 2}
{"type": "browser_click", "selector": "button[type=submit]", "expected_url_contains": "", "expected_text": "", "description": "Click a web control", "expected_outcome": "The requested web control changes the page as expected", "required_context_keys": [], "goal": "Click web element", "tool": "browser.click", "expected_state": "Page updated after click", "verification_method": "browser_dom", "fallback": "retry", "max_attempts": 2}
{"type": "browser_type", "selector": "input[name=q]", "text": "query", "description": "Fill a web form", "expected_outcome": "The form field contains the requested text", "required_context_keys": [], "goal": "Fill web form", "tool": "browser.type", "expected_state": "Form field populated", "verification_method": "browser_dom", "fallback": "retry", "max_attempts": 2}
{"type": "browser_new_tab", "description": "Open a new browser tab", "expected_outcome": "A new browser tab is available", "required_context_keys": [], "goal": "Open new tab", "tool": "browser.new_tab", "expected_state": "New tab active", "verification_method": "browser_dom", "fallback": "retry", "max_attempts": 2}
{"type": "report_page_finding", "query": "current Python release", "description": "Report an evidence-based finding from the page", "expected_outcome": "A finding from extracted page content is available", "required_context_keys": ["extracted_sources"], "goal": "Report finding from page", "tool": "browser.report_finding", "expected_state": "Finding available in state", "verification_method": "browser_dom", "fallback": "retry", "max_attempts": 2}

// System info
{"type": "open_app_wait", "app_name": "chrome", "window_title": "Chrome", "description": "Open Chrome", "expected_outcome": "Chrome browser is open", "required_context_keys": []}

// Final response
{"type": "speak", "text": "Done, sir. Here are the results...", "description": "Final response", "expected_outcome": "Response is spoken to the user", "required_context_keys": []}

IMPORTANT NOTES:
- For Desktop paths: use the actual Windows user Desktop path. If unknown, use "C:/Users/user/Desktop/" as placeholder — the executor will resolve it.
- For Calculator: use type="calculator_compute" with the math expression as a string.
- For 'type in Notepad': first open_app_wait, then type_in_app.
- For browser research: browser_search stores results in state. Then use browser_navigate with source_index to visit each result. Then browser_extract to collect content. Then create_docx with collected content from state.extracted_sources.
- For 'Open Chrome and search': use browser_search (it opens the browser automatically).
- Keep "description" short — it shows in the UI live feed.
- NEVER use vague descriptions like "open the requested application" — always specify exact app_name and window_title.
- The executor will automatically populate state.search_results from browser_search, and state.extracted_sources from browser_extract.
"""


GOAL_UNDERSTANDING_PROMPT = """You are the JARVIS Goal Analyzer. Analyze the user's request and extract:

1. The PRIMARY GOAL (what the user wants accomplished - the end state)
2. INFORMATION mentioned (facts, constraints, context)
3. INTERMEDIATE OPERATIONS needed
4. FINAL DELIVERABLES expected
5. TOOL INSTRUCTIONS (if user specifies a particular tool)
6. TASK TYPE classification
7. CONSTRAINTS (time, format, location, etc.)

Return a JSON object with these fields:
{
  "primary_goal": "clear description of desired end state",
  "information": ["list of facts/constraints mentioned"],
  "intermediate_operations": ["list of operations needed"],
  "final_deliverables": ["list of expected outputs"],
  "tool_instructions": ["any specific tools mentioned"],
  "task_type": "simple|sequential|research|research_calculation|research_document|multi_app|human_intervention",
  "constraints": {"key": "value"},
  "dependencies": [{"step": "description", "depends_on": ["previous step descriptions"]}]
}

Example:
User: "Research the history of Python programming language and create a Word document with findings from at least 3 sources"

Output:
{
  "primary_goal": "Create a Word document containing researched history of Python from 3+ sources",
  "information": ["topic: Python programming language history"],
  "intermediate_operations": ["search for Python history", "visit 3+ sources", "extract content", "create document"],
  "final_deliverables": ["Word document (.docx) on Desktop with research findings"],
  "tool_instructions": [],
  "task_type": "research_document",
  "constraints": {"min_sources": 3, "output_format": "docx", "output_location": "Desktop"},
  "dependencies": [
    {"step": "search for Python history", "depends_on": []},
    {"step": "visit source 1", "depends_on": ["search for Python history"]},
    {"step": "extract source 1", "depends_on": ["visit source 1"]},
    {"step": "visit source 2", "depends_on": ["search for Python history"]},
    {"step": "extract source 2", "depends_on": ["visit source 2"]},
    {"step": "visit source 3", "depends_on": ["search for Python history"]},
    {"step": "extract source 3", "depends_on": ["visit source 3"]},
    {"step": "create document", "depends_on": ["extract source 1", "extract source 2", "extract source 3"]}
  ]
}"""


def _load_all_llm_configs() -> dict:
    """Load all API keys and model configurations from config.json and environment."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "config.json"),
        os.path.join(base_dir, "..", "config.json"),
        os.path.join(base_dir, "..", "..", "config.json"),
        os.path.join(base_dir, "..", "..", "..", "config.json"),
        os.path.join(os.getcwd(), "config.json")
    ]
    cfg = {}
    for cfg_path in candidates:
        resolved = os.path.abspath(cfg_path)
        if os.path.isfile(resolved):
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg:
                        break
            except Exception:
                pass

    return {
        "gemini_api_key": cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", ""),
        "nvidia_api_key": cfg.get("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY", ""),
        "nvidia_model": cfg.get("nvidia_model") or "meta/llama-3.3-70b-instruct",
        "groq_api_key": cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", ""),
        "openai_api_key": cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", ""),
    }


def _load_config_gemini_api_key() -> str:
    """Load Gemini API key from config.json or environment."""
    return _load_all_llm_configs().get("gemini_api_key", "")


def _clean_json_response(text: str) -> Optional[Any]:
    """Strip markdown formatting and parse JSON."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # If wrapped in extra text, try finding JSON bracket array or object
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    arr_match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except Exception:
            pass

    obj_match = re.search(r"\{\s*\".*\"\s*:.*\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except Exception:
            pass

    return None


def _call_gemini_for_plan(task: str, api_key: str, system_prompt: str) -> Optional[List[Dict[str, Any]]]:
    """Call LLM (Gemini, NVIDIA NIM, Groq, or OpenAI) to get a structured action plan."""
    import urllib.request
    import urllib.error
    import google_oauth

    configs = _load_all_llm_configs()
    if not api_key:
        api_key = configs.get("gemini_api_key", "")

    # 1. Try Gemini API / Google OAuth
    use_oauth = google_oauth.is_authenticated()
    access_token = ""
    if use_oauth:
        access_token = google_oauth.get_access_token()
        if not access_token:
            use_oauth = False

    if use_oauth or (api_key and not api_key.startswith("AQ.")):
        models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        base_url = "https://generativelanguage.googleapis.com/v1beta/models/__MODEL__:generateContent"

        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": f"Task: {task}"}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
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
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                text = (
                    data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                )
                parsed = _clean_json_response(text)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict) and "plan" in parsed:
                    return parsed["plan"]
            except Exception:
                continue

    # 2. Try NVIDIA NIM / Groq / OpenAI compatible endpoints if available
    nv_key = configs.get("nvidia_api_key") or configs.get("groq_api_key")
    if nv_key:
        endpoints = []
        if nv_key.startswith("nvapi-") or "nvidia" in configs.get("nvidia_model", ""):
            endpoints.append({
                "url": "https://integrate.api.nvidia.com/v1/chat/completions",
                "key": nv_key,
                "model": configs.get("nvidia_model") or "meta/llama-3.3-70b-instruct"
            })
        if configs.get("groq_api_key") and configs.get("groq_api_key").startswith("gsk_"):
            endpoints.append({
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "key": configs.get("groq_api_key"),
                "model": "llama-3.3-70b-versatile"
            })

        for ep in endpoints:
            try:
                payload = {
                    "model": ep["model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Task: {task}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4096
                }
                headers = {
                    "Authorization": f"Bearer {ep['key']}",
                    "Content-Type": "application/json"
                }
                req = urllib.request.Request(
                    ep["url"],
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = _clean_json_response(content)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict) and "plan" in parsed:
                    return parsed["plan"]
            except Exception:
                continue

    return None


def _resolve_desktop_path(path: str) -> str:
    """Replace placeholder desktop path with the actual one."""
    from system_ops import get_desktop_path
    desktop = get_desktop_path()
    path = path.replace("C:/Users/user/Desktop", desktop)
    path = path.replace("C:\\Users\\user\\Desktop", desktop)
    # Handle any generic user placeholder
    path = re.sub(r"C:[/\\]Users[/\\][^/\\]+[/\\]Desktop", desktop.replace("\\", "/"), path)
    return path


def _extract_research_parameters(task: str) -> Dict[str, Any]:
    """
    Intelligently extract the research topic, target artifact format,
    number of websites/sources (M), exact slide/section count (N),
    and specific target domain from natural language user tasks.

    STRICT DISAMBIGUATION:
      N = slide / section / page count  -> matched ONLY against slide/section/page keywords
      M = source / website count        -> matched ONLY against website/source/article keywords
      They are parsed INDEPENDENTLY so they can NEVER be mixed up.
    """
    task_clean = task.strip()
    task_lower = task_clean.lower()

    word_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

    # ── M: Source / Website Count (ONLY website/source/article keywords) ──────
    num_sources = 3
    src_num_match = re.search(r"\b(\d+)\s+(?:websites?|sources?|sites?|links?|articles?)\b", task_lower)
    src_word_match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:websites?|sources?|sites?|links?|articles?)\b", task_lower)
    if src_num_match:
        num_sources = max(1, min(8, int(src_num_match.group(1))))
    elif src_word_match:
        num_sources = max(1, min(8, word_map.get(src_word_match.group(1), 3)))

    # 2. Output format
    has_pres_kw = bool(re.search(r"\b(powerpoint|pptx|presentation|slide\s*deck|slides|ppt)\b", task_lower))
    has_doc_kw = bool(re.search(r"\b(word|docx|document|doc|report)\b", task_lower))

    # 3. Topic extraction
    topic = ""

    # Pattern 1: Explicit topic/subject markers: "topic [is/of/on/:/about] <topic>"
    m = re.search(r"\b(?:topic|subject)(?:\s+(?:is|of|on|about)|:)?\s+([a-zA-Z0-9_\s\-\'\"]+?)(?:\s+(?:gather|collect|extract|find|from|and|with|into|using|on\s+desktop|save|\d+\s+web|\d+\s+source)|$)", task_lower)
    if m:
        candidate = m.group(1).strip()
        if len(candidate) >= 3:
            topic = candidate

    # Pattern 2: "on [the] <topic>" / "about [the] <topic>"
    if not topic:
        m = re.search(r"\b(?:about|on|regarding|concerning)\s+(?:the\s+)?([a-zA-Z0-9_\s\-\'\"]+?)(?:\s+(?:gather|collect|extract|find|from|and|with|into|using|in\s+\d+|save|\d+\s+web|\d+\s+source)|$)", task_lower)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 3:
                topic = candidate

    # Pattern 3: "create/make/generate a [ppt/doc] on/about/for <topic>"
    if not topic:
        m = re.search(r"\b(?:create|make|generate|build|prepare)\s+(?:a\s+)?(?:ppt|pptx|presentation|slides?|word\s+doc(?:ument)?|docx|document|report|file)\s+(?:on|about|for|of)?\s*(?!(?:from|on|at|to|for|of|and|with)\b)\s*([a-zA-Z][a-zA-Z0-9_\s\-\'\"]*?)(?:\s+(?:gather|collect|extract|and|with|using|\d+\s+web|\d+\s+source)|$)", task_lower)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 3:
                topic = candidate

    # Pattern 4: "research/search/gather info on/about <topic>"
    if not topic:
        m = re.search(r"\b(?:research|search(?:\s+for)?|gather\s+info(?:\s+on|\s+about)?|find\s+info(?:\s+on|\s+about)?|look\s+up)\s+(?:about|on|for)?\s*(?!(?:from|on|at|to|for|of|and|with)\b)\s*([a-zA-Z][a-zA-Z0-9_\s\-\'\"]*?)(?:\s+(?:and|into|to\s+create|make|with|\d+\s+web|\d+\s+source)|$)", task_lower)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 3:
                topic = candidate

    # Fallback to whole task if still empty
    if not topic:
        topic = task_clean

    # Clean noise prefixes & suffixes from the extracted topic
    noise_prefixes = [
        r"^(?:the\s+)?(?:topic|subject)(?:\s+(?:is|of|on|about)|:)?\s*",
        r"^(?:about|on|for|of|regarding|concerning|the|some|details\s+about|info\s+on)\s+",
        r"^(?:create|make|generate|build|write|prepare)\s+(?:a\s+)?(?:ppt|pptx|presentation|slides?|word\s+doc(?:ument)?|docx|document|report|file)\s+(?:on|about|for|of)?\s*",
        r"^(?:research|search(?:\s+for)?|gather\s+info(?:\s+on|\s+about)?|find\s+info(?:\s+on|\s+about)?|look\s+up)\s+",
    ]
    for np in noise_prefixes:
        topic = re.sub(np, "", topic, flags=re.I).strip()

    noise_suffixes = [
        r"\s+(?:gather|collect|extract|find)\s+info(?:rmation)?.*$",
        r"\s+(?:from|using|with|via|across)\s+\d+.*$",
        r"\s+(?:from|using|with|via|across)\s+(?:multiple|several|various|different|one|two|three|four|five|six|seven|eight|nine|ten)\s+.*$",
        r"\s+(?:from|using|with|via|across)\s+(?:websites?|sources?|pages?|sites?|articles?|links?).*$",
        r"\s+(?:and\s+)?(?:make|create|generate|save|build|write|prepare)\s+(?:a\s+)?(?:ppt|pptx|presentation|slides?|word\s+doc(?:ument)?|docx|document|report|file).*$",
        r"\s+into\s+(?:a\s+)?(?:ppt|pptx|presentation|slides?|word\s+doc(?:ument)?|docx|document|report|file).*$",
        r"\s+(?:on|to)\s+desktop.*$",
        r"\b\d+\s+(?:websites?|sources?|pages?|sites?)\b.*$",
        r"\s+(?:from|using|with|via|in|on|at|by|for|about|of)$",
    ]
    for ns in noise_suffixes:
        topic = re.sub(ns, "", topic, flags=re.I).strip()

    topic = re.sub(r"\s+(?:from|using|with|via|in|on|at|by|for|about|of)$", "", topic, flags=re.I).strip()
    topic = topic.strip(" \t\n\r\"'.,;:?!-_")

    # Guard against empty/trivial topics like single verbs or prepositions
    invalid_topics = {"create", "make", "generate", "build", "ppt", "pptx", "presentation",
                      "document", "word", "report", "file", "search", "research", "from",
                      "on", "about", "for", "the", "a", "an", "of", "and", "to", "in", "with"}
    if not topic or len(topic) < 3 or topic.lower() in invalid_topics:
        topic = "Research Topic"

    # ── N: Slide / Section / Page Count (ONLY slide/section/page keywords) ────
    target_slides = None
    slide_num_match = re.search(r"\b(\d+)\s*(?:slides?|sections?|pages?)\b", task_lower)
    slide_word_match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:slides?|sections?|pages?)\b", task_lower)
    if slide_num_match:
        target_slides = max(1, min(20, int(slide_num_match.group(1))))
    elif slide_word_match:
        target_slides = max(1, min(20, word_map.get(slide_word_match.group(1), 8)))

    # ── Target Domain: specific website restriction ───────────────────────────
    target_domain = None
    url_domain_match = re.search(r"(?:from|on|using|via)\s+(?:https?://)?([a-zA-Z0-9\-]+(?:\.[a-zA-Z]{2,})+)", task_lower)
    if url_domain_match:
        target_domain = url_domain_match.group(1).strip()
    else:
        known_sites = {
            "wikipedia": "wikipedia.org", "wiki": "wikipedia.org",
            "nasa": "nasa.gov", "bbc": "bbc.com", "cnn": "cnn.com",
            "britannica": "britannica.com", "imdb": "imdb.com",
            "youtube": "youtube.com", "github": "github.com",
            "stackoverflow": "stackoverflow.com", "nytimes": "nytimes.com",
            "reuters": "reuters.com", "nationalgeographic": "nationalgeographic.com",
            "nature": "nature.com", "sciencedirect": "sciencedirect.com",
        }
        for kw, domain in known_sites.items():
            if re.search(rf"\b{re.escape(kw)}\b", task_lower):
                target_domain = domain
                break

    return {
        "topic": topic,
        "num_sources": num_sources,        # M: website/source count (strictly separate)
        "target_slides": target_slides,    # N: slide/section count  (strictly separate)
        "target_domain": target_domain,    # specific website restriction (if any)
        "is_presentation": has_pres_kw and not has_doc_kw,
        "is_document": has_doc_kw or not has_pres_kw,
    }


def _rule_based_plan(task: str) -> List[Dict[str, Any]]:
    """Deterministic, robust fallback plan generator."""
    task_lower = task.lower().strip()
    actions = []
    from system_ops import get_desktop_path
    desktop = get_desktop_path()

    # An explicit URL is an instruction to navigate, never a search query.
    url_match = re.search(r"https?://[^\s\]\[\),]+", task, re.I)
    if url_match:
        url = url_match.group(0).rstrip(".,;:)")
        remainder = (task[:url_match.start()] + task[url_match.end():]).strip(" ,.-")
        question = re.sub(r"^(?:open\s+(?:chrome|browser)\s*,?\s*)?(?:go\s+to\s*)?", "", remainder, flags=re.I).strip()
        question = question or "Summarize the important information on this page"
        actions = [
            {"type": "browser_navigate", "url": url, "description": f"Open {url}"},
        ]
        if "download" in question.lower():
            actions.append({
                "type": "browser_click", "selector": "a:has-text('Downloads')",
                "expected_url_contains": "python.org/downloads", "description": "Open the Downloads section",
            })
        actions.extend([
            {"type": "browser_extract", "description": "Extract page content"},
            {"type": "report_page_finding", "query": question, "description": "Find the requested information"},
            {"type": "speak", "use_last_finding": True, "text": "Page finding complete.", "description": "Report verified finding"},
        ])
        return actions

    # 0. Safe visual/UI actions that do not need an LLM connection.
    if any(k in task_lower for k in ("screenshot", "capture screen", "capture the screen")):
        actions = [
            {"type": "screenshot_ui", "description": "Capture the current screen"},
            {"type": "speak", "text": "Screenshot captured and verified, sir.", "description": "Done"},
        ]

    elif ("click " in task_lower or "select " in task_lower or
          bool(re.search(r"\bpress\s+.+\s+button\b", task_lower))):
        match = re.search(r"(?:click|press|select)\s+(?:the\s+)?[\"']?(.+?)[\"']?(?:\s+(?:button|control|menu|option))?$", task, re.I)
        target = match.group(1).strip() if match else ""
        if target:
            actions = [
                {"type": "find_ui_element", "text": target, "description": f"Find UI control: {target}"},
                {"type": "click_ui", "text": target, "description": f"Click UI control: {target}"},
                {"type": "speak", "text": f"Clicked {target}, sir.", "description": "Done"},
            ]

    # 1. Research + Word Document / Docx / PowerPoint creation
    elif not actions:
        has_research_kw = any(k in task_lower for k in ["research", "search", "extract", "gather", "find", "collect", "browse", "website", "websites", "topic", "information"])
        has_doc_kw = any(k in task_lower for k in ["word", "docx", "document", "doc", "file", "report"])
        has_pres_kw = any(k in task_lower for k in ["powerpoint", "pptx", "presentation", "slide deck", "slides", "ppt"])

        if (has_research_kw and (has_doc_kw or has_pres_kw)) or has_doc_kw or has_pres_kw:
            params = _extract_research_parameters(task)
            topic = params["topic"]
            num_sources = params["num_sources"]          # M: source count
            target_slides = params["target_slides"]      # N: slide/section count
            target_domain = params["target_domain"]      # specific website if mentioned
            safe_topic = re.sub(r'[^\w\-_]', '_', topic)

            # Build search query — if user wants a specific domain, restrict to it
            search_query = f"site:{target_domain} {topic}" if target_domain else topic

            # Build EXACTLY M source navigation + extraction steps
            browser_steps = [{"type": "browser_search", "query": search_query, "description": f"Search web for {topic}"}]
            for i in range(num_sources):
                nav_desc = f"Visit source {i + 1}" + (f" on {target_domain}" if target_domain else "")
                browser_steps.append({"type": "browser_navigate", "source_index": i, "description": nav_desc})
                browser_steps.append({"type": "browser_extract", "description": f"Extract content from source {i + 1}"})

            if params["is_presentation"]:
                deck_path = os.path.join(desktop, f"{safe_topic}_presentation.pptx")
                slide_note = f" ({target_slides} slides)" if target_slides else ""
                actions = browser_steps + [
                    {"type": "create_pptx", "path": deck_path, "title": f"Presentation: {topic.title()}",
                     "target_slides": target_slides, "target_domain": target_domain,
                     "description": f"Generate PowerPoint{slide_note}: {safe_topic}_presentation.pptx",
                     "slides": [{"title": topic.title(), "bullets": ["Research findings synthesized automatically from extracted sources."]}],
                     "notes": "Generated by J.A.R.V.I.S. Agentic System"},
                    {"type": "verify_file", "path": deck_path, "description": "Verify presentation created"},
                    {"type": "speak", "text": f"Research on '{topic}' complete across {num_sources} sources, sir. Presentation saved to Desktop.", "description": "Done"}
                ]
            else:
                docx_path = os.path.join(desktop, f"{safe_topic}_report.docx")
                section_note = f" ({target_slides} sections)" if target_slides else ""
                actions = browser_steps + [
                    {"type": "create_docx", "path": docx_path, "title": f"Research Report: {topic.title()}",
                     "target_sections": target_slides, "target_domain": target_domain,
                     "content": "",
                     "headings": ["Executive Summary", "Introduction & Background", "Key Findings & Thematic Analysis",
                                  "Detailed Source Insights", "Cross-Source Comparative Analysis",
                                  "Conclusion & Implications", "References & Verified Sources"],
                     "description": f"Generate Word Document{section_note}: {safe_topic}_report.docx"},
                    {"type": "verify_file", "path": docx_path, "description": "Verify Word document created"},
                    {"type": "speak", "text": f"Research on '{topic}' complete across {num_sources} sources, sir. Word document saved to Desktop.", "description": "Done"}
                ]
        else:
            actions = _rule_based_non_research(task, task_lower, desktop)

    return actions


def _rule_based_non_research(task: str, task_lower: str, desktop: str) -> List[Dict[str, Any]]:
    """Offline plans for deterministic desktop, file, calculation, and browser tasks."""
    actions = []
    # 2. Notepad / Type text
    if "notepad" in task_lower and ("type" in task_lower or "write" in task_lower or "open" in task_lower):
        text_match = re.search(r"['\"]([^'\"]+)['\"]", task)
        text = text_match.group(1) if text_match else task
        return [
            {"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad", "description": "Open Notepad"},
            {"type": "type_in_app", "text": text, "window_title": "Notepad", "description": "Type text into Notepad"},
            {"type": "speak", "text": "Opened Notepad and typed your text, sir.", "description": "Done"}
        ]

    # 3. Create folder & nested files
    if "folder" in task_lower and ("create" in task_lower or "make" in task_lower):
        folder_match = re.search(r"(?:create|make)\s+(?:a\s+)?folder\s+(?:named|called)?\s*['\"]?([a-zA-Z0-9_\-\.\s]+)['\"]?", task_lower)
        folder_name = folder_match.group(1).strip() if folder_match else "NewFolder"
        folder_name = re.sub(r"\s+on\s+desktop.*$", "", folder_name)
        folder_path = os.path.join(desktop, folder_name)

        actions = [
            {"type": "create_folder_verified", "path": folder_path, "description": f"Create folder {folder_name}"},
            {"type": "verify_file", "path": folder_path, "description": "Verify folder created"}
        ]

        # Check if user also asked for files inside the folder
        file_match = re.search(r"(?:in|inside)\s+that\s+folder\s+(?:create|make|write)\s+(?:a\s+)?file\s+(?:named|called)?\s*['\"]?([a-zA-Z0-9_\-\.]+)['\"]?", task_lower)
        if file_match:
            file_name = file_match.group(1).strip()
            file_path = os.path.join(folder_path, file_name)
            actions.append({"type": "write_file_verified", "path": file_path, "content": "Created by J.A.R.V.I.S.", "description": f"Create file {file_name}"})
            actions.append({"type": "verify_file", "path": file_path, "description": f"Verify file {file_name}"})

        actions.append({"type": "speak", "text": f"Folder {folder_name} created on Desktop, sir.", "description": "Done"})

    # 4. Strict Calculator Match ONLY (requires explicit calc words or explicit arithmetic operators)
    elif (any(k in task_lower for k in ["calculator", "calc", "calculate", "compute", "math"]) or
          bool(re.search(r"\d+\s*[\+\-\*/×÷]\s*\d+", task))):
        expr_match = re.search(r"(\d[\d\s×*x\+\-÷/\.]+\d)", task)
        expr = expr_match.group(1).replace("×", "*").replace("÷", "/").replace("x", "*") if expr_match else task
        actions = [
            {"type": "calculator_compute", "expression": expr, "expected": "", "description": f"Calculate {expr}"},
            {"type": "speak", "text": "Calculation complete, sir.", "description": "Done"}
        ]

    # 5. Browser search / Chrome open
    elif any(k in task_lower for k in ["chrome", "search", "browser", "google", "website"]):
        query_match = re.search(r"(?:open\s+(?:chrome|browser|google)(?:\s+and)?\s+)?(?:search\s+(?:for|fr|about)?|google|find|browse|look\s+up)\s+(.+)", task_lower)
        query = query_match.group(1).strip() if query_match else task
        query = re.sub(r"^(?:for|fr|about|on|the)\s+", "", query, flags=re.I).strip()
        actions = [
            {"type": "browser_search", "query": query, "description": f"Search web: {query}"},
            {"type": "browser_get_title", "description": "Get page title"},
            {"type": "speak", "text": f"Search completed for {query}, sir.", "description": "Done"}
        ]

    else:
        actions = [
            {"type": "speak", "text": f"Processing your request, sir: {task[:80]}", "description": "Processing"}
        ]

    return actions


def _parse_llm_actions_to_specs(actions: List[Dict[str, Any]], state: TaskState) -> List[ActionSpec]:
    """Convert raw LLM actions to structured ActionSpec with dependencies."""
    specs = []
    for i, action in enumerate(actions):
        atype = action.get("type", "")
        description = action.get("description", atype)
        expected_outcome = action.get("expected_outcome", f"Action {atype} completed successfully")
        required_context_keys = action.get("required_context_keys", [])
        
        # Determine dependencies based on action type and order
        depends_on = []
        produces = []
        consumes = []
        
        # Structured planning fields
        goal = action.get("goal", description)
        tool = action.get("tool", _action_type_to_tool(atype))
        expected_state = action.get("expected_state", expected_outcome)
        verification_method = action.get("verification_method", _default_verification_method(atype))
        fallback = action.get("fallback", _default_fallback(atype))
        max_attempts = action.get("max_attempts", 3)
        confidence_threshold = action.get("confidence_threshold", 0.8)
        
        if atype == "browser_search":
            produces = ["search_results", "current_page_url", "current_page_title"]
        elif atype == "browser_navigate":
            consumes = ["search_results"]
            produces = ["current_page_url", "current_page_title"]
            # Depends on previous browser_search or browser_navigate
            for j in range(i-1, -1, -1):
                if specs[j].type in ("browser_search", "browser_navigate"):
                    depends_on.append(j)
                    break
        elif atype == "browser_extract":
            consumes = ["current_page_url", "current_page_title"]
            produces = ["extracted_sources"]
            # Depends on previous browser_navigate
            for j in range(i-1, -1, -1):
                if specs[j].type == "browser_navigate":
                    depends_on.append(j)
                    break
        elif atype == "create_docx":
            consumes = ["extracted_sources"]
            produces = ["created_document_path"]
            # Depends on all browser_extract actions
            for j in range(i):
                if specs[j].type == "browser_extract":
                    depends_on.append(j)
        elif atype == "create_pptx":
            consumes = ["extracted_sources"]
            produces = ["created_presentation_path"]
        elif atype == "calculator_compute":
            produces = ["collected_numbers"]
        elif atype == "open_app_wait":
            produces = ["active_app", "active_window"]
        elif atype == "inspect_ui":
            produces = ["ui_elements"]
        elif atype == "find_ui_element":
            produces = ["ui_target"]
        elif atype == "click_ui":
            consumes = ["ui_target"]
            for j in range(i - 1, -1, -1):
                if specs[j].type == "find_ui_element":
                    depends_on.append(j)
                    break
        elif atype == "type_ui":
            for j in range(i - 1, -1, -1):
                if specs[j].type in ("click_ui", "find_ui_element", "open_app_wait"):
                    depends_on.append(j)
                    break
        elif atype == "type_in_app":
            consumes = ["active_window"]
            # Depends on open_app_wait
            for j in range(i-1, -1, -1):
                if specs[j].type == "open_app_wait":
                    depends_on.append(j)
                    break
        elif atype == "verify_file":
            consumes = ["created_document_path"]
        elif atype == "browser_get_title":
            produces = ["current_page_title"]
        elif atype == "report_page_finding":
            consumes = ["extracted_sources"]
            for j in range(i - 1, -1, -1):
                if specs[j].type == "browser_extract":
                    depends_on.append(j)
                    break
        elif atype in ("browser_click", "browser_type", "browser_new_tab"):
            # Browser interactions need an already-open browser/page.
            for j in range(i - 1, -1, -1):
                if specs[j].type in ("browser_search", "browser_navigate", "browser_click", "browser_new_tab"):
                    depends_on.append(j)
                    break
        
        # Extract parameters (exclude type and description etc)
        params = {k: v for k, v in action.items() if k not in ("type", "description", "expected_outcome", "required_context_keys", "goal", "tool", "expected_state", "verification_method", "fallback", "max_attempts", "confidence_threshold")}
        
        spec = ActionSpec(
            type=atype,
            description=description,
            parameters=params,
            depends_on=depends_on,
            produces=produces,
            consumes=consumes,
            verification={},  # Will be filled by validator
            expected_outcome=expected_outcome,
            required_context_keys=required_context_keys,
            is_critical=atype != "speak",
            # Structured planning fields
            goal=goal,
            tool=tool,
            expected_state=expected_state,
            verification_method=verification_method,
            fallback=fallback,
            max_attempts=max_attempts,
            confidence_threshold=confidence_threshold,
        )
        specs.append(spec)
    
    return specs


def _action_type_to_tool(action_type: str) -> str:
    """Map action type to tool name."""
    tool_map = {
        "open_app_wait": "computer.open_app",
        "type_in_app": "computer.type_text",
        "press_key": "computer.press_key",
        "calculator_compute": "computer.calculator",
        "inspect_ui": "computer.inspect_ui",
        "find_ui_element": "computer.find_element",
        "click_ui": "computer.click",
        "type_ui": "computer.type_text",
        "screenshot_ui": "computer.screenshot",
        "create_folder_verified": "filesystem.create_folder",
        "write_file_verified": "filesystem.write_file",
        "verify_file": "filesystem.verify_file",
        "create_docx": "office.create_docx",
        "create_pptx": "office.create_pptx",
        "browser_search": "browser.search",
        "browser_navigate": "browser.navigate",
        "browser_extract": "browser.extract",
        "browser_get_title": "browser.get_title",
        "browser_click": "browser.click",
        "browser_type": "browser.type",
        "browser_new_tab": "browser.new_tab",
        "report_page_finding": "browser.report_finding",
        "speak": "speech.speak",
    }
    return tool_map.get(action_type, "unknown")


def _default_verification_method(action_type: str) -> str:
    """Return default verification method for action type."""
    if action_type in ("open_app_wait", "inspect_ui", "find_ui_element", "click_ui", "type_ui"):
        return VerificationMethod.UIA.value
    elif action_type in ("browser_search", "browser_navigate", "browser_extract", "browser_click", "browser_type"):
        return VerificationMethod.BROWSER_DOM.value
    elif action_type in ("create_folder_verified", "write_file_verified", "verify_file", "create_docx", "create_pptx"):
        return VerificationMethod.FILE_SYSTEM.value
    elif action_type in ("calculator_compute", "press_key"):
        return VerificationMethod.PROCESS_CHECK.value
    elif action_type == "screenshot_ui":
        return VerificationMethod.SCREENSHOT_VISION.value
    return VerificationMethod.UIA.value


def _default_fallback(action_type: str) -> str:
    """Return default fallback strategy for action type."""
    fallback_map = {
        "open_app_wait": "retry_with_longer_timeout",
        "find_ui_element": "coordinate_click",
        "click_ui": "coordinate_click",
        "type_ui": "pyautogui_type",
        "browser_search": "fallback_to_bing",
        "browser_navigate": "retry_navigation",
        "browser_extract": "retry_extraction",
        "create_docx": "simplified_document",
        "create_pptx": "simplified_presentation",
    }
    return fallback_map.get(action_type, "retry")


def _infer_task_type(task: str, goal_analysis: Dict[str, Any]) -> TaskType:
    """Infer task type from goal analysis."""
    task_type_str = goal_analysis.get("task_type", "simple")
    try:
        return TaskType(task_type_str)
    except ValueError:
        # Fallback inference
        task_lower = task.lower()
        if "research" in task_lower and (("word" in task_lower or "docx" in task_lower or "document" in task_lower or "report" in task_lower) or ("powerpoint" in task_lower or "pptx" in task_lower or "presentation" in task_lower or "ppt" in task_lower or "slides" in task_lower)):
            return TaskType.RESEARCH_DOCUMENT
        elif "research" in task_lower or "search" in task_lower:
            return TaskType.RESEARCH
        elif "calculate" in task_lower or "compute" in task_lower:
            return TaskType.RESEARCH_CALCULATION
        elif "notepad" in task_lower and "type" in task_lower:
            return TaskType.SEQUENTIAL
        return TaskType.SIMPLE


def _validate_plan(plan: Plan, state: TaskState) -> Plan:
    """Validate the plan before execution."""
    errors = []
    
    # Check if plan addresses the goal
    if not plan.actions:
        errors.append("Plan has no actions")
    
    # Check for speak action at end
    has_speak = any(a.type == "speak" for a in plan.actions)
    if not has_speak:
        errors.append("Plan missing final 'speak' action")
    
    # Validate dependencies
    for i, action in enumerate(plan.actions):
        for dep_idx in action.depends_on:
            if dep_idx >= i or dep_idx >= len(plan.actions):
                errors.append(f"Action {i} ({action.type}) has invalid dependency on step {dep_idx}")
            if dep_idx < 0:
                errors.append(f"Action {i} ({action.type}) has negative dependency index")
    
    # Check that consumed state keys are produced by dependencies
    produced_keys = set()
    for i, action in enumerate(plan.actions):
        # Check consumes
        for key in action.consumes:
            if key not in produced_keys and key not in ("search_results", "current_page_url", "current_page_title", "extracted_sources", "collected_numbers", "active_app", "active_window", "created_document_path", "created_presentation_path", "ui_elements", "ui_target"):
                # Check if any dependency produces it
                found = False
                for dep_idx in action.depends_on:
                    if dep_idx < len(plan.actions) and key in plan.actions[dep_idx].produces:
                        found = True
                        break
                if not found:
                    errors.append(f"Action {i} ({action.type}) consumes '{key}' but no dependency produces it")
        
        # Add produced keys
        produced_keys.update(action.produces)
    
    # Check for required parameters per action type
    required_params = {
        "open_app_wait": ["app_name", "window_title"],
        "type_in_app": ["text", "window_title"],
        "press_key": ["key"],
        "calculator_compute": ["expression"],
        "inspect_ui": [],
        "find_ui_element": [],
        "click_ui": [],
        "type_ui": ["text"],
        "screenshot_ui": [],
        "create_folder_verified": ["path"],
        "write_file_verified": ["path", "content"],
        "verify_file": ["path"],
        "create_docx": ["path", "title"],
        "create_pptx": ["path", "title", "slides"],
        "browser_search": ["query"],
        "browser_navigate": [],  # url or source_index
        "browser_extract": [],
        "browser_get_title": [],
        "browser_click": ["selector"],
        "browser_type": ["selector", "text"],
        "browser_new_tab": [],
        "report_page_finding": ["query"],
        "speak": ["text"],
    }
    
    for i, action in enumerate(plan.actions):
        req = required_params.get(action.type, [])
        for param in req:
            if param not in action.parameters:
                # Special case: browser_navigate can use source_index instead of url
                if action.type == "browser_navigate" and param == "url" and "source_index" in action.parameters:
                    continue
                errors.append(f"Action {i} ({action.type}) missing required parameter: {param}")
    
    plan.validation_errors = errors
    plan.is_valid = len(errors) == 0
    return plan


class Planner:
    def __init__(self):
        self._goal_cache = {}  # Cache goal analyses for similar tasks
    
    def understand_goal(self, task: str, state: TaskState) -> Dict[str, Any]:
        """Analyze the user's request to understand the actual goal."""
        state.task = task
        
        # Check cache
        task_key = task.lower().strip()
        if task_key in self._goal_cache:
            return self._goal_cache[task_key]
        
        # Load API key
        api_key = _load_config_gemini_api_key()
        
        # Try LLM for goal understanding
        goal_analysis = _call_gemini_for_plan(task, api_key, GOAL_UNDERSTANDING_PROMPT)
        if goal_analysis and isinstance(goal_analysis, list) and len(goal_analysis) > 0:
            goal_analysis = goal_analysis[0] if isinstance(goal_analysis[0], dict) else {}
        elif not goal_analysis:
            # Fallback rule-based goal analysis
            goal_analysis = self._rule_based_goal_analysis(task)
        
        # Cache the result
        self._goal_cache[task_key] = goal_analysis
        return goal_analysis
    
    def _rule_based_goal_analysis(self, task: str) -> Dict[str, Any]:
        """Fallback rule-based goal analysis."""
        task_lower = task.lower()
        
        if "notepad" in task_lower and ("type" in task_lower or "write" in task_lower):
            return {
                "primary_goal": "Open Notepad and type specified text",
                "information": [],
                "intermediate_operations": ["open_notepad", "type_text"],
                "final_deliverables": ["Text typed in Notepad"],
                "tool_instructions": [],
                "task_type": "sequential",
                "constraints": {},
                "dependencies": [
                    {"step": "open_notepad", "depends_on": []},
                    {"step": "type_text", "depends_on": ["open_notepad"]}
                ]
            }
        elif ("research" in task_lower or "search" in task_lower or "gather" in task_lower or "find" in task_lower or "topic" in task_lower or "website" in task_lower or "websites" in task_lower) and (("word" in task_lower or "docx" in task_lower or "document" in task_lower or "report" in task_lower) or ("powerpoint" in task_lower or "pptx" in task_lower or "presentation" in task_lower or "ppt" in task_lower or "slides" in task_lower)):
            params = _extract_research_parameters(task)
            topic = params["topic"]
            num_sources = params["num_sources"]
            is_pres = params["is_presentation"]

            deps = [{"step": "search", "depends_on": []}]
            extract_steps = []
            for i in range(num_sources):
                v_step = f"visit_source_{i + 1}"
                e_step = f"extract_source_{i + 1}"
                deps.append({"step": v_step, "depends_on": ["search"]})
                deps.append({"step": e_step, "depends_on": [v_step]})
                extract_steps.append(e_step)

            artifact_name = f"PowerPoint presentation (.pptx)" if is_pres else f"Word document (.docx)"
            deps.append({"step": "create_presentation" if is_pres else "create_document", "depends_on": extract_steps})

            return {
                "primary_goal": f"Create a {artifact_name} containing researched information about {topic} gathered from {num_sources} sources",
                "information": [f"topic: {topic}", f"sources_count: {num_sources}"],
                "intermediate_operations": ["search", "visit_sources", "extract_content", "generate_output"],
                "final_deliverables": [f"{artifact_name} on Desktop with research findings on '{topic}'"],
                "tool_instructions": [],
                "task_type": "research_document",
                "constraints": {"min_sources": num_sources, "output_format": "pptx" if is_pres else "docx", "output_location": "Desktop"},
                "dependencies": deps
            }
        elif "calculator" in task_lower or "calc" in task_lower:
            return {
                "primary_goal": "Calculate mathematical expression and provide result",
                "information": [],
                "intermediate_operations": ["open_calculator", "compute"],
                "final_deliverables": ["Calculation result"],
                "tool_instructions": ["calculator"],
                "task_type": "simple",
                "constraints": {},
                "dependencies": [
                    {"step": "compute", "depends_on": []}
                ]
            }
        else:
            return {
                "primary_goal": f"Process request: {task[:100]}",
                "information": [],
                "intermediate_operations": ["process"],
                "final_deliverables": ["Response"],
                "tool_instructions": [],
                "task_type": "simple",
                "constraints": {},
                "dependencies": []
            }
    
    def plan_task(self, task: str, state: TaskState) -> List[ActionSpec]:
        """Convert a natural language task into a structured action list via LLM."""
        # Reset state for new task
        state.task = task
        state.original_user_intent = task
        state.completed_steps = []
        state.current_step = 0
        state.retry_count = 0
        state.failed_steps = {}
        state.errors = []
        state.observations = []
        state.action_outputs = {}
        state.human_verification_required = False
        state.human_verification_message = ""
        state.human_verification_resolved = False
        state.human_verification_action_index = None
        state.human_verification_context = {}
        state.waiting_for_user = False
        state.replan_count = 0
        state.last_replan_reason = ""
        state.final_outcome_verified = False
        state.final_outcome_data = {}
        
        # Clear browser research state for new task
        state.search_results = []
        state.extracted_sources = []
        state.current_page_url = ""
        state.current_page_title = ""
        state.collected_numbers = []
        
        # Step 1: Understand the goal
        goal_analysis = self.understand_goal(task, state)
        state.interpreted_goal = goal_analysis.get("primary_goal", task)
        state.requirements = goal_analysis
        state.constraints = goal_analysis.get("constraints", {})
        state.task_type = _infer_task_type(task, goal_analysis)
        
        # Load API key
        api_key = _load_config_gemini_api_key()
        
        # Step 2: Generate plan using LLM
        # Extract research parameters FIRST to anchor the LLM on the correct
        # topic, source count (M) and slide count (N) — preventing any confusion.
        research_params = _extract_research_parameters(task)
        topic = research_params["topic"]
        num_sources = research_params["num_sources"]      # M
        target_slides = research_params["target_slides"]  # N
        target_domain = research_params["target_domain"]
        is_presentation = research_params["is_presentation"]

        # Store in state so executor can read them without re-parsing
        state.task_metadata = getattr(state, "task_metadata", {})
        state.task_metadata["target_slides"] = target_slides
        state.task_metadata["num_sources"] = num_sources
        state.task_metadata["target_domain"] = target_domain
        state.task_metadata["topic"] = topic

        # Enrich the task prompt so the LLM cannot confuse action verbs with the query.
        enriched_task = task
        if topic and topic != "Research Topic":
            enriched_task = f"Topic: {topic}. {task}"
            enriched_task += f" Gather info from EXACTLY {num_sources} websites (M={num_sources})."
            if target_slides:
                enriched_task += f" Generate EXACTLY {target_slides} slides/sections (N={target_slides})."
            if target_domain:
                enriched_task += f" Use ONLY sources from {target_domain}."
            if is_presentation:
                enriched_task += " Output format: PowerPoint presentation."

        # URL-directed tasks need exact navigation semantics.  Prefer the
        # deterministic URL plan over an LLM paraphrasing the URL into a search.
        explicit_url_task = bool(re.search(r"https?://[^\s\]\[\),]+", task, re.I))
        actions = None if explicit_url_task else _call_gemini_for_plan(enriched_task, api_key, PLANNER_SYSTEM_PROMPT)
        if actions:
            # Resolve any placeholder desktop paths
            for action in actions:
                for key in ("path", "save_path"):
                    if key in action and isinstance(action[key], str):
                        action[key] = _resolve_desktop_path(action[key])
        else:
            # Fallback to rule-based
            actions = _rule_based_plan(task)
        
        # Step 3: Convert to structured ActionSpecs with dependencies
        specs = _parse_llm_actions_to_specs(actions, state)
        
        # Step 4: Build and validate plan
        plan = Plan(
            actions=specs,
            goal=state.interpreted_goal,
            task_type=state.task_type,
            estimated_steps=len(specs),
            final_outcome_verification={
                "type": "document" if "create_docx" in [a.type for a in specs] else "verification",
                "criteria": goal_analysis.get("final_deliverables", [])
            }
        )
        
        plan = _validate_plan(plan, state)
        state.plan = plan
        
        # If plan is invalid, try to fix it or fall back
        if not plan.is_valid:
            # Try to auto-fix common issues
            plan = self._auto_fix_plan(plan, state)
            plan = _validate_plan(plan, state)
        
        return plan.actions
    
    def _auto_fix_plan(self, plan: Plan, state: TaskState) -> Plan:
        """Attempt to auto-fix common plan validation errors."""
        # Add missing speak action
        if not any(a.type == "speak" for a in plan.actions):
            plan.actions.append(ActionSpec(
                type="speak",
                description="Task complete",
                parameters={"text": "Task completed, sir."},
                is_critical=False
            ))
        
        # Fix missing dependencies for browser_extract
        for i, action in enumerate(plan.actions):
            if action.type == "browser_extract" and not action.depends_on:
                # Find nearest browser_navigate before this
                for j in range(i-1, -1, -1):
                    if plan.actions[j].type == "browser_navigate":
                        action.depends_on = [j]
                        break
        
        # Fix missing dependencies for create_docx
        for i, action in enumerate(plan.actions):
            if action.type == "create_docx" and not action.depends_on:
                extract_indices = [j for j, a in enumerate(plan.actions) if a.type == "browser_extract"]
                if extract_indices:
                    action.depends_on = extract_indices
        
        return plan
    
    def replan(self, task: str, state: TaskState, failure_context: Dict[str, Any]) -> List[ActionSpec]:
        """Replan from current state after a failure or observation."""
        if state.replan_count >= state.max_replans:
            raise Exception(f"Maximum replan attempts ({state.max_replans}) exceeded")
        
        state.replan_count += 1
        state.last_replan_reason = failure_context.get("reason", "Unknown")
        
        # Preserve successful action outputs
        preserved_outputs = state.action_outputs.copy()
        completed = state.completed_steps.copy()
        extracted = state.extracted_sources.copy()
        search_results = state.search_results.copy()
        
        # Generate new plan with context about what failed
        replan_prompt = PLANNER_SYSTEM_PROMPT + f"""

REPLANNING CONTEXT:
- Original task: {task}
- Failed step: {failure_context.get('step_index', 'unknown')} ({failure_context.get('action_type', 'unknown')})
- Failure reason: {failure_context.get('reason', 'unknown')}
- Failure classification: {failure_context.get('classification', 'unknown')}
- Already completed steps: {completed}
- Extracted sources so far: {len(extracted)}
- Search results available: {len(search_results)}

Adjust the plan to:
1. Skip already completed steps
2. Use already extracted data
3. Change strategy for the failed step
4. Maintain dependencies on successful steps
"""
        
        api_key = _load_config_gemini_api_key()

        # Enrich task with extracted topic for replanning too
        replan_research_params = _extract_research_parameters(task)
        replan_topic = replan_research_params["topic"]
        replan_task = task
        if replan_topic and replan_topic != "Research Topic":
            replan_task = f"Topic: {replan_topic}. {task}"

        actions = _call_gemini_for_plan(replan_task, api_key, replan_prompt)
        if not actions:
            actions = _rule_based_plan(task)
        
        # Resolve paths
        for action in actions:
            for key in ("path", "save_path"):
                if key in action and isinstance(action[key], str):
                    action[key] = _resolve_desktop_path(action[key])
        
        # Convert to specs
        specs = _parse_llm_actions_to_specs(actions, state)
        
        # Mark already completed steps as such in the new plan
        # This is a simplified approach - in reality we'd need to map old steps to new
        new_plan = Plan(
            actions=specs,
            goal=state.interpreted_goal,
            task_type=state.task_type,
            estimated_steps=len(specs),
        )
        new_plan = _validate_plan(new_plan, state)
        state.plan = new_plan
        
        return new_plan.actions
