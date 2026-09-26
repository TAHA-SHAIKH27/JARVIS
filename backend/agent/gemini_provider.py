"""
Phase 1 — Gemini provider for J.A.R.V.I.S.

Preserves the existing Gemini integration (REST `generateContent`, model
fallback chain, Google-OAuth-if-authenticated else API key) and exposes it
through the common BaseModelProvider interface so the Model Router can use
Gemini alongside NVIDIA models.

Existing behavior kept:
  - Auth priority: Google OAuth access token > API key (mirrors planner.py).
  - Model chain tried in order until one answers.
  - JSON-in-text cleanup is the caller's job (planner already does it).

Where the common interface has no Gemini equivalent in this repo
(tool_call function-calling, embeddings, rerank), the method raises
ModelError(UNSUPPORTED_CAPABILITY) instead of faking a result.
"""
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from backend.agent.model_interface import (
    BaseModelProvider,
    FailureCategory,
    ModelCapability,
    ModelError,
    ModelResponse,
)

GENERATE_PATH = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Ordered fallback chain — verified live via ListModels (dated 1.5/2.0 names now 404).
DEFAULT_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest")


def _is_timeout_error(err: BaseException) -> bool:
    if isinstance(err, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(err, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


class GeminiProvider(BaseModelProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str = "", models: Optional[List[str]] = None, request_timeout_s: int = 60):
        self.api_key = (api_key or "").strip()
        self.models = list(models) if models else list(DEFAULT_GEMINI_MODELS)
        self.request_timeout_s = request_timeout_s

    # -- capabilities ----------------------------------------------------
    def supports(self, model_id: str, capability: ModelCapability) -> bool:
        # Gemini Flash models in this repo are used for chat + vision/OCR.
        if capability in (ModelCapability.CHAT, ModelCapability.VISION, ModelCapability.OCR):
            return True
        return False

    # -- auth (mirrors planner.py: OAuth first, then API key) ------------
    def _auth(self) -> "tuple[Dict[str, str], bool, str]":
        headers = {"Content-Type": "application/json"}
        try:
            import google_oauth

            if google_oauth.is_authenticated():
                token = google_oauth.get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    return headers, True, token
        except Exception:
            pass
        return headers, False, ""

    def _post(self, model: str, payload: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
        headers, use_oauth, _ = self._auth()
        if not use_oauth and not self.api_key:
            raise ModelError(
                "Gemini API key not configured (and Google OAuth not authenticated)",
                FailureCategory.AUTH_ERROR,
                retryable=False,
            )
        url = GENERATE_PATH.format(model=model)
        if not use_oauth:
            url += f"?key={self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if e.code in (400, 404):
                # Unknown/deprecated model name or bad request for this model:
                # try the next model in the chain (handled by caller), but if
                # this is a direct call, report unavailable.
                raise ModelError(
                    f"Gemini HTTP {e.code} for {model}: {body[:300]}",
                    FailureCategory.UNAVAILABLE,
                    status_code=e.code,
                    retryable=False,
                ) from e
            if e.code in (401, 403):
                raise ModelError(
                    f"Gemini auth failed: {body[:300]}",
                    FailureCategory.AUTH_ERROR,
                    status_code=e.code,
                    retryable=False,
                ) from e
            if e.code == 429:
                raise ModelError(
                    f"Gemini rate limited: {body[:300]}",
                    FailureCategory.RATE_LIMITED,
                    status_code=429,
                    retryable=True,
                ) from e
            raise ModelError(
                f"Gemini HTTP {e.code}: {body[:300]}",
                FailureCategory.SERVER_ERROR,
                status_code=e.code,
                retryable=True,
            ) from e
        except urllib.error.URLError as e:
            if _is_timeout_error(e):
                raise ModelError(f"Gemini request timed out: {e}", FailureCategory.TIMEOUT) from e
            raise ModelError(f"Gemini network error: {e}", FailureCategory.NETWORK_ERROR) from e
        except (TimeoutError, socket.timeout) as e:
            raise ModelError(f"Gemini request timed out: {e}", FailureCategory.TIMEOUT) from e

    @staticmethod
    def _normalize(model: str, payload: Dict[str, Any], latency_s: float) -> ModelResponse:
        try:
            text = (
                payload.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
        except Exception:
            text = ""
        return ModelResponse(
            text=text or "",
            model_id=model,
            provider="gemini",
            latency_s=latency_s,
            usage=payload.get("usageMetadata") or {},
            finish_reason=(payload.get("candidates") or [{}])[0].get("finishReason", ""),
            raw=payload,
        )

    def _messages_to_text(self, messages: List[Dict[str, str]]) -> str:
        parts = []
        for msg in messages or []:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") != "image_url"
                )
            prefix = "System: " if role == "system" else ("Assistant: " if role == "assistant" else "User: ")
            parts.append(f"{prefix}{content}")
        return "\n".join(parts)

    # -- core ------------------------------------------------------------
    def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 60,
    ) -> ModelResponse:
        prompt = self._messages_to_text(messages)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        candidates = [model] if model else list(self.models)
        if model and model not in self.models:
            candidates = [model] + [m for m in self.models if m != model]
        elif not model:
            candidates = list(self.models)
        last_error: Optional[ModelError] = None
        for name in candidates:
            started = time.time()
            try:
                data = self._post(name, payload, timeout_s or self.request_timeout_s)
                return self._normalize(name, data, time.time() - started)
            except ModelError as e:
                last_error = e
                # Model-level failures (404/400 unknown model): try next model.
                # Auth/rate-limit: no point cycling the chain, fail fast.
                if e.category in (FailureCategory.AUTH_ERROR, FailureCategory.RATE_LIMITED):
                    break
                if e.category not in (FailureCategory.UNAVAILABLE, FailureCategory.SERVER_ERROR):
                    break
                continue
        raise last_error or ModelError("Gemini generate failed", FailureCategory.UNKNOWN)

    def vision(
        self,
        model: str,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 60,
    ) -> ModelResponse:
        """Gemini inline_data vision (same wire format as backend/tools/vision.py)."""
        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                        {"text": prompt or "Describe this image in detail."},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.4},
        }
        name = model or (self.models[0] if self.models else "gemini-2.0-flash")
        started = time.time()
        data = self._post(name, payload, timeout_s or self.request_timeout_s)
        return self._normalize(name, data, time.time() - started)

    def ocr(
        self,
        model: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 60,
    ) -> ModelResponse:
        return self.vision(
            model,
            "Extract all text from this image or document. Return only the text, no analysis or commentary.",
            image_base64,
            mime_type,
            timeout_s,
        )

    # -- introspection ---------------------------------------------------
    def health_check(self, model: str, timeout_s: int = 30) -> Dict[str, Any]:
        name = model or (self.models[0] if self.models else "")
        started = time.time()
        try:
            resp = self.generate(
                name,
                [{"role": "user", "content": "Reply with exactly: OK"}],
                temperature=0.0,
                max_tokens=16,
                timeout_s=timeout_s,
            )
            latency = time.time() - started
            ok = bool(resp.text.strip())
            return {
                "ok": ok,
                "latency_s": latency,
                "category": "" if ok else FailureCategory.UNAVAILABLE.value,
                "message": resp.text[:200] if ok else "Empty response",
                "model": resp.model_id,
            }
        except ModelError as e:
            return {
                "ok": False,
                "latency_s": time.time() - started,
                "category": e.category.value,
                "message": e.message[:300],
                "model": name,
            }

    def get_model_info(self, model: str) -> Dict[str, Any]:
        return {
            "model_id": model or (self.models[0] if self.models else ""),
            "provider": "gemini",
            "models_chain": list(self.models),
            "listed": True,
        }
