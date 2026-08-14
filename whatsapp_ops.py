"""
whatsapp_ops.py
----------------
WhatsApp automation for J.A.R.V.I.S. - "open a chat and send a message."

Approach: WhatsApp Desktop (and WhatsApp Web, if the desktop app isn't
installed) registers/handles a `whatsapp://send?phone=<digits>&text=<msg>`
link, which opens directly into a chat with the message pre-filled in the
input box - exactly like clicking a wa.me link. We resolve a contact NAME
to a phone number using a small local contact book stored in
work_files/whatsapp_contacts.json (WhatsApp's own link scheme only
understands phone numbers, not names), open the link, give the app a
moment to load and focus the input box, then simulate pressing Enter to
actually send it.

No official WhatsApp Business API / third-party automation library is
required - this reuses pyautogui, which is already a project dependency.
"""

import os
import re
import json
import time
import webbrowser
import urllib.parse

import pyautogui

WORK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "work_files"))
CONTACTS_FILE = os.path.join(WORK_DIR, "whatsapp_contacts.json")

if not os.path.exists(WORK_DIR):
    os.makedirs(WORK_DIR)

# Seconds to wait after opening the whatsapp:// link before auto-pressing
# Enter, giving the desktop app (or browser tab) time to load and focus
# the chat's message box. WhatsApp Web is noticeably slower than Desktop.
SEND_DELAY_SECONDS = 4.5


# ===== Contact book (name -> phone number) =====

def _load_contacts() -> dict:
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_contacts(contacts: dict):
    try:
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump(contacts, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def list_contacts() -> dict:
    """Return all saved WhatsApp contacts."""
    contacts = _load_contacts()
    return {
        "status": "success",
        "contacts": [
            {"name": c["display_name"], "phone": c["phone"]} for c in contacts.values()
        ]
    }


def add_contact(name: str, phone: str) -> dict:
    """Save or update a contact. Phone must include a country code, e.g. +919876543210."""
    name = (name or "").strip()
    phone_clean = re.sub(r"[^\d+]", "", (phone or "").strip())

    if not name or not phone_clean:
        return {"status": "error", "message": "Both a name and phone number are required, sir."}
    if not phone_clean.startswith("+"):
        return {"status": "error", "message": "Please include the country code, sir (e.g. +91XXXXXXXXXX)."}
    if len(re.sub(r"[^\d]", "", phone_clean)) < 8:
        return {"status": "error", "message": "That phone number looks too short, sir. Please double-check it."}

    contacts = _load_contacts()
    contacts[name.lower()] = {"display_name": name, "phone": phone_clean}
    _save_contacts(contacts)
    return {"status": "success", "message": f"Saved contact {name} ({phone_clean}), sir."}


def delete_contact(name: str) -> dict:
    contacts = _load_contacts()
    key = (name or "").strip().lower()
    if key in contacts:
        del contacts[key]
        _save_contacts(contacts)
        return {"status": "success", "message": f"Removed contact {name}, sir."}
    return {"status": "error", "message": f"No contact named {name} found, sir."}


def _looks_like_phone(text: str) -> bool:
    text = text.strip()
    digits = re.sub(r"[^\d]", "", text)
    return len(digits) >= 8 and bool(re.match(r"^[\d+\s\-()]+$", text))


def _resolve_phone(contact: str) -> dict:
    """Resolve a contact name (fuzzy match against the saved contact book)
    or a raw phone number into a usable phone number."""
    contact_clean = (contact or "").strip()
    if not contact_clean:
        return {"status": "error", "message": "You didn't tell me who to message, sir."}

    if _looks_like_phone(contact_clean):
        phone = re.sub(r"[^\d+]", "", contact_clean)
        if not phone.startswith("+"):
            return {"status": "error", "message": "Please give me the phone number with a country code, sir (e.g. +91...)."}
        return {"status": "success", "phone": phone, "display_name": contact_clean}

    contacts = _load_contacts()
    key = contact_clean.lower()

    if key in contacts:
        c = contacts[key]
        return {"status": "success", "phone": c["phone"], "display_name": c["display_name"]}

    # Fuzzy substring match against saved contacts
    matches = [c for k, c in contacts.items() if key in k or k in key]
    if len(matches) == 1:
        return {"status": "success", "phone": matches[0]["phone"], "display_name": matches[0]["display_name"]}
    if len(matches) > 1:
        names = ", ".join(m["display_name"] for m in matches)
        return {"status": "error", "message": f"I found multiple contacts matching '{contact}', sir: {names}. Please be more specific."}

    return {
        "status": "error",
        "message": (
            f"I don't have a contact named '{contact}' saved, sir. "
            "Add one first with their phone number, including the country code."
        )
    }


# ===== Send flow =====

def send_whatsapp_message(contact: str, message: str, auto_send: bool = True) -> dict:
    """Open WhatsApp Desktop (or WhatsApp Web as a fallback) directly into
    the given contact's chat with the message pre-filled, then simulate
    pressing Enter to actually send it."""

    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved

    phone_digits = resolved["phone"].lstrip("+")
    display_name = resolved["display_name"]
    encoded_msg = urllib.parse.quote(message)

    opened_desktop = True
    try:
        # os.startfile honors registered protocol handlers on Windows.
        # If WhatsApp Desktop is installed, this opens directly to the chat.
        os.startfile(f"whatsapp://send?phone={phone_digits}&text={encoded_msg}")
    except Exception:
        opened_desktop = False
        webbrowser.open(f"https://wa.me/{phone_digits}?text={encoded_msg}")

    if not auto_send:
        return {
            "status": "success",
            "message": f"Opened a chat with {display_name} and pre-filled your message, sir. Review it and press Enter to send."
        }

    # Give the app / browser tab time to load and focus the chat input.
    # WhatsApp Web (fallback path) is slower than the desktop app.
    time.sleep(SEND_DELAY_SECONDS if opened_desktop else SEND_DELAY_SECONDS + 2.5)

    try:
        pyautogui.press("enter")
    except Exception as e:
        return {
            "status": "success",
            "message": (
                f"Opened the chat with {display_name} and filled in your message, sir, "
                f"but I couldn't auto-send it ({str(e)}). Please press Enter manually."
            )
        }

    return {"status": "success", "message": f"Message sent to {display_name} on WhatsApp, sir."}


def send_whatsapp_message_via_phone(contact: str, message: str) -> dict:
    """Send a WhatsApp message using the connected Android phone (ADB deep
    link) instead of WhatsApp Desktop. Reuses the same contact book."""
    if not (message or "").strip():
        return {"status": "error", "message": "No message text was provided, sir."}

    resolved = _resolve_phone(contact)
    if resolved["status"] == "error":
        return resolved

    import phone_control
    phone_digits = resolved["phone"].lstrip("+")
    res = phone_control.send_whatsapp(phone_digits, message)
    if res["status"] == "success":
        res["message"] = f"Message sent to {resolved['display_name']} on WhatsApp via your phone, sir."
    return res
