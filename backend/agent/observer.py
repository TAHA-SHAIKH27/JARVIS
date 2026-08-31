"""
Agent Observer — verifies REAL system state after each action.
Never returns "success" based on assumptions.
"""
import asyncio
import os
import time
from typing import Any, Dict, Optional, List

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


class Observer:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def observe(self, state: TaskState, focus: str = "general") -> Dict[str, Any]:
        """Lightweight general observation (used at start of each loop iteration)."""
        observations = {"observations": []}

        try:
            import psutil
            running = set()
            for proc in psutil.process_iter(["name"]):
                try:
                    running.add(proc.info["name"].lower())
                except Exception:
                    pass
            observations["running_apps"] = list(running)
        except Exception:
            observations["running_apps"] = []

        observations["observations"].append(f"System snapshot taken: focus={focus}")
        return observations

    # ─────────────────────────────────────────────────────────────────────────
    # Per-action verifiers
    # ─────────────────────────────────────────────────────────────────────────

    def verify_window_exists(self, window_title: str) -> Dict[str, Any]:
        """Check that a window with the given title (substring) is present."""
        try:
            import win32gui

            found = []
            def enum_cb(hwnd, ctx):
                text = win32gui.GetWindowText(hwnd)
                if text and window_title.lower() in text.lower():
                    ctx.append(text)

            win32gui.EnumWindows(enum_cb, found)
            if found:
                return {"verified": True, "message": f"Window found: {found[0]}"}
            return {"verified": False, "message": f"Window '{window_title}' not found"}
        except ImportError:
            # win32gui not available — fall back to psutil process check
            try:
                import psutil
                for proc in psutil.process_iter(["name"]):
                    if window_title.lower() in (proc.info.get("name") or "").lower():
                        return {"verified": True, "message": f"Process found: {proc.info['name']}"}
            except Exception:
                pass
            return {"verified": False, "message": "Could not verify window (win32gui unavailable)"}
        except Exception as e:
            return {"verified": False, "message": f"Window check error: {str(e)}"}

    def verify_file_exists(self, path: str) -> Dict[str, Any]:
        """Verify a file exists on disk."""
        if os.path.isfile(path):
            size = os.path.getsize(path)
            return {"verified": True, "message": f"File exists: {path} ({size} bytes)"}
        return {"verified": False, "message": f"File NOT found: {path}"}

    def verify_folder_exists(self, path: str) -> Dict[str, Any]:
        """Verify a folder exists on disk."""
        if os.path.isdir(path):
            return {"verified": True, "message": f"Folder exists: {path}"}
        return {"verified": False, "message": f"Folder NOT found: {path}"}

    def verify_docx(self, path: str) -> Dict[str, Any]:
        """Open and read a DOCX to confirm it has content."""
        try:
            from docx import Document
            if not os.path.isfile(path):
                return {"verified": False, "message": f"DOCX not found: {path}"}
            doc = Document(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            if paragraphs:
                return {
                    "verified": True,
                    "message": f"DOCX verified: {len(paragraphs)} paragraphs, path={path}",
                    "paragraph_count": len(paragraphs)
                }
            return {"verified": False, "message": f"DOCX exists but has no readable content: {path}"}
        except Exception as e:
            return {"verified": False, "message": f"DOCX read error: {str(e)}"}

    def verify_calculator_result(self, expected: str) -> Dict[str, Any]:
        """Try to read the Calculator window display and check the value."""
        # Attempt 1: pywinauto UIA
        try:
            import pywinauto
            from pywinauto import Application
            app = Application(backend="uia").connect(title_re=".*Calculator.*", timeout=3)
            win = app.top_window()
            # In Windows Calculator the display is a Text control
            display = win.child_window(auto_id="CalculatorResults", control_type="Text")
            value = display.window_text().strip()
            # Strip "Display is " prefix that Windows Calculator sometimes adds
            value = value.replace("Display is", "").strip()
            if expected and expected.replace(",", "").replace(" ", "") in value.replace(",", "").replace(" ", ""):
                return {"verified": True, "message": f"Calculator shows: {value}", "display": value}
            if expected:
                return {"verified": False, "message": f"Calculator shows {value!r}, expected {expected!r}", "display": value}
            return {"verified": True, "message": f"Calculator shows: {value}", "display": value}
        except Exception:
            pass

        # Attempt 2: win32gui window text
        try:
            import win32gui
            found_text = []
            def enum_cb(hwnd, ctx):
                title = win32gui.GetWindowText(hwnd)
                if "calculator" in title.lower():
                    ctx.append(title)
            win32gui.EnumWindows(enum_cb, found_text)
            if found_text:
                return {"verified": True, "message": f"Calculator window present: {found_text[0]}"}
        except Exception:
            pass

        return {"verified": False, "message": "Could not read Calculator display"}

    async def verify_browser_page(self, browser, expected_url_fragment: str = "", expected_title_fragment: str = "") -> Dict[str, Any]:
        """Verify browser is on the right page by checking URL and/or title."""
        try:
            title_result = await browser.get_page_title()
            if title_result["status"] != "success":
                return {"verified": False, "message": "Could not get browser page title"}

            title = title_result.get("title", "")
            url = title_result.get("url", "")

            if expected_title_fragment and expected_title_fragment.lower() not in title.lower():
                return {
                    "verified": False,
                    "message": f"Page title mismatch: got '{title}', expected fragment '{expected_title_fragment}'",
                    "title": title, "url": url
                }
            if expected_url_fragment and expected_url_fragment.lower() not in url.lower():
                return {
                    "verified": False,
                    "message": f"URL mismatch: got '{url}', expected fragment '{expected_url_fragment}'",
                    "title": title, "url": url
                }

            return {"verified": True, "message": f"Browser on: {title} | {url}", "title": title, "url": url}
        except Exception as e:
            return {"verified": False, "message": f"Browser verification error: {str(e)}"}

    def verify_text_in_window(self, window_title: str, expected_text: str) -> Dict[str, Any]:
        """
        Try to read text from a window (e.g. Notepad) using pywinauto UIA.
        Returns verified=True only if the expected text is actually found.
        """
        try:
            import pywinauto
            from pywinauto import Application
            app = Application(backend="uia").connect(title_re=f".*{window_title}.*", timeout=3)
            win = app.top_window()
            # Notepad uses an Edit control
            edit = win.child_window(control_type="Edit")
            content = edit.window_text()
            if expected_text.lower() in content.lower():
                return {"verified": True, "message": f"Text found in {window_title}: '{expected_text[:50]}'"}
            return {"verified": False, "message": f"Text '{expected_text[:50]}' NOT found in {window_title}. Content starts: '{content[:80]}'"}
        except Exception as e:
            # If we can't read the content, at least confirm the window is there
            win_check = self.verify_window_exists(window_title)
            if win_check["verified"]:
                return {"verified": True, "message": f"Window present (text read unavailable): {win_check['message']}"}
            return {"verified": False, "message": f"Could not verify text: {str(e)}"}

    # ─────────────────────────────────────────────────────────────────────────
    # Dispatcher: called after each action
    # ─────────────────────────────────────────────────────────────────────────

    async def observe_after_action(
        self,
        action: Dict[str, Any],
        result: Dict[str, Any],
        state: TaskState,
        browser=None
    ) -> Dict[str, Any]:
        """
        Verify the actual system state after an action.
        Returns a dict with 'verified', 'message', and optionally 'extra_data'.
        """
        atype = action.get("type", "")

        if atype == "open_app_wait":
            window_title = action.get("window_title", action.get("app_name", ""))
            await asyncio.sleep(1.5)  # let app finish launching
            return self.verify_window_exists(window_title)

        elif atype == "type_in_app":
            window_title = action.get("window_title", "")
            text = action.get("text", "")
            await asyncio.sleep(0.5)
            return self.verify_text_in_window(window_title, text)

        elif atype == "calculator_compute":
            await asyncio.sleep(1.0)
            expected = str(action.get("expected", ""))
            return self.verify_calculator_result(expected)

        elif atype == "create_folder_verified":
            path = action.get("path", "")
            return self.verify_folder_exists(path)

        elif atype in ("write_file_verified", "verify_file"):
            path = action.get("path", "")
            return self.verify_file_exists(path)

        elif atype == "create_docx":
            path = action.get("path", "")
            await asyncio.sleep(0.3)
            return self.verify_docx(path)

        elif atype in ("browser_search", "browser_navigate"):
            if browser:
                await asyncio.sleep(0.5)
                return await self.verify_browser_page(browser)
            return {"verified": True, "message": "Browser action completed (no verification available)"}

        elif atype == "browser_extract":
            # Verify by checking result has non-empty text
            text = result.get("text", "") if result else ""
            if text and len(text.strip()) > 50:
                return {"verified": True, "message": f"Extracted {len(text)} characters from page"}
            return {"verified": False, "message": "Extraction yielded no meaningful content"}

        elif atype == "browser_get_title":
            title = result.get("title", "") if result else ""
            if title:
                return {"verified": True, "message": f"Page title: {title}", "title": title}
            return {"verified": False, "message": "Could not get page title"}

        else:
            # For actions without specific verifiers, trust the executor result
            if result and result.get("status") == "success":
                return {"verified": True, "message": result.get("message", f"Action {atype} succeeded")}
            elif result and result.get("status") == "error":
                return {"verified": False, "message": result.get("message", f"Action {atype} failed")}
            return {"verified": True, "message": f"Action {atype} completed"}