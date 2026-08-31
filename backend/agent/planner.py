import json
import re
from typing import List, Optional

from backend.agent.state import TaskState


class Planner:
    def plan_task(self, task: str, state: TaskState) -> List[str]:
        """Convert a natural language task into a list of steps.
        Uses Gemini API when available, otherwise falls back to rule-based parsing."""
        state.task = task
        state.completed_steps = []
        state.current_step = 0
        state.retry_count = 0

        # Try to extract structured steps from the task
        steps = self._extract_steps(task)
        if steps:
            return steps

        # Fallback: generate a basic plan based on task keywords
        return self._fallback_plan(task)

    def _extract_steps(self, task: str) -> Optional[List[str]]:
        """Try to extract ordered steps from the task using patterns."""
        task_lower = task.lower().strip()

        # Pattern: "Open Chrome, search for X, then Y"
        if "," in task_lower:
            parts = [p.strip() for p in task_lower.split(",") if p.strip()]
            if len(parts) >= 2:
                return parts

        # Pattern: "Open Chrome and search for Science Day"
        if "open" in task_lower and "search" in task_lower:
            return ["Open the requested application", "Search for the specified query"]

        # Pattern: Single clear action
        if "open" in task_lower:
            return ["Open the requested application"]
        if "search" in task_lower or "google" in task_lower:
            return ["Search the web for the specified query"]
        if "create" in task_lower or "make" in task_lower:
            return ["Create the requested document/file"]

        return None

    def _fallback_plan(self, task: str) -> List[str]:
        """Generate a basic plan based on task keywords."""
        task_lower = task.lower().strip()
        steps = []

        if "open" in task_lower:
            steps.append("Open the requested application")
        if "search" in task_lower or "google" in task_lower:
            steps.append("Search the web for the specified query")
        if "create" in task_lower or "make" in task_lower:
            steps.append("Create the requested document/file")
        if "close" in task_lower:
            steps.append("Close the application")
        if "exit" in task_lower:
            steps.append("Exit the application")

        if not steps:
            steps = ["Process the user's request"]

        return steps