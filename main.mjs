import { app, BrowserWindow, session, ipcMain } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let pythonBackend = null;

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
    win.loadURL("http://localhost:3000");
    // Open DevTools in development
    win.webContents.openDevTools();
  }

  return win;
}

let mainWindow = null;

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
function startPythonBackend() {
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

function stopPythonBackend() {
  if (pythonBackend) {
    pythonBackend.kill("SIGTERM");
    pythonBackend = null;
  }
}

// --- IPC Handlers -----------------------------------------------------------
function registerIPC() {
  // Voice command proxy to Python backend
  ipcMain.handle("voice:command", async (_event, prompt) => {
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
  ipcMain.handle("voice:command-stream", async (_event, prompt) => {
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
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopPythonBackend();
});

// --- Security: Prevent navigation to external URLs -------------------------
app.on("web-contents-created", (_, contents) => {
  contents.on("will-navigate", (event, url) => {
    if (!url.startsWith("http://localhost") && !url.startsWith("file://")) {
      event.preventDefault();
    }
  });
});
