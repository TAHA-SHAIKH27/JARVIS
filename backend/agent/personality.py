"""JARVIS personality: how the agent talks while it works.

Tone contract (user-specified):
- Pleasant, respectful, a little funny — but NEVER at serious moments.
- Serious moments (failures, security/logins, data loss risk, policy blocks):
  straight, plain, respectful. No jokes, no "sir"-stuffing.
- Casual progress narration: warm, brief, lightly witty. "sir" sparingly —
  openings, closings, and genuine deference — not every line.
- Frank and plain when reporting facts (numbers, paths, results).

These helpers only shape *wording*. Event types, icons, and data payloads
are owned by core.py and stay machine-stable for the frontend.
"""
import random
from typing import Any, Dict, Optional

_CASUAL_OPENERS = [
    "On it.",
    "Right away.",
    "Consider it handled.",
    "Rolling up my sleeves.",
]

_CASUAL_DONES = [
    "Done.",
    "That's handled.",
    "One down.",
]


def acknowledge(task: str, n_steps: int) -> str:
    """Opening line for a fresh run. Big jobs get a step count + promise
    of updates; small ones just get going."""
    opener = random.choice(_CASUAL_OPENERS)
    if n_steps >= 6:
        return (f"{opener} {n_steps} steps on this one, sir — "
                f"I'll keep you posted as each lands.")
    return f"{opener} On it, sir."


def narrate_start(action_type: str, desc: str, idx: int, total: int,
                  params: Optional[Dict[str, Any]] = None) -> str:
    """One warm line for 'working on this now' (step_started payload)."""
    params = params or {}
    step = f"Step {idx + 1} of {total}"
    if action_type == "browser_search":
        q = str(params.get("query", ""))[:60]
        return f"{step}: searching the web for '{q}'…"
    if action_type == "browser_navigate":
        return f"{step}: opening source…"
    if action_type == "browser_extract":
        return f"{step}: reading the page…"
    if action_type == "browser_parallel_research":
        n = len(params.get("urls", []) or [])
        return f"{step}: fanning out over {n} tabs at once…"
    if action_type == "browser_download":
        return f"{step}: downloading your file…"
    if action_type == "browser_login":
        return f"{step}: opening the login page — I'll need you in a moment…"
    if action_type == "browser_login_check":
        return f"{step}: checking whether the login stuck…"
    if action_type == "browser_extract_table":
        return f"{step}: pulling the table into a spreadsheet…"
    if action_type == "create_docx":
        return f"{step}: writing the Word document…"
    if action_type == "create_pptx":
        return f"{step}: building the slide deck…"
    if action_type == "verify_file":
        return f"{step}: verifying the file is really there…"
    if action_type == "create_folder_verified":
        return f"{step}: creating the folder…"
    if action_type == "write_file_verified":
        return f"{step}: writing the file…"
    if action_type == "run_tests":
        return f"{step}: running the test suite — this one takes a moment…"
    if action_type == "run_shell":
        cmd = str(params.get("command", ""))[:50]
        return f"{step}: running '{cmd}'…"
    if action_type == "git_op":
        return f"{step}: checking git {params.get('operation', '')}…"
    if action_type == "calculator_compute":
        return f"{step}: crunching the numbers…"
    if action_type == "open_app_wait":
        return f"{step}: opening {params.get('app_name', 'the app')}…"
    if action_type == "type_in_app":
        return f"{step}: typing that in…"
    if action_type == "screenshot_ui":
        return f"{step}: taking a screenshot…"
    if action_type in ("click_ui", "find_ui_element"):
        return f"{step}: working the controls…"
    if action_type == "speak":
        return ""
    return f"{step}: {desc}…"


def narrate_done(action_type: str, observation: Optional[Dict[str, Any]] = None) -> str:
    """One warm line for 'this one's done' (step_completed payload)."""
    observation = observation or {}
    msg = (observation.get("message", "") or "").strip()
    if action_type == "browser_search":
        n = observation.get("results_count", "")
        return f"Search landed ({n} results)." if n != "" else "Search landed."
    if action_type == "browser_navigate":
        return "Page opened."
    if action_type == "browser_extract":
        return "Page read and banked."
    if action_type == "browser_parallel_research":
        n = observation.get("results_count", "")
        return f"All tabs read ({n} sources banked)." if n != "" else "All tabs read."
    if action_type == "browser_download":
        return "Download verified on disk."
    if action_type == "browser_extract_table":
        return "Table captured."
    if action_type in ("create_docx", "create_pptx"):
        return "Document written."
    if action_type in ("run_tests", "run_shell", "git_op"):
        tail = msg.replace("Exit 0:", "").strip()
        return f"Command finished. {tail[:120]}" if tail else "Command finished."
    if action_type == "calculator_compute":
        return msg or random.choice(_CASUAL_DONES)
    if action_type == "screenshot_ui":
        return "Screenshot captured."
    if action_type in ("create_folder_verified", "write_file_verified", "verify_file"):
        return "Verified."
    return random.choice(_CASUAL_DONES)


def narrate_retry(desc: str, attempt: int) -> str:
    """Light, honest retry line — effort, not excuses."""
    return f"That didn't take — trying '{desc}' again (attempt {attempt})."


def narrate_waiting_human(message: str, kind: str = "") -> str:
    """Human-handoff line. Serious when it's a login/security pause."""
    if kind in ("login", "captcha", "security"):
        return f"Paused for you, sir: {message}"
    return f"Over to you, sir — {message}"


def serious(message: str) -> str:
    """Failure/critical wrapper: plain and respectful, zero humor."""
    return message.strip()
