// stt-ipc.ts
// IPC handlers for STT in Electron Main Process
// Exposes STT functionality to renderer

import { ipcMain, IpcMainInvokeEvent } from 'electron';
import { WhisperCppEngine, createSTTEngine } from './stt-engine';
import { STTResult } from './stt-engine';

let sttEngine: WhisperCppEngine | null = null;
let currentSessionId = 0;

export function initializeSTTIPC(): void {
  // Start STT engine
  ipcMain.handle('stt:start', async (_event: IpcMainInvokeEvent, config: {
    model?: string;
    language?: string;
    threads?: number;
  }) => {
    try {
      if (sttEngine) {
        await sttEngine.stop();
      }
      
      sttEngine = createSTTEngine({
        model: config.model || 'base.en',
        language: config.language || 'en',
        threads: config.threads || 4,
      });
      
      await sttEngine.start();
      
      // Forward results to renderer
      sttEngine.on('result', (result: STTResult) => {
        // Broadcast to all renderer windows
        const windows = require('electron').BrowserWindow.getAllWindows();
        windows.forEach((win: any) => {
          if (!win.isDestroyed()) {
            win.webContents.send('stt:result', result);
          }
        });
      });
      
      sttEngine.on('error', (error: Error) => {
        console.error('[STT] Engine error:', error);
        const windows = require('electron').BrowserWindow.getAllWindows();
        windows.forEach((win: any) => {
          if (!win.isDestroyed()) {
            win.webContents.send('stt:error', error.message);
          }
        });
      });
      
      return { success: true };
    } catch (error) {
      console.error('[STT] Failed to start:', error);
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'Failed to start STT' 
      };
    }
  });
  
  // Send audio to STT
  ipcMain.handle('stt:write', async (_event: IpcMainInvokeEvent, audioData: number[]) => {
    if (!sttEngine || !sttEngine.getIsRunning()) {
      return { success: false, error: 'STT engine not running' };
    }
    
    try {
      const audio = new Float32Array(audioData);
      sttEngine.writeAudio(audio);
      return { success: true };
    } catch (error) {
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'Failed to write audio' 
      };
    }
  });
  
  // End current segment
  ipcMain.handle('stt:end-segment', async () => {
    if (!sttEngine) {
      return { success: false, error: 'STT engine not initialized' };
    }
    
    sttEngine.endSegment();
    return { success: true };
  });
  
  // Stop STT engine
  ipcMain.handle('stt:stop', async () => {
    if (sttEngine) {
      await sttEngine.stop();
      sttEngine = null;
    }
    return { success: true };
  });
  
  // Get STT status
  ipcMain.handle('stt:status', async () => {
    return { 
      running: sttEngine?.getIsRunning() || false 
    };
  });
  
  // Cleanup on app quit
  const { app } = require('electron');
  app.on('before-quit', async () => {
    if (sttEngine) {
      await sttEngine.stop();
      sttEngine = null;
    }
  });
}