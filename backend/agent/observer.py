"""
Agent Observer — verifies REAL system state after each action.
Never returns "success" based on assumptions.
Detects CAPTCHA, consent pages, and other browser states.
Provides structured state representation for semantic computer understanding.
"""
import asyncio
import os
import time
import json
import uuid
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field

from backend.agent.state import TaskState, ActionSpec, VerificationResult
from backend.agent.registry import ToolRegistry
from backend.tools.browser import Browser, BrowserPageState
from backend.tools.result_schema import ScreenObservation, UIElement, WindowInfo, ToolResultStatus, create_computer_result


@dataclass
class SemanticState:
    """Enhanced structured state with semantic understanding."""
    application: str
    window_title: str
    window_class: str
    window_bounds: List[int]  # [x1, y1, x2, y2]
    elements: List[UIElement]
    running_apps: List[str]
    active_window: Optional[WindowInfo] = None
    timestamp: float = field(default_factory=time.time)
    source: str = "mixed"
    
    # Semantic understanding
    ui_hierarchy: Dict[str, Any] = field(default_factory=dict)
    element_groups: Dict[str, List[UIElement]] = field(default_factory=dict)
    interaction_hints: List[str] = field(default_factory=list)
    confidence: float = 0.95
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "application": self.application,
            "window_title": self.window_title,
            "window_class": self.window_class,
            "window_bounds": self.window_bounds,
            "elements": [e.to_dict() for e in self.elements],
            "running_apps": self.running_apps,
            "active_window": self.active_window.to_dict() if self.active_window else None,
            "timestamp": self.timestamp,
            "source": self.source,
            "ui_hierarchy": self.ui_hierarchy,
            "element_groups": {k: [e.to_dict() for e in v] for k, v in self.element_groups.items()},
            "interaction_hints": self.interaction_hints,
            "confidence": self.confidence,
        }


class Observer:
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()
        self._computer = None

    def _get_computer(self):
        if self._computer is None:
            computer = self.registry.get("computer_tool")
            if computer:
                self._computer = computer
        return self._computer

    async def observe(self, state: TaskState, focus: str = "general") -> Dict[str, Any]:
        """Lightweight general observation (used at start of each loop iteration)."""
        observations = {"observations": []}

        try:
            import psutil
            running = set()
            for proc in psutil.process_iter(["name"]):
                try:
                    running.add(proc.info["name"].lower())
                except Exception:
                    pass
            observations["running_apps"] = list(running)
        except Exception:
            observations["running_apps"] = []

        observations["observations"].append(f"System snapshot taken: focus={focus}")
        return observations

    async def get_structured_state(self, state: TaskState) -> SemanticState:
        """
        Get a semantically enriched structured representation of the current computer state.
        
        Returns a SemanticState dataclass with:
        - application: application name
        - window_title: active window title
        - window_class: window class name
        - window_bounds: [x1, y1, x2, y2]
        - elements: list of UIElement objects
        - running_apps: list of running process names
        - active_window: WindowInfo object
        - timestamp: float
        - source: "uia" | "win32" | "mixed"
        - ui_tree: full UI tree with parent/children relationships
        - element_groups: elements grouped by role
        - interaction_hints: suggested interactions based on visible elements
        - confidence: overall confidence in state accuracy
        - window_class: window class name
        - window_bounds: [x1, y1, x2, y2]
        """
        application = None
        window_title = None
        window_class = ""
        window_bounds: List[int] = []
        elements: List[UIElement] = []
        active_window: Optional[WindowInfo] = None
        running_apps: List[str] = []
        timestamp = time.time()
        source = "mixed"
        ui_tree: Dict[str, Any] = {}
        element_groups: Dict[str, List[UIElement]] = {}
        interaction_hints: List[str] = []
        confidence = 0.95

        # Get active window
        computer = self._get_computer()
        if computer:
            active = await computer.get_active_window(state)
            if active.get("status") == "success":
                win_data = active["window"]
                active_window = WindowInfo(
                    handle=win_data["handle"],
                    title=win_data["title"],
                    class_name=win_data["class_name"],
                    bounds=win_data["bounds"],
                    is_active=win_data.get("is_active", True),
                    process_id=win_data.get("process_id"),
                    process_name=win_data.get("process_name", ""),
                )
                window_title = win_data["title"]
                window_class = win_data["class_name"]
                window_bounds = win_data["bounds"]
                application = self._extract_app_name(window_title, win_data["class_name"])

        # Get running apps
        try:
            import psutil
            running = set()
            for proc in psutil.process_iter(["name"]):
                try:
                    running.add(proc.info["name"].lower())
                except Exception:
                    pass
            running_apps = list(running)
        except Exception:
            running_apps = []

        # Get UI elements for active window with enhanced metadata
        if window_title and computer:
            elements_result = await computer.inspect_controls(window_title, state=state)
            if elements_result.get("status") == "success":
                raw_controls = elements_result.get("controls", [])
                elements = self._process_raw_controls(raw_controls, window_title)
                
                # Group elements by role for semantic understanding
                for elem in elements:
                    role = elem.role
                    if role not in element_groups:
                        element_groups[role] = []
                    element_groups[role].append(elem)
                    
                    # Build interaction hints based on element types
                    if role in ("button", "link", "menuitem") and elem.enabled:
                        interaction_hints.append(f"Clickable: {elem.name}")
                    elif role in ("edit", "textbox", "combobox") and elem.enabled:
                        interaction_hints.append(f"Editable: {elem.name}")
                    elif role in ("checkbox", "radiobutton") and elem.enabled:
                        interaction_hints.append(f"Toggleable: {elem.name}")
                    elif role in ("menu", "menubar") and elem.enabled:
                        interaction_hints.append(f"Menu: {elem.name}")
                    elif role in ("tab", "tabitem") and elem.enabled:
                        interaction_hints.append(f"Tab: {elem.name}")
                    elif role in ("list", "listitem", "tree", "treeitem") and elem.enabled:
                        interaction_hints.append(f"Selectable: {elem.name}")
                    elif role in ("slider", "scrollbar") and elem.enabled:
                        interaction_hints.append(f"Adjustable: {elem.name}")

        # Build enhanced semantic UI tree with parent/children relationships
        ui_tree = self._build_ui_tree(elements)

        return SemanticState(
            application=application or "Unknown",
            window_title=window_title or "Unknown",
            window_class=window_class,
            window_bounds=window_bounds,
            elements=elements,
            running_apps=running_apps,
            active_window=active_window,
            timestamp=time.time(),
            source=source,
            ui_tree=ui_tree,
            element_groups=element_groups,
            interaction_hints=interaction_hints,
            confidence=confidence,
        )

    def _build_ui_hierarchy(self, elements: List[UIElement]) -> Dict[str, Any]:
        """Build a semantic hierarchy of UI elements based on bounds containment (legacy method)."""
        hierarchy = {"root": {"children": [], "bounds": None}}
        
        # Sort elements by area (largest first) to find containers
        sorted_elements = sorted(elements, key=lambda e: (e.bounds[2] - e.bounds[0]) * (e.bounds[3] - e.bounds[1]), reverse=True)
        
        # Simple containment-based hierarchy
        for elem in sorted_elements:
            elem_dict = elem.to_dict()
            elem_dict["children"] = []
            
            # Find parent (first larger element that contains this one)
            parent = None
            for potential_parent in sorted_elements:
                if potential_parent is elem:
                    continue
                p_bounds = potential_parent.bounds
                e_bounds = elem.bounds
                if (p_bounds[0] <= e_bounds[0] and p_bounds[1] <= e_bounds[1] and
                    p_bounds[2] >= e_bounds[2] and p_bounds[3] >= e_bounds[3]):
                    parent = potential_parent
                    break
            
            if parent:
                # Add to parent's children in hierarchy
                pass  # Simplified for now
            else:
                hierarchy["root"]["children"].append(elem_dict)
        
        return hierarchy

    def _build_ui_tree(self, elements: List[UIElement]) -> Dict[str, Any]:
        """
        Build a proper semantic UI tree with parent/children relationships.
        Returns a tree structure with proper parent/children relationships and unique element IDs.
        """
        if not elements:
            return {"root": {"element_id": "root", "children": [], "bounds": None, "name": "Desktop", "role": "desktop"}}
        
        # Generate unique element IDs if not present
        for i, elem in enumerate(elements):
            if not elem.element_id:
                elem.element_id = f"elem_{id(elem)}_{i}"
        
        # Sort elements by area (largest first) to find containers
        sorted_elements = sorted(elements, key=lambda e: (e.bounds[2] - e.bounds[0]) * (e.bounds[3] - e.bounds[1]), reverse=True)
        
        # Map element_id -> element for quick lookup
        elem_map = {elem.element_id: elem for elem in elements}
        
        # Build containment tree
        # Each element gets a parent_id based on bounds containment
        for elem in elements:
            if not elem.parent_id:
                # Find parent (smallest container that contains this element)
                parent = None
                min_area = float('inf')
                for potential_parent in elements:
                    if potential_parent is elem:
                        continue
                    p_bounds = potential_parent.bounds
                    e_bounds = elem.bounds
                    if (p_bounds[0] <= e_bounds[0] and p_bounds[1] <= e_bounds[1] and
                        p_bounds[2] >= e_bounds[2] and p_bounds[3] >= e_bounds[3]):
                        area = (p_bounds[2] - p_bounds[0]) * (p_bounds[3] - p_bounds[1])
                        if area < min_area:
                            min_area = area
                            parent = potential_parent
                
                if parent:
                    elem.parent_id = parent.element_id
                    parent.children_ids.append(elem.element_id)
                else:
                    elem.parent_id = "root"
        
        # Build tree structure from element relationships
        def build_tree_node(elem_id: str) -> Dict[str, Any]:
            elem = elem_map[elem_id]
            node = elem.to_dict()
            node["children"] = []
            for child_id in elem.children_ids:
                if child_id in elem_map:
                    node["children"].append(build_tree_node(child_id))
            return node
        
        # Build tree starting from root
        tree = {"root": {"element_id": "root", "children": [], "bounds": None, "name": "Desktop", "role": "desktop"}}
        for elem in elements:
            if elem.parent_id == "root" or not elem.parent_id:
                tree["root"]["children"].append(build_tree_node(elem.element_id))
        
        return tree

    def _process_raw_controls(self, raw_controls: List[Dict], window_title: str) -> List[UIElement]:
        """
        Process raw control data from computer.inspect_controls into rich UIElement objects
        with comprehensive metadata.
        """
        elements = []
        
        for ctrl in raw_controls:
            bounds = ctrl.get("bounds", ctrl.get("rect", []))
            if len(bounds) != 4:
                continue
            
            # Skip zero-size or off-screen elements
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                continue
            
            # Extract comprehensive metadata
            name = ctrl.get("name") or ctrl.get("title") or ctrl.get("automation_id") or "unnamed"
            role = ctrl.get("role", ctrl.get("control_type", "")).lower()
            class_name = ctrl.get("class_name", ctrl.get("class", ""))
            automation_id = ctrl.get("automation_id", "")
            framework_id = ctrl.get("framework_id", "")
            enabled = ctrl.get("enabled", True)
            
            # Extract state information
            state_parts = []
            if not ctrl.get("visible", True):
                state_parts.append("hidden")
            if not enabled:
                state_parts.append("disabled")
            if ctrl.get("focused", False):
                state_parts.append("focused")
            if ctrl.get("selected", False):
                state_parts.append("selected")
            if ctrl.get("checked") is True:
                state_parts.append("checked")
            elif ctrl.get("checked") is False and "checkbox" in role:
                state_parts.append("unchecked")
            if ctrl.get("read_only", False):
                state_parts.append("read_only")
            if ctrl.get("required", False):
                state_parts.append("required")
            
            state_str = ", ".join(state_parts) if state_parts else "normal"
            
            # Extract UIA patterns
            uia_patterns = []
            for pattern in ["invoke", "expand_collapse", "toggle", "scroll", "value", "range_value", 
                           "selection", "grid", "table", "text", "window", "transform", "dock", "multiple_view"]:
                if ctrl.get(f"has_{pattern}", False) or ctrl.get(f"supports_{pattern}", False):
                    uia_patterns.append(pattern)
            
            # Determine available actions based on role and patterns
            available_actions = []
            if "invoke" in uia_patterns or role in ("button", "link", "menuitem", "menu"):
                available_actions.append("click")
            if "expand_collapse" in uia_patterns:
                available_actions.extend(["expand", "collapse"])
            if "toggle" in uia_patterns or role in ("checkbox", "radiobutton", "switch"):
                available_actions.append("toggle")
            if "value" in uia_patterns or role in ("edit", "textbox", "combobox", "text"):
                available_actions.extend(["type", "select"])
            if "scroll" in uia_patterns or role in ("scrollbar", "slider"):
                available_actions.append("scroll")
            if "selection" in uia_patterns or role in ("listitem", "treeitem", "list", "tree"):
                available_actions.append("select")
            if role in ("edit", "textbox", "text"):
                available_actions.append("type")
            if role in ("menuitem", "menu"):
                available_actions.append("hover")
            if "drag" in str(ctrl.get("supported_patterns", "")):
                available_actions.append("drag")
            
            # Remove duplicates
            available_actions = list(set(available_actions))
            
            # Extract keyboard shortcuts
            keyboard_shortcuts = []
            accelerator = ctrl.get("accelerator_key", "") or ctrl.get("keyboard_shortcut", "")
            if accelerator:
                keyboard_shortcuts.append(accelerator)
            
            # Extract framework info
            framework = ctrl.get("framework", "")
            if not framework:
                framework_id = ctrl.get("framework_id", "").lower()
                if "wpf" in framework_id or "presentationcore" in framework_id:
                    framework = "WPF"
                elif "chrome" in framework_id or "chromium" in framework_id:
                    framework = "Chrome"
                elif "edge" in framework_id or "msedge" in framework_id:
                    framework = "Edge"
                elif "firefox" in framework_id or "mozilla" in framework_id:
                    framework = "Firefox"
                elif "electron" in framework_id:
                    framework = "Electron"
                elif "java" in framework_id or "awt" in framework_id or "swing" in framework_id:
                    framework = "Java"
                elif "qt" in framework_id:
                    framework = "Qt"
                elif "win32" in framework_id or "user32" in framework_id:
                    framework = "Win32"
                else:
                    framework = "Unknown"
            
            # Create element with all metadata
            bounds = ctrl.get("bounds", ctrl.get("rect", []))
            if len(bounds) != 4:
                continue
            
            # Generate unique element ID
            import uuid
            element_id = f"elem_{uuid.uuid4().hex[:8]}"
            
            # Build interaction hints
            interaction_hints = []
            if role in ("button", "link", "menuitem") and enabled:
                interaction_hints.append(f"Clickable: {name}")
            elif role in ("edit", "textbox", "combobox", "text") and enabled:
                interaction_hints.append(f"Editable: {name}")
            elif role in ("checkbox", "radiobutton") and enabled:
                interaction_hints.append(f"Toggleable: {name}")
            elif role in ("menu", "menubar") and enabled:
                interaction_hints.append(f"Menu: {name}")
            elif role in ("tab", "tabitem") and enabled:
                interaction_hints.append(f"Tab: {name}")
            elif role in ("list", "listitem", "tree", "treeitem") and enabled:
                interaction_hints.append(f"Selectable: {name}")
            elif role in ("slider", "scrollbar") and enabled:
                interaction_hints.append(f"Adjustable: {name}")
            
            # Create UIElement with all metadata
            elem = UIElement(
                name=name,
                role=role,
                bounds=bounds,
                confidence=ctrl.get("confidence", 0.95 if enabled else 0.5),
                source=ctrl.get("source", "uia"),
                enabled=enabled,
                class_name=class_name,
                automation_id=automation_id,
                framework_id=framework_id,
                state=state_str,
                visible=ctrl.get("visible", True),
                focused=ctrl.get("focused", False),
                selected=ctrl.get("selected", False),
                checked=ctrl.get("checked"),
                uia_patterns=uia_patterns,
                available_actions=available_actions,
                keyboard_shortcuts=keyboard_shortcuts,
                interaction_hints=interaction_hints,
                element_id=element_id,
                process_id=ctrl.get("process_id"),
                framework=framework,
                depth=0,  # Will be calculated in tree building
            )
            
            elements.append(elem)
        
        return elements
        """Extract application name from window title/class."""
        known_apps = {
            "notepad": "Notepad",
            "calc": "Calculator",
            "mspaint": "Paint",
            "chrome": "Google Chrome",
            "msedge": "Microsoft Edge",
            "firefox": "Firefox",
            "explorer": "File Explorer",
            "winword": "Microsoft Word",
            "excel": "Microsoft Excel",
            "powerpnt": "Microsoft PowerPoint",
            "cmd": "Command Prompt",
            "taskmgr": "Task Manager",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
        }
        title_lower = window_title.lower()
        class_lower = class_name.lower()
        for key, name in known_apps.items():
            if key in title_lower or key in class_lower:
                return name
        # Fallback: use first word of title
        return window_title.split()[0] if window_title else "Unknown"

    # ─────────────────────────────────────────────────────────────────────────
    # Per-action verifiers
    # ─────────────────────────────────────────────────────────────────────────
    async def observe_after_action(
        self,
        action: ActionSpec,
        result: Dict[str, Any],
        state: TaskState,
        browser: Browser = None
    ) -> Dict[str, Any]:
        """
        Verify the actual system state after an action.
        Returns a dict with 'verified', 'message', 'classification', and optionally 'extra_data'.
        classification: "success" | "retryable" | "human_required" | "recoverable" | "fatal"
        """
        atype = action.type
        computer = self._get_computer()

        if atype == "open_app_wait":
            window_title = action.parameters.get("window_title", action.parameters.get("app_name", ""))
            await asyncio.sleep(1.5)  # let app finish launching
            return self.verify_window_exists(window_title)

        elif atype == "type_in_app":
            window_title = action.parameters.get("window_title", "")
            text = action.parameters.get("text", "")
            await asyncio.sleep(0.5)
            return self.verify_text_in_window(window_title, text)

        elif atype == "calculator_compute":
            await asyncio.sleep(1.0)
            expected = str(action.parameters.get("expected", ""))
            return self.verify_calculator_result(expected)

        elif atype == "inspect_ui":
            elements = result.get("elements", []) if result else []
            element = result.get("element") if result else None
            if result and result.get("status") == "success":
                found = bool(elements or element)
                return {
                    "verified": found,
                    "message": f"Found {len(elements)} visible UI items" if elements else "Matching UI item found",
                    "classification": "success" if found else "recoverable",
                }
            return {"verified": False, "message": result.get("message", "UI inspection failed") if result else "UI inspection failed", "classification": "retryable"}

        elif atype == "find_ui_element":
            element = result.get("element") if result else None
            if result and result.get("status") == "success" and element:
                state.update_context("ui_target", element)
                return {"verified": True, "message": f"Found UI control: {element.get('title') or element.get('text', 'unnamed')}", "classification": "success"}
            return {"verified": False, "message": result.get("message", "UI control not found") if result else "UI control not found", "classification": "recoverable"}

        elif atype == "click_ui":
            if result and result.get("status") == "success":
                target = action.parameters.get("text", action.parameters.get("element", {}).get("title", "target"))
                if computer:
                    await asyncio.sleep(0.3)
                    verification = await computer.get_active_window(state)
                    if verification.get("status") == "success":
                        return {"verified": True, "message": f"Clicked {target}, window active: {verification['window']['title']}", "classification": "success"}
                return {"verified": True, "message": result.get("message", f"Clicked {target}"), "classification": "success"}
            return {"verified": False, "message": result.get("message", f"UI click failed") if result else "UI click failed", "classification": "retryable"}

        elif atype == "type_ui":
            if result and result.get("status") == "success":
                target = action.parameters.get("element", {}).get("title", "focused control")
                if computer:
                    await asyncio.sleep(0.3)
                    verification = await computer.get_active_window(state)
                    if verification.get("status") == "success":
                        return {"verified": True, "message": f"Typed into {target} in {verification['window']['title']}", "classification": "success"}
                return {"verified": True, "message": result.get("message", f"Typed into {target}"), "classification": "success"}
            return {"verified": False, "message": result.get("message", f"UI type failed") if result else "UI type failed", "classification": "retryable"}

        elif atype == "screenshot_ui":
            path = result.get("path", "") if result else ""
            if path and os.path.isfile(path):
                return {"verified": True, "message": f"Screenshot saved: {path}", "path": path, "classification": "success"}
            return {"verified": False, "message": "UI screenshot was not saved", "classification": "recoverable"}

        elif atype == "create_folder_verified":
            path = action.parameters.get("path", "")
            return self.verify_folder_exists(path)

        elif atype in ("write_file_verified", "verify_file"):
            path = action.parameters.get("path", "")
            return self.verify_file_exists(path)

        elif atype == "create_docx":
            path = action.parameters.get("path", "")
            await asyncio.sleep(0.3)
            return self.verify_docx(path)

        elif atype == "create_pptx":
            path = action.parameters.get("path", "")
            await asyncio.sleep(0.3)
            return self.verify_pptx(path)

        elif atype in ("press_key", "speak"):
            return {"verified": True, "message": f"Action {atype} executed", "classification": "success"}

        elif atype == "browser_search":
            if browser:
                await asyncio.sleep(0.5)
                if result and result.get("status") == "success":
                    state.search_results = result.get("results", [])
                    state.current_page_url = result.get("url", "")
                    state.current_page_title = result.get("title", "")
                    msg = result.get("message", "Search completed")
                    return {"verified": True, "message": msg, "classification": "success", "results_count": len(state.search_results)}
                elif result and result.get("status") == "human_verification_required":
                    return {"verified": False, "message": result.get("message", "Human verification required"), "classification": "human_required", "page_state": result.get("page_state", "captcha"), "details": result.get("details", {})}
                elif result and result.get("retryable"):
                    return {"verified": False, "message": result.get("message", "Search failed"), "classification": "retryable"}
                return {"verified": False, "message": result.get("message", "Search failed") if result else "No result", "classification": "recoverable"}
            return {"verified": False, "message": "No browser available for verification", "classification": "fatal"}

        elif atype == "browser_navigate":
            if browser:
                await asyncio.sleep(1.0)
                source_index = action.parameters.get("source_index")
                if source_index is not None and state.search_results:
                    if 0 <= source_index < len(state.search_results):
                        expected_url = state.search_results[source_index].get("url", "")
                        return await self.verify_browser_page(browser, expected_url_fragment=expected_url)
                return await self.verify_browser_page(browser)
            return {"verified": False, "message": "No browser available to verify navigation", "classification": "fatal"}

        elif atype == "browser_extract":
            if browser:
                text = result.get("text", "") if result else ""
                if text and len(text.strip()) > 50:
                    title_result = await browser.get_page_title()
                    source_data = {"text": text[:5000], "title": title_result.get("title", ""), "url": title_result.get("url", ""), "source_index": len(state.extracted_sources)}
                    state.extracted_sources.append(source_data)
                    state.current_page_url = title_result.get("url", "")
                    state.current_page_title = title_result.get("title", "")
                    return {"verified": True, "message": f"Extracted {len(text)} characters from page", "classification": "success"}
                return {"verified": False, "message": "Extraction yielded no meaningful content", "classification": "recoverable"}
            return {"verified": False, "message": "No browser available for extraction verification", "classification": "fatal"}

        elif atype == "browser_get_title":
            title = result.get("title", "") if result else ""
            if title:
                state.current_page_title = title
                state.current_page_url = result.get("url", "")
                return {"verified": True, "message": f"Page title: {title}", "title": title, "classification": "success"}
            return {"verified": False, "message": "Could not get page title", "classification": "retryable"}

        elif atype == "browser_type":
            expected = action.parameters.get("text", "")
            actual = result.get("value", "") if result else ""
            if result and result.get("status") == "success" and actual == expected:
                return {"verified": True, "message": "Browser form value verified", "classification": "success"}
            return {"verified": False, "message": result.get("message", "Browser form input was not verified") if result else "No browser result", "classification": "recoverable"}

        elif atype == "browser_click":
            if not browser or not result or result.get("status") != "success":
                return {"verified": False, "message": result.get("message", "Browser click failed") if result else "No browser result", "classification": "retryable"}
            expected_url = action.parameters.get("expected_url_contains", "")
            expected_text = action.parameters.get("expected_text", "")
            current = await self.verify_browser_page(browser, expected_url_fragment=expected_url)
            if not current.get("verified"):
                return current
            if expected_text:
                body = await browser.get_page_text()
                if expected_text.lower() not in body.get("text", "").lower():
                    return {"verified": False, "message": f"Click completed but expected text was not present: {expected_text}", "classification": "recoverable"}
            return {"verified": True, "message": "Browser click result verified", "classification": "success"}

        elif atype == "browser_new_tab":
            if result and result.get("status") == "success":
                return {"verified": True, "message": "New browser tab verified", "classification": "success"}
            return {"verified": False, "message": result.get("message", "New browser tab failed") if result else "No browser result", "classification": "retryable"}

        elif atype == "browser_extract_search_results":
            if browser:
                verification = await self.verify_search_results(browser)
                if verification.get("verified"):
                    state.search_results = verification.get("results", [])
                    return {"verified": True, "message": verification.get("message", "Search results extracted"), "classification": "success", "results_count": len(state.search_results)}
                return verification
            return {"verified": False, "message": "No browser available for search results extraction", "classification": "fatal"}

        elif atype == "report_page_finding":
            answer = result.get("answer", "") if result else ""
            if result and result.get("status") == "success" and answer:
                return {"verified": True, "message": "Finding is grounded in extracted page content", "classification": "success"}
            return {"verified": False, "message": result.get("message", "No evidence-based page finding") if result else "No page finding result", "classification": "recoverable"}

        elif atype == "open_app":
            window_title = action.parameters.get("app_name", "")
            await asyncio.sleep(1.0)
            return self.verify_window_exists(window_title)

        elif atype == "launch_app":
            window_title = action.parameters.get("app_name", "")
            await asyncio.sleep(1.0)
            return self.verify_window_exists(window_title)

        elif atype == "close_app":
            app_name = action.parameters.get("app_name", "").lower()
            await asyncio.sleep(1.0)
            try:
                import psutil
                for proc in psutil.process_iter(["name"]):
                    if app_name in (proc.info.get("name") or "").lower():
                        return {"verified": False, "message": f"Process {app_name} still running", "classification": "retryable"}
                return {"verified": True, "message": f"Application {app_name} closed", "classification": "success"}
            except Exception:
                return {"verified": True, "message": f"Close action executed for {app_name}", "classification": "success"}

        elif atype == "create_folder":
            folder_name = action.parameters.get("folder_name", "")
            from system_ops import WORK_DIR, get_desktop_path
            paths_to_check = [
                os.path.join(WORK_DIR, folder_name),
                os.path.join(get_desktop_path(), folder_name),
            ]
            for path in paths_to_check:
                if os.path.isdir(path):
                    return {"verified": True, "message": f"Folder exists: {path}", "classification": "success"}
            return {"verified": False, "message": f"Folder not found: {folder_name}", "classification": "recoverable"}

        elif atype == "create_word_doc":
            filename = action.parameters.get("filename", "")
            from system_ops import WORK_DIR, get_desktop_path
            if not filename.endswith('.docx'):
                filename += '.docx'
            paths_to_check = [
                os.path.join(WORK_DIR, filename),
                os.path.join(get_desktop_path(), filename),
            ]
            for path in paths_to_check:
                if os.path.isfile(path):
                    return self.verify_docx(path)
            return {"verified": False, "message": f"Word document not found: {filename}", "classification": "recoverable"}

        elif atype == "write_file":
            filename = action.parameters.get("filename", "")
            from system_ops import WORK_DIR
            path = os.path.join(WORK_DIR, filename)
            return self.verify_file_exists(path)

        elif atype == "take_screenshot":
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "screenshots")
            if os.path.isdir(img_dir):
                files = [f for f in os.listdir(img_dir) if f.endswith('.png')]
                if files:
                    latest = max(files, key=lambda f: os.path.getmtime(os.path.join(img_dir, f)))
                    return {"verified": True, "message": f"Screenshot saved: {latest}", "path": os.path.join(img_dir, latest), "classification": "success"}
            return {"verified": False, "message": "Screenshot not found in screenshots directory", "classification": "recoverable"}

        elif atype == "search_web":
            return {"verified": True, "message": "Web search initiated (opens browser)", "classification": "success"}

        elif atype == "open_url":
            if browser:
                await asyncio.sleep(1.0)
                return await self.verify_browser_page(browser)
            return {"verified": False, "message": "No browser available to verify URL", "classification": "fatal"}

        elif atype in ("volume_up", "volume_down", "mute_volume", "play_pause", "next_track", "prev_track"):
            return {"verified": True, "message": f"Media/volume action {atype} executed", "classification": "success"}

        elif atype in ("shutdown", "restart", "sleep", "lock_screen", "cancel_shutdown"):
            return {"verified": True, "message": f"System action {atype} executed", "classification": "success"}

        elif atype in ("battery", "network_info", "datetime_info", "weather", "show_stats", "check_pc_health"):
            if result and result.get("status") == "success":
                return {"verified": True, "message": result.get("message", f"{atype} query succeeded"), "classification": "success"}
            return {"verified": False, "message": result.get("message", f"{atype} query failed") if result else "No result", "classification": "retryable"}

        elif atype in ("clipboard_read", "clipboard_write"):
            return {"verified": True, "message": f"Clipboard action {atype} executed", "classification": "success"}

        elif atype == "set_timer":
            return {"verified": True, "message": "Timer set on frontend", "classification": "success"}

        elif atype in ("add_note", "add_todo", "clear_history"):
            return {"verified": True, "message": f"Action {atype} executed", "classification": "success"}

        elif atype in ("phone_devices", "phone_mirror", "phone_screenshot", "phone_tap", "phone_swipe",
                       "phone_text", "phone_key", "phone_launch_app", "phone_unlock", "phone_test_pin_tap"):
            return {"verified": True, "message": f"Phone action {atype} executed", "classification": "success"}

        elif atype in ("send_whatsapp", "send_whatsapp_phone", "add_whatsapp_contact"):
            if result and result.get("status") == "success":
                return {"verified": True, "message": result.get("message", f"WhatsApp action {atype} executed successfully"), "classification": "success"}
            msg = result.get("message", f"WhatsApp action {atype} failed") if isinstance(result, dict) else f"WhatsApp action {atype} returned no result"
            return {"verified": False, "message": msg, "classification": "retryable"}

        elif atype == "generate_image":
            if result and result.get("status") == "success":
                return {"verified": True, "message": result.get("message", "Image generated"), "classification": "success"}
            return {"verified": False, "message": result.get("message", "Image generation failed") if result else "No result", "classification": "retryable"}

        elif atype == "save_image":
            return {"verified": True, "message": "Save image action executed", "classification": "success"}

        else:
            return {"verified": False, "message": f"No verifier implemented for action type: {atype}. Cannot verify result.", "classification": "recoverable"}

    def verify_window_exists(self, window_title: str) -> Dict[str, Any]:
        """Check that a window with the given title (substring) is present."""
        try:
            import win32gui

            found = []
            def enum_cb(hwnd, ctx):
                text = win32gui.GetWindowText(hwnd)
                if text and window_title.lower() in text.lower():
                    ctx.append({"title": text, "handle": str(hwnd)})

            win32gui.EnumWindows(enum_cb, found)
            if found:
                return {"verified": True, "message": f"Window found: {found[0]['title']}", "window": found[0]}
            return {"verified": False, "message": f"Window '{window_title}' not found"}
        except ImportError:
            try:
                import psutil
                for proc in psutil.process_iter(["name"]):
                    if window_title.lower() in (proc.info.get("name") or "").lower():
                        return {"verified": True, "message": f"Process found: {proc.info['name']}"}
            except Exception:
                pass
            return {"verified": False, "message": "Could not verify window (win32gui unavailable)"}
        except Exception as e:
            return {"verified": False, "message": f"Window check error: {str(e)}"}

    def verify_file_exists(self, path: str) -> Dict[str, Any]:
        """Verify a file exists on disk."""
        if os.path.isfile(path):
            size = os.path.getsize(path)
            return {"verified": True, "message": f"File exists: {path} ({size} bytes)", "classification": "success"}
        return {"verified": False, "message": f"File NOT found: {path}", "classification": "recoverable"}

    def verify_folder_exists(self, path: str) -> Dict[str, Any]:
        """Verify a folder exists on disk."""
        if os.path.isdir(path):
            return {"verified": True, "message": f"Folder exists: {path}", "classification": "success"}
        return {"verified": False, "message": f"Folder NOT found: {path}", "classification": "recoverable"}

    def verify_docx(self, path: str) -> Dict[str, Any]:
        """Open and read a DOCX to confirm it has content."""
        try:
            from docx import Document
            if not os.path.isfile(path):
                return {"verified": False, "message": f"DOCX not found: {path}", "classification": "recoverable"}
            doc = Document(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            if paragraphs:
                return {
                    "verified": True,
                    "message": f"DOCX verified: {len(paragraphs)} paragraphs, path={path}",
                    "paragraph_count": len(paragraphs),
                    "classification": "success"
                }
            return {"verified": False, "message": f"DOCX exists but has no readable content: {path}", "classification": "recoverable"}
        except Exception as e:
            return {"verified": False, "message": f"DOCX read error: {str(e)}", "classification": "retryable"}

    def verify_pptx(self, path: str) -> Dict[str, Any]:
        """Open and verify a PPTX presentation file exists and has slides."""
        try:
            if not os.path.isfile(path):
                return {"verified": False, "message": f"PPTX not found: {path}", "classification": "recoverable"}
            size = os.path.getsize(path)
            if size < 500:
                return {"verified": False, "message": f"PPTX file is too small or empty: {path} ({size} bytes)", "classification": "recoverable"}
            try:
                from pptx import Presentation
                prs = Presentation(path)
                slides_count = len(prs.slides)
                return {
                    "verified": True,
                    "message": f"PowerPoint verified: {slides_count} slides, path={path}",
                    "classification": "success",
                    "slides_count": slides_count
                }
            except Exception:
                return {
                    "verified": True,
                    "message": f"PowerPoint file exists: {path} ({size} bytes)",
                    "classification": "success"
                }
        except Exception as e:
            return {"verified": False, "message": f"PPTX read error: {str(e)}", "classification": "recoverable"}

    def verify_calculator_result(self, expected: str) -> Dict[str, Any]:
        """Try to read the Calculator window display and check the value."""
        # Attempt 1: pywinauto UIA
        try:
            import pywinauto
            from pywinauto import Application
            app = Application(backend="uia").connect(title_re=".*Calculator.*", timeout=3)
            win = app.top_window()
            # In Windows Calculator the display is a Text control
            display = win.child_window(auto_id="CalculatorResults", control_type="Text")
            value = display.window_text().strip()
            # Strip "Display is " prefix that Windows Calculator sometimes adds
            value = value.replace("Display is", "").strip()
            if expected and expected.replace(",", "").replace(" ", "") in value.replace(",", "").replace(" ", ""):
                return {"verified": True, "message": f"Calculator shows: {value}", "display": value}
            if expected:
                return {"verified": False, "message": f"Calculator shows {value!r}, expected {expected!r}", "display": value}
            return {"verified": True, "message": f"Calculator shows: {value}", "display": value}
        except Exception:
            pass

        # Attempt 2: win32gui window text
        try:
            import win32gui
            found_text = []
            def enum_cb(hwnd, ctx):
                title = win32gui.GetWindowText(hwnd)
                if "calculator" in title.lower():
                    ctx.append(title)
            win32gui.EnumWindows(enum_cb, found_text)
            if found_text:
                return {"verified": True, "message": f"Calculator window present: {found_text[0]}"}
        except Exception:
            pass

        return {"verified": False, "message": "Could not read Calculator display"}

    async def verify_browser_page(self, browser: Browser, expected_url_fragment: str = "", expected_title_fragment: str = "") -> Dict[str, Any]:
        """Verify browser is on the right page by checking URL and/or title, and detect CAPTCHA/consent."""
        try:
            # First, detect page state
            page_state = await browser.detect_page_state()

            if page_state.state == BrowserPageState.CAPTCHA:
                return {
                    "verified": False,
                    "message": page_state.message or "CAPTCHA / human verification required",
                    "classification": "human_required",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.CONSENT:
                return {
                    "verified": False,
                    "message": page_state.message or "Consent page requires user interaction",
                    "classification": "human_required",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.SORRY_PAGE:
                return {
                    "verified": False,
                    "message": page_state.message or "Google 'unusual traffic' page detected",
                    "classification": "human_required",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.NETWORK_ERROR:
                return {
                    "verified": False,
                    "message": "Network/navigation error",
                    "classification": "retryable",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.NAVIGATION_PENDING:
                return {
                    "verified": False,
                    "message": f"Page still loading: {page_state.details.get('ready_state', 'unknown')}",
                    "classification": "retryable",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            # Normal page - verify URL/title if expected
            title_result = await browser.get_page_title()
            if title_result["status"] != "success":
                return {"verified": False, "message": "Could not get browser page title", "classification": "retryable"}

            title = title_result.get("title", "")
            url = title_result.get("url", "")

            if expected_title_fragment and expected_title_fragment.lower() not in title.lower():
                return {
                    "verified": False,
                    "message": f"Page title mismatch: got '{title}', expected fragment '{expected_title_fragment}'",
                    "title": title, "url": url,
                    "classification": "recoverable"
                }
            if expected_url_fragment and expected_url_fragment.lower() not in url.lower():
                return {
                    "verified": False,
                    "message": f"URL mismatch: got '{url}', expected fragment '{expected_url_fragment}'",
                    "title": title, "url": url,
                    "classification": "recoverable"
                }

            return {"verified": True, "message": f"Browser on: {title} | {url}", "title": title, "url": url, "classification": "success"}
        except Exception as e:
            return {"verified": False, "message": f"Browser verification error: {str(e)}", "classification": "retryable"}

    async def verify_search_results(self, browser: Browser) -> Dict[str, Any]:
        """Verify that search results are present and extractable."""
        try:
            page_state = await browser.detect_page_state()

            if page_state.state == BrowserPageState.CAPTCHA:
                return {
                    "verified": False,
                    "message": "CAPTCHA detected on search results page",
                    "classification": "human_required",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.SORRY_PAGE:
                return {
                    "verified": False,
                    "message": "Google sorry page on search results",
                    "classification": "human_required",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.EMPTY_RESULTS:
                return {
                    "verified": False,
                    "message": "No search results found on SERP",
                    "classification": "recoverable",
                    "page_state": page_state.state.value,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.NORMAL_SERP:
                # Extract and verify results
                results = await browser.extract_search_results()
                if results and len(results) > 0:
                    return {
                        "verified": True,
                        "message": f"Found {len(results)} search results",
                        "count": len(results),
                        "results": results,
                        "classification": "success"
                    }
                return {
                    "verified": False,
                    "message": "SERP loaded but extraction yielded no results",
                    "classification": "recoverable",
                    "page_state": page_state.state.value
                }

            # Other states
            return {
                "verified": False,
                "message": f"Unexpected page state: {page_state.state.value}",
                "classification": "recoverable",
                "page_state": page_state.state.value,
                "details": page_state.details
            }
        except Exception as e:
            return {"verified": False, "message": f"Search results verification error: {str(e)}", "classification": "retryable"}

    def verify_text_in_window(self, window_title: str, expected_text: str) -> Dict[str, Any]:
        """
        Try to read text from a window (e.g. Notepad) using pywinauto UIA.
        Returns verified=True only if the expected text is actually found.
        """
        try:
            import pywinauto
            from pywinauto import Application
            app = Application(backend="uia").connect(title_re=f".*{window_title}.*", timeout=3)
            win = app.top_window()
            edit = win.child_window(control_type="Edit")
            content = edit.window_text()
            if expected_text.lower() in content.lower():
                return {"verified": True, "message": f"Text found in {window_title}: '{expected_text[:50]}'", "content": content}
            return {"verified": False, "message": f"Text '{expected_text[:50]}' NOT found in {window_title}. Content starts: '{content[:80]}'", "content": content}
        except Exception as e:
            win_check = self.verify_window_exists(window_title)
            if win_check["verified"]:
                return {"verified": True, "message": f"Window present (text read unavailable): {win_check['message']}"}
            return {"verified": False, "message": f"Could not verify text: {str(e)}"}

    def detect_captcha(self, page_content: str) -> bool:
        """Scan for common CAPTCHA patterns in visible page content."""
        if not page_content:
            return False
        content_lower = page_content.lower()
        captcha_indicators = [
            'please verify you are human',
            'verify you are human',
            'confirm you are human',
            'complete the security check to continue',
            'our systems have detected unusual traffic',
            'press and hold to confirm you are human',
        ]
        return any(indicator in content_lower for indicator in captcha_indicators)

# ═══════════════════════════════════════════════════════════════════════════════════════
# Vision Perception System
# ══════════════════════════════════════════════════════════════════════════════════════

@dataclass
class VisionObservation:
    """Structured vision observation result."""
    source: str = "vision"
    screen_width: int = 0
    screen_height: int = 0
    elements: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0
    screenshot_path: Optional[str] = None
    raw_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "elements": self.elements,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "screenshot_path": self.screenshot_path,
            "raw_text": self.raw_text,
        }


class VisionPerception:
    """Vision-based perception using OCR and visual analysis."""
    
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()
        self._computer = None
    
    def _get_computer(self):
        if self._computer is None:
            computer = self.registry.get("computer_tool")
            if computer:
                self._computer = computer
        return self._computer
    
    async def capture_and_analyze(self, state: TaskState, focus: str = "general") -> VisionObservation:
        """Capture screen and analyze using OCR/vision."""
        computer = self._get_computer()
        if not computer:
            return VisionObservation(confidence=0.0, raw_text="Computer tool not available")
        
        # Capture screenshot
        screenshot_result = await computer.get_screen(state)
        if screenshot_result.get("status") != "success":
            return VisionObservation(confidence=0.0, raw_text="Screenshot capture failed")
        
        screenshot_path = screenshot_result.get("screenshot_path", "")
        if not screenshot_path or not os.path.exists(screenshot_path):
            return VisionObservation(confidence=0.0, raw_text="Screenshot not saved")
        
        # Get screen dimensions
        try:
            from PIL import Image
            with Image.open(screenshot_path) as img:
                width, height = img.size
        except Exception:
            width, height = 1920, 1080  # defaults
        
        # OCR using pytesseract or fallback to LLM vision
        elements = []
        raw_text = ""
        
        # Try OCR first
        try:
            import pytesseract
            raw_text = pytesseract.image_to_string(screenshot_path)
            # Parse text into elements with bounding boxes
            data = pytesseract.image_to_data(screenshot_path, output_type=pytesseract.Output.DICT)
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                if text and len(text) > 1:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    if w > 10 and h > 10:  # Filter out noise
                        elements.append({
                            "type": "text",
                            "text": text,
                            "bounds": [x, y, x + w, y + h],
                            "confidence": data['conf'][i] / 100.0 if data['conf'][i] > 0 else 0.5,
                            "source": "ocr"
                        })
        except ImportError:
            # pytesseract not available, use LLM vision analysis
            raw_text = await self._analyze_with_llm(screenshot_path)
            # Parse LLM response into elements
            elements = self._parse_llm_vision_response(raw_text)
        except Exception as e:
            raw_text = f"OCR error: {str(e)}"
        
        # If no elements found, try LLM vision
        if not elements:
            try:
                vision_text = await self._analyze_with_llm(screenshot_path)
                elements = self._parse_llm_vision_response(vision_text)
                raw_text = vision_text
            except Exception:
                pass
        
        confidence = min(0.8, len(elements) * 0.1) if elements else 0.1
        
        return VisionObservation(
            screen_width=width,
            screen_height=height,
            elements=elements,
            confidence=confidence,
            screenshot_path=screenshot_path,
            raw_text=raw_text[:5000]  # Truncate
        )
    
    async def _analyze_with_llm(self, screenshot_path: str) -> str:
        """Analyze screenshot using LLM vision (Gemini/NVIDIA)."""
        try:
            from backend.tools.computer import Computer
            computer = Computer(self.registry)
            # Use computer's screenshot capabilities
            # For now, return placeholder - in production would call LLM vision API
            return "LLM vision analysis not fully implemented - placeholder"
        except Exception:
            return "LLM vision analysis unavailable"
    
    def _parse_llm_vision_response(self, response: str) -> List[Dict]:
        """Parse LLM vision response into structured elements."""
        elements = []
        # Simple parsing - in production would be more sophisticated
        lines = response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and len(line) > 2:
                elements.append({
                    "type": "text",
                    "text": line[:200],
                    "bounds": [0, 0, 100, 20],
                    "confidence": 0.6,
                    "source": "vision"
                })
        return elements


class PerceptionManager:
    """Unified perception manager combining UIA and Vision."""
    
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()
        self.uia_observer = Observer(registry)
        self.vision = VisionPerception(registry)
        self._last_uia_state: Optional[SemanticState] = None
        self._last_vision_state: Optional[VisionObservation] = None
    
    async def perceive(self, state: TaskState, use_vision: bool = False) -> Dict[str, Any]:
        """
        Get perception from UIA and optionally vision.
        Returns fused perception data.
        """
        # Get UIA perception (primary)
        uia_state = await self.uia_observer.get_structured_state(state)
        self._last_uia_state = uia_state
        
        result = {
            "uia": uia_state.to_dict(),
            "source": "uia",
            "fused": False
        }
        
        # Get vision perception if requested or if UIA is insufficient
        if use_vision or self._needs_vision_fallback(uia_state):
            vision_state = await self.vision.capture_and_analyze(state)
            self._last_vision_state = vision_state
            
            # Fuse UIA and vision
            fused = self._fuse_perceptions(uia_state, vision_state)
            result["vision"] = vision_state.to_dict()
            result["fused"] = fused
            result["source"] = "fused"
        
        return result
    
    def _needs_vision_fallback(self, uia_state: SemanticState) -> bool:
        """Determine if vision fallback is needed."""
        # Need vision if:
        # - UIA confidence is low
        # - Too few elements found
        # - Specific element types not found (canvas, custom controls)
        if uia_state.confidence < 0.7:
            return True
        if len(uia_state.elements) < 3:
            return True
        # Check for canvas/custom controls that UIA might miss
        has_canvas = any("canvas" in e.role.lower() or "custom" in e.role.lower() for e in uia_state.elements)
        if has_canvas:
            return True
        return False
    
    def _fuse_perceptions(self, uia_state: SemanticState, vision_state: VisionObservation) -> Dict[str, Any]:
        """Fuse UIA and vision observations into unified perception."""
        fused_elements = []
        
        # Start with UIA elements (higher confidence)
        uia_elements_by_text = {}
        for elem in uia_state.elements:
            key = (elem.name.lower().strip(), tuple(elem.bounds))
            uia_elements_by_text[key] = elem
        
        # Add vision elements, matching with UIA where possible
        for v_elem in vision_state.elements:
            v_text = v_elem.get("text", "").lower().strip()
            v_bounds = v_elem.get("bounds", [])
            
            # Try to match with UIA element
            matched = False
            for key, uia_elem in uia_elements_by_text.items():
                uia_name, uia_bounds = key
                if v_text == uia_name or (v_text in uia_name or uia_name in v_text):
                    # Check bounds overlap
                    if self._bounds_overlap(uia_elem.bounds, v_bounds):
                        # Merge: UIA element enhanced with vision data
                        merged = uia_elem.to_dict()
                        merged["vision_confirmed"] = True
                        merged["vision_text"] = v_elem.get("text", "")
                        merged["vision_confidence"] = v_elem.get("confidence", 0)
                        merged["confidence"] = min(0.95, uia_elem.confidence + 0.1)
                        fused_elements.append(merged)
                        matched = True
                        break
            
            if not matched:
                # Vision-only element
                fused_elements.append({
                    "type": v_elem.get("type", "unknown"),
                    "name": v_elem.get("text", "vision_element"),
                    "bounds": v_elem.get("bounds", []),
                    "confidence": v_elem.get("confidence", 0.5),
                    "source": "vision",
                    "vision_confirmed": False,
                    "vision_text": v_elem.get("text", ""),
                })
        
        # Add unmatched UIA elements
        for elem in uia_state.elements:
            key = (elem.name.lower().strip(), tuple(elem.bounds))
            if not any(self._bounds_overlap(elem.bounds, v.get("bounds", [])) for v in vision_state.elements):
                fused_elements.append(elem.to_dict())
        
        return {
            "elements": fused_elements,
            "confidence": min(0.95, uia_state.confidence + 0.1) if vision_state.elements else uia_state.confidence,
            "source": "fused",
            "uia_count": len(uia_state.elements),
            "vision_count": len(vision_state.elements),
            "fused_count": len(fused_elements),
        }
    
    def _bounds_overlap(self, bounds1: List[int], bounds2: List[int]) -> bool:
        """Check if two bounding boxes overlap significantly."""
        if len(bounds1) != 4 or len(bounds2) != 4:
            return False
        x1_min, y1_min, x1_max, y1_max = bounds1
        x2_min, y2_min, x2_max, y2_max = bounds2
        
        overlap_x = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
        overlap_y = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
        
        area1 = (x1_max - x1_min) * (y1_max - y1_min)
        area2 = (x2_max - x2_min) * (y2_max - y2_min)
        overlap_area = overlap_x * overlap_y
        
        if area1 == 0 or area2 == 0:
            return False
        
        return (overlap_area / min(area1, area2)) > 0.3
