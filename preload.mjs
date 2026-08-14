// preload.mjs
// Preload script for Electron - exposes safe APIs to renderer

import { contextBridge, ipcRenderer } from "electron";

// Voice API exposed to renderer
contextBridge.exposeInMainWorld("voiceAPI", {
  // STT
  startSTT: (config?: { model?: string; language?: string; threads?: number }) =>
    ipcRenderer.invoke("stt:start", config),
  
  writeSTT: (audioData: number[]) =>
    ipcRenderer.invoke("stt:write", audioData),
  
  endSTTSegment: () =>
    ipcRenderer.invoke("stt:end-segment"),
  
  stopSTT: () =>
    ipcRenderer.invoke("stt:stop"),
  
  getSTTStatus: () =>
    ipcRenderer.invoke("stt:status"),
  
  // Voice commands
  sendCommand: (prompt: string) =>
    ipcRenderer.invoke("voice:command", prompt),
  
  sendCommandStream: (prompt: string) =>
    ipcRenderer.invoke("voice:command-stream", prompt),
  
  // Event listeners
  onSTTResult: (callback: (result: { type: 'partial' | 'final'; text: string; timestamp: number }) => void) => {
    const handler = (_event: any, result: any) => callback(result);
    ipcRenderer.on("stt:result", handler);
    return () => ipcRenderer.off("stt:result", handler);
  },
  
  onSTTError: (callback: (error: string) => void) => {
    const handler = (_event: any, error: string) => callback(error);
    ipcRenderer.on("stt:error", handler);
    return () => ipcRenderer.off("stt:error", handler);
  },
  
  // Voice commands
  sendCommand: (prompt: string) =>
    ipcRenderer.invoke("voice:command", prompt),
  
  sendCommandStream: (prompt: string) =>
    ipcRenderer.invoke("voice:command-stream", prompt),
});

// System info API
contextBridge.exposeInMainWorld("systemAPI", {
  getPlatform: () => process.platform,
  getVersion: () => process.versions.electron,
});

// Notification API
contextBridge.exposeInMainWorld("notificationAPI", {
  show: (title: string, body: string) => {
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((perm) => {
        if (perm === "granted") new Notification(title, { body });
      });
    }
  },
});

// Type declarations for TypeScript
declare global {
  interface Window {
    voiceAPI: {
      startSTT: (config?: { model?: string; language?: string; threads?: number }) => Promise<{ success: boolean; error?: string }>;
      writeSTT: (audioData: number[]) => Promise<{ success: boolean; error?: string }>;
      endSTTSegment: () => Promise<{ success: boolean; error?: string }>;
      stopSTT: () => Promise<{ success: boolean; error?: string }>;
      getSTTStatus: () => Promise<{ running: boolean }>;
      sendCommand: (prompt: string) => Promise<any>;
      sendCommandStream: (prompt: string) => Promise<{ events?: any[]; error?: string }>;
      onSTTResult: (callback: (result: { type: 'partial' | 'final'; text: string; timestamp: number }) => void) => () => void;
      onSTTError: (callback: (error: string) => void) => () => void;
    };
    systemAPI: {
      getPlatform: () => string;
      getVersion: () => string;
    };
    notificationAPI: {
      show: (title: string, body: string) => void;
    };
  }
}