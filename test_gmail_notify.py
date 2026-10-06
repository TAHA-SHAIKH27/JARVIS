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


def test_regular_mail_gets_quiet_toast_not_voice(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    watch = mod.load_watch()
    watch["vip_senders"] = ["boss@company.com"]
    with open(mod.WATCH_PATH, "w", encoding="utf-8") as handle:
        json.dump(watch, handle)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "fetch_unread", lambda limit=20: _fake_messages())
    result = mod.check_for_important()
    assert [m["id"] for m in result["announced"]] == ["m1"]
    assert [m["id"] for m in result["notified"]] == ["m2"]
    assert result["notified"][0].get("speak", "") == ""
    assert "toast" in result["notified"][0]


def test_vip_add_remove_roundtrip(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    assert mod.add_vip("boss@company.com")["status"] == "success"
    assert mod.add_vip("boss@company.com")["message"].startswith("boss@company.com is already")
    assert mod.load_watch()["vip_senders"] == ["boss@company.com"]
    assert mod.remove_vip("stranger@x.com")["status"] == "error"
    assert mod.remove_vip("boss@company.com")["status"] == "success"
    assert mod.load_watch()["vip_senders"] == []


def test_body_prefers_plain_text_and_strips_html(monkeypatch):
    import base64

    def b64(text):
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    plain = {"mimeType": "text/plain",
             "body": {"data": b64("Hello sir")}}
    assert gmail._pick_text_part(plain) == "Hello sir"
    html = {"mimeType": "text/html",
            "body": {"data": b64("<b>Hello</b><script>evil()</script>")}}
    picked = gmail._pick_text_part(html)
    assert picked == "Hello" and "evil" not in picked
    multi = {"mimeType": "multipart/alternative", "parts": [html, plain]}
    assert gmail._pick_text_part(multi) == "Hello sir"


def test_read_latest_single_attaches_body(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "fetch_latest",
                        lambda limit=5: [{"id": "m9", "from_name": "Boss",
                                          "from_email": "b@c.com",
                                          "subject": "Hi", "date": "",
                                          "snippet": "snip"}])
    monkeypatch.setattr(mod, "fetch_message_body", lambda mid, max_chars=2000: "body text here")
    result = mod.read_latest_mail(count=1)
    assert result["status"] == "ok"
    assert result["messages"][0]["body"] == "body text here"
    assert "body text here" in result["message"]


def test_inbox_query_windows():
    assert gmail._inbox_query() == "in:inbox"
    assert gmail._inbox_query(unread=True) == "in:inbox is:unread"
    assert gmail._inbox_query(days=5) == "in:inbox newer_than:5d"
    assert gmail._inbox_query(days=2, older_than_days=1) == \
        "in:inbox newer_than:2d older_than:1d"


def test_api_failure_is_not_empty_inbox(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)

    def fake_get(path, params=None, timeout=20):
        mod._LAST_API_ERROR = "http_401"
        return None

    monkeypatch.setattr(mod, "_api_get", fake_get)
    result = mod.read_latest_mail(count=1)
    assert result["status"] == "error"
    assert "re-link" in result["message"]
    assert "Inbox is clear" not in result["message"]


def test_ranged_count_answer(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "_fetch_messages",
                        lambda query, limit=50: _fake_messages() * 3)
    monkeypatch.setattr(mod, "count_messages", lambda query: 6)
    result = mod.read_latest_mail(count=10, days=5)
    assert result["status"] == "ok" and result["total"] == 6
    assert "6 mails" in result["message"] and "last 5 days" in result["message"]


def test_send_validation_and_relink(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    assert mod.send_email("not-an-address", "", "hi")["status"] == "error"
    assert mod.send_email("a@b.com", "", "")["status"] == "error"
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: False)
    assert mod.send_email("a@b.com", "", "hi")["status"] == "not_linked"
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "_api_post", lambda path, payload: None)
    monkeypatch.setattr(mod, "_LAST_API_ERROR", "http_403", raising=False)
    result = mod.send_email("a@b.com", "sub", "hi")
    assert result["status"] == "needs_relink" and "re-link" in result["message"]


def test_api_failure_is_not_reported_as_empty_inbox(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "_fetch_messages", lambda q, n: [])
    monkeypatch.setattr(mod, "_LAST_API_ERROR", "http_403")
    result = mod.read_latest_mail(count=1)
    assert result["status"] == "error"
    assert "Inbox is clear" not in result["message"]
    assert "re-link" in result["message"]


def test_date_window_query_and_count(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    assert mod._inbox_query(unread=True, days=5) == "in:inbox is:unread newer_than:5d"
    assert mod._inbox_query(days=2, older_than_days=1) == "in:inbox newer_than:2d older_than:1d"
    seen_queries = []
    msgs = [{"id": "m1", "from_name": "A", "from_email": "a@x.com",
             "subject": "One", "date": "", "snippet": ""},
            {"id": "m2", "from_name": "B", "from_email": "b@x.com",
             "subject": "Two", "date": "", "snippet": ""}]

    def fake_fetch(query, limit=20):
        seen_queries.append(query)
        return list(msgs)

    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "_fetch_messages", fake_fetch)
    monkeypatch.setattr(mod, "count_messages", lambda q: 7)
    result = mod.read_latest_mail(count=10, days=5)
    assert result["status"] == "ok" and result["total"] == 7
    assert "7 mails in the last 5 days" in result["message"]
    assert seen_queries and "newer_than:5d" in seen_queries[0]


def test_send_email_validation_and_403_relink(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    bad = mod.send_email("not-an-address", "Hi", "hello")
    assert bad["status"] == "error" and "valid email address" in bad["message"]
    empty = mod.send_email("a@b.com", "Hi", "   ")
    assert empty["status"] == "error" and "nothing to send" in empty["message"]
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: False)
    assert mod.send_email("a@b.com", "Hi", "yo")["status"] == "not_linked"
    monkeypatch.setattr(mod, "is_gmail_linked", lambda: True)
    monkeypatch.setattr(mod, "_api_post", lambda path, payload, timeout=20: None)
    monkeypatch.setattr(mod, "_LAST_API_ERROR", "http_403")
    denied = mod.send_email("a@b.com", "Hi", "yo")
    assert denied["status"] == "needs_relink" and "re-link" in denied["message"]
    monkeypatch.setattr(mod, "_api_post",
                        lambda path, payload, timeout=20: {"id": "sent123"})
    ok = mod.send_email("a@b.com", "Hi", "yo")
    assert ok["status"] == "success" and "sent to a@b.com" in ok["message"]


def test_count_messages_shapes(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_api_get", lambda path, params=None, timeout=20:
                        {"resultSizeEstimate": 7})
    assert mod.count_messages("in:inbox") == 7
    monkeypatch.setattr(mod, "_api_get", lambda path, params=None, timeout=20: None)
    assert mod.count_messages("in:inbox") == -1
