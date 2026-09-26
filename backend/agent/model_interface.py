"""
Phase 1 — Common model interface for J.A.R.V.I.S. multi-model intelligence.

Every provider (NVIDIA, Gemini, …) implements BaseModelProvider so the
Model Router can treat them uniformly. Responses are normalized into
ModelResponse; failures are normalized into ModelError with a
FailureCategory. No third-party dependencies (stdlib only).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional


class ModelCapability(str, Enum):
    CHAT = "chat"
    REASONING = "reasoning"
    CODING = "coding"
    VISION = "vision"
    TOOL_CALL = "tool_call"
    EMBED = "embed"
    RERANK = "rerank"
    OCR = "ocr"
    VOICE = "voice"
    TTS = "tts"
    TRANSLATION = "translation"
    SAFETY = "safety"
    IMAGE_GEN = "image_gen"
    VIDEO = "video"


class FailureCategory(str, Enum):
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"


@dataclass
class ModelResponse:
    """Normalized response from any provider."""

    text: str = ""
    model_id: str = ""
    provider: str = ""
    latency_s: float = 0.0
    usage: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelHealth:
    """Health snapshot tracked per model by the registry/router."""

    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    failure_category: str = ""
    latency_s: float = 0.0
    consecutive_failures: int = 0
    rate_limits: int = 0
    validation_time: Optional[str] = None


class ModelError(Exception):
    """Typed provider failure. `retryable` tells the router whether a
    retry on a *different* model makes sense (never retry the same failing
    model blindly)."""

    def __init__(
        self,
        message: str,
        category: FailureCategory = FailureCategory.UNKNOWN,
        status_code: Optional[int] = None,
        retryable: bool = True,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code
        self.retryable = retryable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "category": self.category.value,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }


class BaseModelProvider(ABC):
    """Common interface every model provider must implement.

    Methods that a provider cannot support MUST raise
    ModelError(category=UNSUPPORTED_CAPABILITY, retryable=False) instead of
    returning fake data — the router relies on this to skip the capability.
    """

    provider_name: str = "base"

    # -- capabilities ----------------------------------------------------
    def supports(self, model_id: str, capability: ModelCapability) -> bool:
        """Best-effort static capability check (registry data wins)."""
        return capability == ModelCapability.CHAT

    # -- core ------------------------------------------------------------
    @abstractmethod
    def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 120,
    ) -> ModelResponse:
        ...

    def stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 120,
    ):
        """Yield text chunks (SSE-style). Default: single generate() chunk."""
        resp = self.generate(model, messages, temperature, max_tokens, timeout_s)
        yield resp.text

    # -- extended (override where applicable) ----------------------------
    def tool_call(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        timeout_s: int = 120,
    ) -> ModelResponse:
        raise ModelError(
            f"{self.provider_name}: tool_call not supported for {model}",
            FailureCategory.UNSUPPORTED_CAPABILITY,
            retryable=False,
        )

    def vision(
        self,
        model: str,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 120,
    ) -> ModelResponse:
        raise ModelError(
            f"{self.provider_name}: vision not supported for {model}",
            FailureCategory.UNSUPPORTED_CAPABILITY,
            retryable=False,
        )

    def embed(
        self,
        model: str,
        inputs: List[str],
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        raise ModelError(
            f"{self.provider_name}: embed not supported for {model}",
            FailureCategory.UNSUPPORTED_CAPABILITY,
            retryable=False,
        )

    def rerank(
        self,
        model: str,
        query: str,
        passages: List[str],
        timeout_s: int = 60,
    ) -> Dict[str, Any]:
        raise ModelError(
            f"{self.provider_name}: rerank not supported for {model}",
            FailureCategory.UNSUPPORTED_CAPABILITY,
            retryable=False,
        )

    def ocr(
        self,
        model: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 120,
    ) -> ModelResponse:
        raise ModelError(
            f"{self.provider_name}: ocr not supported for {model}",
            FailureCategory.UNSUPPORTED_CAPABILITY,
            retryable=False,
        )

    # -- introspection ---------------------------------------------------
    @abstractmethod
    def health_check(self, model: str, timeout_s: int = 60) -> Dict[str, Any]:
        """Tiny live probe. Returns {ok, latency_s, category, message}."""

    @abstractmethod
    def get_model_info(self, model: str) -> Dict[str, Any]:
        """Static/remote info about a model id. Never invents availability."""
