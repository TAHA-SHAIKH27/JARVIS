"""
AgentCore — the master orchestrator of the JARVIS agent loop.

Flow per task:
  1. Planner (LLM) → structured action list
  2. For each action:
       a. Executor → real tool execution
       b. Observer → verify real system state
       c. Verifier → confirmed / retry / fail
       d. emit event to event_queue (→ SSE stream)
  3. Emit "complete" event with final summary
"""
import asyncio
import json
import time
import traceback
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
        """Register all default system tools in the registry."""
        from system_ops import (
            open_application, close_application, list_files, read_file, write_file,
            delete_file, take_screenshot, create_folder, create_word_document,
            check_pc_health, adjust_volume, media_control, search_web, launch_any_app,
            save_generated_image, shutdown_pc, restart_pc, cancel_shutdown, sleep_pc,
            lock_screen, get_clipboard, set_clipboard, get_battery_info, get_network_info,
            get_weather, get_datetime_info, open_url, type_text, press_key,
            get_system_stats
        )
        from phone_control import (
            list_devices, start_mirror, screenshot_as_base64, tap, swipe,
            input_text, press_key as press_key_phone, launch_app as launch_phone_app,
            unlock_phone, test_pin_digit_tap
        )
        from whatsapp_ops import send_whatsapp_message, send_whatsapp_message_via_phone, add_contact
        from backend.tools.computer import Computer
        from backend.tools.browser import Browser
        from backend.tools.office import Office

        system_tools = {
            "open_app": open_application, "close_app": close_application,
            "launch_app": launch_any_app, "shutdown": shutdown_pc, "restart": restart_pc,
            "cancel_shutdown": cancel_shutdown, "sleep": sleep_pc, "lock_screen": lock_screen,
            "volume_up": adjust_volume, "volume_down": adjust_volume, "mute_volume": adjust_volume,
            "play_pause": media_control, "next_track": media_control, "prev_track": media_control,
            "search_web": search_web, "battery": get_battery_info, "network_info": get_network_info,
            "datetime_info": get_datetime_info, "take_screenshot": take_screenshot,
            "show_stats": get_system_stats, "create_folder": create_folder,
            "create_word_doc": create_word_document, "check_pc_health": check_pc_health,
            "clipboard_read": get_clipboard, "clipboard_write": set_clipboard, "open_url": open_url,
            "type_text": type_text, "press_key": press_key,
        }
        for name, func in system_tools.items():
            self.registry.register(name, func)

        phone_tools = {
            "phone_devices": list_devices, "phone_mirror": start_mirror,
            "phone_screenshot": screenshot_as_base64, "phone_tap": tap, "phone_swipe": swipe,
            "phone_text": input_text, "phone_key": press_key_phone,
            "phone_launch_app": launch_phone_app, "phone_unlock": unlock_phone,
            "phone_test_pin_tap": test_pin_digit_tap,
        }
        for name, func in phone_tools.items():
            self.registry.register(name, func)

        self.registry.register("send_whatsapp", send_whatsapp_message)
        self.registry.register("send_whatsapp_phone", send_whatsapp_message_via_phone)
        self.registry.register("add_whatsapp_contact", add_contact)
        self.registry.register("generate_image", lambda prompt, **kwargs: None)

        # Register new tool classes for direct access
        self.registry.register("computer_tool", Computer(self.registry))
        self.registry.register("browser_tool", Browser())
        self.registry.register("office_tool", Office)

    # ─────────────────────────────────────────────────────────────────────────
    # Main agent process loop
    # ─────────────────────────────────────────────────────────────────────────

    async def process(
        self,
        task: str,
        state: TaskState,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        """
        Execute the full agent loop for a task.

        event_queue: if provided, structured event dicts are put() here for
                     streaming to the frontend via SSE.
        """

        async def emit(event_type: str, message: str, data: dict = None, icon: str = "→"):
            """Put an event into the queue (non-blocking)."""
            if event_queue is not None:
                event = {
                    "type": event_type,
                    "message": message,
                    "icon": icon,
                    "data": data or {},
                    "ts": time.time(),
                }
                await event_queue.put(event)

        # ── Initialise state ──────────────────────────────────────────────
        state.task = task
        state.errors = []
        state.completed_steps = []
        state.current_step = 0
        state.retry_count = 0
        state.completion_status = None
        state.observations = []

        collected_data = {}   # accumulates browser text, titles, etc.
        speak_text = ""       # final response text

        await emit("planning", f"Planning task: {task}", icon="🧠")

        # ── Step 1: Plan ──────────────────────────────────────────────────
        try:
            actions = self.planner.plan_task(task, state)
        except Exception as e:
            await emit("error", f"Planning failed: {str(e)}", icon="✗")
            return {"status": "error", "task": task, "errors": [str(e)]}

        if not actions:
            await emit("error", "Planner returned no actions", icon="✗")
            return {"status": "error", "task": task, "errors": ["No actions planned"]}

        # Log the plan
        plan_desc = [a.get("description", a.get("type", "?")) for a in actions]
        await emit("plan_ready", f"Plan: {' → '.join(plan_desc)}", {"steps": plan_desc}, icon="📋")

        state.plan = [a.get("description", a.get("type", "")) for a in actions]

        # ── Step 2: Execute each action ───────────────────────────────────
        max_retries = 3
        action_index = 0

        while action_index < len(actions):
            action = actions[action_index]
            atype = action.get("type", "")
            desc = action.get("description", atype)

            # Skip "speak" actions during execution loop — collect text instead
            if atype == "speak":
                speak_text = action.get("text", "")
                state.completed_steps.append(action_index)
                action_index += 1
                continue

            await emit("action_start", desc, {"action": atype, "step": action_index + 1}, icon="→")

            # Execute
            try:
                result = await self.executor.execute(action, state)
            except Exception as e:
                tb = traceback.format_exc()
                result = {"status": "error", "message": f"Executor exception: {str(e)}", "traceback": tb}

            # Observe (real state verification)
            browser = self.executor._browser  # may be None if no browser action yet
            try:
                observation = await self.observer.observe_after_action(action, result, state, browser)
            except Exception as e:
                observation = {"verified": False, "message": f"Observer error: {str(e)}"}

            # Verify
            verification = self.verifier.verify_action(action, result, observation)

            if verification["verified"]:
                await emit(
                    "action_done",
                    f"✓ {desc}: {observation.get('message', '')}",
                    {"action": atype, "verified": True, "observation": observation},
                    icon="✓"
                )
                state.completed_steps.append(action_index)

                # Collect browser data for DOCX / summary
                if atype == "browser_extract" and result and result.get("text"):
                    key = f"source_{len([k for k in collected_data if k.startswith('source_')])}"
                    collected_data[key] = {
                        "text": result.get("text", "")[:3000],
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                    }
                elif atype == "browser_get_title" and result:
                    collected_data["page_title"] = result.get("title", "")
                    collected_data["page_url"] = result.get("url", "")

                # Reset retry count on successful action
                state.retry_count = 0
                action_index += 1

            else:
                # Action failed or unverified
                fail_msg = verification.get("message", "Verification failed")
                await emit(
                    "action_error",
                    f"✗ {desc}: {fail_msg}",
                    {"action": atype, "verified": False, "message": fail_msg},
                    icon="✗"
                )
                state.errors.append(f"[{atype}] {fail_msg}")

                if verification["should_retry"] and state.retry_count < max_retries:
                    state.retry_count += 1
                    await emit("retrying", f"Retrying: {desc} (attempt {state.retry_count})", icon="↺")
                    await asyncio.sleep(1.0)
                    # Don't advance action_index — retry same action
                else:
                    # Mandatory action failed after retries — do NOT silently continue
                    # Mark task as having a critical failure
                    await emit("error", f"Critical failure on step '{desc}': {fail_msg}. Task cannot continue.", icon="✗")
                    state.completion_status = "failed"
                    # Return early with failure status
                    speak_text = f"Task failed, sir. Critical step failed: {desc}. Error: {fail_msg}"
                    if self.executor._browser:
                        await self.executor.close_browser()
                    await emit(
                        "complete",
                        speak_text,
                        {
                            "status": "failed",
                            "completed_steps": len(state.completed_steps),
                            "total_steps": len(actions),
                            "errors": state.errors,
                            "collected_data": {k: v for k, v in collected_data.items() if isinstance(v, str)},
                        },
                        icon="✗"
                    )
                    return {
                        "status": "failed",
                        "task": task,
                        "speak": speak_text,
                        "plan": state.plan,
                        "completed_steps": state.completed_steps,
                        "errors": state.errors,
                        "collected_data": collected_data,
                    }

        # ── Step 3: Auto-inject collected data into create_docx if needed ─
        # If the plan had browser_extract steps and a create_docx step but
        # content is still a placeholder, fill it with collected text.
        for i, action in enumerate(actions):
            if action.get("type") == "create_docx" and collected_data:
                existing_content = action.get("content", "")
                if len(existing_content) < 200 and collected_data:
                    # Build content from collected sources
                    content_parts = []
                    for key, src in collected_data.items():
                        if isinstance(src, dict) and src.get("text"):
                            content_parts.append(f"Source: {src.get('title', 'Unknown')}")
                            content_parts.append(f"URL: {src.get('url', '')}")
                            content_parts.append("")
                            content_parts.append(src["text"][:2000])
                            content_parts.append("\n---\n")
                    if content_parts:
                        action["content"] = "\n".join(content_parts)

        # ── Step 4: Final result ─────────────────────────────────────────
        state.completion_status = "completed" if not state.errors or state.completed_steps else "failed"

        # Build final speak text if not set
        if not speak_text:
            completed = len(state.completed_steps)
            total = len([a for a in actions if a.get("type") != "speak"])
            if state.errors:
                speak_text = f"Task partially complete, sir. {completed} of {total} steps succeeded. Issues: {'; '.join(state.errors[:2])}"
            elif collected_data.get("page_title"):
                speak_text = f"Done, sir. The page title is: {collected_data['page_title']}"
            else:
                speak_text = f"Task complete, sir. All {total} steps executed successfully."

        # Close browser if it was opened
        if self.executor._browser:
            await emit("observation", "Closing browser", icon="✓")
            await self.executor.close_browser()

        await emit(
            "complete",
            speak_text,
            {
                "status": state.completion_status,
                "completed_steps": len(state.completed_steps),
                "total_steps": len(actions),
                "errors": state.errors,
                "collected_data": {k: v for k, v in collected_data.items() if isinstance(v, str)},
            },
            icon="✓"
        )

        return {
            "status": state.completion_status,
            "task": task,
            "speak": speak_text,
            "plan": state.plan,
            "completed_steps": state.completed_steps,
            "errors": state.errors,
            "collected_data": collected_data,
        }