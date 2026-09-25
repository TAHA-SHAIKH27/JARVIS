"""Phase 2 — clean internal memory interface for J.A.R.V.I.S.

Everything in JARVIS talks to memory through JarvisMemory — never by touching
SQLite/JSON directly:

  add / search / retrieve / update / delete / forget / list / explain
  + remember / handle_explicit_command / memory_context / purge_expired

Behavior contract (matches the Phase 2 brief):
- Provenance: every record carries source + source_reference; unverified model
  text (LOW/MEDIUM, non-explicit) never outranks explicit user words or
  verified task results.
- Privacy: passwords / API keys / tokens / cookies / private keys / auth
  secrets are REFUSED before storage (never written anywhere). Other PII
  (email/phone) is stored only flagged `sensitive`.
- Dedup: exact or near-duplicate adds consolidate into the existing record.
- Conflicts: same topic + different value → higher-authority newcomer
  SUPERSEDES the old record (history preserved, excluded from retrieval);
  low-authority text conflicting with HIGH fact is refused with an
  explanation instead of stored.
- Expiration: working/episodic callers may pass expires_in_s/expiration;
  stable memories never expire unless asked. `mark_expired` runs on every
  read path; `purge_expired` reports the count.
- `forget()` is a hard DELETE — no tombstones, no hidden retention.
- Retrieval pipeline: query → candidates → relevance → optional embedding →
  optional rerank → confidence/importance/recency → project relevance →
  selection, capped by a context budget. Embeddings/rerank degrade gracefully
  (lexical ranking stands alone).

Stdlib only. Tests inject an isolated MemoryStore (JARVIS_MEMORY_DB).
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from backend.agent import memory_embeddings, memory_ranking, memory_rerank
from backend.agent.memory_schema import (
    DEFAULT_CONFIDENCE,
    DEFAULT_IMPORTANCE,
    DEFAULT_PROJECT_ID,
    Confidence,
    MemoryRecord,
    MemorySource,
    MemoryStatus,
    MemoryType,
    Sensitivity,
    content_fingerprint,
    summarize,
)
from backend.agent.memory_store import MemoryStore

_LOCK = threading.RLock()
_DEFAULT_STORE: Optional[MemoryStore] = None
_MIGRATED = False

# -- privacy ---------------------------------------------------------------
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", re.I),
    re.compile(r"\bpassword\s*[:=]\s*\S+", re.I),
    re.compile(r"\bpasswd\s*[:=]\s*\S+", re.I),
    re.compile(r"\bapi[_-]?key\s*[:=]\s*\S+", re.I),
    re.compile(r"\baccess[_-]?token\s*[:=]\s*\S+", re.I),
    re.compile(r"\bbearer\s+[A-Za-z0-9\-._~+/]+", re.I),
    re.compile(r"\bsecret\s*[:=]\s*\S+", re.I),
    re.compile(r"nvapi-[A-Za-z0-9_\-]+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}", re.I),
    re.compile(r"\bghp_[A-Za-z0-9]{8,}", re.I),
    re.compile(r"\bxox[bap]-[A-Za-z0-9\-]+", re.I),
    re.compile(r"\bcookie\s*[:=]\s*\S+", re.I),
    re.compile(r"\bauth[_-]?token\s*[:=]\s*\S+", re.I),
]

_PII_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\+?\d[\d\s\-().]{7,}\d"),
]


def contains_secret(text: str) -> Optional[str]:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text or ""):
            return "authentication secret or credential"
    return None


def classify_sensitivity(text: str, source: str) -> str:
    lowered = (text or "").casefold()
    if any(p.search(text or "") for p in _PII_PATTERNS):
        return Sensitivity.SENSITIVE
    if any(word in lowered for word in ("salary", "medical", "diagnosis", "ssn ")):
        return Sensitivity.SENSITIVE
    return Sensitivity.INTERNAL


# -- topic key (conflict/dedup scope) ---------------------------------------
_KEY_VALUE_RE = re.compile(r"^([a-z0-9][a-z0-9\s'_\-/]{1,60}?)\s*[:=]\s*(.+)$", re.I)
_MY_X_IS_Y_RE = re.compile(
    r"^(?:my|i(?:'m| am)?)\s+(.+?)\s+(?:is|are|was|were|=)\s+(.+)$", re.I)
_PREFER_RE = re.compile(r"^i\s+(?:prefer|like|love|use|own)\s+(.+)$", re.I)


def topic_key(content: str) -> str:
    """Coarse conflict scope: 'favorite color: blue' and 'my favorite color
    is red' share topic 'favorite color'. Returns '' when no topic applies."""
    text = " ".join((content or "").strip().split())
    if not text:
        return ""
    match = _KEY_VALUE_RE.match(text)
    if match:
        return re.sub(r"^(?:my|i)\s+", "", match.group(1).strip(), flags=re.I).casefold()
    match = _MY_X_IS_Y_RE.match(text)
    if match:
        key = re.sub(r"^(?:my|i)\s+", "", match.group(1).strip(), flags=re.I)
        if key:
            return key.casefold()
    match = _PREFER_RE.match(text)
    if match:
        return "preference"
    return ""


def _overlap(a: str, b: str) -> float:
    ta = memory_ranking.tokens(a)
    tb = memory_ranking.tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


# -- store singleton ---------------------------------------------------------
def get_default_store() -> MemoryStore:
    global _DEFAULT_STORE, _MIGRATED
    with _LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = MemoryStore()
        if not _MIGRATED:
            _MIGRATED = True
            try:
                if _DEFAULT_STORE.count() == 0:
                    _DEFAULT_STORE.migrate_legacy_json()
            except Exception:
                pass
        return _DEFAULT_STORE


class JarvisMemory:
    """The single memory façade. `store=None` selects the default SQLite DB."""

    def __init__(self, store: Optional[MemoryStore] = None,
                 project_id: str = DEFAULT_PROJECT_ID):
        self.store = store or get_default_store()
        self.project_id = (project_id or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID

    # -- add -----------------------------------------------------------------
    def add(self, content: str, memory_type: str = MemoryType.USER,
            source: str = MemorySource.CONVERSATION,
            project_id: str = "", importance: Optional[float] = None,
            confidence: Optional[str] = None, tags: Optional[List[str]] = None,
            sensitivity: str = "", expiration: Optional[float] = None,
            expires_in_s: Optional[float] = None,
            source_reference: str = "") -> Dict[str, Any]:
        content = (content or "").strip()
        if not content:
            return {"status": "error", "message": "Memory content cannot be empty."}
        secret = contains_secret(content) or contains_secret(source_reference)
        if secret:
            return {"status": "refused",
                    "message": f"Not stored: looks like {secret}. "
                               "JARVIS never stores passwords, API keys, tokens, "
                               "cookies, private keys or auth secrets."}
        memory_type = (memory_type or MemoryType.USER).strip().lower()
        if memory_type not in MemoryType.ALL:
            return {"status": "error", "message": f"Unknown memory type: {memory_type}"}
        source = (source or MemorySource.CONVERSATION).strip()
        if source not in MemorySource.ALL:
            return {"status": "error", "message": f"Unknown source: {source}"}
        project = (project_id or self.project_id).strip() or self.project_id
        if importance is None:
            importance = DEFAULT_IMPORTANCE.get(memory_type, 0.6)
        if not confidence:
            confidence = DEFAULT_CONFIDENCE.get(source, Confidence.MEDIUM)
        if not sensitivity:
            sensitivity = classify_sensitivity(content, source)
        if expires_in_s is not None:
            try:
                expiration = time.time() + max(0.0, float(expires_in_s))
            except (TypeError, ValueError):
                return {"status": "error", "message": "Bad expires_in_s."}
        # Stable memories must not silently gain an expiration.
        if expiration is not None and memory_type in (
                MemoryType.USER, MemoryType.PROJECT, MemoryType.SEMANTIC,
                MemoryType.PROCEDURAL):
            pass  # explicit caller choice is honored; nothing invented here

        with _LOCK:
            self.store.mark_expired()
            # 1. Exact dedup: same fingerprint, type, project → touch + return.
            fingerprint = content_fingerprint(content)
            existing = self._find_duplicate(fingerprint, content, memory_type, project)
            if existing is not None:
                merged_tags = list(dict.fromkeys(
                    list(existing.tags or []) + [str(t or "").strip().lower()
                                                 for t in (tags or []) if str(t or "").strip()]))
                updated = self.store.update(existing.id, {
                    "tags": merged_tags[:32],
                    "importance": max(float(existing.importance), float(importance)),
                    "confidence": self._stronger(existing.confidence, confidence),
                    "source_reference": source_reference or existing.source_reference,
                })
                return {"status": "success", "message": "Memory already existed; consolidated.",
                        "memory": (updated or existing).to_dict(), "deduped": True}
            # 2. Conflict: same topic key, different content.
            conflict = self._find_conflict(topic_key(content), content, memory_type, project)
            if conflict is not None:
                verdict = self._resolve_conflict(conflict, content, source, confidence,
                                                 importance, source_reference, tags,
                                                 memory_type, project)
                if verdict.get("status") != "success":
                    return verdict
                if verdict.get("conflict") == "superseded":
                    return verdict
            record = MemoryRecord(
                memory_type=memory_type, content=content, summary=summarize(content),
                importance=float(importance), confidence=confidence,
                source=source, source_reference=(source_reference or "")[:1000],
                project_id=project, tags=list(tags or []),
                sensitivity=sensitivity, expiration=expiration,
            )
            self.store.add(record)
            return {"status": "success", "message": "Memory saved.",
                    "memory": record.to_dict()}

    @staticmethod
    def _stronger(a: str, b: str) -> str:
        rank = Confidence.RANK
        return a if rank.get(a, 1) >= rank.get(b, 1) else b

    def _find_duplicate(self, fingerprint: str, content: str,
                        memory_type: str, project: str):
        rows = self.store.list(memory_type=memory_type, project_id=project,
                               status=MemoryStatus.ACTIVE, limit=200)["records"]
        for record in rows:
            if record.embedding_id == fingerprint:
                return record
            if record.content.strip().casefold() == content.strip().casefold():
                return record
            if topic_key(record.content) and topic_key(record.content) == topic_key(content):
                if _overlap(record.content, content) >= 0.9:
                    return record
        return None

    def _find_conflict(self, key: str, content: str, memory_type: str, project: str):
        if not key:
            return None
        rows = self.store.list(memory_type=memory_type, project_id=project,
                               status=MemoryStatus.ACTIVE, limit=200)["records"]
        norm = content.strip().casefold()
        for record in rows:
            if topic_key(record.content) != key:
                continue
            if record.content.strip().casefold() == norm:
                continue
            return record
        return None

    def _resolve_conflict(self, old, content: str, source: str, confidence: str,
                          importance: float, source_reference: str,
                          tags: Optional[List[str]], memory_type: str,
                          project: str) -> Dict[str, Any]:
        """Authority rule: explicit user words and verified results outrank
        everything; HIGH outranks MEDIUM/LOW; equal authority → newest wins
        but history is preserved either way. Low-authority text conflicting
        with a HIGH fact is refused, never stored."""
        new_rank = Confidence.RANK.get(confidence, 1)
        old_rank = Confidence.RANK.get(old.confidence, 1)
        new_authoritative = source in (MemorySource.EXPLICIT_USER,
                                       MemorySource.VERIFIED_TASK_RESULT)
        old_authoritative = old.source in (MemorySource.EXPLICIT_USER,
                                           MemorySource.VERIFIED_TASK_RESULT)
        if new_authoritative or new_rank > old_rank or (
                new_rank == old_rank and not old_authoritative):
            self.store.update(old.id, {"status": MemoryStatus.SUPERSEDED})
            record = MemoryRecord(
                memory_type=memory_type, content=content, summary=summarize(content),
                importance=float(importance), confidence=confidence, source=source,
                source_reference=(source_reference or
                                  f"supersedes {old.id} ({old.content[:120]})")[:1000],
                project_id=project, tags=list(tags or []),
                sensitivity=classify_sensitivity(content, source))
            self.store.add(record)
            return {"status": "success",
                    "message": f"Updated preference (previous value kept in history).",
                    "memory": record.to_dict(), "conflict": "superseded",
                    "superseded_id": old.id}
        return {"status": "refused",
                "message": f"Not stored: conflicts with a higher-confidence memory "
                           f"({old.source}, {old.confidence}): '{old.content[:120]}'. "
                           f"Say 'Correct that memory: ...' to override explicitly.",
                "conflict": "kept_existing", "existing": old.to_dict()}

    # -- search / retrieve ----------------------------------------------------
    def search(self, query: str, limit: int = 8, project_id: str = "",
               memory_types: Optional[List[str]] = None, max_chars: int = 2000,
               use_embeddings: bool = True, use_rerank: bool = True) -> Dict[str, Any]:
        query = (query or "").strip()
        project = (project_id or self.project_id).strip() or self.project_id
        limit = max(1, min(int(limit or 8), 50))
        with _LOCK:
            self.store.mark_expired()
            found = self.store.search_candidates(query, limit=50, project_id="",
                                                 memory_types=memory_types)
            records = found["records"]
            # Project relevance is a ranking signal, not a hard filter: same-
            # project hits rank higher, others still reachable.
            query_vector = None
            embed_used = False
            embed_model = ""
            if use_embeddings and query:
                try:
                    res = memory_embeddings.embed_texts([query], input_type="query",
                                                        timeout_s=15)
                    if res.get("used") and res.get("vectors"):
                        query_vector = list(res["vectors"][0])
                        embed_used = True
                        embed_model = str(res.get("model") or "")
                except Exception:
                    query_vector = None
            rerank_order = None
            rerank_used = False
            if use_rerank and query and records:
                try:
                    rr = memory_rerank.rerank(query, [r.content for r in records])
                    if rr.get("used"):
                        rerank_order = rr.get("order")
                        rerank_used = True
                except Exception:
                    rerank_order = None
            ranked = memory_ranking.rank(query, records, store=self.store,
                                         query_vector=query_vector,
                                         project_id=project, limit=limit,
                                         max_chars=max_chars,
                                         rerank_order=rerank_order)
            hits = []
            for hit in ranked["hits"]:
                record = hit["record"]
                self.store.record_access(record.id)
                hits.append({"id": record.id, "memory_type": record.memory_type,
                             "content": record.content, "summary": record.summary,
                             "score": hit["score"], "explain": self._explain_record(
                                 record, hit["explain"], query)})
            return {"status": "success", "hits": hits, "count": len(hits),
                    "dropped": ranked["dropped"], "embed_used": embed_used,
                    "embed_model": embed_model, "rerank_used": rerank_used,
                    "corrupted_skipped": found.get("corrupted_skipped", 0)}

    def retrieve(self, memory_id: str) -> Dict[str, Any]:
        with _LOCK:
            self.store.mark_expired()
            record = self.store.get((memory_id or "").strip())
            if record is None:
                return {"status": "error", "message": "Memory not found."}
            if record.status != MemoryStatus.ACTIVE or record.is_expired():
                if record.is_expired():
                    self.store.update(record.id, {"status": MemoryStatus.EXPIRED})
                return {"status": "error", "message": "Memory is no longer active."}
            self.store.record_access(record.id)
            record = self.store.get(record.id) or record
            return {"status": "success", "memory": record.to_dict(),
                    "explain": self._explain_record(record, None, "")}

    def _explain_record(self, record: MemoryRecord, rank_explain: Optional[Dict[str, Any]],
                        query: str) -> Dict[str, Any]:
        return {
            "why_retrieved": (f"matched query '{query[:80]}' with relevance "
                              f"{(rank_explain or {}).get('total', 'n/a')} "
                              f"({(rank_explain or {}).get('semantic_kind', 'stored')})"
                              if query else "direct lookup"),
            "memory_type": record.memory_type,
            "source": record.source,
            "source_reference": record.source_reference,
            "confidence": record.confidence,
            "importance": round(float(record.importance), 4),
            "created_at": record.created_at, "updated_at": record.updated_at,
            "last_accessed": record.last_accessed,
            "access_count": record.access_count,
            "relevance": (rank_explain or {}).get("total"),
            "relevance_parts": rank_explain,
            "project_id": record.project_id, "tags": record.tags,
            "status": record.status, "sensitivity": record.sensitivity,
        }

    def explain(self, memory_id: str) -> Dict[str, Any]:
        result = self.retrieve(memory_id)
        if result.get("status") != "success":
            return result
        return {"status": "success", "explain": result["explain"],
                "memory": result["memory"]}

    # -- update / delete / forget / list ---------------------------------------
    def update(self, memory_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        fields = dict(fields or {})
        for forbidden in ("id", "created_at", "embedding_id"):
            fields.pop(forbidden, None)
        if "content" in fields and contains_secret(str(fields["content"] or "")):
            return {"status": "refused",
                    "message": "Not stored: new content looks like a credential."}
        with _LOCK:
            record = self.store.get((memory_id or "").strip())
            if record is None:
                return {"status": "error", "message": "Memory not found."}
            if "content" in fields:
                new_content = str(fields["content"] or "").strip()
                if not new_content:
                    return {"status": "error", "message": "Content cannot be empty."}
                fields["summary"] = summarize(new_content)
                from backend.agent.memory_schema import content_fingerprint as _fp
                fields["embedding_id"] = _fp(new_content)
            try:
                updated = self.store.update(record.id, fields)
            except ValueError as exc:
                return {"status": "error", "message": f"Invalid update: {exc}"}
            if updated is None:
                return {"status": "error", "message": "Memory not found."}
            return {"status": "success", "message": "Memory updated.",
                    "memory": updated.to_dict()}

    def delete(self, memory_id: str) -> Dict[str, Any]:
        with _LOCK:
            ok = self.store.delete((memory_id or "").strip())
            if not ok:
                return {"status": "error", "message": "Memory not found."}
            return {"status": "success", "message": "Memory deleted.",
                    "memory_id": memory_id}

    def forget(self, target: str) -> Dict[str, Any]:
        """True forgetting: resolve an id or a natural description, then hard
        delete the match. The store retains nothing of it afterwards."""
        target = (target or "").strip()
        if not target:
            return {"status": "error", "message": "Nothing to forget."}
        with _LOCK:
            if self.store.get(target) is not None:
                self.store.delete(target)
                return {"status": "success",
                        "message": "Forgotten, sir. That memory is fully removed.",
                        "memory_id": target}
            found = self.store.search_candidates(target, limit=5)["records"]
            same_project = [r for r in found if r.project_id == self.project_id]
            pool = same_project or found
            if not pool:
                return {"status": "error",
                        "message": "I have no memory matching that, sir."}
            best = max(pool, key=lambda r: (memory_ranking.lexical_score(
                target, r.content, r.summary, list(r.tags or [])), r.updated_at))
            self.store.delete(best.id)
            return {"status": "success",
                    "message": f"Forgotten, sir: '{best.content[:120]}' is fully removed.",
                    "memory_id": best.id, "forgotten": best.to_dict()}

    def list(self, memory_type: str = "", project_id: str = "",
             limit: int = 100) -> Dict[str, Any]:
        with _LOCK:
            self.store.mark_expired()
            project = (project_id or self.project_id).strip() or self.project_id
            # Default scope is this project; "" project_id lists everything.
            result = self.store.list(memory_type=memory_type.strip().lower() if memory_type else "",
                                     project_id=project if project_id != "" else project,
                                     status=MemoryStatus.ACTIVE, limit=limit)
            return {"status": "success",
                    "memories": [r.to_dict() for r in result["records"]],
                    "count": result["count"],
                    "corrupted_skipped": result.get("corrupted_skipped", 0)}

    def purge_expired(self) -> Dict[str, Any]:
        with _LOCK:
            count = self.store.mark_expired()
            return {"status": "success", "expired": count}

    # -- convenience ------------------------------------------------------------
    def remember(self, text: str, memory_type: str = MemoryType.USER,
                 project_id: str = "", importance: Optional[float] = None,
                 tags: Optional[List[str]] = None,
                 expires_in_s: Optional[float] = None) -> Dict[str, Any]:
        return self.add(text, memory_type=memory_type, source=MemorySource.EXPLICIT_USER,
                        project_id=project_id, importance=importance,
                        confidence=Confidence.HIGH, tags=tags,
                        source_reference=text[:500], expires_in_s=expires_in_s)

    def memory_context(self, query: str = "", limit: int = 8,
                       max_chars: int = 2000) -> str:
        """Compact memory facts for prompt injection (context-limited)."""
        try:
            result = self.search(query, limit=limit, max_chars=max_chars,
                                 use_embeddings=False, use_rerank=False)
        except Exception:
            return "No stored memories relevant to this task."
        hits = result.get("hits", [])
        if not hits:
            return "No stored memories relevant to this task."
        lines = [f"- [{h['memory_type']}/{h['explain']['source']}] {h['content']}"
                 for h in hits]
        return "\n".join(lines)

    # -- explicit natural-language controls --------------------------------------
    _REMEMBER_LEAD = re.compile(
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:i\s+want\s+you\s+to\s+)?"
        r"(?:remember\s+(?:that|this:?)?|don't\s+forget\s+(?:that\s+)?|do\s+not\s+forget\s+(?:that\s+)?|"
        r"keep\s+in\s+mind\s+(?:that\s+)?|save\s+(?:this\s+)?to\s+memory:?|note\s+(?:that\s+)?|note:?)\s*",
        re.I)
    _DONT_REMEMBER_LEAD = re.compile(
        r"^(?:do\s+not|don't|never)\s+(?:remember|save|store|keep)\s+(?:this:?|that:?|it:?)?\s*", re.I)
    _FORGET_LEAD = re.compile(
        r"^(?:please\s+)?(?:forget\s+(?:that\s+|this\s+|it\s+)?|delete\s+(?:the\s+)?memory\s+(?:of|about|that)?|"
        r"remove\s+(?:the\s+)?memory\s+(?:of|about)?|erase\s+(?:the\s+)?memory\s+(?:of|about)?)\s*", re.I)
    _CORRECT_LEAD = re.compile(
        r"^(?:correct\s+(?:that\s+)?memory:?|actually,?\s*|no,?\s+I\s+meant:?)\s*", re.I)
    _WHAT_REMEMBER = re.compile(
        r"what\s+do\s+you\s+remember\s+(?:about\s+(?:me|us|this\s+project|the\s+project)?|.*)?$", re.I)
    _SHOW_REMEMBER = re.compile(r"show\s+me\s+(?:relevant\s+)?memories?\s*(?:about\s+(.*))?$", re.I)

    def handle_explicit_command(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse remember/forget/correct/show requests. Returns None when the
        text is not a memory command (caller continues normal processing)."""
        raw = (text or "").strip()
        if not raw:
            return None
        lowered = raw.casefold()

        if self._WHAT_REMEMBER.search(lowered) or lowered.strip() in (
                "what do you remember?", "what do you remember about me?",
                "what do you remember about me"):
            scope = MemoryType.PROJECT if "project" in lowered else MemoryType.USER
            result = self.list(memory_type=scope, limit=50)
            memories = result.get("memories", [])
            if not memories:
                who = "this project" if scope == MemoryType.PROJECT else "you"
                return {"action": "show",
                        "speak": f"I don't have any memories stored about {who} yet, sir.",
                        "memories": []}
            lines = "; ".join(m["content"][:120] for m in memories[:10])
            who = "this project" if scope == MemoryType.PROJECT else "you"
            return {"action": "show",
                    "speak": f"I remember {len(memories)} thing(s) about {who}, sir: {lines}.",
                    "memories": memories, "count": len(memories)}

        show_match = self._SHOW_REMEMBER.search(lowered)
        if show_match:
            topic = (show_match.group(1) or "").strip()
            result = self.search(topic or "memory", limit=8,
                                 use_embeddings=False, use_rerank=False)
            hits = result.get("hits", [])
            if not hits:
                return {"action": "show", "speak": "No relevant memories found, sir.", "hits": []}
            lines = "; ".join(h["content"][:120] for h in hits)
            return {"action": "show",
                    "speak": f"Relevant memories, sir: {lines}.",
                    "hits": hits, "count": len(hits)}

        if lowered.startswith(("correct that memory", "correct the memory", "actually,", "actually ", "no, i meant")):
            new_content = self._CORRECT_LEAD.sub("", raw).strip().rstrip(".")
            if not new_content:
                return {"action": "correct", "status": "error",
                        "speak": "Please tell me the corrected memory, sir."}
            # Route through add(): topic-conflict logic supersedes the old
            # record while preserving it as history.
            result = self.add(new_content, memory_type=MemoryType.USER,
                              source=MemorySource.EXPLICIT_USER,
                              confidence=Confidence.HIGH,
                              source_reference=raw[:500])
            if result.get("status") == "success":
                return {"action": "correct", "status": "success",
                        "speak": f"Corrected, sir. I now remember: {new_content[:160]}.",
                        **result}
            return {"action": "correct", **result,
                    "speak": result.get("message", "I could not correct that, sir.")}

        dont_match = self._DONT_REMEMBER_LEAD.match(raw)
        if dont_match or lowered.startswith(("do not remember", "don't remember", "never remember")):
            content = self._DONT_REMEMBER_LEAD.sub("", raw).strip().rstrip(".")
            if not content or len(content) < 3:
                return {"action": "ignore", "status": "success",
                        "speak": "Understood, sir — I won't store that."}
            removed = self.forget(content)
            if removed.get("status") == "success":
                return {"action": "ignore", **removed,
                        "speak": "Understood, sir — I won't remember that. "
                                 "Any matching memory has been fully removed."}
            return {"action": "ignore", "status": "success",
                    "speak": "Understood, sir — I won't store that."}

        forget_match = self._FORGET_LEAD.match(raw)
        if forget_match or lowered.startswith("forget ") or "forget everything" in lowered or \
                "forget all" in lowered or "clear memory" in lowered:
            if any(k in lowered for k in ("forget everything", "forget all", "clear memory")):
                with _LOCK:
                    existing = self.store.list(project_id=self.project_id,
                                               status=MemoryStatus.ACTIVE, limit=1000)["records"]
                    for record in existing:
                        self.store.delete(record.id)
                return {"action": "forget", "status": "success",
                        "speak": "All project memories cleared, sir. Starting fresh.",
                        "cleared": len(existing)}
            target = self._FORGET_LEAD.sub("", raw).strip().rstrip(".") if forget_match else raw[7:].strip()
            result = self.forget(target or raw)
            return {"action": "forget", **result,
                    "speak": result.get("message", result.get("speak", "Done, sir."))}

        remember_match = self._REMEMBER_LEAD.match(raw)
        if remember_match or "remember" in lowered or "don't forget" in lowered or \
                "do not forget" in lowered or "keep in mind" in lowered or "save to memory" in lowered:
            content = self._REMEMBER_LEAD.sub("", raw).strip().rstrip(".") if remember_match else raw.strip()
            if not content or len(content) < 2:
                return {"action": "remember", "status": "error",
                        "speak": "Please tell me what you want me to remember, sir."}
            result = self.remember(content)
            if result.get("status") == "success":
                return {"action": "remember", **result,
                        "speak": f"Understood, sir. I will remember that: {content[:200]}"}
            return {"action": "remember", **result,
                    "speak": result.get("message", "I could not save that, sir.")}

        return None


_default_api: Optional["JarvisMemory"] = None


def get_default_api(project_id: str = DEFAULT_PROJECT_ID) -> JarvisMemory:
    global _default_api
    with _LOCK:
        if _default_api is None or _default_api.project_id != project_id:
            _default_api = JarvisMemory(project_id=project_id)
        return _default_api


def reset_default_api() -> None:
    global _default_api, _DEFAULT_STORE, _MIGRATED
    with _LOCK:
        _default_api = None
        _DEFAULT_STORE = None
        _MIGRATED = False
