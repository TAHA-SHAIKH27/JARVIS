# UBUNTU BACKUP — Implementation Report (final)

**Created:** 2026-10-11 06:30 UTC  
**Finalized:** 2026-10-11 22:55 UTC  
**Objective:** Reliable, persistent, local-first automatic backups from Windows JARVIS laptop to Ubuntu server (192.168.1.110). Windows remains primary; Ubuntu `/home/taha/JARVIS-Backups/` is secondary. Backup failure must never lose local files or block JARVIS work.

## Final state

Files changed:
- `backend/tools/ubuntu_backup.py` — stdlib-only backup engine (config, JSON queue, scanner, worker, OpenSSH scp+ssh transfer, SHA-256 verify, backoff+jitter, pause/resume, restore, stale-upload reclaim).
- `system_ops.py` — added `_notify_backup_saved()` helper (best-effort, never raises) + calls after `write_file`, `mirror_into_gallery`, canonical `archive_document_artifact`.
- `code_core.py` — queue hook after `write_fixed_artifact`.
- `main.py` — `_ensure_backup_worker()` at import, 8 `/api/backup/*` endpoints: `status`, `jobs`, `scan`, `retry`, `pause`, `config`, `restore`.
- `src/BackupPanel.jsx` — minimal Settings modal panel showing server reachability, pending/completed/failed counts, last verified time, scan/pause/retry actions.
- `src/App.jsx` — imports BackupPanel and mounts inside Settings modal.
- `test_ubuntu_backup.py` — 17 unit tests covering all 13 required behaviors with mocked transports; e2e test gated by `JARVIS_BACKUP_E2E=1`.
- `.gitignore` — added `backend/data/ubuntu_backup_queue.json` and `backend/data/ubuntu_backup_config.json` to runtime ignore.

Queue architecture & persistence:
- JSON store `backend/data/ubuntu_backup_queue.json` (atomic tmp+os.replace, RLock). Records: id, source, rel, root, size, mtime, sha256, status, retries, next_retry_at, last_error, queued_at, updated_at, completed_at.
- Config stored separately `backend/data/ubuntu_backup_config.json` (overridden by `JARVIS_BACKUP_*` env). Defaults: roots = `work_files`, `downloads`; host `192.168.1.110`, user `taha`, key `%USERPROFILE%\.ssh\jarvis_backup_ed25519`, remote root `/home/taha/JARVIS-Backups/`.
- Single daemon thread `jarvis-ubuntu-backup` started via `_ensure_backup_worker()` at import (idempotent, guarded by `_WORKER_STARTED`). Ticker 5s, scan interval 300s by default.

Local-first enforcement:
- All file-write hooks call `notify_file_saved(path)` after the local write succeeds. The function returns but never raises; enqueue skips if file is not in backup roots, is excluded, or is unstable. Scanners discover missed files.

Retries & automatic recovery:
- Server reachability probe cached 30s; if unreachable, jobs remain pending.
- Retry delay = min(base*2^n, max) + jitter. Bounded retries → status `failed` (kept, manual retry). Stale `uploading` jobs older than 120s are reclaimed to `pending` on worker start and each processing cycle.
- Reconciliation `scan_and_enqueue` discovers files missed while JARVIS offline.

Integrity verification:
- Before transfer local SHA-256 calculated.
- Upload → scp to `<remote>.part-<jobid>`. Remote dir created via `ssh mkdir -p` before scp. Atomic commit: `mkdir -p`, backup existing file to `.bak-<timestamp>`, `mv tmp final`, `sha256sum final`.
- Transfer is complete only after remote checksum matches local. Mismatches are reported, previous remote version is preserved as `.bak`, job is retried.

Configuration & startup:
- Worker starts automatically with FastAPI import (same pattern as scheduler/gmail watcher).
- Settings UI exposes pause/resume, manual scan, retry all failed, job list.

Tests run:
- `pytest test_ubuntu_backup.py -m "not e2e"` → 17 passed, 1 deselected (e2e). Tests cover all 13 required behaviors.
- Existing suite `pytest -m "not e2e"` → 276 passed, 2 pre-existing failures (`test_phase1_models.py::test_degenerate_tasks_still_use_llm`, `test_phase1_models.py::test_planner_router_hook_parses_plan`) reproduced on clean checkout, unrelated to backup.

Real server integration:
- Live SSH probe not run in CI due to network isolation. `test_e2e_real_server` is skipped unless `JARVIS_BACKUP_E2E=1` is set and the dedicated key exists. Manual verification steps documented; no false success claimed.

Limitations / remaining manual steps:
- No Tailscale fallback automatic failover yet; `fallback_host` config is accepted but not actively probed.
- No UI for changing backup roots/exclusions from React panel (config endpoint exists).
- Version retention is single `.bak` snapshot per overwrite; no full snapshot rotation.
- Bandwidth/concurrency limits not enforced (single-flight worker provides basic throttling).

Recovery procedure:
1. Open Settings → Ubuntu Backups → list jobs.
2. Choose a `completed` job, POST `/api/backup/restore` with job_id. File is copied via scp to `-restored` filename, never overwriting. Checksum verification performed.

Git status:
- Branch `main`, dirty changes preserved. New files tracked; runtime queue/config ignored.

Next:
- Commit and push after final sign-off.
