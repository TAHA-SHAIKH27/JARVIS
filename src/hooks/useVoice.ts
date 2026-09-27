// useVoice.ts
// Standard browser Web Speech API voice pipeline hook for JARVIS.
// Coordinates SpeechRecognition, speechSynthesis, and Web Audio API mic-level visualization.

import { useState, useEffect, useRef, useCallback } from 'react';

declare global {
  interface Window {
    jarvisAudioLevel?: number;
  }
}

export interface UseVoiceReturn {
  isListening: boolean; // Continuous wake word listening active
  isWakeDetected: boolean; // Wake word detected state (flashes green in UI)
  isProcessing: boolean; // Transcribing/executing command
  isSpeaking: boolean; // TTS speaking state
  transcript: string; // Final transcript of the last utterance
  partialTranscript: string; // Interim results
  latency: Record<string, number>; // Compatibility placeholder
  startListening: () => Promise<void>; // Begin continuous listening
  stopListening: () => void; // End continuous listening
  toggleListening: () => Promise<void>; // Toggle continuous mode
  isPushToTalkActive: boolean; // Push-to-Talk active
  startPushToTalk: () => Promise<void>; // Start PTT
  stopPushToTalk: () => Promise<string>; // Stop PTT and return final transcript
  _setExecuteCommand: (fn: (text: string) => void) => void; // Connect command executor
}

interface UseVoiceOptions {
  onTranscript?: (event: { type: 'final'; text: string; timestamp: number }) => void;
  onError?: (error: string) => void;
  muted?: boolean; // when true the hook never speaks (e.g. wake-word "Yes?")
}

export function useVoice(options: UseVoiceOptions = {}): UseVoiceReturn {
  // ---------- State ----------
  const [isListening, setIsListening] = useState(false);
  const [isWakeDetected, setIsWakeDetected] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [partialTranscript, setPartialTranscript] = useState('');
  const [isPushToTalkActive, setIsPushToTalkActive] = useState(false);

  // ---------- Refs for stable callback execution ----------
  const isListeningRef = useRef(false);
  const isPushToTalkActiveRef = useRef(false);
  const isMutedForTTSRef = useRef(false);
  const awaitingFinalPttRef = useRef(false);
  const executeCommandRef = useRef<((text: string) => void) | null>(null);

  // ---------- Barge-in refs (interrupt JARVIS mid-reply by voice) ----------
  // Recognition now STAYS ALIVE during TTS. Results arriving while JARVIS
  // speaks are ignored unless they carry a barge-in cue — this is what lets
  // the user cut in with "Jarvis, …" / "stop" / "wait" instead of waiting.
  const ttsPlayingRef = useRef(false);
  // Rolling window of what JARVIS recently said (lowercase) for echo guard.
  const lastSpokenRef = useRef('');
  // WAKE | COMMAND listen state lives in a ref so barge-in can drive it.
  const listenStateRef = useRef<'WAKE' | 'COMMAND'>('WAKE');
  const bargeRevertTimerRef = useRef<any>(null);

  // Words that cut through JARVIS speech. Ordered longest-first for stripping.
  const BARGE_CUES = ['hey jarvis', 'hold on', 'jarvis', 'listen', 'stop', 'wait', 'quiet', 'shush', 'hey'];
  const bargedAtRef = useRef(0);

  // Whole-word cue match ("they" must not trigger on "hey").
  const cueIn = (text: string): string | undefined => {
    for (const c of BARGE_CUES) {
      const pattern = new RegExp(`\\b${c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
      if (pattern.test(text)) return c;
    }
    return undefined;
  };
  const cueLeads = (text: string): boolean => {
    for (const c of BARGE_CUES) {
      const pattern = new RegExp(`^${c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
      if (pattern.test(text)) return true;
    }
    return false;
  };
  const stripLeadingCue = (text: string): string => {
    for (const c of [...BARGE_CUES].sort((a, b) => b.length - a.length)) {
      const pattern = new RegExp(`^${c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b[\\s,]*`);
      if (pattern.test(text)) return text.replace(pattern, '');
    }
    return text;
  };

  // Mute flag from the host app (single "mute JARVIS" control). Read via ref
  // at speak time so callbacks never go stale.
  const mutedRef = useRef(false);
  useEffect(() => {
    mutedRef.current = !!options.muted;
  }, [options.muted]);

  // Keep a ref of partialTranscript to read the latest state in async callbacks safely
  const partialTranscriptRef = useRef('');
  useEffect(() => {
    partialTranscriptRef.current = partialTranscript;
  }, [partialTranscript]);

  // ---------- Speech Recognition instances ----------
  const recognitionRef = useRef<any>(null);
  const pttRecognitionRef = useRef<any>(null);
  const silenceTimerRef = useRef<any>(null);

  // ---------- Audio context refs for level visualizer ----------
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  // ---------- Audio beep helper ----------
  const playBeep = useCallback((freq = 800) => {
    try {
      const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.12);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.12);
    } catch {}
  }, []);

  // ---------- Web Audio Analyser for Level Visualization ----------
  const initAudioVisualizer = useCallback(async () => {
    if (audioContextRef.current) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      streamRef.current = stream;

      const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext;
      const audioContext = new AudioCtx();
      audioContextRef.current = audioContext;

      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 128;
      analyserRef.current = analyser;

      const source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);

      const bufferLength = analyser.fftSize;
      const dataArray = new Float32Array(bufferLength);

      const getMicLevel = () => {
        if (!analyserRef.current || !streamRef.current) {
          window.jarvisAudioLevel = 0;
          return;
        }

        analyserRef.current.getFloatTimeDomainData(dataArray);

        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i] * dataArray[i];
        }
        const rms = Math.sqrt(sum / bufferLength);

        // Map RMS to jarvisAudioLevel (0.0 - 1.0)
        window.jarvisAudioLevel = Math.min(1.0, Math.max(0, (rms - 0.004) * 24.0)); // Amplified for pulsing visual feedback

        animationFrameRef.current = window.setTimeout(() => requestAnimationFrame(getMicLevel), 33) as unknown as number;
      };

      animationFrameRef.current = window.setTimeout(getMicLevel, 33) as unknown as number;
      console.log('[Voice] Web Audio API visualizer started.');
    } catch (err) {
      console.warn('[Voice] Failed to get microphone for level visualizer:', err);
    }
  }, []);

  const releaseAudioVisualizer = useCallback(() => {
    if (animationFrameRef.current) {
      window.clearTimeout(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    window.jarvisAudioLevel = 0;
    console.log('[Voice] Web Audio API visualizer stopped.');
  }, []);

  // ---------- TTS markers (recognition stays alive for barge-in) ----------
  const noteTtsStarted = useCallback(() => {
    console.log('[Voice] TTS playing — listening for barge-in cues');
    isMutedForTTSRef.current = true;
    ttsPlayingRef.current = true;
  }, []);

  const noteTtsEnded = useCallback(() => {
    console.log('[Voice] TTS ended — normal wake-word listening');
    isMutedForTTSRef.current = false;
    ttsPlayingRef.current = false;
  }, []);

  // ---------- Command Execution Wrapper ----------
  const executeCommand = useCallback(async (text: string) => {
    const cleanText = text.trim();
    if (!cleanText) return;

    console.log('[Voice] Executing command text:', cleanText);
    setIsProcessing(true);
    
    if (executeCommandRef.current) {
      try {
        // Await the command execution so we can reset isProcessing accurately
        await executeCommandRef.current(cleanText);
      } catch (err) {
        console.error('[Voice] Error executing voice command:', err);
      }
    }
    setIsProcessing(false);
  }, []);

  // ---------- TTS Interceptor (Synchronizes states and prevents echo) ----------
  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;

    const originalSpeak = window.speechSynthesis.speak;

    window.speechSynthesis.speak = function (utterance: SpeechSynthesisUtterance) {
      const originalOnStart = utterance.onstart;
      const originalOnEnd = utterance.onend;
      const originalOnError = utterance.onerror;

      // Remember what JARVIS is saying so the barge-in echo guard can
      // tell our own voice apart from the user's.
      try {
        const said = (utterance.text || '').toLowerCase();
        lastSpokenRef.current = (lastSpokenRef.current + ' ' + said).slice(-400);
      } catch {}

      utterance.onstart = function (e) {
        setIsSpeaking(true);
        noteTtsStarted();
        if (originalOnStart) originalOnStart.call(this, e);
      };

      const handleSpeechEnd = (e: any, originalCb: any) => {
        setIsSpeaking(false);
        noteTtsEnded();
        if (originalCb) originalCb.call(this, e);
      };

      utterance.onend = function (e) {
        handleSpeechEnd.call(this, e, originalOnEnd);
      };

      utterance.onerror = function (e) {
        handleSpeechEnd.call(this, e, originalOnError);
      };

      originalSpeak.call(window.speechSynthesis, utterance);
    };

    return () => {
      window.speechSynthesis.speak = originalSpeak;
    };
  }, [noteTtsStarted, noteTtsEnded]);

  // ---------- Continuous Wake-Word Mode ----------
  const initRecognition = useCallback(() => {
    if (recognitionRef.current) return recognitionRef.current;

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('[Voice] Web Speech API SpeechRecognition not supported in this browser.');
      return null;
    }

    const rec = new SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';

    // listenState lives in listenStateRef (declared above) so barge-in can drive it.

    // Barge-in: user cuts in while JARVIS speaks. Returns true when the
    // result was consumed (echo ignored or cue handled).
    const tryBargeIn = (segment: string, isFinal: boolean): boolean => {
      const lower = segment.trim().toLowerCase();
      if (!lower) return false;

      // Echo guard: if most of these words are ones JARVIS just said,
      // this is our own voice coming back through the mic — ignore it.
      const words = lower.split(/\s+/).filter(w => w.length > 2);
      if (words.length > 0) {
        const spoken = lastSpokenRef.current;
        let hits = 0;
        for (const w of words) if (spoken.includes(w)) hits++;
        if (hits / words.length >= 0.6) return true;
      }

      const cue = cueIn(lower);
      if (!cue) return false;
      // Interim results only count when the user leads with the cue
      // ("Jarvis, …", "stop") — keeps latency low without false trips.
      if (!isFinal && !cueLeads(lower)) return false;
      // One barge per moment: follow-up interim/final fragments of the same
      // utterance must not re-cancel and re-beep.
      if (Date.now() - bargedAtRef.current < 2500) return true;
      bargedAtRef.current = Date.now();

      console.log('[Voice] Barge-in cue detected:', cue, '| segment:', segment);
      try { window.speechSynthesis?.cancel(); } catch {}
      setIsSpeaking(false);
      playBeep(650);
      setPartialTranscript('❚❚ Interrupted — listening…');

      // Strip a leading cue: "jarvis open notepad" runs at once, a lone
      // "stop" just opens a short window for the real command.
      const rest = stripLeadingCue(lower);
      const restHasCommand = rest.length > 2 && !cueIn(rest);
      if (restHasCommand) {
        listenStateRef.current = 'WAKE';
        setTranscript(rest);
        setPartialTranscript('');
        options.onTranscript?.({ type: 'final', text: rest, timestamp: Date.now() });
        executeCommand(rest);
      } else {
        listenStateRef.current = 'COMMAND';
        if (bargeRevertTimerRef.current) clearTimeout(bargeRevertTimerRef.current);
        bargeRevertTimerRef.current = setTimeout(() => {
          if (listenStateRef.current === 'COMMAND') {
            listenStateRef.current = 'WAKE';
            setPartialTranscript('');
          }
        }, 8000);
      }
      return true;
    };

    rec.onresult = (event: any) => {
      if (isMutedForTTSRef.current && !ttsPlayingRef.current) return;

      let interimText = '';
      let finalText = '';

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const seg = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += seg;
        } else {
          interimText += seg;
        }
      }

      const lastIsFinal = event.results[event.results.length - 1].isFinal || !interimText;

      // While JARVIS speaks, only barge-in cues get through.
      if (ttsPlayingRef.current) {
        tryBargeIn(finalText || interimText, lastIsFinal);
        return;
      }

      const currentSegment = finalText || interimText;
      console.log(`[Voice] Continuous Recognition [State: ${listenStateRef.current}] | Interim: "${interimText}" | Final: "${finalText}"`);
      
      setPartialTranscript(interimText || finalText);

      // Reset silence detection timeout (never force-stop while TTS plays —
      // that would kill barge-in listening mid-reply).
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

      if (currentSegment.trim() && !ttsPlayingRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          console.log('[Voice] Silence detected. Stopping to force finalization.');
          try {
            rec.stop();
          } catch {}
        }, 900);
      }

      const fullText = currentSegment.trim().toLowerCase();

      if (listenStateRef.current === 'WAKE') {
        if (fullText.includes('jarvis')) {
          // Check for "Jarvis, do X" (one sentence trigger)
          const parts = fullText.split('jarvis');
          const commandText = parts[1] ? parts[1].replace(/^[,\s]+|[,\s]+$/g, '').trim() : '';

          if (commandText.length > 1) {
            // One-sentence flow: wait for final result
            if (event.results[event.results.length - 1].isFinal || !interimText) {
              if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
              
              console.log('[Voice] One-sentence wake word + command parsed:', commandText);
              
              setIsWakeDetected(true);
              setTimeout(() => setIsWakeDetected(false), 1200);
              playBeep(900);

              setTranscript(commandText);
              setPartialTranscript('');
              options.onTranscript?.({ type: 'final', text: commandText, timestamp: Date.now() });

              executeCommand(commandText);
            }
          } else {
            // "Jarvis" -> "Yes?" -> command flow
            if (event.results[event.results.length - 1].isFinal || !interimText) {
              if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

              console.log('[Voice] Wake word detected alone. Transitioning to COMMAND state.');
              
              setIsWakeDetected(true);
              setTimeout(() => setIsWakeDetected(false), 1200);
              
              listenStateRef.current = 'COMMAND';

              // Play beep and output "Yes?" (silent when JARVIS is muted) (silent when JARVIS is muted)
              playBeep(850);
              if (!mutedRef.current && window.speechSynthesis) {
                const utter = new SpeechSynthesisUtterance('Yes?');
                utter.rate = 1.0;
                utter.pitch = 0.85;
                window.speechSynthesis.speak(utter);
              }
            }
          }
        }
      } else if (listenStateRef.current === 'COMMAND') {
        // Capture next command in COMMAND state
        if (fullText && (event.results[event.results.length - 1].isFinal || !interimText)) {
          if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
          if (bargeRevertTimerRef.current) {
            clearTimeout(bargeRevertTimerRef.current);
            bargeRevertTimerRef.current = null;
          }

          console.log('[Voice] Captured follow-up command:', currentSegment);
          listenStateRef.current = 'WAKE'; // Revert back to wake word mode

          setTranscript(currentSegment);
          setPartialTranscript('');
          options.onTranscript?.({ type: 'final', text: currentSegment, timestamp: Date.now() });

          executeCommand(currentSegment);
        }
      }
    };

    rec.onerror = (err: any) => {
      console.error('[Voice] Continuous SpeechRecognition error:', err.error);
      if (err.error === 'not-allowed' || err.error === 'service-not-allowed') {
        options.onError?.('Microphone permission denied.');
        stopListening();
      } else if (err.error === 'network') {
        // Web Speech is a network-backed browser service.  Do not spin in an
        // invisible restart loop while it is unavailable; microphone visuals
        // can continue to work even though transcription cannot.
        options.onError?.('Speech recognition network service is unavailable. Please try again or use text input.');
        stopListening();
      }
    };

    rec.onend = () => {
      console.log('[Voice] Continuous SpeechRecognition ended.');
      if (isListeningRef.current && !isMutedForTTSRef.current) {
        try {
          rec.start();
        } catch (e) {
          console.warn('[Voice] Failed to restart SpeechRecognition:', e);
        }
      }
    };

    recognitionRef.current = rec;
    return rec;
  }, [options, executeCommand, playBeep]);

  const startListening = useCallback(async () => {
    if (isListeningRef.current) return;

    try {
      const rec = initRecognition();
      if (!rec) throw new Error('SpeechRecognition initialization failed');

      isListeningRef.current = true;
      setIsListening(true);
      playBeep(800);

      await initAudioVisualizer();

      try {
        rec.start();
      } catch (e) {
        console.warn('[Voice] SpeechRecognition already started or error starting:', e);
      }
      console.log('[Voice] Continuous wake word listening started');
    } catch (err) {
      console.error('[Voice] Failed to start continuous listening:', err);
      isListeningRef.current = false;
      setIsListening(false);
      options.onError?.('Failed to start continuous speech recognizer.');
    }
  }, [initRecognition, initAudioVisualizer, playBeep, options]);

  const stopListening = useCallback(() => {
    if (!isListeningRef.current) return;

    isListeningRef.current = false;
    setIsListening(false);
    setIsWakeDetected(false);
    setPartialTranscript('');

    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
    }

    if (!isPushToTalkActiveRef.current) {
      releaseAudioVisualizer();
    }
    console.log('[Voice] Continuous wake word listening stopped');
  }, [releaseAudioVisualizer]);

  const toggleListening = useCallback(async () => {
    if (isListeningRef.current) {
      stopListening();
    } else {
      await startListening();
    }
  }, [startListening, stopListening]);

  // ---------- Push-to-Talk Mode ----------
  const startPushToTalk = useCallback(async () => {
    if (isPushToTalkActiveRef.current) return;

    console.log('[Voice] Starting Push-to-Talk recognition');
    
    // Stop continuous recognition if running
    if (isListeningRef.current && recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
    }

    isPushToTalkActiveRef.current = true;
    setIsPushToTalkActive(true);
    playBeep(800);

    await initAudioVisualizer();

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      options.onError?.('SpeechRecognition not supported in this browser.');
      return;
    }

    const rec = new SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';

    rec.onresult = (event: any) => {
      let interimText = '';
      let finalText = '';

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const seg = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += seg;
        } else {
          interimText += seg;
        }
      }

      const currentSegment = finalText || interimText;
      setPartialTranscript(interimText || finalText);

      // Timing safe finalize: if PTT was released, execute on first final result
      if (!isPushToTalkActiveRef.current && awaitingFinalPttRef.current) {
        if (event.results[event.results.length - 1].isFinal || !interimText) {
          awaitingFinalPttRef.current = false;
          executePTTCommand(currentSegment);
        }
      }
    };

    const executePTTCommand = (text: string) => {
      const cleanText = text.trim();
      setPartialTranscript('');
      
      if (cleanText) {
        setTranscript(cleanText);
        options.onTranscript?.({ type: 'final', text: cleanText, timestamp: Date.now() });
        executeCommand(cleanText);
      }
    };

    rec.onerror = (err: any) => {
      console.error('[Voice] PTT recognition error:', err);
      if (err.error === 'not-allowed' || err.error === 'service-not-allowed') {
        options.onError?.('Microphone permission denied.');
      } else if (err.error === 'network') {
        options.onError?.('Speech recognition network service is unavailable.');
      }
    };

    rec.onend = () => {
      console.log('[Voice] PTT recognition ended.');
      
      // Safety finalize if no finalized events fired
      if (awaitingFinalPttRef.current) {
        awaitingFinalPttRef.current = false;
        executePTTCommand(partialTranscriptRef.current);
      }

      if (!isListeningRef.current) {
        releaseAudioVisualizer();
      } else {
        // Resume continuous listening
        if (!isMutedForTTSRef.current) {
          try {
            recognitionRef.current?.start();
          } catch (e) {
            console.warn('[Voice] Failed to restart continuous recognition:', e);
          }
        }
      }
    };

    pttRecognitionRef.current = rec;
    try {
      rec.start();
    } catch (e) {
      console.error('[Voice] Failed to start PTT recognition:', e);
    }
  }, [playBeep, initAudioVisualizer, executeCommand, releaseAudioVisualizer, options]);

  const stopPushToTalk = useCallback(async (): Promise<string> => {
    if (!isPushToTalkActiveRef.current) return '';

    console.log('[Voice] Stopping Push-to-Talk recording');
    isPushToTalkActiveRef.current = false;
    setIsPushToTalkActive(false);
    playBeep(600);

    awaitingFinalPttRef.current = true;

    if (pttRecognitionRef.current) {
      try {
        pttRecognitionRef.current.stop();
      } catch {}
    }

    return '';
  }, [playBeep]);

  // ---------- Cleanup on unmount ----------
  useEffect(() => {
    return () => {
      isListeningRef.current = false;
      isPushToTalkActiveRef.current = false;

      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }

      if (bargeRevertTimerRef.current) {
        clearTimeout(bargeRevertTimerRef.current);
        bargeRevertTimerRef.current = null;
      }

      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {}
      }

      if (pttRecognitionRef.current) {
        try {
          pttRecognitionRef.current.stop();
        } catch {}
      }

      if (animationFrameRef.current) {
      window.clearTimeout(animationFrameRef.current);
      }

      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }

      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {});
      }

      window.jarvisAudioLevel = 0;
    };
  }, []);

  return {
    isListening,
    isWakeDetected,
    isProcessing,
    isSpeaking,
    transcript,
    partialTranscript,
    latency: {},
    startListening,
    stopListening,
    toggleListening,
    isPushToTalkActive,
    startPushToTalk,
    stopPushToTalk,
    _setExecuteCommand: (fn: (text: string) => void) => {
      executeCommandRef.current = fn;
    },
  };
}
