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

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


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

    # ─────────────────────────────────────────────────────────────────────────
    # Main dispatch
    # ─────────────────────────────────────────────────────────────────────────

    async def execute(self, action: Dict[str, Any], state: TaskState) -> Optional[Dict[str, Any]]:
        """Execute a single action dict and return a result dict."""
        atype = action.get("type", "")

        # ── Desktop / Windows automation ────────────────────────────────────

        if atype == "open_app_wait":
            return await self._open_app_wait(action, state)

        elif atype == "type_in_app":
            return await self._type_in_app(action, state)

        elif atype == "press_key":
            return await self._press_key(action, state)

        elif atype == "calculator_compute":
            return await self._calculator_compute(action, state)

        # ── File system ──────────────────────────────────────────────────────

        elif atype == "create_folder_verified":
            return self._create_folder(action)

        elif atype == "write_file_verified":
            return self._write_file(action)

        elif atype == "verify_file":
            return self._verify_file(action)

        elif atype == "create_docx":
            return await self._create_docx(action, state)

        # ── Browser ─────────────────────────────────────────────────────────

        elif atype == "browser_search":
            return await self._browser_search(action)

        elif atype == "browser_navigate":
            return await self._browser_navigate(action)

        elif atype == "browser_extract":
            return await self._browser_extract(action)

        elif atype == "browser_get_title":
            return await self._browser_get_title()

        elif atype == "browser_extract_search_results":
            return await self._browser_extract_search_results()

        # ── Legacy system_ops actions (passed through unchanged) ─────────────

        elif atype == "speak":
            return {"status": "success", "message": action.get("text", "")}

        elif atype == "open_app":
            app_name = action.get("app_name", "")
            from system_ops import launch_any_app
            return launch_any_app(app_name)

        elif atype == "close_app":
            app_name = action.get("app_name", "")
            from system_ops import close_application
            return close_application(app_name)

        elif atype == "launch_app":
            app_name = action.get("app_name", "")
            from system_ops import launch_any_app
            return launch_any_app(app_name)

        elif atype == "shutdown":
            from system_ops import shutdown_pc
            return shutdown_pc(int(action.get("delay_seconds", 0)))

        elif atype == "restart":
            from system_ops import restart_pc
            return restart_pc(int(action.get("delay_seconds", 0)))

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
            query = action.get("query", "")
            from system_ops import search_web
            return search_web(query)

        elif atype == "weather":
            from system_ops import get_weather
            return get_weather(action.get("city", "London"))

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
            folder_name = action.get("folder_name", "")
            from system_ops import create_folder
            return create_folder(folder_name)

        elif atype == "create_word_doc":
            filename = action.get("filename", "")
            content = action.get("content", "")
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
            return set_clipboard(action.get("text", ""))

        elif atype == "open_url":
            from system_ops import open_url
            return open_url(action.get("url", ""))

        elif atype in ("write_file", "write_file_text"):
            from system_ops import write_file
            return write_file(action.get("filename", ""), action.get("content", ""))

        elif atype == "read_file":
            from system_ops import read_file
            return read_file(action.get("filename", ""))

        elif atype == "delete_file":
            from system_ops import delete_file
            return delete_file(action.get("filename", ""))

        elif atype == "set_timer":
            return {
                "status": "success",
                "message": f"Timer set for {action.get('seconds', 60)} seconds",
                "timer_data": {"seconds": action.get("seconds", 60), "label": action.get("label", "Timer")}
            }

        elif atype == "add_note":
            from datetime import datetime
            try:
                import json as _json
                notes_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "notes.json"))
                notes = []
                if os.path.exists(notes_path):
                    with open(notes_path) as f:
                        notes = _json.load(f)
                note = {"id": int(datetime.now().timestamp() * 1000), "text": action.get("text", ""),
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
                todos_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "todos.json"))
                todos = []
                if os.path.exists(todos_path):
                    with open(todos_path) as f:
                        todos = _json.load(f)
                todo = {"id": int(datetime.now().timestamp() * 1000), "text": action.get("text", ""), "done": False}
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
            return tap(action.get("x", 0), action.get("y", 0))

        elif atype == "phone_swipe":
            from phone_control import swipe
            return swipe(action.get("x1", 0), action.get("y1", 0),
                         action.get("x2", 0), action.get("y2", 0),
                         int(action.get("duration_ms", 300)))

        elif atype == "phone_text":
            from phone_control import input_text
            return input_text(action.get("text", ""))

        elif atype == "phone_key":
            from phone_control import press_key
            return press_key(action.get("key", ""))

        elif atype == "phone_launch_app":
            from phone_control import launch_app
            return launch_app(action.get("package", ""))

        elif atype == "phone_unlock":
            from phone_control import unlock_phone
            return unlock_phone(action.get("pin"))

        elif atype == "phone_test_pin_tap":
            from phone_control import test_pin_digit_tap
            return test_pin_digit_tap(str(action.get("digit", "")))

        elif atype == "send_whatsapp":
            from whatsapp_ops import send_whatsapp_message
            return send_whatsapp_message(action.get("contact", ""), action.get("message", ""))

        elif atype == "send_whatsapp_phone":
            from whatsapp_ops import send_whatsapp_message_via_phone
            return send_whatsapp_message_via_phone(action.get("contact", ""), action.get("message", ""))

        elif atype == "add_whatsapp_contact":
            from whatsapp_ops import add_contact
            return add_contact(action.get("name", ""), action.get("phone", ""))

        elif atype == "clear_history":
            import agent
            agent.conversation_history.clear()
            return {"status": "success", "message": "Conversation history cleared"}

        elif atype == "generate_image":
            try:
                import json as _json
                cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.json"))
                hf_key = ""
                if os.path.exists(cfg_path):
                    with open(cfg_path) as f:
                        hf_key = _json.load(f).get("huggingface_api_key", "")
                from agent import generate_image_huggingface
                return generate_image_huggingface(action.get("prompt", ""), hf_key, action.get("save_name", ""))
            except Exception as e:
                return {"status": "error", "message": str(e)}

        else:
            return {"status": "error", "message": f"Unknown action type: {atype}"}

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
        """Check that a file exists."""
        path = action.get("path", "")
        if os.path.isfile(path):
            return {"status": "success", "message": f"File confirmed: {path}", "path": path}
        return {"status": "error", "message": f"File NOT found: {path}"}

    async def _create_docx(self, action: Dict, state: TaskState) -> Dict[str, Any]:
        """Create a Word document using python-docx."""
        path = action.get("path", "")
        title = action.get("title", "Document")
        content = action.get("content", "")
        headings = action.get("headings", [])

        if not path:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            path = os.path.join(desktop, f"{title.replace(' ', '_')}.docx")

        if not path.endswith(".docx"):
            path += ".docx"

        try:
            from backend.tools.office import Office
            result = await Office.create_docx(
                content=content,
                title=title,
                headings=headings if headings else None,
                save_path=path
            )
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to create DOCX: {str(e)}"}

    # ─────────────────────────────────────────────────────────────────────────
    # Browser helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _browser_search(self, action: Dict) -> Dict[str, Any]:
        """Search Google and return results."""
        query = action.get("query", "")
        browser = await self._get_browser()
        return await browser.search(query)

    async def _browser_navigate(self, action: Dict) -> Dict[str, Any]:
        """Navigate to a URL."""
        url = action.get("url", "")
        browser = await self._get_browser()
        return await browser.open(url)

    async def _browser_extract(self, action: Dict) -> Dict[str, Any]:
        """Extract text from the current page."""
        browser = await self._get_browser()
        result = await browser.get_page_text()
        if result.get("status") == "success":
            # Also get title and URL for citation
            title_res = await browser.get_page_title()
            result["title"] = title_res.get("title", "")
            result["url"] = title_res.get("url", "")
        return result

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
    # Sequence executor
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_sequence(self, actions: List[Dict[str, Any]], state: TaskState) -> List[Dict[str, Any]]:
        """Execute a sequence of actions and return results."""
        results = []
        for action in actions:
            result = await self.execute(action, state)
            results.append(result)
            if result and result.get("status") == "error" and not action.get("retry", False):
                break
        return results