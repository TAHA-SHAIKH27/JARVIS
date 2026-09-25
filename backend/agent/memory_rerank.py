"""Phase 2 — reranking, validated-model-only (graceful-off).

Phase 1 verdict: NO validated FREE reranker exists. The candidate
  llama-nemotron-rerank-vl-1b-v2
is UNVERIFIED (no live endpoint id — never invented, never enabled).

This module therefore reports `is_available() == False` on the current
registry and `rerank()` returns its input order unchanged with an honest
reason. The memory pipeline (ranking.py) treats rerank as OPTIONAL: lexical +
optional-embedding scores stand on their own.

If a future validation ENABLES a FREE rerank-capable model, this module will
use it through the single NvidiaProvider abstraction with the correct
protocol — no code changes needed in callers. Until then, nothing here hits
the network or fakes a rerank.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

RERANK_CANDIDATE_UNVERIFIED = "llama-nemotron-rerank-vl-1b-v2"


def validated_rerank_model_id() -> Optional[str]:
    """Registry-checked rerank model id, or None when unavailable (expected)."""
    try:
        from backend.agent import model_factory

        registry, _providers, _router = model_factory.build_router()
        for record in registry.free_enabled():
            if "rerank" not in (record.capabilities or []):
                continue
            return record.model_id
        return None
    except Exception:
        return None


def is_available() -> bool:
    """True only when a validated FREE rerank model is registry-ENABLED."""
    return validated_rerank_model_id() is not None


def rerank(query: str, passages: List[str], timeout_s: int = 60) -> Dict[str, Any]:
    """Rerank passages for a query. Optional stage — safe to skip.

    Returns {"used": bool, "order": [indices best-first], "model"/"reason"}.
    When unavailable (current state), order is the input order and used=False.
    Never raises, never invents scores."""
    passages = list(passages or [])
    if not passages:
        return {"used": False, "order": [], "reason": "no passages"}
    model_id = validated_rerank_model_id()
    if model_id is None:
        return {"used": False, "order": list(range(len(passages))),
                "reason": f"no validated FREE reranker ENABLED "
                          f"({RERANK_CANDIDATE_UNVERIFIED} is UNVERIFIED); "
                          f"lexical ranking only"}
    try:
        from backend.agent import model_factory

        _registry, providers, _router = model_factory.build_router()
        provider = providers.get("nvidia")
        if provider is None:
            return {"used": False, "order": list(range(len(passages))),
                    "reason": "nvidia provider not configured"}
        result = provider.rerank(model_id, query, passages, timeout_s=timeout_s)
        rankings = result.get("rankings")
        order: List[int] = []
        if isinstance(rankings, list):
            for entry in rankings:
                if isinstance(entry, dict) and "index" in entry:
                    try:
                        order.append(int(entry["index"]))
                    except (TypeError, ValueError):
                        continue
        if sorted(order) != list(range(len(passages))):
            return {"used": False, "order": list(range(len(passages))),
                    "reason": "reranker returned unusable ranking"}
        return {"used": True, "order": order, "model": model_id}
    except Exception as exc:
        return {"used": False, "order": list(range(len(passages))),
                "reason": f"rerank failed: {str(exc)[:160]}"}
