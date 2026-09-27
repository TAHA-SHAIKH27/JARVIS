# Notification Center + Reminder Lifecycle — Implementation Plan

> SINGLE plan file for this task. Updated after every step. No other plan files created.

## Date / Time

- **Created:** 2026-09-27 (UTC)
- **Last updated:** 2026-09-27 (UTC) — investigation + baseline done, plan created

## Objective

Make notifications, reminders, and scheduled messages behave like a proper persistent
assistant notification system, while preserving the existing JARVIS startup experience
(cinematic boot, greeting, Agent Mode, Wake Word, Quick Directives, Gemini/NVIDIA paths).

## Current problem (verified by inspection, 2026-09-27)

Backend (`main.py:466-476`):

- `_NOTIFICATIONS` is an **in-memory** `deque(maxlen=20)` with **random UUIDs**.
  Dismiss state is in-memory only. After a backend restart every toast is gone and
  nothing can dedupe — a re-fire would mint a brand-new ID.
- `/api/notifications` returns only undismissed in-memory items; no persistence,
  no read/unread, no history, no stable identity.

Reminders (`backend/agent/phase1_runtime.py:240-296`, `backend/tools/scheduler.py:262-277`):

- `ReminderStore` records hold only `{id, text, due_at, repeat, completed, ...}`.
  There is NO notified/read/dismissed/snoozed/priority state.
- `fire_due_reminders()` marks `completed=True` and fires an ephemeral toast.
  After restart a completed reminder is invisible everywhere (no history), and any
  future UI that naively lists `due()` items as "active" would re-present an
  already-triggered reminder as brand-new (no `TRIGGERED → UNREAD → READ` distinction).
- Live evidence: `backend/data/reminders.json` holds one `completed:true` reminder
  ("i have an lecture of maths", due 2026-09-26) — triggered, then vanished from
  every UI surface. No history, no way to read/delete it from the frontend.

Frontend (`src/App.jsx:346-370,1014-1030`):

- Only transient top-right toasts polled every 8s from `/api/notifications`.
- NO reminder bar, NO notification button/badge, NO notification center,
  NO snooze, NO read/unread, NO history views.

Startup (`src/components/StartupController.jsx`, `backend/startup_engine.py`):

- Cinematic timeline must not be disturbed; notification state must load
  asynchronously after boot, never blocking `SYSTEM_READY`.

Baseline (2026-09-27): `test_scheduler.py` + `backend/agent/test_phase1_runtime.py` = **16 passed**.

## Implementation plan

1. **Backend — ReminderStore lifecycle** (`backend/agent/phase1_runtime.py`):
   Extend records in place (backward compatible, optional keys with defaults):
   `status` (scheduled|triggered|snoozed|dismissed|done), `notified`, `notified_at`,
   `read`, `dismissed`, `snoozed_until`, `priority` (normal|important|urgent),
   `trigger_count`. Keep `completed` semantics. Migrate old records on load.
   New methods: `get`, `mark_triggered`, `mark_read/mark_unread`, `dismiss`,
   `snooze`, `set_priority`, `active_for_bar`. `due()` returns only
   scheduled/snooze-expired items (never already-triggered).
2. **Backend — persistent NotificationStore** (new `backend/agent/notifications.py`,
   file `backend/data/notifications.json`, gitignored): stable IDs
   (`reminder:<id>`, `gmail:<id>`, `wa:<job_id>`), upsert (no duplicates),
   read/unread, dismiss, delete, mark-all-read, clear-read-history (never touches
   future/scheduled/unread), expiry of old read items (30d, documented).
3. **Backend — scheduler + API** (`backend/tools/scheduler.py`, `main.py`):
   `fire_due_reminders` uses `mark_triggered` + notification upsert (idempotent
   across restarts). `_push_notification` persists as well as queueing.
   Endpoints (existing conventions): `GET /api/notifications` (filters),
   `GET /api/notifications/unread-count`, `GET /api/reminders`, `GET /api/scheduled`,
   `POST /api/notifications/read|unread|read-all|dismiss|delete|clear-history|snooze`,
   reminder/scheduled delete routes. Backend is source of truth.
4. **Frontend — bar + button** (`src/components/ReminderBar.jsx`, `src/Header.jsx`,
   `src/App.jsx`, `index.css`): reminder bar above Quick Directives (snooze ✓ ×),
   Notifications button with unread badge near Agent/Wake-Word controls.
5. **Frontend — NotificationCenter** (`src/components/NotificationCenter.jsx`):
   overlay panel, tabs All|Unread|Reminders|Scheduled, sections Today/Upcoming/
   History, search, item actions, mark-all-read, clear-history (confirm), Esc close.
6. **Tests** (new `test_notifications.py`): full lifecycle incl. restart persistence,
   duplicate prevention, snooze, unread count, cleanup guards, API failure handling.
   Full suite must stay green.
7. **Final review**: diff review, frontend `vite build`, manual lifecycle checklist,
   rewrite this file with results, final commit+push with hashes.

## Files likely to change

- `backend/agent/phase1_runtime.py` (extend, not rewrite)
- `backend/agent/notifications.py` (new, one JSON store — the only new store)
- `backend/data/notifications.json` (runtime data, gitignore)
- `backend/tools/scheduler.py` (lifecycle-aware firing)
- `main.py` (persist + new endpoints, startup untouched)
- `src/components/ReminderBar.jsx` (new), `src/components/NotificationCenter.jsx` (new)
- `src/Header.jsx`, `src/App.jsx`, `index.css` (minimal additions)
- `.gitignore` (notifications.json)
- `test_notifications.py` (new)

## Verification checklist

- [ ] JARVIS starts normally, cinematic startup unchanged
- [ ] Reminder bar appears/dismisses/snoozes correctly
- [ ] Dismissed reminder does NOT return as new on restart
- [ ] Notifications button + unread badge work
- [ ] Center opens/closes, tabs/sections/search work
- [ ] Read/unread/mark-all-read work, opening panel deletes nothing
- [ ] Snooze re-fires at snoozed time, survives restart, no duplicates
- [ ] Delete permanently removes; survives restart; unread count correct
- [ ] Clear-history never deletes future/scheduled/unread
- [ ] Repeated restarts never duplicate notifications
- [ ] Full test suite passes, `vite build` clean
- [ ] Every logical change committed + pushed, hashes recorded below

## Work log

- 2026-09-27 — Investigation + baseline (16 passed) + this plan created.
  Root cause confirmed (in-memory notifications, no reminder lifecycle state).
  No code changed yet.
- 2026-09-27 — Step 1 DONE: `ReminderStore` lifecycle (`phase1_runtime.py` only).  Added `status/notified/notified_at/read/dismissed/snoozed_until/priority/
  trigger_count` with `_normalize_reminder` migration; new `get/history/
  active_for_bar/unread_count/mark_triggered/mark_read/mark_unread/dismiss/
  snooze/set_priority`; `due()` only yields scheduled/snooze-expired items.
  Legacy `completed:true` (already announced) migrates to read history, never bar.
  Verification: import OK; `test_scheduler + test_phase1_runtime` 16 passed;
  smoke (tmp store): migrate→trigger→dismiss→reopen→snooze→delete all OK.
  Commit `fix: persist reminder notification state` pushed, in sync.
- 2026-09-27 — Step 2 DONE: persistent `NotificationStore`
  (`backend/agent/notifications.py`, new; `.gitignore` covers
  `backend/data/notifications.json`). Holds ONLY standalone kinds
  (gmail/whatsapp/system); reminders + scheduled stay as views over their own
  stores (no duplication). Stable IDs, upsert dedup, read/unread/dismiss/delete,
  mark-all-read, clear-read-history (unread never touched), purge_expired (read
  + older than 30d only; unread never auto-removed). Verification: smoke
  (upsert dedup, read/unread counts, dismiss visibility, clear guards) OK.
  Commit `feat: persistent notification store` pushed, in sync.
- 2026-09-27 — Step 3 DONE: scheduler + API (`backend/tools/scheduler.py`,
  `main.py`). `fire_due_reminders` uses `mark_triggered` (stable id, no dup);
  new `cancel/reschedule_job_by_id`; gmail/whatsapp results persist with stable
  ids (`gmail:<id>`, `wa:<job-id>`); reminders stay views (no duplication).
  Endpoints: toasts (compat + unread_count), unread-count, center snapshot,
  reminders, scheduled, read/unread/read-all/delete/clear-history/snooze,
  reminder + scheduled delete/reschedule. Verification: import OK; 26 passed
  (scheduler/runtime/gmail); TestClient E2E (create→fire→unread→snooze→
  refire-0→read→unread→delete→gone) OK. Commit `feat: notification APIs`
  pushed, in sync.
- 2026-09-27 — Step 4 DONE: frontend bar + button (`ReminderBar.jsx` new,
  `Header.jsx` bell + badge, `App.jsx` state/poll/actions/bar-above-directives,
  `src/index.css` glass styles). Backend-confirmed actions (failure keeps item
  + chat feedback). Verification: `vite build` clean (1523 modules).
  Commit `feat: reminder bar plus notification button` pushed, in sync.
- 2026-09-27 — Step 5 DONE: Notification Center (`NotificationCenter.jsx` new,
  `App.jsx` center actions + overlay render; `scheduler.delete_job_by_id` +
  routed scheduled delete: pending→cancel-kept, history→hard-delete).
  Panel: tabs All|Unread|Reminders|Scheduled|Notifications, search, Today/
  Upcoming/History sections, per-kind actions, mark-all-read, clear-history
  (confirm), Esc/overlay close, empty states. Verification: `vite build` clean,
  bundled CSS contains new styles; 26 backend tests pass.
  Commit `feat: add notification center` pushed, in sync.
