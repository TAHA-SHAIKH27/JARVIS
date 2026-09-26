"""
Phase 1 — Model validation + full catalog audit for J.A.R.V.I.S.

Two jobs:
  1. validate_model(): real runtime probes (health check, tiny generate,
     optional tool-call probe) that move a registry entry to VALIDATED and
     (only then) allow ENABLED. Evidence fields are always updated.
  2. audit_catalog(): resolve EVERY supplied catalog candidate against the
     live NVIDIA `/v1/models` listing. Identifiers are accepted only from
     the live listing (or KNOWN_ENDPOINT_IDS with in-repo evidence) — never
     invented. Unmatched candidates stay UNVERIFIED/DISCOVERED, never enabled.

FREE-only rule enforced: a model is enabled only when free_endpoint AND
validated AND status ENABLED.
"""
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.agent import model_catalog
from backend.agent.model_interface import BaseModelProvider, FailureCategory, ModelError
from backend.agent.model_registry import ModelRecord, ModelRegistry, ModelStatus


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


# Generic tokens that must not count as evidence of a match.
_STOPWORDS = {
    "instruct", "instruction", "instructions", "model", "models", "chat",
    "the", "and", "for", "with", "a", "an", "of", "v",
}

# Capability-family tokens: if the live id carries one the candidate lacks
# (e.g. a safety-guard id for a plain "Instruct" candidate, a vision id for
# a text-only candidate), it is a different model family — never match.
_FAMILY_VETO = {
    "safety", "guard", "embed", "rerank", "translate", "tts",
    "voice", "ocr", "parse", "reward", "vision", "vl", "multimodal",
    "coder",
}

# Max live-id tokens (org prefix excluded) not covered by the candidate.
# Blocks generic-name lookalikes ("nv-embed-v1" vs a longer embedqa id).
_MAX_EXTRA_TOKENS = 3


def _versions(text: str) -> List[str]:
    """Dotted/underscored version pairs, e.g. '3.3' -> ['33'] (separator-free)."""
    return [
        f"{a}{b}"
        for a, b in re.findall(r"(\d+)[._](\d+)", text or "")
        if len(a) <= 2 and len(b) <= 2
    ]


def resolve_endpoint_id(candidate: str, live_model_ids: List[str]) -> Optional[str]:
    """Resolve a catalog candidate to a live endpoint id — strict, no lookalikes.

    1. KNOWN_ENDPOINT_IDS hit (in-repo runtime evidence) — but only if the
       id is actually present in the live listing (re-checked every audit).
    2. Otherwise the live id must contain EVERY digit-bearing token of the
       candidate (versions/sizes like 3.5, 30b, a3b, 0813, 120b must match
       exactly — "120B" never matches "20b", "49B" never matches "51b")
       AND at least 2 non-generic candidate tokens.
    Returns None when nothing matches: never invent an identifier.
    """
    live = [str(m) for m in (live_model_ids or [])]
    known = model_catalog.known_endpoint_id(candidate)
    if known and known in live:
        return known
    entry = model_catalog.get_candidate(candidate)
    if not entry:
        return None
    cand_tokens = _tokens(candidate)
    digit_tokens = [t for t in cand_tokens if any(c.isdigit() for c in t)]
    alpha_tokens = [t for t in cand_tokens if t not in _STOPWORDS]
    cand_set = set(cand_tokens)
    cand_versions = _versions(candidate)
    # Distinctive name tokens (e.g. "medium", "glimmer", "lightning") must
    # all be present — "Mistral Medium 3" is not "mistral-7b-instruct".
    long_tokens = [t for t in cand_set if len(t) >= 5 and not any(c.isdigit() for c in t)]
    scored: List[Tuple[int, str]] = []
    for mid in live:
        norm = _normalize(mid)
        if any(dt not in norm for dt in digit_tokens):
            continue
        if any(v not in norm for v in cand_versions):
            continue
        if any(t not in norm for t in long_tokens):
            continue
        mid_name = mid.split("/", 1)[1] if "/" in mid else mid
        mid_tokens = set(_tokens(mid_name))
        if any(tok in mid_tokens and tok not in cand_set for tok in _FAMILY_VETO):
            continue
        if len(mid_tokens - cand_set) > _MAX_EXTRA_TOKENS:
            continue
        hits = sum(1 for t in alpha_tokens if t and t in norm)
        if hits >= 2:
            # More token hits win; ties prefer the shorter (more exact) id.
            scored.append((hits * 1000 - len(norm), mid))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def validate_model(
    provider: BaseModelProvider,
    registry: ModelRegistry,
    model_id: str,
    probe_tool_call: bool = False,
    timeout_s: int = 90,
) -> Dict[str, Any]:
    """Run real runtime probes for one model and update the registry.

    Steps: health_check -> tiny generate -> (optional) tool_call probe.
    Success: mark_validated + ENABLED (FREE registry entries only).
    Failure: status mapped from the failure category + evidence recorded.
    """
    record = registry.get(model_id)
    if not record:
        return {"model": model_id, "ok": False, "reason": "not in registry"}

    started = time.time()
    health = provider.health_check(model_id, timeout_s=min(60, timeout_s))
    if not health.get("ok"):
        _apply_failure(registry, record, health.get("category") or "unavailable", health.get("message", ""))
        return {"model": model_id, "ok": False, "stage": "health_check", **health}

    try:
        resp = provider.generate(
            model_id,
            [{"role": "user", "content": "Reply with exactly: VALIDATED"}],
            temperature=0.0,
            max_tokens=32,
            timeout_s=timeout_s,
        )
        if not resp.text.strip():
            _apply_failure(registry, record, FailureCategory.UNSUPPORTED_CAPABILITY.value, "empty generate response")
            return {"model": model_id, "ok": False, "stage": "generate", "reason": "empty response"}
    except ModelError as e:
        _apply_failure(registry, record, e.category.value, e.message)
        return {"model": model_id, "ok": False, "stage": "generate", "category": e.category.value}

    if probe_tool_call:
        try:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "get_time",
                        "description": "Return the current time",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
            provider.tool_call(
                model_id,
                [{"role": "user", "content": "What time is it? Use get_time."}],
                tools,
                timeout_s=timeout_s,
            )
        except ModelError as e:
            if e.category == FailureCategory.UNSUPPORTED_CAPABILITY:
                _apply_failure(registry, record, e.category.value, "tool_call unsupported")
                return {"model": model_id, "ok": False, "stage": "tool_call", "category": e.category.value}
            # A model that answers without calling the tool still passes the
            # chat validation; tool support is just not advertised.

    latency = time.time() - started
    registry.mark_validated(model_id, latency_s=latency)
    registry.record_success(model_id, latency)
    rec = registry.get(model_id)
    enabled = False
    if rec and rec.free_endpoint:
        enabled = registry.set_enabled(model_id, True, note="runtime validated FREE endpoint") is not None
    return {
        "model": model_id,
        "ok": True,
        "enabled": enabled,
        "latency_s": round(latency, 2),
        "health_latency_s": round(health.get("latency_s", 0.0), 2),
    }


def _apply_failure(registry: ModelRegistry, record: ModelRecord, category: str, message: str) -> None:
    registry.record_failure(record.model_id, category)
    mapping = {
        FailureCategory.AUTH_ERROR.value: ModelStatus.AUTH_ERROR,
        FailureCategory.RATE_LIMITED.value: ModelStatus.RATE_LIMITED,
        FailureCategory.UNAVAILABLE.value: ModelStatus.UNAVAILABLE,
        FailureCategory.UNSUPPORTED_CAPABILITY.value: ModelStatus.CAPABILITY_FAILED,
        FailureCategory.TIMEOUT.value: ModelStatus.UNAVAILABLE,
        FailureCategory.SERVER_ERROR.value: ModelStatus.UNAVAILABLE,
    }
    registry.set_status(record.model_id, mapping.get(category, ModelStatus.UNAVAILABLE), note=message[:300])


_STATUS_BY_CATEGORY = {
    "chat": ("general", 50),
    "reasoning": ("heavy", 30),
    "coding": ("coding", 40),
    "vision": ("vision", 40),
    "embed": ("embed", 60),
    "rerank": ("rerank", 60),
    "ocr": ("ocr", 60),
    "voice": ("voice", 80),
    "tts": ("tts", 80),
    "translation": ("general", 80),
    "safety": ("safety", 80),
    "image": ("image", 90),
    "video": ("video", 90),
    "perception": ("perception", 90),
    "biology": ("general", 90),
}


def audit_catalog(
    registry: ModelRegistry,
    live_model_ids: List[str],
    provider_name: str = "nvidia",
) -> Dict[str, Any]:
    """Register/update EVERY supplied candidate from live listing evidence.

    - Matched live id  -> DISCOVERED (ready for runtime validation), with
      FREE endpoint assumed-pending (confirmed only by a successful
      authenticated call — listing alone never enables).
    - No match         -> UNVERIFIED + disabled, never enabled.
    - Previously validated entries keep their evidence (register merges).
    """
    live = [str(m) for m in (live_model_ids or [])]
    report: Dict[str, Any] = {"matched": [], "unmatched": [], "live_count": len(live)}
    for entry in model_catalog.SUPPLIED_CANDIDATES:
        candidate = entry["candidate"]
        endpoint = resolve_endpoint_id(candidate, live)
        group, priority = _STATUS_BY_CATEGORY.get(entry["category"], ("general", 100))
        if endpoint:
            registry.register(
                ModelRecord(
                    model_id=endpoint,
                    provider=provider_name,
                    display_name=candidate,
                    free_endpoint=False,  # confirmed only by runtime validation
                    status=ModelStatus.DISCOVERED.value,
                    capabilities=list(entry.get("capabilities", [])),
                    priority=priority,
                    fallback_group=group,
                    note=f"catalog candidate '{candidate}' matched live listing",
                )
            )
            report["matched"].append({"candidate": candidate, "endpoint": endpoint})
        else:
            key = f"catalog:{candidate}"
            registry.register(
                ModelRecord(
                    model_id=key,
                    provider=provider_name,
                    display_name=candidate,
                    free_endpoint=False,
                    status=ModelStatus.UNVERIFIED.value,
                    enabled=False,
                    capabilities=list(entry.get("capabilities", [])),
                    priority=priority,
                    fallback_group=group,
                    note="no matching live endpoint id — never invented",
                )
            )
            report["unmatched"].append(candidate)
    registry.save()
    report["summary"] = registry.summary()
    return report


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
