"""Phase 3 tests — one coherent agentic loop (offline; models are faked).

Covers §25: router task routing/fallback/health, memory loop spot checks,
vision hierarchy + fallback (mocked/unavailable/empty/timeout), computer
observation, browser observation, office create+verify, voice preservation,
recovery classification, and an end-to-end stubbed agent run. No network,
no GUI, no audio is ever played.
"""
import asyncio

import pytest

from backend.agent import model_factory
from backend.agent.model_interface import FailureCategory, ModelError, ModelResponse
from backend.agent.model_registry import ModelRecord, ModelRegistry
from backend.agent.model_router import ModelRouter, profile_for
from backend.agent.state import ActionSpec, TaskState


# ── fakes ─────────────────────────────────────────────────────────────────────
class FakeProvider:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.calls = []

    def vision(self, model, prompt, image_b64, mime="image/png", timeout_s=90):
        self.calls.append(model)
        if self.error is not None:
            raise self.error
        return ModelResponse(text=self.text, model_id=model, provider="fake",
                             latency_s=0.1)


class FakeRegistry:
    def __init__(self):
        self.successes = []
        self.failures = []

    def record_success(self, model_id, latency_s=0.0):
        self.successes.append(model_id)

    def record_failure(self, model_id, category=""):
        self.failures.append((model_id, category))


class FakeRouter:
    def __init__(self, records, providers):
        self._records = records
        self._providers = providers

    def candidates(self, profile):
        return list(self._records)

    def provider_for(self, record):
        return self._providers.get(record.provider)


def _vision_record(model_id="meta/llama-3.2-11b-vision-instruct"):
    return ModelRecord(model_id=model_id, provider="nvidia",
                       display_name="vision", free_endpoint=True,
                       status="ENABLED", enabled=True, validated=True,
                       capabilities=["chat", "vision"], priority=20,
                       fallback_group="multimodal")


def _fake_build_router(records, providers, registry=None):
    return (registry or FakeRegistry(), providers, FakeRouter(records, providers))


def _png_bytes(tmp_path):
    # Minimal valid PNG (1x1) — only decoded as base64, never rendered.
    import base64
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    path = tmp_path / "shot.png"
    path.write_bytes(raw)
    return str(path)


# ── router: validated-only selection ──────────────────────────────────────────
def test_vision_profile_selects_only_validated_models():
    registry, _providers, router = model_factory.build_router()
    records = router.candidates(profile_for("vision"))
    assert records, "expected at least the validated vision model"
    for record in records:
        assert record.enabled and record.validated and record.free_endpoint
        assert record.status == "ENABLED"
    ids = [r.model_id for r in records]
    assert "meta/llama-3.2-11b-vision-instruct" in ids
    for forbidden in ("meta/muse-glimmer-30b", "z-ai/glm-5.3-flash",
                      "nvidia/nemotron-parse-2.0"):
        assert forbidden not in ids, f"unvalidated {forbidden} must never route"


def test_ocr_profile_has_no_validated_model():
    _registry, _providers, router = model_factory.build_router()
    with pytest.raises(ModelError):
        router.route(profile_for("ocr"))  # parse-2.0 stays disabled


def test_registry_health_circuit_breaks(tmp_path):
    registry = ModelRegistry(str(tmp_path / "reg.json"))
    registry.register(ModelRecord(model_id="test/m", provider="nvidia",
                                  free_endpoint=True, status="ENABLED",
                                  enabled=True, validated=True))
    for _ in range(5):
        registry.record_failure("test/m", "timeout")
    rec = registry.get("test/m")
    assert rec.consecutive_failures == 5


# ── vision fallback through the router ────────────────────────────────────────
def _perception():
    from backend.agent.observer import VisionPerception
    return VisionPerception()


def test_vision_fallback_returns_model_text(tmp_path, monkeypatch):
    provider = FakeProvider(text="A red button labeled Save")
    registry = FakeRegistry()
    monkeypatch.setattr(model_factory, "build_router",
                        lambda: _fake_build_router([_vision_record()], {"nvidia": provider}, registry))
    out = asyncio.run(_perception()._analyze_with_llm(_png_bytes(tmp_path)))
    assert out == "A red button labeled Save"
    assert provider.calls == ["meta/llama-3.2-11b-vision-instruct"]
    assert registry.successes == ["meta/llama-3.2-11b-vision-instruct"]


def test_vision_fallback_empty_response_is_graceful(tmp_path, monkeypatch):
    provider = FakeProvider(text="   ")
    registry = FakeRegistry()
    monkeypatch.setattr(model_factory, "build_router",
                        lambda: _fake_build_router([_vision_record()], {"nvidia": provider}, registry))
    assert asyncio.run(_perception()._analyze_with_llm(_png_bytes(tmp_path))) == ""
    assert registry.failures, "empty response must be recorded as model failure"


def test_vision_fallback_tries_next_candidate(tmp_path, monkeypatch):
    rec_a = _vision_record("vendor/model-a")
    rec_b = _vision_record("vendor/model-b")
    registry = FakeRegistry()

    # One dispatching provider: first candidate times out, second answers.
    class Dispatch:
        def __init__(self):
            self.calls = []

        def vision(self, model, prompt, image_b64, mime="image/png", timeout_s=90):
            self.calls.append(model)
            if model == "vendor/model-a":
                raise ModelError("timeout", FailureCategory.TIMEOUT)
            return ModelResponse(text="A dialog with OK", model_id=model,
                                 provider="fake", latency_s=0.1)

    dispatch = Dispatch()
    monkeypatch.setattr(model_factory, "build_router",
                        lambda: _fake_build_router([rec_a, rec_b], {"nvidia": dispatch}, registry))
    out = asyncio.run(_perception()._analyze_with_llm(_png_bytes(tmp_path)))
    assert out == "A dialog with OK"
    assert dispatch.calls == ["vendor/model-a", "vendor/model-b"]
    assert ("vendor/model-a", "timeout") in registry.failures


def test_vision_fallback_no_candidates_never_calls_network(tmp_path, monkeypatch):
    provider = FakeProvider(text="should never be used")
    monkeypatch.setattr(model_factory, "build_router",
                        lambda: _fake_build_router([], {"nvidia": provider}, FakeRegistry()))
    assert asyncio.run(_perception()._analyze_with_llm(_png_bytes(tmp_path))) == ""
    assert provider.calls == []


def test_vision_fallback_missing_file(tmp_path, monkeypatch):
    provider = FakeProvider(text="x")
    monkeypatch.setattr(model_factory, "build_router",
                        lambda: _fake_build_router([_vision_record()], {"nvidia": provider}, FakeRegistry()))
    assert asyncio.run(_perception()._analyze_with_llm(str(tmp_path / "nope.png"))) == ""
    assert provider.calls == []


# ── hierarchy: UIA first, vision only when insufficient ───────────────────────
def _uia_state(confidence, n_elements, roles=None):
    from backend.agent.observer import SemanticState
    from backend.tools.result_schema import UIElement
    roles = roles or (["button"] * n_elements)
    elements = [UIElement(name=f"btn{i}", role=role, bounds=[0, 0, 10, 10],
                          confidence=0.9, source="uia")
                for i, role in enumerate(roles)]
    return SemanticState(application="app", window_title="t", window_class="c",
                         window_bounds=[0, 0, 10, 10], elements=elements,
                         running_apps=["app"], confidence=confidence)


def test_hierarchy_skips_vision_when_uia_sufficient(monkeypatch):
    from backend.agent.observer import PerceptionManager
    from backend.agent.state import TaskState
    manager = PerceptionManager()
    async def fake_uia(state):
        return _uia_state(0.95, 4)
    monkeypatch.setattr(manager.uia_observer, "get_structured_state", fake_uia)
    called = []

    async def fake_vision(state, focus="general"):
        called.append(True)
        return None

    monkeypatch.setattr(manager.vision, "capture_and_analyze", fake_vision)
    out = asyncio.run(manager.perceive(TaskState()))
    assert called == [] and out["source"] == "uia" and out["fused"] is False


def test_hierarchy_uses_vision_when_uia_weak(monkeypatch):
    from backend.agent.observer import PerceptionManager, VisionObservation
    from backend.agent.state import TaskState
    manager = PerceptionManager()

    async def fake_uia(state):
        return _uia_state(0.4, 1)

    async def fake_vision(state, focus="general"):
        return VisionObservation(
            elements=[{"type": "text", "text": "Save",
                       "bounds": [100, 100, 160, 120],
                       "confidence": 0.8, "source": "vision"}],
            confidence=0.6, raw_text="Save")

    monkeypatch.setattr(manager.uia_observer, "get_structured_state", fake_uia)
    monkeypatch.setattr(manager.vision, "capture_and_analyze", fake_vision)
    out = asyncio.run(manager.perceive(TaskState()))
    assert out["source"] == "fused" and out["vision"]["confidence"] == 0.6


def test_hierarchy_canvas_triggers_vision():
    from backend.agent.observer import PerceptionManager
    manager = PerceptionManager()
    canvas_state = _uia_state(0.95, 4, ["button", "canvas", "link", "menu"])
    assert manager._needs_vision_fallback(canvas_state) is True
    rich_state = _uia_state(0.95, 4, ["button", "link", "menu", "edit"])
    assert manager._needs_vision_fallback(rich_state) is False
    assert manager._needs_vision_fallback(_uia_state(0.4, 5)) is True
    assert manager._needs_vision_fallback(_uia_state(0.95, 1)) is True


# ── computer / observation ────────────────────────────────────────────────────
def test_executor_rejects_unknown_action_closed():
    from backend.agent.executor import Executor
    from backend.agent.registry import ToolRegistry
    from backend.agent.state import TaskState
    action = ActionSpec(type="vision_hack_do_anything", description="evil",
                        parameters={})
    out = asyncio.run(Executor(ToolRegistry()).execute(action, TaskState()))
    assert out["status"] == "error" and "Unknown action type" in out["message"]


def test_observer_inspect_ui_pure_branch():
    from backend.agent.observer import Observer
    from backend.agent.registry import ToolRegistry
    from backend.agent.state import ActionSpec, TaskState
    action = ActionSpec(type="inspect_ui", description="x", parameters={})
    out = asyncio.run(Observer(ToolRegistry()).observe_after_action(
        action, {"status": "success", "elements": [{"a": 1}]}, TaskState(), None))
    assert out["verified"] is True and out["classification"] == "success"


def test_observer_browser_search_without_browser_is_fatal():
    from backend.agent.observer import Observer
    from backend.agent.registry import ToolRegistry
    from backend.agent.state import ActionSpec, TaskState
    action = ActionSpec(type="browser_search", description="x", parameters={})
    out = asyncio.run(Observer(ToolRegistry()).observe_after_action(
        action, {"status": "success"}, TaskState(), None))
    assert out["verified"] is False and out["classification"] == "fatal"


def test_observer_browser_search_success_uses_dom_not_vision():
    from backend.agent.observer import Observer
    from backend.agent.registry import ToolRegistry
    from backend.agent.state import ActionSpec, TaskState
    action = ActionSpec(type="browser_search", description="x", parameters={})
    state = TaskState()
    out = asyncio.run(Observer(ToolRegistry()).observe_after_action(
        action, {"status": "success", "results": [{"url": "https://a.com"}],
                 "url": "https://a.com", "title": "A", "message": "ok"},
        state, object()))
    assert out["verified"] is True
    assert state.search_results == [{"url": "https://a.com"}]


# ── office create + verify ────────────────────────────────────────────────────
def test_office_docx_create_and_verify(tmp_path):
    from backend.agent.observer import Observer
    from backend.agent.registry import ToolRegistry
    from backend.agent.state import ActionSpec, TaskState
    from backend.tools.office import Office
    target = str(tmp_path / "phase3.docx")
    created = asyncio.run(Office.create_docx(content="Hello Phase 3",
                                             title="P3", save_path=target))
    assert created.get("status") == "success"
    action = ActionSpec(type="create_docx", description="x",
                        parameters={"path": target})
    out = asyncio.run(Observer(ToolRegistry()).observe_after_action(
        action, created, TaskState(), None))
    assert out["verified"] is True


# ── verifier ──────────────────────────────────────────────────────────────────
def test_verifier_success_and_fatal():
    from backend.agent.state import ActionSpec
    from backend.agent.verifier import Verifier
    action = ActionSpec(type="speak", description="x", parameters={})
    ok_result = Verifier().verify_action(
        action, {"status": "success"}, {"verified": True, "message": "ok"})
    assert ok_result["verified"] is True and ok_result["should_retry"] is False
    fatal = Verifier().verify_action(
        action, {"status": "error", "message": "blocked"},
        {"verified": False, "message": "blocked", "classification": "fatal"})
    assert fatal["verified"] is False and fatal["should_retry"] is False


# ── voice preserved (no audio ever played) ────────────────────────────────────
def test_voice_system_preserved_idle():
    from backend.agent.voice import TTSState, get_command_processor, get_voice_system
    voice = get_voice_system()
    assert get_voice_system() is voice  # singleton preserved
    assert voice.get_state() in (TTSState.IDLE, TTSState.SPEAKING, TTSState.INTERRUPTED)
    assert get_command_processor() is not None


# ── memory loop spot check ────────────────────────────────────────────────────
def test_memory_loop_retrieval_update_persistence(tmp_path):
    from backend.agent.memory_api import JarvisMemory
    from backend.agent.memory_schema import MemorySource, MemoryType
    from backend.agent.memory_store import MemoryStore
    api = JarvisMemory(store=MemoryStore(str(tmp_path / "p3.db")))
    assert api.remember("test prefers verbose output")["status"] == "success"
    hits = api.search("verbose", use_embeddings=False, use_rerank=False)["hits"]
    assert hits and hits[0]["explain"]["source"] == MemorySource.EXPLICIT_USER
    api2 = JarvisMemory(store=MemoryStore(str(tmp_path / "p3.db")))
    assert api2.search("verbose", use_embeddings=False,
                       use_rerank=False)["count"] == 1
    assert api.list(memory_type=MemoryType.USER)["count"] == 1


# ── end-to-end stubbed agent run ──────────────────────────────────────────────
def test_end_to_end_stubbed_loop():
    import asyncio as _asyncio
    from backend.agent.core import AgentCore
    from backend.agent.memory_api import JarvisMemory
    from backend.agent.memory_store import MemoryStore
    from backend.agent.state import TaskState
    import tempfile as _tempfile
    import os as _os
    api = JarvisMemory(store=MemoryStore(_os.path.join(_tempfile.gettempdir(),
                                                       "p3_e2e.db")))
    try:
        _os.remove(api.store._db_path)
    except OSError:
        pass
    api = JarvisMemory(store=MemoryStore(_os.path.join(_tempfile.gettempdir(),
                                                       "p3_e2e.db")))
    core = AgentCore()
    core._jarvis_memory = api
    from backend.agent.planner import Planner

    def fake_plan(task, state):
        # Real plan construction (valid state.plan) with stubbed actions.
        return Planner()._build_plan(
            [{"type": "speak", "text": "Stubbed loop complete, sir.",
              "description": "done"}],
            state, {"primary_goal": task})

    core.planner.plan_task = fake_plan
    state = TaskState()
    out = _asyncio.run(core.process("stubbed end to end flow", state))
    assert out["status"] == "completed"
    assert "Stubbed loop complete" in out["speak"]
    assert state.get_context("phase2_memory_context") is not None
    try:
        _os.remove(api.store._db_path)
    except OSError:
        pass
