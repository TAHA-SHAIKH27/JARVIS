"""Tests for the JARVIS mute control (frontend + backend voice).

Backend speech (reminders/announcements via SAPI) must stop when muted;
unmuting must not replay stale announcements. No SAPI needed: VoiceSystem
degrades gracefully without it.
"""
import pytest

from backend.agent import voice as voice_mod


@pytest.fixture()
def system():
    vs = voice_mod.VoiceSystem()
    yield vs
    vs.set_muted(False)
    vs.clear_queue()


@pytest.fixture()
def global_mute_restored():
    yield
    try:
        voice_mod.get_voice_system().set_muted(False)
    except Exception:
        pass


def test_mute_drops_new_speech(system):
    assert system.is_muted() is False
    assert system.speak("hello") is True
    assert system.set_muted(True) is True
    assert system.speak("hello") is False
    assert system._tts_queue.empty()
    assert system.set_muted(False) is False
    assert system.speak("hello again") is True


def test_mute_clears_pending_queue(system):
    system.speak("one")
    system.speak("two")
    assert not system._tts_queue.empty()
    system.set_muted(True)
    assert system._tts_queue.empty()


def test_module_helpers(system, monkeypatch, global_mute_restored):
    monkeypatch.setattr(voice_mod, "_voice_system", system)
    assert voice_mod.is_muted() is False
    assert voice_mod.set_muted(True) is True
    assert voice_mod.is_muted() is True
    assert voice_mod.speak("dropped") is False


def test_mute_endpoints(global_mute_restored):
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)

    assert client.get("/api/voice/mute").json() == {"status": "success", "muted": False}
    res = client.post("/api/voice/mute", json={"muted": True}).json()
    assert res == {"status": "success", "muted": True}
    assert voice_mod.get_voice_system().is_muted() is True
    state = client.get("/api/voice/tts/state").json()
    assert state["muted"] is True
    res = client.post("/api/voice/mute", json={"muted": False}).json()
    assert res == {"status": "success", "muted": False}


def test_muted_backend_skips_announcement_speech(tmp_path, monkeypatch,
                                                 global_mute_restored):
    """Reminder firing while muted still records state + toast, minus voice."""
    import backend.agent.phase1_runtime as rt
    import backend.tools.scheduler as sched
    monkeypatch.setattr(rt, "_reminder_path", lambda: str(tmp_path / "r.json"))
    voice_mod.get_voice_system().set_muted(True)
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    rid = rt.runtime.reminders.add("muted check", past)["reminder"]["id"]
    assert sched.fire_due_reminders(lambda p: None) == 1
    # State + lifecycle unaffected; only speech was dropped.
    assert rt.runtime.reminders.get(rid)["status"] == "triggered"
