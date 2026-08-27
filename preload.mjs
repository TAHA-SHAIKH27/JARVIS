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
  show: (title, body) => {
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((perm) => {
        if (perm === "granted") new Notification(title, { body });
      });
    }
  },
});
