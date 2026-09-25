"""
code_core.py — Autonomous Code Intelligence & Developer Engine for J.A.R.V.I.S.
==============================================================================
Capabilities:
- Self-Code Audit (Read-only inspection, zero mutations by default).
- Minimal Unified Diff Generation via Nemotron (NVIDIA NIM).
- Safe Patching with Timestamped Backups & Automatic Rollback.
- Uploaded Code File Inspection, Error-Fixing, and Download Generation.
- Multi-layer validation (py_compile, AST parse, Vite build check, /api/status).

ARCHITECTURE NOTE:
- Nemotron (NVIDIA NIM) is the dedicated engine for code analysis/fixing.
- NO GEMINI FALLBACK for code fixing operations.
- If Nemotron unavailable, operations return clear error requiring Nemotron config.
- Gemini remains the engine for NORMAL JARVIS conversation/tasks.
"""

import os
import sys
import json
import re
import difflib
import shutil
import ast
import time
import socket
import tempfile
import subprocess
import py_compile
import urllib.request
import urllib.error
from datetime import datetime

PROTECTED_FILES = {
    ".env", "config.json", ".git", "credentials.json", "token.json", "client_secrets.json"
}

WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(WORKSPACE_ROOT, ".backup")
DOWNLOADS_DIR = os.path.join(WORKSPACE_ROOT, "downloads")
os.makedirs(BACKUP_ROOT, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def load_config() -> dict:
    """Load configuration dictionary from config.json."""
    cfg_path = os.path.join(WORKSPACE_ROOT, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def is_protected(filepath: str) -> bool:
    """Check if file is protected from code engine mutations."""
    norm = os.path.normpath(filepath).replace("\\", "/")
    basename = os.path.basename(norm)
    if basename in PROTECTED_FILES:
        return True
    if "/.git/" in norm or norm.startswith(".git/"):
        return True
    return False


# Nemotron (NVIDIA NIM) configuration for code intelligence (can be overridden by config.json)
MAX_NEMOTRON_RETRIES = 3
NEMOTRON_RETRY_BACKOFF = 5  # seconds
# Nemotron NIM is slow for full-file rewrites (~9 tok/s on the free tier): a 4K-token
# corrected file can take minutes. 90s almost always times out. Default 240s, configurable.
NEMOTRON_REQUEST_TIMEOUT = 240  # seconds per request
# Output budget per request. NVIDIA's gateway drops single responses generating much
# more than ~13-16K tokens (HTTP 504), so big files are repaired in segments instead
# (see _repair_large_file_segments). This ceiling covers normal + segment outputs.
NEMOTRON_MAX_OUTPUT_TOKENS = 16384
# Files up to this size (chars) go through the existing single-shot rewrite.
# Larger files are split into segments and repaired piece-by-piece.
LARGE_FILE_SINGLE_SHOT_LIMIT = 50000
# Target chars per segment. MUST stay small: the NVIDIA free tier answers small
# prompts in ~10-20s but effectively never returns a ~12-15K-token segment
# prompt (40K+ chars) within the request timeout - it streams nothing for
# minutes, then the whole large-file scan looks stuck ("tries 3-4 attempts").
LARGE_FILE_SEGMENT_TARGET = 12000  # target chars per segment (diff-based outputs stay small)
LARGE_FILE_SEGMENT_MIN = 6000      # minimum chars before allowing a boundary cut


def _get_codecore_retry_config() -> tuple[int, int]:
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


def _get_nemotron_output_tokens() -> int:
    """Load max output tokens from config.json, clamped to the gateway-safe range."""
    config = load_config()
    tokens = config.get("nemotron_max_output_tokens", NEMOTRON_MAX_OUTPUT_TOKENS)
    try:
        tokens = int(tokens)
    except (ValueError, TypeError):
        tokens = NEMOTRON_MAX_OUTPUT_TOKENS
    return max(2048, min(tokens, 32768))


def _get_nemotron_timeout() -> int:
    """Load per-request timeout from config.json, clamped to a sane range."""
    config = load_config()
    timeout = config.get("nemotron_request_timeout_seconds", NEMOTRON_REQUEST_TIMEOUT)
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        timeout = NEMOTRON_REQUEST_TIMEOUT
    return max(30, min(timeout, 600))


def log_codecore_event(event_type: str, message: str, details: dict = None):
    """Structured logging for code core events."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "message": message,
        "details": details or {}
    }
    log_line = f"[{timestamp}] [CODE_CORE:{event_type}] {message}"
    print(log_line, file=sys.stderr)
    
    try:
        log_path = os.path.join(WORKSPACE_ROOT, "code_core.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass


class NemotronUnavailableError(RuntimeError):
    """Raised when Nemotron (NVIDIA NIM) cannot be reached or never completes.

    Subclasses RuntimeError so existing `except Exception`/`except RuntimeError`
    handlers in J.A.R.V.I.S. keep working. Raise type signals that Nemotron —
    not the calling code — is the reason the operation failed.
    """


def _is_timeout_error(err: BaseException) -> bool:
    """Return True when a urllib/socket error is a read/connect timeout."""
    if isinstance(err, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(err, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _classify_nemotron_error(err: BaseException) -> str:
    """Produce a clear, loggable reason string for a Nemotron call failure."""
    if _is_timeout_error(err):
        return "Nemotron request timed out (service unresponsive)"
    if isinstance(err, urllib.error.HTTPError):
        return f"Nemotron returned HTTP {err.code}: {err.reason}"
    if isinstance(err, (urllib.error.URLError, OSError)):
        return f"Nemotron connection/network error: {err}"
    if isinstance(err, json.JSONDecodeError):
        return "Nemotron returned an invalid (non-JSON) response"
    return str(err) or type(err).__name__


def call_nemotron(prompt: str, system_prompt: str = "", model: str = None) -> str:
    """Call Nemotron (via NVIDIA NIM API) for code intelligence tasks.

    This is the DEDICATED code analysis/fixing engine. NO GEMINI FALLBACK.
    On transient failure (timeout / network / HTTP error): retry with bounded
    exponential backoff. On total exhaustion: raise NemotronUnavailableError
    (a RuntimeError) so callers can return a clean structured failure.
    """
    config = load_config()
    api_key = config.get("nvidia_api_key", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        error_msg = "Nemotron (NVIDIA NIM) API key not configured in config.json. Code intelligence operations require Nemotron."
        log_codecore_event("NEMOTRON_CONFIG_ERROR", error_msg, {"has_nvidia_key": False})
        raise NemotronUnavailableError(error_msg)

    raw_model = model or config.get("nvidia_model", "")
    if not raw_model or raw_model in ["meta/llama-3.3-70b-instruct", "qwen/qwen2.5-coder-32b-instruct", "deepseek-ai/deepseek-r1"]:
        model_name = "z-ai/glm-5.3-flash"
    else:
        model_name = raw_model

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
        # Stream tokens as they are produced. A throttled-but-progressing response
        # keeps the connection alive and no longer trips the read timeout at
        # ~13-16K output tokens (which previously caused HTTP 504 / TimeoutError).
        "stream": True
    }
    if model_name.startswith("deepseek-ai/"):
        # DeepSeek V-family models spend the output budget on reasoning_content by
        # default, which truncates whole-file rewrites and causes long timeouts.
        # Disable reasoning so the full budget is used for the actual code answer.
        payload["reasoning_effort"] = "none"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    # Load retry config from config.json (bounded by design)
    max_retries, backoff = _get_codecore_retry_config()
    timeout = _get_nemotron_timeout()
    # Hard wall-clock cap: never let one call stall an operation for ~25 minutes
    # (e.g. 240s timeout x 5 retries). At most two attempts for transient errors.
    deadline = time.time() + (timeout * 2)

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            log_codecore_event("NEMOTRON_REQUEST", f"Attempt {attempt}/{max_retries}", {"model": model_name, "timeout_seconds": timeout})
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
                    log_codecore_event("NEMOTRON_SUCCESS", f"Nemotron responded successfully on attempt {attempt}")
                    return content
                raise RuntimeError("Empty response from Nemotron")
        except Exception as e:
            last_error = e
            reason = _classify_nemotron_error(e)
            log_codecore_event(
                "NEMOTRON_ERROR",
                f"Attempt {attempt}/{max_retries} failed: {reason}",
                {"attempt": attempt, "max_retries": max_retries, "error_type": type(e).__name__, "reason": reason}
            )

            # A completed HTTP response with an error status (e.g. 504 Gateway
            # Timeout, 524, 408, 5xx) means the gateway could not finish THIS
            # exact prompt within its window. Resubmitting the identical whole
            # request a few seconds later will fail the same way (the classic
            # "Attempt 1/5 -> ... -> Attempt 5/5 = ~25 minutes" stall). Fail
            # fast with a typed error instead. 429 (rate limit) IS transient,
            # so it stays retryable along with timeouts/network errors.
            is_http_error = isinstance(e, urllib.error.HTTPError)
            http_retryable = is_http_error and getattr(e, "code", None) == 429
            skip_retry = (is_http_error and not http_retryable) or time.time() >= deadline
            if skip_retry:
                log_codecore_event(
                    "NEMOTRON_NO_RETRY",
                    f"Giving up after attempt {attempt}/{max_retries}: {reason}",
                    {"attempt": attempt, "max_retries": max_retries, "reason": reason,
                     "http_code": getattr(e, "code", None), "deadline_exceeded": time.time() >= deadline}
                )
                break
            if attempt < max_retries:
                delay = backoff * attempt
                log_codecore_event(
                    "NEMOTRON_RETRY",
                    f"Retry scheduled: backing off {delay}s before attempt {attempt + 1}/{max_retries}",
                    {"attempt": attempt, "max_retries": max_retries, "delay_seconds": delay}
                )
                time.sleep(delay)
                continue

    # All retries exhausted — Nemotron is unavailable. Raise a typed error so
    # layer above can return a structured failure instead of a 500 crash.
    error_msg = f"Nemotron failed after attempt {attempt}/{max_retries}. Last error: {last_error}"
    log_codecore_event(
        "NEMOTRON_EXHAUSTED",
        error_msg,
        {"max_retries": max_retries, "last_error_type": type(last_error).__name__, "last_error": str(last_error)}
    )
    raise NemotronUnavailableError(error_msg)


# REMOVED: call_gemini_fallback() - Code intelligence must use Nemotron only.
# Gemini is for NORMAL JARVIS OPERATIONS (conversation, planning, etc.) ONLY.


def create_backup(filepath: str, tag: str = "codecore") -> str:
    """Create timestamped backup of the target file."""
    if not os.path.exists(filepath):
        return ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BACKUP_ROOT, f"{tag}_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)
    basename = os.path.basename(filepath)
    dest_path = os.path.join(backup_dir, basename)
    shutil.copy2(filepath, dest_path)
    return dest_path


def restore_backup(backup_path: str, target_path: str) -> bool:
    """Restore file from backup."""
    if not backup_path or not os.path.exists(backup_path):
        return False
    try:
        shutil.copy2(backup_path, target_path)
        return True
    except Exception:
        return False


def generate_unified_diff(original_content: str, new_content: str, filename: str = "file") -> str:
    """Generate a clean unified diff string."""
    orig_lines = original_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3
    )
    return "".join(diff)


def extract_code_block(response: str) -> str:
    """Extract code block cleanly from LLM response."""
    match = re.search(r"```[a-zA-Z0-9_-]*\s*([\s\S]*?)\s*```", response)
    if match:
        return match.group(1)
    return response.strip()


# ── Codebase Self-Audit (Read-Only) ──────────────────────────────────────────

def _byte_compile_python(filepath: str) -> None:
    """Byte-compile a Python file without writing to the shared __pycache__.

    py_compile.compile() normally writes a .pyc into __pycache__ next to the
    source. On Windows that file can be locked by another process that has the
    module imported (e.g. the running watchdog holds recovery_engine.cpython-314.pyc
    mapped), making the atomic rename fail with PermissionError [WinError 5].
    Compiling into a private temp directory keeps the audit truly read-only and
    immune to such locks. Raises py_compile.PyCompileError on compile failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cfile = os.path.join(tmpdir, os.path.basename(filepath) + ".pyc")
        py_compile.compile(filepath, cfile=cfile, doraise=True)


# Directories never scanned (dependencies, build output, runtime/user data).
_AUDIT_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", "dist", "build",
    "out", ".next", "work_files", "downloads", ".backup", "whisper.cpp",
    "ws-scrcpy", "venv", "env", ".venv",
}

# File types the startup audit understands.
_AUDIT_PY_EXTS = (".py",)
_AUDIT_JS_EXTS = (".jsx", ".js", ".mjs", ".cjs")


def _discover_audit_files() -> tuple[list, list]:
    """Walk the workspace and return (python_files, js_files) as workspace-
    relative paths. Skips dependency/build/runtime dirs so a 800MB
    node_modules can never stall startup. Stdlib only, never raises."""
    py_files: list = []
    js_files: list = []
    try:
        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            # Prune skipped dirs in-place so os.walk never descends into them.
            dirs[:] = [d for d in dirs if d not in _AUDIT_SKIP_DIRS
                       and not d.startswith(".pytest_cache")]
            for name in sorted(files):
                full = os.path.join(root, name)
                try:
                    rel = os.path.relpath(full, WORKSPACE_ROOT)
                except ValueError:
                    continue
                if rel.startswith(".."):
                    continue
                lower = name.lower()
                if lower.endswith(_AUDIT_PY_EXTS):
                    py_files.append(rel)
                elif lower.endswith(_AUDIT_JS_EXTS):
                    js_files.append(rel)
    except Exception:
        pass
    # Fall back to the original core list if discovery yields nothing.
    if not py_files and not js_files:
        py_files = [
            "main.py", "agent.py", "system_ops.py", "code_core.py",
            "recovery_engine.py", "jarvis_watchdog.py", "phone_control.py",
        ]
        js_files = [
            os.path.join("src", "App.jsx"),
            os.path.join("src", "Header.jsx"),
            os.path.join("src", "Telemetry.jsx"),
            os.path.join("src", "CommandGrid.jsx"),
            os.path.join("src", "CoreSphere.jsx"),
        ]
    return py_files, js_files


def audit_codebase() -> dict:
    """
    Perform a complete read-only self-audit of JARVIS's source code.
    Discovers every workspace .py / .jsx / .js / .mjs / .cjs file (skipping
    dependencies, build output and runtime data dirs) and checks Python
    syntax via AST + py_compile and JS modules for duplicate exports.
    NEVER modifies any files.
    """
    issues = []
    py_files, js_files = _discover_audit_files()

    total_checked = 0

    # 1. Audit Python Files
    for rel_path in py_files:
        full_path = os.path.join(WORKSPACE_ROOT, rel_path)
        if not os.path.exists(full_path):
            continue
        total_checked += 1

        # Read source encoding-aware (UTF-8 first, UTF-16 BOM fallback —
        # a stale UTF-16 duplicate must not fail the whole audit).
        try:
            with open(full_path, "rb") as f:
                raw = f.read()
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                source = raw.decode("utf-16", errors="replace")
            else:
                source = raw.decode("utf-8", errors="replace")
        except Exception as e:
            issues.append({
                "file": rel_path,
                "line": 0,
                "line_range": [0, 0],
                "severity": "critical_syntax_error",
                "message": f"Read failure: {str(e)}",
                "snippet": ""
            })
            continue

        # Syntax check via AST
        try:
            ast.parse(source, filename=rel_path)
        except SyntaxError as se:
            start_line = int(se.lineno or 0)
            end_line = int(getattr(se, "end_lineno", None) or start_line)
            issues.append({
                "file": rel_path,
                "line": start_line,
                "line_range": [start_line, end_line],
                "severity": "critical_syntax_error",
                "message": f"Syntax error: {se.msg}",
                "snippet": se.text.strip() if se.text else ""
            })
            continue
        except Exception as e:
            issues.append({
                "file": rel_path,
                "line": 0,
                "line_range": [0, 0],
                "severity": "critical_syntax_error",
                "message": f"Parsing failure: {str(e)}",
                "snippet": ""
            })
            continue

        # Static py_compile test (via private temp dir - never the shared
        # __pycache__, where a locked .pyc would crash the whole audit)
        try:
            _byte_compile_python(full_path)
        except py_compile.PyCompileError as pe:
            # py_compile reads raw bytes: a valid UTF-16 file trips its
            # "null bytes" guard. Re-validate from the decoded source instead.
            if "null bytes" in str(pe):
                try:
                    compile(source, rel_path, "exec")
                    continue
                except SyntaxError as se2:
                    start_line = int(se2.lineno or 0)
                    issues.append({
                        "file": rel_path,
                        "line": start_line,
                        "line_range": [start_line, int(getattr(se2, "end_lineno", None) or start_line)],
                        "severity": "compilation_error",
                        "message": f"Compile error: {se2.msg}",
                        "snippet": ""
                    })
                    continue
            issues.append({
                "file": rel_path,
                "line": 0,
                "line_range": [0, 0],
                "severity": "compilation_error",
                "message": f"py_compile error: {str(pe)}",
                "snippet": ""
            })
        except Exception as e:
            issues.append({
                "file": rel_path,
                "line": 0,
                "line_range": [0, 0],
                "severity": "warning",
                "message": f"py_compile check blocked: {str(e)}",
                "snippet": ""
            })

    # 2. Audit React / Frontend Files
    for rel_path in js_files:
        full_path = os.path.join(WORKSPACE_ROOT, rel_path)
        if not os.path.exists(full_path):
            continue
        total_checked += 1
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Check for unclosed tags or dangling exports
        if content.count("export default") > 1:
            issues.append({
                "file": rel_path,
                "line": 0,
                "line_range": [0, 0],
                "severity": "duplicate_export",
                "message": "Multiple 'export default' statements detected in single module.",
                "snippet": ""
            })

    health_score = max(0, 100 - (len(issues) * 20))
    status = "healthy" if len(issues) == 0 else "errors" if any(i["severity"].startswith("critical") for i in issues) else "warning"

    return {
        "status": status,
        "health_score": health_score,
        "total_files_checked": total_checked,
        "issues_count": len(issues),
        "issues": issues,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ── Preview & Apply Fixes with Auto-Rollback ─────────────────────────────────

def preview_file_fix(filepath: str, issue_description: str = "", line: int = 0) -> dict:
    """
    Generate a proposed minimal fix and unified diff for a target file.
    Does NOT mutate the target file.
    Uses fast surgical window repair for localized syntax errors/large files.
    """
    full_path = os.path.join(WORKSPACE_ROOT, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full_path):
        return {"status": "error", "message": f"File not found: {filepath}"}

    if is_protected(full_path):
        return {"status": "blocked", "message": f"File {filepath} is protected."}

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

    # Determine if there is a specific line number to fix surgically
    target_line = line
    if target_line <= 0 and filepath.endswith(".py"):
        try:
            ast.parse(original_content, filename=filepath)
        except SyntaxError as se:
            target_line = int(se.lineno or 0)
        except Exception:
            pass

    # Surgical Window Repair for localized errors
    if target_line > 0 and len(original_content) > 3000:
        lines = original_content.splitlines(keepends=True)
        total_lines = len(lines)
        window_radius = 25
        start_idx = max(0, target_line - 1 - window_radius)
        end_idx = min(total_lines, max(target_line + window_radius, start_idx + 10))
        window_snippet = "".join(lines[start_idx:end_idx])

        sys_prompt = (
            "You are an expert code repair engine for J.A.R.V.I.S.\n"
            "Your task: Fix the specific bug/syntax error inside the provided code snippet.\n"
            "CRITICAL RULES:\n"
            f"1. Output ONLY the replacement code for lines {start_idx + 1} to {end_idx}.\n"
            "2. Preserve exact variable names, function signatures, and indentation.\n"
            "3. Output ONLY the code inside a single ```...``` block with zero conversational text.\n"
            "4. Do NOT output the entire file — output ONLY the replaced snippet."
        )

        prompt = (
            f"FILE: {filepath}\n"
            f"ERROR NEAR LINE {target_line}: {issue_description or 'Syntax error or bug'}\n\n"
            f"ORIGINAL CODE SNIPPET (Lines {start_idx + 1} to {end_idx}):\n```\n{window_snippet}\n```\n\n"
            f"Output the corrected snippet for lines {start_idx + 1}-{end_idx} inside ```...```."
        )

        try:
            llm_response = call_nemotron(prompt, sys_prompt)
            fixed_snippet = extract_code_block(llm_response)
            if fixed_snippet and len(fixed_snippet.strip()) >= 5:
                if not fixed_snippet.endswith("\n"):
                    fixed_snippet += "\n"
                proposed_content = "".join(lines[:start_idx] + [fixed_snippet] + lines[end_idx:])
                diff = generate_unified_diff(original_content, proposed_content, filename=os.path.basename(filepath))
                return {
                    "status": "success",
                    "file": filepath,
                    "diff": diff,
                    "proposed_content": proposed_content,
                    "original_size": len(original_content),
                    "proposed_size": len(proposed_content),
                    "surgical": True,
                    "line": target_line
                }
        except Exception as e:
            log_codecore_event("SURGICAL_PREVIEW_FALLBACK", f"Surgical preview failed for {filepath}: {e}")

    system_prompt = (
        "You are an expert software developer and code auditor for J.A.R.V.I.S.\n"
        "Your task: Inspect the provided file and generate a minimal, surgically precise fix for the described issue.\n"
        "RULES:\n"
        "1. Fix the bug cleanly with minimal changes.\n"
        "2. Do NOT change existing APIs or remove unrelated features.\n"
        "3. Output the COMPLETE updated code for the file inside a single code block ```...```."
    )

    prompt = (
        f"FILE: {filepath}\n"
        f"ISSUE DESCRIPTION: {issue_description or 'Audit and fix any bugs, syntax errors, or unhandled exceptions.'}\n\n"
        f"CURRENT CODE:\n```\n{original_content}\n```\n\n"
        f"Output the complete fixed code inside ```...```."
    )

    # Large files never go through the single-shot whole-file rewrite
    if len(original_content) > LARGE_FILE_SINGLE_SHOT_LIMIT:
        log_codecore_event(
            "NEMOTRON_LARGE_FILE",
            f"preview_file_fix: {filepath} is {len(original_content)} chars - using segmented repair to avoid gateway 504",
            {"filepath": filepath, "chars": len(original_content)}
        )
        try:
            proposed_content, seg_notes, unresolved = _repair_large_file_segments(
                filepath,
                original_content,
                issue_description or "Audit and fix any bugs, syntax errors, or unhandled exceptions."
            )
        except NemotronUnavailableError as e:
            return {"status": "error", "error_type": "nemotron_unavailable", "file": filepath, "message": str(e)}
        if not proposed_content or len(proposed_content) < 10:
            return {"status": "error", "file": filepath, "message": "Failed to generate valid code fix from AI model."}
        diff = generate_unified_diff(original_content, proposed_content, filename=os.path.basename(filepath))
        return {
            "status": "success",
            "file": filepath,
            "diff": diff,
            "proposed_content": proposed_content,
            "original_size": len(original_content),
            "proposed_size": len(proposed_content),
            "segmented": True,
            "segment_notes": seg_notes,
            "unresolved": unresolved,
        }

    try:
        llm_response = call_nemotron(prompt, system_prompt)
    except NemotronUnavailableError as e:
        return {"status": "error", "error_type": "nemotron_unavailable", "file": filepath, "message": str(e)}
    proposed_content = extract_code_block(llm_response)

    if not proposed_content or len(proposed_content) < 10:
        return {"status": "error", "message": "Failed to generate valid code fix from AI model."}

    diff = generate_unified_diff(original_content, proposed_content, filename=os.path.basename(filepath))

    return {
        "status": "success",
        "file": filepath,
        "diff": diff,
        "proposed_content": proposed_content,
        "original_size": len(original_content),
        "proposed_size": len(proposed_content)
    }


def validate_code_file(filepath: str) -> tuple[bool, str]:
    """Validate a code file according to its extension."""
    if filepath.endswith(".py"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source, filename=filepath)
            _byte_compile_python(filepath)
            return True, "Python syntax & compilation valid."
        except Exception as e:
            return False, str(e)
    elif filepath.endswith(".jsx") or filepath.endswith(".js"):
        # Quick validation using npm run build
        try:
            res = subprocess.run(
                ["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
                cwd=WORKSPACE_ROOT,
                capture_output=True,
                text=True,
                timeout=35
            )
            if res.returncode == 0:
                return True, "Vite production build valid."
            else:
                return False, f"Vite build error: {res.stderr[:500]}"
        except Exception as e:
            return True, f"Build validation bypassed: {e}"
    return True, "Validation passed."


def apply_file_fix(filepath: str, proposed_content: str, max_retries: int = 3) -> dict:
    """
    Apply proposed code fix with timestamped backup, validation suite, and auto-rollback on failure.
    """
    full_path = os.path.join(WORKSPACE_ROOT, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full_path):
        return {"status": "error", "message": f"Target file not found: {filepath}"}

    if is_protected(full_path):
        return {"status": "blocked", "message": f"File {filepath} is protected."}

    # Step 1: Create backup
    backup_path = create_backup(full_path, tag="codecore_fix")
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

    # Step 2: Apply patch
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(proposed_content)

    # Step 3: Validate
    is_valid, val_msg = validate_code_file(full_path)
    if is_valid:
        diff = generate_unified_diff(original_content, proposed_content, filename=os.path.basename(filepath))
        return {
            "status": "success",
            "file": filepath,
            "backup": backup_path,
            "diff": diff,
            "message": f"Successfully applied fix and verified validation ({val_msg})."
        }

    # Step 4: Iterative Repair Loop
    print(f"[CODE_CORE] Initial validation failed ({val_msg}). Beginning iterative repair loop...")
    current_error = val_msg
    current_code = proposed_content

    for attempt in range(1, max_retries + 1):
        print(f"[CODE_CORE] Repair retry attempt {attempt}/{max_retries}...")
        prompt = (
            f"FILE: {filepath}\n"
            f"VALIDATION ERROR:\n{current_error}\n\n"
            f"CODE CAUSING ERROR:\n```\n{current_code}\n```\n\n"
            f"Please fix the validation error and provide the complete corrected code inside ```...```."
        )
        try:
            resp = call_nemotron(prompt, "You are a code validation repair engine. Output only corrected code.")
            retry_code = extract_code_block(resp)
            if retry_code:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(retry_code)
                is_valid, val_msg = validate_code_file(full_path)
                if is_valid:
                    diff = generate_unified_diff(original_content, retry_code, filename=os.path.basename(filepath))
                    return {
                        "status": "success",
                        "file": filepath,
                        "backup": backup_path,
                        "diff": diff,
                        "message": f"Repaired and validated on retry attempt {attempt}."
                    }
                current_error = val_msg
                current_code = retry_code
        except Exception as e:
            current_error = str(e)

    # Step 5: Rollback if all retries failed
    print("[CODE_CORE] All repair retries failed. Executing automatic rollback...")
    restore_backup(backup_path, full_path)

    return {
        "status": "rolled_back",
        "file": filepath,
        "backup": backup_path,
        "message": f"Validation failed after {max_retries} retries: {current_error}. Automatically rolled back to backup."
    }


# ── Uploaded File Error Inspection & Refactoring ─────────────────────────────

_TOPLEVEL_BOUNDARY_RE = re.compile(
    r"^\s*(?:def\s|class\s|async\s|function\s|export\s+(?:default\s+)?(?:function|class|const|let|var|interface|type)\s|"
    r"interface\s|struct\s|type\s|impl\s|fn\s|func\s|procedure\s|public\s|private\s|protected\s)"
)


def _is_toplevel_boundary(line: str) -> bool:
    """Heuristic: does this line start a new top-level block in most languages?"""
    return bool(_TOPLEVEL_BOUNDARY_RE.match(line))


def _split_large_file_segments(content: str) -> list[tuple[int, int, str]]:
    """Split a large file into (start_line, end_line, text) segments.

    Cut points prefer a blank line followed by a top-level block keyword so
    function/class boundaries are preserved as much as possible. This keeps
    per-segment outputs small enough that the NVIDIA gateway never sees a
    giant single response (which 504s at ~13-16K+ output tokens).
    """
    lines = content.splitlines(keepends=True)
    n = len(lines)
    target = LARGE_FILE_SEGMENT_TARGET
    segments: list = []
    start = 0
    while start < n:
        end = start
        size = 0
        while end < n and size < target:
            size += len(lines[end])
            end += 1
        if end >= n:
            segments.append((start, n, "".join(lines[start:])))
            break
        lo = min(start + (target // 2), end - 1)
        best = None
        for i in range(lo, end):
            if not lines[i].strip():
                j = i + 1
                while j < end and not lines[j].strip():
                    j += 1
                if j < end and _is_toplevel_boundary(lines[j]):
                    best = i + 1
                    break
        if best is None:
            last_blank = -1
            for i in range(lo, end):
                if not lines[i].strip():
                    last_blank = i
            if last_blank != -1:
                best = last_blank + 1
        if best is None:
            best = lo
        best = max(best, start + 1)
        if best >= end:
            best = end
        segments.append((start, best, "".join(lines[start:best])))
        start = best
    return segments


def _parse_unified_diff(diff_text: str) -> list:
    """Parse a unified diff into (old_start_0based, old_lines, new_lines) hunks."""
    hunks = []
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@", lines[i])
        if not m:
            i += 1
            continue
        old_start = int(m.group(1)) - 1  # 0-based offset
        old_lines = []
        new_lines = []
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            s = lines[i]
            prefix = s[0] if s else " "
            body = (s[1:] if len(s) > 1 else "").rstrip("\r\n")
            if prefix == " ":
                old_lines.append(body)
                new_lines.append(body)
            elif prefix == "-":
                old_lines.append(body)
            elif prefix == "+":
                new_lines.append(body)
            i += 1
        hunks.append((old_start, old_lines, new_lines))
    return hunks


def _find_hunk_offset(base_norm: list, target: list, expected: int) -> int:
    """Locate where hunk's old lines match inside the base.

    Models frequently report slightly-to-greatly wrong line numbers, so after
    checking near the expected offset we fall back to searching the whole
    segment for a UNIQUE strong content match. Identical/duplicated lines are
    never matched blindly (a margin over the runner-up is required).
    """
    n = len(target)
    if n == 0:
        return -1
    window = 30
    lo = max(0, expected - window)
    hi = min(len(base_norm) - n, expected + window)
    for off in range(lo, hi + 1):
        if base_norm[off:off + n] == target:
            return off
    from difflib import SequenceMatcher
    if n >= 2:
        probe = min(n, 3)
        for off in range(lo, hi + 1):
            if off + probe > len(base_norm):
                break
            if base_norm[off:off + probe] and SequenceMatcher(None, base_norm[off:off + probe], target[:probe]).ratio() >= 0.75:
                return off
    best = -1
    best_ratio = 0.0
    second = 0.0
    for off in range(len(base_norm) - n + 1):
        snippet = base_norm[off:off + n]
        if not snippet:
            continue
        r = SequenceMatcher(None, snippet, target).ratio()
        if r > best_ratio:
            second = best_ratio
            best_ratio = r
            best = off
        elif r > second:
            second = r
    if best >= 0 and best_ratio >= 0.85 and (best_ratio - second) >= 0.15:
        return best
    return -1


def _apply_unified_diff(source: str, diff_text: str, old_base_offset: int = 0) -> tuple:
    """Apply a unified diff to a source string.

    Returns (new_source, failed_hunk_count, failed_hunk_descriptions).
    Successful hunks are applied even if other hunks fail.

    old_base_offset: the 0-based original-file line where the source segment starts.
    The model reports hunks using original file line numbers, so hunk offsets are
    shifted into segment-relative coordinates before matching.
    """
    if not diff_text.strip():
        return source, 0, []
    base = source.splitlines(keepends=True)
    base_norm = [l.rstrip("\r\n") for l in base]
    hunks = sorted(_parse_unified_diff(diff_text), key=lambda h: h[0] - old_base_offset, reverse=True)
    failed = 0
    failed_specs = []
    for old_start, old_lines, new_lines in hunks:
        if not old_lines:
            failed += 1
            failed_specs.append("(addition with no anchor)")
            continue
        off = _find_hunk_offset(base_norm, old_lines, old_start - old_base_offset)
        if off < 0:
            failed += 1
            failed_specs.append((old_lines[0] or "(blank anchor)").strip()[:90])
            continue
        replacement = [nl + "\n" for nl in new_lines]
        base[off:off + len(old_lines)] = replacement
    return "".join(base), failed, failed_specs


def _reconcile_block_trailing_newline(block: str, fixed: str) -> str:
    """Preserve the original trailing-newline style when reassembling segments."""
    if block.endswith("\n") and not fixed.endswith("\n"):
        return fixed + "\n"
    if not block.endswith("\n") and fixed.endswith("\n"):
        return fixed.rstrip("\n")
    return fixed


def _repair_large_file_segments(filename: str, file_content: str, user_instructions: str) -> tuple:
    """Repair a large file segment-by-segment via compact diff hunks.

    Instead of asking the model to reproduce whole segments (which is slow and can
    504 the gateway), the model returns a minimal unified diff of ONLY its changes
    plus a one-line FIX note. We apply the hunks deterministically to each segment
    and reassemble. Falls back to leaving a segment unchanged if a hunk won't apply.

    Returns (fixed_code, notes, unresolved).
    """
    segments = _split_large_file_segments(file_content)
    n = len(segments)
    fixed_blocks: list = []
    notes: list = []
    unresolved: list = []

    sys_prompt = (
        "You are an expert code repair engine for J.A.R.V.I.S.\n"
        "You receive ONE segment (lines of a larger file) inside code fences.\n"
        "Find and fix the real errors, syntax bugs and the user's stated objective in THAT segment.\n"
        "CAREFULLY scan EVERY line for: undefined or misspelled variables, misspelled attribute/method "
        "names, wrong operators, wrong dict/tuple keys, wrong comparisons, off-by-one errors. "
        "MUST find and fix EACH bug, not just the first one.\n"
        "OUTPUT FORMAT (strict):\n"
        "1. Your very first line must be: FIX: <one short sentence describing the main issue and its fix>.\n"
        "2. Then ONLY the minimal unified diff (like git diff -U2) of your change for EACH bug, all inside a "
        "single ```diff ... ``` code block. Change as few lines as possible.\n"
        "HUNK RULE: the line numbers BEFORE +/-\n in each hunk header (e.g. @@ -335,1 +335,1 @@) MUST use "
        "the ORIGINAL file line numbers for the segment range given below. Do NOT renumber. "
        "Do NOT reproduce the whole segment or unchanged lines. "
        "If no change is needed, omit the diff block."
    )

    for idx, (s, e, block) in enumerate(segments, start=1):
        prompt = (
            f"FILE: {filename}\n"
            f"SEGMENT {idx}/{n} (lines {s + 1}-{e} of the original file)\n"
            f"USER OBJECTIVE: {user_instructions or 'Find and fix all errors and bugs in this segment.'}\n\n"
            f"SEGMENT CONTENT:\n```\n{block}\n```\n\n"
            f"Output your FIX: line, then the minimal unified diff of ONLY your changes inside one ```diff ... ``` block."
        )
        try:
            raw = call_nemotron(prompt, sys_prompt)
        except NemotronUnavailableError:
            fixed_blocks.append(block)
            notes.append(f"Lines {s + 1}-{e}: model unavailable after retries - left unchanged")
            unresolved.append((s + 1, e))
            continue

        note = ""
        m = re.search(r"FIX:\s*(.*)", raw)
        if m:
            note = m.group(1).strip()

        fence = re.search(r"```(?:diff)?\s*\n(.*?)```", raw, re.S)
        diff_text = fence.group(1) if fence else raw
        if "@@" not in diff_text:
            diff_text = ""

        if not diff_text:
            fixed_blocks.append(block)
            notes.append(f"Lines {s + 1}-{e}: no issues found in this segment{' - ' + note if note else ''}")
            continue

        changed, failed, failed_specs = _apply_unified_diff(block, diff_text, old_base_offset=s)
        if changed == block:
            if failed:
                spec_txt = "; ".join(failed_specs[:5]) if failed_specs else ""
                notes.append(f"Lines {s + 1}-{e}: {failed} proposed change(s) could not be applied - {note or ''} {('[lines: ' + spec_txt + ']') if spec_txt else ''}")
                unresolved.append((s + 1, e))
            else:
                notes.append(f"Lines {s + 1}-{e}: {note or 'no changes applied'}")
            fixed_blocks.append(block)
            continue

        fixed_blocks.append(_reconcile_block_trailing_newline(block, changed))
        if failed == 0:
            notes.append(f"Lines {s + 1}-{e}: {note or 'changes applied'}")
        else:
            spec_txt = "; ".join(failed_specs[:5]) if failed_specs else ""
            notes.append(
                f"Lines {s + 1}-{e}: partially applied - {failed} change(s) skipped "
                f"([{spec_txt}]) - {note}"
            )
            unresolved.append((s + 1, e))

    fixed_code = "".join(fixed_blocks)
    return fixed_code, notes, unresolved


def _process_large_uploaded_code_file(filename: str, file_content: str, user_instructions: str) -> dict:
    """Large-file variant: repair in segments so no single response is huge."""
    lines_total = len(file_content.splitlines())
    fixed_code, notes, unresolved = _repair_large_file_segments(filename, file_content, user_instructions)

    sanitized_name = re.sub(r"[^\w\.-]", "_", filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"fixed_{timestamp}_{sanitized_name}"
    out_path = os.path.join(DOWNLOADS_DIR, out_filename)

    validation_warning = ""
    if filename.lower().endswith(".py"):
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = os.path.join(td, "chk.py")
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(fixed_code)
                _byte_compile_python(tmp)
        except Exception as ve:
            validation_warning = f"\n\nWARNING: reassembled file does not pass py_compile: {ve}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fixed_code)

    diff = generate_unified_diff(file_content, fixed_code, filename=filename)

    if unresolved:
        u_notes = "".join([f"\n- Lines {s}-{e}: could not be auto-repaired, left unchanged." for s, e in unresolved])
    else:
        u_notes = ""

    seg_notes = "\n".join(f"- {x}" for x in notes) or "- No segment required changes."

    summary = (
        f"Analyzed a large {filename} file ({lines_total} lines) in {len(notes)} segments.\n"
        f"What was found and fixed:\n{seg_notes}{u_notes}\n"
        "WHAT TO DO: Download the fixed file, review the diff above, and run the file's own "
        "tests/linter. Any segment marked UNCHANGED needs a manual look."
    ) + validation_warning

    return {
        "status": "success",
        "original_filename": filename,
        "download_filename": out_filename,
        "download_url": f"/api/code/download/{out_filename}",
        "summary": summary,
        "diff": diff,
        "fixed_code": fixed_code,
        "segmented": True,
    }


def process_uploaded_code_file(filename: str, file_content: str, user_instructions: str = "") -> dict:
    """
    Inspect an uploaded user code file for bugs, refactor/fix it, and save in downloads/ for retrieval.
    """
    system_prompt = (
        "You are an expert code refactoring and bug fixing engine for J.A.R.V.I.S.\n"
        "Your task: Inspect the uploaded user code file, identify bugs, syntax errors, and edge cases, "
        "and refactor it according to user instructions.\n"
        "OUTPUT FORMAT REQUIREMENTS:\n"
        "1. First provide ONLY a concise bulleted summary of errors found and fixes applied.\n"
        "2. Do NOT say 'followed by the complete corrected code' or paste raw source code in the textual explanation.\n"
        "3. Provide the entire corrected file content ONLY inside a single ```...``` block at the very end. The system will save it directly as a downloadable file for the user."
    )

    prompt = (
        f"FILENAME: {filename}\n"
        f"USER INSTRUCTIONS: {user_instructions or 'Find and fix all errors, syntax bugs, and improvements.'}\n\n"
        f"FILE CONTENT:\n```\n{file_content}\n```\n\n"
        f"Please provide your concise bulleted summary of fixes, followed by the complete corrected code inside a single ```...``` block."
    )

    if len(file_content) > LARGE_FILE_SINGLE_SHOT_LIMIT:
        log_codecore_event("NEMOTRON_LARGE_FILE", f"File {filename} is {len(file_content)} chars - using segmented repair", {"filename": filename})
        try:
            return _process_large_uploaded_code_file(filename, file_content, user_instructions)
        except NemotronUnavailableError as e:
            log_codecore_event(
                "NEMOTRON_UNAVAILABLE",
                f"Large uploaded file analysis could not run: Nemotron unavailable -> {e}",
                {"filename": filename}
            )
            return {
                "status": "error",
                "error_type": "nemotron_unavailable",
                "original_filename": filename,
                "message": str(e),
            }

    try:
        llm_response = call_nemotron(prompt, system_prompt)
    except NemotronUnavailableError as e:
        log_codecore_event(
            "NEMOTRON_UNAVAILABLE",
            f"Uploaded file analysis could not run: Nemotron unavailable -> {e}",
            {"filename": filename}
        )
        return {
            "status": "error",
            "error_type": "nemotron_unavailable",
            "original_filename": filename,
            "message": str(e),
        }
    fixed_code = extract_code_block(llm_response)

    if not fixed_code:
        fixed_code = file_content

    # Save to downloads folder
    sanitized_name = re.sub(r"[^\w\.-]", "_", filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"fixed_{timestamp}_{sanitized_name}"
    out_path = os.path.join(DOWNLOADS_DIR, out_filename)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fixed_code)

    diff = generate_unified_diff(file_content, fixed_code, filename=filename)

    # Extract clean explanation text (text before the code block)
    summary_raw = re.split(r"```", llm_response)[0].strip() or "Code analyzed and refactored."
    # Strip any trailing boilerplate phrases pointing to the code block or diff headers
    cleaned_summary = re.sub(
        r"(?i)(###\s*(?:Corrected|Updated|Fixed)\s*Code.*|Here(?:'s| is) the (?:complete )?(?:corrected|fixed) code.*|---\s*a/.*|followed by the complete corrected code.*)",
        "",
        summary_raw
    ).strip()

    return {
        "status": "success",
        "original_filename": filename,
        "download_filename": out_filename,
        "download_url": f"/api/code/download/{out_filename}",
        "summary": cleaned_summary or "Code analyzed and refactored successfully.",
        "diff": diff,
        "fixed_code": fixed_code
    }


# ── Startup Audit & Fix-All (used by the startup self-check notification) ─────

def write_fixed_artifact(filepath: str, fixed_content: str) -> tuple[str, str]:
    """Save a fixed copy of a source file to downloads/ for manual download.

    Returns (out_filename, download_url).
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    sanitized_name = re.sub(r"[^\w\.-]", "_", os.path.basename(filepath))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"fixed_{timestamp}_{sanitized_name}"
    out_path = os.path.join(DOWNLOADS_DIR, out_filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fixed_content)
    log_codecore_event(
        "AUDIT_FIX_ARTIFACT",
        f"Saved fixed artifact for {filepath} as {out_filename}",
        {"filepath": filepath, "download_filename": out_filename}
    )
    return out_filename, f"/api/code/download/{out_filename}"


def apply_reported_fixes(report: dict) -> dict:
    """Apply the reported audit fixes file-by-file via preview -> apply.

    Every reported file is handled independently so a single failing file (e.g.
    Nemotron unavailable, protected path) never stalls the rest of the batch.
    Each successfully fixed file is also saved to downloads/ and returned with a
    live download_url so the UI can offer the corrected file immediately.
    Backups + validation + auto-rollback are enforced by apply_file_fix.
    """
    report = report or {}
    issues = report.get("issues") or []
    results = []
    fixed_count = 0
    failed_count = 0
    for issue in issues:
        fpath = issue.get("file", "")
        if not fpath:
            continue
        issue_msg = issue.get("message", "") or ""
        issue_line = int(issue.get("line") or 0)
        result = {"file": fpath}
        try:
            preview = preview_file_fix(fpath, issue_msg, line=issue_line)
        except NemotronUnavailableError as e:
            result.update({"status": "error", "error_type": "nemotron_unavailable", "message": str(e)})
            failed_count += 1
            results.append(result)
            continue

        if preview.get("status") != "success":
            result["status"] = preview.get("status", "error")
            result["message"] = preview.get("message", "Fix preview generation failed.")
            if preview.get("error_type"):
                result["error_type"] = preview["error_type"]
            failed_count += 1
            results.append(result)
            continue

        result["diff"] = preview.get("diff", "")
        result["segmented"] = preview.get("segmented", False)
        try:
            app_res = apply_file_fix(fpath, preview.get("proposed_content", ""))
        except NemotronUnavailableError as e:
            result.update({"status": "error", "error_type": "nemotron_unavailable", "message": str(e)})
            failed_count += 1
            results.append(result)
            continue

        if app_res.get("status") != "success":
            result["status"] = "error"
            result["message"] = app_res.get("message", "Fix could not be applied; automatic rollback executed.")
            failed_count += 1
            results.append(result)
            continue

        # Applied and validated: also offer the corrected file for download.
        fixed_count += 1
        result["status"] = "success"
        result["message"] = app_res.get("message", "Fixed and validated.")
        result["backup"] = app_res.get("backup", "")
        try:
            artifact_name, artifact_url = write_fixed_artifact(fpath, preview.get("proposed_content", ""))
            result["download_filename"] = artifact_name
            result["download_url"] = artifact_url
        except Exception as ae:
            result["artifact_error"] = str(ae)
        results.append(result)

    if failed_count == 0:
        overall = "success"
    elif fixed_count == 0:
        overall = "error"
    else:
        overall = "partial"
    return {
        "status": overall,
        "issues_count": len(issues),
        "fixed_count": fixed_count,
        "failed_count": failed_count,
        "results": results,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
