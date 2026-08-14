// wake-worker.ts
// Web Worker for Porcupine wake-word detection
// Runs independently from main thread

import { PorcupineWorker, BuiltInKeyword, PorcupineOptions } from '@picovoice/porcupine-web';

interface WorkerMessage {
  type: 'INIT' | 'AUDIO' | 'STOP' | 'SET_ACCESS_KEY';
  accessKey?: string;
  keywords?: string[];
  buffer?: Float32Array;
}

interface WorkerResponse {
  type: 'READY' | 'DETECTED' | 'ERROR' | 'VOLUME' | 'KEY_MISSING';
  keyword?: string;
  score?: number;
  rms?: number;
  error?: string;
}

let porcupineWorker: PorcupineWorker | null = null;
let isProcessing = false;
let accessKey: string | null = null;
let initAttempted = false;

self.onmessage = async (event: MessageEvent<WorkerMessage>) => {
  const { type, accessKey: msgAccessKey, keywords, buffer } = event.data;
  
  switch (type) {
    case 'SET_ACCESS_KEY':
      accessKey = msgAccessKey || null;
      if (accessKey && !initAttempted) {
        initializePorcupine();
      }
      break;
      
    case 'INIT':
      if (!accessKey) {
        postMessage({ 
          type: 'KEY_MISSING', 
          error: 'Porcupine AccessKey not configured. Set VITE_PORCUPINE_ACCESS_KEY in .env' 
        } as WorkerResponse);
        break;
      }
      await initializePorcupine();
      break;
      
    case 'AUDIO':
      if (porcupineWorker && isProcessing && buffer) {
        try {
          // Convert Float32 to Int16 for Porcupine
          const pcm = new Int16Array(buffer.length);
          for (let i = 0; i < buffer.length; i++) {
            const s = Math.max(-1, Math.min(1, buffer[i]));
            pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          
          porcupineWorker.process(pcm);
        } catch (error) {
          console.error('[WakeWorker] Processing error:', error);
        }
      }
      break;
      
    case 'STOP':
      isProcessing = false;
      if (porcupineWorker) {
        await porcupineWorker.release();
        porcupineWorker = null;
      }
      break;
  }
};

async function initializePorcupine(): Promise<void> {
  if (initAttempted) return;
  initAttempted = true;
  
  if (!accessKey) {
    postMessage({ 
      type: 'KEY_MISSING', 
      error: 'Porcupine AccessKey not configured. Set VITE_PORCUPINE_ACCESS_KEY in .env' 
    } as WorkerResponse);
    return;
  }
  
  try {
    const keywordList = ['jarvis'].map(k => k as BuiltInKeyword);
    
    porcupineWorker = await PorcupineWorker.create(
      accessKey,
      keywordList,
      (keywordIndex: number) => {
        // Detection callback
        if (porcupineWorker) {
          const keywordLabels = ['jarvis']; 
          const keyword = keywordLabels[keywordIndex] || 'jarvis';
          postMessage({ 
            type: 'DETECTED', 
            keyword,
            score: 1.0,
            timestamp: Date.now()
          } as WorkerResponse);
        }
      },
      { publicPath: 'porcupine_params.pv' } as any, // model
      {} as PorcupineOptions
    );
    
    isProcessing = true;
    postMessage({ type: 'READY', keyword: 'jarvis' } as WorkerResponse);
  } catch (error) {
    postMessage({ 
      type: 'ERROR', 
      error: error instanceof Error ? error.message : 'Failed to initialize Porcupine' 
    } as WorkerResponse);
  }
}