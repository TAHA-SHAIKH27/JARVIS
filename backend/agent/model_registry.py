"""
Phase 1 — Central model registry for J.A.R.V.I.S.

Single source of truth for every known model: required record fields,
lifecycle statuses, health tracking, and FREE-only filtering. An entry is
usable by the router only when it is ENABLED, and ENABLED requires a real
runtime validation on a FREE endpoint (listing alone never enables).

Persisted to JSON so validation evidence survives restarts.
"""
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STORE_PATH = os.path.join(_WORKSPACE_ROOT, "backend", "agent", "model_registry_store.json")


class ModelStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    VALIDATED = "VALIDATED"
    ENABLED = "ENABLED"
    UNAVAILABLE = "UNAVAILABLE"
    DEPRECATED = "DEPRECATED"
    PAID_OR_PARTNER_ONLY = "PAID_OR_PARTNER_ONLY"
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    CAPABILITY_FAILED = "CAPABILITY_FAILED"
    UNVERIFIED = "UNVERIFIED"
    DISABLED = "DISABLED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ModelRecord:
    """One registry row. Field names match the Phase 1 brief exactly."""

    model_id: str
    provider: str = ""
    display_name: str = ""
    free_endpoint: bool = False
    status: str = ModelStatus.DISCOVERED.value
    enabled: bool = False
    validated: bool = False
    capabilities: List[str] = field(default_factory=list)
    context_limit: int = 0
    priority: int = 100
    fallback_group: str = "general"
    last_validated: Optional[str] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    latency: float = 0.0
    # health extras
    consecutive_failures: int = 0
    failure_category: str = ""
    rate_limits: int = 0
    validation_time: Optional[str] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class ModelRegistry:
    """Thread-safe in-memory registry with JSON persistence."""

    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self._store_path = store_path
        self._lock = threading.Lock()
        self._models: Dict[str, ModelRecord] = {}
        self.load()

    # -- CRUD ----------------------------------------------------------
    def register(self, record: ModelRecord) -> ModelRecord:
        with self._lock:
            existing = self._models.get(record.model_id)
            if existing:
                # Merge: keep live health/validation evidence, refresh metadata.
                existing.provider = record.provider or existing.provider
                existing.display_name = record.display_name or existing.display_name
                if record.capabilities:
                    existing.capabilities = record.capabilities
                if record.context_limit:
                    existing.context_limit = record.context_limit
                if record.priority != 100:
                    existing.priority = record.priority
                if record.fallback_group != "general":
                    existing.fallback_group = record.fallback_group
                if record.note:
                    existing.note = record.note
                return existing
            self._models[record.model_id] = record
            return record

    def get(self, model_id: str) -> Optional[ModelRecord]:
        with self._lock:
            return self._models.get(model_id)

    def all(self) -> List[ModelRecord]:
        with self._lock:
            return list(self._models.values())

    def set_status(self, model_id: str, status: ModelStatus, note: str = "") -> Optional[ModelRecord]:
        with self._lock:
            rec = self._models.get(model_id)
            if not rec:
                return None
            rec.status = status.value
            if note:
                rec.note = note
            if status == ModelStatus.ENABLED:
                rec.enabled = True
            elif status in (
                ModelStatus.UNAVAILABLE,
                ModelStatus.DEPRECATED,
                ModelStatus.PAID_OR_PARTNER_ONLY,
                ModelStatus.AUTH_ERROR,
                ModelStatus.DISABLED,
            ):
                rec.enabled = False
            return rec

    def set_enabled(self, model_id: str, enabled: bool, note: str = "") -> Optional[ModelRecord]:
        """Enable only if FREE + validated. Returns None on refusal."""
        with self._lock:
            rec = self._models.get(model_id)
            if not rec:
                return None
            if enabled and not (rec.free_endpoint and rec.validated):
                return None
            rec.enabled = enabled
            if note:
                rec.note = note
            if enabled:
                rec.status = ModelStatus.ENABLED.value
            elif rec.status == ModelStatus.ENABLED.value:
                rec.status = ModelStatus.VALIDATED.value if rec.validated else ModelStatus.DISABLED.value
            return rec

    # -- health --------------------------------------------------------
    def record_success(self, model_id: str, latency_s: float = 0.0) -> None:
        with self._lock:
            rec = self._models.get(model_id)
            if not rec:
                return
            rec.last_success = _utc_now()
            rec.latency = latency_s
            rec.consecutive_failures = 0
            rec.failure_category = ""

    def record_failure(self, model_id: str, category: str = "") -> None:
        with self._lock:
            rec = self._models.get(model_id)
            if not rec:
                return
            rec.last_failure = _utc_now()
            rec.consecutive_failures += 1
            rec.failure_category = category
            if category == "rate_limited":
                rec.rate_limits += 1

    def mark_validated(
        self,
        model_id: str,
        latency_s: float = 0.0,
        validation_time: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Optional[ModelRecord]:
        with self._lock:
            rec = self._models.get(model_id)
            if not rec:
                return None
            rec.validated = True
            rec.status = ModelStatus.VALIDATED.value
            rec.last_validated = _utc_now()
            rec.validation_time = validation_time or rec.last_validated
            rec.latency = latency_s
            if capabilities:
                rec.capabilities = capabilities
            return rec

    # -- FREE-only filtering -------------------------------------------
    def free_enabled(self) -> List[ModelRecord]:
        """Models the router may use: ENABLED + validated + FREE endpoint."""
        with self._lock:
            return [
                r
                for r in self._models.values()
                if r.enabled
                and r.validated
                and r.free_endpoint
                and r.status == ModelStatus.ENABLED.value
            ]

    def by_group(self, group: str, free_only: bool = True) -> List[ModelRecord]:
        pool = self.free_enabled() if free_only else self.all()
        return sorted(
            [r for r in pool if r.fallback_group == group],
            key=lambda r: (r.priority, r.latency),
        )

    # -- persistence ---------------------------------------------------
    def save(self) -> None:
        try:
            with self._lock:
                payload = {"updated_at": _utc_now(), "models": [m.to_dict() for m in self._models.values()]}
            tmp = self._store_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self._store_path)
        except Exception:
            pass

    def load(self) -> None:
        try:
            if not os.path.isfile(self._store_path):
                return
            with open(self._store_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            for item in payload.get("models", []):
                rec = ModelRecord.from_dict(item)
                self._models[rec.model_id] = rec
        except Exception:
            pass

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            by_status: Dict[str, int] = {}
            for rec in self._models.values():
                by_status[rec.status] = by_status.get(rec.status, 0) + 1
            return {
                "total": len(self._models),
                "by_status": by_status,
                "free_enabled": len(
                    [
                        r
                        for r in self._models.values()
                        if r.enabled and r.validated and r.free_endpoint
                    ]
                ),
            }
