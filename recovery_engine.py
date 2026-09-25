"""
recovery_engine.py — Independent Self-Healing & Crash Recovery Module for J.A.R.V.I.S.
====================================================================================
STANDALONE ARCHITECTURE:
- Zero dependency on main.py, agent.py, or any third-party framework (uses only Python standard library).
- Reads config.json directly for Nemotron (NVIDIA NIM) credentials.
- Safe Patch Workflow: Backup -> Nemotron Diagnostic -> Apply Minimal Patch -> Validate (py_compile) -> Auto-Rollback on failure.
- NO GEMINI FALLBACK for self-healing. Nemotron failures are logged, retried (limited), then escalated to human.
"""

import os
import sys
import json
import re
import time
import shutil
import urllib.request
import urllib.error
import subprocess
import py_compile
import tempfile
from datetime import datetime

# Protected files blacklist — recovery engine will NEVER modify these
PROTECTED_FILES = {
    ".env", "config.json", ".git", "credentials.json", "token.json", "client_secrets.json"
}

BACKUP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".backup")

# Self-healing configuration (can be overridden by config.json)
MAX_NEMOTRON_RETRIES = 3
NEMOTRON_RETRY_BACKOFF = 5  # seconds
# Nemotron NIM streams full-file rewrites slowly (~9 tok/s). 60-90s timeouts are too
# short for real self-healing patches; default 240s, configurable via config.json.
NEMOTRON_REQUEST_TIMEOUT = 240  # seconds per request
NEMOTRON_MAX_OUTPUT_TOKENS = 16384  # output budget per request (gateway-safe ceiling)
NEED_HUMAN_NOTIFICATION = True


def _get_retry_config() -> tuple[int, int]:
    """Load retry config from config.json with defaults."""
    config = load_config()
    max_retries = config.get("nemotron_max_retries", MAX_NEMOTRON_RETRIES)
    backoff = config.get("nemotron_retry_backoff_seconds", NEMOTRON_RETRY_BACKOFF)
    try:
        max_retries = int(max_retries)
        backoff = int(backoff)
    except (ValueError, TypeError):
        max_retries = MAX_NEMOTRON_RETRIES
        backoff = NEMOTRON_RETRY_BACKOFF
    return max_retries, backoff


def _get_nemotron_timeout() -> int:
    """Load per-request timeout from config.json, clamped to a sane range."""
    config = load_config()
    timeout = config.get("nemotron_request_timeout_seconds", NEMOTRON_REQUEST_TIMEOUT)
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        timeout = NEMOTRON_REQUEST_TIMEOUT
    return max(30, min(timeout, 600))


def _get_nemotron_output_tokens() -> int:
    """Load max output tokens from config.json, clamped to the gateway-safe range."""
    config = load_config()
    tokens = config.get("nemotron_max_output_tokens", NEMOTRON_MAX_OUTPUT_TOKENS)
    try:
        tokens = int(tokens)
    except (ValueError, TypeError):
        tokens = NEMOTRON_MAX_OUTPUT_TOKENS
    return max(2048, min(tokens, 32768))


def load_config() -> dict:
    """Safely load config.json using standard library only."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[RECOVERY] Warning: Could not read config.json: {e}", file=sys.stderr)
    return {}


def log_recovery_event(event_type: str, message: str, details: dict = None):
    """Structured logging for recovery events with timestamps."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "message": message,
        "details": details or {}
    }
    log_line = f"[{timestamp}] [RECOVERY:{event_type}] {message}"
    print(log_line, file=sys.stderr)
    
    # Also append to recovery log file
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovery.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass


def call_nemotron(prompt: str, system_prompt: str = "", model: str = None) -> str:
    """Query Nemotron (via NVIDIA NIM API) using standard urllib.
    
    This is the DEDICATED self-healing engine. NO GEMINI FALLBACK.
    On failure: retry with backoff, log failure, notify human.
    """
    config = load_config()
    api_key = config.get("nvidia_api_key", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        error_msg = "Nemotron (NVIDIA NIM) API key not configured in config.json. Self-healing cannot proceed."
        log_recovery_event("NEMOTRON_CONFIG_ERROR", error_msg, {"has_nvidia_key": False})
        raise RuntimeError(error_msg)

    raw_model = model or config.get("nvidia_model", "")
    if not raw_model or raw_model in ["meta/llama-3.3-70b-instruct", "qwen/qwen2.5-coder-32b-instruct", "deepseek-ai/deepseek-r1"]:
        model_name = "z-ai/glm-5.3-flash"
    else:
        model_name = raw_model

    # Load retry config from config.json
    max_retries, backoff = _get_retry_config()
    timeout = _get_nemotron_timeout()

    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.1,
        "top_p": 0.7,
        "max_tokens": _get_nemotron_output_tokens(),
        "stream": True
    }
    if model_name.startswith("deepseek-ai/"):
        # DeepSeek V-family models spend the output budget on reasoning_content by
        # default, which truncates whole-file rewrites and causes long timeouts.
        # Disable reasoning so the full budget is used for the actual code answer.
        payload["reasoning_effort"] = "none"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            log_recovery_event("NEMOTRON_REQUEST", f"Attempt {attempt}/{max_retries}", {"model": model_name, "timeout_seconds": timeout})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_parts = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_line = line[len("data:"):].strip()
                    if data_line == "[DONE]":
                        break
                    try:
                        evt = json.loads(data_line)
                    except Exception:
                        continue
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        content_parts.append(piece)
                content = "".join(content_parts)
                if content:
                    log_recovery_event("NEMOTRON_SUCCESS", f"Nemotron responded successfully on attempt {attempt}")
                    return content
                raise RuntimeError("Empty response from Nemotron")
        except Exception as e:
            last_error = e
            log_recovery_event("NEMOTRON_ERROR", f"Attempt {attempt} failed: {str(e)}", {"attempt": attempt, "max_retries": max_retries})
            if attempt < max_retries:
                time.sleep(backoff * attempt)  # Exponential backoff
                continue
    
    # All retries exhausted
    error_msg = f"Nemotron failed after {max_retries} attempts. Last error: {last_error}"
    log_recovery_event("NEMOTRON_EXHAUSTED", error_msg, {"max_retries": max_retries, "last_error": str(last_error)})
    
    if NEED_HUMAN_NOTIFICATION:
        notify_human_self_healing_failed(error_msg)
    
    raise RuntimeError(error_msg)


def notify_human_self_healing_failed(error_message: str):
    """Notify human operator that self-healing could not complete."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notification = (
        f"\n{'='*60}\n"
        f"[HUMAN NOTIFICATION] {timestamp}\n"
        f"J.A.R.V.I.S. Self-Healing Engine (Nemotron) could not complete recovery.\n"
        f"Error: {error_message}\n"
        f"Action Required: Manual intervention needed.\n"
        f"Check recovery.log and watchdog_crash.log for details.\n"
        f"{'='*60}\n"
    )
    print(notification, file=sys.stderr)
    
    # Write to a dedicated notification file for external monitoring
    try:
        notify_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "human_notification.txt")
        with open(notify_path, "a", encoding="utf-8") as f:
            f.write(notification + "\n")
    except Exception:
        pass


# REMOVED: call_gemini_fallback() - Self-healing must NOT fall back to Gemini.
# Gemini is for NORMAL JARVIS OPERATIONS ONLY.


def is_protected(filepath: str) -> bool:
    """Check if target file is blacklisted from autonomous modifications."""
    norm = os.path.normpath(filepath).replace("\\", "/")
    basename = os.path.basename(norm)
    if basename in PROTECTED_FILES:
        return True
    if "/.git/" in norm or norm.startswith(".git/"):
        return True
    return False


def create_backup(filepath: str, tag: str = "recovery") -> str:
    """Create timestamped backup of the target file before any mutation."""
    if not os.path.exists(filepath):
        return ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BACKUP_ROOT, f"{tag}_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)
    basename = os.path.basename(filepath)
    dest_path = os.path.join(backup_dir, basename)
    shutil.copy2(filepath, dest_path)
    print(f"[RECOVERY] Created backup of {basename} -> {dest_path}")
    return dest_path


def restore_backup(backup_path: str, target_path: str) -> bool:
    """Restore file from backup upon validation failure."""
    if not backup_path or not os.path.exists(backup_path):
        print(f"[RECOVERY] Error: Backup not found at {backup_path}", file=sys.stderr)
        return False
    try:
        shutil.copy2(backup_path, target_path)
        print(f"[RECOVERY] RESTORED {target_path} from backup {backup_path}")
        return True
    except Exception as e:
        print(f"[RECOVERY] Error during backup restoration: {e}", file=sys.stderr)
        return False


def parse_traceback(traceback_text: str) -> dict:
    """
    Parse Python traceback to identify the exact problematic file and line.
    Returns: {"file": str, "line": int, "error": str}
    """
    lines = traceback_text.strip().splitlines()
    target_file = None
    target_line = None
    error_msg = ""
    workspace_dir = os.path.dirname(os.path.abspath(__file__))

    # Search for File "...", line N
    for line in reversed(lines):
        if not error_msg and (":" in line or "Error" in line or "Exception" in line):
            error_msg = line.strip()
        match = re.search(r'File "([^"]+)", line (\d+)', line)
        if match:
            raw_path = match.group(1)
            f_path = raw_path if os.path.isabs(raw_path) else os.path.join(workspace_dir, raw_path)
            # Only consider files in workspace
            if os.path.exists(f_path) and not is_protected(f_path):
                target_file = f_path
                target_line = int(match.group(2))
                break

    return {
        "file": target_file,
        "line": target_line,
        "error": error_msg or "Unknown runtime error"
    }


def validate_python_file(filepath: str) -> tuple[bool, str]:
    """Validate python file syntax using py_compile."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfile = os.path.join(tmpdir, os.path.basename(filepath) + ".pyc")
            py_compile.compile(filepath, cfile=cfile, doraise=True)
        return True, "Syntax valid"
    except py_compile.PyCompileError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Validation blocked: {e}"


def extract_code_from_llm_response(response: str) -> str:
    """Extract code cleanly from markdown code blocks or raw response."""
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", response)
    if match:
        return match.group(1)
    return response.strip()


def _extract_syntax_error_line(filepath: str) -> tuple[int, str]:
    """Check if file has syntax/compilation errors and extract the exact line number."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        import ast
        ast.parse(source, filename=filepath)
    except SyntaxError as se:
        lineno = int(se.lineno or 0)
        return lineno, f"SyntaxError: {se.msg}"
    except Exception as e:
        pass

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfile = os.path.join(tmpdir, os.path.basename(filepath) + ".pyc")
            py_compile.compile(filepath, cfile=cfile, doraise=True)
        return 0, ""
    except py_compile.PyCompileError as pe:
        lineno = 0
        match = re.search(r'line (\d+)', str(pe))
        if match:
            lineno = int(match.group(1))
        return lineno, f"PyCompileError: {str(pe)}"
    except Exception as e:
        return 0, f"Validation check blocked: {e}"


def _repair_window_attempt(target_file: str, target_line: int, error_msg: str, traceback_text: str) -> tuple[bool, str]:
    """Surgically repair a focused line window around target_line without rewriting the whole file."""
    with open(target_file, "r", encoding="utf-8", errors="replace") as f:
        file_content = f.read()

    lines = file_content.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines == 0:
        return False, "File is empty"

    window_radius = 25
    start_idx = max(0, target_line - 1 - window_radius)
    end_idx = min(total_lines, max(target_line + window_radius, start_idx + 10))
    window_snippet = "".join(lines[start_idx:end_idx])

    system_prompt = (
        "You are an expert Python systems recovery engineer for J.A.R.V.I.S.\n"
        "Your task: Fix the specific crash/syntax error inside the provided code snippet.\n"
        "CRITICAL RULES:\n"
        f"1. Output ONLY the corrected replacement code for lines {start_idx + 1} to {end_idx}.\n"
        "2. Preserve exact variable names, function signatures, imports, and indentation.\n"
        "3. Output ONLY the code inside a single ```python ... ``` block with zero conversational text.\n"
        "4. Do NOT output the entire file — output ONLY the replaced snippet."
    )

    prompt = (
        f"FILE: {os.path.basename(target_file)}\n"
        f"ERROR LOCATION: Line {target_line}\n"
        f"ERROR DETAILS: {error_msg}\n\n"
        f"ORIGINAL CODE SNIPPET (Lines {start_idx + 1} to {end_idx}):\n```python\n{window_snippet}\n```\n\n"
        f"Output the corrected snippet for lines {start_idx + 1}-{end_idx} inside ```python ... ```."
    )

    llm_response = call_nemotron(prompt, system_prompt)
    fixed_snippet = extract_code_from_llm_response(llm_response)
    if not fixed_snippet or len(fixed_snippet.strip()) < 5:
        return False, "Empty snippet returned by model"

    # Ensure trailing newline if needed
    if not fixed_snippet.endswith("\n"):
        fixed_snippet += "\n"

    # Splice fixed window back into the file lines
    new_lines = lines[:start_idx] + [fixed_snippet] + lines[end_idx:]
    new_content = "".join(new_lines)

    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    is_valid, val_msg = validate_python_file(target_file)
    return is_valid, val_msg


def recover_from_crash(crash_log_path: str, max_retries: int = 3,
                       in_place: bool = True) -> dict:
    """
    Analyze crash log, locate broken file, create backup, query NVIDIA NIM for a minimal fix,
    apply patch, validate, and retry up to max_retries. If all fail, auto-rollback.

    in_place=True  (default, legacy): repair is written into the original file,
                   with automatic rollback from backup on failure.
    in_place=False (watchdog crash flow): the original file is NEVER written.
                   Repair happens on a staging copy; on success the fixed copy
                   is archived under "FIXED CRASH FILE/" and its path is
                   returned as result["repaired_copy"].
    """
    if not os.path.exists(crash_log_path):
        return {"status": "error", "message": f"Crash log not found: {crash_log_path}"}

    with open(crash_log_path, "r", encoding="utf-8", errors="replace") as f:
        traceback_text = f.read()

    parsed = parse_traceback(traceback_text)
    target_file = parsed.get("file")
    target_line = parsed.get("line")
    error_summary = parsed.get("error")

    # If traceback didn't identify a file, check if any core file has a syntax error
    if not target_file or not os.path.exists(target_file):
        workspace_dir = os.path.dirname(os.path.abspath(__file__))
        core_files = [
            "main.py", "agent.py", "system_ops.py", "code_core.py",
            "recovery_engine.py", "jarvis_watchdog.py", "phone_control.py"
        ]
        for cf in core_files:
            cfp = os.path.join(workspace_dir, cf)
            if os.path.exists(cfp):
                err_line, err_msg = _extract_syntax_error_line(cfp)
                if err_line > 0:
                    target_file = cfp
                    target_line = err_line
                    error_summary = err_msg
                    break

    if not target_file or not os.path.exists(target_file):
        # Check if this is an "unhealthy backend" situation (health check failures
        # without a Python crash) rather than a code crash. In that case, the backend
        # just needs restarting, not code patching.
        crash_summary = (error_summary or "").strip()
        is_unhealthy_backend = (
            "UNHEALTHY BACKEND DETECTED" in crash_summary
            or "Consecutive health check failures" in crash_summary
        )
        if is_unhealthy_backend:
            return {
                "status": "unhealthy_backend",
                "message": f"Backend became unhealthy (health check failures) but no code crash detected. Backend needs restart, not code patching.",
                "file": None,
                "traceback": traceback_text[:1000]
            }
        return {
            "status": "error",
            "message": f"Could not identify a mutable workspace file from traceback: {error_summary}",
            "traceback": traceback_text[:1000]
        }

    if is_protected(target_file):
        return {
            "status": "blocked",
            "message": f"Target file {target_file} is protected from automatic modification.",
            "file": target_file
        }

    print(f"\n[RECOVERY] ========================================")
    print(f"[RECOVERY] Initiating autonomous recovery on: {os.path.basename(target_file)}")
    print(f"[RECOVERY] Error: {error_summary} (Line {target_line})")
    print(f"[RECOVERY] Mode: {'in-place repair' if in_place else 'COPY-ONLY repair (original untouched)'}")
    print(f"[RECOVERY] ========================================")

    # Create master backup before attempting any modifications (read-only copy,
    # kept as a safety record even in copy-only mode).
    backup_path = create_backup(target_file, tag="crash_recovery")

    # Copy-only mode: all repair + validation happens on a staging copy inside
    # "FIXED CRASH FILE/". The project original is never opened for writing.
    work_file = target_file
    staging_path = ""
    if not in_place:
        fixed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FIXED CRASH FILE")
        os.makedirs(fixed_dir, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(target_file))
        staging_path = os.path.join(
            fixed_dir, f"_repair_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.py'}")
        with open(target_file, "rb") as src, open(staging_path, "wb") as out:
            out.write(src.read())
        work_file = staging_path

    def _finalize_work_copy() -> str:
        """Archive a validated staging copy as the deliverable fixed file."""
        fixed_dir = os.path.dirname(staging_path)
        stem, ext = os.path.splitext(os.path.basename(target_file))
        dest = os.path.join(
            fixed_dir, f"{stem}_fixed_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.py'}")
        with open(work_file, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())
        try:
            os.remove(staging_path)
        except OSError:
            pass
        return dest

    def _discard_work_copy() -> None:
        if staging_path:
            try:
                os.remove(staging_path)
            except OSError:
                pass

    with open(target_file, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

    current_error = error_summary
    current_line = target_line or 1

    # Multi-error surgical repair loop (fixes 1-by-1 fast)
    max_surgical_passes = 4
    for p in range(1, max_surgical_passes + 1):
        # Determine exact error line if not known
        if not current_line or current_line <= 0:
            syn_line, syn_msg = _extract_syntax_error_line(work_file)
            if syn_line > 0:
                current_line = syn_line
                current_error = syn_msg

        print(f"\n[RECOVERY] Surgical Repair Pass {p}/{max_surgical_passes} on {os.path.basename(target_file)} near line {current_line}...")
        log_recovery_event("SURGICAL_REPAIR_ATTEMPT", f"Pass {p} on {os.path.basename(target_file)}: line {current_line}", {"line": current_line, "error": current_error})

        try:
            is_valid, val_msg = _repair_window_attempt(work_file, current_line, current_error, traceback_text)
            if is_valid:
                # Check if there's any remaining syntax error on a different line
                next_line, next_msg = _extract_syntax_error_line(work_file)
                if next_line == 0:
                    log_recovery_event("RECOVERY_SUCCESS", f"File {os.path.basename(target_file)} repaired and validated in pass {p}")
                    print(f"[RECOVERY] SUCCESS: File {os.path.basename(target_file)} repaired and validated!")
                    success = {
                        "status": "success",
                        "file": target_file,
                        "attempt": p,
                        "backup": backup_path,
                        "message": f"Successfully repaired {os.path.basename(target_file)} (surgical pass {p})."
                    }
                    if not in_place:
                        success["repaired_copy"] = _finalize_work_copy()
                        success["message"] += " Original file was NOT modified; fixed copy archived."
                    return success
                else:
                    print(f"[RECOVERY] Pass {p} resolved line {current_line}, but found next error at line {next_line}: {next_msg}")
                    current_line = next_line
                    current_error = next_msg
                    continue
            else:
                print(f"[RECOVERY] Surgical pass {p} validation reported: {val_msg}")
                # Check if the validation error pinpointed a new line
                next_line, next_msg = _extract_syntax_error_line(work_file)
                if next_line > 0:
                    current_line = next_line
                    current_error = next_msg
                else:
                    current_error = val_msg
        except RuntimeError as e:
            print(f"\n[RECOVERY] Nemotron self-healing engine unavailable: {e}")
            log_recovery_event("RECOVERY_NEMOTRON_UNAVAILABLE", str(e))
            if in_place:
                restore_backup(backup_path, target_file)
                msg = "Nemotron self-healing engine unavailable after retries. Rolled back safely."
            else:
                _discard_work_copy()
                msg = "Nemotron self-healing engine unavailable after retries. Original file was NOT modified."
            return {
                "status": "nemotron_unavailable",
                "file": target_file,
                "backup": backup_path,
                "message": msg
            }
        except Exception as e:
            print(f"[RECOVERY] Surgical repair exception: {e}")
            current_error = str(e)

    # Fallback to full-file repair if surgical passes failed
    print(f"\n[RECOVERY] Surgical repair exhausted. Falling back to whole-file repair...")
    system_prompt = (
        "You are an expert Python systems recovery engineer for J.A.R.V.I.S.\n"
        "Your task: Fix the provided code file to resolve the specific crash/traceback error.\n"
        "RULES:\n"
        "1. Make ONLY the minimal necessary corrections to fix the bug.\n"
        "2. Do NOT change existing function signatures, API contracts, or unrelated features.\n"
        "3. Output the COMPLETE corrected code for the file inside a single ```python ... ``` block.\n"
        "4. Ensure zero syntax errors, valid imports, and proper exception handling."
    )

    for attempt in range(1, max_retries + 1):
        print(f"\n[RECOVERY] Fallback Attempt {attempt}/{max_retries} — Querying Nemotron (Full File)...")
        prompt = (
            f"FILE TO REPAIR: {target_file}\n"
            f"CRASH TRACEBACK:\n{traceback_text}\n\n"
            f"SPECIFIC ERROR: {current_error}\n\n"
            f"CURRENT FILE CONTENT:\n```python\n{original_content}\n```\n\n"
            f"Please output the complete fixed version of this file inside ```python ... ``` code block."
        )

        try:
            llm_response = call_nemotron(prompt, system_prompt)
            fixed_code = extract_code_from_llm_response(llm_response)

            if not fixed_code or len(fixed_code) < 20:
                print(f"[RECOVERY] Attempt {attempt}: Received invalid/empty response from Nemotron.")
                current_error = "Empty or invalid response from Nemotron"
                time.sleep(1)
                continue

            with open(work_file, "w", encoding="utf-8") as f:
                f.write(fixed_code)

            is_valid, val_msg = validate_python_file(work_file)
            if is_valid:
                log_recovery_event("RECOVERY_SUCCESS", f"File {os.path.basename(target_file)} repaired and validated on fallback attempt {attempt}")
                print(f"[RECOVERY] SUCCESS: File {os.path.basename(target_file)} repaired and validated!")
                success = {
                    "status": "success",
                    "file": target_file,
                    "attempt": attempt,
                    "backup": backup_path,
                    "message": f"Successfully repaired {os.path.basename(target_file)} on fallback attempt {attempt}."
                }
                if not in_place:
                    success["repaired_copy"] = _finalize_work_copy()
                    success["message"] += " Original file was NOT modified; fixed copy archived."
                return success
            else:
                print(f"[RECOVERY] Fallback attempt {attempt} validation failed: {val_msg}")
                current_error = f"Validation py_compile error: {val_msg}"
                time.sleep(1)

        except Exception as e:
            print(f"[RECOVERY] Fallback attempt {attempt} error: {e}")
            current_error = str(e)
            time.sleep(1)

    # If all attempts failed: in-place mode rolls back; copy-only mode simply
    # discards the staging copy (the original was never touched).
    if in_place:
        print(f"\n[RECOVERY] FAILED: All recovery attempts failed. Rolling back to original state...")
        log_recovery_event("RECOVERY_FAILED_ROLLED_BACK", f"All repair attempts failed for {os.path.basename(target_file)}")
        restore_backup(backup_path, target_file)
        msg = f"Could not safely repair {os.path.basename(target_file)} after surgical and fallback attempts. Rolled back safely."
    else:
        print(f"\n[RECOVERY] FAILED: All recovery attempts failed. Discarding work copy (original untouched)...")
        log_recovery_event("RECOVERY_FAILED_DISCARDED", f"All repair attempts failed for {os.path.basename(target_file)}")
        _discard_work_copy()
        msg = f"Could not safely repair {os.path.basename(target_file)} after surgical and fallback attempts. Original file was NOT modified."

    return {
        "status": "failed_rolled_back",
        "file": target_file,
        "backup": backup_path,
        "message": msg
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print("[RECOVERY] Recovery Engine (Nemotron Self-Healing) is operational and ready.")
        cfg = load_config()
        has_nemotron = bool(cfg.get("nvidia_api_key"))
        print(f"[RECOVERY] Nemotron (NVIDIA NIM) configured: {has_nemotron} (Model: {cfg.get('nvidia_model', 'z-ai/glm-5.3-flash')})")
        print(f"[RECOVERY] Gemini fallback for self-healing: DISABLED (by design)")
        print(f"[RECOVERY] Max Nemotron retries: {MAX_NEMOTRON_RETRIES}")
        print(f"[RECOVERY] Retry backoff: {NEMOTRON_RETRY_BACKOFF}s (exponential)")
    elif len(sys.argv) > 2 and sys.argv[1] == "--recover":
        log_file = sys.argv[2]
        result = recover_from_crash(log_file)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python recovery_engine.py [--check | --recover <crash_log_path>]")
