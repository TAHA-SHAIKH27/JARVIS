"""Safe terminal for agentic shell/git/test execution.

Design: the agent runs ON the user's own machine, but task text can contain
untrusted content (web pages, filenames). So every command passes a policy
gate before anything executes:

- shell=False always (no cmd/powershell metachar interpretation)
- first token must be an allowlisted binary or a natively-implemented
  read-only command (dir/ls/echo/type/cat need no subprocess at all)
- git is read-only (status/diff/log/...); push/commit/reset/clean are refused
- python runs workspace scripts or `-m pytest` only (never `-c`, never pip install)
- cwd is confined to the workspace root (no `..` escapes, no absolute outsiders)
- timeouts + output truncation on everything

Anything outside policy returns an error dict — never raises.
"""
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

# Workspace root = repo root (parent of backend/).
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

OUTPUT_CAP = 8000
DEFAULT_TIMEOUT_S = 120
TEST_TIMEOUT_S = 300

# Binaries allowed via subprocess (resolved with shutil.which; never shell=True).
SAFE_BINARIES = {"git", "python", "pip", "pytest", "npm", "node"}

# Read-only commands implemented natively (no subprocess at all).
NATIVE_COMMANDS = {"echo", "dir", "ls", "type", "cat", "pwd"}

# Read-only git subcommands. Everything else (commit/push/reset/clean/...) refused.
GIT_READONLY = {"status", "diff", "log", "branch", "remote", "stash",
                "show", "blame", "ls-files", "rev-parse"}
GIT_BLOCKED_FLAGS = ("-c", "--config", "--exec", "--exec-path")

# Read-only pip subcommands.
PIP_READONLY = {"list", "show", "check", "freeze", "--version"}

# npm subcommands (run/test execute the workspace's own package.json scripts).
NPM_ALLOWED = {"run", "test", "ls", "list", "--version", "-v"}

# Tokens that only mean something to a shell; rejected defense-in-depth
# (subprocess runs with shell=False, so these would be inert literals anyway).
SHELL_TOKENS = {"|", ">", "<", ">>", "&", ";", "&&", "||", "$(", "`"}


def _split_command(command: str) -> List[str]:
    """Split on whitespace (no quote-awareness needed: quotes are inert
    literals under shell=False, so treat them as ordinary characters)."""
    return [t for t in command.strip().split() if t]


def _confine_path(path: str) -> Optional[str]:
    """Resolve `path` (relative to workspace) and return absolute path, or
    None when it escapes the workspace or is otherwise invalid."""
    if not path or not path.strip():
        return None
    candidate = path.strip().strip("\"'")
    abs_path = os.path.abspath(os.path.join(WORKSPACE_ROOT, candidate))
    try:
        if os.path.commonpath([abs_path, WORKSPACE_ROOT]) != WORKSPACE_ROOT:
            return None
    except ValueError:
        return None
    return abs_path


def check_policy(argv: List[str]) -> Optional[str]:
    """Return an error message when argv violates policy, else None."""
    if not argv:
        return "Empty command"
    for tok in argv:
        if tok in SHELL_TOKENS or tok.startswith("$(") or "`" in tok:
            return f"Shell metacharacters are not allowed: {tok}"
    prog = os.path.basename(argv[0]).lower()
    if prog in NATIVE_COMMANDS:
        return None
    if prog not in SAFE_BINARIES:
        return (f"Command not allowed: {argv[0]} "
                f"(allowed: {sorted(SAFE_BINARIES | NATIVE_COMMANDS)})")
    rest = argv[1:]
    if prog == "git":
        if not rest:
            return "git needs a subcommand"
        if rest[0].startswith("-"):
            return f"git flag subcommands are not allowed: {rest[0]}"
        if rest[0] not in GIT_READONLY:
            return (f"git '{rest[0]}' is not allowed (read-only: "
                    f"{sorted(GIT_READONLY)})")
        for flag in rest[1:]:
            if flag in GIT_BLOCKED_FLAGS or flag.startswith("--exec"):
                return f"git flag is not allowed: {flag}"
        return None
    if prog == "python":
        if not rest:
            return "python needs a script or -m module"
        if rest[0] == "-c":
            return "python -c is not allowed (run a workspace script instead)"
        if rest[0] == "-m":
            if len(rest) < 2:
                return "python -m needs a module"
            if rest[1] == "pytest":
                return None
            if rest[1] == "pip":
                if len(rest) < 3 or rest[2] not in PIP_READONLY:
                    return "python -m pip is read-only (list/show/check/freeze)"
                return None
            return f"python -m {rest[1]} is not allowed"
        script = _confine_path(rest[0])
        if not script or not os.path.isfile(script):
            return f"python script not found in workspace: {rest[0]}"
        if not script.lower().endswith(".py"):
            return "python can only run .py scripts"
        return None
    if prog == "pip":
        if not rest or rest[0] not in PIP_READONLY:
            return f"pip is read-only ({sorted(PIP_READONLY)})"
        return None
    if prog == "pytest":
        return None
    if prog == "npm":
        if not rest or rest[0] not in NPM_ALLOWED:
            return f"npm subcommand not allowed: {(rest[0:1] or ['?'])[0]}"
        return None
    if prog == "node":
        if not rest:
            return "node needs a script"
        script = _confine_path(rest[0])
        if not script or not os.path.isfile(script):
            return f"node script not found in workspace: {rest[0]}"
        if not script.lower().endswith((".js", ".mjs", ".cjs")):
            return "node can only run .js/.mjs/.cjs scripts"
        return None
    return None


def _native(argv: List[str], cwd: str) -> Dict[str, Any]:
    """Run dir/ls/echo/type/cat/pwd without any subprocess."""
    prog = os.path.basename(argv[0]).lower()
    if prog == "echo":
        out = " ".join(argv[1:])
        return {"status": "success", "message": out or "(empty)",
                "exit_code": 0, "stdout": out, "stderr": "", "truncated": False}
    if prog == "pwd":
        return {"status": "success", "message": cwd,
                "exit_code": 0, "stdout": cwd, "stderr": "", "truncated": False}
    if prog in ("dir", "ls"):
        target = _confine_path(argv[1]) if len(argv) > 1 else cwd
        if not target or not os.path.isdir(target):
            return {"status": "error", "message": f"Directory not found in workspace: {argv[1] if len(argv) > 1 else '.'}",
                    "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}
        try:
            entries = sorted(os.listdir(target))
        except Exception as e:
            return {"status": "error", "message": f"Cannot list directory: {e}",
                    "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}
        out = "\n".join(entries) if entries else "(empty directory)"
        return {"status": "success", "message": f"{len(entries)} entries in {target}",
                "exit_code": 0, "stdout": out, "stderr": "", "truncated": False}
    if prog in ("type", "cat"):
        if len(argv) < 2:
            return {"status": "error", "message": "type/cat needs a file path",
                    "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}
        target = _confine_path(argv[1])
        if not target or not os.path.isfile(target):
            return {"status": "error", "message": f"File not found in workspace: {argv[1]}",
                    "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(OUTPUT_CAP + 1)
        except Exception as e:
            return {"status": "error", "message": f"Cannot read file: {e}",
                    "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}
        truncated = len(text) > OUTPUT_CAP
        return {"status": "success", "message": f"Read {target}",
                "exit_code": 0, "stdout": text[:OUTPUT_CAP],
                "stderr": "", "truncated": truncated}
    return {"status": "error", "message": f"Unknown native command: {prog}",
            "exit_code": 1, "stdout": "", "stderr": "", "truncated": False}


def run(command: str, workdir: str = "", timeout_s: int = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    """Policy-gated command execution. Never raises; always a result dict."""
    argv = _split_command(command or "")
    problem = check_policy(argv)
    if problem:
        return {"status": "error", "message": f"Blocked by terminal policy: {problem}",
                "exit_code": -1, "stdout": "", "stderr": "", "truncated": False,
                "command": command}
    cwd = WORKSPACE_ROOT
    if workdir and workdir.strip():
        confined = _confine_path(workdir.strip())
        if not confined or not os.path.isdir(confined):
            return {"status": "error",
                    "message": f"Workdir outside workspace or not a directory: {workdir}",
                    "exit_code": -1, "stdout": "", "stderr": "",
                    "truncated": False, "command": command}
        cwd = confined
    prog = os.path.basename(argv[0]).lower()
    if prog in NATIVE_COMMANDS:
        res = _native(argv, cwd)
        res["command"] = command
        res["cwd"] = cwd
        return res
    exe = shutil.which(argv[0])
    if not exe:
        # pytest/pip may only exist as `python -m`; surface a clear error.
        return {"status": "error",
                "message": f"Executable not found on PATH: {argv[0]}",
                "exit_code": -1, "stdout": "", "stderr": "",
                "truncated": False, "command": command}
    try:
        completed = subprocess.run(
            [exe] + argv[1:], shell=False, cwd=cwd,
            capture_output=True, text=True, errors="replace",
            timeout=max(5, min(timeout_s, 600)))
    except subprocess.TimeoutExpired:
        return {"status": "error",
                "message": f"Command timed out after {timeout_s}s: {command}",
                "exit_code": -1, "stdout": "", "stderr": "",
                "truncated": False, "command": command, "cwd": cwd}
    except Exception as e:
        return {"status": "error", "message": f"Command failed to start: {e}",
                "exit_code": -1, "stdout": "", "stderr": "",
                "truncated": False, "command": command, "cwd": cwd}
    stdout, stderr = completed.stdout or "", completed.stderr or ""
    truncated = False
    if len(stdout) > OUTPUT_CAP:
        stdout, truncated = stdout[:OUTPUT_CAP], True
    if len(stderr) > OUTPUT_CAP:
        stderr, truncated = stderr[:OUTPUT_CAP], True
    ok = completed.returncode == 0
    tail_lines = (stderr.strip().splitlines() or stdout.strip().splitlines() or [""])
    return {"status": "success" if ok else "error",
            "message": (f"Exit {completed.returncode}: {command}"
                        + (f" — {tail_lines[-1][:200]}" if tail_lines else "")),
            "exit_code": completed.returncode, "stdout": stdout,
            "stderr": stderr, "truncated": truncated,
            "command": command, "cwd": cwd}


def run_tests(target: str = "", extra_args: str = "",
              timeout_s: int = TEST_TIMEOUT_S) -> Dict[str, Any]:
    """Run the pytest suite (agent's standard verification command)."""
    parts = ["python", "-m", "pytest", "-q"]
    if target and target.strip():
        # Targets must stay inside the workspace.
        for piece in target.strip().split():
            if _confine_path(piece) is None and not piece.startswith("-"):
                return {"status": "error",
                        "message": f"Blocked by terminal policy: test target outside workspace: {piece}",
                        "exit_code": -1, "stdout": "", "stderr": "",
                        "truncated": False, "command": f"pytest {target}"}
            parts.append(piece)
    if extra_args and extra_args.strip():
        parts += extra_args.strip().split()
    return run(" ".join(parts), timeout_s=timeout_s)


def git_op(operation: str, args: str = "") -> Dict[str, Any]:
    """Read-only git inspection (status/diff/log/branch/...)."""
    op = (operation or "").strip().lower()
    if op not in GIT_READONLY:
        return {"status": "error",
                "message": f"Blocked by terminal policy: git '{operation}' is not read-only",
                "exit_code": -1, "stdout": "", "stderr": "",
                "truncated": False, "command": f"git {operation}"}
    return run(f"git {op} {args or ''}".strip())


# ─────────────────────────────────────────────────────────────────────────
# Output summarization (agentic replies: short analysis, not raw dumps)
# ─────────────────────────────────────────────────────────────────────────

SUMMARY_CAP = 600


def _cap(text: str) -> str:
    text = (text or "").strip()
    if len(text) > SUMMARY_CAP:
        return text[:SUMMARY_CAP].rstrip() + "…"
    return text


def _first_token(command: str) -> str:
    parts = _split_command(command or "")
    return os.path.basename(parts[0]).lower() if parts else ""


def _nonempty_lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _summarize_git_status(stdout: str) -> str:
    lines = _nonempty_lines(stdout)
    branch = ""
    m = re.search(r"^On branch (\S+)", stdout, re.M)
    if m:
        branch = m.group(1)
    sync = ""
    if "up to date" in stdout:
        sync = "up to date"
    else:
        m2 = re.search(r"Your branch is (ahead|behind)[^\n]*", stdout)
        if m2:
            sync = m2.group(0).strip().rstrip(".")
    modified = len(re.findall(r"^\s*modified:\s+", stdout, re.M))
    deleted = len(re.findall(r"^\s*deleted:\s+", stdout, re.M))
    newfile = len(re.findall(r"^\s*new file:\s+", stdout, re.M))
    renamed = len(re.findall(r"^\s*renamed:\s+", stdout, re.M))
    untracked = 0
    in_untracked = False
    for raw in stdout.splitlines():
        if "Untracked files:" in raw:
            in_untracked = True
            continue
        if in_untracked:
            s = raw.strip()
            if not s or s.startswith("(") or s.startswith("nothing"):
                continue
            if re.match(r"^(Changes|Untracked|no changes)", s):
                break
            untracked += 1
    bits = []
    if modified:
        bits.append(f"{modified} modified")
    if newfile:
        bits.append(f"{newfile} new")
    if deleted:
        bits.append(f"{deleted} deleted")
    if renamed:
        bits.append(f"{renamed} renamed")
    if untracked:
        bits.append(f"{untracked} untracked")
    head = f"Branch {branch}" if branch else "Git status"
    if sync:
        head += f" ({sync})"
    if not bits:
        return f"{head}. Working tree clean."
    return f"{head}. {', '.join(bits)}."


def _summarize_git_diff(stdout: str) -> str:
    files = re.findall(r"^diff --git a/(.+?) b/", stdout, re.M)
    adds = len(re.findall(r"^\+(?![+])", stdout, re.M))
    dels = len(re.findall(r"^-(?![-])", stdout, re.M))
    if not files:
        return "No differences."
    names = ", ".join(files[:5]) + ("…" if len(files) > 5 else "")
    return f"{len(files)} file(s) changed (+{adds}/-{dels}): {names}."


def _summarize_git_log(stdout: str) -> str:
    commits = len(re.findall(r"^commit ", stdout, re.M))
    subjects = [ln for ln in _nonempty_lines(stdout)
                if not ln.startswith(("commit ", "Author:", "Date:", "Merge:"))]
    latest = subjects[0][:100] if subjects else ""
    if not commits:
        return "No commits found."
    base = f"{commits} commit(s) shown."
    return f"{base} Latest: {latest}." if latest else base


def _summarize_git_branch(stdout: str) -> str:
    current, total = "", 0
    for ln in _nonempty_lines(stdout):
        total += 1
        if ln.startswith("*"):
            current = ln[1:].strip()
    if current:
        return f"Current branch: {current} ({total} branches)."
    return f"{total} branches."


def _summarize_pytest(stdout: str) -> str:
    summary = ""
    for ln in reversed(_nonempty_lines(stdout)):
        if re.search(r"\d+ (passed|failed|error)", ln):
            summary = ln.strip("= .")
            break
    failed = re.findall(r"^FAILED (\S+)", stdout, re.M)
    if not summary:
        return "Test run finished (no summary line found)."
    if failed:
        names = ", ".join(failed[:5]) + ("…" if len(failed) > 5 else "")
        return f"{summary}. Failed: {names}."
    return f"{summary}."


def _summarize_listing(stdout: str) -> str:
    if "(empty directory)" in stdout:
        return "Directory is empty."
    names = _nonempty_lines(stdout)
    if not names:
        return "Directory is empty."
    if len(names) <= 12:
        return f"{len(names)} entries: {', '.join(names)}."
    return f"{len(names)} entries, including {', '.join(names[:8])}…."


def summarize_output(command: str, stdout: str, exit_code: int = 0) -> str:
    """Turn raw command output into a short agentic summary (≤ ~600 chars).

    Deterministic and instant (no LLM round-trip): parses the known shapes
    (git status/diff/log/branch, pytest, directory listings) and compresses
    anything else to its key lines. Non-zero exits report the failure tail."""
    text = (stdout or "").strip()
    if exit_code != 0:
        tail = _nonempty_lines(text)
        detail = tail[-1][:200] if tail else "no output"
        return f"Command failed (exit {exit_code}): {detail}."
    if not text:
        return "Command finished with no output."
    argv = _split_command(command or "")
    prog = _first_token(command)
    sub = argv[1].lower() if len(argv) > 1 else ""
    if prog == "git":
        if sub == "status":
            return _cap(_summarize_git_status(text))
        if sub == "diff":
            return _cap(_summarize_git_diff(text))
        if sub == "log":
            return _cap(_summarize_git_log(text))
        if sub == "branch":
            return _cap(_summarize_git_branch(text))
    if prog in ("pytest",) or (prog == "python" and "pytest" in argv):
        return _cap(_summarize_pytest(text))
    if prog in ("dir", "ls"):
        return _cap(_summarize_listing(text))
    if prog in ("echo", "pwd", "type", "cat"):
        return _cap(text)
    lines = _nonempty_lines(text)
    if len(lines) <= 6:
        return _cap(text)
    head = "\n".join(lines[:4])
    return f"{head}\n… (+{len(lines) - 4} more lines)."
