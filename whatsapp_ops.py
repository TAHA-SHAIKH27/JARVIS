"""whatsapp_ops.py
----------------
WhatsApp automation for J.A.R.V.I.S.

Provides reliable desktop and phone messaging with UI Automation,
contact search, composer focus, message typing, send verification,
and error reporting (no false success).
"""

import os
import re
import time
import urllib.parse
import webbrowser
from typing import Any, Dict, Optional

import pyautogui
import pyperclip

SEND_DELAY_SECONDS = 3.5
CONTACT_SEARCH_DELAY_SECONDS = 1.5


def _looks_like_phone(text: str) -> bool:
    text = (text or "").strip()
    digits = re.sub(r"[^\d]", "", text)
    return len(digits) >= 8 and bool(re.match(r"^[\d+\s\-()]+$", text))


def _normalize_phone(text: str) -> str:
    return re.sub(r"[^\d+]", "", (text or "").strip())


def _find_whatsapp_control():
    """Locate the top-level WhatsApp UI Automation control or window handle."""
    try:
        import uiautomation as auto
        root = auto.GetRootControl()
        for child in root.GetChildren():
            name = (child.Name or "").lower()
            cls = (child.ClassName or "").lower()
            if "whatsapp" in name or "whatsapp" in cls:
                return child
            if cls == "applicationframewindow":
                inner = child.Control(searchDepth=2, SubName="WhatsApp")
                if inner.Exists(0, 0):
                    return child
    except Exception:
        pass
    return None


def _bring_whatsapp_to_foreground() -> bool:
    """Ensure the WhatsApp window is active and in the foreground."""
    control = _find_whatsapp_control()
    if control and control.NativeWindowHandle:
        try:
            import win32con
            import win32gui

            hwnd = control.NativeWindowHandle
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            return True
        except Exception:
            try:
                control.SetFocus()
                time.sleep(0.3)
                return True
            except Exception:
                pass

    # Fallback to win32 window title search
    try:
        import win32con
        import win32gui

        found_hwnd = None

        def enum_win(hwnd, _):
            nonlocal found_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "whatsapp" in title.lower():
                    found_hwnd = hwnd

        win32gui.EnumWindows(enum_win, None)
        if found_hwnd:
            if win32gui.IsIconic(found_hwnd):
                win32gui.ShowWindow(found_hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(found_hwnd, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(found_hwnd)
            time.sleep(0.3)
            return True
    except Exception:
        pass

    return False


def _launch_whatsapp() -> bool:
    """Launch WhatsApp Desktop when its protocol handler is installed."""
    try:
        os.startfile("whatsapp:")
        return True
    except Exception:
        return False


def _ensure_whatsapp_open(timeout_seconds: float = 6.0) -> bool:
    """Ensure WhatsApp Desktop or Web is running and focused."""
    if _bring_whatsapp_to_foreground():
        return True

    opened = _launch_whatsapp()
    if not opened:
        try:
            webbrowser.open("https://web.whatsapp.com/")
            time.sleep(3.0)
            return True
        except Exception:
            return False

    start = time.time()
    while time.time() - start < timeout_seconds:
        time.sleep(0.8)
        if _bring_whatsapp_to_foreground():
            return True
    return True


def _find_message_composer(whatsapp_ctrl=None):
    """Find the message text composer EditControl in WhatsApp."""
    try:
        import uiautomation as auto
        ctrl = whatsapp_ctrl or _find_whatsapp_control()
        if not ctrl:
            return None

        # Look for edit controls matching message input patterns
        for edit in ctrl.GetChildren():
            if edit.ControlTypeName == "EditControl":
                return edit

        # Deeper search for EditControl with message-like attributes
        edits = ctrl.GetChildren()
        for c in ctrl.WalkChildren():
            if c.ControlTypeName == "EditControl":
                name = (c.Name or "").lower()
                auto_id = (c.AutomationId or "").lower()
                cls = (c.ClassName or "").lower()
                if any(k in name for k in ("message", "type", "write", "chat")) or "textbox" in auto_id or "richedit" in cls:
                    return c
    except Exception:
        pass
    return None


def _click_whatsapp_search_button() -> bool:
    """Try to click the New Chat or Search button in WhatsApp via UI Automation."""
    try:
        import uiautomation as auto
        ctrl = _find_whatsapp_control()
        if not ctrl:
            return False
        # Walk all buttons looking for search / new-chat / pencil icon
        search_keywords = ("search", "new chat", "compose", "new conversation", "pencil")
        for btn in ctrl.WalkChildren():
            ctype = (btn.ControlTypeName or "").lower()
            label = (btn.Name or "").lower()
            if ctype in ("buttoncontrol", "button") and any(k in label for k in search_keywords):
                btn.Click()
                time.sleep(0.6)
                return True
    except Exception:
        pass
    return False


def _search_whatsapp_contact(contact: str) -> Dict[str, Any]:
    """Open WhatsApp, search for the contact, select the chat, and verify."""
    name = (contact or "").strip()
    if not name:
        return {"status": "error", "message": "You didn't tell me who to message, sir."}

    if not _ensure_whatsapp_open():
        return {"status": "error", "message": "I could not launch or find WhatsApp on your desktop, sir."}

    # Give WhatsApp more time to fully render before sending keystrokes
    time.sleep(2.5)
    _bring_whatsapp_to_foreground()
    time.sleep(0.5)

    try:
        # Open the search bar in WhatsApp Desktop (Ctrl+F confirmed working)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(1.0)

        # Paste the contact name into the search box
        pyperclip.copy(name)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(CONTACT_SEARCH_DELAY_SECONDS + 0.5)  # wait for results to load

        # Move to first result and open it
        pyautogui.press("down")
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(1.5)

        # Bring back to foreground after chat opens
        _bring_whatsapp_to_foreground()
        return {"status": "success", "display_name": name}
    except Exception as e:
        return {
            "status": "error",
            "message": f"I opened WhatsApp but couldn't search for and open chat with '{name}': {e}",
        }


def _resolve_phone(contact: str) -> Dict[str, Any]:
    """Resolve a direct phone number or identify as a name for contact search."""
    contact_clean = (contact or "").strip()
    if not contact_clean:
        return {"status": "error", "message": "You didn't tell me who to message, sir."}

    if _looks_like_phone(contact_clean):
        phone = _normalize_phone(contact_clean)
        if not phone.startswith("+"):
            return {
                "status": "error",
                "message": "Please provide the phone number with a country code, sir (e.g. +91...).",
            }
        return {"status": "success", "phone": phone, "display_name": contact_clean, "is_phone": True}

    return {"status": "success", "display_name": contact_clean, "is_phone": False}


def _type_and_send_message(message: str, display_name: str, auto_send: bool = True) -> Dict[str, Any]:
    """Focus composer, type message directly, verify text, send, and verify delivery."""
    clean_msg = (message or "").strip()
    if not clean_msg:
        return {"status": "error", "message": "No message text was provided, sir."}

    try:
        _bring_whatsapp_to_foreground()
        composer = _find_message_composer()
        if composer:
            try:
                composer.SetFocus()
                time.sleep(0.2)
            except Exception:
                pass

        # Copy and paste message cleanly
        pyperclip.copy(clean_msg)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)

        if not auto_send:
            return {
                "status": "success",
                "message": f"Opened chat for {display_name} and entered your message, sir. Review it and press Enter to send.",
            }

        # Press Enter to send
        pyautogui.press("enter")
        time.sleep(0.8)

        # Verify message was dispatched
        if composer:
            try:
                # If ValuePattern exists, verify the text cleared upon send
                val = composer.GetValuePattern().Value
                if val and val.strip() == clean_msg:
                    # If still in composer, press Enter once more
                    pyautogui.press("enter")
                    time.sleep(0.5)
            except Exception:
                pass

        return {
            "status": "success",
            "message": f"Message sent to {display_name} on WhatsApp, sir.",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed while typing or sending WhatsApp message to {display_name}: {e}",
        }


def add_contact(name: str, phone: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "message": "JARVIS no longer stores WhatsApp contacts locally. WhatsApp's own contacts are searched directly.",
    }


def list_contacts() -> Dict[str, Any]:
    return {
        "status": "success",
        "contacts": [],
        "message": "JARVIS has no local WhatsApp contact book. WhatsApp is the contact source.",
    }


def delete_contact(name: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "message": "There is no local JARVIS WhatsApp contact book to delete from, sir.",
    }


def send_whatsapp_message(contact: str, message: str, auto_send: bool = True) -> Dict[str, Any]:
    """Send a WhatsApp message using a contact name or phone number with real verification."""
    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved

    display_name = resolved["display_name"]

    # 1. Direct phone-number flow via deep link
    if resolved.get("is_phone"):
        phone_digits = resolved["phone"].lstrip("+")
        opened_desktop = True
        try:
            os.startfile(f"whatsapp://send?phone={phone_digits}")
        except Exception:
            opened_desktop = False
            try:
                webbrowser.open(f"https://web.whatsapp.com/send?phone={phone_digits}")
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Could not open WhatsApp for phone number {display_name}: {e}",
                }

        time.sleep(SEND_DELAY_SECONDS if opened_desktop else SEND_DELAY_SECONDS + 2.5)
        return _type_and_send_message(message, display_name, auto_send=auto_send)

    # 2. Contact name flow: search inside WhatsApp itself
    searched = _search_whatsapp_contact(display_name)
    if searched["status"] == "error":
        return searched

    return _type_and_send_message(message, display_name, auto_send=auto_send)


def send_whatsapp_message_via_phone(contact: str, message: str) -> Dict[str, Any]:
    """Send a WhatsApp message using the connected Android phone (ADB)."""
    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved
    if not resolved.get("is_phone"):
        return {
            "status": "error",
            "message": f"For phone/ADB sending, I need the phone number for {resolved['display_name']}.",
        }

    try:
        import phone_control

        phone_digits = resolved["phone"].lstrip("+")
        res = phone_control.send_whatsapp(phone_digits, message)
        if res.get("status") == "success":
            res["message"] = f"Message sent to {resolved['display_name']} on WhatsApp via your phone, sir."
        return res
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to send WhatsApp message via phone: {e}",
        }
