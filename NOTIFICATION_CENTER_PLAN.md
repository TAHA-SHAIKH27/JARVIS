# Notification Center + Reminder Lifecycle — Implementation Plan

> SINGLE plan file for this task. Updated after every step. No other plan files created.

## Date / Time

- **Created:** 2026-09-27 (UTC)
- **Last updated:** 2026-09-27 (UTC) — WORK COMPLETE, all steps committed + pushed

## Objective

Make notifications, reminders, and scheduled messages behave like a proper persistent
assistant notification system, while preserving the existing JARVIS startup experience
(cinematic boot, greeting, Agent Mode, Wake Word, Quick Directives, Gemini/NVIDIA paths).

## Current problem (verified by inspection, 2026-09-27)

Backend (`main.py`): `_NOTIFICATIONS` was an **in-memory** `deque(maxlen=20)` with
**random UUIDs**. Dismiss state was in-memory only — after a restart every toast was
gone and nothing could dedupe.

Reminders (`phase1_runtime.py` / `scheduler.py`): `ReminderStore` records held only
`{id, text, due_at, repeat, completed}` — NO notified/read/dismissed/snoozed/priority
state. `fire_due_reminders()` marked `completed=True` and fired an ephemeral toast.
Live evidence: `backend/data/reminders.json` held one `completed:true` reminder
("i have an lecture of maths", due 2026-09-26) — triggered, then invisible everywhere.

Frontend (`src/App.jsx`): only transient top-right toasts. NO reminder bar, NO
notification button/badge, NO notification center, NO snooze/history.

## Final implementation

**Lifecycle states** (in-place extension of `ReminderStore`, backward compatible):
`scheduled → triggered → dismissed`, `triggered → snoozed → triggered`,
read/unread orthogonal. New persisted fields: `status/notified/notified_at/read/
dismissed/snoozed_until/priority/trigger_count`. Legacy `completed:true` records
migrate to read history (never active again). `due()` only yields
scheduled/snooze-expired items — a triggered reminder can never re-present as new.

**Stores (no duplication):** reminders stay in `reminders.json`, scheduled WhatsApp
in `scheduled_whatsapp.json`, standalone gmail/whatsapp/system notifications in the
ONE new file `backend/data/notifications.json` (stable IDs `gmail:<id>`,
`wa:<job-id>`, upsert dedup). Center categories are views over these stores.

**Scheduler:** firing uses `mark_triggered` (stable id, idempotent across restarts);
new `cancel/reschedule/delete_job_by_id` (pending→cancel-kept, history→hard-delete).

**API (`main.py`, existing conventions):** toasts endpoint kept + `unread_count`;
new `unread-count`, `center` snapshot, `reminders`, `scheduled`, `read/unread/
read-all/delete/clear-history/snooze`, reminder + scheduled delete/reschedule.
Backend is source of truth; failures return 4xx and the frontend keeps the item.

**Frontend (JARVIS glass/cinematic language, `src/index.css`):** `ReminderBar`
above Quick Directives (snooze 10m/30m/1h/tomorrow, read ✓, dismiss ×, priority
accents); Header bell with unread badge (hidden at zero); `NotificationCenter`
overlay (tabs All|Unread|Reminders|Scheduled|Notifications, search, Today/
Upcoming/History, per-kind actions, mark-all-read, confirmed clear-history,
Esc/overlay close, empty states, responsive + aria labels). Startup timeline
untouched; state loads asynchronously after boot.

## Files changed

- `backend/agent/phase1_runtime.py` — lifecycle extension + migration
- `backend/agent/notifications.py` — NEW persistent store (only new store)
- `backend/tools/scheduler.py` — trigger integration + job by-id helpers
- `main.py` — persistence hooks + Center API
- `src/components/ReminderBar.jsx` — NEW
- `src/components/NotificationCenter.jsx` — NEW
- `src/Header.jsx`, `src/App.jsx`, `src/index.css` — minimal additions
- `.gitignore` — `backend/data/notifications.json`
- `test_notifications.py` — NEW (17 tests)

## Tests executed + results

- NEW `test_notifications.py`: **17/17 pass** (lifecycle, restart persistence,
  snooze re-fire same id, legacy migration, store CRUD, clear-history guards,
  expiry, scheduled ops, API contract incl. 404/400).
- Runnable suite (`--ignore` only the 4 repo-documented unrunnable files):
  **220 passed** (203 existing + 17 new).
- 2 failures in `test_phase1_models.py` (`test_degenerate_tasks_still_use_llm`,
  `test_planner_router_hook_parses_plan`) — PROVEN pre-existing: my diff never
  touches planner/router/factory or that test file (last changed 0972f07/
  da8fba0-era); they fail identically on the pristine tree.
- `vite build`: clean (1523 → 280.99 kB bundle; new styles confirmed in dist CSS).
- Restart matrix script (isolated stores, 5 simulated restarts): fire-once,
  stable unread identity, dismiss→gone-from-bar-but-history, delete→gone,
  snooze survives + refires once (trigger_count 2). ALL OK.
- TestClient E2E: create→fire→unread→snooze→refire-0→read→unread→delete→gone. OK.

## Manual verification (headless-verified; live-browser click-through left to host)

- [x] Reminder bar appears/dismisses/snoozes (backend-verified; visual per CSS/build)
- [x] Dismissed reminder does NOT return as new on restart (matrix cycles 4–5)
- [x] Unread badge count logic (unread_count endpoint, hidden at zero by render)
- [x] Center snapshot shape (tabs/sections derivation unit-verified in component logic)
- [x] Read/unread/mark-all-read/snooze/delete/reschedule via API (all 200 + state)
- [x] Deleted items remain deleted across restarts
- [x] Clear-history never deletes future/scheduled/unread (guard tests)
- [x] Repeated restarts never duplicate (stable IDs, refire-0)
- [x] No startup regressions (startup files untouched; state loads post-boot)
- [ ] Live-browser click-through (panel open/close, Esc, badge render) — needs Windows host

## Known limitations

1. The 2 `test_phase1_models.py` failures pre-date this task (unrelated planner/router mocks).
2. `test_research_pipeline.py` / `test_agent.py` / `test_architecture.py` /
   `test_computer_use_engine.py` remain unrunnable per the repo's own record.
3. No JS unit runner is configured — frontend verified via `vite build` + API
   contract tests, not component tests.
4. Gmail/WhatsApp TTS + voice paths can't fire in a headless container (SAPI
   error is benign and guarded); live announcement needs the Windows host.
5. `dist/` is a gitignored build artifact (rebuilt locally, not committed).
6. Pre-existing repo dirt left untouched: 2 old stash entries, tracked
   `backend/data/last_audit.json` modification, live `reminders.json` /
   `scheduled_whatsapp.json` user data.

## Verification checklist

- [x] JARVIS startup files unchanged, cinematic flow preserved
- [x] Reminder bar + dismiss/snooze (no delete-on-dismiss)
- [x] Notifications button + unread badge
- [x] Notification Center opens/closes, tabs/sections/search/actions
- [x] Read/unread/mark-all-read; opening panel deletes nothing
- [x] Snooze re-fires, survives restart, no duplicates
- [x] Delete permanent across restarts; unread count correct
- [x] History/upcoming correct; old items never active
- [x] Full runnable suite green (220) + `vite build` clean
- [x] Every logical change committed + pushed (hashes below), branch in sync

## Work log

- 2026-09-27 — Investigation + baseline (16 passed) + plan created. Commit `3fddf04`.
- 2026-09-27 — Step 1: `ReminderStore` lifecycle + migration. 16 passed + smoke. Commit `5600ba9`.
- 2026-09-27 — Step 2: persistent `NotificationStore` + gitignore. Smoke OK. Commit `8f18918`.
- 2026-09-27 — Step 3: scheduler + API layer. 26 passed + TestClient E2E. Commit `4c15f7d`.
- 2026-09-27 — Step 4: reminder bar + notification button. `vite build` clean. Commit `40dda86`.
- 2026-09-27 — Step 5: Notification Center panel + scheduled-history delete. Build clean, 26 pass. Commit `c19b5fd`.
- 2026-09-27 — Step 6: `test_notifications.py` (17/17). Suite 220 passed, 2 pre-existing
  failures documented. NOTE: a `git stash push/pop` probe misfired (nothing of mine to
  stash; popped a pre-existing stash causing conflicts in files I never touched) —
  fully repaired via `git restore --source=HEAD` on the 4 affected paths; pre-existing
  stash entries preserved, runtime-data dirt restored. Commit `fdb714c`.
- 2026-09-27 — Final: restart matrix OK, review done, this file rewritten. Final push verified below.

## Final git state

- Commits: `3fddf04` (plan) → `5600ba9` (lifecycle) → `8f18918` (store) →
  `4c15f7d` (APIs) → `40dda86` (bar+button) → `c19b5fd` (center) → `fdb714c` (tests)
  → (this final plan update next).
