"""
Agent Executor — executes structured actions using the real tool stack:
  - backend/tools/computer.py (pywinauto / win32 / pyautogui)
  - backend/tools/browser.py  (Playwright, headless=False)
  - backend/tools/office.py   (python-docx)
  - system_ops.py             (existing tool functions)
"""
import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from backend.agent.state import TaskState, ActionSpec
from backend.agent.registry import ToolRegistry
from backend.tools.result_schema import (
    create_computer_result,
    create_browser_result,
    create_office_result,
    create_filesystem_result,
    ToolResultStatus,
    ComputerActionResult,
    BrowserActionResult,
    OfficeActionResult,
    FilesystemActionResult,
)


class Executor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._browser = None  # lazy-initialized Browser instance

    # ─────────────────────────────────────────────────────────────────────────
    # Browser lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_browser(self):
        """Return the shared Browser instance, starting it if needed."""
        if self._browser is None:
            from backend.tools.browser import Browser
            self._browser = Browser()
            await self._browser.start()
        return self._browser

    async def close_browser(self):
        """Cleanly shut down the browser after the task."""
        if self._browser:
            try:
                await self._browser.stop()
            except Exception:
                pass
            self._browser = None

    def _computer(self):
        """Return the shared Windows automation tool registered by AgentCore."""
        computer = self.registry.get("computer_tool")
        if computer is None:
            raise RuntimeError("Windows automation tool is not registered")
        return computer

    # ─────────────────────────────────────────────────────────────────────────
    # Failure Diagnosis & Recovery
    # ─────────────────────────────────────────────────────────────────────────

    def _diagnose_failure(self, action: ActionSpec, result: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        """
        Diagnose a failure and suggest recovery strategies.
        Returns a dict with diagnosis info and suggested recovery actions.
        """
        atype = action.type
        error_msg = result.get("message", "") if result else "No result"
        
        diagnosis = {
            "action_type": atype,
            "error_message": error_msg,
            "recovery_strategies": [],
            "can_retry": True,
            "requires_alternative": False,
            "alternative_action": None,
        }
        
        if atype == "open_app_wait":
            if "timeout" in error_msg.lower() or "not detected" in error_msg.lower():
                diagnosis["recovery_strategies"] = [
                    "wait_longer",
                    "try_launch_any_app",
                    "check_process_list",
                    "try_alternative_executable"
                ]
                diagnosis["alternative_action"] = {
                    "type": "open_app_wait",
                    "parameters": {**action.parameters, "wait_timeout": 15}
                }
            elif "not found" in error_msg.lower() or "no such file" in error_msg.lower():
                diagnosis["recovery_strategies"] = ["verify_app_name", "check_installation"]
                diagnosis["can_retry"] = False
        
        elif atype in ("find_ui_element", "click_ui", "type_ui"):
            if "not found" in error_msg.lower() or "element not found" in error_msg.lower():
                diagnosis["recovery_strategies"] = [
                    "re_inspect_ui",
                    "try_coordinate_click",
                    "wait_for_element",
                    "try_vision_fallback"
                ]
                diagnosis["alternative_action"] = {
                    "type": "inspect_ui",
                    "parameters": {"target": action.parameters.get("window_title", "")}
                }
                diagnosis["requires_alternative"] = True
        
        elif atype == "browser_search":
            if "captcha" in error_msg.lower() or "sorry" in error_msg.lower():
                diagnosis["recovery_strategies"] = [
                    "fallback_to_bing",
                    "fallback_to_duckduckgo",
                    "wait_for_human"
                ]
                diagnosis["requires_alternative"] = True
            elif "network" in error_msg.lower() or "timeout" in error_msg.lower():
                diagnosis["recovery_strategies"] = ["retry_with_longer_timeout", "check_connectivity"]
        
        elif atype == "browser_navigate":
            if "not found" in error_msg.lower() or "404" in error_msg:
                diagnosis["recovery_strategies"] = [
                    "try_next_search_result",
                    "re_search_with_modified_query"
                ]
                diagnosis["alternative_action"] = {
                    "type": "browser_search",
                    "parameters": {"query": action.parameters.get("query", "") + " alternative"}
                }
        
        elif atype in ("create_docx", "create_pptx"):
            if "permission" in error_msg.lower() or "access denied" in error_msg.lower():
                diagnosis["recovery_strategies"] = [
                    "try_desktop_path",
                    "try_work_dir",
                    "check_disk_space"
                ]
        
        return diagnosis

    def _apply_recovery(self, action: ActionSpec, diagnosis: Dict[str, Any], state: TaskState) -> Optional[ActionSpec]:
        """Apply a recovery strategy and return a modified action if applicable."""
        if not diagnosis.get("alternative_action"):
            return None
        
        alt = diagnosis["alternative_action"]
        # Create a new ActionSpec with the alternative parameters
        from backend.agent.state import ActionSpec
        return ActionSpec(
            type=alt["type"],
            description=f"Recovery: {alt['type']}",
            parameters=alt["parameters"],
            depends_on=action.depends_on,
            produces=action.produces,
            consumes=action.consumes,
            expected_outcome=action.expected_outcome,
            fallback="recovery_fallback",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Main dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def execute(self, action: ActionSpec, state: TaskState) -> Optional[Dict[str, Any]]:
        """Execute a single action spec and return a result dict."""
        atype = action.type

        # Inject state data into parameters for data flow
        params = self._inject_state_data(action, state)

        # ── Desktop / Windows automation ────────────────────────────────────

        if atype == "open_app_wait":
            return await self._open_app_wait(params, state)

        elif atype == "type_in_app":
            return await self._type_in_app(params, state)

        elif atype == "press_key":
            return await self._press_key(params, state)

        elif atype == "calculator_compute":
            return await self._calculator_compute(params, state)

        elif atype == "inspect_ui":
            result = await self._computer().inspect_ui(params.get("target", ""), state)
            if result.get("status") == "success":
                state.update_context("ui_elements", result.get("elements", []))
            return result

        elif atype == "find_ui_element":
            criteria = {
                "text": params.get("text", params.get("target", "")),
                "class": params.get("class", ""),
            }
            result = await self._computer().find_element(criteria, state)
            if result.get("status") == "success" and result.get("element"):
                state.update_context("ui_target", result["element"])
            return result

        elif atype == "click_ui":
            element = params.get("element") or state.get_context("ui_target")
            if not element and params.get("text"):
                found = await self._computer().find_element({"text": params["text"]}, state)
                if found.get("status") != "success":
                    return found
                element = found.get("element")
                state.update_context("ui_target", element)
            return await self._computer().click(
                x=params.get("x"), y=params.get("y"), element=element, state=state
            )

        elif atype == "type_ui":
            return await self._computer().type_text(
                params.get("text", ""), element=params.get("element") or state.get_context("ui_target"), state=state
            )

        elif atype == "screenshot_ui":
            res = await self._computer().screenshot(state)
            shot_path = res.get("path", "") or res.get("screenshot_path", "")
            if res.get("status") == "success" and shot_path:
                state.update_context("last_screenshot_path", shot_path)
            return res

        # ── File system ──────────────────────────────────────────────────────

        elif atype == "create_folder_verified":
            res = self._create_folder(params)
            if res.get("status") == "success" and res.get("path"):
                state.update_context("last_folder_path", res["path"])
            return res

        elif atype == "write_file_verified":
            return self._write_file(params)

        elif atype == "verify_file":
            return self._verify_file(params)

        elif atype == "create_docx":
            return await self._create_docx(params, state)

        elif atype == "create_pptx":
            return await self._create_pptx(params, state)

        # ── Browser ──────────────────────────────────────────────────────────

        elif atype == "browser_search":
            return await self._browser_search(params, state)

        elif atype == "browser_navigate":
            return await self._browser_navigate(params, state)

        elif atype == "browser_extract":
            return await self._browser_extract(params, state)

        elif atype == "browser_get_title":
            return await self._browser_get_title()

        elif atype == "browser_click":
            browser = await self._get_browser()
            return await browser.click(params.get("selector", ""))

        elif atype == "browser_type":
            browser = await self._get_browser()
            return await browser.type(params.get("selector", ""), params.get("text", ""))

        elif atype == "browser_new_tab":
            browser = await self._get_browser()
            return await browser.new_tab()

        elif atype == "browser_extract_search_results":
            return await self._browser_extract_search_results()

        elif atype == "browser_download":
            return await self._browser_download(params, state)

        elif atype == "browser_login":
            return await self._browser_login(params, state)

        elif atype == "browser_login_check":
            return await self._browser_login_check(params, state)

        elif atype == "browser_parallel_research":
            return await self._browser_parallel_research(params, state)

        elif atype == "browser_extract_table":
            return await self._browser_extract_table(params, state)

        elif atype == "run_shell":
            return await self._run_shell(params, state)

        elif atype == "run_tests":
            return await self._run_tests(params, state)

        elif atype == "git_op":
            return await self._git_op(params, state)

        elif atype == "report_page_finding":
            return self._report_page_finding(params, state)

        # ── Legacy system_ops actions (passed through unchanged) ─────────────

        elif atype == "speak":
            return {"status": "success", "message": params.get("text", "")}

        elif atype == "open_app":
            app_name = params.get("app_name", "")
            from system_ops import launch_any_app
            return launch_any_app(app_name)

        elif atype == "close_app":
            app_name = params.get("app_name", "")
            from system_ops import close_application
            return close_application(app_name)

        elif atype == "launch_app":
            app_name = params.get("app_name", "")
            from system_ops import launch_any_app
            return launch_any_app(app_name)

        elif atype == "shutdown":
            from system_ops import shutdown_pc
            return shutdown_pc(int(params.get("delay_seconds", 0)))

        elif atype == "restart":
            from system_ops import restart_pc
            return restart_pc(int(params.get("delay_seconds", 0)))

        elif atype == "cancel_shutdown":
            from system_ops import cancel_shutdown
            return cancel_shutdown()

        elif atype == "sleep":
            from system_ops import sleep_pc
            return sleep_pc()

        elif atype == "lock_screen":
            from system_ops import lock_screen
            return lock_screen()

        elif atype == "volume_up":
            from system_ops import adjust_volume
            return adjust_volume("up")

        elif atype == "volume_down":
            from system_ops import adjust_volume
            return adjust_volume("down")

        elif atype == "mute_volume":
            from system_ops import adjust_volume
            return adjust_volume("mute")

        elif atype == "play_pause":
            from system_ops import media_control
            return media_control("play")

        elif atype == "next_track":
            from system_ops import media_control
            return media_control("next")

        elif atype == "prev_track":
            from system_ops import media_control
            return media_control("prev")

        elif atype == "search_web":
            query = params.get("query", "")
            from system_ops import search_web
            return search_web(query)

        elif atype == "weather":
            from system_ops import get_weather
            return get_weather(params.get("city", "London"))

        elif atype == "battery":
            from system_ops import get_battery_info
            return get_battery_info()

        elif atype == "network_info":
            from system_ops import get_network_info
            return get_network_info()

        elif atype == "datetime_info":
            from system_ops import get_datetime_info
            return get_datetime_info()

        elif atype == "take_screenshot":
            from system_ops import take_screenshot
            return take_screenshot()

        elif atype == "show_stats":
            from system_ops import get_system_stats
            return get_system_stats()

        elif atype == "create_folder":
            folder_name = params.get("folder_name", "")
            from system_ops import create_folder
            return create_folder(folder_name)

        elif atype == "create_word_doc":
            filename = params.get("filename", "")
            content = params.get("content", "")
            from system_ops import create_word_document
            return create_word_document(filename, content)

        elif atype == "check_pc_health":
            from system_ops import check_pc_health
            return check_pc_health()

        elif atype == "clipboard_read":
            from system_ops import get_clipboard
            return get_clipboard()

        elif atype == "clipboard_write":
            from system_ops import set_clipboard
            return set_clipboard(params.get("text", ""))

        elif atype == "open_url":
            from system_ops import open_url
            return open_url(params.get("url", ""))

        elif atype in ("write_file", "write_file_text"):
            from system_ops import write_file
            return write_file(params.get("filename", ""), params.get("content", ""))

        elif atype == "read_file":
            from system_ops import read_file
            return read_file(params.get("filename", ""))

        elif atype == "delete_file":
            from system_ops import delete_file
            return delete_file(params.get("filename", ""))

        elif atype == "set_timer":
            return {
                "status": "success",
                "message": f"Timer set for {params.get('seconds', 60)} seconds",
                "timer_data": {"seconds": params.get("seconds", 60), "label": params.get("label", "Timer")}
            }

        elif atype == "add_note":
            from datetime import datetime
            try:
                import json as _json
                notes_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "notes.json"))
                notes = []
                if os.path.exists(notes_path):
                    with open(notes_path) as f:
                        notes = _json.load(f)
                note = {"id": int(datetime.now().timestamp() * 1000), "text": params.get("text", ""),
                        "time": datetime.now().strftime("%b %d %H:%M")}
                notes.append(note)
                with open(notes_path, "w") as f:
                    _json.dump(notes, f, indent=2)
                return {"status": "success", "message": "Note added"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        elif atype == "add_todo":
            from datetime import datetime
            try:
                import json as _json
                todos_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "todos.json"))
                todos = []
                if os.path.exists(todos_path):
                    with open(todos_path) as f:
                        todos = _json.load(f)
                todo = {"id": int(datetime.now().timestamp() * 1000), "text": params.get("text", ""), "done": False}
                todos.append(todo)
                with open(todos_path, "w") as f:
                    _json.dump(todos, f, indent=2)
                return {"status": "success", "message": "Todo added"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        elif atype == "phone_devices":
            from phone_control import list_devices
            return list_devices()

        elif atype == "phone_mirror":
            from phone_control import start_mirror
            return start_mirror()

        elif atype == "phone_screenshot":
            from phone_control import screenshot_as_base64
            return screenshot_as_base64()

        elif atype == "phone_tap":
            from phone_control import tap
            return tap(params.get("x", 0), params.get("y", 0))

        elif atype == "phone_swipe":
            from phone_control import swipe
            return swipe(params.get("x1", 0), params.get("y1", 0),
                         params.get("x2", 0), params.get("y2", 0),
                         int(params.get("duration_ms", 300)))

        elif atype == "phone_text":
            from phone_control import input_text
            return input_text(params.get("text", ""))

        elif atype == "phone_key":
            from phone_control import press_key
            return press_key(params.get("key", ""))

        elif atype == "phone_launch_app":
            from phone_control import launch_app
            return launch_app(params.get("package", ""))

        elif atype == "phone_unlock":
            from phone_control import unlock_phone
            return unlock_phone(params.get("pin"))

        elif atype == "phone_test_pin_tap":
            from phone_control import test_pin_digit_tap
            return test_pin_digit_tap(str(params.get("digit", "")))

        elif atype == "send_whatsapp":
            from whatsapp_ops import send_whatsapp_message
            return send_whatsapp_message(params.get("contact", ""), params.get("message", ""))

        elif atype == "send_whatsapp_phone":
            from whatsapp_ops import send_whatsapp_message_via_phone
            return send_whatsapp_message_via_phone(params.get("contact", ""), params.get("message", ""))

        elif atype == "add_whatsapp_contact":
            from whatsapp_ops import add_contact
            return add_contact(params.get("name", ""), params.get("phone", ""))

        elif atype == "schedule_whatsapp":
            return self._schedule_whatsapp(params, state)

        elif atype == "list_scheduled_whatsapp":
            try:
                from backend.tools import scheduler as _sched
                jobs = _sched.list_scheduled()
                if not jobs:
                    return {"status": "success", "message": "No scheduled WhatsApp messages, sir.", "jobs": []}
                lines = []
                for job in jobs[:10]:
                    try:
                        from datetime import datetime as _dt
                        when_s = _sched.describe_when(_dt.fromisoformat(str(job.get("send_at", ""))))
                    except Exception:
                        when_s = "unscheduled"
                    lines.append(f"to {job.get('contact')} {when_s}: '{str(job.get('message', ''))[:60]}'")
                return {"status": "success",
                        "message": f"{len(jobs)} scheduled, sir: " + "; ".join(lines) + ".",
                        "jobs": jobs}
            except Exception as e:
                return {"status": "error", "message": f"Could not list scheduled messages: {e}"}

        elif atype == "cancel_scheduled_whatsapp":
            try:
                from backend.tools import scheduler as _sched
                return _sched.cancel_scheduled(str(params.get("fragment", "")))
            except Exception as e:
                return {"status": "error", "message": f"Could not cancel scheduled message: {e}"}

        elif atype == "reschedule_scheduled_whatsapp":
            try:
                from backend.tools import scheduler as _sched
                from datetime import datetime as _dt
                fragment = str(params.get("fragment", ""))
                send_at = str(params.get("send_at", "") or params.get("when_text", "") or params.get("time_text", "")).strip()
                when = None
                if send_at:
                    try:
                        when = _dt.fromisoformat(send_at)
                    except Exception:
                        when = None
                    if when is None:
                        parsed = _sched.parse_when(send_at)
                        if parsed.get("ok"):
                            when = parsed["when"]
                if when is None:
                    return {"status": "error",
                            "message": "When should I move it to, sir? Give send_at (ISO) or a time like 'at 6pm'."}
                return _sched.reschedule_scheduled(fragment, when)
            except Exception as e:
                return {"status": "error", "message": f"Could not reschedule message: {e}"}

        elif atype == "clear_history":
            import agent
            agent.clear_history()
            try:
                from backend.agent import phase1_runtime
                phase1_runtime.runtime.conversation.clear()
            except Exception:
                pass
            return {"status": "success", "message": "Conversation history cleared"}

        elif atype == "generate_image":
            try:
                import json as _json
                base_dir = os.path.dirname(os.path.abspath(__file__))
                candidates = [
                    os.path.join(base_dir, "config.json"),
                    os.path.join(base_dir, "..", "config.json"),
                    os.path.join(base_dir, "..", "..", "config.json"),
                    os.path.join(os.getcwd(), "config.json")
                ]
                hf_key = ""
                for cfg_path in candidates:
                    resolved = os.path.abspath(cfg_path)
                    if os.path.isfile(resolved):
                        with open(resolved, "r", encoding="utf-8") as f:
                            hf_key = _json.load(f).get("huggingface_api_key", "")
                            if hf_key:
                                break
                from agent import generate_image_huggingface
                return generate_image_huggingface(params.get("prompt", ""), hf_key, params.get("save_name", ""))
            except Exception as e:
                return {"status": "error", "message": str(e)}

        else:
            return {"status": "error", "message": f"Unknown action type: {atype}"}

    def _inject_state_data(self, action: ActionSpec, state: TaskState) -> Dict[str, Any]:
        """Inject state data into action parameters based on consumes/produces."""
        params = action.parameters.copy()
        
        # For browser_navigate with source_index, resolve URL from search_results
        if action.type == "browser_navigate" and "source_index" in params:
            source_index = params["source_index"]
            if state.search_results and 0 <= source_index < len(state.search_results):
                params["url"] = state.search_results[source_index].get("url", "")
        
        # For create_docx, inject extracted sources if content is empty
        if action.type == "create_docx" and not params.get("content") and state.extracted_sources:
            content_parts = []
            for src in state.extracted_sources:
                if src.get("text"):
                    content_parts.append(f"Source: {src.get('title', 'Unknown')}")
                    content_parts.append(f"URL: {src.get('url', '')}")
                    content_parts.append("")
                    content_parts.append(src["text"][:3000])
                    content_parts.append("\n---\n")
            if content_parts:
                params["content"] = "\n".join(content_parts)
        
        # For type_in_app, ensure window_title matches active window
        if action.type == "type_in_app" and not params.get("window_title") and state.active_window:
            params["window_title"] = state.active_window
        
        return params

    # ─────────────────────────────────────────────────────────────────────────
    # Desktop automation helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _open_app_wait(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Open an application and wait for its window to appear."""
        app_name = action.get("app_name", "").lower().strip()
        window_title = action.get("window_title", app_name)

        # Map friendly names to executables
        APP_MAP = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "paint": "mspaint.exe",
            "cmd": "cmd.exe",
            "command prompt": "cmd.exe",
            "explorer": "explorer.exe",
            "task manager": "taskmgr.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "firefox": "firefox.exe",
            "word": "winword.exe",
            "excel": "excel.exe",
            "powerpoint": "powerpnt.exe",
        }

        exe = APP_MAP.get(app_name, app_name)

        import subprocess
        try:
            subprocess.Popen(exe, shell=True)
        except Exception as e:
            # Try launch_any_app as fallback
            from system_ops import launch_any_app
            res = launch_any_app(app_name)
            if res.get("status") == "error":
                return {"status": "error", "message": f"Failed to launch {app_name}: {str(e)}"}

        # Wait for the window to appear (up to 8 seconds)
        import win32gui
        deadline = time.time() + 8
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            found = []
            def cb(hwnd, ctx):
                t = win32gui.GetWindowText(hwnd)
                if t and window_title.lower() in t.lower():
                    ctx.append(t)
            try:
                win32gui.EnumWindows(cb, found)
            except Exception:
                pass
            if found:
                state.active_app = found[0]
                state.active_window = found[0]
                return {"status": "success", "message": f"Launched and found window: {found[0]}"}

        # Window didn't appear in time — return ERROR, not success
        return {"status": "error", "message": f"Launched {app_name} but window '{window_title}' not detected within timeout"}

    async def _type_in_app(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Focus a window and type text into it using pyautogui."""
        window_title = action.get("window_title", "")
        text = action.get("text", "")

        # Focus the window first
        try:
            import win32gui
            import win32con

            target_hwnd = None
            def cb(hwnd, ctx):
                nonlocal target_hwnd
                t = win32gui.GetWindowText(hwnd)
                if t and window_title.lower() in t.lower():
                    target_hwnd = hwnd
            win32gui.EnumWindows(cb, None)

            if target_hwnd:
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(target_hwnd)
                await asyncio.sleep(0.4)
        except Exception:
            pass

        # Type the text
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            await asyncio.sleep(0.2)
            pyautogui.write(text, interval=0.03)
            state.update_context("last_typed_text", text[:200])
            return {"status": "success", "message": f"Typed {len(text)} characters into {window_title}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to type text: {str(e)}"}

    async def _press_key(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Press a key or key combination."""
        key = action.get("key", "")
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            # Handle combos like ctrl+s
            if "+" in key:
                parts = [p.strip() for p in key.split("+")]
                pyautogui.hotkey(*parts)
            else:
                pyautogui.press(key)
            return {"status": "success", "message": f"Pressed key: {key}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to press key {key}: {str(e)}"}

    def _schedule_whatsapp(self, params: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        """Store a WhatsApp message for later delivery (same store as normal mode).

        Accepts contact/message plus send_at (ISO 8601) or time_text
        ('at 6pm', 'in 2 hours'). Falls back to parsing the description.
        """
        from datetime import datetime as _dt
        try:
            from backend.tools import scheduler as _sched
        except Exception as e:
            return {"status": "error", "message": f"Scheduler unavailable: {e}"}
        contact = str(params.get("contact", "")).strip()
        message = str(params.get("message", "")).strip()
        send_at_raw = str(params.get("send_at", "") or params.get("when_text", "") or params.get("time_text", "") or params.get("when", "")).strip()
        when = None
        if send_at_raw:
            try:
                when = _dt.fromisoformat(send_at_raw)
            except Exception:
                when = None
            if when is None:
                try:
                    parsed = _sched.parse_when(send_at_raw)
                    when = parsed["when"] if parsed.get("ok") else None
                except Exception:
                    when = None
        if (not contact or not message or when is None) and params.get("description"):
            try:
                fallback = _sched.parse_scheduled_whatsapp(
                    f"{params.get('description', '')} {contact} {message} {send_at_raw}")
                if fallback and "error" not in fallback:
                    contact = contact or fallback.get("contact", "")
                    message = message or fallback.get("message", "")
                    when = when or fallback.get("when")
            except Exception:
                pass
        if not contact:
            return {"status": "error", "message": "Who should I send the WhatsApp to, sir?"}
        if not message:
            return {"status": "error", "message": "What should the message say, sir?"}
        if when is None:
            return {"status": "error",
                    "message": "I need a time, sir. Try 'at 6pm' or 'in 2 hours'."}
        try:
            saved = _sched.schedule_whatsapp(contact, message, when)
        except Exception as e:
            return {"status": "error", "message": f"Could not schedule message: {e}"}
        if saved.get("status") != "success":
            return {"status": "error", "message": saved.get("message", "Could not schedule, sir.")}
        job = saved.get("job", {})
        try:
            when_s = _sched.describe_when(when)
        except Exception:
            when_s = when.isoformat()
        try:
            state.update_context("scheduled_job", job)
        except Exception:
            pass
        return {"status": "success",
                "message": f"Scheduled, sir. WhatsApp to {contact} {when_s}: {message[:160]}.",
                "job": job}

    async def _calculator_compute(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Open Calculator, type the expression, and verify the result."""
        expression = action.get("expression", "")
        expected = str(action.get("expected", ""))

        # Open Calculator
        import subprocess
        subprocess.Popen("calc.exe", shell=True)
        await asyncio.sleep(2.0)

        # Find and focus Calculator window
        try:
            import win32gui, win32con
            calc_hwnd = None
            def cb(hwnd, ctx):
                nonlocal calc_hwnd
                t = win32gui.GetWindowText(hwnd)
                if "calculator" in t.lower():
                    calc_hwnd = hwnd
            win32gui.EnumWindows(cb, None)
            if calc_hwnd:
                win32gui.ShowWindow(calc_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(calc_hwnd)
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Parse and type the expression using pyautogui key presses
        import pyautogui
        pyautogui.FAILSAFE = False

        # Clean the expression
        expr = expression.strip().replace("×", "*").replace("÷", "/").replace("x", "*")

        # Map characters to pyautogui keys
        char_map = {
            "*": "multiply",
            "/": "divide",
            "+": "add",
            "-": "subtract",
            "=": "return",
        }

        await asyncio.sleep(0.3)
        for ch in expr:
            if ch.isdigit():
                pyautogui.press(ch)
            elif ch in char_map:
                pyautogui.press(char_map[ch])
            elif ch == ".":
                pyautogui.press("decimal")
            elif ch == " ":
                continue
            await asyncio.sleep(0.05)

        # Press Enter to compute
        await asyncio.sleep(0.1)
        pyautogui.press("return")
        await asyncio.sleep(0.5)

        # Try to read the result
        display_value = ""
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(title_re=".*Calculator.*", timeout=3)
            win = app.top_window()
            display = win.child_window(auto_id="CalculatorResults", control_type="Text")
            display_value = display.window_text().replace("Display is", "").strip()
        except Exception:
            display_value = "result"

        state.active_app = "Calculator"
        msg = f"Calculator computed: {expression} = {display_value}"
        if display_value:
            state.update_context("last_calc_result", f"{expression} = {display_value}")
        if expected and expected in display_value.replace(",", ""):
            return {"status": "success", "message": msg, "result": display_value, "verified_result": True}
        elif display_value:
            return {"status": "success", "message": msg, "result": display_value, "verified_result": False}
        else:
            return {"status": "success", "message": f"Expression entered: {expression}", "result": "unknown"}

    # ─────────────────────────────────────────────────────────────────────────
    # File system helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _create_folder(self, action: Dict) -> Dict[str, Any]:
        """Create a folder at an absolute path."""
        path = action.get("path", "")
        if not path:
            return {"status": "error", "message": "No path specified for folder creation"}
        try:
            os.makedirs(path, exist_ok=True)
            if os.path.isdir(path):
                return {"status": "success", "message": f"Folder created: {path}", "path": path}
            return {"status": "error", "message": f"Folder not found after creation: {path}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create folder: {str(e)}"}

    def _write_file(self, action: Dict) -> Dict[str, Any]:
        """Write content to an absolute file path."""
        path = action.get("path", "")
        content = action.get("content", "")
        if not path:
            return {"status": "error", "message": "No path specified for file write"}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            if os.path.isfile(path):
                return {"status": "success", "message": f"File written: {path}", "path": path}
            return {"status": "error", "message": f"File not found after write: {path}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to write file: {str(e)}"}

    def _verify_file(self, action: Dict) -> Dict[str, Any]:
        """Check that a file OR folder exists (verify_file covers both)."""
        path = action.get("path", "")
        if os.path.isfile(path):
            return {"status": "success", "message": f"File confirmed: {path}", "path": path}
        if os.path.isdir(path):
            return {"status": "success", "message": f"Folder confirmed: {path}", "path": path}
        return {"status": "error", "message": f"File NOT found: {path}"}

    async def _create_docx(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Create a Word document using python-docx, synthesizing research content from state with AI."""
        path = action.get("path", "")
        title = action.get("title", "Research Report")
        content = action.get("content", "")
        headings = action.get("headings", [])

        if not path:
            from system_ops import get_documents_dir
            safe_title = re.sub(r'[^\w\-_]', '_', title)
            path = os.path.join(get_documents_dir(), f"{safe_title}.docx")

        if not path.endswith(".docx"):
            path += ".docx"

        from backend.tools.office import Office
        from backend.agent.research_synthesizer import ResearchSynthesizer

        synthesizer = ResearchSynthesizer()

        # If extracted sources exist in state, synthesize them through AI pipeline
        if state.extracted_sources or state.search_results:
            raw_sources = state.extracted_sources if state.extracted_sources else state.search_results

            # 1. Deduplicate sources
            unique_sources = []
            seen_urls = set()
            for src in raw_sources:
                u = (src.get("url") or "").strip().lower()
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    unique_sources.append(src)
                elif not u:
                    unique_sources.append(src)

            if not unique_sources:
                unique_sources = raw_sources

            # 2. Analyze each source
            source_analyses = []
            for src in unique_sources:
                s_title = src.get("title") or src.get("url") or "Web Source"
                s_url = src.get("url") or ""
                s_content = src.get("text") or src.get("snippet") or ""
                analysis = synthesizer.analyze_source(s_title, s_url, s_content)
                source_analyses.append(analysis)

            state.source_analyses = source_analyses

            # Extract clean topic from title or task
            clean_topic = title
            for prefix in ["Research Report:", "Research Report -", "Research:", "Report:"]:
                if clean_topic.startswith(prefix):
                    clean_topic = clean_topic[len(prefix):].strip()
            if not clean_topic:
                clean_topic = state.task or "Research Topic"

            # 3. Cross-source comparison
            comparison = synthesizer.compare_sources(clean_topic, source_analyses)
            state.cross_source_analysis = comparison

            # 4. Deep report synthesis
            target_sections = (
                action.get("target_sections")
                or (getattr(state, "task_metadata", {}).get("target_slides") if getattr(state, "task_metadata", None) else None)
            )
            structured_report = synthesizer.synthesize_research_report(
                topic=clean_topic,
                sources=unique_sources,
                source_analyses=source_analyses,
                comparison=comparison,
                target_sections=target_sections
            )
            state.synthesized_report = structured_report

            try:
                result = await Office.create_docx(
                    title=title,
                    structured_report=structured_report,
                    save_path=path
                )
                if result.get("status") == "success":
                    self._archive_document(path)
                    self._bank_artifact(state, result.get("path", path) or path)
                state.final_outcome_verified = True
                state.final_outcome_data = {"path": path, "title": title, "report": structured_report}
                return result
            except Exception as e:
                return {"status": "error", "message": f"Failed to create synthesized DOCX: {str(e)}"}

        # Legacy / Non-research document generation
        if not content.strip():
            content = f"Report: {title}\n\nGenerated by J.A.R.V.I.S. Agentic System."

        try:
            result = await Office.create_docx(
                content=content,
                title=title,
                headings=headings if headings else ["Executive Summary", "Key Findings", "References"],
                save_path=path
            )
            if result.get("status") == "success":
                self._archive_document(path)
                self._bank_artifact(state, result.get("path", path) or path)
            state.final_outcome_verified = True
            state.final_outcome_data = {"path": path, "title": title}
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to create DOCX: {str(e)}"}

    async def _create_pptx(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Create a PowerPoint presentation using python-pptx.

        When research data exists in state, the deck is synthesized from the
        analyzed research (never raw webpage text) — mirroring how _create_docx
        works. Slides that requested a topic-relevant image get one acquired
        online first, with Hugging Face generation used only as a fallback."""
        path = action.get("path", "")
        title = action.get("title", "Presentation")

        if not path:
            from system_ops import WORK_DIR
            safe_title = re.sub(r'[^\w\-_]', '_', title)
            doc_dir = os.path.join(WORK_DIR, "documents")
            os.makedirs(doc_dir, exist_ok=True)
            path = os.path.join(doc_dir, f"{safe_title}.pptx")

        if not path.endswith(".pptx"):
            path += ".pptx"

        try:
            slides = await self._prepare_slides(action, state)
            if not isinstance(slides, list) or not slides:
                if slides is True:
                    return {"status": "ok", "message": "No slides requested for this task.", "path": path}
                return {"status": "error", "message": "create_pptx requires 'slides' to be a list of slide objects."}

            from backend.tools.office import Office
            result = await Office.create_pptx(title=title, slides=slides, save_path=path)
            if result.get("status") == "success":
                self._archive_document(path)
                self._bank_artifact(state, result.get("path", path) or path)
            state.final_outcome_verified = True
            state.final_outcome_data = {"path": path, "title": title, "slide_count": len(slides)}
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to create PowerPoint: {str(e)}"}

    async def _prepare_slides(self, action: Dict, state: TaskState) -> List[Dict[str, Any]]:
        """Decide the final slide structure: synthesized-from-analysis when research
        data exists, otherwise the plan's slides. Then acquire images for any slide
        that genuinely calls for one (online first, HF generation as fallback)."""
        title = action.get("title", "Presentation")
        slides = action.get("slides", []) or []
        if not isinstance(slides, list):
            slides = []

        target_slides = (
            action.get("target_slides")
            or (getattr(state, "task_metadata", {}).get("target_slides") if getattr(state, "task_metadata", None) else None)
            or (len(slides) if len(slides) > 1 else None)
        )

        # Research-backed tasks always synthesize the deck from analyzed content,
        # just like the Word pipeline — planner slides built before extraction
        # cannot reflect the actual information gathered.
        if state.extracted_sources or state.search_results:
            deck = self._synthesize_deck(title, state, target_slides=target_slides)
            if deck and deck.get("slides"):
                slides = deck["slides"]

        if not slides:
            return slides

        slides = await self._acquire_slide_images(slides)
        return slides

    def _synthesize_deck(self, title: str, state: TaskState, target_slides: Optional[int] = None) -> Dict[str, Any]:
        """Run the research analysis pipeline and produce a slide structure."""
        try:
            from backend.agent.research_synthesizer import ResearchSynthesizer
            synthesizer = ResearchSynthesizer()

            raw_sources = state.extracted_sources if state.extracted_sources else state.search_results
            unique_sources = []
            seen_urls = set()
            for src in raw_sources or []:
                u = (src.get("url") or "").strip().lower()
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    unique_sources.append(src)
                elif not u:
                    unique_sources.append(src)
            if not unique_sources:
                unique_sources = raw_sources or []

            source_analyses = []
            for src in unique_sources:
                s_title = src.get("title") or src.get("url") or "Web Source"
                s_url = src.get("url") or ""
                s_content = src.get("text") or src.get("snippet") or ""
                source_analyses.append(synthesizer.analyze_source(s_title, s_url, s_content))
            state.source_analyses = source_analyses

            clean_topic = title
            for prefix in ["Presentation:", "Presentation -", "Research Presentation:", "Deck:"]:
                if clean_topic.startswith(prefix):
                    clean_topic = clean_topic[len(prefix):].strip()
            if not clean_topic.strip():
                clean_topic = state.task or "Research Topic"

            comparison = synthesizer.compare_sources(clean_topic, source_analyses)
            state.cross_source_analysis = comparison
            return synthesizer.synthesize_presentation(
                clean_topic, unique_sources, source_analyses, comparison, target_slides=target_slides
            )
        except Exception as e:
            print(f"[executor] Deck synthesis skipped ({e})")
            return {}

    async def _acquire_slide_images(self, slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """For slides that requested a topic image (image_subject/image_url), acquire
        a relevant one: explicit URL → online image search → HF generation fallback.
        Never generates an image merely to fill a slot — only when requested."""
        from system_ops import WORK_DIR
        import time as _time

        img_dir = os.path.join(WORK_DIR, "images")
        try:
            os.makedirs(img_dir, exist_ok=True)
        except Exception:
            pass
        hf_key = self._load_hf_key()
        browser = getattr(self, "_browser", None)

        updated = []
        for i, slide in enumerate(slides or [], 1):
            if not isinstance(slide, dict):
                updated.append(slide)
                continue
            subject = slide.get("image_subject")
            explicit_url = slide.get("image_url")
            if not subject and not explicit_url:
                updated.append(slide)
                continue

            img_path = ""

            # 1) Direct image URL provided by the plan (most relevant, zero guessing)
            if explicit_url:
                img_path = await self._download_image_url(explicit_url, img_dir, f"slide{i}")

            # 2) Online image search for the slide's subject (relevant by query)
            if not img_path and browser is not None and getattr(browser, "context", None) is not None:
                try:
                    urls = await browser.search_images(str(subject)[:120])
                    for candidate in urls or []:
                        img_path = await self._download_image_url(candidate, img_dir, f"slide{i}")
                        if img_path:
                            break
                except Exception:
                    pass

            # 3) HF generation — supplement only, and only when the slide asked for a picture
            if not img_path and subject and hf_key:
                try:
                    from agent import generate_image_huggingface
                    prompt = f"Editorial, documentary-style image related to: {subject}. Realistic, relevant, high quality."
                    res = generate_image_huggingface(prompt, hf_key, f"ppt_slide{i}_{int(_time.time())}.png")
                    if res.get("status") == "success":
                        filename = res.get("filename", "")
                        if filename:
                            candidate = os.path.join(WORK_DIR, filename.replace("/", os.sep))
                            if os.path.isfile(candidate):
                                img_path = candidate
                except Exception:
                    pass

            slide = dict(slide)
            if img_path:
                slide["image_path"] = img_path
            updated.append(slide)
        return updated

    @staticmethod
    async def _download_image_url(url: str, dest_dir: str, prefix: str) -> str:
        """Download an image to dest_dir. Returns local path on success, else ''."""
        try:
            import requests
            import uuid
            resp = requests.get(url, timeout=12, stream=True,
                                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            if resp.status_code != 200:
                return ""
            ctype = (resp.headers.get("Content-Type", "") or "").lower()
            if not ctype.startswith("image/"):
                return ""
            data = resp.content
            if not data or len(data) > 6 * 1024 * 1024:
                return ""
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
                       "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}
            ext = ext_map.get(ctype, ".jpg")
            path = os.path.join(dest_dir, f"{prefix}_{uuid.uuid4().hex[:8]}{ext}")
            with open(path, "wb") as f:
                f.write(data)
            # python-pptx cannot embed webp — convert to PNG via Pillow when possible
            if ext == ".webp":
                from PIL import Image
                png_path = path[:-5] + ".png"
                Image.open(path).convert("RGB").save(png_path, "PNG")
                try:
                    os.remove(path)
                except Exception:
                    pass
                path = png_path
            return path if os.path.isfile(path) else ""
        except Exception:
            return ""

    def _load_hf_key(self) -> str:
        """Load the configured Hugging Face API key, or '' when unset."""
        try:
            import json as _json
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidates = [
                os.path.join(base_dir, "config.json"),
                os.path.join(base_dir, "..", "config.json"),
                os.path.join(base_dir, "..", "..", "config.json"),
                os.path.join(os.getcwd(), "config.json")
            ]
            for cfg_path in candidates:
                if os.path.isfile(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        key = _json.load(f).get("huggingface_api_key", "")
                    if key:
                        return key
        except Exception:
            pass
        return ""

    @staticmethod
    def _bank_artifact(state: TaskState, path: str) -> None:
        """Append a created artifact path for the final reply evidence."""
        try:
            paths = state.get_context("artifact_paths", []) or []
            if path and path not in paths:
                paths.append(path)
            state.update_context("artifact_paths", paths)
        except Exception:
            pass

    def _archive_document(self, path: str) -> None:
        """Ensure documents/PPTs saved outside work_files are mirrored into
        work_files/documents so the FILES/GALLERY view shows them."""
        try:
            from system_ops import archive_document_artifact
            archive_document_artifact(path)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Browser helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _browser_search(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Search web and store search_results in state."""
        query = action.get("query", "")
        browser = await self._get_browser()
        res = await browser.search(query)
        if res.get("status") == "success":
            state.search_results = res.get("results", [])
            state.current_page_url = res.get("url", "")
            state.current_page_title = res.get("title", "")
        return res

    async def _browser_navigate(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Navigate to a URL or use source_index from state.search_results."""
        browser = await self._get_browser()

        source_index = action.get("source_index")
        url = action.get("url", "")

        if source_index is not None and state.search_results:
            if 0 <= source_index < len(state.search_results):
                src = state.search_results[source_index]
                url = src.get("url", "")
                # Fallback snippet if URL is missing
                if not url and src.get("snippet"):
                    state.extracted_sources.append({
                        "url": "search_snippet",
                        "title": src.get("title", "Search Result"),
                        "text": src.get("snippet", "")
                    })
                    return {"status": "success", "message": f"Used snippet from result {source_index}"}
            else:
                if state.search_results:
                    url = state.search_results[0].get("url", "")

        if not url:
            return {"status": "error", "message": "No URL available for navigation"}

        # Skip redirect wrappers (Scholar/Google/Bing/DuckDuckGo): navigate
        # straight to the destination so verification can match the URL.
        from backend.tools.browser import unwrap_search_url
        url = unwrap_search_url(url)

        res = await browser.open(url)
        if res.get("status") == "success":
            state.current_page_url = url
            state.current_page_title = res.get("title", "")
        return res

    async def _browser_extract(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Extract clean text from current page, deduplicate, and append to state.extracted_sources."""
        browser = await self._get_browser()
        res = await browser.get_page_text()
        if res.get("status") == "success" and res.get("text"):
            text = res.get("text", "").strip()
            source_url = res.get("url") or state.current_page_url or ""
            source_title = res.get("title") or state.current_page_title or "Extracted Web Page"

            if len(text) > 30:
                # Deduplicate: check if URL already in state.extracted_sources
                existing_urls = {s.get("url", "").lower() for s in state.extracted_sources if s.get("url")}
                if source_url.lower() not in existing_urls:
                    source_item = {
                        "url": source_url,
                        "title": source_title,
                        "text": text
                    }
                    state.extracted_sources.append(source_item)
                else:
                    # Update existing source text if longer / better
                    for s in state.extracted_sources:
                        if s.get("url", "").lower() == source_url.lower() and len(text) > len(s.get("text", "")):
                            s["text"] = text
                            s["title"] = source_title
        return res

    def _report_page_finding(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Return a quoted-in-spirit finding selected from extracted page text.

        This is intentionally deterministic: it never invents an answer when a
        page has not supplied matching evidence.
        """
        query = action.get("query", "").strip()
        if not state.extracted_sources:
            return {"status": "error", "message": "No extracted page content is available for the requested finding."}
        source = state.extracted_sources[-1]
        text = source.get("text", "")
        stop_words = {"the", "and", "for", "from", "with", "this", "that", "which", "what", "tell", "shown", "show", "page", "section", "please", "current", "appears", "human", "verification", "wait", "me", "go", "open", "find"}
        terms = [word.lower() for word in re.findall(r"[a-zA-Z0-9.]+", query) if len(word) > 2 and word.lower() not in stop_words]
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        candidates = [line for line in lines if len(line) >= 8]

        def score(line: str) -> int:
            low = line.lower()
            matched = sum(term in low for term in terms)
            # Common evidence indicators are useful only as a ranking boost.
            boost = sum(token in low for token in ("download", "release", "version", "latest"))
            return matched * 10 + boost

        best = max(candidates, key=score, default="")
        if not best or score(best) == 0:
            return {"status": "error", "message": f"The page did not contain a verifiable answer for: {query}"}
        answer = f"From {source.get('title') or source.get('url')}: {best}"
        state.update_context("last_finding", answer)
        return {"status": "success", "message": "Page finding verified", "answer": answer, "source_url": source.get("url", "")}

    # ─────────────────────────────────────────────────────────────────────────
    # Dev Terminal helpers (safe shell / git / tests)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _store_terminal_result(res: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        """Bank truncated output in state for findings/replans; the final
        reply carries a short summary (core.py), not the raw dump."""
        if res.get("stdout"):
            state.update_context("last_shell_output", res["stdout"][-2000:])
            state.update_context("last_shell_command", res.get("command", ""))
            state.update_context("last_shell_exit", res.get("exit_code", -1))
        if res.get("status") == "success":
            state.final_outcome_data = {"command": res.get("command", ""),
                                        "exit_code": res.get("exit_code", 0)}
        return res

    async def _run_shell(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Run a policy-gated shell command (terminal.py enforces safety)."""
        import asyncio as _asyncio
        from backend.tools import terminal as _term
        command = (action.get("command") or "").strip()
        if not command:
            return {"status": "error", "message": "run_shell needs 'command'"}
        workdir = (action.get("workdir") or "").strip()
        timeout_s = int(action.get("timeout_s") or _term.DEFAULT_TIMEOUT_S)
        try:
            res = await _asyncio.to_thread(
                _term.run, command, workdir,
                max(5, min(timeout_s, 600)))
        except Exception as e:
            return {"status": "error", "message": f"Terminal error: {e}"}
        return self._store_terminal_result(res, state)

    async def _run_tests(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Run the pytest suite (longer timeout; still bounded)."""
        import asyncio as _asyncio
        from backend.tools import terminal as _term
        target = (action.get("target") or "").strip()
        extra = (action.get("args") or "").strip()
        timeout_s = int(action.get("timeout_s") or _term.TEST_TIMEOUT_S)
        try:
            res = await _asyncio.to_thread(
                _term.run_tests, target, extra,
                max(30, min(timeout_s, 600)))
        except Exception as e:
            return {"status": "error", "message": f"Test run error: {e}"}
        return self._store_terminal_result(res, state)

    async def _git_op(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Read-only git inspection (status/diff/log/branch/...)."""
        import asyncio as _asyncio
        from backend.tools import terminal as _term
        operation = (action.get("operation") or "status").strip().lower()
        args = (action.get("args") or "").strip()
        try:
            res = await _asyncio.to_thread(_term.git_op, operation, args)
        except Exception as e:
            return {"status": "error", "message": f"Git error: {e}"}
        return self._store_terminal_result(res, state)

    async def _browser_get_title(self) -> Dict[str, Any]:
        """Get the current browser page title."""
        browser = await self._get_browser()
        return await browser.get_page_title()
    async def _browser_extract_search_results(self) -> Dict[str, Any]:
        """Extract clickable search result links from the current Google SERP."""
        browser = await self._get_browser()
        results = await browser.extract_search_results()
        return {"status": "success", "message": f"Found {len(results)} search results", "results": results}

    # ─────────────────────────────────────────────────────────────────────────
    # Browser Pro helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _download_dir(params: Dict[str, Any]) -> str:
        """Resolve the download folder: explicit dir > Desktop > work downloads."""
        from system_ops import get_desktop_path
        explicit = (params.get("save_dir") or params.get("path") or "").strip()
        if explicit and os.path.isdir(explicit):
            return explicit
        if explicit:
            try:
                os.makedirs(explicit, exist_ok=True)
                return explicit
            except Exception:
                pass
        try:
            desktop = get_desktop_path()
            if desktop and os.path.isdir(desktop):
                return desktop
        except Exception:
            pass
        fallback = os.path.abspath(os.path.join(os.getcwd(), "downloads"))
        os.makedirs(fallback, exist_ok=True)
        return fallback

    async def _browser_download(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Download a file via direct URL or via a click-triggered download."""
        browser = await self._get_browser()
        save_dir = self._download_dir(action)
        url = (action.get("url") or "").strip()
        selector = (action.get("selector") or "").strip()
        if url:
            res = await browser.download_file(url, save_dir)
        elif selector:
            res = await browser.download_via_click(selector, save_dir)
        else:
            return {"status": "error",
                    "message": "browser_download needs 'url' or 'selector'"}
        if res.get("status") == "success" and res.get("path"):
            state.update_context("last_download_path", res["path"])
            state.final_outcome_data = {"path": res["path"]}
        return res

    async def _browser_login(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Assisted login: navigate, fill username, then hand to the human.

        Passwords are never filled by the agent. After the username step the
        action reports `human_verification_required` so core pauses and the
        user completes password/2FA/CAPTCHA in the visible browser. On resume
        the follow-up `browser_login_check` verifies the login.
        """
        browser = await self._get_browser()
        url = (action.get("url") or "").strip()
        if url:
            nav = await browser.open(url)
            if nav.get("status") != "success":
                return nav
            state.current_page_url = url
        username = action.get("username", "")
        selector = action.get("username_selector", "")
        if username and selector:
            fill = await browser.fill_login_username(selector, str(username))
            if fill.get("status") != "success":
                return fill
        return {"status": "human_verification_required",
                "message": ("Opened the login page"
                            + (" and entered the username" if username and selector else "")
                            + ". Please complete the password / 2FA / CAPTCHA in the "
                              "browser window, then resume, sir."),
                "page_state": "login",
                "details": {"url": state.current_page_url}}

    async def _browser_login_check(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Verify a human-completed login (called after resume)."""
        browser = await self._get_browser()
        return await browser.check_logged_in()

    async def _browser_parallel_research(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Fan out over explicit URLs: one tab each, extract all, bank sources."""
        browser = await self._get_browser()
        urls = action.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        # Also resolve source_index entries against prior search results.
        indices = action.get("source_indices") or []
        for i in indices:
            try:
                if state.search_results and 0 <= int(i) < len(state.search_results):
                    urls.append(state.search_results[int(i)].get("url", ""))
            except Exception:
                pass
        urls = [u for u in urls if u and u.startswith(("http://", "https://"))]
        if not urls:
            return {"status": "error",
                    "message": "browser_parallel_research needs 'urls' (http(s))"}
        res = await browser.extract_parallel(urls[:5])
        if res.get("status") == "success":
            existing = {s.get("url", "").lower() for s in state.extracted_sources if s.get("url")}
            for src in res.get("sources", []):
                if src.get("url", "").lower() not in existing:
                    state.extracted_sources.append({
                        "url": src.get("url", ""),
                        "title": src.get("title", ""),
                        "text": src.get("text", ""),
                    })
        return res

    async def _browser_extract_table(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Extract page tables and save the largest one as CSV."""
        import csv
        browser = await self._get_browser()
        res = await browser.extract_tables()
        if res.get("status") != "success" or not res.get("tables"):
            return res
        tables = res["tables"]
        best = max(tables, key=lambda t: len(t.get("rows", [])))
        filename = (action.get("filename") or "table.csv").strip() or "table.csv"
        if not filename.lower().endswith(".csv"):
            filename += ".csv"
        save_dir = self._download_dir(action)
        path = os.path.join(save_dir, re.sub(r'[<>:"/\\|?*]', "_", filename))
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                if best.get("caption"):
                    writer.writerow([best["caption"]])
                if best.get("headers"):
                    writer.writerow(best["headers"])
                writer.writerows(best.get("rows", []))
        except Exception as e:
            return {"status": "error", "message": f"Failed to save CSV: {str(e)}"}
        state.update_context("last_table_path", path)
        state.update_context("last_table_rows", len(best.get("rows", [])))
        state.final_outcome_data = {"path": path,
                                    "rows": len(best.get("rows", []))}
        return {"status": "success",
                "message": f"Saved {len(best.get('rows', []))} table rows to {path}",
                "path": path, "tables_found": len(tables)}

    # ─────────────────────────────────────────────────────────────────────────
    # Sequence executor
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_sequence(self, actions: List[ActionSpec], state: TaskState) -> List[Dict[str, Any]]:
        """Execute a sequence of actions and return results."""
        results = []
        for action in actions:
            result = await self.execute(action, state)
            results.append(result)
            if result and result.get("status") == "error" and not action.parameters.get("retry", False):
                break
        return results
