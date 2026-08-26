// preload.mjs
// Preload script for Electron - exposes safe APIs to renderer

import { contextBridge, ipcRenderer } from "electron";

// Voice API exposed to renderer
contextBridge.exposeInMainWorld("voiceAPI", {});

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
    voiceAPI: Record<string, never>;
    systemAPI: {
      getPlatform: () => string;
      getVersion: () => string;
    };
    notificationAPI: {
      show: (title: string, body: string) => void;
    };
  }
}