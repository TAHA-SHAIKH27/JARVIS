"""Regression tests for the Phase 1 runtime foundation."""
from backend.agent import phase1_memory
from backend.agent.phase1_runtime import ConversationContext, ReminderStore, normalize_intent


def test_intent_normalization():
    assert normalize_intent("remember that I prefer dark mode")["intent"] == "remember"
    assert normalize_intent("remind me tomorrow")["intent"] == "reminder"
    assert normalize_intent("research Python history")["intent"] == "research"
    assert normalize_intent("calculate 12 * 4")["intent"] == "calculation"


def test_conversation_context_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "conversation.json"
    import backend.agent.phase1_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "_conversation_path", lambda: str(path))
    context = ConversationContext(max_turns=3)
    for index in range(5):
        context.add("user", f"turn {index}")
    turns = context.list()
    assert len(turns) == 3
    assert turns[0]["content"] == "turn 2"
    assert turns[-1]["content"] == "turn 4"


def test_reminder_store_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "reminders.json"
    import backend.agent.phase1_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "_reminder_path", lambda: str(path))
    store = ReminderStore()
    created = store.add("Review JARVIS Phase 1", "2030-01-01T10:00:00+00:00")
    assert created["status"] == "success"
    reminder_id = created["reminder"]["id"]
    assert len(store.list()) == 1
    assert store.complete(reminder_id)["status"] == "success"
    assert store.list() == []
    assert len(store.list(include_completed=True)) == 1


def test_memory_store_remains_available(tmp_path, monkeypatch):
    path = tmp_path / "persistent_memory.json"
    monkeypatch.setattr(phase1_memory, "_memory_path", lambda: str(path))
    saved = phase1_memory.remember("JARVIS Phase 1 test memory", category="test")
    assert saved["status"] == "success"
    recalled = phase1_memory.recall("Phase 1 test")
    assert recalled["count"] == 1
    assert "JARVIS Phase 1 test memory" in phase1_memory.memory_context("Phase 1 test")
