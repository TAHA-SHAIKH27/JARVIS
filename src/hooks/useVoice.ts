// useVoice.ts
// Main React hook for JARVIS voice pipeline
// Coordinates: AudioWorklet -> Wake Word -> STT -> Gemini -> TTS

import { useState, useEffect, useRef, useCallback } from 'react';
import { 
  AudioChunk, 
  WakeWordResult, 
  STTResult, 
  LatencyMetrics, 
  VoiceConfig, 
  DEFAULT_VOICE_CONFIG,
  TranscriptEvent,
  CommandStreamEvent
} from '../../voice/types';

interface UseVoiceOptions {
  config?: Partial<VoiceConfig>;
  onTranscript?: (event: TranscriptEvent) => void;
  onAction?: (action: CommandStreamEvent) => void;
  onError?: (error: string) => void;
  onLatency?: (metrics: Partial<LatencyMetrics>) => void;
}

interface UseVoiceReturn {
  isListening: boolean;
  isWakeDetected: boolean;
  isProcessing: boolean;
  isSpeaking: boolean;
  transcript: string;
  partialTranscript: string;
  latency: Partial<LatencyMetrics>;
  startListening: () => Promise<void>;
  stopListening: () => void;
  toggleListening: () => Promise<void>;
}

export function useVoice(options: UseVoiceOptions = {}): UseVoiceReturn {
  const {
    config = DEFAULT_VOICE_CONFIG,
    onTranscript,
    onAction,
    onError,
    onLatency,
  } = options;
  
  // Merged config
  const mergedConfig: VoiceConfig = { ...DEFAULT_VOICE_CONFIG, ...config };
  
  // State
  const [isListening, setIsListening] = useState(false);
  const [isWakeDetected, setIsWakeDetected] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [partialTranscript, setPartialTranscript] = useState('');
  const [latency, setLatency] = useState<Partial<LatencyMetrics>>({});
  
  // Refs
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wakeWorkerRef = useRef<Worker | null>(null);
  const ringBufferRef = useRef<Float32Array | null>(null);
  const isRecordingRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const utteranceStartRef = useRef<number>(0);
  const lastPartialRef = useRef<string>('');
  const sttResultCleanupRef = useRef<() => void | null>(null);
  const sttErrorCleanupRef = useRef<() => void | null>(null);
  const latencyRef = useRef<LatencyMetrics>({
    micStart: 0,
    wakeDetected: 0,
    sttFirstPartial: 0,
    sttFinal: 0,
    geminiStart: 0,
    geminiFirstToken: 0,
    actionStart: 0,
    ttsStart: 0,
    ttsFirstAudio: 0,
    actionComplete: 0,
  });
  
  // Configuration
  const porcupineAccessKey = import.meta.env.VITE_PORCUPINE_ACCESS_KEY || '';
  
  // Initialize latency reporting
  const reportLatency = useCallback((metrics: Partial<LatencyMetrics>) => {
    setLatency(prev => ({ ...prev, ...metrics }));
    onLatency?.(metrics);
  }, [onLatency]);
  
  // Initialize wake word worker
  const initWakeWorker = useCallback(async (): Promise<boolean> => {
    if (wakeWorkerRef.current) return true;
    
    if (!porcupineAccessKey) {
      console.warn('[Voice] Porcupine AccessKey not configured. Set VITE_PORCUPINE_ACCESS_KEY in .env. Wake word detection will be disabled.');
      // Don't error - just disable wake word
      return true;
    }
    
    const worker = new Worker(
      new URL('../wake-worker.ts', import.meta.url),
      { type: 'module' }
    );
    
    worker.onmessage = (event) => {
      const { type, keyword, score, error } = event.data;
      
      switch (type) {
        case 'READY':
          console.log('[Voice] Wake word engine ready:', keyword);
          break;
        case 'DETECTED':
          console.log('[Voice] Wake word detected:', keyword, 'score:', score);
          handleWakeDetected(keyword || 'jarvis', score || 0);
          break;
        case 'ERROR':
          console.error('[Voice] Wake worker error:', error);
          onError?.(error);
          break;
        case 'KEY_MISSING':
          console.warn('[Voice] Porcupine AccessKey missing:', error);
          break;
      }
    };
    
    worker.onerror = (error) => {
      console.error('[Voice] Wake worker error:', error);
      onError?.('Wake word worker error');
    };
    
    // Initialize Porcupine
    worker.postMessage({
      type: 'INIT',
      accessKey: porcupineAccessKey,
      keywords: ['jarvis']
    });
    
    wakeWorkerRef.current = worker;
    return true;
  }, [porcupineAccessKey, onError]);
  
  // Handle wake word detection
  const handleWakeDetected = useCallback((keyword: string, score: number) => {
    const now = performance.now();
    latencyRef.current.wakeDetected = now;
    reportLatency({ wakeDetected: now - latencyRef.current.micStart });
    
    setIsWakeDetected(true);
    
    // Visual feedback
    playWakeBeep();
    
    // Start STT recording from ring buffer
    startSTTRecording();
    
    // Reset wake detection after short delay
    setTimeout(() => setIsWakeDetected(false), 500);
  }, [reportLatency]);
  
  // Play wake beep
  const playWakeBeep = useCallback(() => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 800;
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.1);
    } catch (e) {
      console.warn('[Voice] Could not play beep:', e);
    }
  }, []);
  
  // Start STT recording from ring buffer
  const startSTTRecording = useCallback(async () => {
    if (isRecordingRef.current) return;
    
    // Get ring buffer from AudioWorklet
    if (processorRef.current) {
      processorRef.current.port.postMessage({ type: 'STT_START' });
      processorRef.current.port.postMessage({ type: 'GET_BUFFER' });
    }
    
    isRecordingRef.current = true;
    utteranceStartRef.current = performance.now();
    setIsProcessing(true);
    lastPartialRef.current = '';
  }, []);
  
  // Handle ring buffer response from AudioWorklet
  const handleRingBuffer = useCallback((buffer: Float32Array, validSamples: number) => {
    if (!isRecordingRef.current) return;
    
    // Send to STT (whisper.cpp subprocess via Electron IPC or HTTP)
    sendToSTT(buffer.subarray(0, validSamples));
  }, []);
  
  // Send audio to whisper.cpp subprocess via Electron IPC or HTTP fallback
  const sendToSTT = useCallback(async (audio: Float32Array) => {
    // Convert Float32 to 16-bit PCM
    const pcm = new Int16Array(audio.length);
    for (let i = 0; i < audio.length; i++) {
      const s = Math.max(-1, Math.min(1, audio[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    if (window.voiceAPI) {
      // Electron mode: send via IPC
      try {
        await window.voiceAPI.writeSTT(Array.from(pcm));
      } catch (error) {
        console.error('[Voice] Failed to send audio to STT via IPC:', error);
      }
    } else {
      // Localhost mode: send via HTTP to /api/stt/transcribe
      try {
        const formData = new FormData();
        const blob = new Blob([new Int16Array(pcm).buffer], { type: 'audio/wav' });
        formData.append('audio', blob, 'recording.wav');
        
        const response = await fetch('/api/stt/transcribe', {
          method: 'POST',
          body: formData
        });
        
        const data = await response.json();
        if (data.status === 'success' && data.text) {
          handleSTTFinal(data.text);
        } else if (data.status === 'error') {
          console.warn('[Voice] HTTP STT error:', data.message);
        }
      } catch (error) {
        console.error('[Voice] Failed to send audio to STT via HTTP:', error);
      }
    }
  }, []);
  
  // VAD/Silence detection for finalizing STT
  const checkSilence = useCallback(() => {
    if (!isRecordingRef.current) return;
    
    const now = performance.now();
    const elapsed = now - utteranceStartRef.current;
    
    // Check if we've exceeded max utterance duration
    if (elapsed > 30000) { // 30 seconds max
      console.log('[Voice] Max utterance duration reached, finalizing');
      finalizeSTT();
      return;
    }
    
    // Check for silence (no partial updates for a while)
    // This would be triggered by STT partial results
    // For now, we rely on the STT engine's VAD
    
    // Reschedule check
    silenceTimerRef.current = setTimeout(checkSilence, 500);
  }, []);
  
  // Handle STT partial results
  const handleSTTPartial = useCallback((text: string) => {
    if (!isRecordingRef.current) return;
    
    setPartialTranscript(text);
    lastPartialRef.current = text;
    
    // Report first partial latency
    if (latencyRef.current.sttFirstPartial === 0) {
      latencyRef.current.sttFirstPartial = performance.now();
      reportLatency({ 
        sttFirstPartial: latencyRef.current.sttFirstPartial - latencyRef.current.wakeDetected 
      });
    }
    
    // Reset silence timer on new partial
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
    }
    
    // Command mode: shorter silence threshold (400ms)
    // Conversation mode: longer silence threshold (800ms)
    const silenceThreshold = 400; // ms
    
    silenceTimerRef.current = setTimeout(() => {
      console.log('[Voice] Silence detected, finalizing STT');
      finalizeSTT();
    }, silenceThreshold);
  }, [reportLatency]);
  
  // Handle STT final result
  const handleSTTFinal = useCallback((text: string) => {
    console.log('[Voice] STT Final:', text);
    
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    
    latencyRef.current.sttFinal = performance.now();
    reportLatency({ 
      sttFinal: latencyRef.current.sttFinal - latencyRef.current.sttFirstPartial 
    });
    
    finalizeSTT(text);
  }, [reportLatency]);
  
  // Finalize STT and send to Gemini
  const finalizeSTT = useCallback(async (finalText?: string) => {
    const text = finalText || lastPartialRef.current;
    console.log('[Voice] STT Final:', text);
    
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    
    isRecordingRef.current = false;
    setIsProcessing(false);
    setPartialTranscript('');
    
    if (!text.trim()) return;
    
    setTranscript(text);
    onTranscript?.({ type: 'final', text, timestamp: Date.now() });
    
    // Send to Gemini streaming endpoint
    await sendToGemini(text);
  }, [onTranscript]);
  
  // Send transcript to Gemini streaming endpoint
  const sendToGemini = useCallback(async (text: string) => {
    const now = performance.now();
    latencyRef.current.geminiStart = now;
    reportLatency({ geminiStart: now - latencyRef.current.micStart });
    
    try {
      const response = await fetch('/api/command/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      });
      
      if (!response.ok || !response.body) {
        throw new Error('Gemini stream failed');
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let actionBuffer = '';
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        actionBuffer += chunk;
        
        // Process SSE events
        const lines = actionBuffer.split('\n');
        actionBuffer = lines.pop() || '';
        
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          
          const dataStr = line.slice(5).trim();
          if (!dataStr || dataStr === '[DONE]') continue;
          
          try {
            const event: CommandStreamEvent = JSON.parse(dataStr);
            
            if (event.type === 'action') {
              latencyRef.current.actionStart = performance.now();
              reportLatency({ 
                actionStart: latencyRef.current.actionStart - latencyRef.current.geminiStart 
              });
              onAction?.(event);
            } else if (event.type === 'speak') {
              latencyRef.current.ttsStart = performance.now();
              reportLatency({ 
                ttsStart: latencyRef.current.ttsStart - latencyRef.current.geminiStart 
              });
              await speakText(event.text);
            }
          } catch (e) {
            console.warn('[Voice] Failed to parse SSE event:', e);
          }
        }
      }
    } catch (error) {
      console.error('[Voice] Gemini error:', error);
      onError?.('Failed to get response from JARVIS');
    }
  }, [onAction, reportLatency]);
  
  // TTS queue
  const ttsQueueRef = useRef<string[]>([]);
  const ttsSpeakingRef = useRef(false);
  
  const speakText = useCallback(async (text: string): Promise<void> => {
    return new Promise((resolve) => {
      // Split into sentences for streaming TTS
      const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
      ttsQueueRef.current.push(...sentences);
      
      const processQueue = () => {
        if (ttsSpeakingRef.current || ttsQueueRef.current.length === 0) {
          resolve();
          return;
        }
        
        ttsSpeakingRef.current = true;
        setIsSpeaking(true);
        
        const sentence = ttsQueueRef.current.shift()!;
        const utterance = new SpeechSynthesisUtterance(sentence);
        utterance.rate = 1.0;
        utterance.pitch = 0.85;
        
        const voices = window.speechSynthesis.getVoices();
        utterance.voice = voices.find(v => v.lang.startsWith('en')) || voices[0];
        
        utterance.onstart = () => {
          if (latencyRef.current.ttsFirstAudio === 0) {
            latencyRef.current.ttsFirstAudio = performance.now();
            reportLatency({ 
              ttsFirstAudio: latencyRef.current.ttsFirstAudio - latencyRef.current.ttsStart 
            });
          }
        };
        
        utterance.onend = () => {
          ttsSpeakingRef.current = false;
          setIsSpeaking(ttsQueueRef.current.length > 0);
          processQueue();
        };
        
        utterance.onerror = () => {
          ttsSpeakingRef.current = false;
          setIsSpeaking(ttsQueueRef.current.length > 0);
          processQueue();
        };
        
        window.speechSynthesis.speak(utterance);
      };
      
      if (!ttsSpeakingRef.current) {
        processQueue();
      }
    });
  }, [reportLatency]);
  
  // Start listening
  const startListening = useCallback(async () => {
    if (isListening) return;
    
    try {
      // Initialize wake word engine
      const wakeReady = await initWakeWorker();
      if (!wakeReady) return;
      
      // Create AudioContext
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioCtx({ sampleRate: mergedConfig.sampleRate });
      audioContextRef.current = audioContext;
      
      // Verify actual sample rate
      console.log('[Voice] AudioContext sample rate:', audioContext.sampleRate);
      
      // Load AudioWorklet
      await audioContext.audioWorklet.addModule('/voice-processor.js');
      
      // Get microphone
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: mergedConfig.sampleRate,
          channelCount: mergedConfig.channels,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      streamRef.current = stream;
      
      // Create processor
      const processor = new AudioWorkletNode(audioContext, 'voice-processor');
      processorRef.current = processor;
      
      // Handle messages from AudioWorklet
      processor.port.onmessage = (event) => {
        const { type, buffer, validSamples, rms, timestamp } = event.data;
        
        switch (type) {
          case 'AUDIO':
            // Forward to wake word worker
            if (wakeWorkerRef.current) {
              wakeWorkerRef.current.postMessage(
                { type: 'AUDIO', buffer },
                [buffer.buffer]
              );
            }
            break;
          case 'RING_BUFFER':
            handleRingBuffer(buffer, validSamples);
            break;
          case 'VOLUME':
            // Could update UI volume meter
            break;
        }
      };
      
      // Connect audio graph
      const source = audioContext.createMediaStreamSource(stream);
      source.connect(processor);
      processor.connect(audioContext.destination);
      
      // Start wake word detection
      if (wakeWorkerRef.current) {
        wakeWorkerRef.current.postMessage({ type: 'INIT' });
      }
      
      // Start silence checking
      checkSilence();
      
      // Start latency tracking
      latencyRef.current.micStart = performance.now();
      reportLatency({ micStart: 0 });
      
      setIsListening(true);
      console.log('[Voice] Listening started');
      
    } catch (error) {
      console.error('[Voice] Failed to start listening:', error);
      onError?.('Microphone access denied or unavailable');
      stopListening();
    }
  }, [mergedConfig, initWakeWorker, handleRingBuffer, reportLatency, onError]);
  
  // Stop listening
  const stopListening = useCallback(() => {
    // Stop wake word worker
    if (wakeWorkerRef.current) {
      wakeWorkerRef.current.postMessage({ type: 'STOP' });
      wakeWorkerRef.current.terminate();
      wakeWorkerRef.current = null;
    }
    
    // Stop AudioWorklet
    if (processorRef.current) {
      processorRef.current.port.postMessage({ type: 'PORCUPINE_STOP' });
      processorRef.current.port.postMessage({ type: 'STT_STOP' });
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    
    // Stop media stream
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    
    // Cleanup STT listeners
    if (sttResultCleanupRef.current) {
      sttResultCleanupRef.current();
      sttResultCleanupRef.current = null;
    }
    if (sttErrorCleanupRef.current) {
      sttErrorCleanupRef.current();
      sttErrorCleanupRef.current = null;
    }
    
    // Stop STT engine
    if (window.voiceAPI) {
      window.voiceAPI.stopSTT().catch(() => {});
    }
    
    // Cancel any pending timers
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    
    // Cancel TTS
    window.speechSynthesis.cancel();
    ttsQueueRef.current = [];
    ttsSpeakingRef.current = false;
    
    isRecordingRef.current = false;
    setIsListening(false);
    setIsWakeDetected(false);
    setIsProcessing(false);
    setIsSpeaking(false);
    setPartialTranscript('');
    
    console.log('[Voice] Listening stopped');
  }, []);
  
  // Toggle listening
  const toggleListening = useCallback(async () => {
    if (isListening) {
      stopListening();
    } else {
      await startListening();
    }
  }, [isListening, startListening, stopListening]);
  
  // Expose STT handlers for Electron IPC
  useEffect(() => {
    if (!window.voiceAPI) return;
    
    const handlePartial = (text: string) => handleSTTPartial(text);
    const handleFinal = (text: string) => handleSTTFinal(text);
    
    const cleanupPartial = window.voiceAPI.onSTTPartial(handlePartial);
    const cleanupFinal = window.voiceAPI.onSTTFinal(handleFinal);
    
    return () => {
      cleanupPartial();
      cleanupFinal();
    };
  }, [handleSTTPartial, handleSTTFinal]);
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopListening();
    };
  }, [stopListening]);
  
  return {
    isListening,
    isWakeDetected,
    isProcessing,
    isSpeaking,
    transcript,
    partialTranscript,
    latency,
    startListening,
    stopListening,
    toggleListening,
  };
}

// Helper to ensure voices are loaded
if (typeof window !== 'undefined' && window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => {
    // Voices loaded
  };
}