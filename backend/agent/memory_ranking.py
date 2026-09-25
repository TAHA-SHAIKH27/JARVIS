"""Phase 2 — explainable memory ranking.

Relevance blends (weights sum to 1.0; semantic dominates and can never be
drowned by metadata):

  semantic    0.50  cosine(query_vec, mem_vec) when both exist,
                    else token-overlap score on content+summary+tags
  importance  0.15  record.importance (explicit preferences rank higher)
  confidence  0.10  HIGH=1.0 / MEDIUM=0.6 / LOW=0.3
  recency     0.10  1/(1+age_days/30) on updated_at
  frequency   0.05  min(access_count,10)/10
  project     0.05  1.0 when project_id matches, else 0.3
  type        0.03  small prior (user/project > episodic/procedural >
                    semantic > working)
  explicit    0.02  bonus for source == explicit_user

Every scored hit carries `explain` metadata (why retrieved, source,
confidence, timestamp, relevance parts, memory type) — never hidden
chain-of-thought. `rank()` also enforces the context budget: total injected
chars are capped so retrieval respects prompt limits.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.memory_embeddings import cosine_similarity
from backend.agent.memory_schema import Confidence, MemorySource, MemoryType
from backend.agent.memory_store import MemoryStore

W_SEMANTIC = 0.50
W_IMPORTANCE = 0.15
W_CONFIDENCE = 0.10
W_RECENCY = 0.10
W_FREQUENCY = 0.05
W_PROJECT = 0.05
W_TYPE = 0.03
W_EXPLICIT = 0.02

CONFIDENCE_SCORE = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.6, Confidence.LOW: 0.3}

TYPE_PRIOR = {
    MemoryType.USER: 1.0,
    MemoryType.PROJECT: 0.9,
    MemoryType.EPISODIC: 0.7,
    MemoryType.PROCEDURAL: 0.7,
    MemoryType.SEMANTIC: 0.6,
    MemoryType.WORKING: 0.5,
}

_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our",
    "please", "so", "that", "the", "their", "them", "then", "there", "they",
    "this", "to", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your", "about", "know",
})


def tokens(text: str) -> frozenset:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", (text or "").casefold())
                     if t not in _STOP and len(t) > 1)


def lexical_score(query: str, content: str, summary: str, tags: List[str]) -> float:
    """Token-overlap semantic fallback in [0,1]. Key-phrase hits count extra."""
    qtok = tokens(query)
    if not qtok:
        return 0.0
    hay = f"{content} {summary} {' '.join(tags or [])}"
    htok = tokens(hay)
    if not htok:
        return 0.0
    overlap = len(qtok & htok)
    base = overlap / max(1, len(qtok))
    # exact key-phrase presence (e.g. "favorite color" in query) boosts recall
    phrase_boost = 0.0
    lowered = (query or "").casefold()
    for phrase in (" ".join(tags or []), (summary or "").casefold()):
        if phrase and len(phrase) > 3 and phrase in lowered:
            phrase_boost = 0.25
            break
    return max(0.0, min(1.0, base + phrase_boost))


def recency_score(updated_at: float, now: Optional[float] = None) -> float:
    now = now if now is not None else time.time()
    try:
        age_days = max(0.0, (now - float(updated_at)) / 86400.0)
    except (TypeError, ValueError):
        return 0.5
    return 1.0 / (1.0 + age_days / 30.0)


def score_record(query: str, record: Any, query_vector: Optional[List[float]] = None,
                 mem_vector: Optional[List[float]] = None,
                 project_id: str = "", now: Optional[float] = None) -> Tuple[float, Dict[str, Any]]:
    if query_vector and mem_vector:
        semantic = (cosine_similarity(query_vector, mem_vector) + 1.0) / 2.0
        semantic_kind = "cosine"
    else:
        semantic = lexical_score(query, record.content, record.summary,
                                 list(record.tags or []))
        semantic_kind = "lexical"
    confidence = CONFIDENCE_SCORE.get(record.confidence, 0.6)
    recency = recency_score(record.updated_at, now)
    frequency = min(max(0, int(record.access_count or 0)), 10) / 10.0
    project = 1.0 if (project_id and record.project_id == project_id) else (
        0.6 if not project_id else 0.3)
    type_prior = TYPE_PRIOR.get(record.memory_type, 0.5)
    explicit = 1.0 if record.source == MemorySource.EXPLICIT_USER else 0.0
    total = (W_SEMANTIC * semantic + W_IMPORTANCE * float(record.importance)
             + W_CONFIDENCE * confidence + W_RECENCY * recency
             + W_FREQUENCY * frequency + W_PROJECT * project
             + W_TYPE * type_prior + W_EXPLICIT * explicit)
    explain = {
        "semantic": round(semantic, 4), "semantic_kind": semantic_kind,
        "importance": round(float(record.importance), 4),
        "confidence": record.confidence, "recency": round(recency, 4),
        "frequency": round(frequency, 4), "project": round(project, 4),
        "memory_type": record.memory_type, "type_prior": type_prior,
        "explicit": bool(explicit), "source": record.source,
        "total": round(total, 4),
    }
    return total, explain


def rank(query: str, records: List[Any], store: Optional[MemoryStore] = None,
         query_vector: Optional[List[float]] = None, project_id: str = "",
         limit: int = 8, max_chars: int = 2000,
         rerank_order: Optional[List[int]] = None) -> Dict[str, Any]:
    """Order candidates best-first, apply optional rerank pass, cap context.

    Returns {"hits": [{"record","score","explain"}], "dropped",
             "rerank_applied", "budget_chars"}. `rerank_order` (from
    memory_rerank) reorders the top slice when the reranker was used; ranking
    never depends on it being present."""
    now = time.time()
    scored: List[Tuple[float, Dict[str, Any], Any]] = []
    vectors: Dict[str, List[float]] = {}
    if store is not None and query_vector:
        for record in records:
            try:
                emb = store.get_embedding(record.id)
                vec = emb.get("vector") or []
                if vec:
                    vectors[record.id] = vec
            except Exception:
                continue
    for record in records:
        total, explain = score_record(query, record, query_vector,
                                      vectors.get(record.id), project_id, now)
        scored.append((total, explain, record))
    scored.sort(key=lambda e: (e[0], getattr(e[2], "updated_at", 0)), reverse=True)
    rerank_applied = False
    if rerank_order and len(rerank_order) == len(scored):
        try:
            scored = [scored[i] for i in rerank_order
                      if 0 <= i < len(scored)]
            rerank_applied = True
        except (TypeError, IndexError):
            rerank_applied = False
    limit = max(1, min(int(limit or 8), 50))
    hits: List[Dict[str, Any]] = []
    used_chars = 0
    dropped = 0
    for total, explain, record in scored:
        if len(hits) >= limit:
            dropped += len(scored) - len(hits)
            break
        size = len(record.content or "") + len(record.summary or "") + 64
        if hits and used_chars + size > max_chars:
            dropped += 1
            continue
        used_chars += size
        hits.append({"record": record, "score": round(total, 4), "explain": explain})
    return {"hits": hits, "dropped": dropped, "rerank_applied": rerank_applied,
            "budget_chars": max_chars, "used_chars": used_chars}
