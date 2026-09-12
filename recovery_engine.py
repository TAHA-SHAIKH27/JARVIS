"""
recovery_engine.py — Independent Self-Healing & Crash Recovery Module for J.A.R.V.I.S.
====================================================================================
STANDALONE ARCHITECTURE:
- Zero dependency on main.py, agent.py, or any third-party framework (uses only Python standard library).
- Reads config.json directly for NVIDIA / Gemini credentials.
- Safe Patch Workflow: Backup -> NVIDIA NIM Diagnostic -> Apply Minimal Patch -> Validate (py_compile) -> Auto-Rollback on failure.
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
from datetime import datetime

# Protected files blacklist — recovery engine will NEVER modify these
PROTECTED_FILES = {
    ".env", "config.json", ".git", "credentials.json", "token.json", "client_secrets.json"
}

BACKUP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".backup")


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


def call_nvidia_nim(prompt: str, system_prompt: str = "", model: str = None) -> str:
    """Query NVIDIA NIM API (OpenAI-compatible) using standard urllib."""
    config = load_config()
    api_key = config.get("nvidia_api_key", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        print("[RECOVERY] No NVIDIA API key found; attempting Gemini fallback...", file=sys.stderr)
        return call_gemini_fallback(prompt, system_prompt)

    model_name = model or config.get("nvidia_model", "meta/llama-3.3-70b-instruct")
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
        "max_tokens": 4096
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            resp_body = resp.read().decode("utf-8")
            res_json = json.loads(resp_body)
            return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[RECOVERY] NVIDIA NIM error: {e}, trying Gemini fallback...", file=sys.stderr)
        return call_gemini_fallback(prompt, system_prompt)


def call_gemini_fallback(prompt: str, system_prompt: str = "") -> str:
    """Fallback LLM caller using Gemini API when NVIDIA is unavailable."""
    config = load_config()
    api_key = config.get("gemini_api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("No NVIDIA or Gemini API key configured in config.json")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    combined = (f"System: {system_prompt}\n\n" if system_prompt else "") + prompt
    payload = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    with urllib.request.urlopen(req, timeout=45) as resp:
        resp_body = resp.read().decode("utf-8")
        res_json = json.loads(resp_body)
        candidates = res_json.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
    return ""


def parse_traceback(traceback_text: str) -> dict:
    """
    Parse Python traceback to identify the exact problematic file and line.
    Returns: {"file": str, "line": int, "error": str}
    """
    lines = traceback_text.strip().splitlines()
    target_file = None
    target_line = None
    error_msg = ""

    # Search for File "...", line N
    for line in reversed(lines):
        if not error_msg and (":" in line or "Error" in line or "Exception" in line):
            error_msg = line.strip()
        match = re.search(r'File "([^"]+)", line (\d+)', line)
        if match:
            f_path = match.group(1)
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
        py_compile.compile(filepath, doraise=True)
        return True, "Syntax valid"
    except py_compile.PyCompileError as e:
        return False, str(e)


def extract_code_from_llm_response(response: str) -> str:
    """Extract code cleanly from markdown code blocks or raw response."""
    # Look for ```python ... ``` or ``` ... ```
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", response)
    if match:
        return match.group(1)
    return response.strip()


def recover_from_crash(crash_log_path: str, max_retries: int = 3) -> dict:
    """
    Analyze crash log, locate broken file, create backup, query NVIDIA NIM for a minimal fix,
    apply patch, validate, and retry up to max_retries. If all fail, auto-rollback.
    """
    if not os.path.exists(crash_log_path):
        return {"status": "error", "message": f"Crash log not found: {crash_log_path}"}

    with open(crash_log_path, "r", encoding="utf-8", errors="replace") as f:
        traceback_text = f.read()

    parsed = parse_traceback(traceback_text)
    target_file = parsed.get("file")
    target_line = parsed.get("line")
    error_summary = parsed.get("error")

    if not target_file or not os.path.exists(target_file):
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
    print(f"[RECOVERY] ========================================")

    # Create master backup before attempting any modifications
    backup_path = create_backup(target_file, tag="crash_recovery")

    with open(target_file, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

    system_prompt = (
        "You are an expert Python systems recovery engineer for J.A.R.V.I.S.\n"
        "Your task: Fix the provided code file to resolve the specific crash/traceback error.\n"
        "RULES:\n"
        "1. Make ONLY the minimal necessary corrections to fix the bug.\n"
        "2. Do NOT change existing function signatures, API contracts, or unrelated features.\n"
        "3. Output the COMPLETE corrected code for the file inside a single ```python ... ``` block.\n"
        "4. Ensure zero syntax errors, valid imports, and proper exception handling."
    )

    current_error = error_summary
    for attempt in range(1, max_retries + 1):
        print(f"\n[RECOVERY] Attempt {attempt}/{max_retries} — Querying NVIDIA AI...")

        prompt = (
            f"FILE TO REPAIR: {target_file}\n"
            f"CRASH TRACEBACK:\n{traceback_text}\n\n"
            f"SPECIFIC ERROR: {current_error}\n\n"
            f"CURRENT FILE CONTENT:\n```python\n{original_content}\n```\n\n"
            f"Please output the complete fixed version of this file inside ```python ... ``` code block."
        )

        try:
            llm_response = call_nvidia_nim(prompt, system_prompt)
            fixed_code = extract_code_from_llm_response(llm_response)

            if not fixed_code or len(fixed_code) < 20:
                print(f"[RECOVERY] Attempt {attempt}: Received invalid/empty response from LLM.")
                continue

            # Write fixed code
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(fixed_code)

            # Validate
            is_valid, val_msg = validate_python_file(target_file)
            if is_valid:
                print(f"[RECOVERY] SUCCESS: File {os.path.basename(target_file)} repaired and validated!")
                return {
                    "status": "success",
                    "file": target_file,
                    "attempt": attempt,
                    "backup": backup_path,
                    "message": f"Successfully repaired {os.path.basename(target_file)} on attempt {attempt}."
                }
            else:
                print(f"[RECOVERY] Attempt {attempt} validation failed: {val_msg}")
                current_error = f"Validation py_compile error: {val_msg}"
                time.sleep(1)

        except Exception as e:
            print(f"[RECOVERY] Attempt {attempt} error: {e}")
            current_error = str(e)
            time.sleep(1)

    # If all attempts failed, execute automatic rollback
    print(f"\n[RECOVERY] FAILED: All {max_retries} attempts failed. Rolling back to original state...")
    restore_backup(backup_path, target_file)

    return {
        "status": "failed_rolled_back",
        "file": target_file,
        "backup": backup_path,
        "message": f"Could not safely repair {os.path.basename(target_file)} after {max_retries} attempts. Rolled back safely."
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print("[RECOVERY] Recovery Engine is operational and ready.")
        cfg = load_config()
        has_nv = bool(cfg.get("nvidia_api_key"))
        has_gem = bool(cfg.get("gemini_api_key"))
        print(f"[RECOVERY] NVIDIA NIM configured: {has_nv} (Model: {cfg.get('nvidia_model', 'meta/llama-3.3-70b-instruct')})")
        print(f"[RECOVERY] Gemini fallback configured: {has_gem}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--recover":
        log_file = sys.argv[2]
        result = recover_from_crash(log_file)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python recovery_engine.py [--check | --recover <crash_log_path>]")
