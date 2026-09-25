"""Tests for normal-mode reminders + scheduled WhatsApp (offline)."""
from datetime import datetime, timedelta

import backend.tools.scheduler as sched
from backend.agent import phase1_runtime


def _fixed_now():
    return datetime(2026, 9, 25, 10, 0, 0).astimezone()


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "WHATSAPP_JOBS_PATH", str(tmp_path / "scheduled_wa.json"))
    monkeypatch.setattr(phase1_runtime, "_reminder_path",
                        lambda: str(tmp_path / "reminders.json"))
    return sched


# ── time parsing ──────────────────────────────────────────────────────────────
def test_parse_relative_times():
    now = _fixed_now()
    assert sched.parse_when("remind me in 10 minutes", now)["when"] - now == timedelta(minutes=10)
    assert sched.parse_when("in 2 hours", now)["when"] - now == timedelta(hours=2)
    assert sched.parse_when("in an hour", now)["when"] - now == timedelta(hours=1)
    assert sched.parse_when("in half an hour", now)["when"] - now == timedelta(minutes=30)
    assert sched.parse_when("in 3 days", now)["when"] - now == timedelta(days=3)


def test_parse_at_time_rollover():
    now = _fixed_now()  # 10:00 AM
    morning = sched.parse_when("at 6pm", now)
    assert morning["ok"] and morning["when"].hour == 18 and morning["when"].day == 25
    passed = sched.parse_when("at 9am", now)  # 9am passed → tomorrow
    assert passed["ok"] and passed["when"].day == 26 and passed["when"].hour == 9
    explicit = sched.parse_when("tomorrow at 9am", now)
    assert explicit["ok"] and explicit["when"].day == 26
    late = sched.parse_when("at 18:30", now)
    assert late["ok"] and late["when"].hour == 18 and late["when"].minute == 30


def test_parse_weekday():
    now = _fixed_now()  # a Friday
    assert now.weekday() == 4
    result = sched.parse_when("on monday at 5pm", now)
    assert result["ok"] and result["when"].weekday() == 0 and result["when"].hour == 17


def test_parse_invalid():
    assert sched.parse_when("hello world", _fixed_now())["ok"] is False
    assert sched.parse_when("", _fixed_now())["ok"] is False
    # "call mom at work" — bare word after at is not a time
    assert sched.parse_when("call mom at work", _fixed_now())["ok"] is False


# ── reminder parsing ──────────────────────────────────────────────────────────
def test_parse_reminder_variants():
    now = _fixed_now()
    r1 = sched.parse_reminder("remind me in 10 minutes to call mom")
    assert r1["text"] == "call mom" and (r1["when"] - now).total_seconds() > 0
    r2 = sched.parse_reminder("remind me at 6pm to take a break")
    assert r2["text"] == "take a break" and r2["when"].hour == 18
    r3 = sched.parse_reminder("remind me to stretch in 5 minutes")
    assert r3["text"] == "stretch"
    assert sched.parse_reminder("calculate 2+2") is None
    assert "error" in sched.parse_reminder("remind me to call mom")  # no time
    assert "error" in sched.parse_reminder("remind me in 10 minutes")  # no text


# ── whatsapp schedule parsing ─────────────────────────────────────────────────
def test_parse_scheduled_whatsapp():
    r = sched.parse_scheduled_whatsapp("send whatsapp to Mom at 6pm saying happy birthday")
    assert r["contact"] == "Mom" and r["message"] == "happy birthday" and r["when"].hour == 18
    r2 = sched.parse_scheduled_whatsapp("schedule whatsapp to +919876543210 in 2 hours saying on my way")
    assert r2["contact"] == "+919876543210" and r2["message"] == "on my way"
    # immediate send (no time) → not scheduling business
    assert sched.parse_scheduled_whatsapp("send whatsapp to Mom saying hi") is None
    assert sched.parse_scheduled_whatsapp("calculate 2+2") is None
    assert "error" in sched.parse_scheduled_whatsapp("send whatsapp to Mom at 6pm")


# ── normal-mode commands ──────────────────────────────────────────────────────
def test_reminder_command_round_trip(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    created = mod.handle_schedule_command("remind me in 10 minutes to call mom")
    assert created and "Reminder set" in created["speak"]
    listed = mod.handle_schedule_command("list reminders")
    assert listed and "call mom" in listed["speak"]
    cancelled = mod.handle_schedule_command("cancel reminder call mom")
    assert cancelled and "Cancelled" in cancelled["speak"]
    empty = mod.handle_schedule_command("list reminders")
    assert "No active reminders" in empty["speak"]


def test_whatsapp_schedule_round_trip(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    created = mod.handle_schedule_command(
        "send whatsapp to Mom at 6pm saying happy birthday")
    assert created and "Scheduled" in created["speak"] and "Mom" in created["speak"]
    listed = mod.handle_schedule_command("list scheduled messages")
    assert listed and "Mom" in listed["speak"]
    cancelled = mod.handle_schedule_command("cancel scheduled whatsapp to mom")
    assert cancelled and "Cancelled" in cancelled["speak"]
    assert mod.handle_schedule_command("list scheduled messages")["speak"].startswith("No scheduled")


def test_non_schedule_returns_none(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    assert mod.handle_schedule_command("send whatsapp to Mom saying hi now") is None
    assert mod.handle_schedule_command("what is the weather") is None


# ── firing ────────────────────────────────────────────────────────────────────
def test_fire_due_reminders_once(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    phase1_runtime.runtime.reminders.add("take a break",
                                         due_at=(datetime.now().astimezone() - timedelta(minutes=1)).isoformat())
    fired = []
    assert mod.fire_due_reminders(fired.append) == 1
    assert fired[0]["text"] == "take a break"
    assert mod.fire_due_reminders(fired.append) == 0  # completed → never again
    assert len(fired) == 1


def test_fire_due_whatsapp_success_and_failure(tmp_path, monkeypatch):
    mod = _isolate(tmp_path, monkeypatch)
    past = datetime.now().astimezone() - timedelta(minutes=1)
    mod.schedule_whatsapp("Mom", "hi", past)
    mod.schedule_whatsapp("Dad", "hello", past)
    calls, results = [], []

    def fake_send(contact, message):
        calls.append((contact, message))
        if contact == "Dad":
            return {"status": "error", "message": "phone locked"}
        return {"status": "success", "message": "sent"}

    assert mod.fire_due_whatsapp(fake_send, lambda job, res: results.append((job, res))) == 2
    jobs = {j["contact"]: j for j in mod.list_scheduled(include_done=True)}
    assert jobs["Mom"]["status"] == "sent" and jobs["Dad"]["status"] == "failed"
    assert mod.list_scheduled() == []  # nothing pending anymore
    assert mod.fire_due_whatsapp(fake_send, lambda j, r: None) == 0


def test_describe_when():
    now = datetime.now().astimezone()
    assert sched.describe_when(now + timedelta(hours=1)).startswith("today at")
    assert sched.describe_when(now + timedelta(days=1)).startswith("tomorrow at")
