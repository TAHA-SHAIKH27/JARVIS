"""
crash_report.py — Startup-crash user reporting for the J.A.R.V.I.S. watchdog.
==============================================================================
Stdlib only. Used by jarvis_watchdog.handle_crash() AFTER a backend crash:

  1. write_crash_summary()  -> "STARTUP CRASH/crash_<ts>.txt" in plain language:
     what happened, why JARVIS crashed, the responsible file + exact lines,
     and what the watchdog will attempt next.
  2. pop_crash_console()    -> opens a NEW Windows cmd window showing that the
     crash summary was created (falls back to console print elsewhere).
  3. archive_fixed_file()   -> after a successful Nemotron repair, stores the
     repaired file copy under "FIXED CRASH FILE/".
  4. show_fix_summary()     -> pops a cmd window with the repair summary.

Nothing here repairs code — recovery_engine.py remains the only repair path.
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
c) The model returns corrected lines; the watchdog rewrites the file with
   ONLY that chunk changed and checks the result compiles.
d) The repaired file copy is stored under the "FIXED CRASH FILE" folder.
e) A repair summary is shown to you in a command window.

5) LAST OUTPUT BEFORE THE CRASH (technical detail)
--------------------------------------------------
{tail or '(no output captured)'}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def _popup_bat(title: str, body_lines: list) -> str:
    """Write a .bat next to the report that prints a summary and pauses."""
    os.makedirs(CRASH_DIR, exist_ok=True)
    bat = os.path.join(CRASH_DIR, f"_show_{_stamp()}.bat")
    safe = []
    for ln in body_lines:
        # Batch console is ASCII/cp437: strip anything exotic, escape specials.
        ln = ln.encode("ascii", errors="replace").decode("ascii")
        ln = ln.replace("^", "^^").replace("&", "^&").replace("|", "^|")
        safe.append(f"echo {ln}" if ln.strip() else "echo.")
    content = "@echo off\r\ntitle {} \r\n".format(title) + "\r\n".join(safe) + "\r\npause\r\n"
    with open(bat, "w", encoding="utf-8") as f:
        f.write(content)
    return bat


def pop_crash_console(summary_path: str, nice_name: str, error_text: str) -> bool:
    """Pop a NEW Windows cmd window: crash summary has been created.

    Returns True when a popup was launched, False when falling back to print.
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
        "",
    ]
    for ln in lines:
        _safe_print(ln)
    if os.name != "nt":
        return False
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


def show_fix_summary(archived_path: str, nice_name: str, detail: str) -> bool:
    """Pop a cmd window with the post-repair summary (also prints it)."""
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
        "  The original file was backed up before the change, so",
        "  you can roll back at any time. You can restart JARVIS now.",
        "",
    ]
    for ln in lines:
        _safe_print(ln)
    # Keep a copy of the summary next to the fixed file for the record.
    try:
        with open(os.path.join(FIXED_DIR, "last_fix_summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"JARVIS repair summary — {_human_time()}\n\n" + "\n".join(lines))
    except OSError:
        pass
    if os.name != "nt":
        return False
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
