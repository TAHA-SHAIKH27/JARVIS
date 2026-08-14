export interface AudioChunk {
  samples: Float32Array;
  timestamp: number;
  sampleRate: number;
}

export interface WakeWordResult {
  detected: boolean;
  keyword: string;
  score: number;
  timestamp: number;
}

export interface STTPartialResult {
  text: string;
  isFinal: false;
  timestamp: number;
}

export interface STTFinalResult {
  text: string;
  isFinal: true;
  timestamp: number;
  confidence?: number;
}

export type STTResult = STTPartialResult | STTFinalResult;

export interface TranscriptEvent {
  type: 'partial' | 'final';
  text: string;
  timestamp: number;
}

export interface LatencyMetrics {
  micStart: number;
  wakeDetected: number;
  sttFirstPartial: number;
  sttFinal: number;
  geminiStart: number;
  geminiFirstToken: number;
  actionStart: number;
  ttsStart: number;
  ttsFirstAudio: number;
  actionComplete: number;
}

export interface VoiceConfig {
  sampleRate: number;
  channels: number;
  wakeWordSensitivity: number;
  sttModel: string;
  vadSilenceThreshold: number;
  maxUtteranceDuration: number;
  commandFinalizeDelay: number;
  conversationFinalizeDelay: number;
}

export const DEFAULT_VOICE_CONFIG: VoiceConfig = {
  sampleRate: 16000,
  channels: 1,
  wakeWordSensitivity: 0.5,
  sttModel: 'base.en',
  vadSilenceThreshold: 400,
  maxUtteranceDuration: 3000,
  commandFinalizeDelay: 200,
  conversationFinalizeDelay: 800,
};

export interface ActionExecution {
  type: 'action';
  action: {
    type: string;
    [key: string]: unknown;
  };
}

export interface SpeakChunk {
  type: 'speak';
  text: string;
}

export type CommandStreamEvent = ActionExecution | SpeakChunk;