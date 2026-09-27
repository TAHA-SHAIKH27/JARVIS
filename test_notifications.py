"""Tests for the persistent Notification Center + reminder lifecycle.

Covers: creation → scheduling → triggering → read/unread → dismiss →
snooze → delete, restart persistence, duplicate prevention, unread counts,
notification listing, scheduled messages, cleanup/history guards, API
failures, and the backend contract the frontend relies on.

All stores are isolated to tmp_path (production files untouched).
"""
from datetime import datetime, timedelta, timezone

import pytest

import backend.agent.notifications as notif_store
import backend.agent.phase1_runtime as runtime_module
import backend.tools.scheduler as sched


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module, "_reminder_path",
                        lambda: str(tmp_path / "reminders.json"))
    monkeypatch.setattr(notif_store, "_store_path",
                        lambda: str(tmp_path / "notifications.json"))
    monkeypatch.setattr(sched, "WHATSAPP_JOBS_PATH",
                        str(tmp_path / "scheduled_wa.json"))
    return runtime_module.ReminderStore()


def _past_iso(minutes=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _future_iso(minutes=60):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# ── reminder lifecycle ────────────────────────────────────────────────────
def test_reminder_full_lifecycle(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    created = store.add("Maths lecture", _past_iso(), priority="urgent")
    assert created["status"] == "success"
    rid = created["reminder"]["id"]

    # SCHEDULED → due
    assert any(r["id"] == rid for r in store.due())

    # → TRIGGERED / UNREAD (exactly once)
    fired = []
    assert sched.fire_due_reminders(fired.append) == 1
    live = store.get(rid)
    assert live["status"] == "triggered" and live["read"] is False
    assert store.due() == []  # never due again while triggered
    assert [r["id"] for r in store.active_for_bar()] == [rid]
    assert store.unread_count() == 1

    # second ticker pass: nothing refires, no second identity
    assert sched.fire_due_reminders(fired.append) == 0
    assert len(fired) == 1
    assert store.get(rid)["trigger_count"] == 1

    # READ removes it from the bar, record stays
    assert store.mark_read(rid)["status"] == "success"
    assert store.active_for_bar() == [] and store.unread_count() == 0
    assert store.get(rid) is not None

    # UNREAD re-opens it
    assert store.mark_unread(rid)["status"] == "success"
    assert store.unread_count() == 1

    # DISMISS removes from active presentation, keeps history
    assert store.dismiss(rid)["status"] == "success"
    assert store.active_for_bar() == []
    assert any(r["id"] == rid for r in store.history())

    # DELETE removes it permanently
    assert store.remove(rid)["status"] == "success"
    assert store.get(rid) is None
    assert all(r["id"] != rid for r in store.history())


def test_restart_persistence(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    trig = store.add("trigger me", _past_iso())["reminder"]["id"]
    sched.fire_due_reminders(lambda p: None)
    dismissed = store.add("dismissed one", _past_iso())["reminder"]["id"]
    sched.fire_due_reminders(lambda p: None)
    store.dismiss(dismissed)
    snoozed = store.add("snoozed one", _past_iso())["reminder"]["id"]
    sched.fire_due_reminders(lambda p: None)
    store.snooze(snoozed, minutes=45)

    # "Restart": brand-new store object over the same files.
    fresh = runtime_module.ReminderStore()
    assert fresh.get(trig)["status"] == "triggered"
    assert fresh.get(trig)["read"] is False  # still unread, same identity
    assert [r["id"] for r in fresh.active_for_bar()] == [trig]
    assert fresh.get(dismissed)["status"] == "dismissed"
    assert dismissed not in [r["id"] for r in fresh.active_for_bar()]
    snap = fresh.get(snoozed)
    assert snap["status"] == "snoozed" and snap["snoozed_until"]
    assert snoozed not in [r["id"] for r in fresh.active_for_bar()]

    # Dismissed reminder never returns as new after another restart.
    fresh2 = runtime_module.ReminderStore()
    assert dismissed not in [r["id"] for r in fresh2.active_for_bar()]
    assert fresh2.due() == [] or all(
        r["id"] not in (trig, dismissed) for r in fresh2.due())


def test_dismissed_survives_restart_as_history(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    rid = store.add("one-shot", _past_iso())["reminder"]["id"]
    sched.fire_due_reminders(lambda p: None)
    store.dismiss(rid)
    fresh = runtime_module.ReminderStore()
    assert fresh.active_for_bar() == []
    assert any(r["id"] == rid for r in fresh.history())
    # Deleting then restarting: completely gone.
    fresh.remove(rid)
    assert runtime_module.ReminderStore().get(rid) is None


def test_snooze_rearm_and_refire_same_id(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    rid = store.add("wake me", _past_iso())["reminder"]["id"]
    sched.fire_due_reminders(lambda p: None)

    # Snooze into the past (test-only): immediately due again, same id.
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    res = store.snooze(rid, when_iso=past)
    assert res["status"] == "success"
    assert store.get(rid)["status"] == "snoozed"
    assert any(r["id"] == rid for r in store.due())

    fired = []
    assert sched.fire_due_reminders(fired.append) == 1
    assert fired[0]["reminder"]["id"] == rid
    assert store.get(rid)["trigger_count"] == 2
    assert store.get(rid)["status"] == "triggered"


def test_snooze_validation(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    rid = store.add("x", _future_iso())["reminder"]["id"]
    assert store.snooze(rid, minutes=0)["status"] == "error"
    assert store.snooze(rid, minutes=-5)["status"] == "error"
    assert store.snooze(rid, when_iso="not-a-time")["status"] == "error"
    assert store.snooze("missing-id", minutes=10)["status"] == "error"
    assert store.get(rid)["status"] == "scheduled"  # unchanged


def test_legacy_completed_never_active(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    runtime_module._write_json(
        runtime_module._reminder_path(),
        [{"id": "legacy1", "text": "old maths lecture",
          "due_at": "2026-09-26T10:00:00+00:00", "completed": True,
          "created_at": "2026-09-26T06:00:00+00:00",
          "updated_at": "2026-09-27T05:00:00+00:00"}])
    rec = store.get("legacy1")
    assert rec["status"] == "triggered" and rec["read"] is True
    assert store.active_for_bar() == []
    assert any(r["id"] == "legacy1" for r in store.history())


def test_priority_validation_and_persistence(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    rid = store.add("p", _future_iso(), priority="bogus")["reminder"]["id"]
    assert store.get(rid)["priority"] == "normal"
    assert store.set_priority(rid, "urgent")["status"] == "success"
    assert store.set_priority(rid, "nope")["status"] == "error"
    assert runtime_module.ReminderStore().get(rid)["priority"] == "urgent"


# ── notification store ────────────────────────────────────────────────────
def test_notification_upsert_dedupes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert notif_store.upsert_notification("gmail:1", "gmail", "t", "b")["created"] is True
    assert notif_store.upsert_notification("gmail:1", "gmail", "t", "b2")["created"] is False
    assert len(notif_store.list_notifications(include_dismissed=True)) == 1
    assert notif_store.unread_count() == 1


def test_notification_read_unread_dismiss_delete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    notif_store.upsert_notification("wa:1", "whatsapp", "sent", "to Mom")
    assert notif_store.mark_read("wa:1")["status"] == "success"
    assert notif_store.unread_count() == 0
    assert notif_store.mark_unread("wa:1")["status"] == "success"
    assert notif_store.unread_count() == 1
    assert notif_store.dismiss("wa:1")["status"] == "success"
    assert notif_store.list_notifications() == []
    assert len(notif_store.list_notifications(include_dismissed=True)) == 1
    assert notif_store.delete("wa:1")["status"] == "success"
    assert notif_store.list_notifications(include_dismissed=True) == []
    assert notif_store.mark_read("missing")["status"] == "error"


def test_clear_history_keeps_unread_and_other_stores(tmp_path, monkeypatch):
    store = _isolate(tmp_path, monkeypatch)
    notif_store.upsert_notification("gmail:read", "gmail", "r", "b")
    notif_store.upsert_notification("gmail:unread", "gmail", "u", "b")
    notif_store.mark_read("gmail:read")
    rid = store.add("keep me", _future_iso())["reminder"]["id"]
    sched.schedule_whatsapp("Mom", "hi",
                            datetime.now(timezone.utc) + timedelta(hours=2))

    cleared = notif_store.clear_read_history()
    assert cleared["cleared"] == 1
    remaining = [n["id"] for n in notif_store.list_notifications(include_dismissed=True)]
    assert remaining == ["gmail:unread"]
    # Reminder + scheduled stores untouched by construction.
    assert store.get(rid) is not None
    assert len(sched.list_scheduled()) == 1


def test_purge_expired_only_old_read(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    notif_store.upsert_notification("old-read", "system", "o", "b")
    notif_store.mark_read("old-read")
    # Backdate beyond retention.
    items = notif_store._load()
    for item in items:
        if item["id"] == "old-read":
            item["updated_at"] = old
    notif_store._save(items)
    notif_store.upsert_notification("old-unread", "system", "u", "b")
    items = notif_store._load()
    for item in items:
        if item["id"] == "old-unread":
            item["created_at"] = item["updated_at"] = old
    notif_store._save(items)
    notif_store.upsert_notification("new-read", "system", "n", "b")
    notif_store.mark_read("new-read")

    purged = notif_store.purge_expired()
    assert purged["purged"] == 1
    ids = {n["id"] for n in notif_store.list_notifications(include_dismissed=True)}
    assert ids == {"old-unread", "new-read"}  # unread + recent read survive


# ── scheduled messages ────────────────────────────────────────────────────
def test_scheduled_job_cancel_reschedule_delete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    job = sched.schedule_whatsapp("Mom", "happy birthday", when)["job"]
    jid = job["id"]
    assert len(sched.list_scheduled()) == 1

    later = datetime.now(timezone.utc) + timedelta(hours=3)
    assert sched.reschedule_job_by_id(jid, later)["status"] == "success"
    assert sched.get_job(jid)["send_at"] == later.isoformat()
    assert sched.reschedule_job_by_id(jid, datetime.now(timezone.utc))["status"] == "error"

    assert sched.cancel_job_by_id(jid)["status"] == "success"
    assert sched.list_scheduled() == []  # never refires
    assert sched.get_job(jid)["status"] == "cancelled"
    assert sched.cancel_job_by_id(jid)["status"] == "error"  # already cancelled
    assert sched.delete_job_by_id(jid)["status"] == "success"
    assert sched.get_job(jid) is None


def test_pending_job_cannot_be_hard_deleted(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job = sched.schedule_whatsapp("Dad", "hi",
                                  datetime.now(timezone.utc) + timedelta(hours=1))["job"]
    assert sched.delete_job_by_id(job["id"])["status"] == "error"
    assert sched.get_job(job["id"])["status"] == "pending"


# ── API contract (what the frontend relies on) ────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_api_center_snapshot_shape(client):
    res = client.get("/api/notifications/center")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"notifications", "reminders", "scheduled", "unread_count"}
    assert set(body["reminders"]) >= {"active", "upcoming", "history"}
    assert body["unread_count"] == 0


def test_api_reminder_lifecycle_no_duplicates(client):
    # Create via the real /api/command path, fire, restart-view, dismiss.
    created = client.post("/api/command",
                          json={"prompt": "remind me in 1 second to api check"})
    assert created.status_code == 200
    import time
    time.sleep(1.2)
    assert sched.fire_due_reminders(lambda p: None) == 1

    center = client.get("/api/notifications/center").json()
    assert len(center["reminders"]["active"]) == 1
    assert center["unread_count"] == 1
    rid = center["reminders"]["active"][0]["id"]
    assert rid.startswith("reminder:")

    # Restart view: same snapshot, no duplicate identities.
    again = client.get("/api/notifications/center").json()
    ids = [i["id"] for i in again["reminders"]["active"]]
    assert ids == [rid]

    # Snooze hides it; nothing refires spuriously.
    snoozed = client.post("/api/notifications/snooze",
                          json={"id": rid, "minutes": 30}).json()
    assert snoozed["status"] == "success" and snoozed["human"]
    assert client.get("/api/notifications/unread-count").json() == {"unread": 0}
    assert sched.fire_due_reminders(lambda p: None) == 0

    # Unknown ids fail cleanly (frontend keeps the item visible).
    assert client.post("/api/notifications/read",
                       json={"id": "reminder:missing"}).status_code == 404
    assert client.post("/api/notifications/delete",
                       json={"id": "gmail:missing"}).status_code == 404
    bad_snooze = client.post("/api/notifications/snooze",
                             json={"id": "gmail:x", "minutes": 10})
    assert bad_snooze.status_code == 400


def test_api_read_all_and_clear_history_guards(client):
    notif_store.upsert_notification("gmail:a", "gmail", "A", "b")
    notif_store.upsert_notification("gmail:b", "gmail", "B", "b")
    read_all = client.post("/api/notifications/read-all").json()
    assert read_all["status"] == "success" and read_all["marked"] == 2
    assert client.get("/api/notifications/unread-count").json() == {"unread": 0}

    # Future reminder + pending scheduled message survive clear-history.
    client.post("/api/command",
                json={"prompt": "remind me in 2 hours to futureproof"})
    sched.schedule_whatsapp("Mom", "later",
                            datetime.now(timezone.utc) + timedelta(hours=2))
    cleared = client.post("/api/notifications/clear-history").json()
    assert cleared["cleared"] == 2
    center = client.get("/api/notifications/center").json()
    assert len(center["reminders"]["upcoming"]) == 1
    assert any(j["status"] == "pending" for j in center["scheduled"])


def test_api_scheduled_reschedule_validation(client):
    job = sched.schedule_whatsapp("Mom", "hi",
                                  datetime.now(timezone.utc) + timedelta(hours=2))["job"]
    jid = job["id"]
    assert client.post(f"/api/scheduled/{jid}/reschedule",
                       json={"when": "not-a-time"}).status_code == 400
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert client.post(f"/api/scheduled/{jid}/reschedule",
                       json={"when": past}).status_code == 400
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    ok = client.post(f"/api/scheduled/{jid}/reschedule", json={"when": future})
    assert ok.status_code == 200
    # Pending delete cancels (history kept), history delete removes.
    assert client.delete(f"/api/scheduled/{jid}").status_code == 200
    assert sched.get_job(jid)["status"] == "cancelled"
    assert client.delete(f"/api/scheduled/{jid}").status_code == 200
    assert sched.get_job(jid) is None
