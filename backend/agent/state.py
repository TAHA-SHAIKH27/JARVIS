from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class TaskState:
    task: str = ""
    plan: List[str] = field(default_factory=list)
    current_step: int = 0
    completed_steps: List[int] = field(default_factory=list)
    tool_history: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    active_app: Optional[str] = None
    active_window: Optional[str] = None
    browser_state: Optional[Dict[str, Any]] = None
    verification_status: str = "pending"
    retry_count: int = 0
    completion_status: Optional[str] = None