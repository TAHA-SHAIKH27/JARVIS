"""Phase 2 Windows Computer Agent runtime bridge."""
from __future__ import annotations

from typing import Any

_PLANNER_INSTALLED = False
_EXECUTOR_INSTALLED = False

PHASE2_PROMPT_EXTENSION = r'''

PHASE 2 WINDOWS COMPUTER AGENT:
Use the existing Windows computer tool for real desktop control. Prefer semantic UI Automation (UIA) over guessed screen coordinates. Observe before acting when the target is ambiguous, and verify the result after actions.

Additional computer actions:
{"type":"list_windows","description":"List visible Windows applications","expected_outcome":"Visible windows are returned","required_context_keys":[]}
{"type":"focus_window","window_title":"Notepad","description":"Focus the target application window","expected_outcome":"The requested window is focused","required_context_keys":[]}
{"type":"inspect_ui","target":"Save","description":"Inspect the target Windows UI","expected_outcome":"Visible UI controls are discovered","required_context_keys":[]}
{"type":"find_ui_element","text":"Save","description":"Find a visible Windows control","expected_outcome":"The requested control is located","required_context_keys":[]}
{"type":"click_ui","text":"Save","description":"Click the requested Windows control","expected_outcome":"The control is activated","required_context_keys":[]}
{"type":"type_ui","text":"Hello","description":"Type into the focused Windows control","expected_outcome":"The text is entered","required_context_keys":[]}
{"type":"press_key","key":"ctrl+s","description":"Press a keyboard shortcut","expected_outcome":"The shortcut is executed","required_context_keys":[]}
{"type":"scroll_ui","amount":-5,"description":"Scroll the active Windows application","expected_outcome":"The view scrolls","required_context_keys":[]}
{"type":"drag_ui","x1":100,"y1":100,"x2":500,"y2":500,"description":"Drag between two screen points","expected_outcome":"The drag operation completes","required_context_keys":[]}
{"type":"screenshot_ui","description":"Capture the desktop for observation","expected_outcome":"A screenshot is saved","required_context_keys":[]}

COMPUTER USE RULES:
- Prefer finding a named control before clicking it.
- Do not claim an action succeeded unless the executor/observer verifies it.
- Use screenshot_ui when UIA cannot expose the required control; treat it as observation/fallback, not proof by itself.
- For multi-step tasks, keep the plan minimal and ordered.
'''


async def _execute_phase2_action(executor: Any, action: Any, state: Any):
    computer = executor._computer()
    params = executor._inject_state_data(action, state)
    atype = action.type

    if atype == "list_windows":
        return await computer.list_windows(state)
    if atype == "focus_window":
        return await computer.focus_window(params.get("window_title", params.get("title", "")), state)
    if atype == "inspect_ui":
        result = await computer.inspect_ui(params.get("target", ""), state)
        if result.get("status") == "success":
            state.update_context("ui_elements", result.get("elements", result.get("element", {})))
        return result
    if atype == "find_ui_element":
        result = await computer.find_element({
            "text": params.get("text", params.get("target", "")),
            "class": params.get("class", ""),
            "control_type": params.get("control_type", ""),
        }, state)
        if result.get("status") == "success":
            state.update_context("ui_target", result.get("element"))
        return result
    if atype == "click_ui":
        element = params.get("element") or state.get_context("ui_target")
        if not element and params.get("text"):
            found = await computer.find_element({"text": params["text"]}, state)
            if found.get("status") != "success":
                return found
            element = found.get("element")
            state.update_context("ui_target", element)
        return await computer.click(x=params.get("x"), y=params.get("y"), element=element, state=state)
    if atype == "type_ui":
        element = params.get("element") or state.get_context("ui_target")
        return await computer.type_text(params.get("text", ""), element=element, state=state)
    if atype == "scroll_ui":
        return await computer.scroll(int(params.get("amount", 0)), state)
    if atype == "drag_ui":
        return await computer.drag(int(params.get("x1", 0)), int(params.get("y1", 0)), int(params.get("x2", 0)), int(params.get("y2", 0)), state)
    if atype == "screenshot_ui":
        return await computer.screenshot(state)
    return None


def install_phase2() -> None:
    global _PLANNER_INSTALLED, _EXECUTOR_INSTALLED

    if not _PLANNER_INSTALLED:
        try:
            from backend.agent import planner
            original_planner_call = planner._call_gemini_for_plan
            if not getattr(original_planner_call, "_phase2_bridge", False):
                def phase2_planner_call(task: str, api_key: str, system_prompt: str):
                    return original_planner_call(task, api_key, system_prompt + PHASE2_PROMPT_EXTENSION)
                phase2_planner_call._phase2_bridge = True
                planner._call_gemini_for_plan = phase2_planner_call
            _PLANNER_INSTALLED = True
        except Exception:
            pass

    if not _EXECUTOR_INSTALLED:
        try:
            from backend.agent.executor import Executor
            original_execute = Executor.execute
            if not getattr(original_execute, "_phase2_bridge", False):
                async def phase2_execute(self, action, state):
                    result = await _execute_phase2_action(self, action, state)
                    if result is not None:
                        return result
                    return await original_execute(self, action, state)
                phase2_execute._phase2_bridge = True
                Executor.execute = phase2_execute
            _EXECUTOR_INSTALLED = True
        except Exception:
            pass
