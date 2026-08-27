import os
import subprocess
import webbrowser
import psutil
import shutil
import pyautogui
import tempfile
from datetime import datetime

# Root folder for Jarvis's work files
WORK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "work_files"))
if not os.path.exists(WORK_DIR):
    os.makedirs(WORK_DIR)

def get_system_stats():
    """Retrieve current system resource utilization."""
    try:
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage('C:').percent
        
        # Get up to 5 running processes using resources
        processes = []
        for proc in sorted(psutil.process_iter(['name', 'cpu_percent', 'memory_percent']), 
                           key=lambda p: p.info.get('cpu_percent') or 0, reverse=True)[:5]:
            try:
                processes.append({
                    "name": proc.info['name'],
                    "cpu": proc.info['cpu_percent'],
                    "memory": round(proc.info['memory_percent'], 1) if proc.info['memory_percent'] else 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        return {
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "processes": processes,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        return {"error": str(e)}

def open_application(app_name: str) -> dict:
    """Launch standard Windows applications or websites."""
    app_name = app_name.lower().strip()
    
    # Common websites
    websites = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://www.github.com",
        "chatgpt": "https://chatgpt.com",
        "gmail": "https://mail.google.com",
        "wikipedia": "https://www.wikipedia.org"
    }
    
    if app_name in websites or app_name.startswith("http://") or app_name.startswith("https://") or app_name.endswith(".com") or app_name.endswith(".org"):
        url = websites.get(app_name, app_name if app_name.startswith("http") else f"https://{app_name}")
        webbrowser.open(url)
        return {"status": "success", "message": f"Opened browser to {url}"}
        
    # Standard Windows apps mapping
    apps = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "taskmgr": "taskmgr.exe"
    }
    
    if app_name in apps:
        subprocess.Popen(apps[app_name], shell=True)
        return {"status": "success", "message": f"Launched {app_name}"}
    
    # Generic fallback: try running it directly
    try:
        subprocess.Popen(app_name, shell=True)
        return {"status": "success", "message": f"Attempted to launch command: {app_name}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch {app_name}: {str(e)}"}

def close_application(app_name: str) -> dict:
    """Terminate standard processes by name."""
    app_name = app_name.lower().replace(".exe", "").strip()
    # Safe guard: don't close critical system processes
    protected = ["explorer", "svchost", "lsass", "services", "system", "idle", "python", "node"]
    if app_name in protected:
        return {"status": "error", "message": f"Cannot close protected system application: {app_name}"}
        
    try:
        # Use taskkill on Windows to kill by process name
        output = subprocess.check_output(f'taskkill /F /IM "{app_name}.exe"', shell=True, stderr=subprocess.STDOUT)
        return {"status": "success", "message": f"Closed {app_name}: {output.decode().strip()}"}
    except subprocess.CalledProcessError:
        # Try finding processes via psutil
        closed_count = 0
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and app_name in proc.info['name'].lower():
                    proc.kill()
                    closed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if closed_count > 0:
            return {"status": "success", "message": f"Closed {closed_count} instances of {app_name}"}
        return {"status": "error", "message": f"No running application found matching: {app_name}"}

def list_files(subdir: str = "") -> dict:
    """List all files in the Jarvis work files directory."""
    target_dir = os.path.abspath(os.path.join(WORK_DIR, subdir))
    # Prevent directory traversal attacks
    if not target_dir.startswith(WORK_DIR):
        return {"status": "error", "message": "Access denied: outside work workspace"}
        
    if not os.path.exists(target_dir):
        return {"status": "error", "message": f"Directory does not exist: {subdir}"}
        
    try:
        items = []
        for name in os.listdir(target_dir):
            path = os.path.join(target_dir, name)
            is_dir = os.path.isdir(path)
            size = os.path.getsize(path) if not is_dir else 0
            items.append({
                "name": name,
                "is_dir": is_dir,
                "size": size,
                "relative_path": os.path.relpath(path, WORK_DIR).replace("\\", "/")
            })
        return {"status": "success", "files": items, "current_dir": os.path.relpath(target_dir, WORK_DIR).replace("\\", "/")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def write_file(filename: str, content: str) -> dict:
    """Create or overwrite a file in the work files directory."""
    # Ensure safe filename
    filename = os.path.basename(filename)
    path = os.path.join(WORK_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "message": f"Successfully wrote file: {filename}", "path": path}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write file: {str(e)}"}

def read_file(filename: str) -> dict:
    """Read file content in the work files directory (supports nested paths like screenshots/x.png)."""
    filename = filename.replace("\\", "/").lstrip("/")
    path = os.path.abspath(os.path.join(WORK_DIR, filename))
    if not path.startswith(os.path.abspath(WORK_DIR)):
        return {"status": "error", "message": "Invalid path."}
    if not os.path.exists(path):
        return {"status": "error", "message": f"File not found: {filename}"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content, "filename": filename}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read file: {str(e)}"}

def delete_file(filename: str) -> dict:
    """Delete a file or folder inside the work files directory."""

    filename = filename.replace("\\", "/").lstrip("/")

    path = os.path.abspath(os.path.join(WORK_DIR, filename))

    # Prevent deleting anything outside WORK_DIR
    if not path.startswith(os.path.abspath(WORK_DIR)):
        return {
            "status": "error",
            "message": "Invalid path."
        }

    if not os.path.exists(path):
        return {
            "status": "error",
            "message": f"Not found: {filename}"
        }

    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            return {
                "status": "error",
                "message": "Unsupported file type."
            }

        return {
            "status": "success",
            "message": f"Deleted: {filename}"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def take_screenshot() -> dict:
    """Take a screenshot of the main screen and return its status."""
    try:
        img_dir = os.path.join(WORK_DIR, "screenshots")
        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(img_dir, filename)
        pyautogui.screenshot(path)
        return {"status": "success", "message": f"Screenshot saved: screenshots/{filename}", "path": f"screenshots/{filename}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to take screenshot: {str(e)}"}

def get_desktop_path():
    user_profile = os.environ.get("USERPROFILE", "C:\\Users\\taha")
    # Try OneDrive desktop first, then regular desktop
    onedrive_desktop = os.path.join(user_profile, "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    regular_desktop = os.path.join(user_profile, "Desktop")
    if os.path.exists(regular_desktop):
        return regular_desktop
    return user_profile

def create_folder(folder_name: str) -> dict:
    """Create a folder relative to workspace, or on desktop if specified."""
    import re
    folder_name_lower = folder_name.lower()
    
    # Check if they want it on desktop
    if "desktop" in folder_name_lower:
        # Clean folder_name, e.g. "my_test on desktop" -> "my_test"
        clean_name = re.sub(r'\s+on\s+desktop', '', folder_name, flags=re.I)
        clean_name = re.sub(r'desktop\s+named\s+', '', clean_name, flags=re.I)
        clean_name = os.path.basename(clean_name.strip())
        path = os.path.join(get_desktop_path(), clean_name)
    elif os.path.isabs(folder_name):
        path = folder_name
    else:
        path = os.path.abspath(os.path.join(WORK_DIR, folder_name))
        
    try:
        os.makedirs(path, exist_ok=True)
        return {"status": "success", "message": f"Successfully created folder: {os.path.basename(path)}", "path": path}
    except Exception as e:
        return {"status": "error", "message": f"Failed to create folder: {str(e)}"}

def create_word_document(filename: str, content: str) -> dict:
    """Create a Microsoft Word .docx file relative to workspace, or on desktop if specified."""
    import re
    if not filename.endswith('.docx'):
        filename += '.docx'
        
    # Check if desktop requested
    filename_lower = filename.lower()
    if "desktop" in filename_lower:
        clean_name = re.sub(r'\s+on\s+desktop', '', filename, flags=re.I)
        clean_name = os.path.basename(clean_name.strip())
        path = os.path.join(get_desktop_path(), clean_name)
    else:
        filename = os.path.basename(filename)
        path = os.path.join(WORK_DIR, filename)
        
    try:
        import docx
        doc = docx.Document()
        for paragraph in content.split('\n'):
            if paragraph.strip():
                doc.add_paragraph(paragraph)
        doc.save(path)
        return {"status": "success", "message": f"Word document created successfully: {os.path.basename(path)}", "path": path}
    except Exception as e:
        print(f"python-docx error: {str(e)}, using plain text fallback")
        try:
            # Create a simple .docx or .doc file with text format (or a simple text file)
            # MS Word can open a plain text file if named .doc / .txt
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"status": "success", "message": f"Created document (plain text fallback): {os.path.basename(path)}", "path": path}
        except Exception as e2:
            return {"status": "error", "message": f"Failed to create document: {str(e2)}"}

def check_pc_health() -> dict:
    """Perform a comprehensive system health check."""
    import socket
    import time
    
    # 1. Internet connection and ping latency test
    ping_ok = False
    ping_time = 0.0
    try:
        start_t = time.time()
        socket.setdefaulttimeout(2.5)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        ping_time = round((time.time() - start_t) * 1000, 1)
        ping_ok = True
    except Exception:
        pass
        
    # 2. Hardware Resource Metrics
    cpu = psutil.cpu_percent(interval=0.3)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage('C:').percent
    
    # 3. Battery status check
    battery_msg = "N/A"
    if hasattr(psutil, "sensors_battery"):
        battery = psutil.sensors_battery()
        if battery:
            battery_msg = f"{battery.percent}% {'(Charging)' if battery.power_plugged else '(Discharging)'}"
            
    # 4. Warnings and diagnosis
    health_score = 100
    warnings = []
    
    if cpu > 70:
        health_score -= 20
        warnings.append(f"High CPU load detected ({cpu}%)")
    if memory > 75:
        health_score -= 20
        warnings.append(f"High memory utilization ({memory}%)")
    if disk > 90:
        health_score -= 15
        warnings.append(f"C: Drive space is critically low ({disk}%)")
    if not ping_ok:
        health_score -= 10
        warnings.append("No active internet connection detected")
        
    status = "EXCELLENT" if health_score >= 90 else "GOOD" if health_score >= 75 else "DEGRADED" if health_score >= 50 else "CRITICAL"
    
    report_text = f"System health is {status} (Score: {health_score}/100). "
    if warnings:
        report_text += "Warnings detected: " + ", ".join(warnings)
    else:
        report_text += "All hardware metrics are within nominal ranges."
        
    return {
        "status": "success",
        "message": report_text,
        "report": {
            "status": status,
            "score": health_score,
            "cpu": f"{cpu}%",
            "memory": f"{memory}%",
            "disk": f"{disk}%",
            "battery": battery_msg,
            "ping": f"{ping_time}ms" if ping_ok else "Offline",
            "warnings": warnings if warnings else ["All systems nominal."]
        }
    }

def adjust_volume(action: str) -> dict:
    """Adjust or mute the system volume using simulated keypresses."""
    action = action.lower().strip()
    try:
        if action == "up":
            for _ in range(5):
                pyautogui.press("volumeup")
            return {"status": "success", "message": "Increased system volume, sir."}
        elif action == "down":
            for _ in range(5):
                pyautogui.press("volumedown")
            return {"status": "success", "message": "Decreased system volume, sir."}
        elif action == "mute":
            pyautogui.press("volumemute")
            return {"status": "success", "message": "Toggled mute status, sir."}
        else:
            return {"status": "error", "message": f"Unknown volume action: {action}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to adjust volume: {str(e)}"}

def media_control(action: str) -> dict:
    """Control media playback (play, pause, next, skip, prev)."""
    action = action.lower().strip()
    try:
        if action in ["play", "pause", "play_pause", "toggle"]:
            pyautogui.press("playpause")
            return {"status": "success", "message": "Toggled media playback, sir."}
        elif action in ["next", "skip"]:
            pyautogui.press("nexttrack")
            return {"status": "success", "message": "Skipped to next track, sir."}
        elif action in ["prev", "previous", "back"]:
            pyautogui.press("prevtrack")
            return {"status": "success", "message": "Returned to previous track, sir."}
        else:
            return {"status": "error", "message": f"Unknown media action: {action}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to control media: {str(e)}"}

def search_web(query: str) -> dict:
    """Search Google for a query in the default browser."""
    import urllib.parse
    try:
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        webbrowser.open(url)
        return {"status": "success", "message": f"I have searched the web for '{query}', sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to search web: {str(e)}"}


def launch_any_app(app_name: str) -> dict:
    """Find and launch ANY installed application by searching Start Menu shortcuts, Program Files, and PATH.
    This is much more powerful than open_application - it can find apps like VS Code, Spotify, Discord, etc."""
    import glob
    
    app_name_lower = app_name.lower().strip()
    
    # 1. First check common websites
    websites = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://www.github.com",
        "chatgpt": "https://chatgpt.com",
        "gmail": "https://mail.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "whatsapp web": "https://web.whatsapp.com",
        "instagram": "https://www.instagram.com",
        "twitter": "https://twitter.com",
        "reddit": "https://www.reddit.com",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.com",
    }
    
    if app_name_lower in websites:
        webbrowser.open(websites[app_name_lower])
        return {"status": "success", "message": f"Opened {app_name} in your browser, sir."}
    
    if app_name_lower.startswith("http://") or app_name_lower.startswith("https://") or app_name_lower.endswith(".com") or app_name_lower.endswith(".org"):
        url = app_name if app_name.startswith("http") else f"https://{app_name}"
        webbrowser.open(url)
        return {"status": "success", "message": f"Opened {url} in your browser, sir."}
    
    # 2. Quick built-in apps mapping
    quick_apps = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "taskmgr": "taskmgr.exe",
        "settings": "ms-settings:",
        "snipping tool": "SnippingTool.exe",
        "wordpad": "wordpad.exe",
        "control panel": "control.exe",
    }
    
    if app_name_lower in quick_apps:
        try:
            if quick_apps[app_name_lower].startswith("ms-"):
                os.startfile(quick_apps[app_name_lower])
            else:
                subprocess.Popen(quick_apps[app_name_lower], shell=True)
            return {"status": "success", "message": f"Launched {app_name}, sir."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to launch {app_name}: {str(e)}"}
    
    # 3. Search Start Menu shortcuts (.lnk files)
    search_dirs = []
    user_profile = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    
    if user_profile:
        search_dirs.append(os.path.join(user_profile, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"))
        search_dirs.append(os.path.join(user_profile, "Desktop"))
        search_dirs.append(os.path.join(user_profile, "OneDrive", "Desktop"))
    
    search_dirs.append(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    
    best_match = None
    best_score = 0
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            for fname in files:
                if fname.lower().endswith('.lnk') or fname.lower().endswith('.url'):
                    name_no_ext = os.path.splitext(fname)[0].lower()
                    # Score the match
                    score = 0
                    if app_name_lower == name_no_ext:
                        score = 100  # Exact match
                    elif app_name_lower in name_no_ext:
                        score = 80 + (len(app_name_lower) / len(name_no_ext)) * 20
                    elif all(word in name_no_ext for word in app_name_lower.split()):
                        score = 60
                    
                    if score > best_score:
                        best_score = score
                        best_match = os.path.join(root, fname)
    
    if best_match and best_score >= 50:
        try:
            os.startfile(best_match)
            match_name = os.path.splitext(os.path.basename(best_match))[0]
            return {"status": "success", "message": f"Launched {match_name}, sir."}
        except Exception as e:
            return {"status": "error", "message": f"Found {best_match} but failed to launch: {str(e)}"}
    
    # 4. Search Program Files directories for .exe files
    program_dirs = [
        os.environ.get("PROGRAMFILES", "C:\\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs") if os.environ.get("LOCALAPPDATA") else None,
    ]
    
    for pdir in program_dirs:
        if not pdir or not os.path.exists(pdir):
            continue
        # Only search top 2 levels deep for speed
        for entry in os.scandir(pdir):
            if entry.is_dir():
                if app_name_lower in entry.name.lower():
                    # Search for an exe inside
                    try:
                        for sub_entry in os.scandir(entry.path):
                            if sub_entry.is_file() and sub_entry.name.lower().endswith('.exe'):
                                try:
                                    subprocess.Popen(sub_entry.path, shell=True)
                                    return {"status": "success", "message": f"Launched {sub_entry.name} from {entry.name}, sir."}
                                except:
                                    pass
                    except PermissionError:
                        continue
    
    # 5. Last resort: try running the name directly (works for PATH apps)
    try:
        subprocess.Popen(app_name, shell=True)
        return {"status": "success", "message": f"Attempted to launch {app_name}, sir."}
    except Exception as e:
        return {"status": "error", "message": f"I couldn't find an application matching '{app_name}' on your system, sir."}


def save_generated_image(save_name: str, destination: str = "desktop") -> dict:
    """Copy the last generated image to the Desktop or another directory with a new name."""
    import shutil
    
    if not save_name:
        return {"status": "error", "message": "No filename specified for saving the image, sir."}
    
    if not save_name.endswith(('.png', '.jpg', '.jpeg')):
        save_name += '.png'
    
    # Find the most recent image in work_files/images
    img_dir = os.path.join(WORK_DIR, "images")
    if not os.path.exists(img_dir):
        return {"status": "error", "message": "No images have been generated yet, sir."}
    
    # Get most recent image file
    image_files = [f for f in os.listdir(img_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not image_files:
        return {"status": "error", "message": "No generated images found in the workspace, sir."}
    
    image_files.sort(key=lambda f: os.path.getmtime(os.path.join(img_dir, f)), reverse=True)
    latest_image = os.path.join(img_dir, image_files[0])
    
    # Determine destination path
    if destination.lower() == "desktop":
        dest_dir = get_desktop_path()
    else:
        dest_dir = WORK_DIR
    
    dest_path = os.path.join(dest_dir, save_name)
    
    try:
        shutil.copy2(latest_image, dest_path)
        return {"status": "success", "message": f"Image saved as {save_name} to {os.path.basename(dest_dir)}, sir.", "path": dest_path}
    except Exception as e:
        return {"status": "error", "message": f"Failed to save image: {str(e)}"}


# ===== NEW CAPABILITIES =====

def shutdown_pc(delay_seconds: int = 0) -> dict:
    """Shutdown the PC immediately or after a delay in seconds."""
    try:
        if delay_seconds > 0:
            subprocess.Popen(f'shutdown /s /t {delay_seconds}', shell=True)
            return {"status": "success", "message": f"PC will shutdown in {delay_seconds} seconds, sir."}
        else:
            subprocess.Popen('shutdown /s /t 10', shell=True)
            return {"status": "success", "message": "Initiating shutdown sequence in 10 seconds, sir. All systems will power down."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to initiate shutdown: {str(e)}"}


def restart_pc(delay_seconds: int = 0) -> dict:
    """Restart the PC immediately or after a delay in seconds."""
    try:
        if delay_seconds > 0:
            subprocess.Popen(f'shutdown /r /t {delay_seconds}', shell=True)
            return {"status": "success", "message": f"PC will restart in {delay_seconds} seconds, sir."}
        else:
            subprocess.Popen('shutdown /r /t 10', shell=True)
            return {"status": "success", "message": "Rebooting systems in 10 seconds, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to initiate restart: {str(e)}"}


def cancel_shutdown() -> dict:
    """Cancel a pending scheduled shutdown or restart."""
    try:
        subprocess.Popen('shutdown /a', shell=True)
        return {"status": "success", "message": "Shutdown/restart has been cancelled, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to cancel shutdown: {str(e)}"}


def sleep_pc() -> dict:
    """Put the PC to sleep."""
    try:
        subprocess.Popen('rundll32.exe powrprof.dll,SetSuspendState 0,1,0', shell=True)
        return {"status": "success", "message": "Initiating sleep mode, sir. Good night."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to sleep PC: {str(e)}"}


def lock_screen() -> dict:
    """Lock the Windows workstation immediately."""
    try:
        subprocess.Popen('rundll32.exe user32.dll,LockWorkStation', shell=True)
        return {"status": "success", "message": "Workstation locked, sir. Security protocols engaged."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to lock screen: {str(e)}"}


def get_clipboard() -> dict:
    """Read the current contents of the Windows clipboard."""
    try:
        import subprocess
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Get-Clipboard'],
            capture_output=True, text=True, timeout=5
        )
        content = result.stdout.strip()
        if not content:
            return {"status": "success", "message": "Clipboard is empty, sir.", "content": ""}
        # Truncate very long clipboard content
        if len(content) > 500:
            preview = content[:500] + "..."
        else:
            preview = content
        return {"status": "success", "message": f"Clipboard contains: {preview}", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read clipboard: {str(e)}"}


def set_clipboard(text: str) -> dict:
    """Write text to the Windows clipboard."""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'Set-Clipboard -Value "{text}"'],
            capture_output=True, text=True, timeout=5
        )
        return {"status": "success", "message": f"Copied to clipboard, sir: {text[:80]}{'...' if len(text)>80 else ''}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write to clipboard: {str(e)}"}


def get_battery_info() -> dict:
    """Get battery status and charge level."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {"status": "success", "message": "No battery detected — this appears to be a desktop PC, sir.",
                    "battery": {"percent": None, "plugged": True, "time_left": None}}
        percent = round(battery.percent, 1)
        plugged = battery.power_plugged
        secs_left = battery.secsleft
        if secs_left and secs_left != psutil.POWER_TIME_UNLIMITED and secs_left > 0:
            h, m = divmod(secs_left // 60, 60)
            time_str = f"{h}h {m}m remaining"
        elif plugged:
            time_str = "Fully charging" if percent < 100 else "Fully charged"
        else:
            time_str = "Unknown"
        status_str = "charging" if plugged else "discharging"
        msg = f"Battery is at {percent}% and {status_str}. {time_str}."
        return {"status": "success", "message": msg,
                "battery": {"percent": percent, "plugged": plugged, "time_left": time_str}}
    except Exception as e:
        return {"status": "error", "message": f"Failed to get battery info: {str(e)}"}


def get_network_info() -> dict:
    """Get IP addresses, active interfaces, and internet connectivity."""
    import socket
    import urllib.request
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        # Get all interface IPs
        interfaces = {}
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                    interfaces[iface] = addr.address

        # Get public IP
        public_ip = "Unknown"
        try:
            with urllib.request.urlopen('https://api.ipify.org', timeout=3) as r:
                public_ip = r.read().decode('utf-8').strip()
        except Exception:
            pass

        # Check connectivity
        connected = False
        try:
            socket.setdefaulttimeout(2)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            connected = True
        except Exception:
            pass

        iface_str = ", ".join(f"{k}: {v}" for k, v in list(interfaces.items())[:3])
        msg = (f"Network status: {'Connected' if connected else 'Offline'}. "
               f"Local IP: {local_ip}. Public IP: {public_ip}. "
               f"Active interfaces: {iface_str or 'None detected'}.")
        return {
            "status": "success",
            "message": msg,
            "network": {
                "connected": connected,
                "local_ip": local_ip,
                "public_ip": public_ip,
                "hostname": hostname,
                "interfaces": interfaces
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to get network info: {str(e)}"}


def get_weather(city: str) -> dict:
    """Get current weather for a city using the free wttr.in JSON API (no API key required)."""
    import urllib.request
    import urllib.parse
    try:
        city_encoded = urllib.parse.quote(city)
        url = f"https://wttr.in/{city_encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = __import__('json').loads(r.read().decode('utf-8'))

        current = data['current_condition'][0]
        temp_c = current['temp_C']
        temp_f = current['temp_F']
        feels_c = current['FeelsLikeC']
        humidity = current['humidity']
        desc = current['weatherDesc'][0]['value']
        wind_kmph = current['windspeedKmph']
        area = data.get('nearest_area', [{}])[0]
        area_name = area.get('areaName', [{}])[0].get('value', city)
        country = area.get('country', [{}])[0].get('value', '')

        location_str = f"{area_name}, {country}" if country else area_name
        msg = (f"Weather in {location_str}: {desc}. "
               f"Temperature: {temp_c}°C ({temp_f}°F), feels like {feels_c}°C. "
               f"Humidity: {humidity}%. Wind: {wind_kmph} km/h.")
        return {
            "status": "success",
            "message": msg,
            "weather": {
                "location": location_str,
                "description": desc,
                "temp_c": temp_c,
                "temp_f": temp_f,
                "feels_like_c": feels_c,
                "humidity": humidity,
                "wind_kmph": wind_kmph
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"Couldn't retrieve weather for '{city}', sir. Check the city name or your connection. ({str(e)})"}


def get_datetime_info() -> dict:
    """Return current local date, time, day of week, and timezone info."""
    from datetime import datetime
    import time
    now = datetime.now()
    tz_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]
    day_name = now.strftime('%A')
    date_str = now.strftime('%B %d, %Y')
    time_str = now.strftime('%I:%M %p')
    msg = f"It is {day_name}, {date_str} at {time_str} ({tz_name}), sir."
    return {
        "status": "success",
        "message": msg,
        "datetime": {
            "day": day_name,
            "date": date_str,
            "time": time_str,
            "timezone": tz_name,
            "iso": now.isoformat()
        }
    }


def open_url(url: str) -> dict:
    """Open any URL directly in the default browser."""
    import webbrowser
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        webbrowser.open(url)
        return {"status": "success", "message": f"Opened {url} in your browser, sir."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open URL: {str(e)}"}

def type_text(text: str) -> dict:
    """Type out a string of text simulating a keyboard."""
    try:
        # Import here just to be safe, though pyautogui is imported at the top
        import pyautogui
        pyautogui.write(text, interval=0.01)
        return {"status": "success", "message": f"Typed text: {text[:20]}..."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to type text: {str(e)}"}

def press_key(key: str, modifiers: list = None) -> dict:
    """Press a specific key, optionally with modifiers like ctrl or shift."""
    try:
        import pyautogui
        if modifiers:
            # Using hotkey for modified keypresses (e.g., ctrl+c)
            pyautogui.hotkey(*modifiers, key)
            mod_str = "+".join(modifiers)
            return {"status": "success", "message": f"Pressed {mod_str}+{key}"}
        else:
            pyautogui.press(key)
            return {"status": "success", "message": f"Pressed key {key}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to press key {key}: {str(e)}"}
