# JARVIS Implementation Plan — 2026-09-25

## Objective
Implement the requested upgrades directly in the existing JARVIS architecture while preserving the one-agent design, Gemini/Nemotron roles, free/local-first constraints, existing memory system, and regression safety.

## Guardrails
- One agent with many tools; no multi-agent rewrite.
- Gemini remains primary reasoning; Nemotron remains coding/tooling.
- Local fallback is optional and never silently replaces configured models.
- No paid API/subscription requirement and no unnecessary dependencies.
- Extend existing state/planner/executor/recovery/memory systems; do not create competing state systems.
- A step becomes resumable only after verification.
- Previous actions are never blindly replayed.

## Phase 1 — Reliability Core (CRITICAL)
- [x] Added backend/agent/task_persistence.py with SQLite task state, checkpoints and universal task history.
- [x] Integrated durable task creation/resume into AgentCore.process.
- [x] Persisted an action_started marker before real-world execution.
- [x] Persisted action observation/result/verification events.
- [x] Persisted a checkpoint only after the existing verifier reports success.
- [x] Resume starts after the highest verified checkpoint and restores verified completed steps.
- [x] Added plan serialization/deserialization so resumable tasks can reuse their saved plan.
- [x] Added verified prior-task experience retrieval.
- [x] Connected prior verified experience to the existing planner context.
- [ ] Add/execute dedicated checkpoint/restart regression tests locally.
- [ ] Add stronger in-flight recovery verification for the narrow crash window after an external side effect but before observer persistence.

## Phase 2 — Memory + Documents + WhatsApp
- [x] Existing automatic memory extraction is preserved through learn_from_exchange with confidence, privacy, deduplication and conflict rules.
- [x] Existing persistent memory remains the source of user/project facts.
- [x] Added Memory → Experience → Future Action bridge through verified task history.
- [x] Existing document_intel.py already supports PDF/DOCX/PPTX/TXT/MD and image/scanned-document OCR paths; existing research/document generation pipeline remains intact.
- [x] Existing backend/tools/scheduler.py already contains persistent reminders and scheduled WhatsApp jobs with tests.
- [ ] Further improve document semantic indexing/provenance and expose it more deeply to task planning.
- [ ] Perform a live WhatsApp scheduled-send/reschedule/cancel verification on Windows.

## Phase 3 — Local Fallback + Hardening
- [x] Added stdlib-only backend/agent/local_model.py for optional Ollama availability detection and planning.
- [x] Added local fallback after configured remote planner providers fail.
- [x] Existing Gemini/NVIDIA routes remain ahead of local fallback.
- [ ] Add local-model integration tests with a mocked Ollama endpoint.
- [ ] Run the complete local regression suite and fix any regressions.
- [ ] Add stronger task-history UI/API access if required by the frontend.
- [ ] Final architecture/documentation cleanup.

## Git workflow completed so far
Each implemented code step was committed directly to the GitHub main branch: plan update, durable task persistence, plan serialization, core checkpoint/resume integration, in-flight action markers, verified experience retrieval, planner-context experience bridge, and local Ollama fallback.

## Verification status
GitHub commits were successfully created for every implemented step. The connected GitHub environment does not expose a runnable local Windows test environment for this repository, and no workflow run was available for the latest commits. Therefore no claim is being made that the full test suite has passed yet. The next verification step must be performed on the Windows JARVIS machine before treating the reliability changes as production-ready.