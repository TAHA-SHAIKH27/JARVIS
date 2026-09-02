from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime
from enum import Enum


class BrowserPageState(Enum):
    """Detected state of the browser page after navigation/search."""
    NORMAL_SERP = "normal_serp"
    CAPTCHA = "captcha"
    CONSENT = "consent"
    SORRY_PAGE = "sorry_page"
    NETWORK_ERROR = "network_error"
    EMPTY_RESULTS = "empty_results"
    NAVIGATION_PENDING = "navigation_pending"
    UNKNOWN = "unknown"


class FailureClassification(Enum):
    """Classification of action failures for proper retry/handling logic."""
    RETRYABLE = "retryable"           # Temporary: timeout, navigation failure, page loading
    HUMAN_REQUIRED = "human_required" # CAPTCHA, human verification, login requiring user interaction
    RECOVERABLE = "recoverable"       # Strategy failed: selector broken, DOM changed, extraction strategy failed
    FATAL = "fatal"                   # Browser unavailable, invalid action, unrecoverable executor error
    COMPLETED = "completed"           # Intended result verified


class TaskType(Enum):
    """Classification of task complexity for planning strategy."""
    SIMPLE = "simple"                 # Single action (open app, type text)
    SEQUENTIAL = "sequential"         # Multiple dependent steps
    RESEARCH = "research"             # Information gathering from multiple sources
    RESEARCH_CALCULATION = "research_calculation"  # Research + calculation
    RESEARCH_DOCUMENT = "research_document"        # Research + document creation
    MULTI_APP = "multi_app"           # Multiple applications
    HUMAN_INTERVENTION = "human_intervention"      # Requires user input


@dataclass
class ActionSpec:
    """Structured action specification with dependencies and validation."""
    type: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[int] = field(default_factory=list)  # Step indices this action depends on
    produces: List[str] = field(default_factory=list)    # State keys this action produces
    consumes: List[str] = field(default_factory=list)    # State keys this action consumes
    verification: Dict[str, Any] = field(default_factory=dict)  # Expected verification criteria
    expected_outcome: str = ""
    required_context_keys: List[str] = field(default_factory=list)
    retry_strategy: Optional[str] = None  # "same", "replan", "alternative"
    is_critical: bool = True  # If false, failure doesn't halt entire task


@dataclass
class Plan:
    """Validated execution plan with metadata."""
    actions: List[ActionSpec] = field(default_factory=list)
    goal: str = ""
    task_type: TaskType = TaskType.SIMPLE
    estimated_steps: int = 0
    validation_errors: List[str] = field(default_factory=list)
    is_valid: bool = False
    final_outcome_verification: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Detailed result of an observation verification."""
    verified: bool
    message: str
    classification: str = "success"  # success, retryable, human_required, recoverable, fatal
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    task: str = ""
    interpreted_goal: str = ""
    original_user_intent: str = ""
    requirements: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    task_type: TaskType = TaskType.SIMPLE
    
    # Plan and execution state
    plan: Plan = field(default_factory=Plan)
    current_step: int = 0
    completed_steps: List[int] = field(default_factory=list)
    verified_steps: set[int] = field(default_factory=set)
    failed_steps: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # step_index -> failure info
    tool_history: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    active_app: Optional[str] = None
    active_window: Optional[str] = None
    browser_state: Optional[Dict[str, Any]] = None
    verification_status: str = "pending"
    retry_count: int = 0
    completion_status: Optional[str] = None
    
    # ── Browser research data passing ────────────────────────────────────────
    search_results: List[Dict[str, Any]] = field(default_factory=list)
    extracted_sources: List[Dict[str, Any]] = field(default_factory=list)
    current_page_url: str = ""
    current_page_title: str = ""
    collected_numbers: List[float] = field(default_factory=list)
    
    # ── Structured action outputs for data flow ──────────────────────────────
    action_outputs: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # step_index -> output
    
    # ── Human-in-the-loop state ──────────────────────────────────────────────
    human_verification_required: bool = False
    human_verification_message: str = ""
    human_verification_resolved: bool = False
    human_verification_action_index: Optional[int] = None
    human_verification_context: Dict[str, Any] = field(default_factory=dict)
    waiting_for_user: bool = False
    
    # ── Browser lifecycle ────────────────────────────────────────────────────
    browser_initialized: bool = False
    browser_should_persist: bool = False
    
    # ── Replanning state ─────────────────────────────────────────────────────
    replan_count: int = 0
    max_replans: int = 3
    last_replan_reason: str = ""
    
    # ── Final outcome verification ───────────────────────────────────────────
    final_outcome_verified: bool = False
    final_verification_passed: bool = False
    final_outcome_data: Dict[str, Any] = field(default_factory=dict)

    # ── Context management ───────────────────────────────────────────────────
    _context: Dict[str, Any] = field(default_factory=dict)

    def update_context(self, key: str, value: Any) -> None:
        """Update shared context data."""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Retrieve shared context data."""
        return self._context.get(key, default)