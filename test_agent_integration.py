"""Integration checks for the deterministic JARVIS agent loop.

Run directly with ``python test_agent_integration.py``.  These tests avoid
unsafe desktop actions while exercising recovery, CAPTCHA classification,
resume state, and document final verification.
"""
import asyncio
import os
import unittest

from backend.agent.core import AgentCore
from backend.agent.observer import Observer
from backend.agent.verifier import Verifier
from backend.agent.state import ActionSpec, Plan, TaskState
from backend.tools.browser import Browser, BrowserPageState


class RecoveryPlanner:
    def __init__(self, verified_path):
        self.verified_path = verified_path

    def plan_task(self, task, state):
        actions = [
            ActionSpec(type="unsupported_action", description="Intentionally fail"),
            ActionSpec(type="speak", description="Done", parameters={"text": "Done"}, is_critical=False),
        ]
        state.plan = Plan(actions=actions, goal=task, estimated_steps=2, is_valid=True)
        return actions

    def replan(self, task, state, failure_context):
        actions = [
            ActionSpec(type="verify_file", description="Verify recovery marker", parameters={"path": self.verified_path}),
            ActionSpec(type="speak", description="Done", parameters={"text": "Recovered"}, is_critical=False),
        ]
        state.plan = Plan(actions=actions, goal=task, estimated_steps=2, is_valid=True)
        state.replan_count += 1
        return actions


class FakeCaptchaPage:
    url = "https://www.google.com/sorry/index"

    async def title(self):
        return "Unusual traffic"

    async def content(self):
        return "<html><div class='g-recaptcha'>Please verify you are human</div></html>"

    async def inner_text(self, selector, timeout=1000):
        return "Please verify you are human"


class FakeNormalPage:
    url = "https://en.wikipedia.org/wiki/Science_Day"

    async def title(self):
        return "National Science Day - Wikipedia"

    async def content(self):
        return "<html><head><script src='https://google.com/recaptcha/api.js'></script></head><body><h1>National Science Day</h1><p>National Science Day is celebrated in India on 28 February each year to mark the discovery of the Raman effect.</p></body></html>"

    async def inner_text(self, selector, timeout=1000):
        return "National Science Day is celebrated in India on 28 February each year to mark the discovery of the Raman effect by Indian physicist Sir C. V. Raman on 28 February 1928."


class AgentIntegrationTests(unittest.TestCase):
    def test_captcha_is_a_human_blocker(self):
        browser = Browser()
        browser.page = FakeCaptchaPage()
        page_state = asyncio.run(browser.detect_page_state())
        self.assertEqual(page_state.state, BrowserPageState.CAPTCHA)
        self.assertFalse(page_state.verified)

    def test_normal_page_with_scripts_is_not_captcha(self):
        browser = Browser()
        browser.page = FakeNormalPage()
        page_state = asyncio.run(browser.detect_page_state())
        self.assertNotEqual(page_state.state, BrowserPageState.CAPTCHA)
        self.assertTrue(page_state.verified)

    def test_captcha_observation_requires_a_human(self):
        browser = Browser()
        browser.page = FakeCaptchaPage()
        action = ActionSpec(type="browser_navigate", description="Open protected page", parameters={})
        observation = asyncio.run(Observer(AgentCore().registry).observe_after_action(
            action, {"status": "success"}, TaskState(), browser
        ))
        verification = Verifier().verify_action(action, {"status": "success"}, observation)
        self.assertTrue(verification["requires_user"])
        self.assertEqual(verification["classification"], "human_required")

    def test_recovery_replaces_failed_plan_and_verifies_result(self):
        marker = os.path.abspath(__file__)
        core = AgentCore()
        core.planner = RecoveryPlanner(marker)
        result = asyncio.run(core.process("recover from an intentional failure", TaskState()))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["final_verification"]["verified"])
        self.assertEqual(result["completed_steps"], [0, 1])

    def test_resume_clears_human_pause_state(self):
        state = TaskState(waiting_for_user=True, human_verification_required=True)
        result = asyncio.run(AgentCore().resume_after_human(state, {"completed": True}))
        self.assertEqual(result["status"], "resumed")
        self.assertFalse(state.waiting_for_user)
        self.assertFalse(state.human_verification_required)

    def test_resume_endpoint_uses_active_run_state(self):
        from fastapi.testclient import TestClient
        import main

        run_id = "integration-paused-run"
        state = TaskState(waiting_for_user=True, human_verification_required=True)
        main.agent_runs[run_id] = {"state": state, "core": AgentCore(), "task": "captcha test"}
        try:
            response = TestClient(main.app).post("/api/agent/resume", json={"run_id": run_id, "resolution": {"completed": True}})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(state.waiting_for_user)
        finally:
            main.agent_runs.pop(run_id, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
