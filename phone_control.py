"""
phone_control.py
-----------------
J.A.R.V.I.S. "Phone Control" skill — talks to a connected Android device over
ADB (Android Debug Bridge), and can launch scrcpy to mirror/interact with the
phone in a live window.

SETUP (one-time, done by the user - not by Jarvis):
1. You need the `adb` executable (comes in Android "platform-tools") and,
   optionally, `scrcpy` (only required for the live mirror window — every
   other phone feature works with adb alone).
   - platform-tools: https://developer.android.com/tools/releases/platform-tools
   - scrcpy: https://github.com/Genymobile/scrcpy#get-the-app

2. EITHER add the folder(s) containing adb.exe / scrcpy.exe to your system
   PATH, OR (easier, no PATH editing) create a file named `.env` next to
   main.py in the backend folder with the full path(s), e.g. on Windows:

       JARVIS_ADB_PATH=C:\\Tools\\platform-tools\\adb.exe
       JARVIS_SCRCPY_PATH=C:\\Tools\\scrcpy\\scrcpy.exe

   If JARVIS_ADB_PATH / JARVIS_SCRCPY_PATH aren't set, Jarvis falls back to
   plain `adb` / `scrcpy` and expects them on PATH.

3. On the phone: Settings -> About phone -> tap "Build number" 7 times to
   enable Developer Options, then Settings -> Developer Options -> enable
   "USB debugging".
4. Plug the phone in via USB (or set up wireless ADB) and accept the
   "Allow USB debugging?" prompt on the phone screen.
5. Verify with `adb devices` — the device should show status "device"
   (not "unauthorized" or "offline").

All functions return a dict of the shape {"status": "success"|"error", "message": str, ...}
so main.py can surface consistent responses whether called from natural
language commands or the dedicated /api/phone/* endpoints.
"""

import os
import shutil
import subprocess
import base64
import time
from datetime import datetime

from dotenv import load_dotenv
from system_ops import WORK_DIR

# Load JARVIS_ADB_PATH / JARVIS_SCRCPY_PATH from a .env file next to main.py,
# if present, so the user doesn't have to touch their system PATH at all.
load_dotenv()

ADB_BIN = os.environ.get("JARVIS_ADB_PATH", "adb").strip('"')
SCRCPY_BIN = os.environ.get("JARVIS_SCRCPY_PATH", "scrcpy").strip('"')

# Optional: a default unlock PIN, read from .env, used only if the user
# doesn't supply one directly in the command. SECURITY NOTE: this sits in
# plaintext in your local .env file — fine for a personal machine, but
# never commit .env to source control, and skip this entirely if your
# lock screen is swipe-only (no PIN/pattern needed).
DEFAULT_PHONE_PIN = os.environ.get("JARVIS_PHONE_PIN", "").strip()

PHONE_DIR = os.path.join(WORK_DIR, "phone")
if not os.path.exists(PHONE_DIR):
    os.makedirs(PHONE_DIR)

# Common Android keyevent names Jarvis can send with phone_key
KEYEVENT_MAP = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "enter": "KEYCODE_ENTER",
    "power": "KEYCODE_POWER",
    "menu": "KEYCODE_MENU",
    "app_switch": "KEYCODE_APP_SWITCH",
    "recents": "KEYCODE_APP_SWITCH",
    "camera": "KEYCODE_CAMERA",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "next_track": "KEYCODE_MEDIA_NEXT",
    "prev_track": "KEYCODE_MEDIA_PREVIOUS",
    "tab": "KEYCODE_TAB",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
}


def _binary_available(bin_path: str) -> bool:
    """A binary is 'available' if it's a full path that exists on disk, or a
    bare command name that resolves somewhere on PATH."""
    is_full_path = os.path.sep in bin_path or (len(bin_path) > 1 and bin_path[1] == ":")
    if is_full_path:
        return os.path.isfile(bin_path)
    return shutil.which(bin_path) is not None


def is_adb_installed() -> bool:
    return _binary_available(ADB_BIN)


def is_scrcpy_installed() -> bool:
    return _binary_available(SCRCPY_BIN)


def list_devices() -> dict:
    """List all ADB-visible devices and their connection status."""
    if not is_adb_installed():
        return {
            "status": "error",
            "message": "ADB isn't installed or isn't on your PATH, sir. Install Android platform-tools first."
        }
    try:
        result = subprocess.run([ADB_BIN, "devices", "-l"], capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in result.stdout.strip().splitlines()[1:] if l.strip()]
        devices = []
        for line in lines:
            parts = line.split()
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            devices.append({"serial": serial, "status": state})
        if not devices:
            return {
                "status": "success",
                "message": "No Android devices detected, sir. Check the USB cable and that USB debugging is enabled.",
                "devices": []
            }
        ready = [d for d in devices if d["status"] == "device"]
        if not ready:
            return {
                "status": "success",
                "message": f"Found {len(devices)} device(s) but none are authorized yet, sir — check the phone screen for a debugging prompt.",
                "devices": devices
            }
        return {
            "status": "success",
            "message": f"{len(ready)} device(s) connected and ready, sir.",
            "devices": devices
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to query ADB devices: {str(e)}"}


def get_primary_device() -> str:
    """Return the serial of the first ready ('device' status) phone, or '' if none."""
    res = list_devices()
    for d in res.get("devices", []):
        if d["status"] == "device":
            return d["serial"]
    return ""


def _adb_base(device_id: str = None) -> list:
    cmd = [ADB_BIN]
    if device_id:
        cmd += ["-s", device_id]
    return cmd


def start_mirror(device_id: str = None) -> dict:
    """Launch scrcpy to open a live, interactive mirror window of the phone."""
    if not is_scrcpy_installed():
        return {"status": "error", "message": "scrcpy isn't installed or isn't on your PATH, sir."}
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir. Check the USB connection."}
    try:
        subprocess.Popen([SCRCPY_BIN, "-s", dev])
        return {"status": "success", "message": "Launching the phone mirror window now, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch scrcpy: {str(e)}"}


def take_phone_screenshot(device_id: str = None) -> dict:
    """Capture the phone's current screen and save it to work_files/phone."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir. Check the USB connection."}
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"phone_{timestamp}.png"
        path = os.path.join(PHONE_DIR, filename)
        with open(path, "wb") as f:
            result = subprocess.run(
                _adb_base(dev) + ["exec-out", "screencap", "-p"],
                stdout=f, stderr=subprocess.PIPE, timeout=20
            )
        if result.returncode != 0 or os.path.getsize(path) == 0:
            if os.path.exists(path):
                os.remove(path)
            return {"status": "error", "message": "Failed to capture the phone screen, sir."}
        return {
            "status": "success",
            "message": "Phone screenshot captured, sir.",
            "filename": f"phone/{filename}",
            "path": path
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to capture phone screenshot: {str(e)}"}


def screenshot_as_base64(device_id: str = None) -> dict:
    """Convenience wrapper: capture a phone screenshot and return it base64-encoded
    for immediate preview in the chat UI (mirrors how generated images are returned)."""
    res = take_phone_screenshot(device_id)
    if res["status"] != "success":
        return res
    try:
        with open(res["path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        res["image_base64"] = b64
        return res
    except Exception as e:
        return {"status": "error", "message": f"Captured screenshot but failed to encode it: {str(e)}"}


def tap(x: int, y: int, device_id: str = None) -> dict:
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    try:
        subprocess.run(_adb_base(dev) + ["shell", "input", "tap", str(int(x)), str(int(y))],
                        capture_output=True, timeout=10)
        return {"status": "success", "message": f"Tapped ({x}, {y}) on the phone, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to tap: {str(e)}"}


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, device_id: str = None) -> dict:
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    try:
        subprocess.run(
            _adb_base(dev) + ["shell", "input", "swipe", str(int(x1)), str(int(y1)),
                               str(int(x2)), str(int(y2)), str(int(duration_ms))],
            capture_output=True, timeout=10
        )
        return {"status": "success", "message": f"Swiped from ({x1},{y1}) to ({x2},{y2}), sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to swipe: {str(e)}"}


def input_text(text: str, device_id: str = None) -> dict:
    """Type text into whatever field is currently focused on the phone."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    try:
        # adb's `input text` requires spaces to be escaped as %s
        escaped = text.replace(" ", "%s")
        subprocess.run(_adb_base(dev) + ["shell", "input", "text", escaped],
                        capture_output=True, timeout=10)
        preview = text[:60] + ("..." if len(text) > 60 else "")
        return {"status": "success", "message": f"Typed on phone: {preview}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to type text: {str(e)}"}


def press_key(key_name: str, device_id: str = None) -> dict:
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    keycode = KEYEVENT_MAP.get((key_name or "").lower().strip())
    if not keycode:
        supported = ", ".join(sorted(KEYEVENT_MAP.keys()))
        return {"status": "error", "message": f"Unsupported key '{key_name}', sir. Supported: {supported}"}
    try:
        subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", keycode],
                        capture_output=True, timeout=10)
        return {"status": "success", "message": f"Sent '{key_name}' to the phone, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to send key: {str(e)}"}


def _get_screen_size(device_id: str = None):
    """Return (width, height) in pixels, or None if it couldn't be read."""
    dev = device_id or get_primary_device()
    if not dev:
        return None
    try:
        result = subprocess.run(_adb_base(dev) + ["shell", "wm", "size"],
                                 capture_output=True, text=True, timeout=10)
        # Typical output: "Physical size: 1080x2400" (sometimes an extra
        # "Override size: ..." line follows — the last line is authoritative)
        line = result.stdout.strip().splitlines()[-1]
        dims = line.split(":")[-1].strip()
        w, h = dims.split("x")
        return int(w), int(h)
    except Exception:
        return None


def _is_locked(device_id: str = None):
    """Best-effort check of whether the phone is currently sitting at the
    keyguard/lock screen. Returns True/False, or None if it couldn't be
    determined on this device/Android version (dumpsys output varies)."""
    dev = device_id or get_primary_device()
    if not dev:
        return None
    try:
        result = subprocess.run(_adb_base(dev) + ["shell", "dumpsys", "window"],
                                 capture_output=True, text=True, timeout=10)
        output = result.stdout
        for line in output.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                if "keyguard" in line.lower():
                    return True
        # If we got window output but no keyguard-focused window, the phone
        # is unlocked (some window has normal app/launcher focus instead).
        if output.strip():
            return False
        return None
    except Exception:
        return None


# ── PIN pad tap calibration ─────────────────────────────────────────────────
# Coordinates are expressed as fractions of screen width/height (not fixed
# pixels), measured from a real device screenshot, so they scale correctly
# to whatever resolution `adb shell wm size` reports. Some lock screens
# (Samsung One UI, MIUI, etc.) run the PIN pad as a hardened custom view
# that ignores synthetic key events entirely and only responds to real
# touch taps — this is the fallback path for exactly that case.
#
# Fine-tune without touching code: set these in your .env file if taps are
# landing slightly off (each is a fraction between 0 and 1):
#   JARVIS_PIN_Y_OFFSET=0.02   (positive = shift every row down, negative = up)
#   JARVIS_PIN_X_OFFSET=0.0    (positive = shift every column right)
_PIN_Y_OFFSET = float(os.environ.get("JARVIS_PIN_Y_OFFSET", "0") or 0)
_PIN_X_OFFSET = float(os.environ.get("JARVIS_PIN_X_OFFSET", "0") or 0)

# Which method to use for entering the PIN: "tap" (calibrated taps on the
# on-screen keypad — works even on hardened keyguards like Samsung/MIUI
# that ignore synthetic key input), "keyevent" (faster, no visible tapping,
# but silently fails on hardened keyguards), or "auto" (try keyevent first,
# fall back to tap only if still locked). Default is "tap" since that's the
# method proven to actually work across the widest range of devices.
# Override in .env if your device supports keyevent-based entry:
#   JARVIS_PIN_METHOD=keyevent   or   JARVIS_PIN_METHOD=auto
_PIN_METHOD = os.environ.get("JARVIS_PIN_METHOD", "tap").strip().lower()

# Whether to swipe up before entering the PIN, to reveal the keyguard's PIN
# pad from a fully-locked/off screen. Most phones need this. Default is ON.
# The swipe geometry below deliberately starts right at the very bottom
# edge and ends well ABOVE the keypad's top row, so the gesture's path
# never crosses through the digit buttons themselves (crossing through them
# mid-swipe risks registering a stray touch on whichever digit the path
# passes over, corrupting the PIN before real entry even starts). Tune via
# .env if your device's keypad sits higher/lower on screen:
#   JARVIS_UNLOCK_SWIPE=false       (disable the swipe entirely)
#   JARVIS_SWIPE_Y_START=0.97       (fraction of height — swipe start point)
#   JARVIS_SWIPE_Y_END=0.15         (fraction of height — swipe end point,
#                                     should be above _PIN_ROW_Y["123"] below)
_DO_UNLOCK_SWIPE = os.environ.get("JARVIS_UNLOCK_SWIPE", "true").strip().lower() not in ("false", "0", "no")
_SWIPE_Y_START = float(os.environ.get("JARVIS_SWIPE_Y_START", "0.97") or 0.97)
_SWIPE_Y_END = float(os.environ.get("JARVIS_SWIPE_Y_END", "0.15") or 0.15)

_PIN_ROW_Y = {  # fraction of screen height for each keypad row
    "123": 0.647,
    "456": 0.736,
    "789": 0.824,
    "0": 0.913,
}
_PIN_COL_X = {  # fraction of screen width for each keypad column
    "left": 0.210,    # 1, 4, 7
    "mid": 0.499,      # 2, 5, 8, 0
    "right": 0.787,    # 3, 6, 9, backspace
}
_PIN_DIGIT_POSITION = {
    "1": ("123", "left"), "2": ("123", "mid"), "3": ("123", "right"),
    "4": ("456", "left"), "5": ("456", "mid"), "6": ("456", "right"),
    "7": ("789", "left"), "8": ("789", "mid"), "9": ("789", "right"),
    "0": ("0", "mid"),
}


def _pin_digit_coords(digit: str, w: int, h: int):
    """Convert a digit ('0'-'9') into absolute (x, y) pixel coordinates on
    the lock screen's numeric keypad, given the device's real screen size."""
    if digit not in _PIN_DIGIT_POSITION:
        return None
    row_key, col_key = _PIN_DIGIT_POSITION[digit]
    y_frac = min(max(_PIN_ROW_Y[row_key] + _PIN_Y_OFFSET, 0), 1)
    x_frac = min(max(_PIN_COL_X[col_key] + _PIN_X_OFFSET, 0), 1)
    return int(w * x_frac), int(h * y_frac)


def test_pin_digit_tap(digit: str, device_id: str = None) -> dict:
    """Tap a single digit on the lock screen PIN pad — for calibration only.
    Wakes (and, if enabled, swipes — same as the real unlock flow) but does
    NOT submit anything, so you can safely check by eye whether the tap
    lands on the right number without risking a wrong-PIN lockout."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    if digit not in _PIN_DIGIT_POSITION:
        return {"status": "error", "message": f"'{digit}' isn't a valid digit 0-9, sir."}
    try:
        subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", "224"],
                        capture_output=True, timeout=10)
        time.sleep(0.5)
        w, h = _get_screen_size(dev) or (1080, 1920)
        if _DO_UNLOCK_SWIPE:
            x_mid = w // 2
            y_start = int(h * _SWIPE_Y_START)
            y_end = int(h * _SWIPE_Y_END)
            subprocess.run(_adb_base(dev) + ["shell", "input", "swipe",
                                              str(x_mid), str(y_start), str(x_mid), str(y_end), "300"],
                            capture_output=True, timeout=10)
            time.sleep(1.0)
        x, y = _pin_digit_coords(digit, w, h)
        subprocess.run(_adb_base(dev) + ["shell", "input", "tap", str(x), str(y)],
                        capture_output=True, timeout=10)
        return {"status": "success",
                "message": f"Tapped where digit '{digit}' should be, sir ({x}, {y} on a {w}x{h} screen). Check the dots on your phone — did one fill in?"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to test-tap: {str(e)}"}


def unlock_phone(pin: str = None, device_id: str = None) -> dict:
    """Wake the phone and, if a PIN is supplied (or a JARVIS_PHONE_PIN
    default is set in .env), enter it. The swipe-up step is OFF by default
    (see _DO_UNLOCK_SWIPE) since on many devices the PIN pad appears
    immediately on wake, and swiping anyway risks a stray touch on the
    keypad. Verifies the result via dumpsys instead of assuming success.

    PIN entry is attempted two ways in sequence:
      1. Keyevents (KEYCODE_0..9) — works on stock/AOSP-style keyguards.
      2. Calibrated taps on the on-screen keypad — works on hardened
         keyguards (Samsung One UI, MIUI, etc.) that ignore synthetic keys.
    """
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}

    pin_to_use = (pin or DEFAULT_PHONE_PIN or "").strip()

    try:
        # 1. Wake the screen (keycode 224 = KEYCODE_WAKEUP)
        subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", "224"],
                        capture_output=True, timeout=10)
        time.sleep(0.5)

        w, h = _get_screen_size(dev) or (1080, 1920)

        # 2. (Optional, default ON) Swipe up to reveal the keyguard's PIN
        # pad — starts at the very bottom edge and ends well above the
        # keypad's top row, so the path never crosses the digit buttons.
        if _DO_UNLOCK_SWIPE:
            x = w // 2
            y_start = int(h * _SWIPE_Y_START)
            y_end = int(h * _SWIPE_Y_END)
            subprocess.run(_adb_base(dev) + ["shell", "input", "swipe",
                                              str(x), str(y_start), str(x), str(y_end), "300"],
                            capture_output=True, timeout=10)
            time.sleep(1.0)  # let the reveal animation fully settle before anything taps the keypad

        still_locked = _is_locked(dev)

        if still_locked is not False and pin_to_use:
            digits = [d for d in pin_to_use if d.isdigit()]

            # Attempt A: keyevents — only if method is "keyevent" or "auto".
            # Skipped entirely under the "tap" default, since keyevents
            # silently do nothing on hardened keyguards (Samsung One UI,
            # MIUI, etc.) and just waste time before falling through to taps.
            if _PIN_METHOD in ("keyevent", "auto"):
                for digit in digits:
                    subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", f"KEYCODE_{digit}"],
                                    capture_output=True, timeout=10)
                    time.sleep(0.15)
                time.sleep(0.2)
                subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", "66"],  # KEYCODE_ENTER
                                capture_output=True, timeout=10)
                time.sleep(0.6)
                still_locked = _is_locked(dev)

            # Attempt B: calibrated taps on the on-screen keypad — used
            # directly under "tap" (default), or as a fallback under "auto"
            # if keyevents didn't work.
            if _PIN_METHOD in ("tap", "auto") and still_locked is not False:
                for digit in digits:
                    coords = _pin_digit_coords(digit, w, h)
                    if not coords:
                        continue
                    dx, dy = coords
                    subprocess.run(_adb_base(dev) + ["shell", "input", "tap", str(dx), str(dy)],
                                    capture_output=True, timeout=10)
                    time.sleep(0.25)
                time.sleep(0.6)
                still_locked = _is_locked(dev)

        if still_locked is True:
            if pin_to_use:
                method_desc = {"tap": "tap-based", "keyevent": "keyevent-based", "auto": "keyevent and tap-based"}.get(_PIN_METHOD, "PIN")
                return {"status": "error",
                        "message": (f"I tried {method_desc} PIN entry but the phone still appears "
                                    "locked, sir — either the PIN is wrong, or the tap coordinates need "
                                    "adjusting. Try \"test tap 5 on phone\" to check alignment, and set "
                                    "JARVIS_PIN_Y_OFFSET / JARVIS_PIN_X_OFFSET in .env if it's off.")}
            woke_desc = "woke the screen and swiped" if _DO_UNLOCK_SWIPE else "woke the screen"
            return {"status": "success",
                    "message": (f"I {woke_desc}, sir, but your lock screen needs a PIN or pattern to fully "
                                "unlock. Tell me the PIN (e.g. \"unlock my phone with pin 1234\"), or set "
                                "JARVIS_PHONE_PIN in .env so I remember it. (Pattern-only lock screens "
                                "aren't supported — switch to a PIN if you want hands-free unlock.)")}

        if still_locked is False:
            return {"status": "success", "message": "Phone unlocked, sir."}

        # Couldn't determine lock state on this device/Android version
        if pin_to_use:
            return {"status": "success",
                    "message": "Unlock sequence completed and PIN entered, sir — I couldn't confirm the lock state on this device model, so please check the screen."}
        seq_desc = "Wake+swipe" if _DO_UNLOCK_SWIPE else "Wake"
        return {"status": "success",
                "message": (f"{seq_desc} sequence completed, sir — I couldn't confirm the lock state on this "
                             "device model. If it's still locked, it likely needs a PIN: tell me the PIN or "
                             "set JARVIS_PHONE_PIN in .env.")}
    except Exception as e:
        return {"status": "error", "message": f"Failed to unlock phone: {str(e)}"}


def send_whatsapp(phone_digits: str, message: str, device_id: str = None) -> dict:
    """Send a WhatsApp message via the phone using an ADB deep-link intent
    (wa.me), then press Enter to submit — same mechanism as whatsapp_ops.py
    uses for desktop, but targeted at the Android device over ADB."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    try:
        import urllib.parse
        encoded_msg = urllib.parse.quote(message)
        url = f"https://wa.me/{phone_digits}?text={encoded_msg}"
        subprocess.run(
            _adb_base(dev) + ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            capture_output=True, timeout=10
        )
        time.sleep(4.5)  # let WhatsApp load and focus the chat input
        subprocess.run(_adb_base(dev) + ["shell", "input", "keyevent", "66"],  # KEYCODE_ENTER
                        capture_output=True, timeout=10)
        return {"status": "success", "message": "WhatsApp message sent on your phone, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to send WhatsApp on phone: {str(e)}"}


def launch_app(package_name: str, device_id: str = None) -> dict:
    """Launch an installed app by its Android package name (e.g. com.whatsapp)."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    if not package_name:
        return {"status": "error", "message": "No package name specified, sir."}
    try:
        result = subprocess.run(
            _adb_base(dev) + ["shell", "monkey", "-p", package_name, "-c",
                               "android.intent.category.LAUNCHER", "1"],
            capture_output=True, text=True, timeout=15
        )
        if "No activities found" in (result.stdout + result.stderr):
            return {"status": "error", "message": f"Couldn't find app '{package_name}' on the phone, sir."}
        return {"status": "success", "message": f"Launched {package_name} on your phone, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch app: {str(e)}"}


def list_installed_packages(device_id: str = None) -> dict:
    """List third-party (user-installed) app package names on the phone."""
    dev = device_id or get_primary_device()
    if not dev:
        return {"status": "error", "message": "No authorized Android device found, sir."}
    try:
        result = subprocess.run(_adb_base(dev) + ["shell", "pm", "list", "packages", "-3"],
                                 capture_output=True, text=True, timeout=15)
        packages = sorted(
            line.replace("package:", "").strip()
            for line in result.stdout.splitlines() if line.strip()
        )
        return {"status": "success", "message": f"{len(packages)} apps found, sir.", "packages": packages}
    except Exception as e:
        return {"status": "error", "message": f"Failed to list apps: {str(e)}"}


def stream_frames(device_id: str = None, fps: float = 4):
    """Generator yielding raw PNG bytes captured repeatedly over ADB, for a
    pseudo-live MJPEG-style mirror. Not real-time video (adb screencap is
    latency-bound, ~3-6fps realistic), but enough for a live side-panel view."""
    dev = device_id or get_primary_device()
    if not dev:
        return
    interval = 1.0 / max(0.5, fps)
    while True:
        try:
            result = subprocess.run(
                _adb_base(dev) + ["exec-out", "screencap", "-p"],
                capture_output=True, timeout=10
            )
            frame = result.stdout
            if frame:
                yield frame
        except Exception:
            pass
        time.sleep(interval)


def ocr_last_screenshot() -> dict:
    """Optional: run OCR on the most recent phone screenshot. Requires the
    'pytesseract' + 'pillow' pip packages AND the Tesseract OCR binary
    installed on the system. Degrades gracefully if unavailable."""
    try:
        # pyrefly: ignore [missing-import]
        import pytesseract
        from PIL import Image
    except ImportError:
        return {
            "status": "error",
            "message": ("OCR needs the 'pytesseract' and 'pillow' packages plus the Tesseract binary, sir. "
                         "Run: pip install pytesseract pillow, and install Tesseract OCR for your OS.")
        }

    if not os.path.exists(PHONE_DIR):
        return {"status": "error", "message": "No phone screenshots taken yet, sir."}

    shots = [f for f in os.listdir(PHONE_DIR) if f.lower().endswith(".png")]
    if not shots:
        return {"status": "error", "message": "No phone screenshots taken yet, sir."}

    shots.sort(key=lambda f: os.path.getmtime(os.path.join(PHONE_DIR, f)), reverse=True)
    latest = os.path.join(PHONE_DIR, shots[0])

    try:
        text = pytesseract.image_to_string(Image.open(latest)).strip()
        if not text:
            return {"status": "success", "message": "No readable text found in the latest phone screenshot, sir.", "text": ""}
        preview = text[:300] + ("..." if len(text) > 300 else "")
        return {"status": "success", "message": f"Text found: {preview}", "text": text}
    except Exception as e:
        return {"status": "error", "message": f"OCR failed: {str(e)}"}
