"""Phase 2 — embeddings, validated-model-only.

ONLY the Phase 1 validated embedding model may be used:
  nvidia/llama-nemotron-embed-vl-1b-v2   (ENABLED, FREE, validated live with
  input_type=passage protocol; see model_registry_store.json)

Explicitly FORBIDDEN (UNVERIFIED in Phase 1 — never invent availability):
  llama-3_2-nemoretriever-300m-embed-v1, nv-embed-v1, nv-embedcode-7b-v1,
  or anything not ENABLED+validated+FREE in the registry.

Rules:
- `is_available()` checks the REGISTRY only — it never hits the network, so
  offline behavior is identical to online-without-key.
- Real embedding calls use the correct asymmetric protocol: input_type="query"
  for the question, input_type="passage" for documents to index.
- Any runtime failure degrades to lexical ranking (ranking.py) — memory
  retrieval NEVER hard-depends on the network.
- No local model downloads. Small in-memory vector cache only.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Optional

VALIDATED_EMBED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2"

FORBIDDEN_EMBED_MODELS = frozenset({
    "llama-3_2-nemoretriever-300m-embed-v1",
    "nvidia/llama-3_2-nemoretriever-300m-embed-v1",
    "nv-embed-v1",
    "nvidia/nv-embed-v1",
    "nv-embedcode-7b-v1",
    "nvidia/nv-embedcode-7b-v1",
})

_CACHE: Dict[str, List[float]] = {}
_CACHE_LOCK = threading.RLock()
_CACHE_MAX = 512


def _cache_get(key: str) -> Optional[List[float]]:
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _cache_put(key: str, vector: List[float]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)), None)
        _CACHE[key] = vector


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def validated_embed_model_id() -> Optional[str]:
    """Registry-checked embed model id, or None when unavailable.

    Returns the id ONLY if the registry reports it ENABLED + validated + FREE
    with embed capability. Anything else (including the UNVERIFIED candidates)
    yields None — the caller must use lexical ranking instead."""
    try:
        from backend.agent import model_factory

        registry, _providers, _router = model_factory.build_router()
        for record in registry.free_enabled():
            if "embed" not in (record.capabilities or []):
                continue
            if record.model_id in FORBIDDEN_EMBED_MODELS:
                continue
            if record.model_id == VALIDATED_EMBED_MODEL:
                return record.model_id
        return None
    except Exception:
        return None


def is_available() -> bool:
    """True only when a validated FREE embed model is registry-ENABLED."""
    return validated_embed_model_id() is not None


def embed_texts(texts: List[str], input_type: str = "passage",
                timeout_s: int = 60) -> Dict[str, Any]:
    """Embed via the validated NVIDIA model with the correct protocol.

    input_type: "query" for questions, "passage" for documents to index.
    Returns {"used": True, "model", "vectors", "dim"} on success, or
    {"used": False, "reason"} — never raises, never fakes vectors."""
    clean = [(t or "").strip() for t in (texts or [])]
    if not any(clean):
        return {"used": False, "reason": "no input text"}
    if input_type not in ("query", "passage"):
        input_type = "passage"
    model_id = validated_embed_model_id()
    if model_id is None:
        return {"used": False,
                "reason": "no validated FREE embedding model ENABLED in registry"}
    try:
        from backend.agent import model_factory

        _registry, providers, _router = model_factory.build_router()
        provider = providers.get("nvidia")
        if provider is None:
            return {"used": False, "reason": "nvidia provider not configured"}
        vectors: List[List[float]] = []
        uncached: List[str] = []
        uncached_idx: List[int] = []
        for i, text in enumerate(clean):
            key = f"{model_id}\x00{input_type}\x00{text[:2000]}"
            hit = _cache_get(key)
            vectors.append(hit if hit is not None else [])
            if hit is None:
                uncached.append(text[:2000] or " ")
                uncached_idx.append(i)
        if uncached:
            result = provider.embed(model_id, uncached, timeout_s=timeout_s,
                                    input_type=input_type)
            fresh = result.get("embeddings") or []
            if len(fresh) != len(uncached):
                return {"used": False, "reason": "embedding count mismatch"}
            for text, idx, vec in zip(uncached, uncached_idx, fresh):
                if not isinstance(vec, list) or not vec:
                    return {"used": False, "reason": "empty embedding vector"}
                key = f"{model_id}\x00{input_type}\x00{text[:2000]}"
                _cache_put(key, list(vec))
                vectors[idx] = list(vec)
        dim = len(vectors[0]) if vectors and vectors[0] else 0
        return {"used": True, "model": model_id, "vectors": vectors, "dim": dim}
    except Exception as exc:
        return {"used": False, "reason": f"embedding failed: {str(exc)[:160]}"}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
