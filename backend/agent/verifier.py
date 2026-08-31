from typing import Any, Dict, Optional, List
from backend.agent.state import TaskState


class Verifier:
    def __init__(self):
        pass

    def verify(self, state: TaskState, intended_result: Any = None) -> Dict[str, Any]:
        """Verify that the intended result was achieved based on the task and observations."""
        verification_status = "pending"
        confidence = 0.0

        # Check completion status
        if state.completion_status:
            verification_status = state.completion_status
        else:
            # Analyze observations and tool history for success/failure signals
            verification_status = self._analyze_verification(state)

        # Calculate confidence based on retry count and observation quality
        max_retries = 3
        retry_penalty = min(state.retry_count / max_retries, 1.0)
        confidence = max(0.0, 1.0 - retry_penalty)

        # If we've retried too much, mark as failed
        if state.retry_count >= max_retries:
            verification_status = "failed"
            confidence = 0.0

        return {
            "verification_status": verification_status,
            "confidence": confidence,
            "retry_count": state.retry_count,
            "completed_steps": state.completed_steps,
            "active_app": state.active_app,
            "errors": state.errors.copy()
        }

    def _analyze_verification(self, state: TaskState) -> str:
        """Analyze observations and tool history to determine verification status."""
        # Check for error patterns in tool history
        errors_found = []
        for entry in state.tool_history:
            action_type = entry.get("type", "")
            if isinstance(action_type, str) and action_type.startswith("error"):
                errors_found.append(action_type)

        # Check observations for success/failure indicators
        success_indicators = ["success", "completed", "launched", "opened", "saved"]
        failure_indicators = ["error", "failed", "failed to", "cannot", "no such"]

        obs_text = " ".join(state.observations).lower()

        has_success = any(ind in obs_text for ind in success_indicators)
        has_failure = any(ind in obs_text for ind in failure_indicators)

        # Also check the errors list in state
        has_state_errors = len(state.errors) > 0

        if has_failure or has_state_errors:
            return "failed"
        elif has_success or len(state.completed_steps) > 0:
            return "completed"
        elif state.retry_count > 0:
            return "retrying"
        else:
            return "pending"

    def should_retry(self, state: TaskState) -> bool:
        """Determine if the task should be retried based on current state."""
        return state.retry_count < 3 and state.verification_status not in ("completed", "failed")