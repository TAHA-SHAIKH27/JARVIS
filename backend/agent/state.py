from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


@dataclass
class ConversationContext:
    """Conversation context - what the user is discussing."""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    last_user_message: str = ""
    last_agent_response: str = ""
    topic: str = ""
    turn_count: int = 0
    language: str = "en"

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.turn_count += 1
        if role == "user":
            self.last_user_message = content
            self.topic = self._extract_topic(content)
        elif role == "assistant":
            self.last_agent_response = content

    def _extract_topic(self, text: str) -> str:
        # Simple topic extraction from user message
        words = text.lower().split()
        # Remove common stop words
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "must", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "her", "its", "our", "their", "this", "that", "these", "those", "what", "when", "where", "who", "why", "how", "please", "thank", "thanks"}
        topic_words = [w for w in words if w not in stop_words and len(w) > 2]
        return " ".join(topic_words[:5]) if topic_words else ""


@dataclass
class TaskContext:
    """Task context - what JARVIS is currently doing."""
    current_task: str = ""
    interpreted_goal: str = ""
    plan_summary: str = ""
    current_action: str = ""
    action_index: int = 0
    completed_actions: List[str] = field(default_factory=list)
    failed_actions: List[Dict[str, Any]] = field(default_factory=list)
    progress: float = 0.0
    status: str = "pending"  # pending, running, paused, completed, failed
    estimated_steps_remaining: int = 0


@dataclass
class ComputerContext:
    """Computer context - what is currently visible/open on the machine."""
    active_window: Optional[str] = None
    active_app: Optional[str] = None
    running_apps: List[str] = field(default_factory=list)
    open_windows: List[Dict[str, Any]] = field(default_factory=list)
    ui_elements: List[Dict[str, Any]] = field(default_factory=list)
    focused_element: Optional[Dict[str, Any]] = None
    screen_resolution: Optional[tuple] = None
    last_screenshot: Optional[str] = None
    clipboard_content: str = ""
    last_updated: Optional[str] = field(default_factory=lambda: datetime.now().isoformat())

    def update_from_observation(self, observation: Dict[str, Any]):
        if observation.get("active_window"):
            self.active_window = observation["active_window"]
        if observation.get("active_app"):
            self.active_app = observation["active_app"]
        if observation.get("running_apps"):
            self.running_apps = observation["running_apps"]
        if observation.get("elements"):
            self.ui_elements = observation["elements"]
        if observation.get("focused_element"):
            self.focused_element = observation["focused_element"]
        self.last_updated = datetime.now().isoformat()


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


class VerificationMethod(Enum):
    UIA = "uia"
    BROWSER_DOM = "browser_dom"
    SCREENSHOT_VISION = "screenshot_vision"
    FILE_SYSTEM = "file_system"
    PROCESS_CHECK = "process_check"
    OCR = "ocr"


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
    
    # Structured planning fields (target architecture)
    goal: str = ""
    tool: str = ""
    expected_state: str = ""
    verification_method: str = ""
    fallback: str = ""
    max_attempts: int = 3
    confidence_threshold: float = 0.8


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

    memory_context: str = ""
    conversation_context: str = ""
    reminders_context: str = ""
    intent: Dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    task_started_at: str = ""
    phase1_initialized: bool = False

    # Separated contexts
    conversation: ConversationContext = field(default_factory=ConversationContext)
    task_context: TaskContext = field(default_factory=TaskContext)
    computer_context: ComputerContext = field(default_factory=ComputerContext)

    _context: Dict[str, Any] = field(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        """Attach Phase 1 context automatically when a real task starts."""
        object.__setattr__(self, name, value)
        if (
            name == "task"
            and value
            and "_context" in self.__dict__
            and not getattr(self, "phase1_initialized", False)
        ):
            try:
                self.initialize_phase1(value)
            except Exception:
                object.__setattr__(self, "phase1_initialized", False)

    def initialize_phase1(self, task: Optional[str] = None) -> Dict[str, Any]:
        """Load persistent context and connect it to the AI planning layer."""
        if task is not None:
            object.__setattr__(self, "task", task)
        from backend.agent.phase1_runtime import runtime, install_planner_context_bridge

        context = runtime.begin_task(self.task)
        object.__setattr__(self, "task_id", context["task_id"])
        object.__setattr__(self, "task_started_at", context["started_at"])
        object.__setattr__(self, "intent", context["intent"])
        object.__setattr__(self, "memory_context", context["memory_context"])
        object.__setattr__(self, "conversation_context", context["conversation_context"])
        object.__setattr__(self, "reminders_context", context.get("reminders_context", "No active reminders."))
        object.__setattr__(self, "phase1_initialized", True)
        self.update_context("memory_context", self.memory_context)
        self.update_context("conversation_context", self.conversation_context)
        self.update_context("reminders_context", self.reminders_context)
        self.update_context("intent", self.intent)
        self.update_context("task_id", self.task_id)
        install_planner_context_bridge()
        return context

    def finalize_phase1(self, status: str, summary: str = "") -> None:
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


# Install bridges only after all state classes are defined. Importing phase2_runtime
# earlier caused a circular import through executor -> state, which prevented the
# Phase 2 executor bridge from being installed.
from backend.agent import phase1_runtime as _phase1_runtime
from backend.agent import phase2_runtime as _phase2_runtime

_phase1_runtime.install_command_context_bridge()
_phase2_runtime.install_phase2()
