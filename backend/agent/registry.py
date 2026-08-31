from typing import Dict, Any, List
from backend.agent.state import TaskState


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Any] = {}

    def register(self, name: str, tool_func: Any) -> None:
        self._tools[name] = tool_func

    def get(self, name: str) -> Any:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools