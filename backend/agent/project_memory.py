"""Phase 2 — project-aware memory for J.A.R.V.I.S.

Project memory (memory_type=PROJECT, project_id="jarvis") is distinct from
general user memory: it retains architecture decisions, completed phases,
known limitations, verified capabilities, file relationships, implementation
decisions, test results and model validation results.

It NEVER stores the repository itself — only curated facts, each with
provenance pointing at the authoritative file (IMPLEMENTATION_PLAN.md,
model_registry_store.json, source modules). The files stay authoritative;
memory is an index, not a copy.

`seed_project_memory()` is idempotent (add() dedups) and safe to call at
startup and in tests (inject an isolated store).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.memory_schema import Confidence, MemorySource, MemoryType

PROJECT_ID = "jarvis"

# (content, source, source_reference, tags)
_SEED_FACTS: List[tuple] = [
    ("JARVIS is a single agent: AgentCore (backend/agent/core.py) runs "
     "plan-validate-execute-observe-verify-replan; memory is a subsystem of "
     "that agent, never a separate agent.",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md P2.2 + backend/agent/core.py",
     ["architecture", "agent"]),
    ("Model routing: JARVIS Agent -> Model Router -> {primary | multimodal / "
     "fallback | heavy} -> Executor -> Tools. Only FREE + validated + ENABLED "
     "registry entries are ever selected (backend/agent/model_router.py).",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md Phase 1 + backend/agent/model_router.py",
     ["architecture", "model-router"]),
    ("Phase 1 completed 2026-09-21: multi-model intelligence + Model Router, "
     "7 FREE models validated live, full suite green.",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md §10",
     ["history", "phase-1"]),
    ("Phase 2 memory: SQLite backend/data/jarvis_memory.db is the primary "
     "long-term store; persistent_memory.json / current_session_memory.json "
     "are retained for backward compatibility and migration only.",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md P2.2 + backend/agent/memory_store.py",
     ["architecture", "memory", "phase-2"]),
    ("Validated primary chat: poolside/laguna-xs-2.1 (~1s responses, FREE, ENABLED).",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json",
     ["capability", "chat", "validated"]),
    ("Validated multimodal/tools/vision: meta/llama-3.2-11b-vision-instruct "
     "(chat+vision+tool_call proven live ~1.5s).",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json",
     ["capability", "vision", "tools", "validated"]),
    ("Validated heavy reasoning: nvidia/nemotron-3-nano-omni-30b-a3b-reasoning (~4s).",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json",
     ["capability", "reasoning", "validated"]),
    ("Validated embeddings: nvidia/llama-nemotron-embed-vl-1b-v2 with "
     "input_type=passage for documents, input_type=query for questions. "
     "nemoretriever-300m, nv-embed-v1 and nv-embedcode-7b-v1 are UNVERIFIED "
     "and must never be used.",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json + memory_embeddings.py",
     ["capability", "embeddings", "validated"]),
    ("No validated FREE reranker exists: llama-nemotron-rerank-vl-1b-v2 is "
     "UNVERIFIED; memory retrieval operates lexically (+optional embeddings) "
     "without reranking.",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json + memory_rerank.py",
     ["limitation", "rerank"]),
    ("Nemotron 3.5 Lightning 30B A3B answered once in ~211s: accessible but "
     "too slow to route; stays VALIDATED-but-disabled, never routed.",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json",
     ["limitation", "latency"]),
    ("No validated FREE coding, OCR, voice, TTS, image or video model: the "
     "router honestly reports no fit for those capabilities.",
     MemorySource.VERIFIED_TASK_RESULT, "backend/agent/model_registry_store.json",
     ["limitation", "capabilities"]),
    ("Memory ranking is explainable: semantic 0.50 > importance 0.15 > "
     "confidence/recency 0.10 > frequency/project 0.05 > type 0.03 > explicit "
     "0.02; every hit carries metadata, never chain-of-thought.",
     MemorySource.PROJECT_FILE, "backend/agent/memory_ranking.py",
     ["memory", "ranking"]),
    ("Memory privacy rule: passwords, API keys, tokens, cookies, private keys "
     "and auth secrets are refused before storage; PII is flagged sensitive.",
     MemorySource.PROJECT_FILE, "backend/agent/memory_api.py",
     ["memory", "privacy"]),
    ("Memory conflicts: newer explicit corrections supersede older values "
     "while history is preserved; low-confidence text never overwrites "
     "HIGH-confidence facts.",
     MemorySource.PROJECT_FILE, "backend/agent/memory_api.py",
     ["memory", "conflicts"]),
    ("Agent loop order: USER INPUT -> UNDERSTAND -> MEMORY RETRIEVAL -> PLAN "
     "-> ACT -> OBSERVE -> VERIFY -> MEMORY UPDATE; verified task outcomes "
     "are stored as episodic memories.",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md P2.2 + backend/agent/core.py",
     ["architecture", "agent-loop"]),
    ("Planner fast paths: rules-first planning and DDG-first search keep "
     "small tasks at ~1s; LLM planning has a 30s cap (PLAN_LLM_TIMEOUT_S).",
     MemorySource.PROJECT_FILE, "IMPLEMENTATION_PLAN.md §7 + backend/agent/planner.py",
     ["architecture", "planner", "performance"]),
]


def seed_project_memory(api=None) -> Dict[str, Any]:
    """Write curated project facts (idempotent). Returns counts."""
    if api is None:
        from backend.agent.memory_api import get_default_api

        api = get_default_api(project_id=PROJECT_ID)
    added = 0
    deduped = 0
    refused = 0
    for content, source, reference, tags in _SEED_FACTS:
        try:
            result = api.add(content, memory_type=MemoryType.PROJECT,
                             source=source, project_id=PROJECT_ID,
                             confidence=Confidence.HIGH, tags=list(tags),
                             source_reference=reference)
        except Exception:
            refused += 1
            continue
        status = result.get("status")
        if status == "success" and result.get("deduped"):
            deduped += 1
        elif status == "success":
            added += 1
        else:
            refused += 1
    return {"status": "success", "added": added, "deduped": deduped,
            "refused": refused, "total_facts": len(_SEED_FACTS)}


def get_project_overview(api=None, limit: int = 20) -> Dict[str, Any]:
    """List active project memories (newest first)."""
    if api is None:
        from backend.agent.memory_api import get_default_api

        api = get_default_api(project_id=PROJECT_ID)
    try:
        result = api.list(memory_type=MemoryType.PROJECT, project_id=PROJECT_ID,
                          limit=limit)
        return {"status": "success", "memories": result.get("memories", []),
                "count": result.get("count", 0)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}
