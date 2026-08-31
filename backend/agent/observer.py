import asyncio
from typing import Any, Dict, Optional, List

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


class Observer:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def observe(self, state: TaskState, focus: str = "general") -> Dict[str, Any]:
        """Observe the current system state and update the task state."""
        observations = {}

        # Get system stats
        from system_ops import get_system_stats
        stats = get_system_stats()
        if "error" not in stats:
            observations["system_stats"] = stats
            state.observations.append(f"System: CPU {stats.get('cpu', '?')}%, Memory {stats.get('memory', '?')}%")

        # Check active applications/windows
        try:
            import psutil
            running_apps = []
            for proc in psutil.process_iter(['name']):
                try:
                    running_apps.append(proc.info['name'])
                except:
                    pass
            observations["running_apps"] = list(set(running_apps))[:20]
        except Exception:
            observations["running_apps"] = []

        # Browser state if applicable
        if focus == "browser" or "browser" in state.task.lower():
            observations["browser"] = await self._check_browser()

        # Phone state if applicable
        if focus == "phone" or "phone" in state.task.lower():
            observations["phone"] = await self._check_phone()

        state.observations.append(f"Observation: {focus} state captured")
        return observations

    async def _check_browser(self) -> Optional[Dict[str, Any]]:
        """Check if a browser is open and return its state."""
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                name = proc.info['name'].lower() if proc.info['name'] else ''
                if 'chrome' in name or 'edge' in name or 'browser' in name:
                    return {"browser": proc.info['name'], "running": True}
        except Exception:
            pass
        return {"browser": None, "running": False}

    async def _check_phone(self) -> Optional[Dict[str, Any]]:
        """Check phone connection state."""
        try:
            from phone_control import list_devices
            devices = list_devices()
            if devices.get("status") == "success":
                return {"phone": devices.get("message", "Device listed"), "connected": True}
        except Exception:
            pass
        return {"phone": "Not connected", "connected": False}