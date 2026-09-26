"""Phase 1 tests: multi-model intelligence + Model Router.

Covers: provider, authentication, normalization, registry, FREE filtering,
model validation, router, fallback, health, tool calls, errors, timeouts.
All network I/O is mocked — no live calls. Sync only (no pytest-asyncio).
"""
import io
import json
import os
import socket
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.agent import model_catalog
from backend.agent import model_validation as mv
from backend.agent.gemini_provider import GeminiProvider
from backend.agent.model_interface import FailureCategory, ModelError
from backend.agent.model_registry import ModelRecord, ModelRegistry, ModelStatus
from backend.agent.model_router import ModelRouter, profile_for
from backend.agent.nvidia_provider import NvidiaProvider


# -- mocks ---------------------------------------------------------------
class FakeHTTPResponse:
    def __init__(self, payload, lines=None):
        self._payload = payload
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __iter__(self):
        return iter(self._lines or [])


def nvidia_chat(text="OK", model="m", tools=None):
    msg = {"role": "assistant", "content": text}
    if tools is not None:
        msg["tool_calls"] = tools
        finish = "tool_calls"
    else:
        finish = "stop"
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"total_tokens": 7}}


def http_error(code, body="err"):
    return urllib.error.HTTPError("http://x", code, "E", {}, io.BytesIO(body.encode()))


def mock_urlopen(monkeypatch, behavior):
    """behavior: list of FakeHTTPResponse | Exception, one per call."""
    import urllib.request

    calls = {"n": 0, "payloads": []}

    def fake(req, timeout=None):
        idx = min(calls["n"], len(behavior) - 1)
        calls["n"] += 1
        try:
            calls["payloads"].append(json.loads(req.data.decode("utf-8")) if req.data else None)
        except Exception:
            calls["payloads"].append(None)
        item = behavior[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


# -- NVIDIA provider -----------------------------------------------------
def test_nvidia_generate_normalizes(monkeypatch):
    p = NvidiaProvider(api_key="k")
    mock_urlopen(monkeypatch, [FakeHTTPResponse(nvidia_chat("hello", "m"))])
    resp = p.generate("m", [{"role": "user", "content": "hi"}])
    assert resp.text == "hello"
    assert resp.model_id == "m"
    assert resp.provider == "nvidia"
    assert resp.finish_reason == "stop"
    assert resp.usage["total_tokens"] == 7


def test_nvidia_auth_error_no_retry(monkeypatch):
    p = NvidiaProvider(api_key="bad", max_retries=3)
    calls = mock_urlopen(monkeypatch, [http_error(401, "invalid key")])
    try:
        p.generate("m", [{"role": "user", "content": "hi"}])
        assert False, "should raise"
    except ModelError as e:
        assert e.category == FailureCategory.AUTH_ERROR
        assert e.retryable is False
        assert e.status_code == 401
    assert calls["n"] == 1  # auth errors fail fast, no retry


def test_nvidia_missing_key_is_auth_error():
    p = NvidiaProvider(api_key="")
    try:
        p.generate("m", [{"role": "user", "content": "hi"}])
        assert False, "should raise"
    except ModelError as e:
        assert e.category == FailureCategory.AUTH_ERROR


def test_nvidia_rate_limit_retries_then_succeeds(monkeypatch):
    p = NvidiaProvider(api_key="k", max_retries=2, retry_backoff_s=0)
    calls = mock_urlopen(monkeypatch, [http_error(429, "rate limited"), FakeHTTPResponse(nvidia_chat("ok"))])
    resp = p.generate("m", [{"role": "user", "content": "hi"}])
    assert resp.text == "ok"
    assert calls["n"] == 2


def test_nvidia_404_unavailable_no_retry(monkeypatch):
    p = NvidiaProvider(api_key="k", max_retries=3)
    calls = mock_urlopen(monkeypatch, [http_error(404, "not found")])
    try:
        p.generate("m", [{"role": "user", "content": "hi"}])
        assert False
    except ModelError as e:
        assert e.category == FailureCategory.UNAVAILABLE
    assert calls["n"] == 1


def test_nvidia_timeout_category(monkeypatch):
    p = NvidiaProvider(api_key="k", max_retries=1)
    mock_urlopen(monkeypatch, [socket.timeout("timed out")])
    try:
        p.generate("m", [{"role": "user", "content": "hi"}])
        assert False
    except ModelError as e:
        assert e.category == FailureCategory.TIMEOUT


def test_nvidia_stream_parses_sse(monkeypatch):
    p = NvidiaProvider(api_key="k")
    lines = [
        b'data: {"choices": [{"delta": {"content": "hel"}}]}',
        b'data: {"choices": [{"delta": {"content": "lo"}}]}',
        b'data: [DONE]',
    ]
    mock_urlopen(monkeypatch, [FakeHTTPResponse({}, lines=lines)])
    assert "".join(p.stream("m", [{"role": "user", "content": "hi"}])) == "hello"


def test_nvidia_tool_call_parses(monkeypatch):
    p = NvidiaProvider(api_key="k")
    tools = [{"id": "1", "function": {"name": "get_time", "arguments": "{}"}}]
    mock_urlopen(monkeypatch, [FakeHTTPResponse(nvidia_chat("", tools=tools))])
    resp = p.tool_call("m", [{"role": "user", "content": "time?"}], [{"type": "function"}])
    assert resp.tool_calls[0]["name"] == "get_time"


def test_nvidia_vision_payload_shape(monkeypatch):
    p = NvidiaProvider(api_key="k")
    calls = mock_urlopen(monkeypatch, [FakeHTTPResponse(nvidia_chat("a cat"))])
    resp = p.vision("m", "describe", "QUJD", "image/png")
    assert resp.text == "a cat"
    content = calls["payloads"][0]["messages"][0]["content"]
    kinds = {c["type"] for c in content}
    assert {"text", "image_url"} <= kinds
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD")


def test_nvidia_embed_posts_input_type(monkeypatch):
    p = NvidiaProvider(api_key="k")
    calls = mock_urlopen(monkeypatch, [FakeHTTPResponse({"data": [{"embedding": [0.1, 0.2]}]})])
    out = p.embed("e", ["hi"], input_type="passage")
    assert out["embeddings"] == [[0.1, 0.2]]
    assert calls["payloads"][0]["input_type"] == "passage"


def test_nvidia_rerank_404_maps_unavailable(monkeypatch):
    p = NvidiaProvider(api_key="k")
    mock_urlopen(monkeypatch, [http_error(404, "nope")])
    try:
        p.rerank("m", "q", ["a"])
        assert False
    except ModelError as e:
        assert e.category == FailureCategory.UNAVAILABLE


def test_nvidia_health_check_ok_and_fail(monkeypatch):
    p = NvidiaProvider(api_key="k", max_retries=1)
    mock_urlopen(monkeypatch, [FakeHTTPResponse(nvidia_chat("OK"))])
    ok = p.health_check("m", timeout_s=5)
    assert ok["ok"] is True and ok["category"] == ""
    mock_urlopen(monkeypatch, [http_error(500, "boom")])
    bad = p.health_check("m", timeout_s=5)
    assert bad["ok"] is False and bad["category"] == FailureCategory.SERVER_ERROR.value


# -- Gemini provider -----------------------------------------------------
def test_gemini_generate_normalizes_and_chain(monkeypatch):
    g = GeminiProvider(api_key="k", models=["m1", "m2"])
    calls = mock_urlopen(
        monkeypatch,
        [http_error(404, "not found"), FakeHTTPResponse({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})],
    )
    resp = g.generate("", [{"role": "user", "content": "hi"}])
    assert resp.text == "hi"
    assert resp.model_id == "m2"  # fell through to next model in chain
    assert calls["n"] == 2


def test_gemini_no_key_auth_error():
    g = GeminiProvider(api_key="")
    try:
        g.generate("m", [{"role": "user", "content": "hi"}])
        assert False
    except ModelError as e:
        assert e.category == FailureCategory.AUTH_ERROR


def test_gemini_vision_inline_data(monkeypatch):
    g = GeminiProvider(api_key="k")
    calls = mock_urlopen(
        monkeypatch, [FakeHTTPResponse({"candidates": [{"content": {"parts": [{"text": "txt"}]}}]})]
    )
    resp = g.vision("m", "extract", "QUJD", "image/png")
    assert resp.text == "txt"
    part = calls["payloads"][0]["contents"][0]["parts"][0]
    assert part["inline_data"] == {"mime_type": "image/png", "data": "QUJD"}


def test_gemini_unsupported_methods():
    g = GeminiProvider(api_key="k")
    for fn in (lambda: g.embed("m", ["x"]), lambda: g.rerank("m", "q", ["x"]), lambda: g.tool_call("m", [], [])):
        try:
            fn()
            assert False
        except ModelError as e:
            assert e.category == FailureCategory.UNSUPPORTED_CAPABILITY
            assert e.retryable is False


# -- registry ------------------------------------------------------------
def _tmp_registry():
    path = os.path.join(tempfile.mkdtemp(), "reg.json")
    return ModelRegistry(store_path=path)


def test_registry_register_get_statuses():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="m1", provider="nvidia", display_name="M1"))
    assert r.get("m1").status == ModelStatus.DISCOVERED.value
    r.set_status("m1", ModelStatus.UNAVAILABLE, note="404")
    assert r.get("m1").status == ModelStatus.UNAVAILABLE.value
    assert r.get("m1").enabled is False


def test_registry_free_filtering_and_enable_guard():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="paid", provider="nvidia", free_endpoint=False,
                           validated=True, status=ModelStatus.VALIDATED.value))
    assert r.set_enabled("paid", True) is None  # refused: not FREE
    assert r.get("paid").enabled is False
    r.register(ModelRecord(model_id="unval", provider="nvidia", free_endpoint=True,
                           validated=False, status=ModelStatus.DISCOVERED.value))
    assert r.set_enabled("unval", True) is None  # refused: not validated
    r.register(ModelRecord(model_id="good", provider="nvidia", free_endpoint=True,
                           validated=True, status=ModelStatus.VALIDATED.value,
                           capabilities=["chat"], fallback_group="primary"))
    assert r.set_enabled("good", True) is not None
    assert [m.model_id for m in r.free_enabled()] == ["good"]


def test_registry_health_tracking():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="m", provider="nvidia"))
    r.record_failure("m", "timeout")
    r.record_failure("m", "rate_limited")
    rec = r.get("m")
    assert rec.consecutive_failures == 2
    assert rec.rate_limits == 1
    assert rec.last_failure
    r.record_success("m", 1.5)
    rec = r.get("m")
    assert rec.consecutive_failures == 0
    assert rec.latency == 1.5
    assert rec.last_success


def test_registry_persistence():
    path = os.path.join(tempfile.mkdtemp(), "reg.json")
    r = ModelRegistry(store_path=path)
    r.register(ModelRecord(model_id="m", provider="nvidia", capabilities=["chat"]))
    r.record_failure("m", "timeout")
    r.save()
    r2 = ModelRegistry(store_path=path)
    assert r2.get("m").failure_category == "timeout"
    assert r2.get("m").capabilities == ["chat"]


# -- catalog -------------------------------------------------------------
def test_catalog_unique_and_resolution_honest():
    names = [e["candidate"] for e in model_catalog.SUPPLIED_CANDIDATES]
    assert len(names) == len(set(names))  # deduplicated
    assert len(names) >= 90
    live = ["z-ai/glm-5.3-flash", "nvidia/nemotron-3.5-lightning-30b-a3b"]
    assert mv.resolve_endpoint_id("GLM-5.3-Flash", live) == "z-ai/glm-5.3-flash"
    assert mv.resolve_endpoint_id("Inkling", live) is None  # never invented
    assert mv.resolve_endpoint_id("GPT-OSS-120B", ["openai/gpt-oss-20b"]) is None  # no lookalikes
    assert mv.resolve_endpoint_id("Mistral Medium 3", ["mistralai/mistral-7b-instruct-v0.3"]) is None
    assert mv.resolve_endpoint_id("Llama 3.1 8B Instruct",
                                  ["nvidia/llama-3.1-nemotron-safety-guard-8b-v3"]) is None


# -- validation ----------------------------------------------------------
class FakeProvider:
    provider_name = "fake"

    def __init__(self, health_ok=True, text="VALIDATED", tool_ok=True):
        self.health_ok = health_ok
        self.text = text
        self.tool_ok = tool_ok

    def health_check(self, model, timeout_s=60):
        return {"ok": self.health_ok, "latency_s": 0.1, "category": "" if self.health_ok else "unavailable",
                "message": "ok" if self.health_ok else "down", "model": model}

    def generate(self, model, messages, temperature=0.0, max_tokens=32, timeout_s=60):
        from backend.agent.model_interface import ModelResponse

        return ModelResponse(text=self.text, model_id=model, provider="fake")

    def tool_call(self, model, messages, tools, timeout_s=60):
        from backend.agent.model_interface import ModelResponse

        if not self.tool_ok:
            raise ModelError("no tools", FailureCategory.UNSUPPORTED_CAPABILITY, retryable=False)
        return ModelResponse(text="", model_id=model, provider="fake",
                             tool_calls=[{"name": "get_time"}])


def test_validation_success_enables_free_only():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="m", provider="fake", free_endpoint=True, capabilities=["chat"]))
    out = mv.validate_model(FakeProvider(), r, "m", timeout_s=10)
    assert out["ok"] is True and out["enabled"] is True
    rec = r.get("m")
    assert rec.validated and rec.enabled and rec.status == ModelStatus.ENABLED.value


def test_validation_failure_maps_status():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="m", provider="fake", free_endpoint=True))
    out = mv.validate_model(FakeProvider(health_ok=False), r, "m", timeout_s=10)
    assert out["ok"] is False
    assert r.get("m").status == ModelStatus.UNAVAILABLE.value
    assert r.get("m").enabled is False


def test_validation_empty_generate_fails():
    r = _tmp_registry()
    r.register(ModelRecord(model_id="m", provider="fake", free_endpoint=True))
    out = mv.validate_model(FakeProvider(text="   "), r, "m", timeout_s=10)
    assert out["ok"] is False


# -- router --------------------------------------------------------------
def _router_with(models):
    r = _tmp_registry()
    for m in models:
        r.register(m)
    providers = {"nvidia": FakeProvider(), "gemini": FakeProvider()}
    providers["nvidia"].provider_name = "nvidia"
    providers["gemini"].provider_name = "gemini"
    return r, ModelRouter(r, providers)


def _rec(mid, group="general", caps=("chat",), prio=50, fails=0, provider="nvidia"):
    return ModelRecord(model_id=mid, provider=provider, free_endpoint=True, validated=True,
                       enabled=True, status=ModelStatus.ENABLED.value, capabilities=list(caps),
                       priority=prio, fallback_group=group, consecutive_failures=fails)


def test_router_routes_by_task():
    r, router = _router_with([
        _rec("primary-chat", group="primary"),
        _rec("heavy-reason", group="heavy", caps=("chat", "reasoning")),
        _rec("mm-vision", group="multimodal", caps=("chat", "vision")),
    ])
    assert router.route(profile_for("general"))[0].model_id == "primary-chat"
    assert router.route(profile_for("reasoning"))[0].model_id == "heavy-reason"
    assert router.route(profile_for("vision"))[0].model_id == "mm-vision"


def test_router_skips_unhealthy_and_nonfree():
    r, router = _router_with([
        _rec("sick", group="primary", fails=5),
        _rec("ok", group="general"),
    ])
    assert router.route(profile_for("general"))[0].model_id == "ok"
    # paid/unvalidated entries never surface
    r.register(ModelRecord(model_id="paid", provider="nvidia", free_endpoint=False,
                           validated=True, enabled=True, status=ModelStatus.ENABLED.value))
    assert all(m.free_endpoint for m in router.candidates(profile_for("general")))


def test_router_no_candidate_raises():
    r, router = _router_with([])
    try:
        router.route(profile_for("coding"))
        assert False
    except ModelError as e:
        assert e.category == FailureCategory.UNAVAILABLE


def test_router_fallback_bounded_and_records_health(monkeypatch):
    from backend.agent.model_interface import ModelResponse

    r = _tmp_registry()
    r.register(_rec("first", group="primary", prio=1))
    r.register(_rec("second", group="general", prio=2))

    class Flaky:
        provider_name = "nvidia"
        calls = []

        def generate(self, model, messages, temperature=0.2, max_tokens=2048, timeout_s=120):
            self.calls.append(model)
            if model == "first":
                raise ModelError("timeout", FailureCategory.TIMEOUT)
            return ModelResponse(text="recovered", model_id=model, provider="nvidia")

    flaky = Flaky()
    router = ModelRouter(r, {"nvidia": flaky}, max_fallback_attempts=4)
    resp = router.generate_with_fallback(profile_for("general"), [{"role": "user", "content": "hi"}])
    assert resp.text == "recovered"
    assert flaky.calls == ["first", "second"]  # each tried at most once
    assert r.get("first").consecutive_failures == 1
    assert r.get("second").consecutive_failures == 0


def test_router_all_fail_raises_without_endless_retry():
    class Dead:
        provider_name = "nvidia"
        calls = 0

        def generate(self, model, messages, temperature=0.2, max_tokens=2048, timeout_s=120):
            self.calls += 1
            raise ModelError("down", FailureCategory.SERVER_ERROR)

    r = _tmp_registry()
    r.register(_rec("a", group="primary", prio=1))
    r.register(_rec("b", group="general", prio=2))
    dead = Dead()
    router = ModelRouter(r, {"nvidia": dead}, max_fallback_attempts=4)
    try:
        router.generate_with_fallback(profile_for("general"), [{"role": "user", "content": "hi"}])
        assert False
    except ModelError:
        pass
    assert dead.calls == 2  # bounded: one try per candidate


# -- event-loop responsiveness (planner runs in worker thread) ------------
def test_core_planning_does_not_block_event_loop():
    """Slow blocking plan_task must not stall the asyncio loop (health
    checks + SSE). Fails if planning runs inline on the loop."""
    import asyncio
    import time

    from backend.agent.core import AgentCore
    from backend.agent.state import ActionSpec, Plan, TaskState, TaskType

    core = AgentCore()

    def slow_plan(task, state):
        time.sleep(2)  # blocking LLM-style call
        spec = ActionSpec(type="speak", description="Done",
                          parameters={"text": "hi"}, is_critical=False)
        state.task = task
        state.interpreted_goal = task
        state.plan = Plan(actions=[spec], goal=task,
                          task_type=TaskType.SIMPLE, is_valid=True)
        return [spec]

    core.planner.plan_task = slow_plan
    beats = []

    async def main():
        async def heartbeat():
            while True:
                beats.append(time.monotonic())
                await asyncio.sleep(0.1)

        hb = asyncio.create_task(heartbeat())
        try:
            # NOTE: task must be plannable-as-is; vague tasks ("hi") pause
            # for a clarification question by design (see
            # test_clarification_round_trip). This test measures loop
            # blocking, so it uses a valid task with a mocked planner.
            return await core.process("Show git status", TaskState(), None)
        finally:
            hb.cancel()

    res = asyncio.run(main())
    assert res["status"] in ("completed", "partial")
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert gaps, "heartbeat never ticked"
    assert max(gaps) < 1.0, f"event loop blocked: max gap {max(gaps):.2f}s"


# -- tool schema regression (live-run bug: browser_extract crashed) ------
def test_browser_result_schema_accepts_all_caller_kwargs():
    """BrowserActionResult must accept every kwarg browser.py passes.
    Regression: get_page_text(text=...) raised TypeError, failing every
    browser_extract step and forcing needless replans."""
    from backend.tools.result_schema import create_browser_result

    shapes = [
        dict(text="abc", selector="body"),
        dict(text="abc", title="T", url="U"),
        dict(value="v"),
        dict(before_url="a", url="b", title="T"),
        dict(query="q", results=[], url="u", title="T", page_state="s"),
        dict(page_state="s", retryable=True, details={}),
        dict(links=["x"]),
        dict(path="p"),
    ]
    for kw in shapes:
        d = create_browser_result("op", "success", "msg", **kw)
        for k, v in kw.items():
            if v:  # to_dict() omits unset/empty optionals by design
                assert d.get(k) == v, (k, v)
    # Every result dict must be JSON-serializable (base-class `error`
    # field/method collision used to leak a bound method here).
    import json as _json

    _json.dumps(create_browser_result("op", "success", "msg", text="x"))


# -- planner fast path (small tasks must not pay LLM latency) ------------
def test_simple_task_classification():
    from backend.agent.planner import _is_simple_task

    simple = [
        "calculate 12 * 8",
        "open notepad and type hello",
        "create folder JARVIS_TEST on Desktop",
        "take a screenshot",
        "https://example.com what is this page",
        "search for OpenAI website",
        "click the Save button",
    ]
    complex_tasks = [
        "research Python history and create a Word document",
        "create a PowerPoint presentation on AI from 3 websites",
        "gather info from 5 sources into a report",
    ]
    for t in simple:
        assert _is_simple_task(t) is True, t
    for t in complex_tasks:
        assert _is_simple_task(t) is False, t


def test_simple_tasks_plan_without_llm(monkeypatch):
    """Planner must not touch any LLM for simple tasks (fast path)."""
    from backend.agent import planner as planner_mod
    from backend.agent.state import TaskState

    def no_llm(*a, **k):
        raise AssertionError("LLM must not be called for simple tasks")

    monkeypatch.setattr(planner_mod, "_call_router_for_plan", no_llm)
    monkeypatch.setattr(planner_mod, "_call_gemini_for_plan", no_llm)

    import time

    planner = planner_mod.Planner()
    t0 = time.time()
    actions = planner.plan_task("calculate 12 * 8", TaskState())
    assert time.time() - t0 < 20, "simple planning took too long"
    assert [a.type for a in actions] == ["calculator_compute", "speak"]

    actions = planner.plan_task("open notepad and type hello", TaskState())
    assert [a.type for a in actions] == ["open_app_wait", "type_in_app", "speak"]
    # Regression: must type the dictated text, never the whole command.
    assert actions[1].parameters.get("text") == "hello"


# -- browser redirect unwrap (benchmark bug: Scholar wrapper mismatch) ---
def test_unwrap_search_url():
    """Redirect wrappers must unwrap to the destination; plain URLs pass
    through. Regression: Scholar scholar_url wrappers navigated fine but
    verification compared against the wrapper -> false mismatch -> 6
    wasted retries -> task failure."""
    from backend.tools.browser import unwrap_search_url

    assert unwrap_search_url(
        "https://scholar.google.co.in/scholar_url?url=https://www.example.com/a&hl=en"
    ) == "https://www.example.com/a"
    assert unwrap_search_url(
        "https://www.google.com/url?q=https://www.example.com/b&sa=t"
    ) == "https://www.example.com/b"
    assert unwrap_search_url("https://www.example.com/plain") == "https://www.example.com/plain"
    assert unwrap_search_url("") == ""


# -- graceful source skip (benchmark: one dead source killed the task) --
def test_should_skip_empty_source():
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState

    s = TaskState()
    assert AgentCore._should_skip_empty_source(s, "Extraction yielded no meaningful content") is False
    s.extracted_sources = [{"text": "x" * 100}]
    assert AgentCore._should_skip_empty_source(s, "Extraction yielded no meaningful content") is False
    s.extracted_sources.append({"text": "y" * 200})
    assert AgentCore._should_skip_empty_source(s, "Extraction yielded no meaningful content") is True
    assert AgentCore._should_skip_empty_source(s, "Some other error") is False


# -- rules-first planning (research must not pay LLM latency) ------------
def test_rules_first_skips_llm_for_covered_tasks(monkeypatch):
    """plan_task must not touch any LLM when rules cover the task."""
    from backend.agent import planner as planner_mod
    from backend.agent.state import TaskState

    def no_llm(*a, **k):
        raise AssertionError("LLM must not be called when rules cover the task")

    monkeypatch.setattr(planner_mod, "_call_router_for_plan", no_llm)
    monkeypatch.setattr(planner_mod, "_call_gemini_for_plan", no_llm)

    import time

    planner = planner_mod.Planner()
    t0 = time.time()
    actions = planner.plan_task(
        "research the history of artificial intelligence from 3 websites and create a Word document",
        TaskState(),
    )
    assert time.time() - t0 < 20, "rules-first planning took too long"
    types = [a.type for a in actions]
    assert types.count("browser_navigate") == 3
    assert types.count("browser_extract") == 3
    assert "create_docx" in types


def test_degenerate_tasks_still_use_llm(monkeypatch):
    """Genuinely uncovered tasks must still reach the LLM path."""
    from backend.agent import planner as planner_mod
    from backend.agent.state import TaskState

    seen = {}

    def fake_router(task, prompt, timeout_s=0):
        seen["router"] = True
        return None

    def fake_legacy(task, api_key, prompt):
        seen["legacy"] = True
        return None

    monkeypatch.setattr(planner_mod, "_call_router_for_plan", fake_router)
    monkeypatch.setattr(planner_mod, "_call_gemini_for_plan", fake_legacy)
    planner = planner_mod.Planner()
    actions = planner.plan_task("do something utterly bizarre xyz123", TaskState())
    assert seen.get("router") and seen.get("legacy")
    assert [a.type for a in actions] == ["speak"]


# -- planner wiring ------------------------------------------------------
def test_planner_router_hook_falls_back_silently(monkeypatch):
    from backend.agent import planner as planner_mod
    from backend.agent import model_router as router_mod

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(router_mod.ModelRouter, "generate_with_fallback", boom)
    assert planner_mod._call_router_for_plan("do x", "sys") is None


def test_planner_router_hook_parses_plan(monkeypatch):
    from backend.agent import planner as planner_mod
    from backend.agent import model_router as router_mod
    from backend.agent.model_interface import ModelResponse

    plan = [{"type": "speak", "description": "Done", "text": "hi"}]

    def fake_gen(self, profile, messages, temperature=0.1, max_tokens=4096, timeout_s=90):
        return ModelResponse(text=json.dumps(plan), model_id="m", provider="nvidia")

    monkeypatch.setattr(router_mod.ModelRouter, "generate_with_fallback", fake_gen)
    # Point the factory at an isolated registry with one ENABLED model.
    import backend.agent.model_factory as factory_mod

    real_build = factory_mod.build_router

    def fake_build():
        rr = _tmp_registry()
        rr.register(_rec("m", group="primary"))
        return rr, {"nvidia": FakeProvider()}, ModelRouter(rr, {"nvidia": FakeProvider()})

    monkeypatch.setattr(factory_mod, "build_router", fake_build)
    out = planner_mod._call_router_for_plan("do x", "sys")
    assert out == plan
    monkeypatch.setattr(factory_mod, "build_router", real_build)

# -- high-end benchmark: planner covers dual artifacts, hyphen slides, folders --
def test_highend_hyphen_slide_count():
    from backend.agent import planner as P
    params = P._extract_research_parameters(
        "Research EV vs Hydrogen cars from 6 sources and create a 10-slide PowerPoint with charts")
    assert params["target_slides"] == 10
    assert params["num_sources"] == 6
    assert params["is_presentation"] is True


def test_highend_dual_artifact_plan():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task(
        "Research quantum computing from 5 sources and create BOTH a Word report AND a 10-slide PowerPoint", st)
    types = [s.type for s in specs]
    assert "create_docx" in types and "create_pptx" in types
    assert types.count("browser_extract") == 5
    assert st.plan.is_valid


def test_highend_folder_scaffolding_not_research():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task(
        "Create folder ProjectX on desktop with 3 subfolders and a summary file inside each", st)
    types = [s.type for s in specs]
    assert "browser_search" not in types
    assert types.count("create_folder_verified") == 4
    assert types.count("write_file_verified") == 3
    assert st.plan.is_valid


def test_highend_output_folder_and_topic():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    task = "Research cybersecurity threats 2026 from 5 sources and save the Word report plus a 10-slide PowerPoint inside a new folder CyberPack on desktop"
    params = P._extract_research_parameters(task)
    assert params["output_folder"] == "CyberPack"
    assert params["topic"] == "cybersecurity threats 2026"
    assert params["is_document"] and params["is_presentation"]
    st = TaskState()
    specs = P.Planner().plan_task(task, st)
    types = [s.type for s in specs]
    assert types[0] == "create_folder_verified"
    assert "create_docx" in types and "create_pptx" in types
    assert st.plan.is_valid

# -- Browser Pro pack: downloads, assisted login, parallel tabs, table CSV --
def test_browserpro_download_plan():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task("Download https://example.com/report.pdf", st)
    assert [s.type for s in specs] == ["browser_download", "speak"]
    assert specs[0].parameters["url"] == "https://example.com/report.pdf"
    assert st.plan.is_valid


def test_browserpro_login_plan_never_stores_password():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task(
        "Log in to https://example.com/login as user@example.com", st)
    types = [s.type for s in specs]
    assert types == ["browser_login", "browser_login_check", "speak"]
    assert specs[0].parameters.get("username") == "user@example.com"
    assert "password" not in specs[0].parameters
    assert st.plan.is_valid


def test_browserpro_parallel_plan():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task(
        "Compare https://a.com/page and https://b.com/other for me", st)
    assert specs[0].type == "browser_parallel_research"
    assert specs[0].parameters["urls"] == ["https://a.com/page", "https://b.com/other"]
    assert st.plan.is_valid


def test_browserpro_table_plan():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    st = TaskState()
    specs = P.Planner().plan_task(
        "Open https://example.com/data and save the table as data.csv", st)
    assert [s.type for s in specs] == ["browser_navigate", "browser_extract_table", "speak"]
    assert specs[1].parameters["filename"] == "data.csv"
    assert st.plan.is_valid


def test_browserpro_not_simple_tasks():
    from backend.agent import planner as P
    assert P._is_simple_task("Download https://example.com/f.pdf") is False
    assert P._is_simple_task("Log in to https://example.com/login") is False
    assert P._is_simple_task("Open https://example.com/d and save the table") is False
    # Generic single-URL reads stay on the fast path.
    assert P._is_simple_task("Summarize https://example.com/a") is True


def test_browserpro_observer_branches():
    import asyncio
    from backend.agent.state import TaskState, ActionSpec
    from backend.agent.observer import Observer
    async def go():
        obs = Observer()
        st = TaskState()
        mk = lambda t: ActionSpec(type=t, description=t)
        d = tempfile.mkdtemp()
        dl = os.path.join(d, "f.pdf")
        with open(dl, "w") as f:
            f.write("x")
        r = await obs.observe_after_action(mk("browser_download"), {"status": "success", "path": dl}, st, None)
        assert r["classification"] == "success"
        r = await obs.observe_after_action(mk("browser_login"), {"status": "human_verification_required"}, st, None)
        assert r["classification"] == "human_required"
        r = await obs.observe_after_action(mk("browser_login_check"), {"status": "success", "logged_in": True}, st, None)
        assert r["classification"] == "success"
        r = await obs.observe_after_action(mk("browser_login_check"), {"status": "error", "logged_in": False}, st, None)
        assert r["classification"] == "human_required"
        r = await obs.observe_after_action(mk("browser_parallel_research"), {"status": "success", "sources": [{"url": "u"}]}, st, None)
        assert r["classification"] == "success"
        csvp = os.path.join(d, "t.csv")
        with open(csvp, "w") as f:
            f.write("a,b\n")
        r = await obs.observe_after_action(mk("browser_extract_table"), {"status": "success", "path": csvp}, st, None)
        assert r["classification"] == "success"
    asyncio.run(go())


def test_browserpro_login_requires_user():
    from backend.agent.state import ActionSpec
    from backend.agent.verifier import Verifier
    r = Verifier().verify_action(
        ActionSpec(type="browser_login", description="x"),
        {"status": "human_verification_required", "message": "m"},
        {"verified": False, "message": "Login needs human completion", "classification": "human_required"})
    assert r["status"] == "human_required" and r["requires_user"] is True


def test_browserpro_table_csv_saved():
    import asyncio
    import csv as _csv
    from backend.agent.executor import Executor
    from backend.agent.state import TaskState
    class FakeBrowser:
        async def extract_tables(self):
            return {"status": "success", "message": "ok",
                    "tables": [{"caption": "", "headers": ["A", "B"], "rows": [["1", "2"]]}]}
    async def go():
        ex = Executor.__new__(Executor)
        async def _fake():
            return FakeBrowser()
        ex._get_browser = _fake
        st = TaskState()
        d = tempfile.mkdtemp()
        res = await ex._browser_extract_table({"filename": "out.csv", "save_dir": d}, st)
        assert res["status"] == "success"
        with open(res["path"], encoding="utf-8-sig") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == ["A", "B"] and rows[1] == ["1", "2"]
    asyncio.run(go())

# -- Dev Terminal pack: policy gates, planner routing, verify chain --
def test_terminal_policy_blocks():
    from backend.tools import terminal as T
    assert T.check_policy(["rm", "-rf", "/"]) is not None
    assert T.check_policy(["git", "push", "origin", "main"]) is not None
    assert T.check_policy(["git", "commit", "-am", "x"]) is not None
    assert T.check_policy(["git", "-c", "x=y", "status"]) is not None
    assert T.check_policy(["python", "-c", "1"]) is not None
    assert T.check_policy(["python", "-m", "pip", "install", "x"]) is not None
    assert T.check_policy(["python", "../../evil.py"]) is not None
    assert T.check_policy(["git", "status", "|", "cat"]) is not None
    assert T.check_policy(["powershell", "-Command", "x"]) is not None


def test_terminal_policy_allows():
    from backend.tools import terminal as T
    for cmd in (["git", "status"], ["git", "diff"], ["git", "log"],
                ["python", "-m", "pytest", "-q"], ["pip", "list"],
                ["npm", "ls"], ["echo", "hi"], ["dir"], ["pwd"]):
        assert T.check_policy(cmd) is None, cmd


def test_terminal_native_and_confinement():
    from backend.tools import terminal as T
    r = T.run("echo hello")
    assert r["status"] == "success" and r["stdout"] == "hello"
    r = T.run("dir backend/tools")
    assert r["status"] == "success" and "terminal.py" in r["stdout"]
    r = T.run("git status", workdir="../../..")
    assert r["status"] == "error" and "outside workspace" in r["message"]
    r = T.run("git push origin main")
    assert r["status"] == "error" and "Blocked by terminal policy" in r["message"]


def test_terminal_planner_routing():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    pl = P.Planner()
    st = TaskState()
    assert [s.type for s in pl.plan_task("Run the test suite", st)][:1] == ["run_tests"]
    assert st.plan.is_valid
    st = TaskState()
    specs = pl.plan_task("Show git status", st)
    assert specs[0].type == "git_op" and specs[0].parameters["operation"] == "status"
    assert st.plan.is_valid
    st = TaskState()
    specs = pl.plan_task("Run dir work_files", st)
    assert specs[0].type == "run_shell" and specs[0].parameters["command"] == "dir work_files"
    assert st.plan.is_valid
    # Existing routes unaffected.
    assert P._is_simple_task("Calculate 48*25") is True
    assert P._is_simple_task("Run the test suite") is True


def test_terminal_verify_chain_live():
    import asyncio
    from backend.agent.executor import Executor
    from backend.agent.observer import Observer
    from backend.agent.verifier import Verifier
    from backend.agent.state import TaskState, ActionSpec
    async def go():
        ex = Executor.__new__(Executor)
        obs, ver, st = Observer(), Verifier(), TaskState()
        action = ActionSpec(type="git_op", description="x", parameters={"operation": "status"})
        res = await ex._git_op({"operation": "status"}, st)
        ob = await obs.observe_after_action(action, res, st, None)
        v = ver.verify_action(action, res, ob)
        assert v["status"] == "success" and v["verified"] is True
        bad = ActionSpec(type="run_shell", description="x", parameters={"command": "git push origin main"})
        res2 = await ex._run_shell({"command": "git push origin main"}, st)
        ob2 = await obs.observe_after_action(bad, res2, st, None)
        v2 = ver.verify_action(bad, res2, ob2)
        assert v2["status"] == "fatal" and v2["should_retry"] is False
    asyncio.run(go())

# -- Speak evidence: completion replies must carry the actual result --
def test_speak_evidence_terminal_output():
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.update_context("last_shell_output", "On branch main")
    assert AgentCore._collect_speak_evidence(st) == "On branch main"
    # Consume-once: second call is empty, plain speaks stay unchanged.
    assert AgentCore._collect_speak_evidence(st) == ""
    assert AgentCore._collect_speak_evidence(TaskState()) == ""


def test_speak_evidence_download_and_table():
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.update_context("last_download_path", "C:/dl/f.pdf")
    st.update_context("last_table_path", "C:/dl/t.csv")
    st.update_context("last_table_rows", 42)
    ev = AgentCore._collect_speak_evidence(st)
    assert "C:/dl/f.pdf" in ev and "C:/dl/t.csv" in ev and "42 rows" in ev


def test_speak_evidence_compresses_long_output():
    # A 5000-char dump never reaches the chat raw; it becomes a summary.
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.update_context("last_shell_output", "x" * 5000)
    ev = AgentCore._collect_speak_evidence(st)
    assert len(ev) <= 601 and ev.endswith("…")


def test_speak_evidence_summarizes_shell_output():
    # Long shell dumps are analyzed into short summaries, not pasted raw.
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.update_context("last_shell_output", "\n".join(f"line{i}" for i in range(30)))
    st.update_context("last_shell_command", "npm ls")
    st.update_context("last_shell_exit", 0)
    ev = AgentCore._collect_speak_evidence(st)
    assert "more lines" in ev and "line29" not in ev
    # Explicit full-output requests still get the raw text (capped).
    st2 = TaskState()
    st2.task = "Show full output of the tests"
    st2.update_context("last_shell_output", "y" * 5000)
    ev2 = AgentCore._collect_speak_evidence(st2)
    assert ev2.endswith("(truncated)")


def test_git_status_loop_speaks_output():
    import asyncio
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    async def go():
        out = await AgentCore().process("Show git status", TaskState())
        assert out["status"] == "completed"
        assert "On branch" in out["speak"] or "branch" in out["speak"].lower()
    asyncio.run(go())

# -- Summary replies: short analysis, not raw dumps --
def test_terminal_summarize_git_status():
    from backend.tools import terminal as T
    out = ("On branch main\nYour branch is up to date with \x27origin/main\x27.\n\n"
           "Changes not staged for commit:\n\tmodified:   a.py\n\tdeleted:    b.py\n\n"
           "Untracked files:\n\tx/\n\nno changes added")
    s = T.summarize_output("git status", out, 0)
    assert "Branch main" in s and "1 modified" in s and "1 untracked" in s
    assert "modified:   a.py" not in s  # no raw dump


def test_terminal_summarize_pytest_and_failures():
    from backend.tools import terminal as T
    s = T.summarize_output("python -m pytest -q", "....\nFAILED test_a.py::test_x\n86 passed, 1 failed in 4s", 0)
    assert "86 passed" in s and "test_a.py::test_x" in s
    s = T.summarize_output("git diff", "fatal: not a repo", 128)
    assert s.startswith("Command failed (exit 128)")


def test_terminal_summarize_listing_and_generic():
    from backend.tools import terminal as T
    assert T.summarize_output("dir", "a.py\nb.py", 0) == "2 entries: a.py, b.py."
    assert T.summarize_output("dir", "(empty directory)", 0) == "Directory is empty."
    long_text = "\n".join(f"line{i}" for i in range(20))
    s = T.summarize_output("npm ls", long_text, 0)
    assert "+16 more lines" in s


def test_git_status_loop_speaks_summary_not_dump():
    import asyncio
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    async def go():
        out = await AgentCore().process("Show git status", TaskState())
        assert out["status"] == "completed"
        assert "Branch" in out["speak"] and "modified" in out["speak"]
        assert "Changes not staged for commit" not in out["speak"]
    asyncio.run(go())

# -- Evidence replies: every command reports its actual result --
def _ev_state(**ctx):
    from backend.agent.state import TaskState
    st = TaskState()
    for k, v in ctx.items():
        st.update_context(k, v)
    return st


def _ev_action(tag):
    from backend.agent.state import ActionSpec
    return ActionSpec(type="speak", description="Done", parameters={"text": "Done, sir.", "evidence": tag})


def test_evidence_calc_result():
    from backend.agent.core import AgentCore
    st = _ev_state(last_calc_result="48*25 = 1200")
    ev = AgentCore._collect_speak_evidence(st, _ev_action("calc"))
    assert ev == "Result: 48*25 = 1200."


def test_evidence_search_titles():
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.search_results = [{"title": "Alpha"}, {"title": "Beta"}, {"title": "Gamma"}, {"title": "Delta"}]
    ev = AgentCore._collect_speak_evidence(st, _ev_action("search"))
    assert ev == "Top results: Alpha; Beta; Gamma."


def test_evidence_artifact_folder_typed_screenshot():
    from backend.agent.core import AgentCore
    st = _ev_state(artifact_paths=["C:/d/a.docx", "C:/d/a.pptx"])
    assert AgentCore._collect_speak_evidence(st, _ev_action("artifact")) == "Saved to: C:/d/a.docx, C:/d/a.pptx."
    st = _ev_state(last_folder_path="C:/d/X")
    assert AgentCore._collect_speak_evidence(st, _ev_action("folder")) == "Location: C:/d/X."
    st = _ev_state(last_typed_text="hello world")
    assert AgentCore._collect_speak_evidence(st, _ev_action("typed")) == "Text entered: \"hello world\"."
    st = _ev_state(last_screenshot_path="C:/s.png")
    assert AgentCore._collect_speak_evidence(st, _ev_action("screenshot")) == "Screenshot saved to: C:/s.png."
    # Untagged speaks never attach these (no cross-talk between plans).
    st = _ev_state(last_calc_result="1 = 1")
    assert AgentCore._collect_speak_evidence(st, None) == ""


def test_evidence_sources_from_parallel():
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    st = TaskState()
    st.extracted_sources = [{"title": "Page A", "url": "u1"}, {"title": "Page B", "url": "u2"}]
    ev = AgentCore._collect_speak_evidence(st, _ev_action("sources"))
    assert ev == "Sources: Page A; Page B."


def test_planner_speaks_carry_evidence_tags():
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    pl = P.Planner()
    st = TaskState()
    specs = pl.plan_task("Calculate 48*25", st)
    assert specs[-1].parameters.get("evidence") == "calc"
    st = TaskState()
    specs = pl.plan_task("Create folder EvCheck on desktop", st)
    assert specs[-1].parameters.get("evidence") == "folder"


def test_folder_loop_speaks_location():
    import asyncio
    import shutil
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    from system_ops import get_desktop_path
    import os as _os
    async def go():
        out = await AgentCore().process("Create folder EvCheck987 on desktop", TaskState())
        assert out["status"] == "completed"
        assert "Location:" in out["speak"] and "EvCheck987" in out["speak"]
    asyncio.run(go())
    _p = _os.path.join(get_desktop_path(), "EvCheck987")
    if _os.path.isdir(_p):
        shutil.rmtree(_p, ignore_errors=True)

# -- File homes: screenshots->laptop+album, docs->work_files/documents --
def test_storage_dirs_exist():
    import os as _os
    from system_ops import get_screenshots_dir, get_documents_dir, WORK_DIR
    shots = get_screenshots_dir()
    assert _os.path.isdir(shots)
    docs = get_documents_dir()
    assert _os.path.isdir(docs)
    assert _os.path.abspath(docs).startswith(_os.path.abspath(WORK_DIR))


def test_mirror_into_gallery():
    import os as _os
    import tempfile as _tf
    from system_ops import mirror_into_gallery, WORK_DIR
    d = _tf.mkdtemp()
    src = _os.path.join(d, "probe_shot.png")
    with open(src, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    dest = mirror_into_gallery(src)
    assert dest and _os.path.isfile(dest)
    assert _os.path.abspath(dest).startswith(_os.path.join(_os.path.abspath(WORK_DIR), "screenshots"))
    _os.remove(dest)
    # Files already inside work_files are not duplicated.
    inside = _os.path.join(WORK_DIR, "screenshots", "probe_shot.png")
    assert mirror_into_gallery(inside) == ""


def test_artifact_plans_target_documents():
    import os as _os
    from backend.agent import planner as P
    from backend.agent.state import TaskState
    from system_ops import get_documents_dir
    docs = _os.path.abspath(get_documents_dir())
    st = TaskState()
    specs = P.Planner().plan_task("Research AI trends from 3 websites and create a Word report", st)
    doc = next(s for s in specs if s.type == "create_docx")
    assert _os.path.abspath(doc.parameters["path"]).startswith(docs)
    from system_ops import get_desktop_path
    assert _os.path.abspath(doc.parameters["path"]) != _os.path.join(
        _os.path.abspath(get_desktop_path()), _os.path.basename(doc.parameters["path"]))
    st = TaskState()
    specs = P.Planner().plan_task(
        "Research quantum computing from 2 sources and create BOTH a Word report AND a 5-slide PowerPoint", st)
    for s in specs:
        if s.type in ("create_docx", "create_pptx", "verify_file", "create_folder_verified"):
            assert _os.path.abspath(s.parameters["path"]).startswith(docs), s.parameters["path"]


def test_observer_screenshot_accepts_both_keys():
    import asyncio
    import os as _os
    import tempfile as _tf
    from backend.agent.observer import Observer
    from backend.agent.state import TaskState, ActionSpec
    async def go():
        obs = Observer()
        st = TaskState()
        d = _tf.mkdtemp()
        p = _os.path.join(d, "s.png")
        with open(p, "wb") as f:
            f.write(b"x")
        mk = lambda: ActionSpec(type="screenshot_ui", description="x")
        r1 = await obs.observe_after_action(mk(), {"status": "success", "screenshot_path": p}, st, None)
        assert r1["classification"] == "success" and r1["path"] == p
        r2 = await obs.observe_after_action(mk(), {"status": "success", "path": p}, st, None)
        assert r2["classification"] == "success"
    asyncio.run(go())


def test_gallery_lists_album_files():
    import os as _os
    from main import get_gallery
    from system_ops import WORK_DIR
    probe = _os.path.join(WORK_DIR, "screenshots", "_probe_album.png")
    _os.makedirs(_os.path.dirname(probe), exist_ok=True)
    with open(probe, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    try:
        items = get_gallery()["images"]
        hit = [i for i in items if i["filename"] == "_probe_album.png"]
        assert hit and hit[0]["category"] == "pc_screenshot"
    finally:
        if _os.path.exists(probe):
            _os.remove(probe)

# -- Talk like an agent: narration, questions, personality --
def test_personality_narration():
    from backend.agent import personality as P
    assert "Step 2 of 5" in P.narrate_start("browser_search", "d", 1, 5, {"query": "AI"})
    assert P.narrate_start("speak", "d", 0, 1) == ""
    assert "tabs" in P.narrate_start("browser_parallel_research", "d", 0, 2, {"urls": ["a", "b"]})
    assert P.narrate_done("browser_search", {"message": "m", "results_count": 4})
    assert "attempt 2" in P.narrate_retry("download", 2)
    assert "sir" in P.narrate_waiting_human("finish the login", "login")
    assert P.serious("  boom  ") == "boom"
    assert "steps" in P.acknowledge("big", 10).lower()


def test_clarify_asks_only_when_blocked():
    from backend.agent import clarify as C
    for ok in ["Show git status", "Calculate 48*25",
               "Research AI trends from 5 websites and create a Word report",
               "Download https://example.com/f.pdf", "Take a screenshot",
               "Run the test suite", "Create folder X on desktop"]:
        assert C.needs_clarification(ok) is None, ok
    for vague, hint in [("fix it", "dangling pronoun"), ("summarize this", "missing source"),
                        ("research and make a report", "missing topic"), ("search", "missing query"),
                        ("create a file", "missing filename"), ("help", "vague task")]:
        r = C.needs_clarification(vague)
        assert r and r["hint"] == hint, vague
    assert C.apply_answer("research this", "quantum") == "research this [Clarification: quantum]"


def test_clarification_round_trip():
    import asyncio
    from backend.agent import clarify as C
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    async def go():
        core, st = AgentCore(), TaskState()
        events = []
        async def emit(t, m, d=None, icon=""):
            events.append((t, m, d or {}))
        async def answerer():
            for _ in range(100):
                await asyncio.sleep(0.05)
                if st.waiting_for_user:
                    break
            assert st.waiting_for_user
            await core.resume_after_human(st, {"answer": "quantum computing"})
        t = asyncio.create_task(answerer())
        out = await core._ask_clarification(
            "research and make a report", st,
            C.needs_clarification("research and make a report"), emit)
        await t
        assert out is not None and "quantum computing" in out
        assert [e for e in events if e[0] == "clarification_required"]
        assert st.clarification_done is True
    asyncio.run(go())

# -- Mid-run triage: related merges + restarts, unrelated queues --
def test_classify_instruction_verdicts():
    from backend.agent import clarify as C
    t = "Research AI trends from 5 sources and create a Word report"
    assert C.classify_instruction(t, "actually make it 7 sources")["related"] is True
    assert C.classify_instruction(t, "also add a PowerPoint deck")["related"] is True
    assert C.classify_instruction(t, "take a screenshot")["related"] is False
    assert C.classify_instruction("Show git status", "now run the test suite")["related"] is False
    assert C.classify_instruction("Download https://a.com/f.pdf", "Download https://b.com/g.pdf")["related"] is False
    assert C.classify_instruction(t, "save it as trends2.docx instead")["related"] is True
    assert C.is_interruption("stop everything") is True
    assert C.is_interruption("show git status") is False


def test_enqueue_instruction_verdicts():
    from backend.agent.core import AgentCore
    core = AgentCore()
    core._active_task = "Show git status"
    v = core.enqueue_instruction("now run the test suite", "Show git status")
    assert v["verdict"] == "queued"
    v = core.enqueue_instruction("actually show the full output", "Show git status")
    assert v["verdict"] == "merged"
    assert core.enqueue_instruction("  ")["verdict"] == "ignored"


def test_midrun_queued_task_runs_after():
    import asyncio
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    async def go():
        core = AgentCore()
        core.inject_mid_task_instruction("take a screenshot")
        out = await core.process("Show git status", TaskState())
        assert out["status"] == "completed"
        assert out.get("queued") == ["take a screenshot"]
        assert "Branch" in out["speak"]
    asyncio.run(go())


def test_midrun_related_change_restarts_plan():
    import asyncio
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    async def go():
        core = AgentCore()
        core.inject_mid_task_instruction("actually show the full output")
        out = await core.process("Show git status", TaskState())
        assert out["status"] == "completed"
        assert "Change:" in out["task"]
    asyncio.run(go())
