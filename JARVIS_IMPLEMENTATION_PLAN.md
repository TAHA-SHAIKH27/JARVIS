# JARVIS Implementation Plan — 2026-09-25

## Objective
Implement the requested upgrades directly in the existing JARVIS architecture, preserving current behavior, Gemini/Nemotron roles, one-agent design, free/local-first constraints, and regression safety.

## Guardrails
- One agent with many tools; no multi-agent rewrite.
- Gemini remains primary reasoning; Nemotron remains coding/tooling.
- Local fallback is optional and never silently replaces configured models.
- No paid API/subscription requirement and no unnecessary dependencies.
- Extend existing state/planner/executor/recovery/memory systems; do not create competing state systems.
- A step is complete only after verification.
- Previous actions are never blindly replayed; re-observe and verify before acting.

## Phase 1 — Reliability Core (CRITICAL)
- [ ] Persistent task/checkpoint store.
- [ ] Step-level checkpoints containing plan/action/observation/result/error metadata.
- [ ] Persist running/paused/interrupted/failed/completed task state.
- [ ] Resume from the last verified checkpoint after process/backend/Windows restart.
- [ ] Prevent duplicate execution of verified completed steps.
- [ ] Stale-running-task detection and safe recovery.
- [ ] Universal searchable task history.
- [ ] Store verified task outcomes/recovery as experience.
- [ ] Tests for completion, pause/resume, restart, duplicate prevention, partial failure, and corrupted checkpoints.

## Phase 2 — Memory + Documents + WhatsApp
- [ ] Automatic memory extraction with confidence/privacy filtering, dedup and conflict handling.
- [ ] Memory → Experience → Future Action retrieval during planning.
- [ ] Link experiences to tools/projects/tasks and verified outcomes.
- [ ] PDF/DOCX/PPTX intelligence: extraction, OCR where available, structured content, provenance, comparison and semantic retrieval.
- [ ] Research → cited report → DOCX/PPTX pipeline integration.
- [ ] Persistent WhatsApp scheduling with saved-contact resolution, cancel/reschedule, restart persistence and execution status.
- [ ] Tests for extraction, experience retrieval, documents and scheduling state.

## Phase 3 — Local Fallback + Hardening
- [ ] Local Ollama-compatible fallback/model routing without changing Gemini/Nemotron defaults.
- [ ] Detect local availability and degrade gracefully.
- [ ] Integrate all upgrades with UNDERSTAND → PLAN → ACT → OBSERVE → VERIFY → ADAPT → CONTINUE.
- [ ] End-to-end regression coverage; preserve existing tests.
- [ ] Update documentation and architecture notes.

## Required development workflow
For every code/documentation step:
1. Inspect affected code.
2. Implement one coherent change.
3. Verify statically and run available tests when execution is available.
4. Update THIS file with done work and verification/results.
5. Commit/push that verified step to GitHub.
6. Only then start the next step.
Do not create additional session-plan files.

## Current progress
- Step 0 — Plan updated for the requested work. Repository code has not yet been changed for these upgrades.
