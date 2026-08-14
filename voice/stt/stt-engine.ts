// stt-engine.ts
// whisper.cpp subprocess manager for streaming STT
// Runs in Electron Main Process

import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

interface STTConfig {
  model: string;
  sampleRate: number;
  language?: string;
  threads?: number;
}

interface STTResult {
  type: 'partial' | 'final';
  text: string;
  timestamp: number;
}

export class WhisperCppEngine extends EventEmitter {
  private process: ChildProcess | null = null;
  private config: STTConfig;
  private isRunning = false;
  private buffer = '';
  private modelPath: string;
  
  constructor(config: STTConfig) {
    super();
    this.config = {
      language: 'en',
      threads: 4,
      ...config
    };
    
    // Resolve model path
    this.modelPath = this.resolveModelPath(config.model);
  }
  
  private resolveModelPath(model: string): string {
    // Check common locations
    const possiblePaths = [
      path.join(__dirname, '..', 'resources', 'models', `${model}.ggml`),
      path.join(__dirname, '..', 'resources', 'models', `${model}.bin`),
      path.join(process.cwd(), 'models', `${model}.ggml`),
      path.join(process.cwd(), 'models', `${model}.bin`),
      path.join(process.resourcesPath || '', 'models', `${model}.ggml`),
      path.join(process.resourcesPath || '', 'models', `${model}.bin`),
    ];
    
    for (const p of possiblePaths) {
      try {
        if (require('fs').existsSync(p)) {
          return p;
        }
      } catch {}
    }
    
    // Default to relative path - will need to be configured
    return path.join(__dirname, '..', 'resources', 'models', `${model}.ggml`);
  }
  
  async start(): Promise<void> {
    if (this.isRunning) return;
    
    // Verify model exists
    const fs = require('fs');
    if (!fs.existsSync(this.modelPath)) {
      throw new Error(`Whisper model not found at: ${this.modelPath}`);
    }
    
    // whisper.cpp command for streaming
    // Using whisper-cli with streaming mode
    const args = [
      '-m', this.modelPath,
      '-t', String(this.config.threads),
      '-l', this.config.language || 'en',
      '--step', '500',        // Process every 500ms
      '--length', '5000',     // 5 second context
      '-vth', '0.6',          // VAD threshold
      '-f', '-',              // Read from stdin
      '-otxt',                // Output text
    ];
    
    // Try to find whisper-cli executable
    const whisperCli = this.findWhisperCli();
    if (!whisperCli) {
      throw new Error('whisper-cli not found. Please build whisper.cpp or install via package manager.');
    }
    
    console.log('[STT] Starting whisper.cpp:', whisperCli, args.join(' '));
    
    this.process = spawn(whisperCli, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env }
    });
    
    this.isRunning = true;
    this.buffer = '';
    
    // Handle stdout (transcription results)
    this.process.stdout?.on('data', (data: Buffer) => {
      const text = data.toString('utf8');
      this.handleOutput(text);
    });
    
    // Handle stderr
    this.process.stderr?.on('data', (data: Buffer) => {
      const text = data.toString('utf8');
      if (text.includes('error') || text.includes('Error')) {
        console.error('[STT] stderr:', text);
      }
    });
    
    // Handle process exit
    this.process.on('exit', (code) => {
      console.log('[STT] Process exited with code:', code);
      this.isRunning = false;
      if (code !== 0 && code !== null) {
        this.emit('error', new Error(`whisper.cpp exited with code ${code}`));
      }
    });
    
    // Give it a moment to start
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  
  private findWhisperCli(): string | null {
    const possiblePaths = [
      path.join(__dirname, '..', 'resources', 'bin', 'whisper-cli'),
      path.join(__dirname, '..', 'resources', 'bin', 'whisper-cli.exe'),
      path.join(process.cwd(), 'whisper-cli'),
      path.join(process.cwd(), 'whisper-cli.exe'),
      path.join(process.resourcesPath || '', 'bin', 'whisper-cli'),
      path.join(process.resourcesPath || '', 'bin', 'whisper-cli.exe'),
      'whisper-cli', // In PATH
    ];
    
    for (const p of possiblePaths) {
      try {
        if (require('fs').existsSync(p)) {
          return p;
        }
      } catch {}
    }
    
    // Check if in PATH
    try {
      require('child_process').execSync('which whisper-cli', { stdio: 'ignore' });
      return 'whisper-cli';
    } catch {}
    
    try {
      require('child_process').execSync('where whisper-cli', { stdio: 'ignore' });
      return 'whisper-cli.exe';
    } catch {}
    
    return null;
  }
  
  private handleOutput(text: string): void {
    this.buffer += text;
    
    // whisper.cpp outputs lines like:
    // [00:00.000 --> 00:02.000]  Hello world
    // Or partial results during streaming
    
    const lines = this.buffer.split('\n');
    this.buffer = lines.pop() || '';
    
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      
      // Parse whisper.cpp output format
      // [start --> end] text
      const match = trimmed.match(/^\[[\d:.]+ --> [\d:. ]+\]\s*(.+)$/);
      if (match) {
        const text = match[1].trim();
        if (text) {
          this.emit('result', {
            type: 'final',
            text,
            timestamp: Date.now()
          } as STTResult);
        }
        continue;
      }
      
      // Check for partial results (if whisper.cpp supports it)
      // Some versions output partials without timestamps
      if (trimmed && !trimmed.startsWith('[')) {
        this.emit('result', {
          type: 'partial',
          text: trimmed,
          timestamp: Date.now()
        } as STTResult);
      }
    }
  }
  
  // Send audio data to whisper.cpp stdin
  writeAudio(audio: Float32Array): void {
    if (!this.isRunning || !this.process?.stdin?.writable) {
      return;
    }
    
    // Convert Float32 (-1 to 1) to 16-bit PCM
    const pcm = new Int16Array(audio.length);
    for (let i = 0; i < audio.length; i++) {
      const s = Math.max(-1, Math.min(1, audio[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    // Write as raw PCM
    this.process.stdin?.write(Buffer.from(pcm.buffer));
  }
  
  // Signal end of audio segment
  endSegment(): void {
    if (this.process?.stdin?.writable) {
      this.process.stdin.end();
    }
  }
  
  async stop(): Promise<void> {
    this.isRunning = false;
    
    if (this.process) {
      this.process.kill('SIGTERM');
      
      // Wait for exit
      await new Promise(resolve => {
        if (this.process) {
          this.process.once('exit', resolve);
          // Force kill after 2 seconds
          setTimeout(() => {
            if (this.process && !this.process.killed) {
              this.process.kill('SIGKILL');
            }
            resolve();
          }, 2000);
        } else {
          resolve();
        }
      });
      
      this.process = null;
    }
  }
  
  getIsRunning(): boolean {
    return this.isRunning;
  }
}

// Singleton instance
let sttEngineInstance: WhisperCppEngine | null = null;

export function getSTTEngine(config?: STTConfig): WhisperCppEngine {
  if (!sttEngineInstance && config) {
    sttEngineInstance = new WhisperCppEngine(config);
  }
  return sttEngineInstance!;
}

export function createSTTEngine(config: STTConfig): WhisperCppEngine {
  if (sttEngineInstance) {
    sttEngineInstance.removeAllListeners();
    sttEngineInstance.stop().catch(() => {});
  }
  sttEngineInstance = new WhisperCppEngine(config);
  return sttEngineInstance;
}