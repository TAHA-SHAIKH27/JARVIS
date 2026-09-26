"""
Phase 1 — Model Router for J.A.R.V.I.S.

ONE router sits between the agent and all models:

  JARVIS Agent -> Model Router -> {primary | multimodal/fallback | heavy} -> Executor -> Tools

Routing considers: task type, reasoning/coding/vision/tool requirements,
latency budget, context size, model health, and FREE status. Only
FREE + validated + ENABLED registry entries are ever selected.

Fallback (bounded, no endless retries): on timeout / server error /
rate limit / unavailable model / unsupported capability / auth error, the
router records the failure in the registry and moves to the next VALIDATED
FREE candidate. Each candidate is tried at most once per request.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.model_interface import (
    BaseModelProvider,
    FailureCategory,
    ModelCapability,
    ModelError,
    ModelResponse,
)
from backend.agent.model_registry import ModelRecord, ModelRegistry, ModelStatus

# Preferred routing only — a preference, never a guarantee. If the preferred
# model is not ENABLED/FREE/healthy, the router falls through to whatever
# validated FREE model fits.
PREFERRED_PRIMARY = "z-ai/glm-5.3-flash"  # current validated default
PREFERRED_PRIMARY_NEMOTRON = "nvidia/nemotron-3-5-lightning-30b-a3b"  # target primary IF validated
PREFERRED_MULTIMODAL = "z-ai/glm-5.3-flash"

MAX_FALLBACK_ATTEMPTS = 4


@dataclass
class TaskProfile:
    """What the current task needs from a model."""

    task_type: str = "general"  # general | chat | reasoning | coding | vision | ocr | embed | rerank
    needs_reasoning: bool = False
    needs_coding: bool = False
    needs_vision: bool = False
    needs_tools: bool = False
    needs_ocr: bool = False
    max_latency_s: float = 0.0  # 0 = no budget
    min_context: int = 0
    prefer_free: bool = True


def profile_for(task_type: str, **kwargs) -> TaskProfile:
    """Convenience constructor: profile_for("vision"), profile_for("coding")."""
    tt = (task_type or "general").lower()
    return TaskProfile(
        task_type=tt,
        needs_reasoning=tt in ("reasoning", "heavy") or kwargs.get("needs_reasoning", False),
        needs_coding=tt in ("coding",) or kwargs.get("needs_coding", False),
        needs_vision=tt in ("vision", "multimodal") or kwargs.get("needs_vision", False),
        needs_tools=kwargs.get("needs_tools", False),
        needs_ocr=tt in ("ocr",) or kwargs.get("needs_ocr", False),
        max_latency_s=kwargs.get("max_latency_s", 0.0),
        min_context=kwargs.get("min_context", 0),
    )


def _required_capability(profile: TaskProfile) -> Optional[ModelCapability]:
    if profile.needs_vision:
        return ModelCapability.VISION
    if profile.needs_ocr:
        return ModelCapability.OCR
    if profile.needs_tools:
        return ModelCapability.TOOL_CALL
    if profile.task_type == "embed":
        return ModelCapability.EMBED
    if profile.task_type == "rerank":
        return ModelCapability.RERANK
    if profile.task_type == "safety":
        return ModelCapability.SAFETY
    if profile.task_type == "translation":
        return ModelCapability.TRANSLATION
    if profile.needs_coding:
        return ModelCapability.CODING
    if profile.needs_reasoning:
        return ModelCapability.REASONING
    return None


def _group_preference(profile: TaskProfile) -> List[str]:
    """Fallback-group order for a task (preferences, not guarantees)."""
    if profile.needs_vision or profile.task_type in ("multimodal",):
        return ["multimodal", "vision", "primary", "heavy", "general"]
    if profile.needs_reasoning or profile.task_type in ("reasoning", "heavy"):
        return ["heavy", "reasoning", "primary", "general"]
    if profile.needs_coding or profile.task_type == "coding":
        return ["coding", "primary", "heavy", "general"]
    if profile.needs_tools:
        return ["multimodal", "primary", "general", "heavy"]
    if profile.task_type in ("embed",):
        return ["embed", "general"]
    if profile.task_type in ("rerank",):
        return ["rerank", "general"]
    if profile.task_type in ("ocr",):
        return ["ocr", "vision", "multimodal", "general"]
    if profile.task_type in ("safety",):
        return ["safety", "general", "primary"]
    if profile.task_type in ("translation",):
        return ["general", "primary"]
    return ["primary", "general", "heavy", "multimodal"]


class ModelRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        providers: Dict[str, BaseModelProvider],
        max_fallback_attempts: int = MAX_FALLBACK_ATTEMPTS,
    ):
        self.registry = registry
        self.providers = providers
        self.max_fallback_attempts = max(1, int(max_fallback_attempts))

    # -- provider lookup -------------------------------------------------
    def _provider_for(self, record: ModelRecord) -> Optional[BaseModelProvider]:
        return self.providers.get((record.provider or "").lower())

    # -- candidate ordering ----------------------------------------------
    def candidates(self, profile: TaskProfile) -> List[ModelRecord]:
        """Ordered FREE + ENABLED + validated candidates for a profile."""
        pool = self.registry.free_enabled()
        if profile.prefer_free:
            pool = [r for r in pool if r.free_endpoint]
        cap = _required_capability(profile)
        if cap:
            pool = [r for r in pool if cap.value in (r.capabilities or [])]
        if profile.min_context:
            pool = [r for r in pool if (r.context_limit or 0) >= profile.min_context]
        if profile.max_latency_s:
            pool = [r for r in pool if not r.latency or r.latency <= profile.max_latency_s]
        # Drop circuit-broken models (5 consecutive failures = unhealthy).
        pool = [r for r in pool if r.consecutive_failures < 5]

        group_order = _group_preference(profile)
        rank = {g: i for i, g in enumerate(group_order)}

        def sort_key(r: ModelRecord):
            return (
                rank.get(r.fallback_group, 99),
                r.priority,
                r.consecutive_failures,
                r.latency or 1e9,
            )

        return sorted(pool, key=sort_key)

    def route(self, profile: TaskProfile) -> Tuple[ModelRecord, BaseModelProvider]:
        """Pick the best model + provider. Raises ModelError if none fits."""
        for record in self.candidates(profile):
            provider = self._provider_for(record)
            if provider is not None:
                return record, provider
        raise ModelError(
            "No ENABLED FREE validated model fits this task",
            FailureCategory.UNAVAILABLE,
            retryable=False,
        )

    # -- execution with bounded fallback ----------------------------------
    def generate_with_fallback(
        self,
        profile: TaskProfile,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 120,
    ) -> ModelResponse:
        """Try candidates in order; on failure record health and move on.
        Each candidate is tried at most once; at most max_fallback_attempts
        total tries. Never endlessly retries."""
        ordered = self.candidates(profile)[: self.max_fallback_attempts]
        if not ordered:
            raise ModelError(
                "No ENABLED FREE validated model available (fallback exhausted)",
                FailureCategory.UNAVAILABLE,
                retryable=False,
            )
        errors: List[Dict[str, Any]] = []
        for record in ordered:
            provider = self._provider_for(record)
            if provider is None:
                continue
            started = time.time()
            try:
                resp = provider.generate(record.model_id, messages, temperature, max_tokens, timeout_s)
                self.registry.record_success(record.model_id, time.time() - started)
                return resp
            except ModelError as e:
                self.registry.record_failure(record.model_id, e.category.value)
                errors.append({"model": record.model_id, **e.to_dict()})
                # Auth errors on one model may mean a bad key for the whole
                # provider — still try other providers, never the same model.
                continue
            except Exception as e:  # defensive: provider bug, not a model fault
                self.registry.record_failure(record.model_id, FailureCategory.UNKNOWN.value)
                errors.append(
                    {"model": record.model_id, "message": str(e)[:300], "category": "unknown"}
                )
                continue
        raise ModelError(
            f"All {len(ordered)} fallback candidates failed: {errors[:3]}",
            FailureCategory.UNAVAILABLE,
            retryable=False,
        )

    # -- health ------------------------------------------------------------
    def health_snapshot(self) -> Dict[str, Any]:
        rows = []
        for rec in self.registry.all():
            rows.append(
                {
                    "model_id": rec.model_id,
                    "status": rec.status,
                    "enabled": rec.enabled,
                    "validated": rec.validated,
                    "free": rec.free_endpoint,
                    "latency": rec.latency,
                    "last_success": rec.last_success,
                    "last_failure": rec.last_failure,
                    "failure_category": rec.failure_category,
                    "consecutive_failures": rec.consecutive_failures,
                    "rate_limits": rec.rate_limits,
                }
            )
        return {"models": rows, "summary": self.registry.summary()}

    def is_healthy(self, model_id: str) -> bool:
        rec = self.registry.get(model_id)
        if not rec:
            return False
        return (
            rec.enabled
            and rec.validated
            and rec.free_endpoint
            and rec.consecutive_failures < 5
            and rec.status == ModelStatus.ENABLED.value
        )
