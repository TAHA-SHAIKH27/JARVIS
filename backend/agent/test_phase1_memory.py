"""Regression tests for the Phase 1 persistent memory store."""
from backend.agent import phase1_memory as memory


def test_remember_recall_and_forget(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    saved = memory.remember("User prefers concise answers", category="preference")
    assert saved["status"] == "success"
    memory_id = saved["memory"]["id"]

    found = memory.recall("concise")
    assert found["count"] == 1
    assert found["memories"][0]["id"] == memory_id

    deleted = memory.forget(memory_id)
    assert deleted["status"] == "success"
    assert memory.recall("concise")["count"] == 0


def test_normalization_and_structured_fields(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    saved = memory.remember("Remember my favorite color is blue", category="general")
    assert saved["status"] == "success"
    mem = saved["memory"]
    assert mem["key"] == "favorite color"
    assert mem["value"] == "blue"
    assert mem["text"] == "favorite color: blue"
    assert mem["source_text"] == "Remember my favorite color is blue"


def test_natural_question_recall(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    memory.remember("Remember my favorite color is blue")
    memory.remember("Remember my favorite food is pizza")
    memory.remember("Remember my dog is Max")

    # Natural question matching
    recalled = memory.recall("What's my favorite color?")
    assert recalled["count"] >= 1
    assert recalled["memories"][0]["key"] == "favorite color"
    assert recalled["memories"][0]["value"] == "blue"

    # Context string injection formatting
    ctx = memory.memory_context("What's my favorite color?")
    assert "favorite color: blue" in ctx

    # Another question
    recalled_food = memory.recall("What is my favorite food?")
    assert recalled_food["count"] >= 1
    assert recalled_food["memories"][0]["value"] == "pizza"


def test_duplicate_memory_is_not_created(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    first = memory.remember("Use British JARVIS persona")
    second = memory.remember("use british jarvis persona")
    assert first["memory"]["id"] == second["memory"]["id"]
    assert memory.recall()["count"] == 1


def test_memory_update_for_same_key(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    first = memory.remember("Remember my favorite color is blue")
    second = memory.remember("Remember my favorite color is red")
    assert first["memory"]["id"] == second["memory"]["id"]
    assert second["memory"]["value"] == "red"
    assert second["memory"]["text"] == "favorite color: red"
    assert memory.recall()["count"] == 1
    assert memory.recall("color")["memories"][0]["value"] == "red"


def test_legacy_unkeyed_records_backward_compatibility(tmp_path, monkeypatch):
    import json
    path = tmp_path / "persistent_memory.json"
    legacy_data = [
        {"id": "old-1", "text": "my favorite color is blue", "category": "general", "created_at": 100, "updated_at": 100}
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    recalled = memory.recall("What is my favorite color?")
    assert recalled["count"] == 1
    assert recalled["memories"][0]["value"] == "blue"
    assert recalled["memories"][0]["key"] == "favorite color"


def test_clear_memory(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    memory.remember("Remember my favorite color is blue")
    assert memory.recall()["count"] == 1
    res = memory.clear()
    assert res["status"] == "success"
    assert memory.recall()["count"] == 0
