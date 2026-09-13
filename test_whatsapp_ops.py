"""Unit and integration tests for JARVIS WhatsApp operations and observer verification."""
import unittest
from unittest.mock import MagicMock, patch

import whatsapp_ops
from backend.agent.observer import Observer
from backend.agent.state import ActionSpec


class TestWhatsAppOps(unittest.TestCase):
    def test_empty_message_returns_error(self):
        res = whatsapp_ops.send_whatsapp_message("Mom", "")
        self.assertEqual(res["status"], "error")
        self.assertIn("No message text", res["message"])

        res_phone = whatsapp_ops.send_whatsapp_message_via_phone("+919876543210", "   ")
        self.assertEqual(res_phone["status"], "error")
        self.assertIn("No message text", res_phone["message"])

    def test_phone_resolution_without_country_code(self):
        res = whatsapp_ops._resolve_phone("9876543210")
        # 10 digits without + should prompt for country code
        self.assertEqual(res["status"], "error")
        self.assertIn("country code", res["message"])

    def test_phone_resolution_with_country_code(self):
        res = whatsapp_ops._resolve_phone("+91 98765-43210")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_phone"])
        self.assertEqual(res["phone"], "+919876543210")

    def test_name_resolution(self):
        res = whatsapp_ops._resolve_phone("John Doe")
        self.assertEqual(res["status"], "success")
        self.assertFalse(res["is_phone"])
        self.assertEqual(res["display_name"], "John Doe")

    @patch("whatsapp_ops._type_and_send_message")
    @patch("whatsapp_ops._search_whatsapp_contact")
    def test_send_whatsapp_message_by_name_success(self, mock_search, mock_type_send):
        mock_search.return_value = {"status": "success", "display_name": "Alice"}
        mock_type_send.return_value = {"status": "success", "message": "Message sent to Alice on WhatsApp, sir."}

        res = whatsapp_ops.send_whatsapp_message("Alice", "Hello Alice")
        self.assertEqual(res["status"], "success")
        self.assertIn("Message sent to Alice", res["message"])
        mock_search.assert_called_once_with("Alice")
        mock_type_send.assert_called_once_with("Hello Alice", "Alice", auto_send=True)

    @patch("whatsapp_ops._search_whatsapp_contact")
    def test_send_whatsapp_message_search_failure(self, mock_search):
        mock_search.return_value = {
            "status": "error",
            "message": "I opened WhatsApp but couldn't search for and open chat with 'Bob': timeout",
        }

        res = whatsapp_ops.send_whatsapp_message("Bob", "Hello Bob")
        self.assertEqual(res["status"], "error")
        self.assertIn("couldn't search", res["message"])

    @patch("whatsapp_ops._type_and_send_message")
    @patch("os.startfile")
    def test_send_whatsapp_message_by_phone_success(self, mock_startfile, mock_type_send):
        mock_type_send.return_value = {"status": "success", "message": "Message sent to +1234567890 on WhatsApp, sir."}

        res = whatsapp_ops.send_whatsapp_message("+1234567890", "Test message")
        self.assertEqual(res["status"], "success")
        mock_startfile.assert_called_once_with("whatsapp://send?phone=1234567890")
        mock_type_send.assert_called_once_with("Test message", "+1234567890", auto_send=True)

    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    @patch("whatsapp_ops._bring_whatsapp_to_foreground")
    def test_type_and_send_message_direct_success(self, mock_fg, mock_copy, mock_hotkey, mock_press):
        mock_fg.return_value = True

        res = whatsapp_ops._type_and_send_message("Hello from test", "John", auto_send=True)
        self.assertEqual(res["status"], "success")
        self.assertIn("Message sent to John", res["message"])
        mock_copy.assert_called_once_with("Hello from test")
        mock_hotkey.assert_called_once_with("ctrl", "v")
        mock_press.assert_called_once_with("enter")

    @patch("whatsapp_ops._bring_whatsapp_to_foreground")
    def test_type_and_send_message_exception_returns_error(self, mock_fg):
        mock_fg.side_effect = RuntimeError("Display driver error")

        res = whatsapp_ops._type_and_send_message("Hello", "John", auto_send=True)
        self.assertEqual(res["status"], "error")
        self.assertIn("Failed while typing or sending", res["message"])


class TestWhatsAppObserverIntegration(unittest.TestCase):
    def setUp(self):
        self.observer = Observer()

    def test_observer_verifies_whatsapp_success(self):
        import asyncio
        from backend.agent.state import TaskState
        action = ActionSpec(type="send_whatsapp", description="Send WhatsApp message", parameters={"contact": "Alice", "message": "Hi"})
        result = {"status": "success", "message": "Message sent to Alice on WhatsApp, sir."}

        obs = asyncio.run(self.observer.observe_after_action(action, result, TaskState()))
        self.assertTrue(obs["verified"])
        self.assertEqual(obs["classification"], "success")
        self.assertIn("Message sent to Alice", obs["message"])

    def test_observer_rejects_whatsapp_failure(self):
        import asyncio
        from backend.agent.state import TaskState
        action = ActionSpec(type="send_whatsapp", description="Send WhatsApp message", parameters={"contact": "Bob", "message": "Hi"})
        result = {"status": "error", "message": "Could not launch WhatsApp."}

        obs = asyncio.run(self.observer.observe_after_action(action, result, TaskState()))
        self.assertFalse(obs["verified"])
        self.assertEqual(obs["classification"], "retryable")
        self.assertIn("Could not launch WhatsApp", obs["message"])

    def test_observer_rejects_whatsapp_none_result(self):
        import asyncio
        from backend.agent.state import TaskState
        action = ActionSpec(type="send_whatsapp", description="Send WhatsApp message", parameters={"contact": "Bob", "message": "Hi"})

        obs = asyncio.run(self.observer.observe_after_action(action, None, TaskState()))
        self.assertFalse(obs["verified"])
        self.assertEqual(obs["classification"], "retryable")


if __name__ == "__main__":
    unittest.main()
