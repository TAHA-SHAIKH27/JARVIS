"""
Agent Verifier — determines whether an action truly succeeded based on
the Observer's structured verification result with failure classification.

Verification outcomes:
- SUCCESS: Both executor and observer confirm action completed as expected
- PARTIAL_SUCCESS: Executor succeeded but observer could only partially verify
- FAILURE: Action did not achieve expected outcome
- UNKNOWN: Cannot determine outcome (missing verifier, etc.)
"""
from enum import Enum
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from backend.agent.state import TaskState, ActionSpec, FailureClassification
from backend.tools.result_schema import ToolResultStatus


class VerificationOutcome(Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


@dataclass
class VerificationConfig:
    """Configuration for verification confidence thresholds per action type."""
    min_confidence_for_success: float = 0.7
    min_confidence_for_partial: float = 0.4
    executor_weight: float = 0.4
    observer_weight: float = 0.6
    # Action-type specific confidence modifiers
    action_type_modifiers: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "open_app_wait": {"executor_weight": 0.3, "observer_weight": 0.7},
        "type_in_app": {"executor_weight": 0.2, "observer_weight": 0.8},
        "click_ui": {"executor_weight": 0.3, "observer_weight": 0.7},
        "browser_search": {"executor_weight": 0.5, "observer_weight": 0.5},
        "browser_navigate": {"executor_weight": 0.4, "observer_weight": 0.6},
        "browser_extract": {"executor_weight": 0.3, "observer_weight": 0.7},
        "create_docx": {"executor_weight": 0.4, "observer_weight": 0.6},
        "create_pptx": {"executor_weight": 0.4, "observer_weight": 0.6},
        "calculator_compute": {"executor_weight": 0.5, "observer_weight": 0.5},
        "find_ui_element": {"executor_weight": 0.2, "observer_weight": 0.8},
    })


class Verifier:
    def __init__(self, config: Optional[VerificationConfig] = None):
        self.config = config or VerificationConfig()

    def _get_action_weights(self, action_type: str) -> tuple:
        """Get executor and observer weights for an action type."""
        modifiers = self.config.action_type_modifiers.get(action_type, {})
        executor_w = modifiers.get("executor_weight", self.config.executor_weight)
        observer_w = modifiers.get("observer_weight", self.config.observer_weight)
        # Normalize
        total = executor_w + observer_w
        return executor_w / total, observer_w / total

    def _calculate_confidence(self, exec_ok: bool, exec_message: str, 
                             obs_verified: bool, obs_message: str,
                             obs_confidence: float, classification: str,
                             action_type: str) -> float:
        """Calculate verification confidence with sophisticated scoring."""
        executor_w, observer_w = self._get_action_weights(action_type)
        
        # Base confidence from executor
        if exec_ok:
            exec_conf = 0.8
            # Boost for specific success indicators
            if "success" in exec_message.lower() or "verified" in exec_message.lower():
                exec_conf = 0.9
            elif "completed" in exec_message.lower():
                exec_conf = 0.85
        else:
            exec_conf = 0.1
            if "timeout" in exec_message.lower():
                exec_conf = 0.3
        
        # Observer confidence
        if obs_verified:
            obs_conf = max(obs_confidence, 0.85)
        else:
            obs_conf = obs_confidence * 0.5  # Penalize unverified
            # But check for partial progress indicators
            if obs_message and any(kw in obs_message.lower() for kw in ["found", "partial", "some", "progress", "detected"]):
                obs_conf = max(obs_conf, 0.4)
        
        # Weighted combination
        confidence = (executor_w * exec_conf) + (observer_w * obs_conf)
        
        # Classification-based adjustments
        if classification == "human_required":
            confidence = 0.0  # Cannot verify without human
        elif classification == "fatal":
            confidence = 0.05
        elif classification == "retryable":
            confidence = max(confidence, 0.3)  # Might succeed on retry
        
        return min(max(confidence, 0.0), 1.0)

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
            "outcome":     "success" | "partial_success" | "failure" | "unknown",
            "status":      "success" | "retry" | "human_required" | "recoverable" | "fatal",
            "message":     str,
            "should_retry": bool,
            "classification": FailureClassification value,
            "requires_user": bool,  # for human_required
            "recoverable": bool,    # for recoverable failures
            "confidence":  float,   # 0.0 - 1.0 confidence in verification
          }
        """
        # If the executor itself reported an error, mark unverified
        exec_ok = result.get("status") != "error" if result else False
        exec_message = result.get("message", "") if result else "Executor returned no result"
        obs_verified = observation.get("verified", False)
        obs_message = observation.get("message", "")
        classification = observation.get("classification", "recoverable")
        obs_confidence = observation.get("confidence", 0.5)

        # Calculate confidence using sophisticated scoring
        confidence = self._calculate_confidence(
            exec_ok, exec_message, obs_verified, obs_message,
            obs_confidence, classification, action.type
        )

        if exec_ok and obs_verified:
            return {
                "verified": True,
                "outcome": VerificationOutcome.SUCCESS.value,
                "status": "success",
                "message": obs_message or exec_message or "Action succeeded",
                "should_retry": False,
                "classification": FailureClassification.COMPLETED.value,
                "requires_user": False,
                "recoverable": True,
                "confidence": confidence,
            }
        elif not exec_ok:
            # Executor error - check if it's a known recoverable error
            if "timeout" in exec_message.lower() or "timed out" in exec_message.lower():
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.FAILURE.value,
                    "status": "retry",
                    "message": exec_message,
                    "should_retry": True,
                    "classification": FailureClassification.RETRYABLE.value,
                    "requires_user": False,
                    "recoverable": True,
                    "confidence": self._calculate_confidence(False, exec_message, False, "", 0.3, "retryable", action.type),
                }
            return {
                "verified": False,
                "outcome": VerificationOutcome.FAILURE.value,
                "status": "failure",
                "message": exec_message,
                "should_retry": True,
                "classification": FailureClassification.RECOVERABLE.value,
                "requires_user": False,
                "recoverable": True,
                "confidence": self._calculate_confidence(False, exec_message, False, "", 0.1, "recoverable", action.type),
            }
        else:
            # Executor OK but observer did not confirm
            # Use the classification from observer
            try:
                cls = FailureClassification(classification) if classification in [c.value for c in FailureClassification] else FailureClassification.RECOVERABLE
            except ValueError:
                cls = FailureClassification.RECOVERABLE

            calc_confidence = self._calculate_confidence(True, exec_message, False, obs_message, obs_confidence, classification, action.type)

            if cls == FailureClassification.HUMAN_REQUIRED:
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.FAILURE.value,
                    "status": "human_required",
                    "message": f"Human intervention required: {obs_message}",
                    "should_retry": False,  # Don't auto-retry, wait for user
                    "classification": cls.value,
                    "requires_user": True,
                    "recoverable": True,
                    "confidence": 0.0,
                }
            elif cls == FailureClassification.RETRYABLE:
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.FAILURE.value,
                    "status": "retry",
                    "message": f"Temporary failure (retryable): {obs_message}",
                    "should_retry": True,
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": True,
                    "confidence": calc_confidence,
                }
            elif cls == FailureClassification.RECOVERABLE:
                # Check if this is a partial success (some progress made)
                if obs_message and any(kw in obs_message.lower() for kw in ["found", "partial", "some", "progress", "detected", "located"]):
                    return {
                        "verified": False,
                        "outcome": VerificationOutcome.PARTIAL_SUCCESS.value,
                        "status": "recoverable",
                        "message": f"Partial progress: {obs_message}",
                        "should_retry": True,
                        "classification": cls.value,
                        "requires_user": False,
                        "recoverable": True,
                        "confidence": max(calc_confidence, 0.5),
                    }
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.FAILURE.value,
                    "status": "recoverable",
                    "message": f"Strategy failed (recoverable): {obs_message}",
                    "should_retry": True,  # Will retry with different strategy or re-plan
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": True,
                    "confidence": calc_confidence,
                }
            elif cls == FailureClassification.FATAL:
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.FAILURE.value,
                    "status": "fatal",
                    "message": f"Fatal error: {obs_message}",
                    "should_retry": False,
                    "classification": cls.value,
                    "requires_user": False,
                    "recoverable": False,
                    "confidence": 0.05,
                }
            else:
                return {
                    "verified": False,
                    "outcome": VerificationOutcome.UNKNOWN.value,
                    "status": "recoverable",
                    "message": f"Verification failed: {obs_message}",
                    "should_retry": True,
                    "classification": FailureClassification.RECOVERABLE.value,
                    "requires_user": False,
                    "recoverable": True,
                    "confidence": 0.2,
                }

    def verify(self, state: TaskState, intended_result: Any = None) -> Dict[str, Any]:
        """
        Overall task verification — used for final status after the loop.
        Checks state.errors and state.completed_steps.
        Returns structured verification with outcome classification.
        """
        total_steps = len(state.plan.actions) if state.plan and state.plan.actions else 0
        completed = len(state.completed_steps)
        failed = len(state.failed_steps)
        
        if state.completion_status == "completed":
            return {
                "verification_status": "completed",
                "outcome": VerificationOutcome.SUCCESS.value,
                "confidence": 1.0,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "total_steps": total_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if state.retry_count >= 3 and completed == 0:
            return {
                "verification_status": "failed",
                "outcome": VerificationOutcome.FAILURE.value,
                "confidence": 0.0,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "total_steps": total_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if state.errors:
            # If there are errors but some steps completed, it's partial
            if completed > 0:
                return {
                    "verification_status": "partial",
                    "outcome": VerificationOutcome.PARTIAL_SUCCESS.value,
                    "confidence": 0.4,
                    "retry_count": state.retry_count,
                    "completed_steps": state.completed_steps,
                    "total_steps": total_steps,
                    "failed_steps": failed,
                    "active_app": state.active_app,
                    "errors": state.errors.copy(),
                }
            return {
                "verification_status": "failed",
                "outcome": VerificationOutcome.FAILURE.value,
                "confidence": 0.1,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "total_steps": total_steps,
                "active_app": state.active_app,
                "errors": state.errors.copy(),
            }

        if completed > 0:
            return {
                "verification_status": "completed",
                "outcome": VerificationOutcome.SUCCESS.value,
                "confidence": 0.9,
                "retry_count": state.retry_count,
                "completed_steps": state.completed_steps,
                "total_steps": total_steps,
                "active_app": state.active_app,
                "errors": [],
            }

        return {
            "verification_status": "pending",
            "outcome": VerificationOutcome.UNKNOWN.value,
            "confidence": 0.0,
            "retry_count": state.retry_count,
            "completed_steps": state.completed_steps,
            "total_steps": total_steps,
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