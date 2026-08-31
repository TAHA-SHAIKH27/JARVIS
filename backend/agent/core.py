import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry
from backend.agent.planner import Planner
from backend.agent.executor import Executor
from backend.agent.observer import Observer
from backend.agent.verifier import Verifier


class AgentCore:
    def __init__(self):
        self.registry = ToolRegistry()
        self.planner = Planner()
        self.executor = Executor(self.registry)
        self.observer = Observer(self.registry)
        self.verifier = Verifier()
        self._setup_default_tools()

    def _setup_default_tools(self):
        """Register all default system tools."""
        # System ops
        from system_ops import (
            open_application, close_application, list_files, read_file, write_file,
            delete_file, take_screenshot, create_folder, create_word_document,
            check_pc_health, adjust_volume, media_control, search_web, launch_any_app,
            save_generated_image, shutdown_pc, restart_pc, cancel_shutdown, sleep_pc,
            lock_screen, get_clipboard, set_clipboard, get_battery_info, get_network_info,
            get_weather, get_datetime_info, get_system_stats, open_url, type_text, press_key
        )

        # Phone control
        from phone_control import (
            list_devices, start_mirror, screenshot_as_base64, tap, swipe,
            input_text, press_key as press_key_phone, launch_app as launch_phone_app,
            unlock_phone, test_pin_digit_tap
        )

        # WhatsApp ops
        from whatsapp_ops import send_whatsapp_message, send_whatsapp_message_via_phone, add_contact

        # Register system tools
        system_tools = {
            "open_app": open_application,
            "close_app": close_application,
            "launch_app": launch_any_app,
            "shutdown": shutdown_pc,
            "restart": restart_pc,
            "cancel_shutdown": cancel_shutdown,
            "sleep": sleep_pc,
            "lock_screen": lock_screen,
            "volume_up": adjust_volume,
            "volume_down": adjust_volume,
            "mute_volume": adjust_volume,
            "play_pause": media_control,
            "next_track": media_control,
            "prev_track": media_control,
            "search_web": search_web,
            "weather": lambda city: get_weather(city) if isinstance(city, str) else get_weather("London"),
            "battery": get_battery_info,
            "network_info": get_network_info,
            "datetime_info": get_datetime_info,
            "take_screenshot": take_screenshot,
            "show_stats": get_system_stats,
            "create_folder": create_folder,
            "create_word_doc": create_word_document,
            "check_pc_health": check_pc_health,
            "clipboard_read": get_clipboard,
            "clipboard_write": set_clipboard,
            "open_url": open_url,
            "type_text": type_text,
            "press_key": press_key,
        }

        for name, func in system_tools.items():
            self.registry.register(name, func)

        # Register phone tools
        phone_tools = {
            "phone_devices": list_devices,
            "phone_mirror": start_mirror,
            "phone_screenshot": screenshot_as_base64,
            "phone_tap": tap,
            "phone_swipe": swipe,
            "phone_text": input_text,
            "phone_key": press_key_phone,
            "phone_launch_app": launch_phone_app,
            "phone_unlock": unlock_phone,
            "phone_test_pin_tap": test_pin_digit_tap,
        }
        for name, func in phone_tools.items():
            self.registry.register(name, func)

        # Register WhatsApp tools
        self.registry.register("send_whatsapp", send_whatsapp_message)
        self.registry.register("send_whatsapp_phone", send_whatsapp_message_via_phone)
        self.registry.register("add_whatsapp_contact", add_contact)

        # Register image generation
        self.registry.register("generate_image", lambda prompt, **kwargs: None)
        self.registry.register("generate_image_huggingface", lambda prompt, hf_key, save_name: None)

    async def process(self, task: str, state: TaskState) -> Dict[str, Any]:
        """Process a natural language task through the full agent loop."""
        state.errors = []
        state.completed_steps = []
        state.current_step = 0
        state.retry_count = 0
        state.completion_status = None

        # Step 1: Plan the task
        steps = self.planner.plan_task(task, state)
        state.plan = steps
        state.task = task

        # Step 2: Main execution loop
        max_iterations = 10
        for iteration in range(max_iterations):
            # Observe system state
            observations = await self.observer.observe(state, "general")
            state.observations.extend(observations.get("observations", []))

            # Check if task is complete
            if state.current_step >= len(steps) or state.completion_status == "completed":
                break

            # Get current step
            if state.current_step < len(state.plan):
                current_step = state.plan[state.current_step]
            else:
                break

            # Execute the action
            # Determine what action to take based on the step
            action = self._derive_action(current_step, state)

            if not action:
                state.errors.append(f"Could not derive action for step: {current_step}")
                state.retry_count += 1
                if not self.verifier.should_retry(state):
                    break
                continue

            # Execute the action
            result = await self.executor.execute(action, state)
            state.tool_history.append(action.copy())

            # Record the result
            if result and isinstance(result, dict):
                if result.get("status") == "error":
                    state.errors.append(result.get("message", "Unknown error"))
                    state.retry_count += 1

            # Update step progress
            state.current_step += 1

            # Verify after each step
            verification = self.verifier.verify(state, action)
            state.verification_status = verification["verification_status"]

            # If completed or failed, stop
            if verification["verification_status"] in ("completed", "failed"):
                state.completion_status = verification["verification_status"]
                break

            # If needing retry
            if not self.verifier.should_retry(state) and verification["verification_status"] != "pending":
                break

        # Final verification
        final_verification = self.verifier.verify(state)
        state.completion_status = final_verification["verification_status"]

        return {
            "status": state.completion_status or "pending",
            "task": state.task,
            "plan": state.plan,
            "completed_steps": state.completed_steps,
            "errors": state.errors,
            "observations": state.observations,
            "retry_count": state.retry_count,
        }

    def _derive_action(self, step: str, state: TaskState) -> Optional[Dict[str, Any]]:
        """Derive a concrete action from a plan step string."""
        step_lower = step.lower().strip()

        # Open application
        if any(word in step_lower for word in ["open", "launch", "start"]):
            # Extract app name
            for word in step_lower.split():
                if word not in ["open", "launch", "start", "the", "a", "an"]:
                    app_name = word
                    # Try to reconstruct the full app name
                    # Look at the original task for context
                    return {"type": "open_app", "app_name": app_name}

        # Search the web
        if any(word in step_lower for word in ["search", "google", "find"]):
            # Extract query
            # Simple heuristic: everything after "for" or the main phrase
            query_match = __import__("re").search(r'(?:for|search )(.+)', step_lower)
            query = query_match.group(1).strip() if query_match else step_lower
            return {"type": "search_web", "query": query}

        # Create document
        if any(word in step_lower for word in ["create", "make", "generate"]):
            # Check if it's a Word document
            if "word" in step_lower or ".docx" in step_lower:
                # Extract filename and content
                filename_match = __import__("re").search(r'(?:named|called)?\s*([a-zA-Z0-9_\-\.]+)', step_lower)
                filename = filename_match.group(1) if filename_match else "document.docx"
                return {"type": "create_word_doc", "filename": filename, "content": "Generated content"}
            return {"type": "speak", "text": "I can help create documents, but I need more specifics about the format and content."}

        # Shutdown/restart/sleep
        if any(word in step_lower for word in ["shutdown", "shut down", "power off"]):
            # Extract delay if present
            delay_match = __import__("re").search(r'in\s+(\d+)\s*min', step_lower)
            delay = int(delay_match.group(1)) * 60 if delay_match else 0
            return {"type": "shutdown", "delay_seconds": delay}

        if any(word in step_lower for word in ["restart", "reboot"]):
            delay_match = __import__("re").search(r'in\s+(\d+)\s*min', step_lower)
            delay = int(delay_match.group(1)) * 60 if delay_match else 0
            return {"type": "restart", "delay_seconds": delay}

        if any(word in step_lower for word in ["sleep", "hibernate"]):
            return {"type": "sleep"}

        # Default: speak
        return {"type": "speak", "text": f"I'll help you with: {step}"}