"""
crash_report.py — Startup-crash user reporting for the J.A.R.V.I.S. watchdog.
==============================================================================
Stdlib only. Used by jarvis_watchdog.handle_crash() AFTER a backend crash:

  1. write_crash_summary()  -> "STARTUP CRASH/crash_<ts>.txt" in plain language:
     what happened, why JARVIS crashed, the responsible file + exact lines,
     and what the watchdog will attempt next.
  2. pop_crash_console()    -> opens ONE Windows cmd window showing the crash
     summary. The window then WAITS in place for the repair to finish and
     prints the repair summary in the SAME window (no second popup).
     Returns a token identifying this incident (None when no popup).
  3. archive_fixed_file()   -> after a successful Nemotron repair, stores the
     repaired file copy under "FIXED CRASH FILE/".
  4. show_fix_summary()     -> writes "FIXED CRASH FILE/fix_<token>.txt" which
     the waiting window picks up and displays. Never opens a new window.

Nothing here repairs code — recovery_engine.py remains the only repair path,
and in the watchdog flow it runs copy-only (original file never written).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime

WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
CRASH_DIR = os.path.join(WORKSPACE_ROOT, "STARTUP CRASH")
FIXED_DIR = os.path.join(WORKSPACE_ROOT, "FIXED CRASH FILE")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_print(text: str) -> None:
    """Print without ever crashing on Windows cp1252 consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((str(text) + "\n").encode(enc, errors="replace"))
        sys.stdout.buffer.flush()


def _human_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Plain-language meanings for the most common startup crash errors.
_ERROR_MEANINGS = [
    ("SyntaxError", "a line of Python code is written in a way Python cannot understand (e.g. a missing bracket, quote, or colon)."),
    ("IndentationError", "some lines are indented inconsistently — Python uses indentation to understand code blocks."),
    ("ModuleNotFoundError", "JARVIS tried to import a Python package that is not installed in this environment."),
    ("ImportError", "JARVIS tried to import something that could not be loaded (missing or broken dependency)."),
    ("NameError", "the code refers to a variable or function name that was never defined."),
    ("TypeError", "an operation received a value of the wrong type (e.g. text where a number was expected)."),
    ("AttributeError", "the code tried to use a feature that the object does not have (often after a library update)."),
    ("FileNotFoundError", "JARVIS tried to open a file that does not exist at the expected location."),
    ("PermissionError", "Windows blocked JARVIS from reading or writing a file (permissions/antivirus lock)."),
    ("OSError", "an operating-system level problem (file lock, path, or resource issue)."),
    ("ConnectionError", "a network connection failed during startup (model/API endpoint unreachable)."),
    ("TimeoutError", "something during startup took too long and timed out."),
    ("ValueError", "a function received an inappropriate value during startup."),
    ("KeyError", "the code looked up a setting that is missing (often in config.json)."),
]


def explain_error(error_text: str) -> str:
    """One plain-language line explaining the raw error, plus the raw error."""
    raw = (error_text or "Unknown runtime error").strip()
    for name, meaning in _ERROR_MEANINGS:
        if name in raw:
            return f"{name} — {meaning}\nRaw error: {raw}"
    return f"An unexpected error stopped startup.\nRaw error: {raw}"


def code_excerpt(filepath: str, line: int, radius: int = 10) -> str:
    """Return numbered lines around `line`, marking the culprit with '>>> '."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        try:
            with open(filepath, "r", encoding="utf-16", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            return f"(could not read file: {e})"
    if not lines:
        return "(file is empty)"
    target = max(1, min(int(line or 1), len(lines)))
    out = []
    for i in range(max(1, target - radius), min(len(lines), target + radius) + 1):
        marker = ">>> " if i == target else "    "
        out.append(f"{marker}Line {i}: {lines[i - 1][:220]}")
    return "\n".join(out)


def write_crash_summary(crash_output: str, parsed: dict, incident_no: int) -> str:
    """Write the user-readable crash summary. Returns the .txt path."""
    os.makedirs(CRASH_DIR, exist_ok=True)
    path = os.path.join(CRASH_DIR, f"crash_{_stamp()}.txt")

    target_file = parsed.get("file") or ""
    target_line = parsed.get("line") or 0
    error_text = parsed.get("error") or "Unknown runtime error"
    nice_name = os.path.basename(target_file) if target_file else "could not be identified automatically"

    tail = "\n".join((crash_output or "").strip().splitlines()[-40:])

    body = f"""J.A.R.V.I.S. STARTUP CRASH SUMMARY
==================================
Date/time : {_human_time()}
Incident  : #{incident_no}

1) WHAT HAPPENED
----------------
JARVIS failed while starting up and the watchdog stopped the broken backend
so it cannot keep crashing in a loop. NOTHING was deleted or changed yet —
this file is only a report.

2) WHY DID JARVIS CRASH
-----------------------
{explain_error(error_text)}

3) FILE RESPONSIBLE
-------------------
File : {nice_name}
Full path : {target_file or '(unknown)'}
Line : {target_line or '(unknown)'}

Suspect lines (marked with >>>):
{code_excerpt(target_file, target_line) if target_file else '(no file identified)'}

4) WHAT HAPPENS NEXT (automatic)
--------------------------------
a) This summary was created here: {path}
b) The watchdog sends ONLY the suspect lines above (not your whole project)
   to the NVIDIA repair model.
c) The model returns corrected lines; the watchdog repairs a COPY of the
   file with ONLY that chunk changed and checks the result compiles.
   Your ORIGINAL file in the project is never touched.
d) The repaired file copy is stored under the "FIXED CRASH FILE" folder.
e) The repair summary appears in the SAME command window (it waits for it).

5) LAST OUTPUT BEFORE THE CRASH (technical detail)
--------------------------------------------------
{tail or '(no output captured)'}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


# How long the waiting cmd window polls for the repair result (30 min —
# Nemotron full-file repairs are slow). Poll interval 5s.
_WAIT_TIMEOUT_S = 1800
_WAIT_POLL_S = 5


def _waiting_crash_bat(head_lines: list, token: str) -> str:
    """Crash popup that STAYS OPEN: shows the crash, waits for the repair
    result file, prints it in the same window, then pauses. ASCII-only."""
    os.makedirs(CRASH_DIR, exist_ok=True)
    bat = os.path.join(CRASH_DIR, f"_show_{token}.bat")
    fix_file = os.path.join(FIXED_DIR, f"fix_{token}.txt")
    safe = []
    for ln in head_lines:
        ln = ln.encode("ascii", errors="replace").decode("ascii")
        ln = ln.replace("^", "^^").replace("&", "^&").replace("|", "^|")
        safe.append(f"echo {ln}" if ln.strip() else "echo.")
    script = ["@echo off", f"title JARVIS Crash Report - {token}", *safe]
    script += [
        "echo.",
        "echo Waiting for the automatic repair to finish IN THIS WINDOW...",
        "echo (this can take several minutes - please do not close it)",
        "set ELAPSED=0",
        ":wait",
        f'if exist "{fix_file}" goto done',
        f"timeout /t {_WAIT_POLL_S} /nobreak >nul",
        f"set /a ELAPSED+={_WAIT_POLL_S}",
        f"if %ELAPSED% GEQ {_WAIT_TIMEOUT_S} goto timeout",
        "goto wait",
        ":timeout",
        "echo.",
        "echo Repair is still running or could not complete -",
        "echo please check the watchdog console for details.",
        "pause",
        "exit /b",
        ":done",
        "echo.",
        f'type "{fix_file}"',
        "pause",
    ]
    with open(bat, "w", encoding="utf-8") as f:
        f.write("\r\n".join(script) + "\r\n")
    return bat


def pop_crash_console(summary_path: str, nice_name: str, error_text: str):
    """Pop ONE Windows cmd window with the crash summary; it waits for and
    then shows the repair summary in the SAME window.

    Returns the incident token (str) when a popup was launched, else None.
    Console print happens in both cases.
    """
    lines = [
        "================================================================",
        "  J.A.R.V.I.S. STARTUP CRASH  -  summary created",
        "================================================================",
        "",
        f"  Crash summary file:",
        f"  {summary_path}",
        "",
        f"  Failing file : {nice_name}",
        f"  Error        : {(error_text or '')[:100]}",
        "",
        "  The watchdog will now send the suspect lines to the",
        "  NVIDIA repair model and attempt an automatic fix.",
        "  Your original project file will NOT be modified.",
        "",
    ]
    for ln in lines:
        _safe_print(ln)
    if os.name != "nt":
        return None
    token = _stamp()
    try:
        bat = _waiting_crash_bat(lines, token)
        subprocess.Popen(["cmd", "/c", "start", "", bat],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return token
    except Exception as e:
        _safe_print(f"[crash-report] Could not pop cmd window: {e}")
        return None
    try:
        bat = _popup_bat("JARVIS Crash Report", lines)
        subprocess.Popen(["cmd", "/c", "start", "", bat],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[crash-report] Could not pop cmd window: {e}")
        return False


def archive_fixed_file(target_file: str) -> str:
    """Copy the repaired file into FIXED CRASH FILE/. Returns the copy path."""
    os.makedirs(FIXED_DIR, exist_ok=True)
    base = os.path.basename(target_file)
    stem, ext = os.path.splitext(base)
    dest = os.path.join(FIXED_DIR, f"{stem}_fixed_{_stamp()}{ext or '.py'}")
    with open(target_file, "rb") as src, open(dest, "wb") as out:
        out.write(src.read())
    return dest


def show_fix_summary(archived_path: str, nice_name: str, detail: str,
                     token: str = None) -> str:
    """Write the repair summary where the WAITING crash window picks it up.

    No new window is ever opened: the popup from pop_crash_console() polls
    for FIXED CRASH FILE/fix_<token>.txt and prints it in the same window.
    Returns the summary file path ("" when nothing was written).
    """
    lines = [
        "================================================================",
        "  J.A.R.V.I.S. SELF-HEALING  -  repair summary",
        "================================================================",
        "",
        f"  Repaired file : {nice_name}",
        f"  Saved copy    : {archived_path}",
        "",
        f"  Result : {(detail or 'repaired and validated')[:160]}",
        "",
        "  Your original project file was NOT modified.",
        "  To use the fix, copy the saved file over the original",
        "  yourself after reviewing it. The pre-repair backup is",
        "  also kept under the .backup folder.",
        "",
    ]
    for ln in lines:
        _safe_print(ln)
    # Keep a copy of the summary next to the fixed file for the record.
    try:
        os.makedirs(FIXED_DIR, exist_ok=True)
        # ASCII so the waiting cmd window can TYPE it cleanly.
        ascii_lines = [ln.encode("ascii", errors="replace").decode("ascii")
                       for ln in lines]
        text = f"JARVIS repair summary — {_human_time()}\n\n" + "\n".join(ascii_lines)
        with open(os.path.join(FIXED_DIR, "last_fix_summary.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        if token:
            with open(os.path.join(FIXED_DIR, f"fix_{token}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            return os.path.join(FIXED_DIR, f"fix_{token}.txt")
        return os.path.join(FIXED_DIR, "last_fix_summary.txt")
    except OSError:
        return ""
    try:
        bat = _popup_bat("JARVIS Repair Summary", lines)
        subprocess.Popen(["cmd", "/c", "start", "", bat],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[crash-report] Could not pop cmd window: {e}")
        return False


if __name__ == "__main__":
    demo = {"file": __file__, "line": 1, "error": "SyntaxError: expected ':'"}
    print(write_crash_summary("Traceback (most recent call last):\n  SyntaxError: expected ':'", demo, 1))
