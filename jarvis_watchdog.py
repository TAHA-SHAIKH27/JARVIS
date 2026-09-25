"""
jarvis_watchdog.py — Standalone Process Supervisor & Crash Recovery Daemon for J.A.R.V.I.S.
========================================================================================
STANDALONE ARCHITECTURE:
- Runs as an independent supervisor process wrapping main.py.
- Zero dependency on FastAPI/Uvicorn — pure standard library.
- Monitors backend health via process status AND HTTP polling on /api/status.
- On crash OR unhealthy HTTP state: captures stderr/traceback -> invokes recovery_engine.py -> restarts JARVIS.
- Prevents infinite restart loops with MAX_CRASH_RECOVERIES limit.
"""

import os
import sys
import time
import subprocess
import signal
import urllib.request
import urllib.error
from datetime import datetime

import collections
import threading

# Import recovery engine
import recovery_engine

WATCHDOG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog.log")
CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog_crash.log")
MAX_CRASH_RECOVERIES = 3
HEALTH_CHECK_INTERVAL = 5  # seconds
HEALTH_CHECK_URL = "http://127.0.0.1:8000/api/status"
# Number of consecutive HTTP health check failures before triggering recovery
MAX_CONSECUTIVE_HEALTH_FAILURES = 5
# Grace period after start before health checks count (seconds)
HEALTH_CHECK_GRACE_PERIOD = 15


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
        self.consecutive_health_failures = 0
        self.process_start_time = 0
        self.stdout_lines = collections.deque(maxlen=1000)
        self.stderr_lines = collections.deque(maxlen=1000)
        self._reader_threads = []

    def _stream_reader(self, stream, target_deque, prefix=""):
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                clean_line = line.rstrip("\r\n")
                target_deque.append(clean_line)
                # Print child logs to watchdog console
                if clean_line.strip():
                    print(f"[JARVIS] {clean_line}")
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def start_jarvis(self) -> subprocess.Popen:
        """Launch main.py as a subprocess."""
        log(f"Starting J.A.R.V.I.S. Core backend ({self.main_script})...")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        self.stdout_lines.clear()
        self.stderr_lines.clear()
        self._reader_threads.clear()

        # Start uvicorn main:app with piped stderr/stdout for crash capture
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )

        # Spawn background reader threads to prevent OS pipe buffer deadlocks
        t_out = threading.Thread(
            target=self._stream_reader,
            args=(self.process.stdout, self.stdout_lines, "STDOUT"),
            daemon=True
        )
        t_err = threading.Thread(
            target=self._stream_reader,
            args=(self.process.stderr, self.stderr_lines, "STDERR"),
            daemon=True
        )
        t_out.start()
        t_err.start()
        self._reader_threads.extend([t_out, t_err])

        log(f"J.A.R.V.I.S. PID: {self.process.pid}")
        self.process_start_time = time.time()
        self.consecutive_health_failures = 0
        return self.process

    def check_health(self) -> bool:
        """Ping HTTP /api/status endpoint."""
        try:
            req = urllib.request.Request(HEALTH_CHECK_URL, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            log(f"Health check HTTP error: {e.code}")
            return False
        except urllib.error.URLError as e:
            log(f"Health check URL error: {e.reason}")
            return False
        except Exception as e:
            log(f"Health check unexpected error: {e}")
            return False

    def capture_crash_output(self) -> str:
        """Read captured stdout and stderr buffers."""
        # Wait briefly for reader threads to flush final output
        for t in self._reader_threads:
            t.join(timeout=1.0)

        stdout_text = "\n".join(self.stdout_lines)
        stderr_text = "\n".join(self.stderr_lines)

        full_output = f"=== STDERR ===\n{stderr_text}\n\n=== STDOUT ===\n{stdout_text}"
        with open(CRASH_LOG, "w", encoding="utf-8") as f:
            f.write(full_output)

        log(f"Saved crash output to {CRASH_LOG}")
        return full_output

    def prompt_user_after_recovery(self, result: dict) -> bool:
        """
        Ask user confirmation after recovery with smart options if rejected.
        """
        target_file = result.get("file", "unknown")
        backup_path = result.get("backup", "")
        basename = os.path.basename(target_file)

        print("\n" + "="*65)
        print(f" [GUARDIAN] AI Auto-Repair Succeeded for: {basename}")
        if backup_path:
            print(f" [GUARDIAN] Original Backup Preserved at: {backup_path}")
        print("="*65)

        try:
            choice = input(f"\n[GUARDIAN] Start J.A.R.V.I.S. now? [Y/n] (Press Enter for Yes): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "y"

        if choice in ["", "y", "yes"]:
            log(f"User approved startup. Launching J.A.R.V.I.S. backend...")
            return True

        # User chose 'N' -> Provide smart action options
        print("\n" + "-"*65)
        print(" [GUARDIAN] What would you like to do?")
        print("   [R] Rollback: Revert file to original backup copy")
        print("   [M] Manual Edit: Pause supervisor so you can edit in your IDE")
        print("   [Q] Quit: Shut down J.A.R.V.I.S. supervisor")
        print("-"*65)

        try:
            sub_choice = input("[GUARDIAN] Select option (R / M / Q): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sub_choice = "q"

        if sub_choice == "r":
            if result.get("repaired_copy"):
                # Copy-only repair: the project original was never modified,
                # so there is nothing to revert — say so and stand down
                # WITHOUT writing to the original file.
                log(f"No rollback needed: original {basename} was never modified (copy-only repair).")
                print(f"\n[GUARDIAN] Nothing to revert, sir — your original '{basename}' was never touched.")
                return False
            if backup_path and os.path.exists(backup_path):
                recovery_engine.restore_backup(backup_path, target_file)
                log(f"Reverted {basename} back to backup state. Watchdog standing down.")
            else:
                log(f"No backup file available to revert.")
            return False

        elif sub_choice == "m":
            print(f"\n[GUARDIAN] Supervisor paused. Edit '{basename}' in your IDE now.")
            try:
                input("[GUARDIAN] When you have saved your edits in your editor, press [ENTER] to resume: ")
            except (EOFError, KeyboardInterrupt):
                pass

            is_valid, val_msg = recovery_engine.validate_python_file(target_file)
            if is_valid:
                log(f"Manual edits validated successfully ({val_msg}). Launching J.A.R.V.I.S. backend...")
                return True
            else:
                print(f"[GUARDIAN] Validation Error in your edits: {val_msg}")
                try:
                    retry = input("[GUARDIAN] Try launching anyway? [y/N]: ").strip().lower()
                    return retry in ["y", "yes"]
                except (EOFError, KeyboardInterrupt):
                    return False

        else:
            log("Watchdog shutdown requested by user.")
            return False

    def _attempt_visible_repair(self, t_file: str, t_line: int, t_err: str,
                                  summary_path: str) -> dict:
        """Run the repair inside the popup cmd window and settle the result.

        Snapshot the original, pop the interactive shell (it runs `opencode`
        visibly and signals done_<token>.txt), wait, then validate + archive
        the fixed COPY and restore the original. Any failure returns a
        non-success dict so the caller falls back to headless recovery.
        """
        import time as _time
        try:
            import crash_report
            with open(t_file, "rb") as f:
                snapshot = f.read()
        except OSError as e:
            return {"status": "error",
                    "message": f"Could not snapshot original: {e}"}
        try:
            backup_path = recovery_engine.create_backup(t_file, tag="crash_recovery")
        except Exception:
            backup_path = ""
        try:
            token, job = crash_report.pop_interactive_repair_console(
                summary_path, t_file, t_line, t_err)
        except Exception as e:
            return {"status": "error", "message": f"Popup failed: {e}"}
        self._crash_token = token
        self._repair_job = job
        if not token or not job.get("donefile"):
            return {"status": "error",
                    "message": "No interactive window (non-Windows or popup blocked)"}
        log(f"Waiting for the visible repair session (token {token})...")
        deadline = _time.time() + 1800
        exit_code = None
        while _time.time() < deadline:
            if os.path.exists(job["donefile"]):
                try:
                    with open(job["donefile"], "r", encoding="utf-8",
                              errors="replace") as f:
                        exit_code = int((f.read() or "").strip() or 0)
                except (OSError, ValueError):
                    exit_code = -1
                break
            _time.sleep(5)
        if exit_code is None:
            return {"status": "error",
                    "message": "Visible window closed or timed out waiting"}
        if exit_code != 0:
            return {"status": "error",
                    "message": f"Visible opencode run exited with code {exit_code}"}
        try:
            settled = recovery_engine.validate_and_archive_visible_fix(
                t_file, snapshot, backup_path)
        except Exception as e:
            return {"status": "error", "message": f"Settle failed: {e}"}
        if not settled.get("valid"):
            return {"status": "error", "message": settled.get("message", "")}
        log(f"Repaired file archived: {settled['repaired_copy']}")
        return {"status": "success", "file": t_file, "backup": backup_path,
                "repaired_copy": settled["repaired_copy"],
                "message": settled.get("message", "")}

    def handle_crash(self) -> bool:
        """Capture crash log, call recovery engine, and decide whether to restart."""
        self.recovery_count += 1
        log(f"CRASH DETECTED! (Incident #{self.recovery_count})")
        
        crash_output = self.capture_crash_output()

        # Diagnostic summary
        parsed = recovery_engine.parse_traceback(crash_output)
        t_file = parsed.get("file")
        t_line = parsed.get("line")
        t_err = parsed.get("error")

        print("\n" + "!"*65)
        print(f" [WATCHDOG] J.A.R.V.I.S. CRASH DETECTED (Incident #{self.recovery_count})")
        if t_file:
            print(f" [WATCHDOG] Failing File: {os.path.basename(t_file)}")
            print(f" [WATCHDOG] Error Line:   Line {t_line}")
        print(f" [WATCHDOG] Error Info:   {t_err}")
        print("!"*65 + "\n")

        # User-facing crash report: plain-language summary under
        # "STARTUP CRASH/". Then the interactive repair shell (ONE cmd
        # window: summary -> any key -> cd to project -> visible
        # `opencode run` -> transcript -> fix summary in the SAME window).
        # Copy-only throughout: the original is never written.
        self._crash_token = None
        self._repair_job = {}
        summary_path = ""
        try:
            import crash_report
            summary_path = crash_report.write_crash_summary(
                crash_output, parsed, self.recovery_count)
            log(f"Crash summary written: {summary_path}")
        except Exception as e:
            log(f"Crash summary step failed (non-fatal): {e}")

        if self.recovery_count > MAX_CRASH_RECOVERIES:
            log(f"Max recovery limit ({MAX_CRASH_RECOVERIES}) reached. Halting auto-recovery to prevent infinite loops.")
            log("Please review watchdog_crash.log and fix errors manually.")
            return False

        # ── Visible repair first (Windows + identified file only) ──────
        if t_file and t_line and os.name == "nt":
            visible = self._attempt_visible_repair(t_file, t_line, t_err or "",
                                                   summary_path)
            if visible.get("status") == "success":
                try:
                    import crash_report
                    crash_report.show_fix_summary(
                        visible["repaired_copy"],
                        os.path.basename(t_file),
                        visible["message"],
                        token=self._crash_token)
                except Exception as e:
                    log(f"Fix-summary step failed (non-fatal): {e}")
                return self.prompt_user_after_recovery(visible)
            log(f"Visible repair unavailable/failed ({visible.get('message')}) — "
                f"falling back to headless recovery.")

        log("Invoking Independent Guardian Recovery Engine...")
        result = recovery_engine.recover_from_crash(CRASH_LOG, max_retries=3,
                                                   in_place=False)
        log(f"Recovery Engine Result: {result.get('status')} - {result.get('message')}")

        if result.get("status") == "success":
            # The fixed COPY is already archived by the engine
            # (result["repaired_copy"]); publish its summary into the SAME
            # waiting cmd window. The project original was never modified.
            try:
                import crash_report
                fixed_path = result.get("repaired_copy") or ""
                if not fixed_path:
                    fixed_path = crash_report.archive_fixed_file(result.get("file", ""))
                log(f"Repaired file archived: {fixed_path}")
                crash_report.show_fix_summary(
                    fixed_path,
                    os.path.basename(result.get("file", "") or "unknown"),
                    result.get("message", ""),
                    token=getattr(self, "_crash_token", None))
            except Exception as e:
                log(f"Fix-summary step failed (non-fatal): {e}")
            return self.prompt_user_after_recovery(result)
        elif result.get("status") == "unhealthy_backend":
            # Backend became unhealthy (health check failures) but no code crash detected.
            # The backend just needs restarting, not code patching.
            log("Crash recovery identified unhealthy backend state - will restart backend.")
            return True
        else:
            log(f"Recovery was unable to safely repair the issue. Error: {result.get('message')}")
            return False

    def handle_unhealthy_backend(self) -> bool:
        """Handle unhealthy HTTP backend state by terminating process and invoking recovery."""
        self.recovery_count += 1
        log(f"UNHEALTHY BACKEND DETECTED! (Incident #{self.recovery_count})")
        
        # Terminate the unhealthy process
        if self.process and self.process.poll() is None:
            log("Terminating unhealthy backend process...")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
        
        # Capture whatever output we can
        crash_output = self.capture_crash_output()
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n\n=== UNHEALTHY BACKEND DETECTED ===\nConsecutive health check failures: {self.consecutive_health_failures}\n")

        if self.recovery_count > MAX_CRASH_RECOVERIES:
            log(f"Max recovery limit ({MAX_CRASH_RECOVERIES}) reached. Halting auto-recovery to prevent infinite loops.")
            log("Please review watchdog_crash.log and fix errors manually.")
            return False

        log("Invoking Independent Recovery Engine for unhealthy backend...")
        result = recovery_engine.recover_from_crash(CRASH_LOG, max_retries=3,
                                                   in_place=False)
        log(f"Recovery Engine Result: {result.get('status')} - {result.get('message')}")

        if result.get("status") == "success":
            # Copy-only repair: publish the archived fixed copy's summary
            # (no crash popup exists on this path, so token is None).
            try:
                import crash_report
                fixed_path = result.get("repaired_copy") or ""
                if not fixed_path:
                    fixed_path = crash_report.archive_fixed_file(result.get("file", ""))
                log(f"Repaired file archived: {fixed_path}")
                crash_report.show_fix_summary(
                    fixed_path,
                    os.path.basename(result.get("file", "") or "unknown"),
                    result.get("message", ""),
                    token=None)
            except Exception as e:
                log(f"Fix-summary step failed (non-fatal): {e}")
            return self.prompt_user_after_recovery(result)
        elif result.get("status") == "unhealthy_backend":
            # Backend became unhealthy (health check failures) but no code crash detected.
            # The backend just needs restarting, not code patching.
            log("Backend unhealthy but no code crash detected - will restart backend.")
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
                elapsed_since_start = time.time() - self.process_start_time
                
                if not is_healthy:
                    self.consecutive_health_failures += 1
                    log(f"Health check FAILED (consecutive: {self.consecutive_health_failures}/{MAX_CONSECUTIVE_HEALTH_FAILURES})")
                    
                    # Only trigger recovery after grace period and consecutive failures
                    if elapsed_since_start > HEALTH_CHECK_GRACE_PERIOD and self.consecutive_health_failures >= MAX_CONSECUTIVE_HEALTH_FAILURES:
                        log(f"BACKEND UNHEALTHY: {self.consecutive_health_failures} consecutive health check failures after grace period.")
                        log("Triggering recovery engine for unhealthy backend state...")
                        should_restart = self.handle_unhealthy_backend()
                        if should_restart:
                            break  # Break inner loop to restart
                        else:
                            log("Watchdog standing down due to unrecoverable unhealthy state.")
                            return
                else:
                    # Health check passed - reset counter
                    if self.consecutive_health_failures > 0:
                        log(f"Health check RECOVERED (was {self.consecutive_health_failures} consecutive failures)")
                    self.consecutive_health_failures = 0

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
