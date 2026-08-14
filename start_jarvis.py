#!/usr/bin/env python
"""
start_jarvis.py
---------------
Startup script to run JARVIS backend + voice service together.
"""
import os
import sys
import subprocess
import time
import signal
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()
BACKEND_DIR = BASE_DIR
VENV_PYTHON = sys.executable


def check_env():
    """Check required environment variables."""
    # openWakeWord doesn't require an access key (unlike Porcupine)
    required = []
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[Start] Missing required env vars: {missing}")
        print("Set them in .env file or environment")
        return False
    return True


def run_backend():
    """Run FastAPI backend with uvicorn (no --reload to avoid whisper.cpp file-watch overhead)."""
    os.chdir(BACKEND_DIR)
    cmd = [
        VENV_PYTHON, "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1", "--port", "8000",
        "--workers", "1", "--log-level", "warning",
    ]
    print(f"[Start] Starting backend: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=os.environ.copy())


def run_voice_service():
    """Run voice service."""
    os.chdir(BACKEND_DIR)
    cmd = [VENV_PYTHON, "voice_service.py"]
    print(f"[Start] Starting voice service: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=os.environ.copy())


def run_frontend_dev():
    """Run Vite dev server."""
    frontend_dir = BASE_DIR
    cmd = ["npm", "run", "dev"]
    print(f"[Start] Starting frontend: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=frontend_dir, env=os.environ.copy(), shell=True)


def main():
    # Load .env
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    
    if not check_env():
        print("\n[Start] Create .env file with:")
        print("  GROQ_API_KEY=your_groq_key (optional)")
        print("  WHISPER_MODEL=base.en (optional, default)")
        return 1
    
    processes = []
    
    def cleanup():
        print("\n[Start] Shutting down...")
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("[Start] Done.")
    
    # Handle Ctrl+C
    def signal_handler(sig, frame):
        cleanup()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start backend
        backend = run_backend()
        processes.append(backend)
        time.sleep(2)  # Wait for backend to start
        
        # Start frontend (voice now runs in browser via WebSocket)
        frontend = run_frontend_dev()
        processes.append(frontend)
        
        print("\n[Start] All services running!")
        print("  Backend:  http://127.0.0.1:8000")
        print("  Frontend: http://localhost:3000")
        print("  Voice:    Browser WebSocket (click mic button)")
        print("\nPress Ctrl+C to stop all services.\n")
        
        # Wait for any process to exit
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f"[Start] Process exited with code {p.returncode}")
                    cleanup()
                    return p.returncode
            time.sleep(1)
            
    except KeyboardInterrupt:
        cleanup()
        return 0
    except Exception as e:
        print(f"[Start] Error: {e}")
        cleanup()
        return 1


if __name__ == "__main__":
    sys.exit(main())