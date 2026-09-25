# JARVIS Implementation Plan — Final Audit, Correction & Completion

## Audit timestamp
2026-09-25 (final audit pass, local workspace inspection — no blind rewrites).

## Audit objective
Verify each required system against its ACTUAL implementation/integration/call path,
keep what is correct, and correct/complete only the gaps.

## Requirements vs current status (verified by reading code, not filenames)

### Already correct — LEAVE ALONE
- Durable task checkpoints + universal history (`backend/agent/task_persistence.py`,
  SQLite, atomic writes): task/checkpoint/history tables, verified-only checkpoint,
  `action_started` journaling, `latest_action_started`, `search_history`,
  `history_for_task`, `recoverable_tasks`. Integrated in `core.py process()`
  (create/resume, plan persist, observe persist, checkpoint only after verifier
  success, resume after highest verified step, final `mark()`).
- Plan serialization (`serialize_plan`/`deserialize_plan`) wired into resume path.
- Local Ollama fallback (`backend/agent/local_model.py`, stdlib-only): availability
  probe, model select, `generate_plan`; called in `planner._call_gemini_for_plan`
  ONLY after Gemini/NVIDIA paths fail. Gemini primary + Nemotron coding roles kept.
- Memory: explicit remember/forget/correct/show (`memory_api.JarvisMemory`),
  privacy refusal, dedup, conflict/supersede authority rules, expiration,
  project scope; auto-extraction via `learn_from_exchange` (MEDIUM/conversation,
  never overwrites HIGH) called from `core._memory_store_outcome`. Phase 1
  `phase1_memory` legacy path intact.
- Observer/Verifier (`observer.py`/`verifier.py`): ACTION→OBSERVE→VERIFY with
  filesystem/DOM/UIA checks, failure classification, bounded retry/replan,
  human-in-the-loop for login/captcha.
- WhatsApp: contact search inside WhatsApp itself (no `contact.json` — correct),
  phone-number deep-link flow, ADB phone route, scheduler store
  (`scheduled_whatsapp.json`, survives restart), list/cancel, 30s ticker firing
  via `main.py`, success/failure status tracking.
- Uncommitted local work (executor browser-pro actions, screenshot-dir mirroring,
  verifier fatal fast-path, computer/browser/system_ops improvements) is
  legitimate feature work — MUST be preserved, verified, then committed.

### Gaps found (partial/incorrect/missing — fix minimally)
- [x] G1. Experience reaches the LLM only via the `install_planner_context_bridge`
  monkey-patch on the legacy `_call_gemini_for_plan` path (installed from
  `state.initialize_phase1`). The Model-Router path (`_call_router_for_plan`)
  and direct `planner.plan_task` callers that never trigger the bridge get NO
  prior-experience context. FIXED 2026-09-25: `planner.plan_task` now injects
  `experience_context()` directly next to the `phase2_memory_context` block, so
  router + legacy paths both plan with it (bounded 1500 chars, failure-silent,
  guidance-only wording). Verified: planner imports OK; seeded verified
  checkpoint retrieved via `experience_context()`.
- [x] G2. Scheduler has NO `reschedule` operation and `handle_schedule_command`
  parses no reschedule phrasing ("move X to …", "reschedule X to …").
  FIXED 2026-09-25: added `reschedule_scheduled()` (pending-only, future-time
  guard, >1yr refusal; never touches sent/failed/cancelled so history is never
  rewritten and delivery can't duplicate) + NL wiring for
  reschedule/move/postpone/shift/change. Verified: schedule→reschedule→list
  (new time shown)→cancel round-trip passes via both direct calls and
  `handle_schedule_command`. Duplicate-send protection kept (pending→
  sent/failed/cancelled transitions).
- [x] G3. Resume path records `action_started` but never READS
  `latest_action_started` and never re-observes the environment before
  continuing. FIXED 2026-09-25: on resume, `core.process()` now queries
  `latest_action_started()` and emits a `recovery_check` event naming the
  unverified in-flight step, then takes a fresh `observer.observe()` snapshot
  (stored as `resume_observation`, `re_observed` event) before executing.
  Verified steps still resume at `current_step` (never replayed); only the
  unverified step is retried after re-observation. Verified: core imports OK;
  in-flight marker round-trip + observer snapshot pass on an isolated store.
- [x] G4. Document pipeline extracts full text (+OCR) but has no provenance /
  section / retrieval record linking document knowledge to tasks.
  FIXED 2026-09-25 (minimal, stdlib-only, existing pipeline untouched):
  `document_intel.index_document()` (heading/Page/Slide-aware sections,
  overlapping chunks with source/section/char-offset provenance) +
  `retrieve_sections()` (lexical ranking, provenance-preserving hits).
  Verified: 2-section sample indexes to 2 chunks; query returns the correct
  section with source; empty query/index degrade to [].
- [x] G5. `JARVIS_TASK_DB` default (`jarvis_tasks.db` at repo root) and scheduler
  JSON stores are untracked runtime artifacts — FIXED 2026-09-25: `.gitignore`
  now also covers `jarvis_tasks.db*`, `backend/data/session_memory.json`,
  `backend/data/current_session_memory.json`, `backend/data/last_audit.json`,
  `backend/agent/model_registry_store.json` (scheduler/memory entries already
  covered). Verified via `git check-ignore`. NOTE: `current_session_memory.json`
  (modified) and `session_memory.json` (deleted) are PRE-EXISTING tracked
  runtime noise in the worktree — left untouched, never staged into commits
  (all commits use explicit `git add <files>`).
- [ ] G6. Full pytest suite cannot run in THIS environment: Python 3.14 +
  installed numpy crashes the interpreter at import (access violation in
  `numpy/_core/multiarray`). PARTIAL 2026-09-25 — per-file runs in this
  container, all passing (199 total):
  test_scheduler 12, phase1_memory+phase2_memory 57, phase1_runtime 4,
  planner_direct+whatsapp_ops+memory_restart 13, gmail_notify 10,
  phase3_integration 20, phase1_models 83.
  Pre-existing failures NOT caused by this pass (files untouched by my edits):
  test_agent.py collection error (subscripts ActionSpec at module import);
  test_architecture.py 4 + test_computer_use_engine.py 6 (no pytest-asyncio
  plugin installed); test_research_pipeline.py (SystemExit at import).
  Full regression must still run on the Windows JARVIS host.

## Planned corrections (one edit → verify → plan → commit → push each)
1. Planner experience injection (G1).
2. Scheduler reschedule + command wiring (G2).
3. Core resume re-observation + in-flight check (G3).
4. Document provenance helper (G4).
5. Commit preserved local work + full-report rewrite of this file.

## Verification status
- Targeted imports OK: task_persistence, local_model, scheduler (2026-09-25).
- Full suite: NOT yet run (blocked by numpy/Py3.14 crash in this container;
  must run on Windows host). No "all tests pass" claim is made.