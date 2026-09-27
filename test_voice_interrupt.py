"""Tests for voice interruption / mid-task instruction triage.

Covers VoiceCommandProcessor: empty input, interruption keywords (speech
stopped + core interrupt requested), mid-task merge vs queue verdicts, and
fresh commands. These are the backend paths the hands-free barge-in and the
agent-mode voice routing rely on.
"""
import asyncio

import pytest

from backend.agent.voice import VoiceCommandProcessor


class FakeCore:
    def __init__(self):
        self.interrupts = []
        self.injected = []

    def request_interrupt(self, reason=""):
        self.interrupts.append(reason)

    def inject_mid_task_instruction(self, text):
        self.injected.append(text)


class FakeState:
    def __init__(self, task=""):
        self.task = task


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_empty_command_rejected():
    proc = VoiceCommandProcessor(FakeCore())
    assert run(proc.process_command("   ", FakeState("task")))["status"] == "error"


@pytest.mark.parametrize("phrase", [
    "stop", "stop that right now", "wait wait", "hold on",
    "quiet please", "shush", "that's enough", "cancel everything",
])
def test_interruption_keywords(phrase):
    core = FakeCore()
    proc = VoiceCommandProcessor(core)
    res = run(proc.process_command(phrase, FakeState("some active task")))
    assert res["status"] == "interrupted"
    assert len(core.interrupts) == 1
    assert phrase in core.interrupts[0]


def test_non_interruption_passes_through():
    core = FakeCore()
    proc = VoiceCommandProcessor(core)
    res = run(proc.process_command("what is the weather", FakeState()))
    assert res["status"] == "new_command"
    assert core.interrupts == []


def test_active_task_related_merges():
    core = FakeCore()
    proc = VoiceCommandProcessor(core)
    state = FakeState("search for pictures of cats")
    res = run(proc.process_command("actually search for pictures of dogs", state))
    assert res["status"] == "mid_task_instruction"
    assert core.injected == ["actually search for pictures of dogs"]


def test_active_task_unrelated_queues():
    core = FakeCore()
    proc = VoiceCommandProcessor(core)
    state = FakeState("search for pictures of cats")
    res = run(proc.process_command("open the calculator application", state))
    assert res["status"] == "task_queued"
    assert core.injected == ["open the calculator application"]


def test_no_task_starts_new_command():
    core = FakeCore()
    proc = VoiceCommandProcessor(core)
    res = run(proc.process_command("take a screenshot", FakeState()))
    assert res["status"] == "new_command"
    assert res["text"] == "take a screenshot"


def test_interruption_detector_direct():
    proc = VoiceCommandProcessor()
    assert proc._is_interruption("please stop talking") is True
    assert proc._is_interruption("tell me a joke") is False
