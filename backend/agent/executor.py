import asyncio
import json
from typing import Any, Dict, Optional, List

from backend.agent.state import TaskState
from backend.agent.registry import ToolRegistry


class Executor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute(self, action: Dict[str, Any], state: TaskState) -> Optional[Dict[str, Any]]:
        """Execute a single action and return the result, or None if the action type is not recognized."""
        action_type = action.get("type", "")

        # Log the action to tool history
        state.tool_history.append(action.copy())

        # Handle known action types
        if action_type == "speak":
            return {"status": "success", "message": action.get("text", "")}

        elif action_type == "open_app":
            app_name = action.get("app_name", "")
            from system_ops import open_application
            return open_application(app_name)

        elif action_type == "close_app":
            app_name = action.get("app_name", "")
            from system_ops import close_application
            return close_application(app_name)

        elif action_type == "launch_app":
            app_name = action.get("app_name", "")
            from system_ops import launch_any_app
            return launch_any_app(app_name)

        elif action_type == "shutdown":
            delay = int(action.get("delay_seconds", 0))
            from system_ops import shutdown_pc
            return shutdown_pc(delay)

        elif action_type == "restart":
            delay = int(action.get("delay_seconds", 0))
            from system_ops import restart_pc
            return restart_pc(delay)

        elif action_type == "cancel_shutdown":
            from system_ops import cancel_shutdown
            return cancel_shutdown()

        elif action_type == "sleep":
            from system_ops import sleep_pc
            return sleep_pc()

        elif action_type == "lock_screen":
            from system_ops import lock_screen
            return lock_screen()

        elif action_type == "volume_up":
            from system_ops import adjust_volume
            return adjust_volume("up")

        elif action_type == "volume_down":
            from system_ops import adjust_volume
            return adjust_volume("down")

        elif action_type == "mute_volume":
            from system_ops import adjust_volume
            return adjust_volume("mute")

        elif action_type == "play_pause":
            from system_ops import media_control
            return media_control("play")

        elif action_type == "next_track":
            from system_ops import media_control
            return media_control("next")

        elif action_type == "prev_track":
            from system_ops import media_control
            return media_control("prev")

        elif action_type == "search_web":
            query = action.get("query", "")
            from system_ops import search_web
            return search_web(query)

        elif action_type == "weather":
            city = action.get("city", "London")
            from system_ops import get_weather
            return get_weather(city)

        elif action_type == "battery":
            from system_ops import get_battery_info
            return get_battery_info()

        elif action_type == "network_info":
            from system_ops import get_network_info
            return get_network_info()

        elif action_type == "datetime_info":
            from system_ops import get_datetime_info
            return get_datetime_info()

        elif action_type == "take_screenshot":
            from system_ops import take_screenshot
            return take_screenshot()

        elif action_type == "show_stats":
            from system_ops import get_system_stats
            return get_system_stats()

        elif action_type == "create_folder":
            folder_name = action.get("folder_name", "")
            from system_ops import create_folder
            return create_folder(folder_name)

        elif action_type == "create_word_doc":
            filename = action.get("filename", "")
            content = action.get("content", "")
            from system_ops import create_word_document
            return create_word_document(filename, content)

        elif action_type == "check_pc_health":
            from system_ops import check_pc_health
            return check_pc_health()

        elif action_type == "clipboard_read":
            from system_ops import get_clipboard
            return get_clipboard()

        elif action_type == "clipboard_write":
            text = action.get("text", "")
            from system_ops import set_clipboard
            return set_clipboard(text)

        elif action_type == "open_url":
            url = action.get("url", "")
            from system_ops import open_url as open_url_func
            return open_url_func(url)

        elif action_type == "generate_image":
            img_prompt = action.get("prompt", "")
            hf_key = ""
            from main import load_config
            config = load_config()
            hf_key = config.get("huggingface_api_key", "")
            from system_ops import generate_image_huggingface
            return generate_image_huggingface(img_prompt, hf_key, action.get("save_name", ""))

        elif action_type == "save_image":
            save_name = action.get("save_name", "")
            destination = action.get("destination", "desktop")
            from system_ops import save_generated_image
            return save_generated_image(save_name, destination)

        elif action_type == "add_note":
            note_text = action.get("text", "")
            from main import _load_json_list, _save_json_list, NOTES_FILE
            from datetime import datetime
            notes = _load_json_list(NOTES_FILE)
            note = {"id": int(datetime.now().timestamp() * 1000), "text": note_text,
                    "time": datetime.now().strftime("%b %d %H:%M")}
            notes.append(note)
            _save_json_list(NOTES_FILE, notes)
            return {"status": "success", "message": "Note added"}

        elif action_type == "add_todo":
            todo_text = action.get("text", "")
            from main import _load_json_list, _save_json_list, TODOS_FILE
            from datetime import datetime
            todos = _load_json_list(TODOS_FILE)
            todo = {"id": int(datetime.now().timestamp() * 1000), "text": todo_text, "done": False}
            todos.append(todo)
            _save_json_list(TODOS_FILE, todos)
            return {"status": "success", "message": "Todo added"}

        elif action_type == "set_timer":
            seconds = int(action.get("seconds", 60))
            label = action.get("label", "Timer")
            return {"status": "success", "message": f"Timer set for {seconds} seconds", "timer_data": {"seconds": seconds, "label": label}}

        elif action_type == "open_url_new":
            url = action.get("url", "")
            from system_ops import open_url
            return open_url(url)

        elif action_type == "phone_devices":
            from phone_control import list_devices
            return list_devices()

        elif action_type == "phone_mirror":
            from phone_control import start_mirror
            return start_mirror()

        elif action_type == "phone_screenshot":
            from phone_control import screenshot_as_base64
            return screenshot_as_base64()

        elif action_type == "phone_tap":
            x = action.get("x", 0)
            y = action.get("y", 0)
            from phone_control import tap
            return tap(x, y)

        elif action_type == "phone_swipe":
            x1 = action.get("x1", 0)
            y1 = action.get("y1", 0)
            x2 = action.get("x2", 0)
            y2 = action.get("y2", 0)
            duration_ms = int(action.get("duration_ms", 300))
            from phone_control import swipe
            return swipe(x1, y1, x2, y2, duration_ms)

        elif action_type == "phone_text":
            text = action.get("text", "")
            from phone_control import input_text
            return input_text(text)

        elif action_type == "phone_key":
            key = action.get("key", "")
            from phone_control import press_key
            return press_key(key)

        elif action_type == "phone_launch_app":
            package = action.get("package", "")
            from phone_control import launch_app
            return launch_app(package)

        elif action_type == "phone_unlock":
            pin = action.get("pin")
            from phone_control import unlock_phone
            return unlock_phone(pin)

        elif action_type == "phone_test_pin_tap":
            digit = action.get("digit", "")
            from phone_control import test_pin_digit_tap
            return test_pin_digit_tap(digit)

        elif action_type == "send_whatsapp":
            contact = action.get("contact", "")
            message = action.get("message", "")
            from whatsapp_ops import send_whatsapp_message
            return send_whatsapp_message(contact, message)

        elif action_type == "send_whatsapp_phone":
            contact = action.get("contact", "")
            message = action.get("message", "")
            from whatsapp_ops import send_whatsapp_message_via_phone
            return send_whatsapp_message_via_phone(contact, message)

        elif action_type == "add_whatsapp_contact":
            name = action.get("name", "")
            phone = action.get("phone", "")
            from whatsapp_ops import add_contact
            return add_contact(name, phone)

        elif action_type == "clear_history":
            import agent
            agent.conversation_history.clear()
            return {"status": "success", "message": "Conversation history cleared"}

        elif action_type == "generate_image_huggingface":
            img_prompt = action.get("prompt", "")
            hf_key = action.get("hf_key", "")
            save_name = action.get("save_name", "")
            from system_ops import generate_image_huggingface
            return generate_image_huggingface(img_prompt, hf_key, save_name)

        else:
            # Unknown action type - return error
            return {"status": "error", "message": f"Unknown action type: {action_type}"}

    async def execute_sequence(self, actions: List[Dict[str, Any]], state: TaskState) -> List[Dict[str, Any]]:
        """Execute a sequence of actions and return results."""
        results = []
        for action in actions:
            result = await self.execute(action, state)
            results.append(result)
            # Stop on error if no retry
            if result and result.get("status") == "error" and not action.get("retry", False):
                break
        return results