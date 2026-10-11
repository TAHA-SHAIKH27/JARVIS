"""ubuntu_backup.py — reliable local-first automatic backups to an Ubuntu server.

Local-first contract: every file is saved on the Windows laptop FIRST by the
normal JARVIS workflow. This module only *copies* already-saved files to the
Ubuntu backup root. A backup failure never deletes, moves, or blocks local
files, and never raises into the caller (``notify_file_saved`` is best-effort).

Design (stdlib only, mirrors ``backend/tools/scheduler.py`` conventions):
- Persistent JSON queue (atomic ``tmp`` + ``os.replace`` writes, ``RLock``)
  so pending jobs survive crashes, shutdowns, and restarts.
- Reconciliation scans discover files missed while JARVIS was offline; no
  reliance on a filesystem watcher.
- Stability gate (mtime age + size steadiness) avoids queueing/uploading
  files that a generator is still writing.
- Single-flight worker thread (one transfer at a time, daemon) with bounded
  exponential backoff + jitter, pause/resume, and graceful shutdown.
- Transfer via the Windows OpenSSH client (``ssh``/``scp``) with the
  dedicated key, ``BatchMode=yes``, default host-key verification (never
  disabled), temp remote names (``.part-<jobid>``), and SHA-256 verification
  before a job is marked complete.
- No remote deletion, ever. Prior remote versions are kept as
  ``<name>.bak-<timestamp>`` snapshots instead of being silently replaced.

Secrets are never embedded here; the key path is configurable and the queue
excludes secrets/credentials/tokens by default.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import random
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
CONFIG_PATH = os.path.join(DATA_DIR, "ubuntu_backup_config.json")
QUEUE_PATH = os.path.join(DATA_DIR, "ubuntu_backup_queue.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "host": "192.168.1.110",
    "fallback_host": "",  # e.g. Tailscale IP/hostname; tried when host is unreachable
    "user": "taha",
    "key_path": os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                             ".ssh", "jarvis_backup_ed25519"),
    "remote_root": "/home/taha/JARVIS-Backups/",
    # Local roots backed up (absolute paths; defaults resolved at load time).
    "roots": [],
    "exclude_name_patterns": [
        "*.tmp", "*.temp", "*.swp", "~*", ".~lock.*", "*.part-*",
        "*.crdownload", "*.pyc", "*.pyo", "Thumbs.db", ".DS_Store",
    ],
    "exclude_dir_names": [
        "__pycache__", ".git", ".venv", "venv", "env", "node_modules",
        ".pytest_cache", ".cache",
    ],
    # Sensitive files are never backed up (matched case-insensitively
    # against the file name and, for some, any path component).
    "exclude_sensitive_names": [
        ".env", ".env.*", "*token*.json", "*secret*", "*credential*",
        "*api_key*", "*.pem", "*.key", "id_rsa*", "id_ed25519*",
        "client_secret.json", "config.json",
    ],
    "max_file_bytes": 500 * 1024 * 1024,  # skip single files larger than this
    "stable_seconds": 2.0,      # mtime must be this old before upload (faster for small files)
    "scan_interval_seconds": 300.0,
    "tick_seconds": 2.0,        # worker polls more frequently
    "ssh_timeout_seconds": 10,
    "transfer_timeout_seconds": 120,
    "retry_base_seconds": 30.0,
    "retry_max_seconds": 3600.0,
    "retry_jitter_seconds": 10.0,
    "max_retries": 20,          # then status -> "failed" (kept for manual retry)
    "max_history": 500,         # cap on completed jobs retained
    "max_failed": 200,          # cap on failed jobs retained
    "server_cache_ttl_seconds": 30.0,
    "min_free_bytes": 50 * 1024 * 1024,  # refuse new jobs below this free space
}

ACTIVE_STATUSES = ("pending", "uploading", "retrying")
TERMINAL_STATUSES = ("completed", "failed")

_LOCK = threading.RLock()
_WORKER_STARTED = False
_STOP_EVENT = threading.Event()
_WORKER_THREAD: Optional[threading.Thread] = None

_SERVER_CACHE: Dict[str, Any] = {"ok": False, "at": 0.0, "msg": "never checked", "host": ""}

# Transport indirection: tests inject fakes via ``set_transport``. The default
# uses the real OpenSSH client.
_Transport = Callable[..., Any]
_TRANSPORTS: Dict[str, Any] = {}


def _default_roots() -> List[str]:
    return [os.path.join(BASE_DIR, "work_files"),
            os.path.join(BASE_DIR, "downloads")]


# ── config ──────────────────────────────────────────────────────────────────
def _apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    mapping = {
        "JARVIS_BACKUP_ENABLED": ("enabled", lambda v: v.strip().lower() not in ("0", "false", "no", "off")),
        "JARVIS_BACKUP_HOST": ("host", str),
        "JARVIS_BACKUP_FALLBACK_HOST": ("fallback_host", str),
        "JARVIS_BACKUP_USER": ("user", str),
        "JARVIS_BACKUP_KEY": ("key_path", str),
        "JARVIS_BACKUP_REMOTE_ROOT": ("remote_root", str),
    }
    for env, (key, conv) in mapping.items():
        raw = os.environ.get(env)
        if raw is not None and str(raw).strip() != "":
            try:
                cfg[key] = conv(raw)
            except Exception:
                pass
    return cfg


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            cfg.update(stored)
    except (OSError, ValueError, TypeError):
        pass
    if not cfg.get("roots"):
        cfg["roots"] = _default_roots()
    cfg["key_path"] = os.path.expandvars(os.path.expanduser(str(cfg.get("key_path") or "")))
    remote = str(cfg.get("remote_root") or "").replace("\\", "/")
    if remote and not remote.endswith("/"):
        remote += "/"
    cfg["remote_root"] = remote or "/home/taha/JARVIS-Backups/"
    return _apply_env_overrides(cfg)


def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a partial config update. Returns the effective config."""
    with _LOCK:
        current = load_config()
        allowed = set(DEFAULT_CONFIG.keys())
        for key, value in (patch or {}).items():
            if key in allowed:
                current[key] = value
        # Persist only non-default roots/exclusions verbatim; always persist.
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(current, handle, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)
        except OSError:
            pass
        return current


def sanitized_config() -> Dict[str, Any]:
    """Config safe for UI display (no secret values; key path is not secret)."""
    return load_config()


# ── queue store ─────────────────────────────────────────────────────────────
def _read_queue() -> Dict[str, Any]:
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("jobs", {})
            data.setdefault("paused", False)
            data.setdefault("last_success", None)
            data.setdefault("last_scan", None)
            data.setdefault("note", "")
            if isinstance(data["jobs"], list):  # tolerate legacy shape
                data["jobs"] = {j.get("id", uuid.uuid4().hex): j for j in data["jobs"]
                                if isinstance(j, dict)}
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"jobs": {}, "paused": False, "last_success": None,
            "last_scan": None, "note": ""}


def _write_queue(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
        tmp = QUEUE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, QUEUE_PATH)
    except OSError:
        pass


def _prune(state: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    jobs = state.get("jobs", {})
    completed = sorted((j for j in jobs.values() if j.get("status") == "completed"),
                       key=lambda j: j.get("completed_at") or 0)
    overflow = len(completed) - int(cfg.get("max_history") or 500)
    for job in completed[:max(0, overflow)]:
        jobs.pop(job.get("id", ""), None)
    failed = sorted((j for j in jobs.values() if j.get("status") == "failed"),
                    key=lambda j: j.get("updated_at") or 0)
    overflow = len(failed) - int(cfg.get("max_failed") or 200)
    for job in failed[:max(0, overflow)]:
        jobs.pop(job.get("id", ""), None)


def _active_for_source(jobs: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    for job in jobs.values():
        if job.get("source") == source and job.get("status") in ACTIVE_STATUSES:
            return job
    return None


def _completed_for_source(jobs: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    best = None
    for job in jobs.values():
        if job.get("source") == source and job.get("status") == "completed":
            if best is None or (job.get("completed_at") or 0) > (best.get("completed_at") or 0):
                best = job
    return best


# ── eligibility + stability ─────────────────────────────────────────────────
def _matches_any(name: str, patterns: List[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


def is_eligible(path: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """True when a file may be backed up. Symlinks are never followed."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False, "not-a-regular-file"
        name = os.path.basename(path)
        if _matches_any(name, cfg.get("exclude_name_patterns") or []):
            return False, "excluded-temp"
        if _matches_any(name, cfg.get("exclude_sensitive_names") or []):
            return False, "excluded-sensitive"
        parts = os.path.abspath(path).split(os.sep)
        excluded_dirs = {d.lower() for d in (cfg.get("exclude_dir_names") or [])}
        for part in parts:
            if part.lower() in excluded_dirs:
                return False, "excluded-dir"
        try:
            size = os.path.getsize(path)
        except OSError:
            return False, "unreadable"
        if size > int(cfg.get("max_file_bytes") or 0):
            return False, "too-large"
        return True, ""
    except Exception:
        return False, "error"


def _is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def _root_for(path: str, cfg: Dict[str, Any]) -> Optional[str]:
    for root in (cfg.get("roots") or []):
        try:
            if _is_under(path, root):
                return os.path.abspath(root)
        except Exception:
            continue
    return None


def is_stable(path: str, cfg: Dict[str, Any]) -> bool:
    """A file is ready only if it is not currently being written."""
    try:
        stable_after = float(cfg.get("stable_seconds") or 5.0)
        first_size = os.path.getsize(path)
        first_mtime = os.path.getmtime(path)
        if time.time() - first_mtime < stable_after:
            return False
        time.sleep(1.0)
        return (os.path.getsize(path) == first_size
                and os.path.getmtime(path) == first_mtime)
    except OSError:
        return False


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel_for(path: str, root: str) -> str:
    return os.path.relpath(os.path.abspath(path), os.path.abspath(root)).replace(os.sep, "/")


# ── enqueue ─────────────────────────────────────────────────────────────────
def _disk_ok() -> bool:
    try:
        free = shutil.disk_usage(os.path.dirname(QUEUE_PATH)).free
        return free >= int(load_config().get("min_free_bytes") or 0)
    except Exception:
        return True


def enqueue_file(path: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Queue one file for backup. Never raises; returns a result dict."""
    try:
        cfg = cfg or load_config()
        abspath = os.path.abspath(path)
        ok, reason = is_eligible(abspath, cfg)
        if not ok:
            return {"status": "skipped", "reason": reason}
        root = _root_for(abspath, cfg)
        if root is None:
            return {"status": "skipped", "reason": "outside-backup-roots"}
        if not _disk_ok():
            return {"status": "skipped", "reason": "low-disk-space"}
        try:
            size = os.path.getsize(abspath)
            mtime = os.path.getmtime(abspath)
        except OSError as exc:
            return {"status": "skipped", "reason": f"unreadable: {exc}"}
        with _LOCK:
            state = _read_queue()
            jobs = state["jobs"]
            active = _active_for_source(jobs, abspath)
            if active is not None:
                if active.get("size") == size and active.get("mtime") == mtime:
                    return {"status": "duplicate", "job_id": active.get("id")}
                # File changed while a job was pending: refresh in place.
                active.update({"size": size, "mtime": mtime, "sha256": None,
                               "status": "pending", "retries": 0,
                               "next_retry_at": None, "last_error": "",
                               "rel": rel_for(abspath, root),
                               "updated_at": time.time()})
                _write_queue(state)
                return {"status": "requeued", "job_id": active.get("id")}
            done = _completed_for_source(jobs, abspath)
            if done is not None and done.get("size") == size and done.get("mtime") == mtime:
                return {"status": "duplicate", "job_id": done.get("id")}
            job_id = uuid.uuid4().hex
            now = time.time()
            jobs[job_id] = {
                "id": job_id, "source": abspath, "rel": rel_for(abspath, root),
                "root": root, "size": size, "mtime": mtime, "sha256": None,
                "status": "pending", "retries": 0, "next_retry_at": None,
                "last_error": "", "queued_at": now, "updated_at": now,
                "completed_at": None,
            }
            _prune(state, cfg)
            _write_queue(state)
            return {"status": "queued", "job_id": job_id}
    except Exception as exc:  # never break the caller's save path
        return {"status": "error", "reason": str(exc)[:200]}


def notify_file_saved(path: str) -> Dict[str, Any]:
    """Best-effort hook for file-generation workflows. Never raises.

    The file must already be fully saved locally before calling this; a
    backup failure here never affects the local file.
    """
    try:
        return enqueue_file(path)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:200]}


def scan_and_enqueue(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Reconciliation scan: discover eligible files missed while offline."""
    cfg = cfg or load_config()
    counts = {"queued": 0, "duplicate": 0, "skipped": 0, "requeued": 0}
    try:
        with _LOCK:
            state = _read_queue()
            state["last_scan"] = time.time()
            _write_queue(state)
        for root in (cfg.get("roots") or []):
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # Prune excluded/symlinked dirs in place.
                kept = []
                for dirname in dirnames:
                    full = os.path.join(dirpath, dirname)
                    if os.path.islink(full):
                        continue
                    if dirname.lower() in [d.lower() for d in (cfg.get("exclude_dir_names") or [])]:
                        continue
                    kept.append(dirname)
                dirnames[:] = kept
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    if os.path.islink(full):
                        continue
                    res = enqueue_file(full, cfg)
                    counts[res.get("status", "skipped")] = counts.get(res.get("status", "skipped"), 0) + 1
        return {"status": "success", **counts}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}


# ── OpenSSH transport ───────────────────────────────────────────────────────
def _ssh_base(cfg: Dict[str, Any]) -> List[str]:
    """Base SSH command with performance optimizations."""
    # Performance options:
    # -o AddressFamily=inet        Force IPv4 (avoid IPv6 fallback delays)
    # -o Ciphers=...               Fastest AEAD ciphers (hardware-accelerated on modern CPUs)
    # -o MACs=...                  Fastest MACs (encrypt-then-MAC)
    # -o Compression=yes           Enable compression (helps text/code/docs)
    # -o TCPKeepAlive=yes          Keep connection alive
    # -o ServerAliveInterval=15    Detect dead connections faster
    # -o ServerAliveCountMax=3
    # -o ControlMaster=auto        Connection multiplexing (Unix only, disabled on Windows)
    # -o ControlPath=~/.ssh/cm-%r@%h:%p
    # -o ControlPersist=60         Keep master open 60s after last use
    base = ["ssh", "-i", cfg["key_path"],
            "-o", "BatchMode=yes",
            "-o", "AddressFamily=inet",
            "-o", "Ciphers=aes128-gcm@openssh.com,chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-ctr,aes256-ctr",
            "-o", "MACs=hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com,umac-128-etm@openssh.com",
            "-o", "Compression=yes",
            "-o", "TCPKeepAlive=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", f"ConnectTimeout={int(cfg.get('ssh_timeout_seconds') or 15)}"]
    # ControlMaster only works on Unix (requires Unix domain sockets)
    if os.name != "nt":
        base += [
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={os.path.expanduser('~')}/.ssh/cm-%r@%h:%p",
            "-o", "ControlPersist=60",
        ]
    base.append(f"{cfg['user']}@{cfg['host']}")
    return base


def _scp_base(cfg: Dict[str, Any]) -> List[str]:
    """Base SCP command with performance optimizations (inherits SSH options)."""
    # SCP doesn't support all SSH options directly, but passes -o flags through
    base = ["scp", "-i", cfg["key_path"],
            "-o", "BatchMode=yes",
            "-o", "AddressFamily=inet",
            "-o", "Ciphers=aes128-gcm@openssh.com,chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-ctr,aes256-ctr",
            "-o", "MACs=hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com,umac-128-etm@openssh.com",
            "-o", "Compression=yes",
            "-o", "TCPKeepAlive=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", f"ConnectTimeout={int(cfg.get('ssh_timeout_seconds') or 15)}"]
    # ControlMaster only works on Unix (requires Unix domain sockets)
    if os.name != "nt":
        base += [
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={os.path.expanduser('~')}/.ssh/cm-%r@%h:%p",
            "-o", "ControlPersist=60",
        ]
    return base


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def candidate_hosts(cfg: Dict[str, Any]) -> List[str]:
    hosts = [str(cfg.get("host") or "").strip()]
    fallback = str(cfg.get("fallback_host") or "").strip()
    if fallback:
        hosts.append(fallback)
    return [h for h in hosts if h]


def check_server(cfg: Optional[Dict[str, Any]] = None,
                 force: bool = False) -> Dict[str, Any]:
    """Probe reachability (cached). Never marks files backed up — probe only."""
    cfg = cfg or load_config()
    now = time.time()
    with _LOCK:
        cache = dict(_SERVER_CACHE)
    if not force and now - cache.get("at", 0) < float(cfg.get("server_cache_ttl_seconds") or 30):
        return {"reachable": cache["ok"], "host": cache.get("host", ""),
                "message": cache.get("msg", ""), "cached": True}
    check = _TRANSPORTS.get("check", _openssh_check)
    result = check(cfg)
    with _LOCK:
        _SERVER_CACHE.update({"ok": bool(result.get("reachable")),
                              "at": now, "msg": result.get("message", ""),
                              "host": result.get("host", "")})
    result["cached"] = False
    return result


def _openssh_check(cfg: Dict[str, Any]) -> Dict[str, Any]:
    last_msg = "unreachable"
    for host in candidate_hosts(cfg):
        trial = dict(cfg)
        trial["host"] = host
        try:
            # Use optimized SSH base for health check too (fast connection reuse via ControlMaster)
            proc = subprocess.run(
                _ssh_base(trial) + ["echo", "jarvis-backup-ok"],
                capture_output=True, text=True,
                timeout=int(cfg.get("ssh_timeout_seconds") or 15) + 5)
            if proc.returncode == 0 and "jarvis-backup-ok" in (proc.stdout or ""):
                return {"reachable": True, "host": host,
                        "message": f"ssh ok via {host}"}
            last_msg = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:200]
        except FileNotFoundError:
            return {"reachable": False, "host": "", "message": "ssh client not found"}
        except Exception as exc:
            last_msg = f"{type(exc).__name__}: {str(exc)[:160]}"
    return {"reachable": False, "host": "", "message": last_msg}


def _remote_paths(cfg: Dict[str, Any], rel: str, job_id: str) -> Tuple[str, str, str]:
    """Return (remote_dir, remote_final, remote_tmp) confined to remote_root."""
    safe_rel = rel.replace("\\", "/").strip("/")
    parts = [p for p in safe_rel.split("/") if p not in ("", ".", "..")]
    confined = "/".join(parts)
    if not confined:
        raise ValueError("empty remote path")
    root = (cfg.get("remote_root") or "").rstrip("/") + "/"
    final = root + confined
    remote_dir = final.rsplit("/", 1)[0] + "/"
    tmp = f"{final}.part-{job_id}"
    return remote_dir, final, tmp


def upload_and_verify(cfg: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """Copy one file via scp to a temp name, commit, and verify SHA-256."""
    uploader = _TRANSPORTS.get("upload", _openssh_upload)
    return uploader(cfg, job)


def _openssh_upload(cfg: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    source = job["source"]
    try:
        local_sha = sha256_of(source)
    except OSError as exc:
        return {"status": "error", "message": f"source unreadable: {exc}"}
    try:
        remote_dir, remote_final, remote_tmp = _remote_paths(cfg, job["rel"], job["id"])
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    timeout = int(cfg.get("transfer_timeout_seconds") or 120)
    last_host = ""
    last_err = ""
    for host in candidate_hosts(cfg):
        last_host = host
        trial = dict(cfg)
        trial["host"] = host
        try:
            # Ensure remote directory exists before scp (scp cannot create dirs)
            mkdir_cmd = _ssh_base(trial) + ["mkdir", "-p", remote_dir]
            mkdir = subprocess.run(mkdir_cmd, capture_output=True, text=True, timeout=timeout)
            if mkdir.returncode != 0:
                last_err = (mkdir.stderr or mkdir.stdout or f"mkdir exit {mkdir.returncode}").strip()[:200]
                continue
            # Use optimized SCP base command
            scp_cmd = _scp_base(trial) + [source, f"{trial['user']}@{host}:{remote_tmp}"]
            scp = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=timeout)
            if scp.returncode != 0:
                last_err = (scp.stderr or scp.stdout or f"scp exit {scp.returncode}").strip()[:200]
                continue
            # Atomic commit + checksum verification on remote
            commit = ("mkdir -p {d} && if [ -e {f} ]; then mv -f {f} {f}.bak-$(date +%Y%m%d%H%M%S); fi"
                      " && mv -f {t} {f} && sha256sum {f}").format(
                          d=_sh_quote(remote_dir), f=_sh_quote(remote_final), t=_sh_quote(remote_tmp))
            ssh = subprocess.run(_ssh_base(trial) + [commit],
                                 capture_output=True, text=True, timeout=timeout)
            if ssh.returncode != 0:
                last_err = (ssh.stderr or ssh.stdout or f"ssh exit {ssh.returncode}").strip()[:200]
                continue
            remote_sha = (ssh.stdout or "").strip().split()[0] if (ssh.stdout or "").strip() else ""
            if not remote_sha:
                last_err = "empty checksum from server"
                continue
            if remote_sha.lower() != local_sha.lower():
                last_err = "checksum mismatch"
                return {"status": "mismatch", "message": "checksum mismatch",
                        "local_sha": local_sha, "remote_sha": remote_sha, "host": host}
            return {"status": "success", "local_sha": local_sha,
                    "remote_sha": remote_sha, "host": host}
        except FileNotFoundError:
            return {"status": "error", "message": "ssh/scp client not found"}
        except subprocess.TimeoutExpired:
            last_err = "transfer timed out"
            continue
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
            continue
    transient = any(tag in last_err.lower() for tag in
                    ("timed out", "unreachable", "connection", "reset", "broken pipe",
                     "no route", "permission denied (publickey"))

    return {"status": "transient" if transient else "error",
            "message": f"{last_err or 'transfer failed'} (host {last_host})",
            "local_sha": local_sha}


def retry_delay_seconds(retries: int, cfg: Dict[str, Any]) -> float:
    base = float(cfg.get("retry_base_seconds") or 30.0)
    cap = float(cfg.get("retry_max_seconds") or 3600.0)
    jitter = float(cfg.get("retry_jitter_seconds") or 10.0)
    return min(base * (2 ** max(0, retries)), cap) + random.uniform(0, jitter)


def set_transport(name: str, func: Any) -> None:
    """Inject a fake transport for tests. ``name`` in {"check", "upload"}."""
    _TRANSPORTS[name] = func


def clear_transports() -> None:
    _TRANSPORTS.clear()


def _reclaim_stale_uploads() -> int:
    """Reclaim jobs stuck in 'uploading' after a crash or abrupt stop.

    Move jobs that have been uploading for >120s back to pending so they
    can be retried. Local files are never touched; remote files are left
    in place. This prevents orphaned 'uploading' jobs from persisting
    forever after the worker dies mid-transfer.
    """
    threshold = 120.0
    now = time.time()
    reclaimed = 0
    with _LOCK:
        state = _read_queue()
        for job in state.get("jobs", {}).values():
            if job.get("status") == "uploading":
                updated = float(job.get("updated_at") or 0)
                if updated and (now - updated) >= threshold:
                    job["status"] = "pending"
                    job["updated_at"] = now
                    job["last_error"] = (job.get("last_error") or "") + "; job reclaimed after crash"
                    reclaimed += 1
        if reclaimed:
            _write_queue(state)
    return reclaimed


# ── worker ──────────────────────────────────────────────────────────────────
def _process_due_jobs(cfg: Dict[str, Any]) -> Dict[str, int]:
    # Reclaim any jobs orphaned from a previous crash before we build the due list
    _reclaim_stale_uploads()
    counts = {"completed": 0, "deferred": 0, "failed": 0}
    now = time.time()
    with _LOCK:
        state = _read_queue()
        jobs = state["jobs"]
        due = [j for j in jobs.values()
               if j.get("status") == "pending"
               or (j.get("status") == "retrying" and (j.get("next_retry_at") or 0) <= now)]
    if not due:
        return counts
    if state.get("paused") or not cfg.get("enabled"):
        return counts
    server = check_server(cfg)
    if not server.get("reachable"):
        with _LOCK:
            state = _read_queue()
            state["note"] = f"server unreachable: {server.get('message', '')[:160]}"
            _write_queue(state)
        counts["deferred"] = len(due)
        return counts
    due.sort(key=lambda j: j.get("queued_at") or 0)
    for job in due:
        if _STOP_EVENT.is_set():
            break
        with _LOCK:
            state = _read_queue()
            if state.get("paused") or not load_config().get("enabled", True):
                _write_queue(state)
                break
            current = state["jobs"].get(job["id"])
            if current is None or current.get("status") not in ("pending", "retrying"):
                continue
            if not os.path.isfile(current["source"]) or os.path.islink(current["source"]):
                current.update({"status": "failed", "last_error": "source file missing; remote copy preserved",
                                "updated_at": time.time()})
                _write_queue(state)
                counts["failed"] += 1
                continue
            current["status"] = "uploading"
            current["updated_at"] = time.time()
            _write_queue(state)
        # Stability + transfer happen outside the lock.
        outcome = _upload_job(cfg, dict(current))
        with _LOCK:
            state = _read_queue()
            stored = state["jobs"].get(job["id"])
            if stored is None:
                continue
            if outcome["status"] == "deferred-unstable":
                stored.update({"status": "pending", "updated_at": time.time()})
                _write_queue(state)
                counts["deferred"] += 1
                continue
            if outcome["status"] == "ok":
                stored.update({"status": "completed", "sha256": outcome["sha"],
                               "completed_at": time.time(), "updated_at": time.time(),
                               "last_error": "", "retries": stored.get("retries", 0)})
                state["last_success"] = time.time()
                state["note"] = ""
                _prune(state, cfg)
                _write_queue(state)
                counts["completed"] += 1
                continue
            retries = int(stored.get("retries", 0)) + 1
            stored["retries"] = retries
            stored["last_error"] = outcome["message"][:300]
            stored["updated_at"] = time.time()
            if retries >= int(cfg.get("max_retries") or 20):
                stored.update({"status": "failed", "next_retry_at": None})
                counts["failed"] += 1
            else:
                stored.update({"status": "retrying",
                               "next_retry_at": time.time() + retry_delay_seconds(retries, cfg)})
                counts["deferred"] += 1
            _write_queue(state)
    return counts


def _upload_job(cfg: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    try:
        current_size = os.path.getsize(job["source"])
        current_mtime = os.path.getmtime(job["source"])
    except OSError:
        return {"status": "fail", "message": "source file missing; remote copy preserved"}
    if current_size != job.get("size") or current_mtime != job.get("mtime"):
        # File changed since enqueue: refresh the record, upload next tick.
        with _LOCK:
            state = _read_queue()
            stored = state["jobs"].get(job["id"])
            if stored is not None:
                stored.update({"size": current_size, "mtime": current_mtime,
                               "sha256": None, "status": "pending",
                               "updated_at": time.time()})
                _write_queue(state)
        return {"status": "deferred-unstable", "message": "file changed; requeued"}
    if not is_stable(job["source"], cfg):
        return {"status": "deferred-unstable", "message": "file still being written"}
    result = upload_and_verify(cfg, job)
    if result.get("status") == "success":
        return {"status": "ok", "sha": result.get("remote_sha", "")}
    if result.get("status") == "mismatch":
        return {"status": "fail",
                "message": f"checksum mismatch (local {result.get('local_sha', '')[:12]}… "
                           f"remote {result.get('remote_sha', '')[:12]}…); previous remote kept as .bak"}
    return {"status": "fail", "message": str(result.get("message", "transfer failed"))[:300]}


def _worker_loop() -> None:
    cfg = load_config()
    next_scan = 0.0
    while not _STOP_EVENT.is_set():
        try:
            cfg = load_config()
            now = time.time()
            if now >= next_scan:
                try:
                    scan_and_enqueue(cfg)
                except Exception:
                    pass
                next_scan = now + float(cfg.get("scan_interval_seconds") or 300.0)
            try:
                _process_due_jobs(cfg)
            except Exception:
                pass
        except Exception:
            pass
        _STOP_EVENT.wait(float(cfg.get("tick_seconds") or 5.0))


def ensure_worker() -> bool:
    """Start the background backup worker (idempotent)."""
    global _WORKER_STARTED, _WORKER_THREAD
    # Recover any jobs left in 'uploading' after a previous crash
    _reclaim_stale_uploads()
    with _LOCK:
        if _WORKER_STARTED and _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        thread = threading.Thread(target=_worker_loop, name="jarvis-ubuntu-backup", daemon=True)
        _WORKER_THREAD = thread
        _WORKER_STARTED = True
    thread.start()
    return True


def shutdown_worker(timeout: float = 10.0) -> Dict[str, Any]:
    """Graceful shutdown: stop after the in-flight transfer finishes."""
    global _WORKER_STARTED
    _STOP_EVENT.set()
    thread = _WORKER_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
    with _LOCK:
        _WORKER_STARTED = False
    with _LOCK:
        state = _read_queue()
        pending = sum(1 for j in state["jobs"].values() if j.get("status") in ACTIVE_STATUSES)
    return {"status": "success", "pending_preserved": pending,
            "note": "pending jobs remain queued and resume on next start"}


# ── status / actions (for API + UI) ─────────────────────────────────────────
def categorize_file(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ("pdf", "docx", "doc", "txt", "md", "pptx", "xlsx", "xls", "csv", "rtf", "odt"):
        return "document"
    if ext in ("py", "js", "jsx", "ts", "tsx", "html", "css", "json", "sh", "cpp", "c", "h", "java", "sql", "yaml", "yml"):
        return "code"
    if ext in ("png", "jpg", "jpeg", "gif", "svg", "webp", "mp4", "webm", "mp3", "wav", "m4a", "ogg"):
        return "media"
    if ext in ("zip", "tar", "gz", "7z", "rar", "bz2"):
        return "archive"
    if ext in ("db", "sqlite", "parquet", "bin"):
        return "data"
    return "other"


def get_status(refresh_server: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    with _LOCK:
        state = _read_queue()
        jobs = list(state["jobs"].values())
    counts = {name: 0 for name in ("pending", "uploading", "retrying", "completed", "failed")}
    total_bytes = 0
    verified_bytes = 0
    pending_bytes = 0
    failed_bytes = 0
    active_transfer = None

    for job in jobs:
        status = job.get("status")
        sz = int(job.get("size") or 0)
        total_bytes += sz
        if status in counts:
            counts[status] += 1
        if status == "completed":
            verified_bytes += sz
        elif status in ACTIVE_STATUSES:
            pending_bytes += sz
            if status == "uploading" and active_transfer is None:
                active_transfer = {
                    "id": job.get("id"),
                    "rel": job.get("rel"),
                    "size": sz,
                    "updated_at": job.get("updated_at"),
                }
        elif status == "failed":
            failed_bytes += sz

    server = check_server(cfg, force=refresh_server)

    disk_total = 0
    disk_free = 0
    try:
        du = shutil.disk_usage(BASE_DIR)
        disk_total = du.total
        disk_free = du.free
    except Exception:
        pass

    return {
        "enabled": bool(cfg.get("enabled")),
        "paused": bool(state.get("paused")),
        "worker_running": bool(_WORKER_THREAD is not None and _WORKER_THREAD.is_alive()),
        "host": cfg.get("host"), "fallback_host": cfg.get("fallback_host"),
        "user": cfg.get("user"), "remote_root": cfg.get("remote_root"),
        "roots": cfg.get("roots"),
        "server": server,
        "counts": counts,
        "total_jobs": len(jobs),
        "total_bytes": total_bytes,
        "verified_bytes": verified_bytes,
        "pending_bytes": pending_bytes,
        "failed_bytes": failed_bytes,
        "active_transfer": active_transfer,
        "local_system": {
            "platform": "Windows 11",
            "hostname": os.environ.get("COMPUTERNAME", "JARVIS-LAPTOP"),
            "disk_total": disk_total,
            "disk_free": disk_free,
            "disk_used": max(0, disk_total - disk_free),
        },
        "last_success": state.get("last_success"),
        "last_scan": state.get("last_scan"),
        "note": state.get("note", ""),
    }


def list_jobs(status: str = "", limit: int = 100, search: str = "", category: str = "") -> Dict[str, Any]:
    with _LOCK:
        raw_jobs = list(_read_queue()["jobs"].values())
    
    jobs = []
    for j in raw_jobs:
        job_copy = dict(j)
        cat = categorize_file(job_copy.get("rel") or job_copy.get("source") or "")
        job_copy["category"] = cat
        jobs.append(job_copy)

    jobs.sort(key=lambda j: j.get("updated_at") or 0, reverse=True)

    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    if category:
        jobs = [j for j in jobs if j.get("category") == category]
    if search:
        s = search.lower()
        jobs = [j for j in jobs if s in (j.get("rel") or "").lower() or s in (j.get("source") or "").lower()]

    return {"jobs": jobs[:max(1, min(int(limit or 100), 500))], "total": len(jobs)}


def test_connection() -> Dict[str, Any]:
    """Test remote server connection immediately and return probe metrics."""
    cfg = load_config()
    t0 = time.time()
    server = check_server(cfg, force=True)
    latency_ms = round((time.time() - t0) * 1000, 1)
    return {
        "status": "success" if server.get("reachable") else "unreachable",
        "reachable": bool(server.get("reachable")),
        "latency_ms": latency_ms,
        "host": server.get("host") or cfg.get("host"),
        "user": cfg.get("user"),
        "message": server.get("message", ""),
    }


def set_paused(paused: bool) -> Dict[str, Any]:
    with _LOCK:
        state = _read_queue()
        state["paused"] = bool(paused)
        _write_queue(state)
    return {"status": "success", "paused": bool(paused)}


def retry_job(job_id: str) -> Dict[str, Any]:
    with _LOCK:
        state = _read_queue()
        job = state["jobs"].get(job_id)
        if job is None:
            return {"status": "error", "message": "job not found"}
        if job.get("status") not in ("failed", "retrying"):
            return {"status": "error", "message": f"job is {job.get('status')}; nothing to retry"}
        try:
            job.update({"size": os.path.getsize(job["source"]),
                        "mtime": os.path.getmtime(job["source"]),
                        "sha256": None})
        except OSError:
            pass
        job.update({"status": "pending", "retries": 0, "next_retry_at": None,
                    "last_error": "", "updated_at": time.time()})
        _write_queue(state)
    return {"status": "success", "job_id": job_id}


def retry_all_failed() -> Dict[str, Any]:
    with _LOCK:
        state = _read_queue()
        retried = 0
        for job in state["jobs"].values():
            if job.get("status") == "failed":
                job.update({"status": "pending", "retries": 0,
                            "next_retry_at": None, "last_error": "",
                            "updated_at": time.time()})
                retried += 1
        _write_queue(state)
    return {"status": "success", "retried": retried}


def restore_file(job_id: str, dest_dir: str = "") -> Dict[str, Any]:
    """Copy a backed-up file from Ubuntu back to Windows.

    Safeguard: never overwrites — if the target name exists, a
    ``-restored[-N]`` suffix is added. Returns the local path written.
    """
    cfg = load_config()
    with _LOCK:
        job = _read_queue()["jobs"].get(job_id)
    if job is None:
        return {"status": "error", "message": "job not found"}
    if job.get("status") != "completed":
        return {"status": "error", "message": "only verified (completed) backups can be restored"}
    try:
        _, remote_final, _ = _remote_paths(cfg, job["rel"], job["id"])
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    target_dir = os.path.abspath(dest_dir) if dest_dir else os.path.dirname(job["source"])
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        return {"status": "error", "message": f"cannot create destination: {exc}"}
    base = os.path.basename(job["source"])
    stem, ext = os.path.splitext(base)
    candidate = os.path.join(target_dir, f"{stem}-restored{ext}")
    counter = 1
    while os.path.exists(candidate):
        counter += 1
        candidate = os.path.join(target_dir, f"{stem}-restored-{counter}{ext}")
    last_err = ""
    for host in candidate_hosts(cfg):
        trial = dict(cfg)
        trial["host"] = host
        try:
            # Use optimized SCP base command for restore too
            scp_cmd = _scp_base(trial) + [f"{trial['user']}@{host}:{_sh_quote(remote_final)}", candidate]
            proc = subprocess.run(scp_cmd, capture_output=True, text=True,
                                  timeout=int(cfg.get("transfer_timeout_seconds") or 120))
            if proc.returncode == 0 and os.path.isfile(candidate):
                if job.get("sha256") and sha256_of(candidate) != job["sha256"]:
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass
                    return {"status": "error",
                            "message": "restored file failed checksum verification and was removed"}
                return {"status": "success", "path": candidate, "host": host}
            last_err = (proc.stderr or proc.stdout or f"scp exit {proc.returncode}").strip()[:200]
        except FileNotFoundError:
            return {"status": "error", "message": "scp client not found"}
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
    try:
        if os.path.isfile(candidate):
            os.remove(candidate)
    except OSError:
        pass
    return {"status": "error", "message": last_err or "restore failed"}
