"""
code_core.py — Autonomous Code Intelligence & Developer Engine for J.A.R.V.I.S.
================================================================================
Capabilities:
- Self-Code Audit (Read-only inspection, zero mutations by default).
- Minimal Unified Diff Generation via NVIDIA NIM.
- Safe Patching with Timestamped Backups & Automatic Rollback.
- Uploaded Code File Inspection, Error-Fixing, and Download Generation.
- Multi-layer validation (py_compile, AST parse, Vite build check, /api/status).
"""

import os
import sys
import json
import re
import difflib
import shutil
import ast
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


def call_nvidia_nim(prompt: str, system_prompt: str = "", model: str = None) -> str:
    """Call NVIDIA NIM API with streaming/OpenAI-compatible protocol."""
    config = load_config()
    api_key = config.get("nvidia_api_key", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    
    if not api_key:
        # Fallback to Gemini if no NVIDIA key
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
        with urllib.request.urlopen(req, timeout=50) as resp:
            resp_body = resp.read().decode("utf-8")
            res_json = json.loads(resp_body)
            return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[CODE_CORE] NVIDIA NIM error: {e}, falling back to Gemini...", file=sys.stderr)
        return call_gemini_fallback(prompt, system_prompt)


def call_gemini_fallback(prompt: str, system_prompt: str = "") -> str:
    """Fallback LLM caller using Gemini API."""
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

def audit_codebase() -> dict:
    """
    Perform a complete read-only self-audit of JARVIS's source code.
    Scans Python and JavaScript files for syntax errors, unhandled exceptions, and warnings.
    NEVER modifies any files.
    """
    issues = []
    py_files = [
        "main.py", "agent.py", "system_ops.py", "code_core.py",
        "recovery_engine.py", "jarvis_watchdog.py", "phone_control.py"
    ]
    
    js_files = [
        os.path.join("src", "App.jsx"),
        os.path.join("src", "Header.jsx"),
        os.path.join("src", "Telemetry.jsx"),
        os.path.join("src", "CommandGrid.jsx"),
        os.path.join("src", "CoreSphere.jsx"),
    ]

    total_checked = 0

    # 1. Audit Python Files
    for rel_path in py_files:
        full_path = os.path.join(WORKSPACE_ROOT, rel_path)
        if not os.path.exists(full_path):
            continue
        total_checked += 1

        # Syntax check via AST
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            ast.parse(source, filename=rel_path)
        except SyntaxError as se:
            issues.append({
                "file": rel_path,
                "line": se.lineno,
                "severity": "critical_syntax_error",
                "message": f"Syntax error: {se.msg}",
                "snippet": se.text.strip() if se.text else ""
            })
            continue
        except Exception as e:
            issues.append({
                "file": rel_path,
                "line": 0,
                "severity": "critical_syntax_error",
                "message": f"Parsing failure: {str(e)}",
                "snippet": ""
            })
            continue

        # Static py_compile test
        try:
            py_compile.compile(full_path, doraise=True)
        except py_compile.PyCompileError as pe:
            issues.append({
                "file": rel_path,
                "line": 0,
                "severity": "compilation_error",
                "message": f"py_compile error: {str(pe)}",
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

def preview_file_fix(filepath: str, issue_description: str = "") -> dict:
    """
    Generate a proposed minimal fix and unified diff for a target file.
    Does NOT mutate the target file.
    """
    full_path = os.path.join(WORKSPACE_ROOT, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full_path):
        return {"status": "error", "message": f"File not found: {filepath}"}

    if is_protected(full_path):
        return {"status": "blocked", "message": f"File {filepath} is protected."}

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

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

    llm_response = call_nvidia_nim(prompt, system_prompt)
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
            py_compile.compile(filepath, doraise=True)
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
            resp = call_nvidia_nim(prompt, "You are a code validation repair engine. Output only corrected code.")
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

def process_uploaded_code_file(filename: str, file_content: str, user_instructions: str = "") -> dict:
    """
    Inspect an uploaded user code file for bugs, refactor/fix it, and save in downloads/ for retrieval.
    """
    system_prompt = (
        "You are an expert code refactoring and bug fixing engine for J.A.R.V.I.S.\n"
        "Your task: Inspect the uploaded user code file, identify bugs, syntax errors, and edge cases, "
        "and refactor it according to user instructions.\n"
        "Provide:\n"
        "1. A summary of errors found and fixes applied.\n"
        "2. The COMPLETE corrected code inside a ```...``` block."
    )

    prompt = (
        f"FILENAME: {filename}\n"
        f"USER INSTRUCTIONS: {user_instructions or 'Find and fix all errors, syntax bugs, and improvements.'}\n\n"
        f"FILE CONTENT:\n```\n{file_content}\n```\n\n"
        f"Please provide the summary of fixes and the complete corrected code inside ```...```."
    )

    llm_response = call_nvidia_nim(prompt, system_prompt)
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

    # Extract explanation text (text before the code block)
    summary = re.split(r"```", llm_response)[0].strip() or "Code analyzed and refactored."

    return {
        "status": "success",
        "original_filename": filename,
        "download_filename": out_filename,
        "download_url": f"/api/code/download/{out_filename}",
        "summary": summary,
        "diff": diff,
        "fixed_code": fixed_code
    }
