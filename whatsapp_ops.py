"""
whatsapp_ops.py
----------------
WhatsApp automation for J.A.R.V.I.S.

Contact resolution no longer depends on a JARVIS-owned contact JSON file.
For names, JARVIS opens WhatsApp Desktop/Web and uses WhatsApp's own
contact/new-chat search. For phone numbers, it uses the WhatsApp deep-link
flow directly.
"""

import os
import re
import time
import webbrowser
import urllib.parse

import pyautogui

SEND_DELAY_SECONDS = 4.5
CONTACT_SEARCH_DELAY_SECONDS = 1.5


def _looks_like_phone(text: str) -> bool:
    text = (text or "").strip()
    digits = re.sub(r"[^\d]", "", text)
    return len(digits) >= 8 and bool(re.match(r"^[\d+\s\-()]+$", text))


def _normalize_phone(text: str) -> str:
    return re.sub(r"[^\d+]", "", (text or "").strip())


def _launch_whatsapp() -> bool:
    """Launch WhatsApp Desktop when its protocol handler is installed."""
    try:
        os.startfile("whatsapp:")
        return True
    except Exception:
        return False


def _search_whatsapp_contact(contact: str) -> dict:
    """Open WhatsApp and search its own contact/new-chat picker by name."""
    name = (contact or "").strip()
    if not name:
        return {"status": "error", "message": "You didn't tell me who to message, sir."}

    opened_desktop = _launch_whatsapp()
    if not opened_desktop:
        try:
            webbrowser.open("https://web.whatsapp.com/")
        except Exception as e:
            return {"status": "error", "message": f"I couldn't open WhatsApp, sir: {e}"}

    time.sleep(2.5)

    try:
        # Official WhatsApp Windows shortcut for New Chat.
        pyautogui.hotkey("ctrl", "alt", "n")
        time.sleep(0.8)
        pyautogui.write(name, interval=0.03)
        time.sleep(CONTACT_SEARCH_DELAY_SECONDS)
        pyautogui.press("enter")
        time.sleep(1.5)
    except Exception as e:
        return {
            "status": "error",
            "message": f"I opened WhatsApp but couldn't search for '{name}' automatically: {e}"
        }

    return {"status": "success", "display_name": name, "opened_desktop": opened_desktop}


def _resolve_phone(contact: str) -> dict:
    """Resolve a direct phone number or leave a name for WhatsApp search.

    Names are intentionally not resolved from a local file. WhatsApp itself
    is now the source of truth for contact names.
    """
    contact_clean = (contact or "").strip()
    if not contact_clean:
        return {"status": "error", "message": "You didn't tell me who to message, sir."}

    if _looks_like_phone(contact_clean):
        phone = _normalize_phone(contact_clean)
        if not phone.startswith("+"):
            return {
                "status": "error",
                "message": "Please give me the phone number with a country code, sir (e.g. +91...)."
            }
        return {"status": "success", "phone": phone, "display_name": contact_clean, "is_phone": True}

    return {"status": "success", "display_name": contact_clean, "is_phone": False}


# Compatibility stubs for older planner actions. They no longer create or
# maintain a JARVIS-owned contact file.
def add_contact(name: str, phone: str) -> dict:
    return {
        "status": "error",
        "message": "JARVIS no longer stores WhatsApp contacts locally. WhatsApp's own contacts are searched directly."
    }


def list_contacts() -> dict:
    return {
        "status": "success",
        "contacts": [],
        "message": "JARVIS has no local WhatsApp contact book. WhatsApp is the contact source."
    }


def delete_contact(name: str) -> dict:
    return {
        "status": "error",
        "message": "There is no local JARVIS WhatsApp contact book to delete from, sir."
    }


def send_whatsapp_message(contact: str, message: str, auto_send: bool = True) -> dict:
    """Send a WhatsApp message using a contact name or phone number."""
    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved

    display_name = resolved["display_name"]

    # Direct phone-number flow remains the fastest path.
    if resolved.get("is_phone"):
        phone_digits = resolved["phone"].lstrip("+")
        encoded_msg = urllib.parse.quote(message)
        opened_desktop = True
        try:
            os.startfile(f"whatsapp://send?phone={phone_digits}&text={encoded_msg}")
        except Exception:
            opened_desktop = False
            webbrowser.open(f"https://wa.me/{phone_digits}?text={encoded_msg}")

        if not auto_send:
            return {
                "status": "success",
                "message": f"Opened a WhatsApp chat for {display_name} and pre-filled your message, sir. Review it and press Enter to send."
            }

        time.sleep(SEND_DELAY_SECONDS if opened_desktop else SEND_DELAY_SECONDS + 2.5)
        try:
            pyautogui.press("enter")
        except Exception as e:
            return {
                "status": "success",
                "message": f"Opened the chat for {display_name} and filled your message, but auto-send failed ({e}). Please press Enter manually."
            }
        return {"status": "success", "message": f"Message sent to {display_name} on WhatsApp, sir."}

    # Name flow: search the contact inside WhatsApp itself.
    searched = _search_whatsapp_contact(display_name)
    if searched["status"] == "error":
        return searched

    if not auto_send:
        return {
            "status": "success",
            "message": f"Opened the WhatsApp contact search for {display_name} and selected the matching chat. Review the message before sending, sir."
        }

    try:
        pyautogui.write(message, interval=0.01)
        time.sleep(0.3)
        pyautogui.press("enter")
    except Exception as e:
        return {
            "status": "success",
            "message": f"Opened {display_name}'s WhatsApp chat, but I couldn't type/send automatically ({e}). Please finish it manually."
        }

    return {"status": "success", "message": f"Message sent to {display_name} on WhatsApp, sir."}


def send_whatsapp_message_via_phone(contact: str, message: str) -> dict:
    """Send a WhatsApp message using the connected Android phone (ADB).

    The phone path requires a phone number and does not use a local contact file.
    """
    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved
    if not resolved.get("is_phone"):
        return {
            "status": "error",
            "message": f"For phone/ADB sending, I need the number for {resolved['display_name']}. The phone path does not use a local contact book."
        }

    import phone_control
    phone_digits = resolved["phone"].lstrip("+")
    res = phone_control.send_whatsapp(phone_digits, message)
    if res["status"] == "success":
        res["message"] = f"Message sent to {resolved['display_name']} on WhatsApp via your phone, sir."
    return res
