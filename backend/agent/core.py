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
"""
import asyncio
import json
import time
import traceback
from typing import Any, Dict, List, Optional, Set

from backend.agent.state import TaskState, ActionSpec, Plan, TaskType, FailureClassification
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
        plan_desc = [a.description for a in actions]
        await emit("plan_created", f"Plan created with {len(actions)} steps", {"steps": plan_desc}, icon="📋")

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
                speak_text = action.parameters.get("text", "")
                state.completed_steps.append(action_index)
                completed_indices.add(action_index)
                action_index += 1
                continue

            # Check if waiting for human
            if state.waiting_for_user and state.human_verification_action_index == action_index:
                await emit("waiting_for_user", state.human_verification_message, 
                          {"action_index": action_index, "context": state.human_verification_context}, icon="⏳")
                # Wait for human to resolve
                while state.waiting_for_user and state.human_verification_action_index == action_index:
                    await asyncio.sleep(1.0)
                if state.human_verification_resolved:
                    await emit("resuming", "Human intervention resolved, resuming execution", {"action_index": action_index}, icon="▶")
                    state.waiting_for_user = False
                    state.human_verification_resolved = False
                    # Continue with this action
                else:
                    # Human didn't resolve, treat as failure
                    state.errors.append(f"Human intervention not resolved for step {action_index}")
                    break

            state.current_step = action_index
            await emit("step_started", f"Executing step {action_index + 1}/{len(actions)}: {desc}", 
                      {"action": atype, "step": action_index + 1, "total": len(actions)}, icon="→")

            # Execute
            await emit("tool_started", f"Starting tool: {atype}", {"action": atype, "parameters": action.parameters}, icon="⚙")
            try:
                result = await self.executor.execute(action, state)
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
                await emit(
                    "step_completed",
                    f"✓ {desc}: {observation.get('message', '')}",
                    {"action": atype, "verified": True, "observation": observation, "step": action_index + 1},
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
                    await emit("human_intervention_required", fail_msg, 
                              {"action_index": action_index, "classification": classification}, icon="👤")
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
                    
                    await emit("retrying", f"Retrying: {desc} (attempt {state.retry_count}/{max_retries})", 
                              {"action": atype, "attempt": state.retry_count}, icon="↺")
                    await asyncio.sleep(1.0 * state.retry_count)  # Exponential backoff
                    continue


                elif classification == FailureClassification.RECOVERABLE.value and state.replan_count < state.max_replans:
                    # Try replanning with different strategy
                    await emit("replanning", f"Strategy failed, replanning... (replan {state.replan_count + 1}/{state.max_replans})", 
                              {"reason": fail_msg, "action_index": action_index}, icon="🔄")
                    
                    try:
                        failure_context = {
                            "step_index": action_index,
                            "action_type": atype,
                            "reason": fail_msg,
                            "classification": classification
                        }
                        new_actions = self.planner.replan(task, state, failure_context)
                        actions = new_actions
                        action_index = 0
                        completed_indices = set()
                        state.completed_steps = []
                        state.retry_count = 0
                        continue
                    except Exception as e:
                        await emit("error", f"Replanning failed: {str(e)}", icon="✗")
                        state.errors.append(f"Replanning failed: {str(e)}")
                        break

                elif classification == FailureClassification.FATAL.value or (not should_retry and state.retry_count >= max_retries):
                    # Fatal error or max retries exceeded
                    await emit("error", f"Fatal failure on step '{desc}': {fail_msg}. Task cannot continue.", icon="✗")
                    state.completion_status = "failed"
                    speak_text = f"Task failed, sir. Critical step failed: {desc}. Error: {fail_msg}"
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
            self._log_execution(action_index + 1, len(actions), action, result or {}, observation or {}, verification or {})
            
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

        await emit(
            "task_completed" if state.completion_status == "completed" else "task_partial",
            speak_text,
            {
                "status": state.completion_status,
                "completed_steps": len(state.completed_steps),
                "total_steps": len([a for a in actions if a.type != "speak"]),
                "errors": state.errors,
                "final_verification": final_verification,
            },
            icon="✓" if state.completion_status == "completed" else "⚠"
        )

        return {
            "status": state.completion_status,
            "task": task,
            "speak": speak_text,
            "plan": [a.description for a in plan.actions],
            "completed_steps": state.completed_steps,
            "errors": state.errors,
            "final_verification": final_verification,
            "action_outputs": state.action_outputs,
        }

    def _dependencies_satisfied(self, action: ActionSpec, completed_indices: Set[int], state: TaskState) -> bool:
        """Check if all dependencies for this action are satisfied."""
        for dep_idx in action.depends_on:
            if dep_idx not in completed_indices:
                return False
        return True

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
                        if paragraphs:
                            results["verified"] = True
                            results["message"] = f"Document created and verified: {len(paragraphs)} paragraphs"
                            results["details"] = {"path": doc_path, "paragraph_count": len(paragraphs)}
                            results["summary"] = f"Document saved to {doc_path}"
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
        log_dir = 'C:/Users/taha/OneDrive/Desktop/J.A.R.V.I.S. (Claude)/backend/logs'
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
        """Resume execution after human intervention."""
        state.human_verification_resolved = True
        state.human_verification_required = False
        state.waiting_for_user = False
        # The main loop will continue from the paused action
        return {"status": "resumed", "resolution": resolution}