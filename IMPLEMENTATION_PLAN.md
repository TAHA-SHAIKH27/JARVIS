# J.A.R.V.I.S. — PHASE 1 + PHASE 2 + PHASE 3 IMPLEMENTATION PLAN

## Multimodal Intelligence + Full System Integration (Phase 3 in progress)

> Single plan file for all phases. Updated after every step. No other plan files will be created.

---

## PHASE 3 — Multimodal Intelligence + Full System Integration

### P3.1 Date / Time

- **Phase 3 start:** 2026-09-25 (UTC)
- **Last updated:** 2026-09-25 (UTC) — Phase 3 COMPLETE, stopping

### P3.2 Objective

One continuous loop — USER → UNDERSTAND → MEMORY → PLAN → MODEL ROUTER →
VALIDATED FREE MODEL → ACT → OBSERVE (UIA/DOM/screenshot/vision/OCR) →
VERIFY → RECOVER → MEMORY UPDATE — with no second agent, no new paid deps,
no ADB/phone/watchdog additions, and no unvalidated models enabled.

### P3.3 Audit state (2026-09-25, inspected before any change)

- Phase 1 INTACT: router-first goal/plan/replan (`planner.py:1313,1517,1650`)
  with legacy fallback; registry evidence in `model_registry_store.json`.
  Validated ENABLED FREE: laguna-xs-2.1 (primary), llama-3.2-11b-vision
  (vision/tools), omni-reasoning (heavy), riva-translate, 2× safety,
  embed-vl-1b-v2. Glimmer/GLM-Flash/Nemotron-Lightning NOT routable
  (UNAVAILABLE/DISCOVERED/disabled-slow — must stay off).
- Phase 2 INTACT: SQLite memory + API + agent hooks (`core.py` retrieval,
  command interception, episodic+learning update).
- Loop INTACT: executor rejects unknown action types closed
  (`executor.py:568`); verifier + final-outcome checks exist; recovery
  engine is crash/code-repair (Nemotron), model fallback lives in router.
- CONCRETE GAP: `VisionPerception._analyze_with_llm`
  (`observer.py:1261`) is a PLACEHOLDER — vision fallback never reaches a
  real model. Hierarchy (UIA first, vision only when insufficient) exists
  and must be preserved.
- OCR: nemotron-parse-2.0 UNAVAILABLE → stays disabled; fallback is
  pytesseract-or-Gemini inside observer/vision tool (preserved).
- Voice: SAPI/Web Speech preserved; NVIDIA voice models UNVERIFIED → no
  integration (riva-translate available, no translation feature to use it).
- Baseline suite 2026-09-25: **185 passed** (full list in §P3.8).

### P3.4 Planned steps

1. Vision fallback: route `_analyze_with_llm` through the Model Router
   vision profile (bounded candidates, health recording, graceful-off).
   Glimmer/GLM never enabled. → verify → test → commit → push.
2. `test_phase3_integration.py`: router fallback/health, vision
   mocked/unavailable/empty/timeout, OCR-disabled path, computer/browser/
   office/voice spot checks, recovery + e2e workflows. → commit → push.
3. Fresh live probe of the vision model (§26) before claiming it works;
   record evidence; final report; STOP.

### P3.5 Checklist

- [x] Audit + baseline 185 passed recorded
- [x] This Phase 3 plan section created
- [x] Vision fallback via validated model only (graceful-off otherwise)
- [x] No unvalidated model enabled (Glimmer/GLM/parse-2.0/voice stay off)
- [x] Phase 3 integration tests green (20/20)
- [x] Fresh §26 vision probe with recorded evidence (below)
- [x] Full suite green (205) + per-component commit/push verified

### P3.6 Verification requirements (per logical change)

EDIT/CREATE → VERIFY → TEST → REVIEW DIFF → UPDATE THIS FILE → COMMIT →
PUSH → VERIFY PUSH → NEXT. No batching; fix failures before committing;
stop the line on push failure.

### P3.7 GitHub checkpoints

Vision integration → push; tests → push; final plan+report → push. Each
with inspected diff, no secrets, focused message, verified `main...origin/main`.

### P3.8 Work log (append after every step)

- 2026-09-25 — Audit + baseline (185 passed: agent/memory/planner/
  restart/whatsapp/phase1-models/gmail/scheduler suites) + created Phase 3
  section. Files changed: `IMPLEMENTATION_PLAN.md`. Commit/push: DONE —
  commit `80a4da5` "Phase 3: plan plus audit baseline 185 passed", push
  `8815dd1..80a4da5 main -> main`, in sync verified 2026-09-25.
- 2026-09-25 — Vision fallback via Model Router (`observer.py` ONLY hunk:
  `_analyze_with_llm` placeholder → router vision profile, ≤3 candidates,
  health recording, graceful ""). NOTE: `observer.py`/`phase2_runtime.py`
  carry pre-existing working-tree changes (dirty since before Phase 2,
  covered by the 185 baseline); this checkpoint commits file state =
  baseline-verified + the described hunks, no re-attribution. Glimmer/GLM
  unreachable by construction (candidates() = ENABLED+validated+FREE).
  Verification: py_compile clean; 20/20 new Phase 3 tests pass (mocked
  success/empty/timeout/no-candidates/missing-file + hierarchy predicate).
  Commit/push: DONE — commit `aa25aab`, push `80a4da5..aa25aab main ->
  main`, in sync verified 2026-09-25.
- 2026-09-25 — Bridge hardening + `test_phase3_integration.py` (20 tests).
  `phase2_runtime.py` ONLY hunk: `_execute_phase2_action` falls through
  (returns None) when the computer tool is unavailable instead of raising
  RuntimeError — found because the new unknown-action test exposed it;
  production (AgentCore registers the tool) unchanged. Tests cover §25:
  validated-only vision selection, OCR profile with no validated model,
  health circuit-break, 5 vision cases, 3 hierarchy cases, executor
  closed-rejection, observer browser/office branches, verifier, voice
  idle preservation, memory loop, stubbed e2e. Same pre-existing-dirt note
  applies to `phase2_runtime.py`. Commit/push: DONE — commit `2bcab2b`,
  push `aa25aab..2bcab2b main -> main`, in sync verified 2026-09-25.
- 2026-09-25 — §26 live probe + completion. Probe (one real request, 1x1
  PNG, "Reply with exactly: OK", 90s budget): `meta/
  llama-3.2-11b-vision-instruct` → `{"ok": true, "latency_s": 0.96,
  "text": "OK"}` on 2026-09-25. Vision fallback is therefore live-capable
  today, not just mocked. Registry store left untouched (no re-validation
  run claimed). FULL suite: **205 passed** (185 baseline + 20 new), zero
  regressions; test-run DB removed; no secrets committed.

### P3.9 Phase 3 completion state (final, verified 2026-09-25)

- Router remains functional (goal/plan/replan router-first verified by
  audit + existing tests; no change needed, none made).
- Phase 2 memory remains functional (loop hooks + 50 tests intact).
- Computer/Browser/Office/Observer/Verifier/Voice/Recovery preserved;
  executor still rejects unknown types closed.
- UIA → DOM → screenshot → vision hierarchy intact; vision now reaches
  the validated model (0.96s live proof) and degrades to "" otherwise.
- OCR stays disabled (parse-2.0 UNAVAILABLE, profile has no validated
  model); NVIDIA voice models stay off (UNVERIFIED); Glimmer/GLM stay off.
- No second agent, no new deps, no ADB/phone/watchdog additions.
- Commits: `80a4da5` (plan+baseline), `aa25aab` (vision), `2bcab2b`
  (bridge+tests) (+ this final plan update next). STOPPING here.

---

> Single plan file for all phases. Updated after every step. No other plan files will be created.

---

## PHASE 2 — Advanced Persistent Memory System

### P2.1 Date / Time

- **Phase 2 start:** 2026-09-25 (UTC)
- **Last updated:** 2026-09-25 (UTC) — Phase 2 COMPLETE, stopping

### P2.2 Phase 2 objective

Transform session/conversation memory into a robust, persistent, searchable,
project-aware memory system (single-agent subsystem, NOT a separate agent):

```text
USER INPUT → UNDERSTAND → MEMORY RETRIEVAL → PLAN → ACT → OBSERVE → VERIFY → MEMORY UPDATE
```

Types: working / user / project / episodic / semantic / procedural.
SQLite (`backend/data/jarvis_memory.db`) is the primary long-term store;
existing JSON (`persistent_memory.json`, `current_session_memory.json`) is
retained for backward compat + one-time migration, never the only mechanism.
Embeddings use ONLY the Phase 1 validated model
(`nvidia/llama-nemotron-embed-vl-1b-v2`, `input_type` protocol, ENABLED in
`model_registry_store.json`); `llama-3_2-nemoretriever-300m-embed-v1`,
`nv-embed-v1`, `nv-embedcode-7b-v1` are UNVERIFIED and MUST NOT be used.
Reranker `llama-nemotron-rerank-vl-1b-v2` is UNVERIFIED → system operates
without reranking (honest no-fit, optional path only).

### P2.3 Current project state (audited 2026-09-25)

- `backend/agent/phase1_memory.py` — explicit user memories, normalized
  key/value, token+phrase recall, same-key update dedup, JSON
  (`backend/data/persistent_memory.json`, currently `[]`).
- `backend/agent/phase1_runtime.py` — `ConversationContext`
  (`current_session_memory.json`), `ReminderStore`, `Phase1Runtime`
  (begin/finish/context_for/model_context), planner + `/api/command` bridges.
- `backend/agent/core.py` — `AgentCore.process()` plan→execute→observe→
  verify loop; planner router-first (`model_router` lazy) + rule fallback.
- `backend/agent/planner.py` — `_call_gemini_for_plan` (Gemini+NVIDIA inline),
  `_call_router_for_plan`, `_rule_based_plan`, `_is_simple_task` fast path.
- Model layer (Phase 1, preserved): `model_interface/registry/catalog/
  nvidia_provider (embed input_type + /reranking)/gemini_provider/router/
  validation/factory`; store evidence `model_registry_store.json`.
- Validated ENABLED FREE (2026-09-21 evidence): laguna-xs-2.1 (primary),
  llama-3.2-11b-vision (multimodal/tools), omni-reasoning (heavy),
  riva-translate, 2× safety, **embed-vl-1b-v2** (embed, input_type=passage).
  Rerank/coding/OCR/voice/image: no validated FREE model.
- `main.py` — `/api/command` (+Phase1 bridge), `/api/agent/run|execute|
  status|plan|resume|instruct`, `/api/status`.
- Baseline test run 2026-09-25: **113 passed**
  (`test_agent_integration` + `test_phase1_memory` + `test_phase1_runtime` +
  `test_planner_direct` + `test_memory_restart_integration` +
  `test_whatsapp_ops` + `test_phase1_models`), Python 3.14, sqlite 3.50.4.
- Working tree at Phase 2 start is DIRTY: Phase 1 model/router/provider
  files + `IMPLEMENTATION_PLAN.md` itself are still untracked/uncommitted
  locally (never pushed); modified: core/executor/observer/planner/verifier/
  voice/browser/computer/result_schema/main/App.jsx/system_ops. Phase 2
  commits will be focused per-component; pre-existing dirt is recorded here
  and NOT claimed as Phase 2 work.

### P2.4 Planned steps

1. Schema (`backend/agent/memory_schema.py`): 6 types, sources, HIGH/MEDIUM/
   LOW confidence, sensitivity, status/expiration, validation, corrupt-record
   tolerance. → verify → test → commit → push.
2. Storage (`backend/agent/memory_store.py`): SQLite primary
   (`jarvis_memory.db`), FTS5-if-available else LIKE fallback, indexes,
   atomic writes, migration from `persistent_memory.json`, restart-proof.
   → verify → test → commit → push.
3. Embeddings (`memory_embeddings.py`, validated-only) + rerank
   (`memory_rerank.py`, unavailable-graceful) + ranking (`memory_ranking.py`,
   explainable weights). → verify → test → commit → push.
4. Memory API (`memory_api.py`): add/search/retrieve/update/delete/forget/
   list/explain + explicit controls ("Remember/Forget/What do you remember/
   Correct/Show") + privacy blocklist + dedup + conflict (supersede, keep
   provenance) + expiration. → verify → test → commit → push.
5. Project memory (`project_memory.py` seed from real files/registry, never
   whole repo) + agent integration (`core.py` retrieval→update hooks,
   planner context budget). → verify → test → commit → push.
6. Tests (`backend/agent/test_phase2_memory.py`): all §23 topics; full suite
   green; existing 113 still passing. → commit → push. Final report, STOP
   before Phase 3.

### P2.5 Checklist

- [x] Audit + baseline 113 passed recorded
- [x] This Phase 2 plan section created
- [x] Schema
- [x] SQLite storage + migration + restart persistence
- [x] Memory API (add/search/retrieve/update/delete/forget/list/explain)
- [x] Explicit remember/forget/correct/show on real store (no fake forget)
- [x] Provenance + confidence (explicit>verified>assumption, no silent overwrite)
- [x] Privacy blocklist + sensitivity
- [x] Retrieval pipeline (candidate→relevance→embed(opt)→rerank(opt)→
      confidence/importance/recency→project→select, context-limited)
- [x] Embeddings validated-only (embed-vl-1b-v2 + input_type; others rejected)
- [x] Rerank validated-only (unavailable → graceful off)
- [x] Explainable ranking (no semantic-drowning, no CoT leak)
- [x] Dedup + conflict + expiration + project memory
- [x] Agent integration (single-agent subsystem)
- [x] Chat learning (preferences from conversation) + planner obeys memory
- [x] Phase 2 tests + full suite green + per-component commit/push verified

### P2.6 Verification requirements (per logical change)

`EDIT/CREATE` → `VERIFY` (import + smoke) → `TEST` (new + relevant old) →
`REVIEW DIFF` → `UPDATE THIS FILE` → `COMMIT` → `PUSH` → `VERIFY PUSH` →
`NEXT`. Failures fixed before commit; push failures stop the line.

### P2.7 GitHub checkpoint requirements

Schema → push; Storage → push; API → push; Retrieval/embed/rerank → push;
Agent integration → push; Tests → push. Each with `git status/diff`,
focused commit message, `git push` output + `git log origin` verification
recorded below. Never claim commit/push without evidence.

### P2.8 Work log (append after every step)

- 2026-09-25 — Audit + baseline (113 passed) + created this Phase 2 section.
  Files changed: `IMPLEMENTATION_PLAN.md`. Verification: full pytest 113
  passed; `python --version` 3.14.0, sqlite 3.50.4. Commit/push: DONE —
  commit `4a1553c` "Phase 2: add implementation plan (audit + 113-test
  baseline)", `git push origin main` → `dacaec4..4a1553c main -> main`,
  `git status -sb` shows `main...origin/main` in sync (verified 2026-09-25).
- 2026-09-25 — Schema + SQLite storage (+ legacy migration).
  Files created: `backend/agent/memory_schema.py` (6 types, 5 sources,
  HIGH/MEDIUM/LOW, sensitivity, active/superseded/expired, validation,
  corrupt-tolerant `from_dict`), `backend/agent/memory_store.py` (SQLite
  `backend/data/jarvis_memory.db`, WAL, FTS5-or-LIKE candidates, indexes,
  hard-delete forget, `record_access`, `mark_expired`, legacy JSON migrate).
  Files modified: `IMPLEMENTATION_PLAN.md` (this log). Verification:
  `py_compile` clean; smoke (tmp DB): add→get→list→candidates→restart
  new-instance persist→delete all OK; existing `test_phase1_memory` +
  `test_phase1_runtime` 11 passed; no stray DB in `backend/data`.
  Commit/push: DONE — commit `1cbe579` "Phase 2: memory schema + SQLite
  storage with legacy migration", push `4a1553c..1cbe579 main -> main`,
  in sync verified 2026-09-25.
- 2026-09-25 — Embeddings (validated-only) + rerank (graceful-off) + ranking.
  Files created: `backend/agent/memory_embeddings.py` (ONLY
  `nvidia/llama-nemotron-embed-vl-1b-v2`; nemoretriever/nv-embed-v1/
  nv-embedcode forbidden; registry-only `is_available`, correct
  query/passage `input_type`, vector cache, never raises), `backend/agent/
  memory_rerank.py` (no validated FREE reranker → `is_available False`,
  input order preserved with honest reason; future ENABLED rerank model
  would be used via provider protocol), `backend/agent/memory_ranking.py`
  (weights semantic .50 > importance .15 > confidence/recency .10 …,
  metadata-only `explain`, context-budget cap, optional rerank pass).
  Verification: registry resolves embed id with zero network calls;
  rerank None/False (matches Phase 1 UNVERIFIED verdict); lexical smoke
  ranks "favorite color: blue" above "favorite food: pizza"; 11 Phase 1
  tests still pass. Commit/push: DONE — commit `6d8e179`, push
  `1cbe579..6d8e179 main -> main`, in sync verified 2026-09-25.
- 2026-09-25 — Memory API + explicit controls + privacy + dedup/conflict/expiry.
  Files created: `backend/agent/memory_api.py` (`JarvisMemory`: add/search/
  retrieve/update/delete/forget/list/explain + remember + purge_expired +
  memory_context + `handle_explicit_command` for Remember/Don't-remember/
  What-remember/Forget/Correct/Show; secret blocklist refusal; PII→sensitive;
  fingerprint+overlap dedup; topic-key conflicts with supersede-history and
  low-authority refusal; per-read `mark_expired`; hard-delete forget;
  project-scoped ranking with graceful embed/rerank). Verification:
  `py_compile` clean; smoke (tmp DB): dedup, supersede (active=1/history=2),
  LOW-vs-HIGH refusal, 2 secret refusals, search/retrieve/explain, update,
  5 explicit commands incl. real forget (dog count 0), expiry, context
  budget all OK; 11 Phase 1 tests pass; no stray DB. Commit/push: DONE —
  commit `75ac930`, push `6d8e179..75ac930 main -> main`, in sync verified
  2026-09-25.
- 2026-09-25 — Project memory + agent integration (single-agent subsystem).
  Files created: `backend/agent/project_memory.py` (16 curated PROJECT facts
  with file/registry provenance, idempotent seed, overview; never the repo).
  Files modified: `backend/agent/core.py` (lazy `memory` property,
  `memory_context_for` retrieval into state, explicit-command interception
  before planning, episodic verified-outcome update after final verification
  — all guarded, pytest runs skip episodic writes), `backend/agent/
  memory_api.py` ("about me"→USER scope, "about project"→PROJECT scope),
  `.gitignore` (local `jarvis_memory.db*`), `IMPLEMENTATION_PLAN.md`.
  Verification: seed 16 added → re-seed 16 deduped; remember/show
  interception via real `process()`; normal task completes with Phase 2
  context in state; `test_agent_integration`+Phase 1 memory/runtime 17
  passed; test-run DB had 0 rows (pytest skip works) and was removed;
  gitignore verified. Commit/push: DONE — commit `866eaf8`, push
  `75ac930..866eaf8 main -> main`, in sync verified 2026-09-25.
- 2026-09-25 — Chat learning + planner obeys memory (user-asked).
  Files modified: `backend/agent/memory_api.py` (`learn_from_exchange`:
  preference cues from ordinary chat → USER/MEDIUM/conversation, never
  overwrites explicit HIGH, secrets refused; side-effect-free command
  detector; hedge-stripping topic keys so "I think my X is green" conflicts
  correctly; consistent `count`/`used_chars` shapes), `backend/agent/
  core.py` (MEMORY UPDATE also learns choices), `backend/agent/planner.py`
  (LLM prompt — router + Gemini — gains bounded preferences block from
  state Phase 2 context; rule path byte-identical).
  Files created: `backend/agent/test_phase2_memory.py` (50 tests: all §23
  topics + learning + planner enrichment + agent integration).
  Verification: 50/50 new pass; FULL suite **163 passed** (113 baseline + 50
  new), zero regressions; test-run DB had 0 rows and was removed.
  Commit/push: DONE — commit `3ddb1b8`, push `866eaf8..3ddb1b8 main ->
  main`, in sync verified 2026-09-25.

### P2.9 Phase 2 completion state (final, verified 2026-09-25)

- Persistent memory works across restarts: SQLite `backend/data/
  jarvis_memory.db` (WAL); verified by two-instance test + smoke.
- Structured types: working/user/project/episodic/semantic/procedural.
- Retrieval works: candidates → relevance → optional embed → optional
  rerank → confidence/importance/recency → project → budget-capped select.
- Explicit remember/forget/correct/show work on the real store, including
  inside `AgentCore.process()` (bypasses planning, no fake forget —
  hard DELETE verified by re-search).
- Provenance (5 sources) + confidence (HIGH/MEDIUM/LOW) on every record;
  conflicts supersede with history (never silent), LOW never beats HIGH.
- Dedup (fingerprint + near-duplicate consolidation), expiration
  (per-record, auto-marked, purged; stable types never auto-expire).
- Project memory: 16 curated facts, idempotent seed, USER/PROJECT scoping.
- Embeddings: ONLY `nvidia/llama-nemotron-embed-vl-1b-v2` (registry-checked,
  correct query/passage `input_type`); nemoretriever/nv-embed-v1/nv-embedcode
  rejected as UNVERIFIED. No live embed call was made in Phase 2 work
  (offline-safe; cosine path covered with fake vectors).
- Rerank: `llama-nemotron-rerank-vl-1b-v2` UNVERIFIED → graceful off,
  input order preserved (verified by test).
- Chat learning: `learn_from_exchange` banks stable choices from ordinary
  conversation as MEDIUM; planner LLM prompt carries bounded memory block;
  rule path byte-identical (proven by test). Frequency weight makes
  often-used memories surface more — use improves recall.
- Tests: 50 new in `backend/agent/test_phase2_memory.py`; FULL suite 163
  passed (113 baseline intact). Every logical change committed + pushed:
  `4a1553c`, `1cbe579`, `6d8e179`, `75ac930`, `866eaf8`, `3ddb1b8`
  (+ this final plan update next). No Phase 3 work started.

---

## PHASE 3 — Proactive Gmail announcements (in progress, 2026-09-25)

User-asked: normal-mode JARVIS announces important mail unasked — spoken
aloud (backend TTS queue, never interrupts active speech) + on-screen toast.
WhatsApp explicitly deferred by user. Schedule: check on every backend
restart + every 30 min. Important-only: VIP senders or urgent keywords.

- 2026-09-25 — Backend monitor. Files created: `backend/tools/
  gmail_notify.py` (own gmail.readonly OAuth scope + `token_gmail.json`, so
  the Gemini token is untouched; REST via `requests`, no new deps;
  VIP/keyword filter; `gmail_seen.json` dedup across restarts; never
  raises), `test_gmail_notify.py` (10 tests, mocked REST). Files modified:
  `main.py` (daemon watcher thread: 60s grace → restart check → 30-min
  loop; `/api/gmail/status|login|logout|check`; `/api/notifications` +
  dismiss; `/api/status` shape unchanged), `.gitignore` (gmail
  watch/seen/token). Verification: 10/10 monitor tests; endpoint smoke
  (status/check/notifications/dismiss, unlinked graceful). Commit/push:
  DONE — commit `0f70806`, push `4e226ee..0f70806 main -> main`, in sync
  verified 2026-09-25.
- 2026-09-25 — Frontend toast + Gmail settings. Files modified: `src/
  App.jsx` (notice stack top-right with beep + dismiss, `/api/notifications`
  on the 8s poll, Gmail link/unlink section in Settings reusing OAuth
  styles). Verification: `vite build` clean (1516 modules); FULL suite
  **173 passed** (163 + 10 gmail), zero regressions. Commit/push: DONE —
  commit `66ee08d`, push `0f70806..66ee08d main -> main`, in sync verified
  2026-09-25. Phase 3 Gmail watcher COMPLETE (WhatsApp deferred per user).
- 2026-09-25 — Normal-mode reminders + scheduled WhatsApp (user-asked).
  Truth: reminders were stored but nothing ever fired them; WhatsApp was
  send-now-only. Files created: `backend/tools/scheduler.py` (stdlib time
  parser: relative/at-today-tomorrow/weekday, aware ISO; reminder parse/
  add/list/cancel on Phase 1 store; WhatsApp job store
  `scheduled_whatsapp.json` surviving restarts; 30s daemon ticker; direct
  `/api/command`-shaped handler; never raises), `test_scheduler.py` (12
  tests, mocked stores). Files modified: `main.py` (direct handler before
  Gemini in `process_command`; ticker callbacks: reminder voice+toast,
  scheduled send via existing desktop sender with spoken success/failure),
  `.gitignore` (scheduler/reminder private data). Verification: 12/12 new;
  live `/api/command` smoke (set→list→cancel both features, no LLM);
  FULL suite **185 passed**, zero regressions. Commit/push: DONE — commit
  `058f5f2`, push `40020ec..058f5f2 main -> main`, in sync verified
  2026-09-25.

---

# J.A.R.V.I.S. — PHASE 1 IMPLEMENTATION PLAN (history, preserved)

## Multi-Model Intelligence + Model Router

> Single plan file for Phase 1. Updated after every step. No other plan files will be created.

---

## 1. Date / Time

- **Phase start:** 2026-09-21 (UTC)
- **Last updated:** 2026-09-21 (UTC) — Phase 1 COMPLETE, stopping

## 2. Objective

Build a reliable multi-model intelligence layer and Model Router on top of the
existing J.A.R.V.I.S. agent, without touching advanced memory or major
multimodal expansion:

```text
JARVIS Agent
     ↓
Model Router
     ↓
┌──────────────┬───────────────┬──────────────┐
│ Primary      │ Multimodal    │ Heavy        │
│ Agent        │ / Fallback    │ Reasoning    │
└──────────────┴───────────────┴──────────────┘
     ↓
Existing Executor
     ↓
Existing Tools
```

ONE JARVIS agent. MULTIPLE models. ONE router. FREE-only NVIDIA usage.

## 3. Current Architecture (as inspected)

- `backend/agent/core.py` — `AgentCore`: plan → validate → execute → observe →
  verify → replan loop; human-in-the-loop; CodeCore self-debug hook.
  (Note: file defines `__init__` twice; second definition wins — pre-existing.)
- `backend/agent/planner.py` — `Planner` + module functions. LLM access is
  **duplicated inline HTTP**: `_call_gemini_for_plan()` contains a Gemini
  `generateContent` block (3s timeout) and an NVIDIA/Groq OpenAI-compatible
  block (3s timeout). Rule-based fallback `_rule_based_plan()` works offline.
- `backend/agent/executor.py` — dispatches `ActionSpec` to Computer / Browser /
  Office / system_ops / phone / WhatsApp tools. No LLM calls inside.
- `backend/agent/observer.py` — post-action state verification + `SemanticState`/
  `PerceptionManager` vision fallback. No LLM calls inside (vision via tools).
- `backend/agent/verifier.py` — confidence-weighted verification +
  `verify_with_vision`. No direct LLM calls.
- `backend/agent/state.py` — `TaskState`, `ActionSpec`, `Plan`,
  `FailureClassification`, `VerificationMethod`, `TaskType`.
- `backend/tools/vision.py` — Gemini vision/OCR (`inline_data`), model chain
  `gemini-2.5-flash → 2.0-flash → 1.5-flash`. Preserved as-is in Phase 1.
- `code_core.py` — `call_nemotron()`: dedicated NVIDIA NIM streaming caller
  (default model `z-ai/glm-5.3-flash`), used for code fixing only.
- Config: root `config.json` holds `gemini_api_key`, `nvidia_api_key`
  (`nvapi-…`, also duplicated as `groq_api_key`), `nvidia_model`
  (`z-ai/glm-5.3-flash`), nemotron retry/timeout/token settings.
- Prior evidence (`AGENT_RECALL.txt`, 2026-09-14): on this free tier,
  `z-ai/glm-5.3-flash` answers small prompts in ~12–19s (streaming);
  `deepseek-ai/deepseek-v4-flash-0731` queued ~100s; only GLM is reliable/fast.

## 4. Phase 1 Plan

1. **Registry** (`backend/agent/model_registry.py`): central record with
   `model_id, provider, display_name, free_endpoint, status, enabled,
   validated, capabilities, context_limit, priority, fallback_group,
   last_validated, last_success, last_failure, latency` + health
   (`consecutive_failures, failure_category, rate_limits, validation_time`).
   Statuses: `DISCOVERED, VALIDATED, ENABLED, UNAVAILABLE, DEPRECATED,
   PAID_OR_PARTNER_ONLY, AUTH_ERROR, RATE_LIMITED, CAPABILITY_FAILED,
   UNVERIFIED, DISABLED`. FREE-only filtering: `enabled ⇒ validated + free`.
2. **Catalog** (`backend/agent/model_catalog.py`): every supplied candidate
   name + resolved NVIDIA endpoint identifier (never invented) + capability
   hints. Listing alone never enables a model.
3. **Interface** (`backend/agent/model_interface.py`): `BaseModelProvider`
   with `generate/stream/tool_call/vision/embed/rerank/ocr/health_check/
   get_model_info`, normalized `ModelResponse`, `ModelError` categories.
4. **NVIDIA provider** (`backend/agent/nvidia_provider.py`): ONE abstraction
   over `https://integrate.api.nvidia.com/v1/chat/completions` (+ `/v1/models`
   for catalog listing). No per-model HTTP duplication.
5. **Gemini provider** (`backend/agent/gemini_provider.py`): preserve existing
   Gemini behavior behind the common interface.
6. **Router** (`backend/agent/model_router.py`): route on task type, reasoning/
   coding/vision/tool/latency/context/health/FREE status; bounded fallback
   chain (timeout → server error → rate limit → unavailable → unsupported
   capability → auth error); no endless retries.
7. **Validation** (`backend/agent/model_validation.py`): real runtime checks
   (tiny prompt, capability probes) → registry updates; full audit of ALL
   supplied candidates against live `/v1/models` + spot runtime probes.
8. **Planner wiring**: `Planner` prefers router, falls back to existing
   `_call_gemini_for_plan()` + rule-based path. No executor/tool changes.
9. **Tests** (`test_phase1_models.py`): provider, auth, normalization,
   registry, FREE filtering, validation, router, fallback, health, tool
   calls, errors, timeouts. Then full suite re-run.

## 5. Checklist

- [x] Inspect core.py, planner.py, executor.py, observer.py, verifier.py,
      state.py, backend/tools/*, Gemini + NVIDIA integration, config, env
- [x] Run existing test suite → baseline recorded (§6)
- [x] Create this single IMPLEMENTATION_PLAN.md
- [x] Central model registry (required fields + statuses + FREE filter)
- [x] ONE NVIDIA provider abstraction (generate/stream/tool_call/vision/
      embed/rerank/ocr/health_check/get_model_info, normalized responses)
- [x] Gemini preserved + common-interface compatible
- [x] Model Router (task/reasoning/coding/vision/tool/latency/context/
      health/FREE) + bounded fallback
- [x] Health tracking (last_success/last_failure/failure_category/latency/
      consecutive_failures/rate_limits/validation_time)
- [x] ALL supplied candidates audited (identifiers resolved, never invented)
- [x] Real NVIDIA runtime validation performed (FREE + accessible + healthy)
- [x] Primary (`Nemotron 3.5 Lightning 30B A3B`) verdict by evidence only
- [x] Fallback (`GLM-5.3-Flash`) verdict by evidence only
- [x] New tests added + full suite re-run, no regressions vs baseline
- [x] IMPLEMENTATION_PLAN.md updated + factual final report, then STOP

## 6. Baseline Test Results (pre-change, 2026-09-21)

- `test_agent_integration.py` (6) + `backend/agent/test_phase1_memory.py`
  (7) + `backend/agent/test_phase1_runtime.py` (4): **17 passed**.
- `test_planner_direct.py` + `test_memory_restart_integration.py` +
  `test_whatsapp_ops.py`: **13 passed**.
- `test_architecture.py`: 4 async functions are **scripts, not pytest tests**
  (no `pytest-asyncio` plugin) — fail at collection under pytest by design;
  they run via `python test_architecture.py`.
- `test_agent.py`: **pre-existing collection bug** — runs `asyncio.run()` at
  import and treats `ActionSpec` (planner returns specs, not dicts) as
  subscriptable → `TypeError`. Not caused by Phase 1.
- `test_research_pipeline.py` / `test_computer_use_engine.py`: execute on
  import / need live Windows GUI — excluded from pytest baseline.

## 7. Work Log

- **2026-09-21 — Inspection.** Read agent core/planner/executor/observer/
  verifier/state, registry, tools (browser/computer/office/vision/charts/
  result_schema), `code_core.call_nemotron`, `agent.py` Gemini paths,
  `research_synthesizer.py`, `main.py` config, `config.json`, `.env`,
  `AGENT_RECALL.txt`. Ran baseline suite (§6). Created this file.
  Files changed: `IMPLEMENTATION_PLAN.md` (new).
- **2026-09-21 — Build.** New: `backend/agent/model_interface.py`
  (BaseModelProvider + normalized response/error), `model_catalog.py`
  (93 unique supplied candidates, match tokens, 1 trusted id),
  `model_registry.py` (required fields + 11 statuses + FREE filter +
  JSON persistence), `nvidia_provider.py` (ONE abstraction over NIM
  chat/models/embed/rerank + SSE stream + normalized errors),
  `gemini_provider.py` (existing REST/OAuth/chain behavior preserved),
  `model_router.py` (profile routing + bounded fallback + health),
  `model_validation.py` (runtime probes + live-listing audit, never
  invents ids), `model_factory.py` (config-based wiring). Edited:
  `planner.py` (router-first with legacy fallback at 3 call sites),
  `core.py` (lazy `model_router` property). Verified: `py_compile` clean;
  smoke test shows 0 ENABLED models → router inactive → rule-based
  planning unchanged (offline behavior preserved).
- **2026-09-21 — strict resolver.** First audit pass matched 39 candidates
  but manual review caught 12 lookalikes (e.g. `GPT-OSS-120B→gpt-oss-20b`,
  `Llama 3.1 8B→safety-guard`, `Mistral Medium 3→mistral-7b`). Hardened
  `resolve_endpoint_id`: every digit token must match, dotted versions must
  match (`3.3≠3.1`), distinctive long tokens must all match, family veto
  (safety/guard/embed/vision/…), ≤3 extra tokens. Result: **27 exact
  matches, 66 honest UNVERIFIED**. Store reset and re-audited.
  Files changed: `model_validation.py`.
- **2026-09-21 — live validation (FREE key, real requests).**
  `/v1/models` → 81 live ids. Non-stream probes: vision-11b OK (2.4s).
  Streaming probes: Nemotron 3.5 Lightning answered once in 210.8s
  (accessible, too slow); GLM-5.3-Flash empty after 276s (tier queued
  today; 2026-09-14 recall: 12–19s OK). Sweep (30s health + validate):
  laguna-xs-2.1, omni-reasoning, 2× safety, riva-v1.1, vision-11b, embed-vl
  (input_type fix) ENABLED; 18 UNAVAILABLE (7× HTTP 404 listed-but-not-
  servable, 3× empty, 3× timeout, 2× HTTP 500, 503, …). Router tweaks:
  safety/translation/tool groups, laguna→primary, vision→multimodal,
  omni→reasoning caps. Fixed factory seed id to live-verified dotted id;
  `embed()` gained `input_type`. Lightning marked VALIDATED-but-disabled
  (evidence: 1 stream answer, 211s — not routable).
  Files changed: `model_router.py`, `model_catalog.py`, `model_factory.py`,
  `nvidia_provider.py`, `model_registry_store.json` (evidence).
- **2026-09-21 — tests + regression.** New `test_phase1_models.py`: 31/31
  pass (1 real bug found & fixed: wrong FailureCategory name). Full suite:
  **61 passed** (31 new + 30 baseline), zero regressions. Live E2E:
  `generate_with_fallback` answered exactly via laguna-xs-2.1; planner
  produced a correct plan (tier slow ~100s/call that hour; rule path
  intact, health clean). Files changed: `test_phase1_models.py`.
- **2026-09-21 — live-run fix (post-Phase-1 hardening).** First real
  `POST /api/agent/run` showed watchdog health timeouts (4/5): the
  planner's blocking LLM calls ran inline on the server event loop,
  stalling `/api/status` + SSE while planning (pre-existing pattern,
  amplified by Phase-1's longer router timeouts). Fix: `plan_task` and both
  `replan` calls now run via `asyncio.to_thread` in `core.py` — loop stays
  responsive. Regression test added (heartbeat gap < 1s during 2s blocking
  plan; verified it fails on the old inline behavior). Suite: **62 passed**
  (32 new + 30 baseline). `ConnectionResetError` tracebacks in the log are
  benign pre-existing Windows asyncio noise. Files changed: `  core.py`,
  `test_phase1_models.py`.
- **2026-09-21 — live-run fix #2 (pre-existing tool bug, not Phase 1).**
  User's research task failed at `browser_extract`: `BrowserActionResult`
  had no `text`/`value`/`selector`/`links`/`path`/`query`/`before_url`/
  `details`/`retryable` fields, so every extract/type/get_page_text call
  crashed the dataclass constructor and forced needless replans. Fix: added
  the missing optional fields (+ to_dict emission) in `result_schema.py`.
  While verifying, found a second latent bug: base `ToolResult.error`
  field collides with the `error()` classmethod, leaking a bound method
  into every result dict (not JSON-serializable) — guarded in `to_dict()`.
  Computer schema verified clean. Regression test added. Suite: **63
  passed**. Files changed:   `backend/tools/result_schema.py`,
  `test_phase1_models.py`.
- **2026-09-21 — graded ladder test (low→high), live agent runs.** L1
  calculate 48*25: PASS 6.0s. L2 create folder: initially FAILED — real
  findings: (a) executor+observer `verify_file` used `isfile`, rejecting
  folders (folder WAS created, verify wrongly failed 6×); fixed both to
  accept files-or-folders; (b) planner lowercased folder names (matched on
  task_lower); fixed to match original with re.I. Re-run: PASS ~0s, case
  preserved. L3 notepad open+type: PASS 4.9s. L4 live browser search: PASS
  13.3s. L5 research (2 sources) + Word doc: PASS 73s, 8/8 steps, docx
  verified real (34 paragraphs, 1028 words) — the exact flow that crashed
  for the user before fix #2. Suite: **65 passed**. Artifacts cleaned up.
  Files changed: `backend/agent/executor.py`, `backend/agent/observer.py`,
  `backend/agent/planner.py`.
- **2026-09-21 — notepad dictation fix (user-reported).** Unquoted
  "open notepad and type hello" typed the whole command: no quote match
  fell back to `text = task`. Fix: extract what follows type/write, strip
  trailing "in notepad", fall back to empty (never the command). Verified
  6 phrasings; content assertion added. Suite: **65 passed**.
  Files changed: `backend/agent/planner.py`, `test_phase1_models.py`.
- **2026-09-21 — benchmark 3-source research+doc (user-asked comparison).**
  Run 1: FAIL 449s — Scholar redirect-wrapper URLs navigated fine but
  verification compared against the wrapper (false mismatch ×6). Fix:
  `unwrap_search_url` (Scholar/Google/Bing/DDG) applied at navigate +
  verify in `browser.py`/`executor.py`/`observer.py`. Run 2: FAIL 314s —
  navigations now pass, but one empty source page retried 6× and killed
  the task despite 2 banked sources. Fix: `_should_skip_empty_source` —
  skip dead sources when >200 chars banked (core.py). Run 3: **COMPLETED
  222s (3.7 min), 10/10 steps, docx verified real** (33 paras). Suite: **67
  passed**. Files changed: `backend/tools/browser.py`,
  `backend/agent/executor.py`, `observer.py`, `core.py`,
  `test_phase1_models.py`.
- **2026-09-21 — speed round 2 (user: "how can we make it fast").**
  Benchmark breakdown showed planning 129s + search 69s of 222s. Fixes:
  (a) rules-first planning — rule plan used instantly when non-degenerate,
  LLM only for uncovered tasks (new `_is_degenerate_plan`, `_build_plan` /
  `_store_research_params` helpers); research planning 129s → 0.5s.
  (b) DDG-first search (Google→fallback): search 69s → 5.4s. Re-run same
  benchmark: **COMPLETED 65.7s, 10/10, zero errors, docx real** (38 paras,
  696 words) — was 222s. Suite: **69 passed**. Files changed:
  `backend/agent/planner.py`, `backend/tools/browser.py`,
  `test_phase1_models.py`.
- **2026-09-21 — speed fix (user-reported: small tasks too slow).** Every
  task paid up to ~3 min of LLM calls (goal + plan, 90s each) even when the
  deterministic planner knew the answer. Fix: `_is_simple_task` fast path —
  calculator, app open/type, folder create, screenshot, UI click, explicit
  URL, plain search skip LLMs entirely (rule-based goal + plan, ~0s);
  research/artifact tasks still try the router but with a 30s cap
  (`PLAN_LLM_TIMEOUT_S`) so a queued tier yields to rules fast. Measured:
  calc 0.85s, notepad 0.01s (was ~200s). Tests added. Suite: **65 passed**.
  Files changed: `backend/agent/planner.py`, `test_phase1_models.py`.

---

## 8. Validation & Audit Results (2026-09-21, live FREE-key evidence)

- **Live `/v1/models` listing:** 81 ids, HTTP 200 with the configured key.
- **Primary verdict — `Nemotron 3.5 Lightning 30B A3B`
  (`nvidia/nemotron-3.5-lightning-30b-a3b`): NOT adopted as primary.**
  Criteria: FREE ✓ (key accepted, no 401/403) + listed ✓ + runtime answered
  once ✓ (stream, trivial prompt) BUT latency 210.8s + reasoning-leak output
  ⇒ health requirement FAILED. Status: VALIDATED-but-disabled, never routed.
- **Fallback verdict — `GLM-5.3-Flash` (`z-ai/glm-5.3-flash`): NOT enabled
  today.** 2026-09-14 recall: 12–19s stream OK. 2026-09-21: non-stream
  timeout (125s) + stream empty (276s) ⇒ tier queued/degraded ⇒ stays
  DISCOVERED until a fresh validation passes. Nothing was forced.
- **De-facto routing after validation (all FREE + validated + ENABLED):**
  general/chat → `poolside/laguna-xs-2.1` (~1–8s); vision/multimodal/tools →
  `meta/llama-3.2-11b-vision-instruct` (~1.5s, tool_call proven live);
  reasoning → `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (~4s);
  safety → `nvidia/nemotron-3.5-content-safety` / `…-safety-guard-8b-v3`;
  translation → `nvidia/riva-translate-4b-instruct-v1.1`; embed →
  `nvidia/llama-nemotron-embed-vl-1b-v2` (2048-dim). Coding/OCR/rerank/voice/
  image: no validated FREE model ⇒ router honestly reports no fit.
- **Key lesson (proven twice): listing ≠ servable.** 7 listed ids return
  HTTP 404 on use; 2 more return HTTP 500/503; muse-glimmer returns instant
  empty (3 probes). Validation, not the catalog, decides.
- **Per-model table:** §9 (compact). Full evidence:
  `backend/agent/model_registry_store.json`.

## 9. Model Audit Table (27 matched of 93 unique candidates)

| Candidate | Resolved endpoint id | Live status | Enabled | Evidence |
|-----------|---------------------|-------------|---------|----------|
| GLM-5.3-Flash | z-ai/glm-5.3-flash | DISCOVERED | No | 2 timeouts 2026-09-21; OK 2026-09-14 |
| GLM-5.3 | z-ai/glm-5.3 | UNAVAILABLE | No | timeout 95s |
| Nemotron 3.5 Lightning 30B A3B | nvidia/nemotron-3.5-lightning-30b-a3b | VALIDATED (disabled) | No | 1 stream answer, 210.8s — too slow |
| Muse Glimmer 30B | meta/muse-glimmer-30b | UNAVAILABLE | No | 3× instant empty response |
| Kimi K3 | moonshotai/kimi-k3 | UNAVAILABLE | No | timeout 95s |
| Laguna XS 2.1 | poolside/laguna-xs-2.1 | ENABLED | Yes | chat ~1s, primary group |
| Nemotron 3 Ultra 550B A55B | nvidia/nemotron-3-ultra-550b-a55b | UNAVAILABLE | No | HTTP 500 then 503 |
| Nemotron 3 Nano Omni | nvidia/nemotron-3-nano-omni-30b-a3b-reasoning | ENABLED | Yes | chat+reasoning ~4s, heavy group |
| Gemma-4-31B-IT | google/gemma-4-31b-it | UNAVAILABLE | No | timeout 95s |
| Cosmos Reason2 8B | nvidia/cosmos-reason2-8b | UNAVAILABLE | No | HTTP 404 on use |
| GPT OSS 20B | openai/gpt-oss-20b | UNAVAILABLE | No | empty after 60s |
| Llama 3.1 Nemotron 70B Instruct | nvidia/llama-3.1-nemotron-70b-instruct | UNAVAILABLE | No | HTTP 404 on use |
| Llama 3.1 Nemotron Ultra 253B | nvidia/llama-3.1-nemotron-ultra-253b-v1 | UNAVAILABLE | No | HTTP 404 on use |
| Mistral-7B-Instruct-v0.3 | mistralai/mistral-7b-instruct-v0.3 | UNAVAILABLE | No | HTTP 404 on use |
| nemotron-3-nano-30b-a3b | nvidia/nemotron-nano-3-30b-a3b | UNAVAILABLE | No | HTTP 404 on use |
| Gemma 3 12B IT | google/gemma-3-12b-it | UNAVAILABLE | No | HTTP 404 on use |
| Gemma 3 4B IT | google/gemma-3-4b-it | UNAVAILABLE | No | HTTP 404 on use |
| Llama-3.2-90B-Vision-Instruct | meta/llama-3.2-90b-vision-instruct | UNAVAILABLE | No | timeout 65s |
| Llama 3.2 11b Vision Instruct | meta/llama-3.2-11b-vision-instruct | ENABLED | Yes | chat+vision+tool_call ~1.5s |
| llama-nemotron-embed-vl-1b-v2 | nvidia/llama-nemotron-embed-vl-1b-v2 | ENABLED | Yes | embed 2048-dim, input_type=passage |
| nemotron-parse-2.0 | nvidia/nemotron-parse-2.0 | UNAVAILABLE | No | empty after 4s |
| riva-translate-4b-instruct-v1_1 | nvidia/riva-translate-4b-instruct-v1.1 | ENABLED | Yes | translation ~1.3s |
| nemotron-3-content-safety | nvidia/nemotron-3.5-content-safety | ENABLED | Yes | safety ~0.9s |
| llama-3.1-nemotron-safety-guard-8b-v3 | nvidia/llama-3.1-nemotron-safety-guard-8b-v3 | ENABLED | Yes | safety ~6.8s |
| Llama Guard 4 12B | meta/llama-guard-4-12b | UNAVAILABLE | No | timeout 65s |
| synthetic-video-detector | nvidia/ai-synthetic-video-detector | UNAVAILABLE | No | HTTP 500 |
| mistral-nemotron | mistralai/mistral-nemotron | UNAVAILABLE | No | HTTP 500 after 17s |

**66 UNVERIFIED (no live endpoint id — never invented, never enabled):**
Active Speaker Detection, ByteDance-Seed/Seed-OSS-36B-Instruct, DeepSeek V4
Flash, DeepSeek V4 Flash 0731, DeepSeek V4 Pro, DeepSeek V4 Pro 0813,
FLUX.1-Kontext-dev, FLUX.1-dev, FLUX.1-schnell, FLUX.2 Klein 4B, GLM-5.2,
GPT-OSS-120B, Gemma 3n E2b/E4b It, Inkling, Llama 3.1 8B Instruct, Llama 3.1
Nemotron Nano 8B v1, Llama 3.1 Nemotron Nano VL 8B v1, Llama 3.2 1b/3B
Instruct, Llama 3.3 70b Instruct, Llama 3.3 Nemotron Super 49B v1/v1.5,
Llama 4 Maverick 17b 128e Instruct, Magistral Small 2506, MiniMax-M2.7/M3,
Ministral 3 14B 2512, Mistral Large 3 675B 2512, Mistral Medium 3/3.5,
Nemotron Nano 12B v2 VL, Phi 4 Multimodal, Phi-4-Mini, Qwen Image/Edit,
Qwen2.5/Qwen3 Coders, Qwen3-Next-80B, Qwen3.5 122B/397B, Step 3.5/3.7 Flash,
bevformer, cosmos-predict/transfer, esm2/esmfold, gliner-pii,
nemoretriever-300m, rerank-vl-1b, magpie-tts, mistral-small-4-119b,
safety-reasoning-4b, nemotron-ocr-v2, nemotron-voicechat, nv-embed-v1,
nv-embedcode, paligemma, sarvam-m, sparsedrive, streampetr, studiovoice,
usdcode, usdvalidate.

## 10. Exit Status

**Phase 1: COMPLETE — all exit conditions met (2026-09-21).**

- [x] NVIDIA provider works (7 models validated live; E2E router call exact)
- [x] Gemini still works (provider preserved + **live proof 2026-09-21**:
      chain retried past a 503 on 2.5-flash and answered; no Gemini call
      sites removed — planner legacy path + vision.py untouched)
- [x] Registry works (93 records, persistence, evidence in store JSON)
- [x] Router works (correct slot routing incl. live E2E; honest no-fit)
- [x] FREE-only filtering works (enable guard + tests; paid/unverified never
      enabled — 0 non-FREE entries in `free_enabled()`)
- [x] Fallback works (bounded, tested; live planner fell back cleanly)
- [x] Model health works (all required fields tracked + persisted)
- [x] Supplied models audited (93 unique: 27 resolved exactly, 66 UNVERIFIED)
- [x] Actual NVIDIA validation performed (81-id listing + ~30 live probes)
- [x] Tests pass (61/61: 31 new + 30 baseline, zero regressions)
- [x] `IMPLEMENTATION_PLAN.md` updated (this file only)

STOPPING here. Phase 2 not started.
