"""Phase 2 tests — persistent, searchable, project-aware memory.

Isolated SQLite DB per test (tmp_path); no network (embeddings/rerank are
monkeypatched or asserted offline). Covers every §23 topic: creation,
persistence, retrieval, update, deletion, forget, explicit remember/forget,
confidence, provenance, deduplication, conflicts, expiration, project memory,
embeddings, reranking, ranking, context limits, restart persistence,
corrupted/invalid records, privacy filtering, plus agent-loop integration.
"""
import os
import sqlite3
import time

import pytest

from backend.agent import memory_embeddings, memory_ranking, memory_rerank
from backend.agent.memory_api import JarvisMemory
from backend.agent.memory_schema import (
    Confidence,
    MemoryRecord,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from backend.agent.memory_store import MemoryStore


@pytest.fixture()
def store(tmp_path):
    return MemoryStore(str(tmp_path / "mem.db"))


@pytest.fixture()
def api(store):
    return JarvisMemory(store=store)


# -- creation / persistence / retrieval ---------------------------------------
def test_memory_creation_with_structured_fields(api):
    result = api.add("User prefers dark mode", memory_type=MemoryType.USER,
                     source=MemorySource.EXPLICIT_USER, tags=["preference"])
    assert result["status"] == "success"
    mem = result["memory"]
    for field in ("id", "memory_type", "content", "summary", "importance",
                  "confidence", "created_at", "updated_at", "last_accessed",
                  "access_count", "source", "project_id", "tags",
                  "embedding_id", "status", "sensitivity", "expiration"):
        assert field in mem, field
    assert mem["memory_type"] == "working" or mem["memory_type"] == "user"
    assert mem["confidence"] == Confidence.HIGH  # explicit user words
    assert mem["source"] == MemorySource.EXPLICIT_USER


def test_memory_types_are_distinct(api):
    for mtype in MemoryType.ALL:
        result = api.add(f"{mtype} fact {mtype}", memory_type=mtype,
                         source=MemorySource.SYSTEM_OBSERVATION)
        assert result["status"] == "success", (mtype, result)
        assert result["memory"]["memory_type"] == mtype
    for mtype in MemoryType.ALL:
        assert api.list(memory_type=mtype)["count"] == 1


def test_persistence_across_instances(tmp_path):
    path = str(tmp_path / "persist.db")
    first = JarvisMemory(store=MemoryStore(path))
    assert first.remember("my favorite color is blue")["status"] == "success"
    second = JarvisMemory(store=MemoryStore(path))  # simulated restart
    found = second.search("favorite color", use_embeddings=False, use_rerank=False)
    assert found["count"] == 1
    assert "blue" in found["hits"][0]["content"]


def test_retrieval_returns_ranked_explained_hits(api):
    api.remember("my favorite color is blue")
    api.remember("my favorite food is pizza")
    result = api.search("What is my favorite color?", use_embeddings=False,
                        use_rerank=False)
    assert result["count"] >= 1
    top = result["hits"][0]
    assert "blue" in top["content"]
    assert top["explain"]["source"] == MemorySource.EXPLICIT_USER
    assert top["explain"]["confidence"] == Confidence.HIGH
    assert top["explain"]["memory_type"] == MemoryType.USER


def test_retrieve_update_delete_round_trip(api):
    saved = api.remember("my dog is Max")["memory"]
    mid = saved["id"]
    assert api.retrieve(mid)["status"] == "success"
    updated = api.update(mid, {"importance": 0.95})
    assert updated["status"] == "success"
    assert updated["memory"]["importance"] == 0.95
    assert api.delete(mid)["status"] == "success"
    assert api.retrieve(mid)["status"] == "error"
    assert api.delete(mid)["status"] == "error"


def test_forget_removes_fully(api):
    mid = api.remember("temporary nickname Bobby")["memory"]["id"]
    result = api.forget(mid)
    assert result["status"] == "success"
    assert api.store.get(mid) is None  # nothing retained in active store
    assert api.search("Bobby", use_embeddings=False,
                      use_rerank=False)["count"] == 0


def test_forget_by_description(api):
    api.remember("my favorite color is blue")
    result = api.forget("favorite color")
    assert result["status"] == "success"
    assert api.search("favorite color", use_embeddings=False,
                      use_rerank=False)["count"] == 0


# -- explicit controls ----------------------------------------------------------
def test_explicit_remember_command(api):
    cmd = api.handle_explicit_command("Remember my favorite food is sushi")
    assert cmd["action"] == "remember" and cmd["status"] == "success"
    assert "sushi" in cmd["speak"]
    assert api.search("favorite food", use_embeddings=False,
                      use_rerank=False)["count"] == 1


def test_explicit_forget_command(api):
    api.remember("my favorite food is sushi")
    cmd = api.handle_explicit_command("Forget that my favorite food is sushi")
    assert cmd["status"] == "success"
    assert api.search("favorite food", use_embeddings=False,
                      use_rerank=False)["count"] == 0


def test_explicit_dont_remember_removes_match(api):
    api.remember("my guilty pleasure is reality TV")
    cmd = api.handle_explicit_command("Don't remember my guilty pleasure is reality TV")
    assert cmd["action"] == "ignore"
    assert api.search("reality TV", use_embeddings=False,
                      use_rerank=False)["count"] == 0


def test_explicit_what_remember_scopes_user(api):
    api.remember("my favorite color is blue")
    from backend.agent import project_memory
    project_memory.seed_project_memory(api)
    cmd = api.handle_explicit_command("What do you remember about me?")
    assert cmd["action"] == "show"
    assert all(m["memory_type"] == MemoryType.USER for m in cmd["memories"])
    proj = api.handle_explicit_command("What do you remember about this project?")
    assert all(m["memory_type"] == MemoryType.PROJECT for m in proj["memories"])


def test_explicit_correct_memory(api):
    api.remember("my favorite color is blue")
    cmd = api.handle_explicit_command("Correct that memory: my favorite color is red")
    assert cmd["status"] == "success"
    assert "red" in cmd["speak"]
    found = api.search("favorite color", use_embeddings=False, use_rerank=False)
    assert found["count"] == 1 and "red" in found["hits"][0]["content"]


def test_explicit_show_relevant(api):
    api.remember("my dog is Max")
    cmd = api.handle_explicit_command("Show me relevant memories about dog")
    assert cmd["action"] == "show" and cmd["count"] >= 1


def test_non_command_returns_none(api):
    assert api.handle_explicit_command("Calculate 48 times 25") is None


# -- confidence / provenance ------------------------------------------------------
def test_confidence_defaults_by_source(api):
    explicit = api.add("explicit fact", source=MemorySource.EXPLICIT_USER)
    assert explicit["memory"]["confidence"] == Confidence.HIGH
    verified = api.add("verified outcome", source=MemorySource.VERIFIED_TASK_RESULT)
    assert verified["memory"]["confidence"] == Confidence.HIGH
    observed = api.add("casual observation", source=MemorySource.SYSTEM_OBSERVATION)
    assert observed["memory"]["confidence"] == Confidence.MEDIUM


def test_provenance_is_preserved(api):
    result = api.add("deployed build 42", memory_type=MemoryType.EPISODIC,
                     source=MemorySource.VERIFIED_TASK_RESULT,
                     source_reference="agent run #42")
    mem = result["memory"]
    assert mem["source"] == MemorySource.VERIFIED_TASK_RESULT
    assert mem["source_reference"] == "agent run #42"
    assert mem["memory_type"] == MemoryType.EPISODIC


# -- dedup / conflicts --------------------------------------------------------------
def test_deduplication_consolidates(api):
    first = api.remember("User prefers concise answers")
    second = api.remember("user prefers concise answers")
    assert second.get("deduped") is True
    assert first["memory"]["id"] == second["memory"]["id"]
    assert api.list()["count"] == 1


def test_conflict_supersedes_with_history(api):
    api.remember("my favorite color is blue")
    result = api.remember("my favorite color is red")
    assert result.get("conflict") == "superseded"
    assert api.list()["count"] == 1  # one active record
    history = api.store.list(status="")["records"]
    assert len(history) == 2  # old value preserved as superseded
    assert {r.status for r in history} == {MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED}


def test_low_confidence_cannot_overwrite_high(api):
    api.remember("my favorite color is blue")  # HIGH explicit
    refused = api.add("favorite color: green", source=MemorySource.CONVERSATION,
                      confidence=Confidence.LOW)
    assert refused["status"] == "refused"
    found = api.search("favorite color", use_embeddings=False, use_rerank=False)
    assert "blue" in found["hits"][0]["content"]


# -- expiration -----------------------------------------------------------------------
def test_expiration_and_purge(api):
    saved = api.remember("temporary plan for today", expires_in_s=0.05)["memory"]
    time.sleep(0.1)
    assert api.retrieve(saved["id"])["status"] == "error"  # expired
    assert api.search("temporary plan", use_embeddings=False,
                      use_rerank=False)["count"] == 0
    stable = api.remember("my favorite color is blue")["memory"]
    assert stable["expiration"] is None  # stable memories never auto-expire
    assert api.retrieve(stable["id"])["status"] == "success"


# -- project memory ---------------------------------------------------------------------
def test_project_memory_seed_and_scope(api):
    from backend.agent import project_memory
    first = project_memory.seed_project_memory(api)
    assert first["added"] == first["total_facts"] and first["added"] > 0
    second = project_memory.seed_project_memory(api)
    assert second["added"] == 0 and second["deduped"] == first["total_facts"]
    overview = project_memory.get_project_overview(api)
    assert overview["count"] == first["total_facts"]
    assert all(m["memory_type"] == MemoryType.PROJECT for m in overview["memories"])
    # project facts do not leak into user-scoped "about me"
    cmd = api.handle_explicit_command("What do you remember about me?")
    assert cmd["count"] == 0


# -- embeddings (validated-only, offline) -------------------------------------------------
def test_only_validated_embed_model_is_used():
    assert memory_embeddings.VALIDATED_EMBED_MODEL == "nvidia/llama-nemotron-embed-vl-1b-v2"
    assert memory_embeddings.VALIDATED_EMBED_MODEL not in memory_embeddings.FORBIDDEN_EMBED_MODELS
    resolved = memory_embeddings.validated_embed_model_id()
    assert resolved in (None, memory_embeddings.VALIDATED_EMBED_MODEL)
    if resolved is not None:
        assert resolved not in memory_embeddings.FORBIDDEN_EMBED_MODELS


def test_embedding_search_path_with_fake_vectors(api, monkeypatch):
    api.remember("my favorite color is blue")
    api.remember("my favorite food is pizza")

    def fake_embed(texts, input_type="passage", timeout_s=60):
        vectors = []
        for text in texts:
            lowered = text.casefold()
            vectors.append([1.0, 0.0] if "color" in lowered or "blue" in lowered else [0.0, 1.0])
        return {"used": True, "model": "fake-test", "vectors": vectors, "dim": 2}

    monkeypatch.setattr(memory_embeddings, "embed_texts", fake_embed)
    # store one vector manually to exercise the cosine branch
    record = api.search("color", use_embeddings=False, use_rerank=False)["hits"][0]
    api.store.add(__import__("backend.agent.memory_schema", fromlist=["MemoryRecord"])
                  .MemoryRecord.from_dict({**api.retrieve(record["id"])["memory"]}),
                  embedding={"vector": [1.0, 0.0], "model": "fake-test", "dim": 2})
    result = api.search("What is my favorite color?", use_embeddings=True, use_rerank=False)
    assert result["embed_used"] is True
    assert "blue" in result["hits"][0]["content"]
    assert result["hits"][0]["explain"]["relevance_parts"]["semantic_kind"] == "cosine"


def test_embedding_failure_falls_back_to_lexical(api, monkeypatch):
    api.remember("my favorite color is blue")
    monkeypatch.setattr(memory_embeddings, "embed_texts",
                        lambda texts, input_type="passage", timeout_s=60: {"used": False,
                                                                          "reason": "offline"})
    result = api.search("favorite color", use_embeddings=True, use_rerank=False)
    assert result["embed_used"] is False
    assert result["count"] == 1


# -- reranking (unavailable → graceful off) -------------------------------------------------
def test_reranker_unavailable_and_graceful():
    assert memory_rerank.validated_rerank_model_id() is None
    assert memory_rerank.is_available() is False
    result = memory_rerank.rerank("query", ["b", "a"])
    assert result["used"] is False and result["order"] == [0, 1]


def test_search_works_without_reranker(api):
    api.remember("my favorite color is blue")
    result = api.search("favorite color", use_embeddings=False, use_rerank=True)
    assert result["rerank_used"] is False
    assert result["count"] == 1


# -- ranking ----------------------------------------------------------------------------------
def test_semantic_relevance_dominates_metadata(api):
    api.add("my favorite color is blue", source=MemorySource.EXPLICIT_USER,
            importance=0.1)  # low importance but exact match
    api.add("unrelated quarterly report summary", source=MemorySource.EXPLICIT_USER,
            importance=1.0)  # max importance, no overlap
    result = api.search("favorite color", use_embeddings=False, use_rerank=False)
    assert "blue" in result["hits"][0]["content"]


def test_ranking_explain_has_metadata_without_cot(api):
    api.remember("my favorite color is blue")
    hit = api.search("favorite color", use_embeddings=False, use_rerank=False)["hits"][0]
    explain = hit["explain"]
    for key in ("why_retrieved", "source", "confidence", "memory_type",
                "relevance", "relevance_parts", "created_at", "updated_at"):
        assert key in explain, key
    assert "chain_of_thought" not in explain and "reasoning" not in explain


def test_context_limits_are_respected(api):
    for i in range(6):
        api.remember(f"fact number {i} about Trains and color blue")
    result = api.search("Trains blue", limit=8, max_chars=120,
                        use_embeddings=False, use_rerank=False)
    assert result["used_chars"] <= 120 or len(result["hits"]) <= 1
    assert result["dropped"] >= 1
    ctx = api.memory_context("Trains blue", limit=8, max_chars=120)
    assert len(ctx) <= 400


# -- corrupted / invalid records ------------------------------------------------------------------
def test_invalid_records_are_rejected():
    with pytest.raises(ValueError):
        MemoryRecord(memory_type="nonsense", content="x")
    with pytest.raises(ValueError):
        MemoryRecord(content="   ")
    with pytest.raises(ValueError):
        MemoryRecord.from_dict({"content": "x", "confidence": "SORTA"})
    with pytest.raises(ValueError):
        MemoryRecord.from_dict("not-a-dict")


def test_corrupted_rows_are_skipped(api):
    api.remember("my favorite color is blue")
    conn = sqlite3.connect(api.store._db_path)
    try:
        conn.execute(
            "INSERT INTO memories (id, memory_type, content, summary, importance,"
            " confidence, created_at, updated_at, last_accessed, access_count,"
            " source, source_reference, project_id, tags_json, embedding_id,"
            " embedding_json, embedding_model, embedding_dim, status,"
            " sensitivity, expiration) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("corrupt-1", "user", "corrupted entry blue", "corrupted", "not-a-number",
             "MEDIUM", 1.0, 1.0, 1.0, 0, "conversation", "", "jarvis", "[]",
             "x", "[]", "", 0, "active", "internal", None))
        conn.commit()
    finally:
        conn.close()
    listed = api.list()
    assert listed["count"] == 1  # only the good record
    assert listed.get("corrupted_skipped", 0) >= 1
    searched = api.search("blue", use_embeddings=False, use_rerank=False)
    assert searched.get("corrupted_skipped", 0) >= 1


def test_legacy_json_migration(tmp_path):
    import json
    legacy = [{"id": "old-1", "text": "favorite color: blue", "category": "general",
               "source_text": "Remember my favorite color is blue",
               "created_at": 100.0, "updated_at": 200.0}]
    legacy_path = tmp_path / "persistent_memory.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    api = JarvisMemory(store=MemoryStore(str(tmp_path / "mig.db")))
    report = api.store.migrate_legacy_json(str(legacy_path))
    assert report["migrated"] == 1
    found = api.search("favorite color", use_embeddings=False, use_rerank=False)
    assert found["count"] == 1
    mem = found["hits"][0]
    assert mem["id"] == "old-1"  # id + provenance preserved
    assert mem["explain"]["source"] == MemorySource.EXPLICIT_USER


# -- privacy -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("secret", [
    "my password: hunter2",
    "api_key: nvapi-abc123XYZ",
    "Bearer sk-abcdefgh12345678 token here",
    "-----BEGIN RSA PRIVATE KEY-----\nabc",
    "cookie: session=abc123",
    "access_token: xyz",
])
def test_secrets_are_never_stored(api, secret):
    result = api.remember(secret)
    assert result["status"] == "refused"
    assert api.list()["count"] == 0


def test_pii_is_flagged_sensitive(api):
    result = api.remember("my email is user@example.com")
    assert result["status"] == "success"
    assert result["memory"]["sensitivity"] == "sensitive"


# -- agent integration --------------------------------------------------------------------------------------
def test_agent_retrieval_step_writes_state_context(api):
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    api.remember("my favorite color is blue")
    core = AgentCore()
    core._jarvis_memory = api
    ctx = core.memory_context_for("What is my favorite color?")
    assert "blue" in ctx
    state = TaskState()
    state.update_context("phase2_memory_context", ctx)
    assert "blue" in state.get_context("phase2_memory_context")


def test_agent_intercepts_memory_commands(api):
    import asyncio
    from backend.agent.core import AgentCore
    from backend.agent.state import TaskState
    core = AgentCore()
    core._jarvis_memory = api
    out = asyncio.run(core.process("Remember my favorite color is teal", TaskState()))
    assert out["status"] == "completed"
    assert out["memory_action"]["action"] == "remember"
    assert api.search("teal", use_embeddings=False, use_rerank=False)["count"] == 1


def test_agent_stores_verified_episodic_outcome(api, monkeypatch):
    from backend.agent.core import AgentCore
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # allow episodic write
    core = AgentCore()
    core._jarvis_memory = api
    core._memory_store_outcome("do a thing", "completed", "All done.")
    episodic = api.list(memory_type=MemoryType.EPISODIC)["memories"]
    assert len(episodic) == 1
    assert episodic[0]["source"] == MemorySource.VERIFIED_TASK_RESULT
    assert episodic[0]["confidence"] == Confidence.HIGH


def test_memory_failures_never_break_tasks(api, monkeypatch):
    from backend.agent.core import AgentCore
    core = AgentCore()
    core._jarvis_memory = api
    monkeypatch.setattr(api, "memory_context", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert core.memory_context_for("anything") == ""  # degraded, not raised


# -- learning from chats (gets better with use) -----------------------------------------
def test_learn_from_chat_preferences(api):
    result = api.learn_from_exchange("I really like concise answers with bullet points")
    assert result["status"] == "success" and len(result["learned"]) >= 1
    mem = api.search("concise answers", use_embeddings=False,
                     use_rerank=False)["hits"][0]
    assert mem["explain"]["source"] == MemorySource.CONVERSATION
    assert mem["explain"]["confidence"] == Confidence.MEDIUM
    assert mem["memory_type"] == MemoryType.USER


def test_learn_skips_memory_commands_and_failures(api):
    assert api.learn_from_exchange("Remember my color is blue")["status"] == "skipped"
    assert api.learn_from_exchange("I love tea", status="failed")["status"] == "skipped"
    assert api.learn_from_exchange("")["learned"] == []
    assert api.list()["count"] == 0


def test_learned_choice_never_overwrites_explicit(api):
    api.remember("my favorite color is blue")  # HIGH explicit
    result = api.learn_from_exchange("I think my favorite color is green")
    assert result["learned"] == []  # refused by authority rules
    found = api.search("favorite color", use_embeddings=False, use_rerank=False)
    assert "blue" in found["hits"][0]["content"]


def test_learn_refuses_secrets(api):
    result = api.learn_from_exchange("I always use hunter2 as my password: hunter2")
    assert result["learned"] == []
    assert api.list()["count"] == 0


def test_agent_outcome_learns_user_choice(api, monkeypatch):
    from backend.agent.core import AgentCore
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # allow memory writes
    core = AgentCore()
    core._jarvis_memory = api
    core._memory_store_outcome("I prefer concise answers, please summarize",
                               "completed", "Done, sir.")
    learned = [m for m in api.list()["memories"]
               if "concise" in m["content"] and m["source"] == MemorySource.CONVERSATION]
    assert len(learned) == 1
    episodic = api.list(memory_type=MemoryType.EPISODIC)["memories"]
    assert len(episodic) == 1  # verified outcome banked alongside


def test_planner_llm_prompt_carries_memory(monkeypatch):
    from backend.agent import planner as planner_module
    from backend.agent.state import TaskState
    captured = {}

    def fake_router(task, system_prompt, timeout_s=0):
        captured["task"] = task
        return None

    monkeypatch.setattr(planner_module, "_call_router_for_plan", fake_router)
    monkeypatch.setattr(planner_module, "_call_gemini_for_plan",
                        lambda task, key, prompt: None)
    state = TaskState()
    state.update_context("phase2_memory_context",
                         "- [user/explicit_user] I prefer concise answers")
    plan = planner_module.Planner().plan_task(
        "Design a comprehensive weekly meal planning system with nutritional balance",
        state)
    assert plan  # falls back to rules, but the LLM prompt was enriched first
    assert "USER PREFERENCES FROM MEMORY" in captured["task"]
    assert "concise answers" in captured["task"]


def test_planner_rule_path_ignores_memory(monkeypatch):
    from backend.agent import planner as planner_module
    from backend.agent.state import TaskState

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM path must not run for simple tasks")

    monkeypatch.setattr(planner_module, "_call_router_for_plan", fail_if_called)
    monkeypatch.setattr(planner_module, "_call_gemini_for_plan", fail_if_called)
    state = TaskState()
    state.update_context("phase2_memory_context", "- [user/explicit_user] X")
    plan = planner_module.Planner().plan_task("calculate 12 * 7", state)
    assert len(plan) > 0  # pure rule path, memory never parsed as task text
