"""Tests for the proactive Gmail watcher (offline — Gmail REST is mocked)."""
import json

import backend.tools.gmail_notify as gmail


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail, "WATCH_PATH", str(tmp_path / "gmail_watch.json"))
    monkeypatch.setattr(gmail, "SEEN_PATH", str(tmp_path / "gmail_seen.json"))
    return gmail


def test_watch_defaults_created(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    watch = mod.load_watch()
    assert watch["poll_minutes"] == 30
    assert "urgent" in watch["urgent_keywords"]
    assert watch["vip_senders"] == []
    assert (tmp_path / "gmail_watch.json").exists()


def test_important_vip_sender(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    watch = mod.load_watch()
    watch["vip_senders"] = ["boss@company.com"]
    msg = {"from_name": "The Boss", "from_email": "boss@company.com",
           "subject": "Hello", "snippet": "just saying hi"}
    verdict = mod.is_important(msg, watch)
    assert verdict["important"] is True and "VIP" in verdict["reason"]


def test_important_vip_name_match(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    watch = mod.load_watch()
    watch["vip_senders"] = ["professor sharma"]
    msg = {"from_name": "Professor Sharma", "from_email": "x@univ.edu",
           "subject": "Notes", "snippet": "see attached"}
    assert mod.is_important(msg, watch)["important"] is True


def test_important_urgent_keyword(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    msg = {"from_name": "Someone", "from_email": "s@mail.com",
           "subject": "URGENT: server down", "snippet": "please help"}
    verdict = mod.is_important(msg, mod.load_watch())
    assert verdict["important"] is True


def test_not_important_newsletter(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    msg = {"from_name": "Newsletter", "from_email": "news@mail.com",
           "subject": "Weekly deals", "snippet": "10% off everything"}
    assert mod.is_important(msg, mod.load_watch())["important"] is False


def test_parse_sender_variants():
    assert gmail.parse_sender("Jane Doe <jane@mail.com>") == {"name": "Jane Doe", "email": "jane@mail.com"}
    parsed = gmail.parse_sender("plain@mail.com")
    assert parsed["email"] == "plain@mail.com"
    assert gmail.parse_sender("")["name"] == "Unknown sender"


def test_announcement_text_shape_and_truncation():
    text = gmail.announcement_text({"from_name": "Boss", "subject": "Hi"})
    assert text.startswith("Sir, important mail from Boss:")
    long_text = gmail.announcement_text({"from_name": "B", "subject": "x" * 200})
    assert len(long_text) < 220 and long_text.endswith("….")


def _fake_messages():
    return [
        {"id": "m1", "from_name": "Boss", "from_email": "boss@company.com",
         "subject": "Hello", "date": "", "snippet": "hi"},
        {"id": "m2", "from_name": "Newsletter", "from_email": "news@mail.com",
         "subject": "Deals", "date": "", "snippet": "sale"},
    ]


def test_check_announces_only_unseen_important(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    watch = mod.load_watch()
    watch["vip_senders"] = ["boss@company.com"]
    with open(mod.WATCH_PATH, "w", encoding="utf-8") as handle:
        json.dump(watch, handle)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "fetch_unread", lambda limit=20: _fake_messages())

    first = mod.check_for_important()
    assert first["status"] == "ok" and first["checked"] == 2
    assert len(first["announced"]) == 1
    assert first["announced"][0]["id"] == "m1"
    assert first["announced"][0]["speak"].startswith("Sir, important mail from Boss:")

    second = mod.check_for_important()  # nothing new → silence
    assert second["announced"] == []

    third = mod.check_for_important()  # restart-proof: still silent
    assert third["announced"] == []


def test_check_not_linked(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: False)
    result = mod.check_for_important()
    assert result["status"] == "not_linked" and result["announced"] == []


def test_seen_state_survives_reload(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "fetch_unread", lambda limit=20: _fake_messages())
    mod.check_for_important()
    state = mod.load_seen()
    assert set(state["seen_ids"]) == {"m1", "m2"}
    assert state["last_check"] > 0
