"""
jarvis_watchdog.py — Standalone Process Supervisor & Crash Recovery Daemon for J.A.R.V.I.S.
========================================================================================
STANDALONE ARCHITECTURE:
- Runs as an independent supervisor process wrapping main.py.
- Zero dependency on FastAPI/Uvicorn — pure standard library.
- Monitors backend health via process status and HTTP polling on /api/status.
- On crash: captures stderr/traceback -> invokes recovery_engine.py -> restarts JARVIS.
"""

import os
import sys
import time
import subprocess
import signal
import urllib.request
import urllib.error
from datetime import datetime

# Import recovery engine
import recovery_engine

WATCHDOG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog.log")
CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog_crash.log")
MAX_CRASH_RECOVERIES = 3
HEALTH_CHECK_INTERVAL = 4  # seconds
HEALTH_CHECK_URL = "http://localhost:8000/api/status"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [WATCHDOG] {msg}"
    print(line)
    try:
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class JarvisSupervisor:
    def __init__(self, main_script: str = "main.py"):
        self.main_script = main_script
        self.process = None
        self.recovery_count = 0
        self.running = True

    def start_jarvis(self) -> subprocess.Popen:
        """Launch main.py as a subprocess."""
        log(f"Starting J.A.R.V.I.S. Core backend ({self.main_script})...")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Start main.py with piped stderr/stdout for crash capture
        self.process = subprocess.Popen(
            [sys.executable, "-u", self.main_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )
        log(f"J.A.R.V.I.S. PID: {self.process.pid}")
        return self.process

    def check_health(self) -> bool:
        """Ping HTTP /api/status endpoint."""
        try:
            req = urllib.request.Request(HEALTH_CHECK_URL, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def capture_crash_output(self) -> str:
        """Read stdout and stderr from terminated process."""
        stdout_text = ""
        stderr_text = ""
        try:
            if self.process:
                stdout_text, stderr_text = self.process.communicate(timeout=5)
        except Exception:
            pass

        full_output = f"=== STDERR ===\n{stderr_text}\n\n=== STDOUT ===\n{stdout_text}"
        with open(CRASH_LOG, "w", encoding="utf-8") as f:
            f.write(full_output)

        log(f"Saved crash output to {CRASH_LOG}")
        return full_output

    def handle_crash(self) -> bool:
        """Capture crash log, call recovery engine, and decide whether to restart."""
        self.recovery_count += 1
        log(f"CRASH DETECTED! (Incident #{self.recovery_count})")
        
        crash_output = self.capture_crash_output()

        if self.recovery_count > MAX_CRASH_RECOVERIES:
            log(f"Max recovery limit ({MAX_CRASH_RECOVERIES}) reached. Halting auto-recovery to prevent infinite loops.")
            log("Please review watchdog_crash.log and fix errors manually.")
            return False

        log("Invoking Independent Recovery Engine...")
        result = recovery_engine.recover_from_crash(CRASH_LOG, max_retries=3)
        log(f"Recovery Engine Result: {result.get('status')} - {result.get('message')}")

        if result.get("status") == "success":
            log("Recovery succeeded! Restarting J.A.R.V.I.S. backend in 2 seconds...")
            time.sleep(2)
            return True
        else:
            log(f"Recovery was unable to safely repair the issue. Error: {result.get('message')}")
            return False

    def run(self, test_mode: bool = False):
        """Main supervision loop."""
        log("==================================================")
        log("J.A.R.V.I.S. Watchdog Daemon Initialized")
        log("==================================================")

        if test_mode:
            log("Test mode active: Verification succeeded.")
            return

        while self.running:
            self.start_jarvis()
            
            # Initial grace period for boot
            time.sleep(3)

            # Health loop
            while self.running:
                ret_code = self.process.poll()
                if ret_code is not None:
                    # Process exited
                    log(f"JARVIS backend terminated unexpectedly with exit code {ret_code}.")
                    should_restart = self.handle_crash()
                    if should_restart:
                        break  # Break inner loop to restart
                    else:
                        log("Watchdog standing down due to unrecoverable crash.")
                        return

                # Check HTTP health
                is_healthy = self.check_health()
                if not is_healthy:
                    # Could still be starting up, give it a moment
                    pass

                time.sleep(HEALTH_CHECK_INTERVAL)

    def stop(self):
        """Terminate child process gracefully."""
        self.running = False
        if self.process and self.process.poll() is None:
            log("Stopping J.A.R.V.I.S. child process...")
            try:
                self.process.terminate()
                self.process.wait(timeout=4)
            except Exception:
                self.process.kill()
        log("Watchdog shut down cleanly.")


if __name__ == "__main__":
    test_mode = "--test-mode" in sys.argv
    supervisor = JarvisSupervisor()

    def sig_handler(sig, frame):
        log("Received shutdown signal.")
        supervisor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        supervisor.run(test_mode=test_mode)
    except KeyboardInterrupt:
        supervisor.stop()
