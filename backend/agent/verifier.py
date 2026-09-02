"""
Agent Verifier — determines whether an action truly succeeded based on
the Observer's structured verification result with failure classification.
"""
from typing import Any, Dict, Optional
from backend.agent.state import TaskState, ActionSpec, FailureClassification


class Verifier:
    def __init__(self):
        pass

    def verify_action(
        self,
        action: ActionSpec,
        result: Dict[str, Any],
        observation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Verify a single action based on its executor result AND the
        observer's real-state check with failure classification.

        Returns:
          {
            "verified":    bool,
            "status":      "success" | "failure" | "retry" | "human_required" | "recoverable" | "fatal",
            "message":     str,
            "should_retry": bool,
            "classification": FailureClassification value,
            "requires_user": bool,  # for human_required
            "recoverable": bool,    # for recoverable failures
          }
        """
        # If the executor itself reported an error, mark unverified
        exec_ok = result.get("status") != "error" if result else False
        obs_verified = observation.get("verified", False)
        obs_message = observation.get("message", "")
        classification = observation.get("classification", "recoverable")

        if exec_ok and obs_verified:
            return {
                "verified": True,
                "status": "success",
                "message": obs_message or result.get("message", "Action succeeded"),
                "should_retry": False,
                "classification": FailureClassification.COMPLETED.value,
                "requires_user": False,
                "recoverable": True,
            }
        elif not exec_ok:
            # Executor error - check if it's a known recoverable error
            exec_msg = result.get("message", "Executor reported error") if result else "Executor returned no result"
            # Check for specific error types
            if "timeout" in exec_msg.lower() or "timed out" in exec_msg.lower():
                return {
                    "verified": False,
                    "status": "retry",
                    "message": exec_msg,
                    "should_retry": True,
                    "classification": FailureClassification.RETRYABLE.value,
                    "requires_user": False,
                    "recoverable": True,
                }
            return {
                "verified": False,
                "status": "failure",
                "message": exec_msg,
                "should_retry": True,
                "classification": FailureClassification.RECOVERABLE.value,
                "requires_user": False,
                "recoverable": True,
            }
        else:
            # Executor OK but observer did not confirm
            # Use the classification from observer
            cls = FailureClassification(classification) if classification in [c.value for c in FailureClassification] else FailureClassification.RECOVERABLE

            if cls == FailureClassification.HUMAN_REQUIRED:
                return {
                    "verified": False,
                    "status": "human_required",
                    "message": f"Human intervention required: {obs_message}",
                    "should_retry": False,  # Don't auto-retry, wait for user
                    "classification": cls.value,
                    "requires_user": True,
                    "recoverable": True,
                }
            elif cls == FailureClassification.RETRYABLE:
                return {
                    "verified": False,
                    "status": "retry",
                    "message": f"Temporary failure (retryable): {obs_message}",
                    "should_retry": True,
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": True,
                }
            elif cls == FailureClassification.RECOVERABLE:
                return {
                    "verified": False,
                    "status": "recoverable",
                    "message": f"Strategy failed (recoverable): {obs_message}",
                    "should_retry": True,  # Will retry with different strategy or re-plan
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": True,
                }
            elif cls == FailureClassification.FATAL:
                return {
                    "verified": False,
                    "status": "fatal",
                    "message": f"Fatal error: {obs_message}",
                    "should_retry": False,
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": False,
                }
            else:
                return {
                    "verified": False,
                    "status": "recoverable",
                    "message": f"Verification failed: {obs_message}",
                    "should_retry": True,
                    "classification": FailureClassification.RECOVERABLE.value,
                    "requires_user": False,
                    "recoverable": True,
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

    def should_retry(self, state: TaskState, classification: str = None) -> bool:
        """Determine if the current action should be retried based on classification."""
        if classification == FailureClassification.HUMAN_REQUIRED.value:
            return False  # Never auto-retry human required
        if classification == FailureClassification.FATAL.value:
            return False  # Never retry fatal
        if classification == FailureClassification.RECOVERABLE.value:
            return state.retry_count < 2  # Limited retries for recoverable
        if classification == FailureClassification.RETRYABLE.value:
            return state.retry_count < 3  # Standard retries
        return state.retry_count < 3