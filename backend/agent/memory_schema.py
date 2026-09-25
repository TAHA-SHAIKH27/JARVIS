"""Phase 2 — structured memory record for J.A.R.V.I.S.

Single source of truth for what a memory IS. Storage, ranking, API and agent
integration all build on MemoryRecord; nothing invents parallel schemas.

Memory types (stored as plain strings, never raw conversation dumps):
  working    — current-task state (short-lived, may expire)
  user       — stable user preferences / explicitly remembered facts
  project    — JARVIS architecture, decisions, capabilities, history
  episodic   — past events/tasks + their VERIFIED outcomes
  semantic   — generalized knowledge from verified interactions
  procedural — workflows / procedures / methods that worked

Sources (provenance — an unverified model statement is never auto-factual):
  explicit_user, conversation, project_file, system_observation,
  verified_task_result

Confidence: HIGH (explicit user instruction, verified result, authoritative
project file) > MEDIUM (ordinary observation) > LOW (hedged assumption).
Conflicting memories never silently overwrite — see memory_api.py.

Stdlib only. Windows 11 + Python 3.14 compatible.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class MemoryType:
    WORKING = "working"
    USER = "user"
    PROJECT = "project"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

    ALL = (WORKING, USER, PROJECT, EPISODIC, SEMANTIC, PROCEDURAL)


class MemorySource:
    EXPLICIT_USER = "explicit_user"
    CONVERSATION = "conversation"
    PROJECT_FILE = "project_file"
    SYSTEM_OBSERVATION = "system_observation"
    VERIFIED_TASK_RESULT = "verified_task_result"

    ALL = (
        EXPLICIT_USER,
        CONVERSATION,
        PROJECT_FILE,
        SYSTEM_OBSERVATION,
        VERIFIED_TASK_RESULT,
    )


class Confidence:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    ALL = (HIGH, MEDIUM, LOW)
    RANK = {LOW: 0, MEDIUM: 1, HIGH: 2}


class Sensitivity:
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"

    ALL = (PUBLIC, INTERNAL, SENSITIVE)


class MemoryStatus:
    ACTIVE = "active"
    SUPERSEDED = "superseded"  # lost a conflict; kept for provenance only
    EXPIRED = "expired"  # past `expiration`; excluded from retrieval

    ALL = (ACTIVE, SUPERSEDED, EXPIRED)


DEFAULT_PROJECT_ID = "jarvis"

# Stable memories never expire unless the caller says so. Working/episodic
# callers may pass an explicit `expiration`; the API never invents one for
# user/project/semantic/procedural records.
DEFAULT_IMPORTANCE = {
    MemoryType.WORKING: 0.5,
    MemoryType.USER: 0.85,
    MemoryType.PROJECT: 0.8,
    MemoryType.EPISODIC: 0.7,
    MemoryType.SEMANTIC: 0.6,
    MemoryType.PROCEDURAL: 0.7,
}

# Confidence default by provenance. Explicit user words and verified task
# results outrank assumptions — never the reverse.
DEFAULT_CONFIDENCE = {
    MemorySource.EXPLICIT_USER: Confidence.HIGH,
    MemorySource.VERIFIED_TASK_RESULT: Confidence.HIGH,
    MemorySource.PROJECT_FILE: Confidence.HIGH,
    MemorySource.CONVERSATION: Confidence.MEDIUM,
    MemorySource.SYSTEM_OBSERVATION: Confidence.MEDIUM,
}


def utc_now_s() -> float:
    return time.time()


def new_id() -> str:
    return str(uuid.uuid4())


def content_fingerprint(content: str) -> str:
    """Stable id for dedup: sha256 of whitespace-collapsed lowercase text."""
    norm = " ".join((content or "").strip().casefold().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def summarize(content: str, max_chars: int = 200) -> str:
    text = " ".join((content or "").strip().split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


@dataclass
class MemoryRecord:
    """One structured memory. Field set matches the Phase 2 brief; names are
    kept compatible with the Phase 1 JSON store where an equivalent exists
    (id / created_at / updated_at / source)."""

    id: str = field(default_factory=new_id)
    memory_type: str = MemoryType.USER
    content: str = ""
    summary: str = ""
    importance: float = 0.85
    confidence: str = Confidence.MEDIUM
    created_at: float = field(default_factory=utc_now_s)
    updated_at: float = field(default_factory=utc_now_s)
    last_accessed: float = field(default_factory=utc_now_s)
    access_count: int = 0
    source: str = MemorySource.CONVERSATION
    source_reference: str = ""
    project_id: str = DEFAULT_PROJECT_ID
    tags: List[str] = field(default_factory=list)
    embedding_id: str = ""
    status: str = MemoryStatus.ACTIVE
    sensitivity: str = Sensitivity.INTERNAL
    expiration: Optional[float] = None

    def __post_init__(self) -> None:
        self.memory_type = (self.memory_type or MemoryType.USER).strip().lower()
        if self.memory_type not in MemoryType.ALL:
            raise ValueError(f"unknown memory_type: {self.memory_type!r}")
        self.source = (self.source or MemorySource.CONVERSATION).strip()
        if self.source not in MemorySource.ALL:
            raise ValueError(f"unknown source: {self.source!r}")
        self.confidence = (self.confidence or Confidence.MEDIUM).strip().upper()
        if self.confidence not in Confidence.ALL:
            raise ValueError(f"unknown confidence: {self.confidence!r}")
        self.status = (self.status or MemoryStatus.ACTIVE).strip().lower()
        if self.status not in MemoryStatus.ALL:
            raise ValueError(f"unknown status: {self.status!r}")
        self.sensitivity = (self.sensitivity or Sensitivity.INTERNAL).strip().lower()
        if self.sensitivity not in Sensitivity.ALL:
            raise ValueError(f"unknown sensitivity: {self.sensitivity!r}")
        self.content = (self.content or "").strip()
        if not self.content:
            raise ValueError("memory content cannot be empty")
        if not self.summary:
            self.summary = summarize(self.content)
        try:
            self.importance = max(0.0, min(1.0, float(self.importance)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad importance: {self.importance!r}") from exc
        for attr in ("created_at", "updated_at", "last_accessed"):
            try:
                setattr(self, attr, float(getattr(self, attr)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"bad {attr}: {getattr(self, attr)!r}") from exc
        try:
            self.access_count = max(0, int(self.access_count))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad access_count: {self.access_count!r}") from exc
        if self.expiration is not None:
            try:
                self.expiration = float(self.expiration)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"bad expiration: {self.expiration!r}") from exc
        cleaned_tags: List[str] = []
        for tag in self.tags or []:
            tag = str(tag or "").strip().lower()
            if tag and tag not in cleaned_tags:
                cleaned_tags.append(tag)
        self.tags = cleaned_tags[:32]
        self.project_id = (self.project_id or DEFAULT_PROJECT_ID).strip() or DEFAULT_PROJECT_ID
        if not self.embedding_id:
            self.embedding_id = content_fingerprint(self.content)

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.expiration is None:
            return False
        return (now if now is not None else time.time()) >= self.expiration

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        """Strict parse: raises ValueError on corrupted/invalid records so the
        store can skip + count them instead of crashing or storing garbage."""
        if not isinstance(data, dict):
            raise ValueError(f"memory record must be an object, got {type(data).__name__}")
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)
