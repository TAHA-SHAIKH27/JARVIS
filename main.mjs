import { app, BrowserWindow, session, ipcMain } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, ChildProcess } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let pythonBackend: ChildProcess | null = null;
let sttProcess: ChildProcess | null = null;

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.mjs"),
    },
  });

  if (app.isPackaged) {
    // Production build: load the static files Vite produced (`npm run build` -> dist/)
    win.loadFile(path.join(__dirname, "dist", "index.html"));
  } else {
    // Dev mode: load the Vite dev server
    win.loadURL("http://localhost:5173");
    // Open DevTools in development
    win.webContents.openDevTools();
  }
  
  return win;
}

let mainWindow: BrowserWindow | null = null;

// --- Microphone / media permission fix -------------------------------------
function registerMediaPermissions() {
  const ses = session.defaultSession;

  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === "media") {
      callback(true);
      return;
    }
    callback(false);
  });

  ses.setPermissionCheckHandler((webContents, permission) => {
    return permission === "media";
  });
}

// --- Python Backend Management ---------------------------------------------
function startPythonBackend(): Promise<void> {
  return new Promise((resolve, reject) => {
    const backendPath = app.isPackaged
      ? path.join(process.resourcesPath, "backend")
      : path.join(__dirname);
    
    const pythonExe = app.isPackaged
      ? path.join(process.resourcesPath, "python", "python.exe")
      : "python";
    
    console.log("[Main] Starting Python backend from:", backendPath);
    
    pythonBackend = spawn(pythonExe, ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"], {
      cwd: backendPath,
      env: { ...process.env, PYTHONPATH: backendPath },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    
    pythonBackend.stdout?.on("data", (data) => {
      console.log("[Backend]", data.toString().trim());
    });
    
    pythonBackend.stderr?.on("data", (data) => {
      console.error("[Backend]", data.toString().trim());
    });
    
    pythonBackend.on("error", (err) => {
      console.error("[Backend] Failed to start:", err);
      reject(err);
    });
    
    pythonBackend.on("exit", (code) => {
      console.log("[Backend] Exited with code:", code);
      pythonBackend = null;
    });
    
    // Wait for backend to be ready
    const checkReady = setInterval(async () => {
      try {
        const response = await fetch("http://127.0.0.1:8000/api/status");
        if (response.ok) {
          clearInterval(checkReady);
          console.log("[Backend] Ready");
          resolve();
        }
      } catch {
        // Not ready yet
      }
    }, 500);
    
    // Timeout after 30 seconds
    setTimeout(() => {
      clearInterval(checkReady);
      if (pythonBackend) {
        reject(new Error("Backend startup timeout"));
      }
    }, 30000);
  });
}

function stopPythonBackend(): void {
  if (pythonBackend) {
    pythonBackend.kill("SIGTERM");
    pythonBackend = null;
  }
}

// --- STT (whisper.cpp subprocess) Management -------------------------------
function startSTTProcess(config: { model?: string; language?: string; threads?: number } = {}): Promise<void> {
  return new Promise((resolve, reject) => {
    if (sttProcess) {
      console.log("[STT] Process already running");
      resolve();
      return;
    }
    
    // Find whisper-cli executable
    const possiblePaths = [
      path.join(__dirname, "..", "resources", "bin", "whisper-cli"),
      path.join(__dirname, "..", "resources", "bin", "whisper-cli.exe"),
      path.join(process.cwd(), "whisper-cli"),
      path.join(process.cwd(), "whisper-cli.exe"),
      path.join(process.resourcesPath || "", "bin", "whisper-cli"),
      path.join(process.resourcesPath || "", "bin", "whisper-cli.exe"),
      "whisper-cli", // In PATH
    ];
    
    let whisperCli = null;
    for (const p of possiblePaths) {
      try {
        if (require("fs").existsSync(p)) {
          whisperCli = p;
          break;
        }
      } catch {}
    }
    
    if (!whisperCli) {
      // Check if in PATH
      try {
        require("child_process").execSync("which whisper-cli", { stdio: "ignore" });
        whisperCli = "whisper-cli";
      } catch {}
      
      try {
        require("child_process").execSync("where whisper-cli", { stdio: "ignore" });
        whisperCli = "whisper-cli.exe";
      } catch {}
    }
    
    if (!whisperCli) {
      reject(new Error("whisper-cli not found. Please build whisper.cpp or install via package manager."));
      return;
    }
    
    // Find model
    const modelName = config.model || "base.en";
    const modelPaths = [
      path.join(__dirname, "..", "resources", "models", `${modelName}.ggml`),
      path.join(__dirname, "..", "resources", "models", `${modelName}.bin`),
      path.join(process.cwd(), "models", `${modelName}.ggml`),
      path.join(process.cwd(), "models", `${modelName}.bin`),
      path.join(process.resourcesPath || "", "models", `${modelName}.ggml`),
      path.join(process.resourcesPath || "", "models", `${modelName}.bin`),
    ];
    
    let modelPath = null;
    for (const p of modelPaths) {
      try {
        if (require("fs").existsSync(p)) {
          modelPath = p;
          break;
        }
      } catch {}
    }
    
    if (!modelPath) {
      reject(new Error(`Whisper model not found: ${modelName}. Please download model to resources/models/`));
      return;
    }
    
    console.log("[STT] Starting whisper.cpp:", whisperCli, "with model:", modelPath);
    
    // whisper.cpp command for streaming
    const args = [
      '-m', modelPath,
      '-t', String(config.threads || 4),
      '-l', config.language || 'en',
      '--step', '500',        // Process every 500 ms
      '--length', '5000',     // 5 second context
      '-vth', '0.6',          // VAD threshold
      '-f', '-',              // Read from stdin
      '-otxt',                // Output text
    ];
    
    sttProcess = spawn(whisperCli, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
      windowsHide: true,
    });
    
    let stdoutBuffer = "";
    let stderrBuffer = "";
    
    sttProcess.stdout?.on("data", (data: Buffer) => {
      const text = data.toString("utf8");
      stdoutBuffer += text;
      
      // Process lines
      const lines = stdoutBuffer.split("\n");
      stdoutBuffer = lines.pop() || "";
      
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        
        // Check if it's a partial or final result
        // whisper.cpp outputs: [start --> end] text
        const match = trimmed.match(/^\[[\d:.]+ --> [\d:. ]+\]\s*(.+)$/);
        if (match) {
          const text = match[1].trim();
          if (text) {
            // Send to all renderer windows
            const windows = BrowserWindow.getAllWindows();
            windows.forEach((win) => {
              if (!win.isDestroyed()) {
                win.webContents.send("stt:partial", text);
              }
            });
          }
        }
      }
    });
    
    sttProcess.stderr?.on("data", (data: Buffer) => {
      stderrBuffer += data.toString("utf8");
    });
    
    sttProcess.on("error", (err) => {
      console.error("[STT] Process error:", err);
      reject(err);
    });
    
    sttProcess.on("exit", (code) => {
      console.log("[STT] Process exited with code:", code);
      sttProcess = null;
      if (code !== 0 && code !== null) {
        const windows = BrowserWindow.getAllWindows();
        windows.forEach((win) => {
          if (!win.isDestroyed()) {
            win.webContents.send("stt:error", `whisper.cpp exited with code ${code}: ${stderrBuffer}`);
          }
        });
      }
    });
    
    // Give it a moment to start
    setTimeout(() => resolve(), 500);
  });
}

function stopSTTProcess(): void {
  if (sttProcess) {
    sttProcess.kill("SIGTERM");
    sttProcess = null;
  }
}

// --- IPC Handlers -----------------------------------------------------------
function registerIPC() {
  // STT handlers
  ipcMain.handle("stt:start", async (_event, config) => {
    try {
      await startSTTProcess(config);
      return { success: true };
    } catch (error) {
      console.error("[STT] Failed to start:", error);
      return { 
        success: false, 
        error: error instanceof Error ? error.message : "Failed to start STT" 
      };
    }
  });
  
  ipcMain.handle("stt:write", async (_event, audioData: number[]) => {
    if (!sttProcess || !sttProcess.stdin?.writable) {
      return { success: false, error: "STT process not running" };
    }
    
    try {
      const pcm = new Int16Array(audioData);
      sttProcess.stdin?.write(Buffer.from(pcm.buffer));
      return { success: true };
    } catch (error) {
      return { 
        success: false, 
        error: error instanceof Error ? error.message : "Failed to write audio" 
      };
    }
  });
  
  ipcMain.handle("stt:end-segment", async () => {
    if (sttProcess) {
      sttProcess.stdin?.end();
    }
    return { success: true };
  });
  
  ipcMain.handle("stt:stop", async () => {
    stopSTTProcess();
    return { success: true };
  });
  
  ipcMain.handle("stt:status", async () => {
    return { running: !!sttProcess };
  });
  
  // Voice command proxy to Python backend
  ipcMain.handle("voice:command", async (_event, prompt: string) => {
    try {
      const response = await fetch("http://127.0.0.1:8000/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });
      return await response.json();
    } catch (error) {
      return { error: error instanceof Error ? error.message : "Failed" };
    }
  });
  
  // Streaming command endpoint
  ipcMain.handle("voice:command-stream", async (_event, prompt: string) => {
    try {
      const response = await fetch("http://127.0.0.1:8000/api/command/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });
      
      if (!response.ok || !response.body) {
        throw new Error("Stream failed");
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const events = [];
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");
        
        for (const line of lines) {
          if (line.startsWith("data:")) {
            const data = line.slice(5).trim();
            if (data && data !== "[DONE]") {
              try {
                events.push(JSON.parse(data));
              } catch {}
            }
          }
        }
      }
      
      return { events };
    } catch (error) {
      return { error: error instanceof Error ? error.message : "Stream failed" };
    }
  });
}

// --- Main App Lifecycle ----------------------------------------------------
app.whenReady().then(async () => {
  registerMediaPermissions();
  registerIPC();
  
  // Start Python backend
  try {
    await startPythonBackend();
  } catch (error) {
    console.error("[Main] Failed to start Python backend:", error);
  }
  
  mainWindow = createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopPythonBackend();
  stopSTTProcess();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopPythonBackend();
  stopSTTProcess();
});

// --- Security: Prevent navigation to external URLs -------------------------
app.on("web-contents-created", (_, contents) => {
  contents.on("will-navigate", (event, url) => {
    if (!url.startsWith("http://localhost") && !url.startsWith("file://")) {
      event.preventDefault();
    }
  });
});