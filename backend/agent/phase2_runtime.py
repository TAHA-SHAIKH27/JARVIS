"""Phase 2 Windows Computer Agent runtime bridge."""
from __future__ import annotations

from typing import Any

_PLANNER_INSTALLED = False
_EXECUTOR_INSTALLED = False

PHASE2_PROMPT_EXTENSION = r'''

PHASE 2 WINDOWS COMPUTER AGENT:
Use the existing Windows computer tool for real desktop control. Prefer semantic UI Automation (UIA) over guessed screen coordinates. Observe before acting when the target is ambiguous, and verify the result after actions.

Computer-use rules:
- For normal desktop tasks, use open_app_wait -> inspect_ui/find_ui_element -> click_ui/type_ui/press_key as needed -> verification.
- Prefer finding a named control before clicking it.
- Use the existing inspect_ui/find_ui_element/click_ui/type_ui/screenshot_ui actions; do not invent new action types.
- Use screenshot_ui when UIA cannot expose the required control; treat it as observation/fallback, not proof by itself.
- Do not claim an action succeeded unless the executor/observer verifies it.
- For multi-step tasks, keep the plan minimal and ordered.
- For File Explorer or normal Windows applications, operate the visible application rather than pretending a command completed.
'''


async def _execute_phase2_action(executor: Any, action: Any, state: Any):
    """Provide additional computer primitives while preserving existing actions."""
    computer = executor._computer()
    params = executor._inject_state_data(action, state)
    atype = action.type

    if atype == "list_windows":
        return await computer.list_windows(state)
    if atype == "focus_window":
        return await computer.focus_window(params.get("window_title", params.get("title", "")), state)
    if atype == "scroll_ui":
        return await computer.scroll(int(params.get("amount", 0)), state)
    if atype == "drag_ui":
        return await computer.drag(int(params.get("x1", 0)), int(params.get("y1", 0)), int(params.get("x2", 0)), int(params.get("y2", 0)), state)
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
