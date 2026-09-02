"""
Agent Planner — converts natural-language tasks into structured executable action plans.
Supports data passing through TaskState for browser research workflows.
"""
import json
import re
import os
from typing import List, Dict, Any, Optional

from backend.agent.state import TaskState, TaskType, ActionSpec, Plan


# ── Prompt sent to the LLM ────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are the JARVIS Agent Planner. Convert the user's task into a JSON array of executable steps.

RULES:
1. Output ONLY a valid JSON array. No markdown fences, no explanation.
2. Each element is an action object with a "type", "description", "expected_outcome", and "required_context_keys" field.
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
{"type": "open_app_wait", "app_name": "notepad", "window_title": "Notepad", "description": "Open Notepad", "expected_outcome": "Notepad application is running and visible", "required_context_keys": []}
{"type": "type_in_app",   "text": "Hello world",  "window_title": "Notepad", "description": "Type text in Notepad", "expected_outcome": "The text 'Hello world' is typed into Notepad", "required_context_keys": []}
{"type": "press_key",     "key": "ctrl+s",        "description": "Press Ctrl+S to save", "expected_outcome": "Save dialog is opened or file is saved", "required_context_keys": []}
{"type": "calculator_compute", "expression": "125 * 48", "expected": "6000", "description": "Calculate 125 × 48", "expected_outcome": "Calculation result is computed", "required_context_keys": []}

// File system (VERIFIED versions - these check actual filesystem)
{"type": "create_folder_verified", "path": "C:/Users/username/Desktop/FOLDER_NAME", "description": "Create folder on Desktop", "expected_outcome": "Folder exists at the specified path", "required_context_keys": []}
{"type": "write_file_verified",    "path": "C:/full/path/file.txt", "content": "text", "description": "Create file", "expected_outcome": "File exists with the correct content", "required_context_keys": []}
{"type": "verify_file",           "path": "C:/full/path/file.txt", "description": "Verify file/folder exists", "expected_outcome": "File presence is confirmed", "required_context_keys": []}
{"type": "create_docx",           "path": "C:/full/path/doc.docx", "title": "Title", "content": "body text with sources", "headings": ["Heading 1", "Heading 2"], "description": "Create Word document", "expected_outcome": "Word document is created", "required_context_keys": []}

// Browser (uses visible Playwright Chromium, headless=False)
// browser_search automatically extracts and stores results in state.search_results
// If Google blocks with CAPTCHA, browser_search automatically falls back to Bing — no special handling needed
{"type": "browser_search",   "query": "National Science Day India", "description": "Search Google", "expected_outcome": "Search results are retrieved", "required_context_keys": []}
// browser_navigate: navigate to a URL (use from state.search_results)
{"type": "browser_navigate", "url": "https://example.com", "source_index": 0, "description": "Navigate to source 1", "expected_outcome": "Browser navigates to the specified URL", "required_context_keys": ["search_results"]}
// browser_extract: extracts text from current page, stores in state.extracted_sources
{"type": "browser_extract",  "description": "Extract text from current page", "expected_outcome": "Text is extracted from the page", "required_context_keys": ["current_page_url"]}
{"type": "browser_get_title","description": "Get current page title", "expected_outcome": "Page title is retrieved", "required_context_keys": []}

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


def _call_gemini_for_plan(task: str, api_key: str, system_prompt: str) -> Optional[List[Dict[str, Any]]]:
    """Call the Gemini API to get a structured action plan."""
    import urllib.request
    import urllib.error
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
    elif ("research" in task_lower or "search" in task_lower) and ("word" in task_lower or "docx" in task_lower or "document" in task_lower):
        # Research task with multiple sources
        topic = task
        for pattern in [
            r"research\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
            r"search\s+for\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
            r"find\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
        ]:
            m = re.search(pattern, task_lower)
            if m:
                topic = m.group(1).strip()
                break
        topic = re.sub(r'\s+(and|from|into|create)\s+(word\s+)?(document|docx).*$', '', topic, flags=re.I).strip()
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        safe_topic = topic.replace(' ', '_')

        actions = [
            {"type": "browser_search", "query": topic, "description": f"Search for {topic}"},
            {"type": "browser_navigate", "source_index": 0, "description": "Navigate to first source"},
            {"type": "browser_extract", "description": "Extract from first source"},
            {"type": "browser_navigate", "source_index": 1, "description": "Navigate to second source"},
            {"type": "browser_extract", "description": "Extract from second source"},
            {"type": "browser_navigate", "source_index": 2, "description": "Navigate to third source"},
            {"type": "browser_extract", "description": "Extract from third source"},
            {"type": "create_docx", "path": os.path.join(desktop, f"{safe_topic}_research.docx"),
             "title": f"Research: {topic}", "content": "", "headings": ["Overview", "Key Findings", "Sources"], "description": "Create research document"},
            {"type": "verify_file", "path": os.path.join(desktop, f"{safe_topic}_research.docx"),
             "description": "Verify document created"},
            {"type": "speak", "text": f"Research on {topic} complete and saved to Desktop, sir.", "description": "Done"},
        ]
    elif "calculator" in task_lower or "calc" in task_lower:
        expr_match = re.search(r"(\d[\d\s×*x\+\-÷/\.]+\d)", task)
        expr = expr_match.group(1).replace("×", "*").replace("÷", "/").replace("x", "*") if expr_match else ""
        actions = [
            {"type": "calculator_compute", "expression": expr, "expected": "",
             "description": f"Calculate {expr}"},
            {"type": "speak", "text": f"Calculation complete, sir.", "description": "Done"},
        ]
    elif ("chrome" in task_lower or "search" in task_lower or "browser" in task_lower):
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
        elif atype == "calculator_compute":
            produces = ["collected_numbers"]
        elif atype == "open_app_wait":
            produces = ["active_app", "active_window"]
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
        
        # Extract parameters (exclude type and description etc)
        params = {k: v for k, v in action.items() if k not in ("type", "description", "expected_outcome", "required_context_keys")}
        
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
            is_critical=atype != "speak"
        )
        specs.append(spec)
    
    return specs


def _infer_task_type(task: str, goal_analysis: Dict[str, Any]) -> TaskType:
    """Infer task type from goal analysis."""
    task_type_str = goal_analysis.get("task_type", "simple")
    try:
        return TaskType(task_type_str)
    except ValueError:
        # Fallback inference
        task_lower = task.lower()
        if "research" in task_lower and ("word" in task_lower or "docx" in task_lower or "document" in task_lower):
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
            if key not in produced_keys and key not in ("search_results", "current_page_url", "current_page_title", "extracted_sources", "collected_numbers", "active_app", "active_window", "created_document_path"):
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
        "create_folder_verified": ["path"],
        "write_file_verified": ["path", "content"],
        "verify_file": ["path"],
        "create_docx": ["path", "title"],
        "browser_search": ["query"],
        "browser_navigate": [],  # url or source_index
        "browser_extract": [],
        "browser_get_title": [],
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
        elif ("research" in task_lower or "search" in task_lower) and ("word" in task_lower or "docx" in task_lower or "document" in task_lower):
            topic = task
            for pattern in [
                r"research\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
                r"search\s+for\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
                r"find\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)",
            ]:
                m = re.search(pattern, task_lower)
                if m:
                    topic = m.group(1).strip()
                    break
            return {
                "primary_goal": f"Create a Word document containing researched information about {topic}",
                "information": [f"topic: {topic}"],
                "intermediate_operations": ["search", "visit_sources", "extract_content", "create_document"],
                "final_deliverables": ["Word document (.docx) on Desktop with research findings"],
                "tool_instructions": [],
                "task_type": "research_document",
                "constraints": {"min_sources": 3, "output_format": "docx", "output_location": "Desktop"},
                "dependencies": [
                    {"step": "search", "depends_on": []},
                    {"step": "visit_source_1", "depends_on": ["search"]},
                    {"step": "extract_source_1", "depends_on": ["visit_source_1"]},
                    {"step": "visit_source_2", "depends_on": ["search"]},
                    {"step": "extract_source_2", "depends_on": ["visit_source_2"]},
                    {"step": "visit_source_3", "depends_on": ["search"]},
                    {"step": "extract_source_3", "depends_on": ["visit_source_3"]},
                    {"step": "create_document", "depends_on": ["extract_source_1", "extract_source_2", "extract_source_3"]}
                ]
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
        
        # Step 2: Generate plan using LLM
        actions = _call_gemini_for_plan(task, api_key, PLANNER_SYSTEM_PROMPT)
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
        
        actions = _call_gemini_for_plan(task, api_key, replan_prompt)
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