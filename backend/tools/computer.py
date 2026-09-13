import asyncio
import pythoncom
import win32gui
import win32api
import win32con
import time
import re
from typing import Any, Dict, Optional, List
import pywinauto
from pywinauto import application as py_app

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


class Computer:
    """Windows UI Automation layer using UIA/Win32 with input fallbacks."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def open_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        try:
            try:
                py_app.Application().start(app_name)
                return {"status": "success", "message": f"Opened {app_name} via pywinauto"}
            except Exception:
                pass
            from system_ops import open_application
            result = open_application(app_name)
            if result.get("status") == "success":
                return result
            if app_name.lower().startswith("http"):
                from system_ops import open_url
                open_url(app_name)
                return {"status": "success", "message": f"Opened {app_name} in browser"}
            return {"status": "error", "message": f"Could not open {app_name}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open {app_name}: {str(e)}"}

    async def close_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        try:
            from system_ops import close_application
            return close_application(app_name)
        except Exception as e:
            return {"status": "error", "message": f"Failed to close {app_name}: {str(e)}"}

    def _visible_windows(self) -> List[Dict[str, Any]]:
        windows: List[Dict[str, Any]] = []
        def enum_handler(hwnd, _ctx):
            try:
                title = win32gui.GetWindowText(hwnd).strip()
                if title and win32gui.IsWindowVisible(hwnd):
                    windows.append({"handle": str(hwnd), "title": title, "class": win32gui.GetClassName(hwnd)})
            except Exception:
                pass
        win32gui.EnumWindows(enum_handler, None)
        return windows

    async def list_windows(self, state: TaskState) -> Dict[str, Any]:
        try:
            return {"status": "success", "windows": [w["title"] for w in self._visible_windows()]}
        except Exception as e:
            return {"status": "error", "message": f"Failed to list windows: {str(e)}"}

    async def focus_window(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        try:
            target = (window_title or "").strip()
            if not target:
                return {"status": "error", "message": "Window title is required"}
            matched = [w for w in self._visible_windows() if target.casefold() in w["title"].casefold()]
            if matched:
                hwnd = int(matched[0]["handle"])
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                state.active_window = matched[0]["title"]
                return {"status": "success", "message": f"Focused window: {matched[0]['title']}"}
            try:
                app = py_app.Application(backend="uia").connect(title_re=".*" + re.escape(target) + ".*", timeout=2)
                app.top_window().set_focus()
                state.active_window = target
                return {"status": "success", "message": f"Focused window via UIA: {target}"}
            except Exception:
                return {"status": "error", "message": f"Could not focus window: {target}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to focus window: {str(e)}"}

    async def inspect_ui(self, target: str = "", state: TaskState = None) -> Dict[str, Any]:
        try:
            elements = self._visible_windows()
            if target:
                for elem in elements:
                    if target.casefold() in elem["title"].casefold() or target.casefold() in elem["class"].casefold():
                        controls = await self._uia_controls_for_window(elem["title"])
                        elem["controls"] = controls
                        return {"status": "success", "element": elem}
            return {"status": "success", "elements": elements[:20]}
        except Exception as e:
            return {"status": "error", "message": f"Failed to inspect UI: {str(e)}"}

    async def _uia_controls_for_window(self, window_title: str, limit: int = 40) -> List[Dict[str, Any]]:
        controls: List[Dict[str, Any]] = []
        try:
            from pywinauto import Desktop
            root = Desktop(backend="uia").window(title_re=".*" + re.escape(window_title) + ".*")
            if not root.exists(timeout=2):
                return controls
            descendants = root.descendants(control_type=("Button", "Edit", "CheckBox", "ComboBox", "ListItem", "MenuItem", "TabItem", "Hyperlink"))
            for control in descendants[:limit]:
                try:
                    rect = control.rectangle()
                    controls.append({
                        "title": control.window_text(),
                        "control_type": getattr(control.element_info, "control_type", ""),
                        "class": control.class_name(),
                        "enabled": bool(control.is_enabled()),
                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                    })
                except Exception:
                    pass
        except Exception:
            pass
        return controls

    async def find_element(self, criteria: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        try:
            target_text = (criteria.get("text") or criteria.get("title") or "").strip()
            target_class = (criteria.get("class") or "").strip()
            control_type = (criteria.get("control_type") or "").strip()
            try:
                from pywinauto import Desktop
                query: Dict[str, Any] = {"visible_only": True, "enabled_only": True}
                if target_text:
                    query["title_re"] = ".*" + re.escape(target_text) + ".*"
                if target_class:
                    query["class_name_re"] = ".*" + re.escape(target_class) + ".*"
                if control_type:
                    query["control_type"] = control_type
                control = Desktop(backend="uia").window(**query)
                if control.exists(timeout=2):
                    rect = control.rectangle()
                    return {"status": "success", "element": {"title": control.window_text(), "text": control.window_text(), "class": control.class_name(), "control_type": getattr(control.element_info, "control_type", ""), "rect": [rect.left, rect.top, rect.right, rect.bottom]}}
            except Exception:
                pass
            found = []
            for elem in self._visible_windows():
                if (not target_text or target_text.casefold() in elem["title"].casefold()) and (not target_class or target_class.casefold() in elem["class"].casefold()):
                    found.append(elem)
            return {"status": "success", "element": found[0]} if found else {"status": "error", "message": "Element not found"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to find element: {str(e)}"}

    async def click(self, x: int = None, y: int = None, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        try:
            if element:
                title = element.get("title") or element.get("text", "")
                control_type = element.get("control_type", "")
                if title:
                    try:
                        from pywinauto import Desktop
                        query = {"visible_only": True, "title_re": ".*" + re.escape(title) + ".*"}
                        if control_type:
                            query["control_type"] = control_type
                        control = Desktop(backend="uia").window(**query)
                        if control.exists(timeout=1):
                            try:
                                control.invoke()
                            except Exception:
                                control.click_input()
                            return {"status": "success", "message": f"Clicked UI control: {title}"}
                    except Exception:
                        pass
                rect = element.get("rect")
                if rect and len(rect) == 4:
                    cx = (int(rect[0]) + int(rect[2])) // 2
                    cy = (int(rect[1]) + int(rect[3])) // 2
                    win32api.SetCursorPos((cx, cy))
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
                    return {"status": "success", "message": f"Clicked UI control at ({cx}, {cy})"}
                hwnd = int(element.get("handle")) if element.get("handle") else None
                if hwnd and win32gui.IsWindow(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
                    rect = win32gui.GetWindowRect(hwnd)
                    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                    win32api.SetCursorPos((cx, cy))
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
                    return {"status": "success", "message": "Clicked on element"}
            if x is not None and y is not None:
                win32api.SetCursorPos((int(x), int(y)))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, int(x), int(y), 0, 0)
                return {"status": "success", "message": f"Clicked at ({x}, {y})"}
            return {"status": "error", "message": "No click target specified"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to click: {str(e)}"}

    async def type_text(self, text: str, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        try:
            import pyautogui
            if element:
                title = element.get("title") or element.get("text", "")
                if title:
                    try:
                        from pywinauto import Desktop
                        control = Desktop(backend="uia").window(title_re=".*" + re.escape(title) + ".*")
                        if control.exists(timeout=1):
                            control.set_focus()
                    except Exception:
                        pass
            pyautogui.write(str(text or ""), interval=0.01)
            return {"status": "success", "message": f"Typed {len(str(text or ''))} characters"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to type text: {str(e)}"}

    async def press_key(self, key: str, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            normalized = (key or "").strip().lower()
            if "+" in normalized:
                pyautogui.hotkey(*[part.strip() for part in normalized.split("+") if part.strip()])
            else:
                pyautogui.press(normalized)
            return {"status": "success", "message": f"Pressed key: {key}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to press key: {str(e)}"}

    async def screenshot(self, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            import os
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            os.makedirs(img_dir, exist_ok=True)
            path = os.path.join(img_dir, f"ui_{int(time.time() * 1000)}.png")
            pyautogui.screenshot(path)
            return {"status": "success", "message": f"Screenshot saved: {path}", "path": path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to take screenshot: {str(e)}"}

    async def drag(self, x1: int, y1: int, x2: int, y2: int, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.moveTo(int(x1), int(y1), duration=0.1)
            pyautogui.dragTo(int(x2), int(y2), duration=0.5, button="left")
            return {"status": "success", "message": f"Dragged from ({x1},{y1}) to ({x2},{y2})"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to drag: {str(e)}"}

    async def scroll(self, amount: int = 0, state: TaskState = None) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.scroll(int(amount))
            return {"status": "success", "message": f"Scrolled by {amount}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to scroll: {str(e)}"}

    async def drag_drop(self, from_element: Dict, to_element: Dict, state: TaskState) -> Dict[str, Any]:
        try:
            def center(element: Dict) -> Optional[tuple]:
                rect = element.get("rect") if element else None
                if rect and len(rect) == 4:
                    return ((int(rect[0]) + int(rect[2])) // 2, (int(rect[1]) + int(rect[3])) // 2)
                return None
            start, end = center(from_element), center(to_element)
            if not start or not end:
                return {"status": "error", "message": "Drag/drop requires UI elements with bounding rectangles"}
            return await self.drag(start[0], start[1], end[0], end[1], state)
        except Exception as e:
            return {"status": "error", "message": f"Failed drag drop: {str(e)}"}
