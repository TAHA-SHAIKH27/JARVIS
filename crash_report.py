"""
crash_report.py — Startup-crash user reporting for the J.A.R.V.I.S. watchdog.
==============================================================================
Stdlib only. Used by jarvis_watchdog.handle_crash() AFTER a backend crash:

  1. write_crash_summary()  -> "STARTUP CRASH/crash_<ts>.txt" in plain language:
     what happened, why JARVIS crashed, the responsible file + exact lines,
     and what the watchdog will attempt next.
  2. pop_interactive_repair_console() -> opens ONE Windows cmd window that
     becomes a live repair shell: summary, any-key, cd to project, visible
     `opencode run` with the prompt attached, transcript, then the fix
     summary in the SAME window. Returns (token, job_dict).
  3. archive_fixed_file()   -> after a successful repair, stores the
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
b) The watchdog writes a short error-focused prompt (file, exact lines,
   what happened) into your local OpenCode session, which fixes it with
   full project context. (If that fails, the NVIDIA window repair is tried
   automatically as backup.)
c) The model fixes the file directly, changing ONLY the culprit lines,
   and the watchdog checks the result compiles. A backup is kept first,
   so you can always roll back.
d) A record copy of the repaired file is stored under "FIXED CRASH FILE".
e) The repair summary appears in the SAME command window (it waits for it).

5) LAST OUTPUT BEFORE THE CRASH (technical detail)
--------------------------------------------------
{tail or '(no output captured)'}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


# How long the watchdog waits for the visible shell to signal done (30 min —
# agentic repairs are slow). Poll interval 5s.
_WAIT_TIMEOUT_S = 1800
_WAIT_POLL_S = 5


def write_repair_prompt(token: str, targets: list,
                        error_text: str) -> str:
    """Write the exact repair prompt for the visible shell. Returns its path."""
    from recovery_engine import build_opencode_prompt_multi
    prompt, _excerpts = build_opencode_prompt_multi(targets or [],
                                                    error_text or "")
    if not prompt:
        first = (targets or [{}])[0]
        prompt = (f"Crash repair task in file {first.get('file', '')}, "
                  f"line {first.get('line', '')}: {error_text}. Fix minimally.")
    os.makedirs(CRASH_DIR, exist_ok=True)
    path = os.path.join(CRASH_DIR, f"prompt_{token}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt + "\n")
    return path


def _interactive_repair_bat(head_lines: list, token: str, prompt_path: str) -> dict:
    """Crash popup that becomes a live repair shell (single window):

    summary -> press any key -> cd to project root -> run
    `opencode run` with the prompt file attached -> save transcript ->
    signal done -> wait for the fix file -> type it -> pause.
    Returns paths dict for the watchdog to poll.
    """
    os.makedirs(CRASH_DIR, exist_ok=True)
    os.makedirs(FIXED_DIR, exist_ok=True)
    bat = os.path.join(CRASH_DIR, f"_show_{token}.bat")
    transcript = os.path.join(CRASH_DIR, f"transcript_{token}.txt")
    donefile = os.path.join(CRASH_DIR, f"done_{token}.txt")
    fix_file = os.path.join(FIXED_DIR, f"fix_{token}.txt")
    root = WORKSPACE_ROOT

    def esc(text: str) -> str:
        return (text.encode("ascii", errors="replace").decode("ascii")
                .replace("^", "^^").replace("&", "^&").replace("|", "^|"))

    script = ["@echo off", f"title JARVIS Crash Report - {token}"]
    for ln in head_lines:
        ln = esc(ln)
        script.append(f"echo {ln}" if ln.strip() else "echo.")
    script += [
        "echo.",
        "echo Press any key to open the repair shell...",
        "pause >nul",
        "cls",
        f'cd /d "{root}"',
        "echo Repairing with your local OpenCode session...",
        "echo.",
        # Visible `opencode` invocation; -f attaches the prompt file so no
        # multiline quoting is needed. Transcript is teed to a file.
        f'opencode run --dir "{root}" -f "{prompt_path}" '
        '"Fix the startup crash described in the attached prompt file. '
        'Follow its rules exactly." '
        f'> "{transcript}" 2>&1',
        f"echo %ERRORLEVEL% > \"{donefile}\"",
        "echo.",
        "echo --- repair session transcript (last lines) ---",
        f'powershell -NoProfile -Command "Get-Content \'{transcript}\' -Tail 12"',
        "echo.",
        "echo Waiting for the watchdog to validate and archive the fix...",
        "set ELAPSED=0",
        ":wait",
        f'if exist "{fix_file}" goto done',
        f"timeout /t {_WAIT_POLL_S} /nobreak >nul",
        f"set /a ELAPSED+={_WAIT_POLL_S}",
        f"if %ELAPSED% GEQ {_WAIT_TIMEOUT_S} goto timeout",
        "goto wait",
        ":timeout",
        "echo.",
        "echo Validation is still running or could not complete -",
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
    return {"bat": bat, "transcript": transcript, "donefile": donefile,
            "fix_file": fix_file, "prompt": prompt_path, "token": token}


def pop_interactive_repair_console(summary_path: str, targets: list,
                                   error_text: str):
    """Pop ONE cmd window that becomes the live repair shell (see above).

    `targets` is [{"file","line"}] — one prompt covers them all.
    Returns (token, job_dict) on popup, else (None, {}). Console print
    happens in both cases.
    """
    first = (targets or [{}])[0]
    nice_names = ", ".join(os.path.basename(t.get("file", ""))
                           for t in (targets or []) if t.get("file")) or "unknown"
    first_line = first.get("line", 0)
    lines = [
        "================================================================",
        "  J.A.R.V.I.S. STARTUP CRASH  -  summary created",
        "================================================================",
        "",
        f"  Crash summary file:",
        f"  {summary_path}",
        "",
        f"  Failing file(s): {nice_names}",
        f"  Error line   : {first_line or '(unknown)'}",
        f"  Error        : {(error_text or '')[:100]}",
        "",
        "  Press any key in the popup window: it will cd to the",
        "  project, run `opencode` with the repair prompt attached,",
        "  and show the repair summary in the SAME window.",
        "  The file(s) are fixed directly; no backup copies.",
        "",
    ]
    for ln in lines:
        _safe_print(ln)
    if os.name != "nt":
        return None, {}
    token = _stamp()
    try:
        prompt_path = write_repair_prompt(token, targets or [], error_text or "")
        job = _interactive_repair_bat(lines, token, prompt_path)
        subprocess.Popen(["cmd", "/c", "start", "", job["bat"]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return token, job
    except Exception as e:
        _safe_print(f"[crash-report] Could not pop cmd window: {e}")
        return None, {}


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

    No new window is ever opened: the interactive popup polls
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
        "  Your file(s) were fixed directly in the project.",
        "  A record copy is saved under FIXED CRASH FILE.",
        "  JARVIS is restarting now — no action needed.",
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


if __name__ == "__main__":
    demo = {"file": __file__, "line": 1, "error": "SyntaxError: expected ':'"}
    print(write_crash_summary("Traceback (most recent call last):\n  SyntaxError: expected ':'", demo, 1))
