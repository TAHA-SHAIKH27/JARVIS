"""Integration test for JARVIS Phase 1 persistent memory storage and restart recall.

Tests saving a memory via the /api/command UI bridge, simulating a process restart,
and successfully recalling the memory with a natural question like "What's my favorite color?".
"""
import json
import os
import subprocess
import sys
import unittest
from starlette.testclient import TestClient

import main
from backend.agent import phase1_memory, phase1_runtime


class TestMemoryRestartIntegration(unittest.TestCase):
    def setUp(self):
        self.data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend", "data"))
        self.memory_path = os.path.join(self.data_dir, "persistent_memory.json")
        self.session_path = os.path.join(self.data_dir, "current_session_memory.json")
        phase1_memory.clear()
        phase1_runtime.runtime.conversation.clear()
        # Install command bridge if not already running
        phase1_runtime.install_command_context_bridge()
        self.client = TestClient(main.app)

    def tearDown(self):
        phase1_memory.clear()
        phase1_runtime.runtime.conversation.clear()

    def test_save_memory_restart_and_recall(self):
        # 1. Save explicit memory via the /api/command UI bridge
        response = self.client.post("/api/command", json={"prompt": "Remember my favorite color is blue"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("memory_saved", False))
        self.assertIn("favorite color is blue", data.get("speak", "").lower())

        # 2. Verify file persisted to disk with structured fields
        self.assertTrue(os.path.exists(self.memory_path))
        with open(self.memory_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        self.assertEqual(len(items), 1)
        mem = items[0]
        self.assertEqual(mem["key"], "favorite color")
        self.assertEqual(mem["value"], "blue")
        self.assertEqual(mem["text"], "favorite color: blue")
        self.assertIn("favorite color is blue", mem["source_text"].lower())

        # 3. Prevent duplicate memories
        dup_response = self.client.post("/api/command", json={"prompt": "Remember my favorite color is blue"})
        self.assertEqual(dup_response.status_code, 200)
        with open(self.memory_path, "r", encoding="utf-8") as f:
            items_after_dup = json.load(f)
        self.assertEqual(len(items_after_dup), 1)

        # 4. Simulate JARVIS restart via a fresh Python subprocess
        code = """
import json, sys
from starlette.testclient import TestClient
import main
from backend.agent import phase1_runtime
phase1_runtime.install_command_context_bridge()

client = TestClient(main.app)
response = client.post("/api/command", json={"prompt": "What's my favorite color?"})
data = response.json()
print(json.dumps(data))
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            check=True
        )

        output_json = json.loads(proc.stdout.strip().splitlines()[-1])
        speak_text = output_json.get("speak", "")
        self.assertIn("blue", speak_text.lower())
        self.assertTrue("color" in speak_text.lower() or "colour" in speak_text.lower())

        # 5. Test clear memory reset behavior
        clear_response = self.client.post("/api/command", json={"prompt": "clear memory"})
        self.assertEqual(clear_response.status_code, 200)
        with open(self.memory_path, "r", encoding="utf-8") as f:
            items_after_clear = json.load(f)
        self.assertEqual(len(items_after_clear), 0)


if __name__ == "__main__":
    unittest.main()
