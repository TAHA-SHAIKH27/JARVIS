import asyncio
import pythoncom
import win32gui
import win32api
import win32con
import time
import re
import os
from typing import Any, Dict, Optional, List, Tuple
import pywinauto
from pywinauto import application as py_app
from pywinauto import Desktop

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry
from backend.tools.result_schema import (
    create_computer_result,
    UIElement,
    WindowInfo,
    ScreenObservation,
    ToolResultStatus,
)


class Computer:
    """Windows UI Automation layer using UIA/Win32 with input fallbacks.
    
    Priority order for interactions:
    1. Windows UI Automation (UIA) / accessibility tree
    2. Application-specific semantic controls
    3. Coordinate-based interaction (pyautogui/win32 fallback)
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._mss_instance = None

    def _get_mss(self):
        if not MSS_AVAILABLE:
            return None
        if self._mss_instance is None:
            self._mss_instance = mss.mss()
        return self._mss_instance

    async def open_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        try:
            try:
                py_app.Application().start(app_name)
                return create_computer_result("open_app", ToolResultStatus.SUCCESS.value, f"Opened {app_name} via pywinauto", target=app_name)
            except Exception:
                pass
            from system_ops import open_application
            result = open_application(app_name)
            if result.get("status") == "success":
                return create_computer_result("open_app", ToolResultStatus.SUCCESS.value, result.get("message", f"Opened {app_name}"), target=app_name)
            if app_name.lower().startswith("http"):
                from system_ops import open_url
                open_url(app_name)
                return create_computer_result("open_app", ToolResultStatus.SUCCESS.value, f"Opened {app_name} in browser", target=app_name)
            return create_computer_result("open_app", ToolResultStatus.ERROR.value, f"Could not open {app_name}", target=app_name, recoverable=True)
        except Exception as e:
            return create_computer_result("open_app", ToolResultStatus.ERROR.value, f"Failed to open {app_name}: {str(e)}", target=app_name, recoverable=True)

    async def close_app(self, app_name: str, state: TaskState) -> Dict[str, Any]:
        try:
            from system_ops import close_application
            result = close_application(app_name)
            if result.get("status") == "success":
                return create_computer_result("close_app", ToolResultStatus.SUCCESS.value, result.get("message", f"Closed {app_name}"), target=app_name)
            return create_computer_result("close_app", ToolResultStatus.ERROR.value, result.get("message", f"Failed to close {app_name}"), target=app_name, recoverable=True)
        except Exception as e:
            return create_computer_result("close_app", ToolResultStatus.ERROR.value, f"Failed to close {app_name}: {str(e)}", target=app_name, recoverable=True)

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
            windows = [w["title"] for w in self._visible_windows()]
            return create_computer_result("list_windows", ToolResultStatus.SUCCESS.value, f"Found {len(windows)} windows", data={"windows": windows})
        except Exception as e:
            return create_computer_result("list_windows", ToolResultStatus.ERROR.value, f"Failed to list windows: {str(e)}", recoverable=True)

    async def focus_window(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        try:
            target = (window_title or "").strip()
            if not target:
                return create_computer_result("focus_window", ToolResultStatus.ERROR.value, "Window title is required", target=target, recoverable=False)
            
            # Debug: list visible windows to understand titles
            visible = self._visible_windows()
            # Log for debugging (in tests this will show)
            print(f"[DEBUG] Visible windows: {[w['title'] for w in visible]}")
            
            # Try exact/substring match first
            matched = [w for w in visible if target.casefold() in w["title"].casefold()]
            if not matched:
                # Try matching against class name too
                matched = [w for w in visible if target.casefold() in w.get("class", "").casefold()]
            if not matched:
                # Try partial word match
                target_words = target.split()
                for word in target_words:
                    if len(word) > 2:
                        matched = [w for w in visible if word.casefold() in w["title"].casefold()]
                        if matched:
                            break
            
            if matched:
                hwnd = int(matched[0]["handle"])
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                state.active_window = matched[0]["title"]
                return create_computer_result("focus_window", ToolResultStatus.SUCCESS.value, f"Focused window: {matched[0]['title']}", target=matched[0]["title"])
            
            # Try UIA connect with regex
            try:
                app = py_app.Application(backend="uia").connect(title_re=".*" + re.escape(target) + ".*", timeout=3)
                app.top_window().set_focus()
                state.active_window = target
                return create_computer_result("focus_window", ToolResultStatus.SUCCESS.value, f"Focused window via UIA: {target}", target=target)
            except Exception as uia_err:
                print(f"[DEBUG] UIA connect failed: {uia_err}")
            
            # Try connecting by class name if we know common ones
            class_map = {
                "notepad": "Notepad",
                "calculator": "CalcFrame",
                "paint": "MSPaintApp",
                "explorer": "CabinetWClass",
            }
            if target.lower() in class_map:
                try:
                    app = py_app.Application(backend="uia").connect(class_name=class_map[target.lower()], timeout=3)
                    app.top_window().set_focus()
                    state.active_window = target
                    return create_computer_result("focus_window", ToolResultStatus.SUCCESS.value, f"Focused window via class: {target}", target=target)
                except Exception:
                    pass
            
            return create_computer_result("focus_window", ToolResultStatus.ERROR.value, f"Could not focus window: {target}. Visible: {[w['title'] for w in visible]}", target=target, recoverable=True)
        except Exception as e:
            return create_computer_result("focus_window", ToolResultStatus.ERROR.value, f"Failed to focus window: {str(e)}", target=target, recoverable=True)

    async def inspect_ui(self, target: str = "", state: TaskState = None) -> Dict[str, Any]:
        try:
            elements = self._visible_windows()
            if target:
                for elem in elements:
                    if target.casefold() in elem["title"].casefold() or target.casefold() in elem["class"].casefold():
                        controls = await self._uia_controls_for_window(elem["title"])
                        elem["controls"] = controls
                        return create_computer_result("inspect_ui", ToolResultStatus.SUCCESS.value, f"Inspected window: {elem['title']}", element=elem)
            return create_computer_result("inspect_ui", ToolResultStatus.SUCCESS.value, f"Found {len(elements)} top-level windows", data={"elements": elements[:20]})
        except Exception as e:
            return create_computer_result("inspect_ui", ToolResultStatus.ERROR.value, f"Failed to inspect UI: {str(e)}", recoverable=True)

    async def _uia_controls_for_window(self, window_title: str, limit: int = 100) -> List[UIElement]:
        controls: List[UIElement] = []
        try:
            from pywinauto import Desktop
            # Try to connect to the window
            root = Desktop(backend="uia").window(title_re=".*" + re.escape(window_title) + ".*")
            if not root.exists(timeout=5):
                # Try with class name fallback
                return controls
            
            # Get ALL descendants, not just specific control types
            # This captures more UI elements
            all_descendants = root.descendants()
            print(f"[DEBUG] Found {len(all_descendants)} total descendants for '{window_title}'")
            
            for control in all_descendants[:limit]:
                try:
                    rect = control.rectangle()
                    # Skip zero-size or off-screen elements
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                    ctype = getattr(control.element_info, "control_type", "")
                    cname = control.window_text() or control.class_name() or f"Unnamed_{ctype}"
                    # Only include elements that have some meaningful identity
                    if ctype or cname:
                        controls.append(UIElement(
                            name=cname,
                            role=ctype.lower() if ctype else "unknown",
                            bounds=[rect.left, rect.top, rect.right, rect.bottom],
                            confidence=0.95 if control.is_enabled() else 0.5,
                            source="uia",
                            enabled=bool(control.is_enabled()),
                            class_name=control.class_name(),
                            automation_id=getattr(control.element_info, "automation_id", ""),
                        ))
                except Exception as e:
                    # Silently skip problematic controls
                    pass
        except Exception as e:
            print(f"[DEBUG] _uia_controls_for_window error for '{window_title}': {e}")
            pass
        print(f"[DEBUG] Returning {len(controls)} controls for '{window_title}'")
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
                    element = UIElement(
                        name=control.window_text(),
                        role=getattr(control.element_info, "control_type", "").lower(),
                        bounds=[rect.left, rect.top, rect.right, rect.bottom],
                        confidence=0.95,
                        source="uia",
                        enabled=True,
                        class_name=control.class_name(),
                        automation_id=getattr(control.element_info, "automation_id", ""),
                    )
                    return create_computer_result("find_element", ToolResultStatus.SUCCESS.value, f"Found element: {element.name}", element=element.to_dict())
            except Exception:
                pass
            found = []
            for elem in self._visible_windows():
                if (not target_text or target_text.casefold() in elem["title"].casefold()) and (not target_class or target_class.casefold() in elem["class"].casefold()):
                    found.append(elem)
            if found:
                return create_computer_result("find_element", ToolResultStatus.SUCCESS.value, f"Found window: {found[0]['title']}", element=found[0])
            return create_computer_result("find_element", ToolResultStatus.ERROR.value, "Element not found", recoverable=True)
        except Exception as e:
            return create_computer_result("find_element", ToolResultStatus.ERROR.value, f"Failed to find element: {str(e)}", recoverable=True)

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
                            return create_computer_result("click", ToolResultStatus.SUCCESS.value, f"Clicked UI control: {title}", target=title)
                    except Exception:
                        pass
                rect = element.get("rect")
                if rect and len(rect) == 4:
                    cx = (int(rect[0]) + int(rect[2])) // 2
                    cy = (int(rect[1]) + int(rect[3])) // 2
                    win32api.SetCursorPos((cx, cy))
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
                    return create_computer_result("click", ToolResultStatus.SUCCESS.value, f"Clicked UI control at ({cx}, {cy})", coordinates=[cx, cy])
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
                    return create_computer_result("click", ToolResultStatus.SUCCESS.value, "Clicked on element", coordinates=[cx, cy])
            if x is not None and y is not None:
                win32api.SetCursorPos((int(x), int(y)))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, int(x), int(y), 0, 0)
                return create_computer_result("click", ToolResultStatus.SUCCESS.value, f"Clicked at ({x}, {y})", coordinates=[x, y])
            return create_computer_result("click", ToolResultStatus.ERROR.value, "No click target specified", recoverable=False)
        except Exception as e:
            return create_computer_result("click", ToolResultStatus.ERROR.value, f"Failed to click: {str(e)}", recoverable=True)

    async def type_text(self, text: str, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        try:
            import pyautogui
            target = ""
            if element:
                target = element.get("title") or element.get("text", "")
                if target:
                    try:
                        from pywinauto import Desktop
                        control = Desktop(backend="uia").window(title_re=".*" + re.escape(target) + ".*")
                        if control.exists(timeout=1):
                            control.set_focus()
                    except Exception:
                        pass
            pyautogui.write(str(text or ""), interval=0.01)
            return create_computer_result("type_text", ToolResultStatus.SUCCESS.value, f"Typed {len(str(text or ''))} characters", target=target)
        except Exception as e:
            return create_computer_result("type_text", ToolResultStatus.ERROR.value, f"Failed to type text: {str(e)}", recoverable=True)

    async def press_key(self, key: str, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            normalized = (key or "").strip().lower()
            if "+" in normalized:
                pyautogui.hotkey(*[part.strip() for part in normalized.split("+") if part.strip()])
            else:
                pyautogui.press(normalized)
            return create_computer_result("press_key", ToolResultStatus.SUCCESS.value, f"Pressed key: {key}", target=key)
        except Exception as e:
            return create_computer_result("press_key", ToolResultStatus.ERROR.value, f"Failed to press key: {str(e)}", recoverable=True)

    async def screenshot(self, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            import os
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            os.makedirs(img_dir, exist_ok=True)
            path = os.path.join(img_dir, f"ui_{int(time.time() * 1000)}.png")
            pyautogui.screenshot(path)
            return create_computer_result("screenshot", ToolResultStatus.SUCCESS.value, f"Screenshot saved: {path}", screenshot_path=path)
        except Exception as e:
            return create_computer_result("screenshot", ToolResultStatus.ERROR.value, f"Failed to take screenshot: {str(e)}", recoverable=True)

    async def drag(self, x1: int, y1: int, x2: int, y2: int, state: TaskState) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.moveTo(int(x1), int(y1), duration=0.1)
            pyautogui.dragTo(int(x2), int(y2), duration=0.5, button="left")
            return create_computer_result("drag", ToolResultStatus.SUCCESS.value, f"Dragged from ({x1},{y1}) to ({x2},{y2})", coordinates=[x1, y1, x2, y2])
        except Exception as e:
            return create_computer_result("drag", ToolResultStatus.ERROR.value, f"Failed to drag: {str(e)}", recoverable=True)

    async def scroll(self, amount: int = 0, state: TaskState = None) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.scroll(int(amount))
            return create_computer_result("scroll", ToolResultStatus.SUCCESS.value, f"Scrolled by {amount}")
        except Exception as e:
            return create_computer_result("scroll", ToolResultStatus.ERROR.value, f"Failed to scroll: {str(e)}", recoverable=True)

    async def drag_drop(self, from_element: Dict, to_element: Dict, state: TaskState) -> Dict[str, Any]:
        try:
            def center(element: Dict) -> Optional[tuple]:
                rect = element.get("rect") if element else None
                if rect and len(rect) == 4:
                    return ((int(rect[0]) + int(rect[2])) // 2, (int(rect[1]) + int(rect[3])) // 2)
                return None
            start, end = center(from_element), center(to_element)
            if not start or not end:
                return create_computer_result("drag_drop", ToolResultStatus.ERROR.value, "Drag/drop requires UI elements with bounding rectangles", recoverable=False)
            return await self.drag(start[0], start[1], end[0], end[1], state)
        except Exception as e:
            return create_computer_result("drag_drop", ToolResultStatus.ERROR.value, f"Failed drag drop: {str(e)}", recoverable=True)

    # ════════════════════════════════════════════════════════════════════════
    # NEW: Enhanced Computer Use Engine methods
    # ════════════════════════════════════════════════════════════════════════

    async def get_screen(self, state: TaskState) -> Dict[str, Any]:
        """Capture full screen using mss (efficient) or pyautogui fallback."""
        try:
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            os.makedirs(img_dir, exist_ok=True)
            path = os.path.join(img_dir, f"screen_{int(time.time() * 1000)}.png")

            mss_instance = self._get_mss()
            if mss_instance:
                mss_instance.shot(output=path)
            elif PYAUTOGUI_AVAILABLE:
                import pyautogui
                pyautogui.screenshot(path)
            else:
                return create_computer_result("get_screen", ToolResultStatus.ERROR.value, "No screenshot backend available", recoverable=False)

            return create_computer_result("get_screen", ToolResultStatus.SUCCESS.value, f"Full screen captured: {path}", screenshot_path=path)
        except Exception as e:
            return create_computer_result("get_screen", ToolResultStatus.ERROR.value, f"Failed to capture screen: {str(e)}", recoverable=True)

    async def get_active_window(self, state: TaskState) -> Dict[str, Any]:
        """Get the currently active (foreground) window info."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return create_computer_result("get_active_window", ToolResultStatus.ERROR.value, "No active window", recoverable=True)
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            window_info = WindowInfo(
                handle=str(hwnd),
                title=title,
                class_name=class_name,
                bounds=[rect[0], rect[1], rect[2], rect[3]],
                is_active=True,
            )
            return create_computer_result("get_active_window", ToolResultStatus.SUCCESS.value, f"Active window: {title}", element=window_info.to_dict())
        except Exception as e:
            return create_computer_result("get_active_window", ToolResultStatus.ERROR.value, f"Failed to get active window: {str(e)}", recoverable=True)

    async def inspect_window(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        """Get detailed info about a specific window including all UIA controls."""
        try:
            matched = [w for w in self._visible_windows() if window_title.casefold() in w["title"].casefold()]
            if not matched:
                return create_computer_result("inspect_window", ToolResultStatus.ERROR.value, f"Window not found: {window_title}", recoverable=True)
            
            window = matched[0]
            hwnd = int(window["handle"])
            rect = win32gui.GetWindowRect(hwnd)
            
            controls = await self._uia_controls_for_window(window["title"], limit=100)
            
            window_info = WindowInfo(
                handle=window["handle"],
                title=window["title"],
                class_name=window["class"],
                bounds=[rect[0], rect[1], rect[2], rect[3]],
                is_active=True,
            )
            
            return create_computer_result("inspect_window", ToolResultStatus.SUCCESS.value, f"Inspected window: {window['title']}", 
                element=window_info.to_dict(),
                data={"controls": [c.to_dict() if hasattr(c, 'to_dict') else c for c in controls], "control_count": len(controls)}
            )
        except Exception as e:
            return create_computer_result("inspect_window", ToolResultStatus.ERROR.value, f"Failed to inspect window: {str(e)}", recoverable=True)

    async def inspect_controls(self, window_title: str, control_types: List[str] = None, state: TaskState = None) -> Dict[str, Any]:
        """Get all controls of specific types for a window."""
        try:
            if control_types is None:
                control_types = ["Button", "Edit", "CheckBox", "ComboBox", "ListItem", "MenuItem", "TabItem", "Hyperlink", "Text", "Pane", "ScrollBar", "Slider", "ProgressBar", "TreeItem", "List", "Table", "DataGrid"]
            
            from pywinauto import Desktop
            root = Desktop(backend="uia").window(title_re=".*" + re.escape(window_title) + ".*")
            if not root.exists(timeout=2):
                return create_computer_result("inspect_controls", ToolResultStatus.ERROR.value, f"Window not found: {window_title}", recoverable=True)
            
            controls = []
            for control in root.descendants():
                try:
                    ctype = getattr(control.element_info, "control_type", "")
                    if ctype in control_types:
                        rect = control.rectangle()
                        controls.append(UIElement(
                            name=control.window_text() or control.class_name(),
                            role=ctype.lower(),
                            bounds=[rect.left, rect.top, rect.right, rect.bottom],
                            confidence=0.95 if control.is_enabled() else 0.5,
                            source="uia",
                            enabled=bool(control.is_enabled()),
                            class_name=control.class_name(),
                            automation_id=getattr(control.element_info, "automation_id", ""),
                        ))
                except Exception:
                    pass
            
            return create_computer_result("inspect_controls", ToolResultStatus.SUCCESS.value, f"Found {len(controls)} controls", 
                data={"controls": [c.to_dict() for c in controls], "count": len(controls)}
            )
        except Exception as e:
            return create_computer_result("inspect_controls", ToolResultStatus.ERROR.value, f"Failed to inspect controls: {str(e)}", recoverable=True)

    async def find_ui_element(self, criteria: Dict[str, Any], state: TaskState) -> Dict[str, Any]:
        """Alias for find_element with enhanced search."""
        return await self.find_element(criteria, state)

    async def click_element(self, element: Dict, state: TaskState) -> Dict[str, Any]:
        """Click a UI element found via find_element/find_ui_element."""
        return await self.click(element=element, state=state)

    async def click_coordinates(self, x: int, y: int, state: TaskState) -> Dict[str, Any]:
        """Click at absolute screen coordinates."""
        return await self.click(x=x, y=y, state=state)

    async def double_click(self, x: int = None, y: int = None, element: Dict = None, state: TaskState = None) -> Dict[str, Any]:
        """Double-click at coordinates or on element."""
        try:
            if element:
                rect = element.get("rect")
                if rect and len(rect) == 4:
                    cx = (int(rect[0]) + int(rect[2])) // 2
                    cy = (int(rect[1]) + int(rect[3])) // 2
                    x, y = cx, cy
            
            if x is None or y is None:
                return create_computer_result("double_click", ToolResultStatus.ERROR.value, "No click target specified for double-click", recoverable=False)
            
            if PYAUTOGUI_AVAILABLE:
                import pyautogui
                pyautogui.moveTo(int(x), int(y), duration=0.1)
                pyautogui.doubleClick()
                return create_computer_result("double_click", ToolResultStatus.SUCCESS.value, f"Double-clicked at ({x}, {y})", coordinates=[x, y])
            else:
                win32api.SetCursorPos((int(x), int(y)))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, int(x), int(y), 0, 0)
                time.sleep(0.1)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, int(x), int(y), 0, 0)
                return create_computer_result("double_click", ToolResultStatus.SUCCESS.value, f"Double-clicked at ({x}, {y})", coordinates=[x, y])
        except Exception as e:
            return create_computer_result("double_click", ToolResultStatus.ERROR.value, f"Failed to double-click: {str(e)}", recoverable=True)

    async def move_mouse(self, x: int, y: int, state: TaskState, duration: float = 0.2) -> Dict[str, Any]:
        """Move mouse to coordinates."""
        try:
            if PYAUTOGUI_AVAILABLE:
                import pyautogui
                pyautogui.moveTo(int(x), int(y), duration=duration)
            else:
                win32api.SetCursorPos((int(x), int(y)))
            return create_computer_result("move_mouse", ToolResultStatus.SUCCESS.value, f"Moved mouse to ({x}, {y})", coordinates=[x, y])
        except Exception as e:
            return create_computer_result("move_mouse", ToolResultStatus.ERROR.value, f"Failed to move mouse: {str(e)}", recoverable=True)

    async def hotkey(self, *keys: str, state: TaskState) -> Dict[str, Any]:
        """Press a keyboard shortcut (e.g., 'ctrl', 'c')."""
        try:
            if PYAUTOGUI_AVAILABLE:
                import pyautogui
                pyautogui.hotkey(*keys)
            else:
                # Fallback: press each key with small delays
                for key in keys:
                    await self.press_key(key, state)
                    time.sleep(0.05)
            return create_computer_result("hotkey", ToolResultStatus.SUCCESS.value, f"Pressed hotkey: {'+'.join(keys)}", target="+".join(keys))
        except Exception as e:
            return create_computer_result("hotkey", ToolResultStatus.ERROR.value, f"Failed to press hotkey: {str(e)}", recoverable=True)

    async def wait_for_element(self, criteria: Dict[str, Any], timeout: float = 10.0, state: TaskState = None) -> Dict[str, Any]:
        """Wait for a UI element to appear."""
        start = time.time()
        while time.time() - start < timeout:
            result = await self.find_element(criteria, state)
            if result.get("status") == "success" and result.get("element"):
                return result
            await asyncio.sleep(0.3)
        return create_computer_result("wait_for_element", ToolResultStatus.ERROR.value, f"Element not found within {timeout}s: {criteria}", recoverable=True)

    async def screenshot_region(self, x: int, y: int, width: int, height: int, state: TaskState) -> Dict[str, Any]:
        """Capture a specific screen region."""
        try:
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            os.makedirs(img_dir, exist_ok=True)
            path = os.path.join(img_dir, f"region_{int(time.time() * 1000)}.png")

            mss_instance = self._get_mss()
            if mss_instance:
                monitor = {"left": x, "top": y, "width": width, "height": height}
                mss_instance.shot(output=path, monitor=monitor)
            elif PYAUTOGUI_AVAILABLE and PIL_AVAILABLE:
                import pyautogui
                from PIL import Image
                screenshot = pyautogui.screenshot(region=(x, y, width, height))
                screenshot.save(path)
            else:
                return create_computer_result("screenshot_region", ToolResultStatus.ERROR.value, "No screenshot backend available for region capture", recoverable=False)

            return create_computer_result("screenshot_region", ToolResultStatus.SUCCESS.value, f"Region captured: {path}", screenshot_path=path, data={"region": [x, y, width, height]})
        except Exception as e:
            return create_computer_result("screenshot_region", ToolResultStatus.ERROR.value, f"Failed to capture region: {str(e)}", recoverable=True)

    async def screenshot_window(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        """Capture a specific window."""
        try:
            matched = [w for w in self._visible_windows() if window_title.casefold() in w["title"].casefold()]
            if not matched:
                return create_computer_result("screenshot_window", ToolResultStatus.ERROR.value, f"Window not found: {window_title}", recoverable=True)
            
            hwnd = int(matched[0]["handle"])
            rect = win32gui.GetWindowRect(hwnd)
            return await self.screenshot_region(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], state)
        except Exception as e:
            return create_computer_result("screenshot_window", ToolResultStatus.ERROR.value, f"Failed to capture window: {str(e)}", recoverable=True)

    async def get_window_text(self, window_title: str, state: TaskState) -> Dict[str, Any]:
        """Get all visible text from a window (UIA TextPattern)."""
        try:
            from pywinauto import Desktop
            # Use findwindows to get all matching windows, then pick the first one
            from pywinauto import findwindows
            matches = findwindows.find_elements(
                title_re=".*" + re.escape(window_title) + ".*",
                backend="uia",
                visible_only=True,
                enabled_only=False
            )
            if not matches:
                return create_computer_result("get_window_text", ToolResultStatus.ERROR.value, f"Window not found: {window_title}", recoverable=True)
            
            # Use the first matching window (should be the most recently active)
            root = Desktop(backend="uia").window(handle=matches[0].handle)
            if not root.exists(timeout=2):
                return create_computer_result("get_window_text", ToolResultStatus.ERROR.value, f"Window not accessible: {window_title}", recoverable=True)
            
            texts = []
            for control in root.descendants():
                try:
                    text = control.window_text()
                    if text and text.strip():
                        rect = control.rectangle()
                        texts.append({
                            "text": text.strip(),
                            "control_type": getattr(control.element_info, "control_type", ""),
                            "rect": [rect.left, rect.top, rect.right, rect.bottom],
                        })
                except Exception:
                    pass
            
            return create_computer_result("get_window_text", ToolResultStatus.SUCCESS.value, f"Found {len(texts)} text elements", data={"texts": texts, "count": len(texts)})
        except Exception as e:
            return create_computer_result("get_window_text", ToolResultStatus.ERROR.value, f"Failed to get window text: {str(e)}", recoverable=True)
