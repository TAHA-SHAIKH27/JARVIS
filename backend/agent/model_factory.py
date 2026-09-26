"""
Phase 1 — Default wiring: registry + providers + router from existing config.

Builds on the exact config sources the repo already uses (root config.json
+ environment, same keys as planner.py / code_core.py). No behavior change
until a model is runtime-validated and ENABLED: Planner keeps its existing
Gemini/NVIDIA-inline path and rule-based fallback when the registry has no
ENABLED model.
"""
import json
import os
from typing import Any, Dict, Tuple

from backend.agent.gemini_provider import GeminiProvider
from backend.agent.model_registry import ModelRecord, ModelRegistry, ModelStatus
from backend.agent.model_router import ModelRouter
from backend.agent.nvidia_provider import NvidiaProvider

_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_llm_config() -> Dict[str, Any]:
    """Same sources as planner._load_all_llm_configs (config.json + env)."""
    cfg: Dict[str, Any] = {}
    for name in ("config.json",):
        path = os.path.join(_WORKSPACE_ROOT, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
                if cfg:
                    break
            except Exception:
                pass
    return {
        "gemini_api_key": cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", ""),
        "nvidia_api_key": cfg.get("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY", ""),
        "nvidia_model": cfg.get("nvidia_model") or "z-ai/glm-5.3-flash",
        "nvidia_base_url": cfg.get("nvidia_base_url") or "https://integrate.api.nvidia.com/v1",
        "router_timeout_s": int(cfg.get("model_router_timeout_seconds", 90) or 90),
    }


def ensure_default_models(registry: ModelRegistry, preferred_model: str = "") -> None:
    """Seed the preferred primary / multimodal slots as DISCOVERED entries.

    Seeding never enables anything: validation must still prove FREE +
    accessible + healthy before set_enabled() can succeed.
    """
    preferred = preferred_model or "z-ai/glm-5.3-flash"
    registry.register(
        ModelRecord(
            model_id=preferred,
            provider="nvidia",
            display_name="Primary agent model (configured default)",
            free_endpoint=False,
            status=ModelStatus.DISCOVERED.value,
            capabilities=["chat"],
            priority=10,
            fallback_group="primary",
        )
    )
    registry.register(
        ModelRecord(
            model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
            provider="nvidia",
            display_name="Nemotron 3.5 Lightning 30B A3B (primary candidate)",
            free_endpoint=False,
            status=ModelStatus.DISCOVERED.value,
            capabilities=["chat"],
            priority=5,
            fallback_group="primary",
            note="enabled only if runtime validation proves FREE + healthy",
        )
    )


def build_registry(store_path: str = "") -> ModelRegistry:
    from backend.agent.model_registry import DEFAULT_STORE_PATH

    registry = ModelRegistry(store_path or DEFAULT_STORE_PATH)
    return registry


def build_providers(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nvidia": NvidiaProvider(
            api_key=config.get("nvidia_api_key", ""),
            base_url=config.get("nvidia_base_url") or "https://integrate.api.nvidia.com/v1",
        ),
        "gemini": GeminiProvider(api_key=config.get("gemini_api_key", "")),
    }


def build_router(
    registry: "ModelRegistry | None" = None,
    providers: "Dict[str, Any] | None" = None,
) -> Tuple[ModelRegistry, Dict[str, Any], ModelRouter]:
    """Build (registry, providers, router). Seeds defaults; loads persisted
    validation evidence from the store."""
    config = load_llm_config()
    registry = registry or build_registry()
    ensure_default_models(registry, config.get("nvidia_model", ""))
    providers = providers or build_providers(config)
    router = ModelRouter(registry, providers)
    return registry, providers, router
