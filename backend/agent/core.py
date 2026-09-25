"""
AgentCore — the master orchestrator of the JARVIS agent loop.

Flow per task:
  1. Goal Understanding → Planner (LLM) → structured action plan
  2. Plan Validation → check dependencies, parameters, completeness
  3. For each action (respecting dependencies):
       a. Executor → real tool execution
       b. Observer → verify real system state
       c. Verifier → confirmed / retry / fail with classification
       d. Store structured output in state.action_outputs
       e. Emit event to event_queue (→ SSE stream)
  4. After each step: Check if replanning needed
  5. Human-in-the-loop handling (pause/resume)
  6. Final Outcome Verification → verify actual deliverable exists
  7. Emit "complete" event with verified summary

Supports:
- Mid-task user instructions (updates current task context)
- Interruptible execution (planning, speaking, waiting, acting)
- Separate conversation/task/computer contexts
- Bounded failure recovery with alternative strategies
"""
import asyncio
import json
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum

from backend.agent.state import TaskState, ActionSpec, Plan, TaskType, FailureClassification
from backend.agent.registry import ToolRegistry
from backend.agent.planner import Planner
from backend.agent.executor import Executor
from backend.agent.observer import Observer
from backend.agent.verifier import Verifier
from backend.agent import personality
from backend.agent import clarify


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
    # Interruption & Status Management
    # ─────────────────────────────────────────────────────────────────────────

    class AgentStatus(Enum):
        """High-level agent status for frontend reporting."""
        IDLE = "idle"
        THINKING = "thinking"
        PLANNING = "planning"
        ACTING = "acting"
        OBSERVING = "observing"
        VERIFYING = "verifying"
        RECOVERING = "recovering"
        REPLANNING = "replanning"
        LISTENING = "listening"
        SPEAKING = "speaking"
        WAITING_FOR_USER = "waiting_for_user"
        COMPLETED = "completed"
        FAILED = "failed"
        INTERRUPTED = "interrupted"

    def __init__(self):
        self.registry = ToolRegistry()
        self.planner = Planner()
        self.executor = Executor(self.registry)
        self.observer = Observer(self.registry)
        self.verifier = Verifier()
        self._setup_default_tools()
        
        # Interruption and status tracking
        self._interrupt_requested = False
        self._interrupt_reason = ""
        self._current_status = self.AgentStatus.IDLE
        self._status_callback: Optional[Callable[[AgentStatus, str], None]] = None
        self._mid_task_instruction: Optional[str] = None
        self._mid_task_instruction_processed = False
        # Mid-run command queue: [{"text": str, "verdict": "merged"|"queued"|None}]
        self._pending_instructions: List[Dict[str, Any]] = []
        self._active_task: str = ""
        self._tts_task: Optional[asyncio.Task] = None
        self._current_action_start_time: Optional[float] = None
        self._execution_lock = asyncio.Lock()

        # Phase 1: multi-model intelligence. Built lazily so import-time and
        # offline behavior are unchanged; Planner also uses it directly.
        self._model_router = None
        self._model_registry = None
        self._model_providers = None

        # Phase 2: persistent memory subsystem (single-agent subsystem, not a
        # separate agent). Lazy so import-time and offline behavior stay put.
        self._jarvis_memory = None

    @property
    def model_router(self):
        """The single Model Router for this agent (JARVIS -> Router -> models)."""
        if self._model_router is None:
            from backend.agent import model_factory
            registry, providers, router = model_factory.build_router()
            self._model_registry = registry
            self._model_providers = providers
            self._model_router = router
        return self._model_router

    @property
    def memory(self):
        """Phase 2 memory façade (None when unavailable — tasks still run)."""
        if self._jarvis_memory is None:
            try:
                from backend.agent.memory_api import JarvisMemory
                self._jarvis_memory = JarvisMemory()
            except Exception:
                return None
        return self._jarvis_memory

    def memory_context_for(self, task: str, limit: int = 6,
                           max_chars: int = 1500) -> str:
        """MEMORY RETRIEVAL step: compact relevant memories for a task.

        Lexical-only (no network) so planning never stalls. Never raises —
        returns "" when memory is unavailable."""
        try:
            api = self.memory
            if api is None:
                return ""
            return api.memory_context(task or "", limit=limit, max_chars=max_chars)
        except Exception:
            return ""

    def _memory_store_outcome(self, task: str, status: str, speak: str) -> None:
        """MEMORY UPDATE step: bank the VERIFIED outcome as episodic memory.

        Skipped for automated test runs (PYTEST_CURRENT_TEST) so CI noise
        never pollutes long-term memory. Never raises — memory must never
        break task execution."""
        try:
            import os as _os
            if _os.environ.get("PYTEST_CURRENT_TEST"):
                return
            api = self.memory
            if api is None:
                return
            from backend.agent.memory_schema import (
                Confidence, MemorySource, MemoryType)
            summary = (speak or status or "").strip()
            content = f"Task '{(task or '')[:200]}' finished with status {status}."
            if summary:
                content += f" Outcome: {summary[:400]}"
            api.add(content, memory_type=MemoryType.EPISODIC,
                    source=MemorySource.VERIFIED_TASK_RESULT,
                    confidence=Confidence.HIGH,
                    tags=["task-outcome", str(status or "unknown")],
                    source_reference=f"agent run, status={status}")
            # Learn stable user choices from the chat itself so JARVIS gets
            # better with use (learned facts are MEDIUM/conversation-scoped
            # and can never overwrite explicit HIGH preferences).
            try:
                api.learn_from_exchange(task, status)
            except Exception:
                pass
        except Exception:
            pass

    def set_status_callback(self, callback: Callable[[AgentStatus, str], None]):
        """Set callback for status updates (for frontend SSE)."""
        self._status_callback = callback

    def _set_status(self, status: AgentStatus, message: str = ""):
        """Update agent status and emit event."""
        self._current_status = status
        # This will be called from within process() which has event_queue

    def request_interrupt(self, reason: str = "User requested interruption"):
        """Request interruption of current execution."""
        self._interrupt_requested = True
        self._interrupt_reason = reason

    def clear_interrupt(self):
        """Clear interruption request."""
        self._interrupt_requested = False
        self._interrupt_reason = ""

    def inject_mid_task_instruction(self, instruction: str):
        """Queue a mid-task instruction (voice-service compatible entry)."""
        text = (instruction or "").strip()
        if text:
            self._pending_instructions.append({"text": text})

    def enqueue_instruction(self, text: str, current_task: str = "") -> Dict[str, Any]:
        """Accept a new command while a run is active; triage immediately.

        Returns {"verdict": "merged"|"queued", "message": str} so the caller
        (HTTP/voice) can confirm instantly. Merged items restart the plan;
        queued items run after the current task finishes."""
        text = (text or "").strip()
        if not text:
            return {"verdict": "ignored", "message": "Empty instruction ignored, sir."}
        task = current_task or getattr(self, "_active_task", "") or ""
        verdict = clarify.classify_instruction(task, text)
        self._pending_instructions.append({"text": text})
        if verdict["related"]:
            return {"verdict": "merged",
                    "message": f"Noted, sir — folding that into the current task ({verdict['reason']}) and restarting the plan."}
        return {"verdict": "queued",
                "message": f"Noted, sir — that's separate work, so I've queued it to run right after this task."}

    async def _check_interrupt(self, event_queue: Optional[asyncio.Queue] = None) -> bool:
        """Check for interruption and handle it gracefully."""
        if self._interrupt_requested:
            if event_queue:
                await event_queue.put({
                    "type": "interrupted",
                    "message": f"Execution interrupted: {self._interrupt_reason}",
                    "icon": "⚠",
                    "data": {"reason": self._interrupt_reason},
                    "ts": time.time(),
                })
            return True
        return False

    async def _handle_mid_task_instruction(self, state: TaskState, event_queue: Optional[asyncio.Queue] = None) -> bool:
        """Drain queued mid-run commands: related ones merge into the task
        (fresh plan, restart from step one); independent ones wait their
        turn in state.queued_tasks. Returns True when the plan changed."""
        if not self._pending_instructions:
            return False
        items = self._pending_instructions
        self._pending_instructions = []
        merged: List[str] = []
        for item in items:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            if not text.strip():
                continue
            verdict = clarify.classify_instruction(state.task, text)
            if verdict["related"]:
                merged.append(text)
            else:
                queued = getattr(state, "queued_tasks", None)
                if queued is None:
                    queued = []
                    state.queued_tasks = queued
                if text not in queued:
                    queued.append(text)
                if event_queue:
                    await event_queue.put({
                        "type": "task_queued",
                        "message": f"Queued for after this task, sir: {text[:80]}",
                        "icon": "⏳",
                        "data": {"instruction": text, "queue": list(queued)},
                        "ts": time.time(),
                    })
        if not merged:
            return False
        change = " + ".join(m[:100] for m in merged)
        if event_queue:
            await event_queue.put({
                "type": "plan_restarted",
                "message": f"Understood, sir — folding that in ({change}) and restarting the plan from the top.",
                "icon": "🔄",
                "data": {"changes": merged},
                "ts": time.time(),
            })
        state.task = f"{state.task} | Change: {change}"
        try:
            new_actions = await asyncio.to_thread(
                self.planner.plan_task, state.task, state)
            # plan_task rebuilds state.plan from scratch; the caller resets
            # execution to step one (user asked for a restart, not a resume).
            _ = new_actions
            return True
        except Exception as e:
            if event_queue:
                await event_queue.put({
                    "type": "error",
                    "message": f"Failed to process mid-task instruction: {str(e)}",
                    "icon": "✗",
                    "ts": time.time(),
                })
            return False

    async def _emit_status(self, status: 'AgentCore.AgentStatus', message: str, event_queue: Optional[asyncio.Queue] = None):
        """Emit status update event."""
        if event_queue:
            await event_queue.put({
                "type": "status_update",
                "message": message,
                "icon": "📊",
                "data": {"status": status.value},
                "ts": time.time(),
            })

    async def _execute_with_interrupt_check(self, action: ActionSpec, state: TaskState, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        """Execute an action with periodic interrupt checking."""
        # For long-running actions, we could add periodic checks here
        # For now, just execute normally - interruption is checked between actions
        return await self.executor.execute(action, state)

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
        state.action_outputs = {}
        state.failed_steps = {}
        state.human_verification_required = False
        state.human_verification_message = ""
        state.human_verification_resolved = False
        state.human_verification_action_index = None
        state.human_verification_context = {}
        state.waiting_for_user = False
        state.replan_count = 0
        state.last_replan_reason = ""
        state.final_outcome_verified = False
        state.final_outcome_data = {}
        state.queued_tasks = []
        self._active_task = task
        # NOTE: _pending_instructions is NOT cleared here — instructions may
        # legitimately arrive between run creation and loop start.

        speak_text = ""       # final response text

        await emit("planning", f"Planning task: {task}", icon="🧠")

        # ── Step 0: Clarification (ask once when genuinely unclear) ──────
        # Like a good assistant, JARVIS asks a focused follow-up instead of
        # guessing. One round only — an empty answer means best-effort run.
        if not getattr(state, "clarification_done", False):
            question = clarify.needs_clarification(task)
            if question:
                enriched = await self._ask_clarification(task, state, question, emit, event_queue)
                if enriched is None:
                    # Interrupted while asking — stop politely.
                    state.completion_status = "interrupted"
                    speak_text = f"Task interrupted, sir. {self._interrupt_reason}"
                    return {"status": "interrupted", "task": task, "speak": speak_text,
                            "completed_steps": state.completed_steps, "errors": state.errors,
                            "interrupt_reason": self._interrupt_reason}
                task = enriched
                state.task = task

        # ── Phase 2: explicit memory commands bypass planning ─────────────
        # "Remember this" / "Forget that" / "What do you remember" /
        # "Correct that memory" / "Show me relevant memories" act on real
        # persistent memory and return directly — no plan, no tools.
        try:
            _api = self.memory
            _cmd = _api.handle_explicit_command(task) if _api is not None else None
        except Exception:
            _cmd = None
        if _cmd is not None:
            _speak = str(_cmd.get("speak") or "Done, sir.")
            state.completion_status = "completed"
            state.update_context("memory_command", _cmd.get("action", ""))
            await emit("task_completed", _speak,
                       {"status": "completed", "memory_action": _cmd.get("action", ""),
                        "memory": _cmd}, icon="✓")
            return {"status": "completed", "task": task, "speak": _speak,
                    "plan": [], "completed_steps": [], "errors": [],
                    "memory_action": _cmd}

        # ── Phase 2: MEMORY RETRIEVAL (lexical, offline-safe) ─────────────
        # Relevant memories land in state context for PLAN/ACT/OBSERVE/VERIFY.
        try:
            state.update_context("phase2_memory_context",
                                 self.memory_context_for(task))
        except Exception:
            pass

        # ── Step 1: Plan ──────────────────────────────────────────────────
        # Planner does blocking network I/O (LLM via router/legacy, up to the
        # router timeout). Run it in a worker thread so the server event loop
        # stays responsive to health checks and the SSE stream stays alive.
        try:
            actions = await asyncio.to_thread(self.planner.plan_task, task, state)
        except Exception as e:
            await emit("error", f"Planning failed: {str(e)}", icon="✗")
            return {"status": "error", "task": task, "errors": [str(e)]}

        if not actions:
            await emit("error", "Planner returned no actions", icon="✗")
            return {"status": "error", "task": task, "errors": ["No actions planned"]}

        # Log the plan
        plan_desc = [a.description for a in actions]
        n_real = len([a for a in actions if a.type != "speak"])
        await emit("plan_created", personality.acknowledge(task, n_real), {"steps": plan_desc}, icon="📋")

        # ── Step 2: Validate Plan ─────────────────────────────────────────
        plan = state.plan
        if not plan.is_valid:
            await emit("plan_validation_failed", f"Plan validation failed: {plan.validation_errors}", {"errors": plan.validation_errors}, icon="✗")
            # Try to auto-fix
            plan = self.planner._auto_fix_plan(plan, state)
            plan = self.planner._validate_plan(plan, state)
            state.plan = plan
            
            if not plan.is_valid:
                await emit("error", "Plan validation failed after auto-fix", icon="✗")
                return {"status": "error", "task": task, "errors": plan.validation_errors}

        await emit("plan_validated", f"Plan validated successfully", {"steps": plan_desc}, icon="✓")

        # ── Step 3: Execute actions respecting dependencies ───────────────
        max_retries = 3
        action_index = 0
        completed_indices: Set[int] = set()

        while action_index < len(actions):
            # Check for interruption before each action
            if await self._check_interrupt(event_queue):
                state.completion_status = "interrupted"
                speak_text = f"Task interrupted, sir. {self._interrupt_reason}"
                await emit("task_interrupted", speak_text, {
                    "completed_steps": len(state.completed_steps),
                    "total_steps": len([a for a in actions if a.type != "speak"]),
                    "errors": state.errors,
                    "reason": self._interrupt_reason
                }, icon="⚠")
                return {
                    "status": "interrupted",
                    "task": task,
                    "speak": speak_text,
                    "completed_steps": state.completed_steps,
                    "errors": state.errors,
                    "interrupt_reason": self._interrupt_reason
                }

            # Handle mid-task instruction if available
            if await self._handle_mid_task_instruction(state, event_queue):
                # Plan was rebuilt from the merged task - restart from step one
                task = state.task
                actions = state.plan.actions
                action_index = 0
                completed_indices = set()
                state.completed_steps = []
                state.retry_count = 0
                continue

            action = actions[action_index]
            atype = action.type
            desc = action.description

            # Check dependencies
            if not self._dependencies_satisfied(action, completed_indices, state):
                # Skip for now, will come back after dependencies complete
                action_index += 1
                continue

            # Skip "speak" actions during execution loop — collect text instead
            if atype == "speak":
                speak_text = (
                    state.get_context("last_finding", "")
                    if action.parameters.get("use_last_finding")
                    else action.parameters.get("text", "")
                )
                # Plain completion messages should carry the actual evidence:
                # terminal output, download paths, saved tables. Otherwise the
                # user hears "done" without ever seeing the result.
                if not action.parameters.get("use_last_finding"):
                    evidence = self._collect_speak_evidence(state, action)
                    if evidence:
                        speak_text = f"{speak_text}\n\n{evidence}" if speak_text else evidence
                state.completed_steps.append(action_index)
                completed_indices.add(action_index)
                action_index += 1
                continue

            # Check if waiting for human
            if state.waiting_for_user and state.human_verification_action_index == action_index:
                await emit("waiting_for_user", state.human_verification_message, 
                          {"action_index": action_index, "context": state.human_verification_context}, icon="⏳")
                # Wait for human to resolve with interrupt check
                while state.waiting_for_user and state.human_verification_action_index == action_index:
                    if await self._check_interrupt(event_queue):
                        state.completion_status = "interrupted"
                        speak_text = f"Task interrupted while waiting for user, sir. {self._interrupt_reason}"
                        await emit("task_interrupted", speak_text, {"reason": self._interrupt_reason}, icon="⚠")
                        return {"status": "interrupted", "task": task, "speak": speak_text, "errors": state.errors}
                    await asyncio.sleep(0.5)
                if state.human_verification_resolved:
                    await emit("resuming", "Human intervention resolved, resuming execution", {"action_index": action_index}, icon="▶")
                    state.waiting_for_user = False
                    state.human_verification_resolved = False
                else:
                    state.errors.append(f"Human intervention not resolved for step {action_index}")
                    break

            state.current_step = action_index
            self._current_action_start_time = time.time()
            await emit("step_started", personality.narrate_start(atype, desc, action_index, len(actions), action.parameters),
                      {"action": atype, "step": action_index + 1, "total": len(actions), "description": desc}, icon="→")

            # Execute with interrupt checking
            await emit("tool_started", f"Starting tool: {atype}", {"action": atype, "parameters": action.parameters}, icon="⚙")
            try:
                result = await self._execute_with_interrupt_check(action, state, event_queue)
            except Exception as e:
                tb = traceback.format_exc()
                result = {"status": "error", "message": f"Executor exception: {str(e)}", "traceback": tb}
            await emit("tool_completed", f"Tool {atype} returned", {"action": atype, "result_status": result.get("status") if result else "none"}, icon="⚙")

            # Store result in state for data flow
            state.action_outputs[action_index] = result or {}

            # Observe (real state verification)
            await emit("observing", f"Observing system state after {atype}", {"action": atype}, icon="👁")
            browser = self.executor._browser
            try:
                observation = await self.observer.observe_after_action(action, result, state, browser)
            except Exception as e:
                observation = {"verified": False, "message": f"Observer error: {str(e)}", "classification": "retryable"}

            # Verify
            await emit("verification_started", f"Verifying result of {atype}", {"action": atype}, icon="✓")
            verification = self.verifier.verify_action(action, result, observation)


            # Log execution step
            self._log_execution(action_index + 1, len(actions), action, result or {}, observation or {}, verification or {})
            
            if verification["verified"]:

                await emit("verification_passed", f"Verification passed for {atype}", {"action": atype}, icon="✓")
                # Emit status update for frontend
                await self._emit_status(self.AgentStatus.ACTING, f"Step {action_index + 1} completed: {desc}", event_queue)

                await emit(
                    "step_completed",
                    f"✓ {personality.narrate_done(atype, observation)}",
                    {"action": atype, "verified": True, "observation": observation, "step": action_index + 1, "description": desc},
                    icon="✓"
                )
                state.completed_steps.append(action_index)
                completed_indices.add(action_index)
                state.observations.append(observation)

                # Store structured output for data flow
                if result:
                    state.action_outputs[action_index] = result

                # Reset retry count on successful action
                state.retry_count = 0
                action_index += 1

            else:
                # Action failed or unverified
                fail_msg = verification.get("message", "Verification failed")
                classification = verification.get("classification", "recoverable")
                should_retry = verification.get("should_retry", False)
                requires_user = verification.get("requires_user", False)

                await emit("verification_failed", f"Verification failed for {atype}: {fail_msg}", {"action": atype, "classification": classification}, icon="✗")
                await emit(
                    "step_failed",
                    f"✗ {desc}: {fail_msg}",
                    {"action": atype, "verified": False, "message": fail_msg, 
                     "classification": classification, "step": action_index + 1},
                    icon="✗"
                )
                state.errors.append(f"[{atype}] {fail_msg}")
                state.failed_steps[action_index] = {
                    "action_type": atype,
                    "message": fail_msg,
                    "classification": classification,
                    "result": result,
                    "observation": observation
                }

                # Graceful degradation: an empty source page must not kill a
                # research task that already banked usable sources. Skip the
                # dead source and continue (dependencies treat it as done).
                if atype == "browser_extract" and self._should_skip_empty_source(state, fail_msg):
                    await emit("step_skipped", f"Source had no readable content — continuing with {len(state.extracted_sources)} source(s)",
                              {"action": atype, "step": action_index + 1}, icon="⏭")
                    state.completed_steps.append(action_index)
                    completed_indices.add(action_index)
                    state.observations.append(observation)
                    state.retry_count = 0
                    action_index += 1
                    continue

                # Handle based on failure classification
                if requires_user:
                    # Human required - pause and wait
                    state.human_verification_required = True
                    state.human_verification_message = fail_msg
                    state.human_verification_action_index = action_index
                    state.human_verification_context = {
                        "action": action.parameters,
                        "result": result,
                        "observation": observation
                    }
                    state.waiting_for_user = True
                    kind = "login" if atype in ("browser_login", "browser_login_check") else (
                        "captcha" if "captcha" in (fail_msg or "").lower() else "")
                    await emit("human_intervention_required", personality.narrate_waiting_human(fail_msg, kind),
                              {"action_index": action_index, "classification": classification, "kind": kind}, icon="👤")
                    # Don't advance - wait for human
                    continue


                elif classification == FailureClassification.RETRYABLE.value and state.retry_count < max_retries:
                    state.retry_count += 1
                    
                    # Parameter adaptation
                    if state.retry_count == 2:
                        # On second retry, adapt parameters if possible
                        if action.type == "browser_search" or action.type == "browser_navigate":
                            await emit("retrying", f"Adapting parameters for {desc} (attempt {state.retry_count}/{max_retries})", icon="↺")
                            # Add some wait time before retrying browser actions
                            await asyncio.sleep(3.0)
                        elif action.type == "open_app_wait":
                            await asyncio.sleep(2.0) # Wait longer for app to open
                    
                    await emit("retrying", personality.narrate_retry(desc, state.retry_count),
                              {"action": atype, "attempt": state.retry_count}, icon="↺")
                    await asyncio.sleep(1.0 * state.retry_count)  # Exponential backoff
                    continue


                elif classification == FailureClassification.RECOVERABLE.value and state.replan_count < state.max_replans:
                    # Try replanning with different strategy
                    await emit("replanning", f"Strategy failed, replanning... (replan {state.replan_count + 1}/{state.max_replans})", 
                              {"reason": fail_msg, "action_index": action_index}, icon="🔄")
                    await self._emit_status(self.AgentStatus.REPLANNING, f"Replanning due to: {fail_msg}", event_queue)
                    
                    try:
                        failure_context = {
                            "step_index": action_index,
                            "action_type": atype,
                            "reason": fail_msg,
                            "classification": classification
                        }
                        # Use state.task which may include mid-task instructions
                        # (blocking I/O -> worker thread, same as plan_task).
                        new_actions = await asyncio.to_thread(
                            self.planner.replan, state.task, state, failure_context
                        )
                        actions = new_actions
                        # Replanning replaces the authoritative plan. Final
                        # verification must evaluate the replacement, not the
                        # plan that just failed.
                        plan = state.plan
                        action_index = 0
                        completed_indices = set()
                        state.completed_steps = []
                        state.retry_count = 0
                        state.replan_count += 1
                        state.last_replan_reason = fail_msg
                        continue
                    except Exception as e:
                        await emit("error", f"Replanning failed: {str(e)}", icon="✗")
                        state.errors.append(f"Replanning failed: {str(e)}")
                        break

                # ── CodeCore Self-Debugging Integration ─────────────────────────────
                # If the failure is code-related, attempt self-debugging via CodeCore
                if self._is_code_related_failure(atype, fail_msg, result):
                    await self._attempt_codecore_self_debug(state, action, result, observation, fail_msg, event_queue)

                elif classification == FailureClassification.FATAL.value or (not should_retry and state.retry_count >= max_retries):
                    # Fatal error or max retries exceeded
                    await emit("error", f"Fatal failure on step '{desc}': {fail_msg}. Task cannot continue.", icon="✗")
                    state.completion_status = "failed"
                    speak_text = personality.serious(
                        f"Task failed, sir. Critical step failed: {desc}. Error: {fail_msg}")
                    if self.executor._browser:
                        await self.executor.close_browser()
                    await emit(
                        "task_failed",
                        speak_text,
                        {
                            "status": "failed",
                            "completed_steps": len(state.completed_steps),
                            "total_steps": len(actions),
                            "errors": state.errors,
                        },
                        icon="✗"
                    )
                    return {
                        "status": "failed",
                        "task": task,
                        "speak": speak_text,
                        "plan": [a.description for a in plan.actions],
                        "completed_steps": state.completed_steps,
                        "errors": state.errors,
                    }
                else:
                    # Default: retry
                    if state.retry_count >= max_retries:
                        await emit("error", f"Max retries exceeded on step '{desc}'. Task cannot continue.", icon="✗")
                        state.completion_status = "failed"
                        if self.executor._browser:
                            await self.executor.close_browser()
                        return {
                            "status": "failed",
                            "task": task,
                            "speak": f"Task failed, sir. Max retries exceeded on step: {desc}.",
                            "errors": state.errors,
                        }
                    state.retry_count += 1
                    await emit("retrying", f"Retrying: {desc} (attempt {state.retry_count})", icon="↺")
                    await asyncio.sleep(1.0)
                    continue

        # ── Step 4: Check for incomplete steps (dependencies not met) ──────
        incomplete = [i for i in range(len(actions)) if i not in completed_indices and actions[i].type != "speak"]
        if incomplete:
            await emit("replanning", f"Some steps incomplete, attempting to resolve...", 
                      {"incomplete_steps": incomplete}, icon="🔄")
            # Try to execute remaining steps
            for idx in incomplete:
                action = actions[idx]
                if self._dependencies_satisfied(action, completed_indices, state):
                    # Execute this step
                    state.current_step = idx
                    await emit("step_started", f"Executing delayed step {idx + 1}: {action.description}", 
                              {"action": action.type, "step": idx + 1}, icon="→")
                    try:
                        result = await self.executor.execute(action, state)
                    except Exception as e:
                        result = {"status": "error", "message": f"Executor exception: {str(e)}"}
                    
                    state.action_outputs[idx] = result or {}
                    
                    browser = self.executor._browser
                    try:
                        observation = await self.observer.observe_after_action(action, result, state, browser)
                    except Exception as e:
                        observation = {"verified": False, "message": f"Observer error: {str(e)}"}
                    
                    verification = self.verifier.verify_action(action, result, observation)

                    # Log execution step
                    self._log_execution(idx + 1, len(actions), action, result or {}, observation or {}, verification or {})

                    if verification["verified"]:
                        state.completed_steps.append(idx)
                        completed_indices.add(idx)
                        state.observations.append(observation)
                        await emit("step_completed", f"✓ {action.description}", 
                                  {"action": action.type, "verified": True}, icon="✓")

        # ── Step 5: Final Outcome Verification ─────────────────────────────
        await emit("final_verification", "Verifying final outcome...", {"goal": state.interpreted_goal}, icon="🔍")
        
        final_verification = await self._verify_final_outcome(state, plan)
        state.final_outcome_verified = final_verification["verified"]
        state.final_outcome_data = final_verification

        if not final_verification["verified"]:
            # Final outcome not achieved - try to recover or report partial
            await emit("verification_failed", f"Final outcome not verified: {final_verification['message']}", 
                      final_verification, icon="✗")
            state.completion_status = "partial" if state.completed_steps else "failed"
            speak_text = final_verification.get("message", "Task could not be fully completed.")
        else:
            state.completion_status = "completed"
            await emit("verification_passed", "Final outcome verified successfully", final_verification, icon="✓")
            # Build final speak text if not set
            if not speak_text:
                completed = len(state.completed_steps)
                total = len([a for a in actions if a.type != "speak"])
                speak_text = f"Task complete, sir. {completed} of {total} steps executed successfully. {final_verification.get('summary', '')}"

        # Close browser if it was opened
        if self.executor._browser:
            await emit("observation", "Closing browser", icon="✓")
            await self.executor.close_browser()

        queued = list(getattr(state, "queued_tasks", []) or [])
        if queued:
            await emit("task_queued_summary",
                       f"Finished, sir — and {len(queued)} task(s) are queued next: {queued[0][:80]}",
                       {"queued": queued}, icon="⏳")

        await emit(
            "task_completed" if state.completion_status == "completed" else "task_partial",
            speak_text,
            {
                "status": state.completion_status,
                "completed_steps": len(state.completed_steps),
                "total_steps": len([a for a in actions if a.type != "speak"]),
                "errors": state.errors,
                "final_verification": final_verification,
                "queued": queued,
            },
            icon="✓" if state.completion_status == "completed" else "⚠"
        )

        # ── Phase 2: MEMORY UPDATE — bank the verified outcome ────────────
        self._memory_store_outcome(task, state.completion_status or "unknown",
                                   speak_text)

        return {
            "status": state.completion_status,
            "task": task,
            "speak": speak_text,
            "plan": [a.description for a in plan.actions],
            "completed_steps": state.completed_steps,
            "errors": state.errors,
            "final_verification": final_verification,
            "action_outputs": state.action_outputs,
            "queued": queued,
        }

    def _dependencies_satisfied(self, action: ActionSpec, completed_indices: Set[int], state: TaskState) -> bool:
        """Check if all dependencies for this action are satisfied."""
        for dep_idx in action.depends_on:
            if dep_idx not in completed_indices:
                return False
        return True

    @staticmethod
    def _should_skip_empty_source(state: TaskState, fail_msg: str) -> bool:
        """Skip a dead source only when usable evidence is already banked.
        Prevents one empty/JS-only/blocked page from failing a whole
        research task. Never skips when nothing has been gathered yet."""
        if "no meaningful content" not in (fail_msg or "").lower():
            return False
        banked = sum(len(s.get("text") or "") for s in (state.extracted_sources or []))
        return banked > 200

    @staticmethod
    def _collect_speak_evidence(state: TaskState, action=None) -> str:
        """Build the reply evidence for read-style actions (consume-once).

        Agentic replies carry a SHORT SUMMARY, not a raw dump: terminal
        output is analyzed (branch state, test counts, listings) and only
        the conclusion reaches the chat. Download/table paths stay as-is.
        Speak actions may request explicit evidence via
        `parameters["evidence"]`: calc | search | screenshot | artifact |
        folder | typed | sources. A user asking for "full output"/"verbose"
        still gets the raw text (capped). Returns "" when nothing is banked.
        """
        parts: List[str] = []
        requested = ""
        try:
            requested = (action.parameters.get("evidence", "") or "") if action else ""
        except Exception:
            requested = ""

        def _take(key: str) -> str:
            val = (state.get_context(key, "") or "")
            if isinstance(val, list):
                out = list(val)
                state.update_context(key, [])
                return out
            val = str(val).strip()
            state.update_context(key, "")
            return val

        if requested == "calc":
            calc = str(state.get_context("last_calc_result", "") or "").strip()
            if calc:
                parts.append(f"Result: {calc}.")
                state.update_context("last_calc_result", "")

        if requested in ("typed",):
            typed = str(state.get_context("last_typed_text", "") or "").strip()
            if typed:
                short = typed if len(typed) <= 100 else typed[:100].rstrip() + "…"
                parts.append(f'Text entered: "{short}".')
                state.update_context("last_typed_text", "")

        if requested in ("folder",):
            folder = str(state.get_context("last_folder_path", "") or "").strip()
            if folder:
                parts.append(f"Location: {folder}.")
                state.update_context("last_folder_path", "")

        if requested in ("screenshot",):
            shot = str(state.get_context("last_screenshot_path", "") or "").strip()
            if shot:
                parts.append(f"Screenshot saved to: {shot}.")
                state.update_context("last_screenshot_path", "")

        if requested in ("artifact",):
            paths = _take("artifact_paths")
            if paths:
                parts.append("Saved to: " + ", ".join(paths) + ".")

        if requested in ("search", "sources"):
            bank = state.extracted_sources if requested == "sources" else state.search_results
            titles = [str((s.get("title") or s.get("url") or "")).strip()
                      for s in (bank or [])][:3]
            titles = [t[:80] for t in titles if t]
            if titles:
                parts.append(("Sources: " if requested == "sources" else "Top results: ")
                             + "; ".join(titles) + ".")
        # Auto evidence (no tag needed): terminal summaries, downloads, tables.
        shell_out = (state.get_context("last_shell_output", "") or "").strip()
        if shell_out:
            task_l = (state.task or "").lower()
            if re.search(r"\bfull\b.*\boutput\b|\bverbose\b|\bshow\s+all\b|\bcomplete\s+output\b", task_l):
                raw = shell_out
                if len(raw) > 1500:
                    raw = raw[:1500].rstrip() + "\n…(truncated)"
                parts.append(raw)
            else:
                from backend.tools.terminal import summarize_output
                parts.append(summarize_output(
                    state.get_context("last_shell_command", ""),
                    shell_out,
                    int(state.get_context("last_shell_exit", 0) or 0)))
            state.update_context("last_shell_output", "")
            state.update_context("last_shell_command", "")
            state.update_context("last_shell_exit", "")
        dl_path = (state.get_context("last_download_path", "") or "").strip()
        if dl_path:
            parts.append(f"Saved to: {dl_path}")
            state.update_context("last_download_path", "")
        table_path = (state.get_context("last_table_path", "") or "").strip()
        if table_path:
            rows = state.get_context("last_table_rows", "")
            parts.append(f"Table saved to: {table_path}"
                         + (f" ({rows} rows)" if rows != "" else ""))
            state.update_context("last_table_path", "")
            state.update_context("last_table_rows", "")
        return "\n".join(parts).strip()

    async def _verify_final_outcome(self, state: TaskState, plan: Plan) -> Dict[str, Any]:
        """Verify the final outcome matches the user's requested goal."""
        goal = state.interpreted_goal
        verification_criteria = plan.final_outcome_verification
        criteria_type = verification_criteria.get("type", "verification")
        criteria_list = verification_criteria.get("criteria", [])
        
        results = {
            "verified": False,
            "message": "",
            "details": {},
            "summary": ""
        }
        
        if criteria_type == "document":
            # Verify document was created and has content
            doc_path = None
            for idx, output in state.action_outputs.items():
                if output and output.get("path") and output.get("path", "").endswith(".docx"):
                    doc_path = output["path"]
                    break
            
            if not doc_path:
                # Check state for created document
                for idx in state.completed_steps:
                    action = plan.actions[idx]
                    if action.type == "create_docx":
                        doc_path = action.parameters.get("path", "")
                        break
            
            if doc_path:
                import os
                if os.path.isfile(doc_path):
                    try:
                        from docx import Document
                        doc = Document(doc_path)
                        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                        document_text = "\n".join(paragraphs).lower()
                        requested_title = next(
                            (a.parameters.get("title", "") for a in plan.actions if a.type == "create_docx"),
                            ""
                        ).lower()
                        title_terms = [term for term in requested_title.split() if len(term) > 3 and term not in {"research", "report", "document"}]
                        has_requested_topic = not title_terms or any(term in document_text for term in title_terms)
                        has_research_evidence = not state.extracted_sources or any(
                            source.get("url", "").lower() in document_text
                            for source in state.extracted_sources if source.get("url")
                        )
                        if paragraphs and has_requested_topic and has_research_evidence:
                            results["verified"] = True
                            results["message"] = f"Document created and verified: {len(paragraphs)} paragraphs"
                            results["details"] = {"path": doc_path, "paragraph_count": len(paragraphs), "topic_verified": has_requested_topic, "sources_verified": has_research_evidence}
                            results["summary"] = f"Document saved to {doc_path}"
                        elif not has_requested_topic:
                            results["message"] = "Document exists but does not contain the requested topic"
                        elif not has_research_evidence:
                            results["message"] = "Document exists but does not include extracted source evidence"
                        else:
                            results["verified"] = False
                            results["message"] = "Document exists but has no content"
                    except Exception as e:
                        results["verified"] = False
                        results["message"] = f"Document read error: {str(e)}"
                else:
                    results["verified"] = False
                    results["message"] = f"Document not found at {doc_path}"
            else:
                results["verified"] = False
                results["message"] = "No document creation action found in plan"
        
        elif criteria_type == "verification":
            # Generic verification - check if all critical steps completed
            critical_steps = [i for i, a in enumerate(plan.actions) if a.is_critical and a.type != "speak"]
            completed_critical = [i for i in critical_steps if i in state.completed_steps]
            
            if len(completed_critical) == len(critical_steps):
                results["verified"] = True
                results["message"] = "All critical steps completed successfully"
                results["summary"] = f"{len(completed_critical)} critical steps verified"
            else:
                results["verified"] = False
                results["message"] = f"Only {len(completed_critical)}/{len(critical_steps)} critical steps completed"
        
        else:
            # Default: check if any steps completed
            if state.completed_steps:
                results["verified"] = True
                results["message"] = f"{len(state.completed_steps)} steps completed"
            else:
                results["verified"] = False
                results["message"] = "No steps completed"
        
        return results


    def _log_execution(self, step_idx: int, total_steps: int, action: ActionSpec, result: dict, observation: dict, verification: dict):
        import datetime
        import os
        log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'execution.log')
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        status = result.get('status', 'unknown') if result else 'none'
        obs_msg = observation.get('message', '') if hasattr(observation, 'get') else str(observation)
        v_passed = verification.get('verified', False) if hasattr(verification, 'get') else False
        v_msg = verification.get('message', '') if hasattr(verification, 'get') else ''
        
        log_entry = (
            f"[{ts}] STEP {step_idx}/{total_steps} | Action: {action.type} | Result: {status}\n"
            f"[{ts}] OBSERVATION | Details: {obs_msg}\n"
            f"[{ts}] VERIFICATION | Passed: {v_passed} | Message: {v_msg}\n"
        )
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')

    async def resume_after_human(self, state: TaskState, resolution: Dict[str, Any]) -> Dict[str, Any]:
        """Resume execution after human intervention.

        Carries a clarification answer (if any) into state so the waiting
        question loop can fold it back into the task."""
        try:
            answer = ((resolution or {}).get("answer", "") or "").strip()
        except Exception:
            answer = ""
        if answer:
            state.update_context("clarification_answer", answer)
        state.human_verification_resolved = True
        state.human_verification_required = False
        state.waiting_for_user = False
        # The main loop will continue from the paused action
        return {"status": "resumed", "resolution": resolution}

    async def _ask_clarification(self, task: str, state: TaskState,
                                 question: Dict[str, Any], emit,
                                 event_queue=None) -> Optional[str]:
        """Ask one follow-up question before planning; returns the enriched
        task, or None when interrupted mid-question."""
        state.human_verification_required = True
        state.human_verification_message = question["question"]
        state.human_verification_action_index = -1  # pre-plan marker
        state.human_verification_context = {
            "kind": "clarification",
            "question": question["question"],
            "options": question.get("options", []),
            "hint": question.get("hint", ""),
        }
        state.waiting_for_user = True
        await emit("clarification_required", question["question"],
                   {"question": question["question"],
                    "options": question.get("options", []),
                    "kind": "clarification"},
                   icon="❓")
        while state.waiting_for_user and state.human_verification_action_index == -1:
            if await self._check_interrupt(event_queue):
                state.waiting_for_user = False
                return None
            await asyncio.sleep(0.5)
        await emit("resuming", "Got it, sir — carrying on.",
                   {"action_index": -1}, icon="▶")
        state.waiting_for_user = False
        state.human_verification_resolved = False
        state.clarification_done = True
        answer = (state.get_context("clarification_answer", "") or "").strip()
        state.update_context("clarification_answer", "")
        if not answer:
            return task  # best effort with the original prompt
        return clarify.apply_answer(task, answer)

    # ─────────────────────────────────────────────────────────────────────────
    # CodeCore Self-Debugging Integration
    # ─────────────────────────────────────────────────────────────────────────

    def _is_code_related_failure(self, action_type: str, error_message: str, result: dict) -> bool:
        """Determine if a failure is code-related and suitable for CodeCore self-debugging."""
        code_related_actions = {
            "code_audit", "code_fix", "code_test", "code_preview_fix", 
            "code_apply_fix", "code_process_file", "generate_image"
        }
        
        if action_type in code_related_actions:
            return True
        
        # Check error message for code-related patterns
        error_lower = error_message.lower()
        code_keywords = [
            "syntax error", "indentation", "undefined", "attribute error",
            "import error", "module not found", "name error", "type error",
            "compilation error", "py_compile", "ast.parse", "traceback",
            "nemotron", "nvidia", "nvidia_api_key", "huggingface"
        ]
        
        return any(keyword in error_lower for keyword in code_keywords)

    async def _attempt_codecore_self_debug(self, state: TaskState, action: ActionSpec, 
                                            result: dict, observation: dict, 
                                            error_message: str, event_queue: asyncio.Queue) -> bool:
        """
        Attempt to self-debug a code-related failure using CodeCore.
        Returns True if debugging was attempted (regardless of success).
        """
        try:
            from code_core import preview_file_fix, apply_file_fix, audit_codebase
            
            # Try to identify the problematic file from the error
            target_file = self._extract_file_from_error(error_message, action)
            
            if not target_file:
                return False
            
            await emit("codecore_debug", f"Attempting self-debug via CodeCore for {target_file}", 
                      {"file": target_file, "error": error_message}, icon="🔧")
            
            # Step 1: Preview the fix
            try:
                preview = preview_file_fix(target_file, error_message)
            except Exception as e:
                await emit("codecore_debug", f"CodeCore preview failed: {str(e)}", icon="⚠")
                return False
            
            if preview.get("status") != "success":
                await emit("codecore_debug", f"CodeCore could not generate fix: {preview.get('message', 'Unknown error')}", icon="⚠")
                return False
            
            # Step 2: Apply the fix with validation
            try:
                app_res = apply_file_fix(target_file, preview.get("proposed_content", ""))
            except Exception as e:
                await emit("codecore_debug", f"CodeCore apply failed: {str(e)}", icon="⚠")
                return False
            
            if app_res.get("status") == "success":
                await emit("codecore_debug", f"CodeCore successfully fixed {target_file}: {app_res.get('message', '')}", icon="✓")
                # Retry the failed action
                return True
            else:
                await emit("codecore_debug", f"CodeCore fix validation failed: {app_res.get('message', 'Validation error')}", icon="⚠")
                return False
                
        except Exception as e:
            await emit("codecore_debug", f"CodeCore self-debug error: {str(e)}", icon="⚠")
            return False

    def _extract_file_from_error(self, error_message: str, action: ActionSpec) -> Optional[str]:
        """Extract the target file path from an error message or action parameters."""
        import re
        
        # Check action parameters first
        if action.parameters.get("target") and action.parameters["target"].endswith(".py"):
            return action.parameters["target"]
        if action.parameters.get("filepath") and action.parameters["filepath"].endswith(".py"):
            return action.parameters["filepath"]
        
        # Try to extract from traceback
        tb_match = re.search(r'File "([^"]+\.py)"', error_message)
        if tb_match:
            return tb_match.group(1)
        
        # Check for common patterns
        file_match = re.search(r'([a-zA-Z0-9_/\-\.]+\.py)', error_message)
        if file_match:
            return file_match.group(1)
        
        return None
        return {"status": "resumed", "resolution": resolution}
