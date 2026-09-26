"""
Standardized tool result schemas for JARVIS.

All tools should return results conforming to these schemas for consistent
verification and error handling across the agent loop.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ToolResultStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    HUMAN_VERIFICATION_REQUIRED = "human_verification_required"
    PARTIAL = "partial"


@dataclass
class ToolResult:
    """Base result structure for all tools."""
    status: str
    action: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    recoverable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status,
            "action": self.action,
            "message": self.message,
        }
        if self.data:
            result["data"] = self.data
        # NOTE: the `error` field name collides with the `error()` classmethod
        # below, so an unset error defaults to the bound method, not None.
        # Only emit real error payloads; this also keeps results JSON-safe.
        if self.error and not callable(self.error):
            result["error"] = self.error
        result["recoverable"] = self.recoverable
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def success(cls, action: str, message: str, data: Dict[str, Any] = None, metadata: Dict[str, Any] = None) -> "ToolResult":
        return cls(
            status=ToolResultStatus.SUCCESS.value,
            action=action,
            message=message,
            data=data or {},
            metadata=metadata or {},
            recoverable=True,
        )

    @classmethod
    def error(cls, action: str, message: str, error: str = None, recoverable: bool = True, metadata: Dict[str, Any] = None) -> "ToolResult":
        return cls(
            status=ToolResultStatus.ERROR.value,
            action=action,
            message=message,
            error=error or message,
            recoverable=recoverable,
            metadata=metadata or {},
        )

    @classmethod
    def human_required(cls, action: str, message: str, data: Dict[str, Any] = None, metadata: Dict[str, Any] = None) -> "ToolResult":
        return cls(
            status=ToolResultStatus.HUMAN_VERIFICATION_REQUIRED.value,
            action=action,
            message=message,
            data=data or {},
            recoverable=True,
            metadata=metadata or {},
        )

    @classmethod
    def partial(cls, action: str, message: str, data: Dict[str, Any] = None, metadata: Dict[str, Any] = None) -> "ToolResult":
        return cls(
            status=ToolResultStatus.PARTIAL.value,
            action=action,
            message=message,
            data=data or {},
            recoverable=True,
            metadata=metadata or {},
        )


# Computer tool specific result structures
@dataclass
class ComputerActionResult(ToolResult):
    """Result from computer automation actions."""
    target: Optional[str] = None
    element: Optional[Dict[str, Any]] = None
    coordinates: Optional[List[int]] = None
    screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.target:
            result["target"] = self.target
        if self.element:
            result["element"] = self.element
        if self.coordinates:
            result["coordinates"] = self.coordinates
        if self.screenshot_path:
            result["screenshot_path"] = self.screenshot_path
        return result


@dataclass
class UIElement:
    """Standardized UI element representation with comprehensive metadata."""
    name: str
    role: str
    bounds: List[int]  # [x1, y1, x2, y2]
    confidence: float
    source: str  # "uia", "win32", "ocr", "vision"
    enabled: bool = True
    class_name: str = ""
    automation_id: str = ""
    
    # Enhanced metadata fields
    framework_id: str = ""
    state: str = ""  # "normal", "focused", "selected", "checked", "disabled", "hidden", "read_only", "required"
    visible: bool = True
    focused: bool = False
    selected: bool = False
    checked: Optional[bool] = None
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    uia_patterns: List[str] = field(default_factory=list)  # "invoke", "expand_collapse", "toggle", "scroll", "value", "range_value", "selection", "grid", "table", "text", "window"
    available_actions: List[str] = field(default_factory=list)  # "click", "double_click", "right_click", "type", "select", "expand", "collapse", "scroll", "drag", "hover"
    keyboard_shortcuts: List[str] = field(default_factory=list)
    interaction_hints: List[str] = field(default_factory=list)
    element_id: str = ""  # unique identifier for this element
    process_id: Optional[int] = None
    framework: str = ""  # "Win32", "WPF", "Chrome", "Edge", "Firefox", "Electron", "Java", "Qt", "Unknown"
    depth: int = 0  # depth in UI tree
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "bounds": self.bounds,
            "confidence": self.confidence,
            "source": self.source,
            "enabled": self.enabled,
            "class_name": self.class_name,
            "automation_id": self.automation_id,
            "framework_id": self.framework_id,
            "state": self.state,
            "visible": self.visible,
            "focused": self.focused,
            "selected": self.selected,
            "checked": self.checked,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "uia_patterns": self.uia_patterns,
            "available_actions": self.available_actions,
            "keyboard_shortcuts": self.keyboard_shortcuts,
            "interaction_hints": self.interaction_hints,
            "element_id": self.element_id,
            "process_id": self.process_id,
            "framework": self.framework,
            "depth": self.depth,
        }


@dataclass
class WindowInfo:
    """Standardized window information."""
    handle: str
    title: str
    class_name: str
    bounds: List[int]  # [x1, y1, x2, y2]
    is_active: bool = False
    process_id: Optional[int] = None
    process_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handle": self.handle,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds,
            "is_active": self.is_active,
            "process_id": self.process_id,
            "process_name": self.process_name,
        }


@dataclass
class ScreenObservation:
    """Structured screen observation result."""
    application: str
    window_title: str
    elements: List[UIElement]
    active_window: Optional[WindowInfo] = None
    running_apps: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=__import__('time').time)
    source: str = "mixed"
    
    # Enhanced hierarchy and semantic understanding
    ui_tree: Dict[str, Any] = field(default_factory=dict)  # full UI tree with parent/children
    element_groups: Dict[str, List[UIElement]] = field(default_factory=dict)  # elements grouped by role
    interaction_hints: List[str] = field(default_factory=list)
    confidence: float = 0.95
    window_class: str = ""
    window_bounds: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "application": self.application,
            "window_title": self.window_title,
            "elements": [e.to_dict() for e in self.elements],
            "active_window": self.active_window.to_dict() if self.active_window else None,
            "running_apps": self.running_apps,
            "timestamp": self.timestamp,
            "source": self.source,
            "ui_tree": self.ui_tree,
            "element_groups": {k: [e.to_dict() for e in v] for k, v in self.element_groups.items()},
            "interaction_hints": self.interaction_hints,
            "confidence": self.confidence,
            "window_class": self.window_class,
            "window_bounds": self.window_bounds,
        }


# Browser tool specific result structures
@dataclass
class BrowserActionResult(ToolResult):
    """Result from browser automation actions."""
    url: Optional[str] = None
    title: Optional[str] = None
    page_state: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    # Optional payload fields used by extract/type/get_page_text/get_links/
    # screenshot/click/search callers. All default to None so old code paths
    # are unaffected; to_dict() only emits fields that are set.
    text: Optional[str] = None
    value: Optional[str] = None
    selector: Optional[str] = None
    query: Optional[str] = None
    before_url: Optional[str] = None
    links: Optional[List[Any]] = None
    path: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    retryable: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.url:
            result["url"] = self.url
        if self.title:
            result["title"] = self.title
        if self.page_state:
            result["page_state"] = self.page_state
        if self.results:
            result["results"] = self.results
        if self.text:
            result["text"] = self.text
        if self.value is not None:
            result["value"] = self.value
        if self.selector:
            result["selector"] = self.selector
        if self.query:
            result["query"] = self.query
        if self.before_url:
            result["before_url"] = self.before_url
        if self.links is not None:
            result["links"] = self.links
        if self.path:
            result["path"] = self.path
        if self.details is not None:
            result["details"] = self.details
        if self.retryable is not None:
            result["retryable"] = self.retryable
        return result


@dataclass
class SearchResult:
    """Standardized search result."""
    title: str
    url: str
    snippet: str = ""
    index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "index": self.index,
        }


@dataclass
class ExtractedSource:
    """Standardized extracted page content."""
    url: str
    title: str
    text: str
    source_index: int = 0
    word_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "source_index": self.source_index,
            "word_count": self.word_count,
        }


# Office tool specific result structures
@dataclass
class OfficeActionResult(ToolResult):
    """Result from office document generation."""
    path: Optional[str] = None
    document_type: Optional[str] = None  # "docx" or "pptx"
    page_count: Optional[int] = None
    slide_count: Optional[int] = None
    paragraph_count: Optional[int] = None
    word_count: Optional[int] = None
    verified: Optional[bool] = None
    has_summary: Optional[bool] = None
    has_findings: Optional[bool] = None
    has_references: Optional[bool] = None
    noise_detected: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.path:
            result["path"] = self.path
        if self.document_type:
            result["document_type"] = self.document_type
        if self.page_count:
            result["page_count"] = self.page_count
        if self.slide_count:
            result["slide_count"] = self.slide_count
        if self.paragraph_count:
            result["paragraph_count"] = self.paragraph_count
        if self.word_count is not None:
            result["word_count"] = self.word_count
        if self.verified is not None:
            result["verified"] = self.verified
        if self.has_summary is not None:
            result["has_summary"] = self.has_summary
        if self.has_findings is not None:
            result["has_findings"] = self.has_findings
        if self.has_references is not None:
            result["has_references"] = self.has_references
        if self.noise_detected is not None:
            result["noise_detected"] = self.noise_detected
        return result


# Filesystem tool specific result structures
@dataclass
class FilesystemActionResult(ToolResult):
    """Result from filesystem actions."""
    path: Optional[str] = None
    exists: bool = False
    size: Optional[int] = None
    is_directory: bool = False

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.path:
            result["path"] = self.path
        result["exists"] = self.exists
        if self.size is not None:
            result["size"] = self.size
        result["is_directory"] = self.is_directory
        return result


# Helper functions for creating standardized results
def create_computer_result(action: str, status: str, message: str, **kwargs) -> Dict[str, Any]:
    """Create a standardized computer tool result."""
    result = ComputerActionResult(
        status=status,
        action=action,
        message=message,
        **kwargs
    )
    return result.to_dict()


def create_browser_result(action: str, status: str, message: str, **kwargs) -> Dict[str, Any]:
    """Create a standardized browser tool result."""
    result = BrowserActionResult(
        status=status,
        action=action,
        message=message,
        **kwargs
    )
    return result.to_dict()


def create_office_result(action: str, status: str, message: str, **kwargs) -> Dict[str, Any]:
    """Create a standardized office tool result."""
    result = OfficeActionResult(
        status=status,
        action=action,
        message=message,
        **kwargs
    )
    return result.to_dict()


def create_filesystem_result(action: str, status: str, message: str, **kwargs) -> Dict[str, Any]:
    """Create a standardized filesystem tool result."""
    result = FilesystemActionResult(
        status=status,
        action=action,
        message=message,
        **kwargs
    )
    return result.to_dict()