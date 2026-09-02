import asyncio
import pythoncom
import win32gui
import win32api
import win32con
import time
from typing import Any, Dict, Optional, List
import pywinauto
from pywinauto import application as py_app

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


class Computer:
    """Windows UI Automation layer using uiautomation/pywinauto."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def open_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        """Open an application by name using UI Automation."""
        try:
            # Try pywinauto first
            try:
                py_app.Application(app_name).start()
                return {"status": "success", "message": f"Opened {app_name} via pywinauto"}
            except Exception:
                pass

            # Fallback: use system_ops
            from system_ops import open_application
            result = open_application(app_name)
            if result["status"] == "success":
                return result

            # Last resort: webbrowser
            from system_ops import open_url
            if app_name.lower().startswith("http"):
                open_url(app_name)
                return {"status": "success", "message": f"Opened {app_name} in browser"}

            return {"status": "error", "message": f"Could not open {app_name}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open {app_name}: {str(e)}"}

    async def close_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        """Close an application by name."""
        try:
            from system_ops import close_application
            return close_application(app_name)
        except Exception as e:
            return {"status": "error", "message": f"Failed to close {app_name}: {str(e)}"}

    async def list_windows(self, state: TaskState) -> Dict[str, Any]:
        """List all top-level windows."""
        try:
            windows = []
            def enum_handler(hwnd, ctx):
                if win32gui.GetWindowText(hwnd):
                    windows.append(win32gui.GetWindowText(hwnd))
            win32gui.EnumWindows(enum_handler, None)
            return {"status": "success", "windows": windows}
        except Exception as e:
            return {"status": "error", "message": f"Failed to list windows: {str(e)}"}

    async def focus_window(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        """Focus a specific window by title."""
        try:
            pythoncom.CoInitialize()
            try:
                hwnd = win32gui.FindWindow(None, window_title)
                if not hwnd:
                    def enum_handler(h, ctx):
                        if window_title.lower() in win32gui.GetWindowText(h).lower():
                            ctx.append(h)
                    matched_hwnds = []
                    win32gui.EnumWindows(enum_handler, matched_hwnds)
                    if matched_hwnds:
                        hwnd = matched_hwnds[0]
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    return {"status": "success", "message": f"Focused window: {window_title}"}
            except Exception:
                pass
            # Fallback: try pywinauto
            try:
                app = py_app.Application(backend="win32").connect(title_re=".*" + window_title + ".*")
                app.top_window().set_focus()
                return {"status": "success", "message": f"Focused window via pywinauto: {window_title}"}
            except Exception:
                pass
            return {"status": "error", "message": f"Could not focus window: {window_title}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to focus window: {str(e)}"}

    async def inspect_ui(self, target: str = "", state: TaskState = None) -> Dict[str, Any]:
        """Inspect UI elements."""
        try:
            pythoncom.CoInitialize()
            elements = []
            def enum_handler(hwnd, ctx):
                try:
                    text = win32gui.GetWindowText(hwnd)
                    if text:
                        class_name = win32gui.GetClassName(hwnd)
                        elements.append({"handle": str(hwnd), "title": text, "class": class_name})
                except:
                    pass
            win32gui.EnumWindows(enum_handler, None)

            # If target specified, search for it
            if target:
                for elem in elements:
                    if target.lower() in elem["title"].lower() or target.lower() in elem["class"].lower():
                        return {"status": "success", "element": elem}

            return {"status": "success", "elements": elements[:20]}
        except Exception as e:
            return {"status": "error", "message": f"Failed to inspect UI: {str(e)}"}

    async def find_element(self, criteria: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        """Find a UI element by criteria."""
        try:
            pythoncom.CoInitialize()
            target_text = criteria.get("text", "")
            target_class = criteria.get("class", "")

            found_window = []
            def enum_handler(hwnd, ctx):
                try:
                    text = win32gui.GetWindowText(hwnd)
                    cls = win32gui.GetClassName(hwnd)
                    if (not target_text or target_text.lower() in text.lower()) and \
                       (not target_class or target_class.lower() in cls.lower()):
                        found_window.append({"text": text, "class": cls, "handle": str(hwnd)})
                        return False
                except:
                    pass
                return True

            try:
                win32gui.EnumWindows(enum_handler, None)
            except:
                pass

            if found_window:
                return {"status": "success", "element": found_window[0]}
            return {"status": "error", "message": "Element not found"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to find element: {str(e)}"}

    async def click(self, x: int = None, y: int = None, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        """Click at coordinates or on an element."""
        try:
            pythoncom.CoInitialize()
            if element:
                # Click on element
                try:
                    title = element.get("title", "")
                    hwnd = int(element.get("handle")) if element.get("handle") else None
                    if not hwnd and title:
                        hwnd = win32gui.FindWindow(None, title)
                    if hwnd:
                        rect = win32gui.GetWindowRect(hwnd)
                        cx = (rect[0] + rect[2]) // 2
                        cy = (rect[1] + rect[3]) // 2
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        win32api.SetCursorPos((cx, cy))
                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
                        return {"status": "success", "message": "Clicked on element"}
                except Exception as e:
                    return {"status": "error", "message": f"Failed to click element: {str(e)}"}
            elif x is not None and y is not None:
                # Click at coordinates
                win32api.SetCursorPos((x, y))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
                return {"status": "success", "message": f"Clicked at ({x}, {y})"}
            else:
                # Try pywinauto click
                try:
                    import pywinauto
                    app = pywinauto.Application().connect(title="J.A.R.V.I.S.")
                    dlg = app.top_window()
                    dlg.Click()
                    return {"status": "success", "message": "Clicked via pywinauto"}
                except:
                    pass
            return {"status": "error", "message": "No click target specified"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to click: {str(e)}"}

    async def type_text(self, text: str, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        """Type text into an element or at cursor position."""
        try:
            import pyautogui
            if element:
                # Try to focus and type
                try:
                    pythoncom.CoInitialize()
                    title = element.get("title", "")
                    hwnd = int(element.get("handle")) if element.get("handle") else None
                    if not hwnd and title:
                        hwnd = win32gui.FindWindow(None, title)
                    if hwnd:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                except:
                    pass
            pyautogui.write(text, interval=0.01)
            return {"status": "success", "message": f"Typed: {text[:50]}..."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to type text: {str(e)}"}

    async def press_key(self, key: str, state: TaskState) -> Dict[str, Any]:
        """Press a key."""
        try:
            import pyautogui
            pyautogui.press(key)
            return {"status": "success", "message": f"Pressed key: {key}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to press key: {str(e)}"}

    async def screenshot(self, state: TaskState) -> Dict[str, Any]:
        """Take a screenshot."""
        try:
            import pyautogui
            import os
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            if not os.path.exists(img_dir):
                os.makedirs(img_dir)
            filename = f"ui_{int(time.time())}.png"
            path = os.path.join(img_dir, filename)
            pyautogui.screenshot(path)
            return {"status": "success", "message": f"Screenshot saved: {path}", "path": path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to take screenshot: {str(e)}"}

    async def drag(self, x1: int, y1: int, x2: int, y2: int, state: TaskState) -> Dict[str, Any]:
        """Drag from (x1,y1) to (x2,y2)."""
        try:
            import pyautogui
            pyautogui.drag(x2 - x1, y2 - y1, duration=0.5)
            return {"status": "success", "message": f"Dragged from ({x1},{y1}) to ({x2},{y2})"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to drag: {str(e)}"}

    async def scroll(self, amount: int = 0, state: TaskState = None) -> Dict[str, Any]:
        """Scroll by amount."""
        try:
            import pyautogui
            pyautogui.scroll(amount)
            return {"status": "success", "message": f"Scrolled by {amount}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to scroll: {str(e)}"}

    async def drag_drop(self, from_element: Dict, to_element: Dict, state: TaskState) -> Dict[str, Any]:
        """Drag and drop between elements."""
        try:
            # Get coordinates from element texts
            from_x, from_y = 100, 100  # default
            to_x, to_y = 200, 200  # default
            
            # Try to find actual coordinates
            if from_element.get("handle"):
                try:
                    hwnd = int(from_element["handle"])
                    rc = win32gui.GetWindowRect(hwnd)
                    from_x, from_y = rc[0], rc[1]
                except:
                    pass
            
            if to_element.get("handle"):
                try:
                    hwnd = int(to_element["handle"])
                    rc = win32gui.GetWindowRect(hwnd)
                    to_x, to_y = rc[0], rc[1]
                except:
                    pass
            
            return await self.drag(from_x, from_y, to_x, to_y, state)
        except Exception as e:
            return {"status": "error", "message": f"Failed drag drop: {str(e)}"}