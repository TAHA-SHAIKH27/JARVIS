"""Basic regression tests for the Phase 1 persistent memory store."""
from backend.agent import phase1_memory as memory


def test_remember_recall_and_forget(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
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


def test_duplicate_memory_is_not_created(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    monkeypatch.setattr(memory, "_memory_path", lambda: str(path))

    first = memory.remember("Use British JARVIS persona")
    second = memory.remember("use british jarvis persona")
    assert first["memory"]["id"] == second["memory"]["id"]
    assert memory.recall()["count"] == 1
