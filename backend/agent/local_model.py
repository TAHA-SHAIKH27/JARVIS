"""Optional local Ollama fallback for JARVIS planning.

No extra Python dependency: uses urllib from the standard library. Cloud
providers remain the preferred path; this module is consulted only after the
configured remote planning paths fail.
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


def _base_url() -> str:
    return (os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"))


def available_models(timeout_s: float = 1.5) -> List[str]:
    try:
        req = urllib.request.Request(_base_url() + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [str(m.get("name", "")).strip() for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def select_model(models: Optional[List[str]] = None) -> Optional[str]:
    configured = os.environ.get("JARVIS_LOCAL_MODEL", "").strip()
    models = models if models is not None else available_models()
    if configured and configured in models:
        return configured
    if configured and not models:
        # Do not pretend the model is available; availability must be probed.
        return None
    preferred = ("qwen", "gemma", "llama", "mistral", "phi", "deepseek")
    for family in preferred:
        for name in models:
            if family in name.casefold():
                return name
    return models[0] if models else None


def generate_plan(task: str, system_prompt: str, timeout_s: float = 8.0) -> Optional[Any]:
    """Ask a detected local Ollama model for the same JSON plan shape as remote LLMs."""
    model = select_model()
    if not model:
        return None
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task}"},
        ],
        "options": {"temperature": 0.1},
    }
    try:
        req = urllib.request.Request(
            _base_url() + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("message") or {}).get("content", "")
        if not content:
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("["), content.rfind("]")
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end + 1])
            else:
                return None
        if isinstance(parsed, dict) and "plan" in parsed:
            return parsed["plan"]
        return parsed if isinstance(parsed, list) else None
    except Exception:
        return None
