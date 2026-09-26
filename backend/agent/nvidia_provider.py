"""
Phase 1 — ONE NVIDIA provider abstraction for J.A.R.V.I.S.

All NVIDIA NIM traffic flows through NvidiaProvider: generate, stream,
tool_call, vision, embed, rerank, ocr, health_check, get_model_info.
Responses are normalized to ModelResponse; failures to ModelError with a
FailureCategory the router can act on.

Endpoints (NVIDIA NIM OpenAI-compatible gateway):
  chat   : POST {base}/chat/completions   (SSE when stream=True)
  models : GET  {base}/models             (catalog listing, live evidence)
  embed  : POST {base}/embeddings
  rerank : POST {base}/reranking          (404/unsupported -> UNAVAILABLE)

No per-model HTTP duplication: callers pass the model id; this class owns
the wire format, timeouts, retries (bounded), and error classification.
Stdlib only (urllib) — no new dependencies.
"""
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

from backend.agent.model_interface import (
    BaseModelProvider,
    FailureCategory,
    ModelCapability,
    ModelError,
    ModelResponse,
)

CHAT_PATH = "/chat/completions"
MODELS_PATH = "/models"
EMBED_PATH = "/embeddings"
RERANK_PATH = "/reranking"

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _is_timeout_error(err: BaseException) -> bool:
    if isinstance(err, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(err, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def classify_http_error(code: Optional[int], body: str = "") -> "tuple[FailureCategory, bool]":
    """Map HTTP status -> (category, retryable-on-another-model)."""
    if code in (401, 403):
        return FailureCategory.AUTH_ERROR, False
    if code == 429:
        return FailureCategory.RATE_LIMITED, True
    if code == 404:
        return FailureCategory.UNAVAILABLE, False
    if code == 422:
        return FailureCategory.UNSUPPORTED_CAPABILITY, False
    if code is not None and 500 <= code <= 599:
        return FailureCategory.SERVER_ERROR, True
    lowered = (body or "").lower()
    if "rate" in lowered and "limit" in lowered:
        return FailureCategory.RATE_LIMITED, True
    return FailureCategory.UNKNOWN, True


class NvidiaProvider(BaseModelProvider):
    provider_name = "nvidia"

    # Static capability hints by model family (registry data wins at runtime).
    _VISION_HINTS = ("vision", "vl", "multimodal", "paligemma", "phi-4", "maverick")
    _EMBED_HINTS = ("embed", "retriever")
    _RERANK_HINTS = ("rerank", "rank")
    _REASON_HINTS = ("reason", "pro", "ultra", "r1", "magistral", "cosmos-reason")

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = "z-ai/glm-5.3-flash",
        request_timeout_s: int = 120,
        max_retries: int = 2,
        retry_backoff_s: int = 5,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.default_model = default_model
        self.request_timeout_s = request_timeout_s
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_s = max(0, int(retry_backoff_s))

    # -- capabilities ----------------------------------------------------
    def supports(self, model_id: str, capability: ModelCapability) -> bool:
        mid = (model_id or "").lower()
        if capability == ModelCapability.CHAT:
            return True
        if capability == ModelCapability.VISION:
            return any(h in mid for h in self._VISION_HINTS)
        if capability == ModelCapability.EMBED:
            return any(h in mid for h in self._EMBED_HINTS)
        if capability == ModelCapability.RERANK:
            return any(h in mid for h in self._RERANK_HINTS)
        if capability == ModelCapability.REASONING:
            return any(h in mid for h in self._REASON_HINTS)
        if capability == ModelCapability.CODING:
            return "coder" in mid or "code" in mid
        if capability == ModelCapability.TOOL_CALL:
            return not any(h in mid for h in ("embed", "rerank", "ocr", "parse"))
        if capability == ModelCapability.OCR:
            return "ocr" in mid or "parse" in mid or self.supports(model_id, ModelCapability.VISION)
        return False

    # -- low-level HTTP (single place) ------------------------------------
    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ModelError(
                "NVIDIA API key not configured",
                FailureCategory.AUTH_ERROR,
                retryable=False,
            )
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _post_json(self, path: str, payload: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            category, retryable = classify_http_error(e.code, body)
            raise ModelError(
                f"NVIDIA HTTP {e.code}: {body[:300]}",
                category,
                status_code=e.code,
                retryable=retryable,
            ) from e
        except urllib.error.URLError as e:
            if _is_timeout_error(e):
                raise ModelError(f"NVIDIA request timed out: {e}", FailureCategory.TIMEOUT) from e
            raise ModelError(f"NVIDIA network error: {e}", FailureCategory.NETWORK_ERROR) from e
        except (TimeoutError, socket.timeout) as e:
            raise ModelError(f"NVIDIA request timed out: {e}", FailureCategory.TIMEOUT) from e
        except (ModelError, json.JSONDecodeError):
            raise
        except Exception as e:
            raise ModelError(f"NVIDIA request failed: {e}", FailureCategory.UNKNOWN) from e

    def _get_json(self, path: str, timeout_s: int) -> Dict[str, Any]:
        url = self.base_url + path
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            category, retryable = classify_http_error(e.code, body)
            raise ModelError(
                f"NVIDIA HTTP {e.code}: {body[:300]}",
                category,
                status_code=e.code,
                retryable=retryable,
            ) from e
        except urllib.error.URLError as e:
            if _is_timeout_error(e):
                raise ModelError(f"NVIDIA request timed out: {e}", FailureCategory.TIMEOUT) from e
            raise ModelError(f"NVIDIA network error: {e}", FailureCategory.NETWORK_ERROR) from e
        except (TimeoutError, socket.timeout) as e:
            raise ModelError(f"NVIDIA request timed out: {e}", FailureCategory.TIMEOUT) from e
        except Exception as e:
            raise ModelError(f"NVIDIA request failed: {e}", FailureCategory.UNKNOWN) from e

    # -- normalization (single place) --------------------------------------
    @staticmethod
    def _normalize_chat(model: str, payload: Dict[str, Any], latency_s: float) -> ModelResponse:
        choices = payload.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        text = message.get("content") or ""
        tool_calls = []
        for tc in message.get("tool_calls") or []:
            try:
                tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "name": (tc.get("function") or {}).get("name", ""),
                        "arguments": (tc.get("function") or {}).get("arguments", ""),
                    }
                )
            except Exception:
                continue
        return ModelResponse(
            text=text or "",
            model_id=model,
            provider="nvidia",
            latency_s=latency_s,
            usage=payload.get("usage") or {},
            tool_calls=tool_calls,
            finish_reason=first.get("finish_reason", ""),
            raw=payload,
        )

    # -- core --------------------------------------------------------------
    def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 120,
    ) -> ModelResponse:
        model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if model.startswith("deepseek-ai/"):
            # DeepSeek V-family spends the output budget on reasoning_content
            # by default; disable it so the budget serves the actual answer.
            payload["reasoning_effort"] = "none"
        last_error: Optional[ModelError] = None
        deadline = time.time() + min(timeout_s * 2, 600)
        for attempt in range(1, self.max_retries + 1):
            started = time.time()
            try:
                data = self._post_json(CHAT_PATH, payload, timeout_s)
                return self._normalize_chat(model, data, time.time() - started)
            except ModelError as e:
                last_error = e
                # Only timeouts / network blips / rate limits are retried, and
                # never past the wall-clock deadline. HTTP 4xx/5xx responses
                # describe THIS prompt+model, so fail fast (same lesson as
                # code_core.call_nemotron).
                if e.category not in (
                    FailureCategory.TIMEOUT,
                    FailureCategory.NETWORK_ERROR,
                    FailureCategory.RATE_LIMITED,
                ):
                    break
                if attempt >= self.max_retries or time.time() >= deadline:
                    break
                time.sleep(self.retry_backoff_s * attempt)
        raise last_error or ModelError("NVIDIA generate failed", FailureCategory.UNKNOWN)

    def stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout_s: int = 120,
    ) -> Iterator[str]:
        """Yield content deltas from the SSE stream (keeps slow free-tier
        connections alive while tokens trickle in)."""
        model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if model.startswith("deepseek-ai/"):
            payload["reasoning_effort"] = "none"
        url = self.base_url + CHAT_PATH
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        evt = json.loads(chunk)
                    except Exception:
                        continue
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            category, retryable = classify_http_error(e.code, body)
            raise ModelError(
                f"NVIDIA HTTP {e.code}: {body[:300]}",
                category,
                status_code=e.code,
                retryable=retryable,
            ) from e
        except urllib.error.URLError as e:
            if _is_timeout_error(e):
                raise ModelError(f"NVIDIA stream timed out: {e}", FailureCategory.TIMEOUT) from e
            raise ModelError(f"NVIDIA stream network error: {e}", FailureCategory.NETWORK_ERROR) from e
        except (TimeoutError, socket.timeout) as e:
            raise ModelError(f"NVIDIA stream timed out: {e}", FailureCategory.TIMEOUT) from e

    def tool_call(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        timeout_s: int = 120,
    ) -> ModelResponse:
        model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2048,
            "stream": False,
            "tools": tools,
            "tool_choice": "auto",
        }
        started = time.time()
        data = self._post_json(CHAT_PATH, payload, timeout_s)
        resp = self._normalize_chat(model, data, time.time() - started)
        # A model that silently ignores the tools parameter fails the
        # capability probe — report it instead of faking success.
        if not resp.tool_calls and (data.get("choices") or [{}])[0].get("finish_reason") != "tool_calls":
            # Not an error by itself (model may answer directly); caller
            # decides. Normal case: return what the model said.
            pass
        return resp

    def vision(
        self,
        model: str,
        prompt: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 120,
    ) -> ModelResponse:
        model = model or self.default_model
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Describe this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    },
                ],
            }
        ]
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048,
            "stream": False,
        }
        started = time.time()
        data = self._post_json(CHAT_PATH, payload, timeout_s)
        return self._normalize_chat(model, data, time.time() - started)

    def embed(
        self,
        model: str,
        inputs: List[str],
        timeout_s: int = 60,
        input_type: str = "passage",
    ) -> Dict[str, Any]:
        """Embeddings via POST {base}/embeddings.

        Asymmetric NVIDIA embed models require `input_type` ("query" for
        questions, "passage" for documents to index)."""
        payload: Dict[str, Any] = {"model": model, "input": inputs, "input_type": input_type}
        started = time.time()
        data = self._post_json(EMBED_PATH, payload, timeout_s)
        vectors = [(item.get("embedding") or []) for item in data.get("data") or []]
        return {
            "model": model,
            "embeddings": vectors,
            "latency_s": time.time() - started,
            "raw": data,
        }

    def rerank(self, model: str, query: str, passages: List[str], timeout_s: int = 60) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model, "query": query, "passages": passages}
        started = time.time()
        try:
            data = self._post_json(RERANK_PATH, payload, timeout_s)
        except ModelError as e:
            if e.status_code == 404:
                raise ModelError(
                    f"NVIDIA rerank endpoint unavailable for {model}",
                    FailureCategory.UNAVAILABLE,
                    status_code=404,
                    retryable=False,
                ) from e
            raise
        return {"model": model, "rankings": data.get("rankings", data), "latency_s": time.time() - started}

    def ocr(
        self,
        model: str,
        image_base64: str,
        mime_type: str = "image/png",
        timeout_s: int = 120,
    ) -> ModelResponse:
        resp = self.vision(
            model,
            "Extract all text from this image or document. Return only the text, no analysis or commentary.",
            image_base64,
            mime_type,
            timeout_s,
        )
        resp.raw["ocr"] = True
        return resp

    # -- introspection -------------------------------------------------------
    def list_models(self, timeout_s: int = 30) -> List[Dict[str, Any]]:
        data = self._get_json(MODELS_PATH, timeout_s)
        models = data.get("data") or data.get("models") or []
        return models if isinstance(models, list) else []

    def health_check(self, model: str, timeout_s: int = 60) -> Dict[str, Any]:
        model = model or self.default_model
        started = time.time()
        try:
            resp = self.generate(
                model,
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
                "model": model,
            }
        except ModelError as e:
            return {
                "ok": False,
                "latency_s": time.time() - started,
                "category": e.category.value,
                "message": e.message[:300],
                "model": model,
            }

    def get_model_info(self, model: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {"model_id": model, "provider": "nvidia"}
        try:
            for entry in self.list_models():
                if isinstance(entry, dict) and entry.get("id") == model:
                    info.update(entry)
                    info["listed"] = True
                    break
            else:
                info["listed"] = False
        except ModelError as e:
            info["listed"] = False
            info["list_error"] = e.message[:200]
        return info
