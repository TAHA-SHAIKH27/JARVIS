"""
Agent Verifier — determines whether an action truly succeeded based on
the Observer's structured verification result (not string matching).
"""
from typing import Any, Dict, Optional
from backend.agent.state import TaskState


class Verifier:
    def __init__(self):
        pass

    def verify_action(
        self,
        action: Dict[str, Any],
        result: Dict[str, Any],
        observation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Verify a single action based on its executor result AND the
        observer's real-state check.

        Returns:
          {
            "verified":    bool,
            "status":      "success" | "failure" | "retry",
            "message":     str,
            "should_retry": bool,
          }
        """
        # If the executor itself reported an error, mark unverified
        exec_ok = result.get("status") != "error" if result else False
        obs_verified = observation.get("verified", False)
        obs_message = observation.get("message", "")

        if exec_ok and obs_verified:
            return {
                "verified": True,
                "status": "success",
                "message": obs_message or result.get("message", "Action succeeded"),
                "should_retry": False,
            }
        elif not exec_ok:
            return {
                "verified": False,
                "status": "failure",
                "message": result.get("message", "Executor reported error") if result else "Executor returned no result",
                "should_retry": True,
            }
        else:
            # Executor OK but observer did not confirm
            return {
                "verified": False,
                "status": "retry",
                "message": f"Executor OK but verification failed: {obs_message}",
                "should_retry": True,
            }

    def verify(self, state: TaskState, intended_result: Any = None) -> Dict[str, Any]:
        """
        Overall task verification — used for final status after the loop.
        Checks state.errors and state.completed_steps.
        """
        if state.completion_status == "completed":
            return {
                "verification_status": "completed",
                "confidence": 1.0,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if state.retry_count >= 3:
            return {
                "verification_status": "failed",
                "confidence": 0.0,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if state.errors:
            # If there are errors but some steps completed, it's partial
            status = "failed" if not state.completed_steps else "partial"
            return {
                "verification_status": status,
                "confidence": 0.3,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if state.completed_steps:
            return {
                "verification_status": "completed",
                "confidence": 0.9,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "active_app": state.active_app,
                "errors": [],
            }

        return {
            "verification_status": "pending",
            "confidence": 0.0,
            "retry_count": state.retry_count,
            "completed_steps": state.completed_steps,
            "active_app": state.active_app,
            "errors": state.errors.copy(),
        }

    def should_retry(self, state: TaskState) -> bool:
        """Determine if the current action should be retried."""
        return (
            state.retry_count < 3
            and state.verification_status not in ("completed", "failed")
        )