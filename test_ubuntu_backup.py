#!/usr/bin/env python
"""test_ubuntu_backup.py — unit + integration tests for Ubuntu backups.

All SSH/network operations are mocked via ``ubuntu_backup.set_transport``
except ``test_e2e_real_server``, which is marked ``e2e`` and only runs with
``JARVIS_BACKUP_E2E=1`` (honest reporting: never claimed passed unless run).
"""
import hashlib
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.tools import ubuntu_backup as ub

_REAL_IS_STABLE = ub.is_stable
_REAL_LOAD_CONFIG = ub.load_config


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture()
def isolate(tmp_path, monkeypatch):
    """Redirect queue/config to tmp; reset module-global caches/transports."""
    monkeypatch.setattr(ub, "QUEUE_PATH", str(tmp_path / "queue.json"))
    monkeypatch.setattr(ub, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(ub, "_SERVER_CACHE",
                        {"ok": False, "at": 0.0, "msg": "never checked", "host": ""})
    ub.clear_transports()
    monkeypatch.setattr(ub, "is_stable", lambda path, cfg: True)
    ub._STOP_EVENT.clear()
    ub._WORKER_STARTED = False
    ub._WORKER_THREAD = None
    yield tmp_path
    ub.clear_transports()
    try:
        ub._STOP_EVENT.set()
    except Exception:
        pass


@pytest.fixture()
def cfg(isolate):
    work = isolate / "work_files"
    dl = isolate / "downloads"
    work.mkdir()
    dl.mkdir()
    return {
        **ub.DEFAULT_CONFIG,
        "enabled": True,
        "host": "fake-host",
        "fallback_host": "",
        "user": "fake-user",
        "key_path": str(isolate / "fake_key"),
        "remote_root": "/home/fake/JARVIS-Backups/",
        "roots": [str(work), str(dl)],
        "stable_seconds": 0.0,
        "scan_interval_seconds": 3600.0,
        "tick_seconds": 0.05,
        "ssh_timeout_seconds": 2,
        "transfer_timeout_seconds": 30,
        "retry_base_seconds": 0.05,
        "retry_max_seconds": 0.2,
        "retry_jitter_seconds": 0.0,
        "max_retries": 3,
        "max_history": 50,
        "max_failed": 50,
        "server_cache_ttl_seconds": 300.0,
        "min_free_bytes": 0,
    }


class FakeRemote:
    """In-memory stand-in for the Ubuntu server."""

    def __init__(self):
        self.files = {}   # remote_final_path -> bytes
        self.calls = []   # audit trail (used to prove no remote deletes)
        self.reachable = True
        self.fail_uploads = 0  # next N uploads fail transiently

    def check(self, check_cfg):
        self.calls.append(("check", check_cfg.get("host")))
        if self.reachable:
            return {"reachable": True, "host": "fake-host", "message": "fake ssh ok"}
        return {"reachable": False, "host": "", "message": "fake: no route to host"}

    def upload(self, up_cfg, job):
        self.calls.append(("upload", job["source"], job["rel"]))
        if not self.reachable:
            return {"status": "transient", "message": "fake: no route to host"}
        if self.fail_uploads > 0:
            self.fail_uploads -= 1
            return {"status": "transient", "message": "fake: connection reset by peer"}
        try:
            with open(job["source"], "rb") as handle:
                data = handle.read()
        except OSError as exc:
            return {"status": "error", "message": f"source unreadable: {exc}"}
        # Emulate temp-name + atomic commit: interrupted transfers must never
        # leave a completed-looking file (modeled by only writing on success).
        tmp = f"{job['rel']}.part-{job['id']}"
        self.calls.append(("write-tmp", tmp))
        final = ("remote:" + job["rel"]).replace("\\", "/")
        self.files[final] = data
        sha = hashlib.sha256(data).hexdigest()
        return {"status": "success", "local_sha": sha, "remote_sha": sha, "host": "fake-host"}


@pytest.fixture()
def remote():
    return FakeRemote()


def _install(isolate, cfg, remote, monkeypatch):
    ub.set_transport("check", remote.check)
    ub.set_transport("upload", remote.upload)
    monkeypatch.setattr(ub, "load_config", lambda: cfg)
    return cfg


def _write(root, name, content="hello jarvis"):
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    # Make it look settled for scans that check mtime age.
    old = time.time() - 60
    os.utime(path, (old, old))
    return path


# ── Phase 7 tests ───────────────────────────────────────────────────────────
def test_01_local_file_persists_before_remote_backup(isolate, cfg, remote, monkeypatch):
    """Local save succeeds and survives even when the backup transport fails."""
    _install(isolate, cfg, remote, monkeypatch)
    remote.fail_uploads = 99  # backup can never succeed here
    path = _write(cfg["roots"][0], "report.docx", "local-first-content")
    res = ub.notify_file_saved(path)
    assert res["status"] == "queued"
    ub._process_due_jobs(cfg)
    with open(path, "r", encoding="utf-8") as handle:
        assert handle.read() == "local-first-content"  # local file untouched
    status = ub.get_status()
    assert status["counts"]["completed"] == 0
    assert os.path.isfile(path)


def test_02_server_unavailable_keeps_jobs_pending(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    remote.reachable = False
    path = _write(cfg["roots"][0], "notes.txt", "offline work")
    assert ub.notify_file_saved(path)["status"] == "queued"
    counts = ub._process_due_jobs(cfg)
    assert counts["completed"] == 0
    status = ub.get_status()
    assert status["server"]["reachable"] is False
    assert status["counts"]["pending"] + status["counts"]["retrying"] == 1
    assert os.path.isfile(path)


def test_03_queue_persists_across_restart(isolate, cfg, remote, monkeypatch):
    """Jobs are durable on disk: a fresh read (simulated restart) finds them."""
    _install(isolate, cfg, remote, monkeypatch)
    path = _write(cfg["roots"][0], "durable.txt", "survive restart")
    job_id = ub.notify_file_saved(path)["job_id"]
    with open(ub.QUEUE_PATH, "r", encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert job_id in persisted["jobs"]
    assert persisted["jobs"][job_id]["source"] == os.path.abspath(path)
    assert persisted["jobs"][job_id]["status"] == "pending"


def test_04_retry_after_connectivity_returns(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    remote.reachable = False
    path = _write(cfg["roots"][0], "retry-me.txt", "will retry")
    ub.notify_file_saved(path)
    ub._process_due_jobs(cfg)  # deferred while offline
    remote.reachable = True
    with ub._LOCK:
        ub._SERVER_CACHE.update({"ok": False, "at": 0.0})  # force fresh probe
    # Force the retrying job due immediately.
    with ub._LOCK:
        state = ub._read_queue()
        for job in state["jobs"].values():
            job["next_retry_at"] = 0.0
        ub._write_queue(state)
    counts = ub._process_due_jobs(cfg)
    assert counts["completed"] == 1
    assert ub.get_status()["counts"]["completed"] == 1


def test_05_sha256_verification_gates_completion(isolate, cfg, monkeypatch):
    """A checksum mismatch must never mark a job complete."""
    ub.set_transport("check", lambda c: {"reachable": True, "host": "h", "message": "ok"})

    def bad_upload(up_cfg, job):
        with open(job["source"], "rb") as handle:
            local_sha = hashlib.sha256(handle.read()).hexdigest()
        return {"status": "mismatch", "message": "checksum mismatch",
                "local_sha": local_sha, "remote_sha": "0" * 64, "host": "h"}

    ub.set_transport("upload", bad_upload)
    monkeypatch.setattr(ub, "load_config", lambda: cfg)
    path = _write(cfg["roots"][0], "verify.txt", "integrity matters")
    ub.notify_file_saved(path)
    ub._process_due_jobs(cfg)
    status = ub.get_status()
    assert status["counts"]["completed"] == 0
    jobs = ub.list_jobs()["jobs"]
    assert jobs and jobs[0]["status"] in ("retrying", "failed")
    assert "mismatch" in (jobs[0]["last_error"] or "").lower()


def test_06_interrupted_transfer_never_completes(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    remote.fail_uploads = 1  # first attempt dies mid-transfer
    path = _write(cfg["roots"][0], "partial.bin", "x" * 1000)
    ub.notify_file_saved(path)
    ub._process_due_jobs(cfg)
    assert ub.get_status()["counts"]["completed"] == 0
    assert remote.files == {}  # no completed-looking remote file
    # Temp-name discipline is enforced by the real transport: unit-check it.
    remote_dir, final, tmp = ub._remote_paths(cfg, "docs/a.txt", "job123")
    assert tmp == final + ".part-job123"
    assert tmp.startswith(cfg["remote_root"])


def test_07_duplicate_job_prevention(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    path = _write(cfg["roots"][0], "dup.txt", "once")
    first = ub.notify_file_saved(path)
    second = ub.notify_file_saved(path)
    assert first["status"] == "queued"
    assert second["status"] == "duplicate"
    scan1 = ub.scan_and_enqueue(cfg)
    assert ub.list_jobs()["total"] == 1
    assert scan1["duplicate"] >= 1


def test_08_modification_and_reconciliation_scan(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    path = _write(cfg["roots"][0], "evolving.txt", "v1")
    ub.notify_file_saved(path)
    ub._process_due_jobs(cfg)  # v1 completes
    assert ub.get_status()["counts"]["completed"] == 1
    time.sleep(0.05)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("v2-longer")
    old = time.time() - 60
    os.utime(path, (old, old))
    res = ub.scan_and_enqueue(cfg)  # reconciliation discovers the change
    assert res["status"] == "success"
    ub._process_due_jobs(cfg)
    assert ub.get_status()["counts"]["completed"] == 2
    # File created while "offline" (no notify call) is found by the scan.
    missed = _write(cfg["roots"][1], "missed-while-offline.txt", "found me")
    assert ub.scan_and_enqueue(cfg)["queued"] >= 1
    assert ub._active_for_source(ub._read_queue()["jobs"], os.path.abspath(missed)) is not None


def test_09_spaces_and_unicode_filenames(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    names = ["my report 2026.docx", " Seyahat planı — İstanbul.pptx", "notes (final) v2.txt"]
    for name in names:
        path = _write(cfg["roots"][0], name, "unicode ok")
        assert ub.notify_file_saved(path)["status"] == "queued"
    counts = ub._process_due_jobs(cfg)
    assert counts["completed"] == 3
    assert ub.get_status()["counts"]["completed"] == 3


def test_10_exclusions_and_sensitive_files(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    excluded = ["scratch.tmp", ".env", "token_gmail.json", "config.json",
                "id_ed25519", "client_secret.json", "notes_secret_backup.txt",
                "cache.pyc", "Thumbs.db"]
    for name in excluded:
        path = _write(cfg["roots"][0], name, "must not leave laptop")
        res = ub.notify_file_saved(path)
        assert res["status"] == "skipped", name
    # Excluded dirs + symlinks + outside roots.
    cache_dir = os.path.join(cfg["roots"][0], "__pycache__")
    os.makedirs(cache_dir, exist_ok=True)
    assert ub.notify_file_saved(_write(cache_dir, "mod.py", "x"))["status"] == "skipped"
    outside = _write(str(isolate), "outside.txt", "not in roots")
    assert ub.notify_file_saved(outside)["status"] == "skipped"
    assert ub.list_jobs()["total"] == 0
    assert remote.files == {}


def test_11_no_remote_delete_on_local_delete(isolate, cfg, remote, monkeypatch):
    """Local deletes never propagate: job fails safely, remote stays, no rm."""
    _install(isolate, cfg, remote, monkeypatch)
    path = _write(cfg["roots"][0], "doomed.txt", "bye")
    ub.notify_file_saved(path)
    os.remove(path)  # user deletes the local file
    ub._process_due_jobs(cfg)
    ops = [call[0] for call in remote.calls]
    assert "upload" not in ops  # failed before any transfer attempt
    assert not any(call[0] in ("delete", "rm", "remove") for call in remote.calls)
    jobs = ub.list_jobs()["jobs"]
    assert jobs and jobs[0]["status"] == "failed"
    assert "preserved" in (jobs[0]["last_error"] or "").lower()


def test_12_worker_shutdown_and_restart(isolate, cfg, remote, monkeypatch):
    _install(isolate, cfg, remote, monkeypatch)
    remote.reachable = False  # nothing can complete; jobs must survive
    path = _write(cfg["roots"][0], "survive.txt", "pending work")
    ub.notify_file_saved(path)
    assert ub.ensure_worker() is True
    time.sleep(0.4)  # let the worker tick at least once
    res = ub.shutdown_worker(timeout=5.0)
    assert res["status"] == "success"
    assert res["pending_preserved"] >= 1
    with open(ub.QUEUE_PATH, "r", encoding="utf-8") as handle:
        assert len(json.load(handle)["jobs"]) >= 1
    # Restart resumes and completes once connectivity returns.
    remote.reachable = True
    with ub._LOCK:
        ub._SERVER_CACHE.update({"ok": False, "at": 0.0})
    assert ub.ensure_worker() is True
    deadline = time.time() + 10
    while time.time() < deadline and ub.get_status()["counts"]["completed"] < 1:
        time.sleep(0.2)
    ub.shutdown_worker(timeout=5.0)
    assert ub.get_status()["counts"]["completed"] == 1


def test_13_unstable_file_deferred(isolate, cfg, remote, monkeypatch):
    """A file still being written is not uploaded (real stability gate)."""
    _install(isolate, cfg, remote, monkeypatch)
    monkeypatch.setattr(ub, "is_stable", _REAL_IS_STABLE)
    fresh = _write(cfg["roots"][0], "fresh.txt", "just written")
    now = time.time()
    os.utime(fresh, (now, now))  # brand-new mtime -> unstable with big stable_seconds
    cfg["stable_seconds"] = 3600.0
    ub.notify_file_saved(fresh)
    counts = ub._process_due_jobs(cfg)
    assert counts["completed"] == 0
    assert remote.files == {}


def test_config_roundtrip_and_env_override(isolate, cfg, monkeypatch):
    monkeypatch.setattr(ub, "load_config", _REAL_LOAD_CONFIG)
    saved = ub.save_config({"host": "10.0.0.5", "enabled": False})
    assert saved["host"] == "10.0.0.5"
    assert saved["enabled"] is False
    assert ub.load_config()["host"] == "10.0.0.5"
    monkeypatch.setenv("JARVIS_BACKUP_HOST", "192.168.1.200")
    assert ub.load_config()["host"] == "192.168.1.200"
    monkeypatch.delenv("JARVIS_BACKUP_HOST")


def test_remote_path_confinement(isolate, cfg):
    # Traversal segments are stripped and everything stays under remote_root.
    _, final, _ = ub._remote_paths(cfg, "../../etc/passwd", "x")
    assert final == cfg["remote_root"].rstrip("/") + "/etc/passwd"
    _, final2, _ = ub._remote_paths(cfg, "a/../../b/c.txt", "x")
    assert final2.startswith(cfg["remote_root"])
    assert ".." not in final2
    with pytest.raises(ValueError):
        ub._remote_paths(cfg, "../..", "x")


# ── real OpenSSH transport, subprocess mocked ───────────────────────────────
def test_14_real_transport_uses_temp_names_and_verifies(isolate, cfg, monkeypatch):
    """Exercise the real ``_openssh_upload`` with a recorded subprocess.

    Proves: list-form argv (no shell interpolation), BatchMode, host-key
    verification NOT disabled, temp remote name, .bak preservation of the
    previous version, and SHA-256 gating.
    """
    monkeypatch.setattr(ub, "load_config", _REAL_LOAD_CONFIG)
    path = _write(cfg["roots"][0], "docs plan.txt", "new-version-bytes")
    job = {"id": "jobabc123", "source": os.path.abspath(path),
           "rel": "docs plan.txt", "size": os.path.getsize(path),
           "mtime": os.path.getmtime(path)}
    _, final, tmp = ub._remote_paths(cfg, job["rel"], job["id"])
    stored = {final: b"old-version-bytes"}  # a previously verified backup
    seen = []

    def _unquote(text):
        text = text.strip()
        if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
            return text[1:-1].replace("'\\''", "'")
        return text

    class _Proc:
        def __init__(self, rc=0, out="", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def fake_run(argv, **kwargs):
        assert kwargs.get("shell", False) is not True
        assert isinstance(argv, list)
        seen.append(list(argv))
        if argv[0] == "scp":
            dest = argv[-1]
            remote = _unquote(dest.split(":", 1)[1])
            with open(argv[-2], "rb") as handle:
                stored[remote] = handle.read()
            return _Proc(0, "", "")
        if argv[0] == "ssh":
            # New: handle mkdir -p from upload_and_verify
            if len(argv) >= 6 and argv[-3] == "mkdir":
                # mkdir -p remote_dir
                return _Proc(0, "", "")
            import re as _re
            quoted = _re.findall(r"'(?:[^']|'\\''*)*'", argv[-1])
            parts = [_unquote(q) for q in quoted]
            # Order in the commit command: dir, final, final, final(.bak),
            # tmp, final, final.
            remote_dir, remote_final = parts[0], parts[1]
            remote_tmp = parts[4]
            assert remote_tmp.endswith(f".part-{job['id']}")
            assert remote_tmp.startswith(cfg["remote_root"])
            assert remote_final == final
            if remote_final in stored:
                stored[remote_final + ".bak-20200101"] = stored[remote_final]
            stored[remote_final] = stored.pop(remote_tmp)
            digest = hashlib.sha256(stored[remote_final]).hexdigest()
            return _Proc(0, f"{digest}  {remote_final}\n", "")
        raise AssertionError(f"unexpected command: {argv[0]}")

    monkeypatch.setattr(ub.subprocess, "run", fake_run)
    result = ub.upload_and_verify(cfg, job)
    assert result["status"] == "success"
    assert result["local_sha"] == result["remote_sha"]
    assert stored[final] == b"new-version-bytes"
    assert stored[final + ".bak-20200101"] == b"old-version-bytes"
    flat = " ".join(" ".join(cmd) for cmd in seen)
    assert "BatchMode=yes" in flat
    assert "StrictHostKeyChecking=no" not in flat
    assert "-i" in seen[0] and cfg["key_path"] in seen[0]


def test_15_real_transport_scp_failure_is_transient(isolate, cfg, monkeypatch):
    monkeypatch.setattr(ub, "load_config", _REAL_LOAD_CONFIG)
    path = _write(cfg["roots"][0], "netfail.txt", "data")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Connection reset by peer"

    monkeypatch.setattr(ub.subprocess, "run", lambda *a, **k: _Proc())
    job = {"id": "j1", "source": os.path.abspath(path), "rel": "netfail.txt",
           "size": 4, "mtime": os.path.getmtime(path)}
    result = ub.upload_and_verify(cfg, job)
    assert result["status"] == "transient"


# ── real-server e2e (opt-in, honest reporting) ───────────────────────────────
@pytest.mark.e2e
def test_e2e_real_server(tmp_path):
    """Live transfer against the configured Ubuntu server.

    Run with: JARVIS_BACKUP_E2E=1 python -m pytest test_ubuntu_backup.py -m e2e
    Never reported as passed unless actually executed against the server.
    """
    if os.environ.get("JARVIS_BACKUP_E2E") != "1":
        pytest.skip("set JARVIS_BACKUP_E2E=1 to run the live server test")
    key = os.path.expandvars(os.path.expanduser(
        r"%USERPROFILE%\.ssh\jarvis_backup_ed25519"))
    if not os.path.isfile(key):
        pytest.skip("dedicated SSH key not present")
    live_cfg = {**ub.DEFAULT_CONFIG, "host": os.environ.get("JARVIS_BACKUP_HOST", "192.168.1.110"),
                "user": "taha", "key_path": key,
                "remote_root": "/home/taha/JARVIS-Backups/jarvis-e2e/",
                "ssh_timeout_seconds": 15, "transfer_timeout_seconds": 120}
    probe = ub.check_server(live_cfg, force=True)
    assert probe["reachable"], f"server unreachable: {probe['message']}"
    target = tmp_path / "jarvis e2e ünicode test.txt"
    target.write_text("jarvis backup e2e payload", encoding="utf-8")
    job = {"id": "e2e-test", "source": str(target), "rel": target.name,
           "size": target.stat().st_size, "mtime": target.stat().st_mtime}
    result = ub.upload_and_verify(live_cfg, job)
    assert result["status"] == "success", f"live upload failed: {result}"
    assert result["local_sha"] == result["remote_sha"]
