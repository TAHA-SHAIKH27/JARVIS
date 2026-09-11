from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class BrowserPageState(Enum):
    NORMAL_SERP = "normal_serp"
    CAPTCHA = "captcha"
    CONSENT = "consent"
    SORRY_PAGE = "sorry_page"
    NETWORK_ERROR = "network_error"
    EMPTY_RESULTS = "empty_results"
    NAVIGATION_PENDING = "navigation_pending"
    UNKNOWN = "unknown"


class FailureClassification(Enum):
    RETRYABLE = "retryable"
    HUMAN_REQUIRED = "human_required"
    RECOVERABLE = "recoverable"
    FATAL = "fatal"
    COMPLETED = "completed"


class TaskType(Enum):
    SIMPLE = "simple"
    SEQUENTIAL = "sequential"
    RESEARCH = "research"
    RESEARCH_CALCULATION = "research_calculation"
    RESEARCH_DOCUMENT = "research_document"
    MULTI_APP = "multi_app"
    HUMAN_INTERVENTION = "human_intervention"


@dataclass
class ActionSpec:
    type: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[int] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    consumes: List[str] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    required_context_keys: List[str] = field(default_factory=list)
    retry_strategy: Optional[str] = None
    is_critical: bool = True


@dataclass
class Plan:
    actions: List[ActionSpec] = field(default_factory=list)
    goal: str = ""
    task_type: TaskType = TaskType.SIMPLE
    estimated_steps: int = 0
    validation_errors: List[str] = field(default_factory=list)
    is_valid: bool = False
    final_outcome_verification: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    verified: bool
    message: str
    classification: str = "success"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    task: str = ""
    interpreted_goal: str = ""
    original_user_intent: str = ""
    requirements: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    task_type: TaskType = TaskType.SIMPLE

    plan: Plan = field(default_factory=Plan)
    current_step: int = 0
    completed_steps: List[int] = field(default_factory=list)
    verified_steps: set[int] = field(default_factory=set)
    failed_steps: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    tool_history: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    active_app: Optional[str] = None
    active_window: Optional[str] = None
    browser_state: Optional[Dict[str, Any]] = None
    verification_status: str = "pending"
    retry_count: int = 0
    completion_status: Optional[str] = None

    search_results: List[Dict[str, Any]] = field(default_factory=list)
    extracted_sources: List[Dict[str, Any]] = field(default_factory=list)
    source_analyses: List[Dict[str, Any]] = field(default_factory=list)
    cross_source_analysis: Dict[str, Any] = field(default_factory=dict)
    synthesized_report: Dict[str, Any] = field(default_factory=dict)
    current_page_url: str = ""
    current_page_title: str = ""
    collected_numbers: List[float] = field(default_factory=list)

    action_outputs: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    human_verification_required: bool = False
    human_verification_message: str = ""
    human_verification_resolved: bool = False
    human_verification_action_index: Optional[int] = None
    human_verification_context: Dict[str, Any] = field(default_factory=dict)
    waiting_for_user: bool = False

    browser_initialized: bool = False
    browser_should_persist: bool = False

    replan_count: int = 0
    max_replans: int = 3
    last_replan_reason: str = ""

    final_outcome_verified: bool = False
    final_verification_passed: bool = False
    final_outcome_data: Dict[str, Any] = field(default_factory=dict)

    # Phase 1 persistent runtime context.
    memory_context: str = ""
    conversation_context: str = ""
    intent: Dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    task_started_at: str = ""
    phase1_initialized: bool = False

    _context: Dict[str, Any] = field(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        """Attach Phase 1 context automatically when a real task starts."""
        object.__setattr__(self, name, value)
        if name == "task" and value and not getattr(self, "phase1_initialized", False):
            try:
                self.initialize_phase1(value)
            except Exception:
                # Phase 1 persistence must never prevent the core agent from
                # running when its optional state store is unavailable.
                object.__setattr__(self, "phase1_initialized", False)

    def initialize_phase1(self, task: Optional[str] = None) -> Dict[str, Any]:
        """Load persistent memory/conversation context for the current task."""
        if task is not None:
            object.__setattr__(self, "task", task)
        from backend.agent.phase1_runtime import runtime
        context = runtime.begin_task(self.task)
        object.__setattr__(self, "task_id", context["task_id"])
        object.__setattr__(self, "task_started_at", context["started_at"])
        object.__setattr__(self, "intent", context["intent"])
        object.__setattr__(self, "memory_context", context["memory_context"])
        object.__setattr__(self, "conversation_context", context["conversation_context"])
        object.__setattr__(self, "phase1_initialized", True)
        self.update_context("memory_context", self.memory_context)
        self.update_context("conversation_context", self.conversation_context)
        self.update_context("intent", self.intent)
        self.update_context("task_id", self.task_id)
        return context

    def finalize_phase1(self, status: str, summary: str = "") -> None:
        """Persist the assistant-side outcome for future conversation context."""
        from backend.agent.phase1_runtime import runtime
        runtime.finish_task(self.task, {"status": status, "speak": summary})

    def remember(self, text: str, category: str = "general") -> Dict[str, Any]:
        from backend.agent import phase1_memory
        return phase1_memory.remember(text, category=category, source="agent")

    def recall_memory(self, query: str = "", limit: int = 8) -> str:
        from backend.agent import phase1_memory
        value = phase1_memory.memory_context(query, limit=limit)
        object.__setattr__(self, "memory_context", value)
        self.update_context("memory_context", value)
        return value

    def update_context(self, key: str, value: Any) -> None:
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)
