"""
Voice System — Local/browser-native STT and TTS with interruption support.

Uses Windows SAPI for TTS (no external dependencies).
STT is handled by the frontend (browser Web Speech API) and sent via /api/voice/command.
"""
import asyncio
import itertools
import threading
import queue
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum


class TTSState(Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    PAUSED = "paused"


@dataclass
class TTSRequest:
    text: str
    priority: int = 0  # Higher = more urgent
    interrupt_current: bool = True
    callback: Optional[Callable] = None
    metadata: dict = None
    voice_id: Optional[str] = None  # SAPI voice to use for this utterance (None = current)


class VoiceSystem:
    """
    Windows SAPI-based TTS with interruption support.
    
    Features:
    - Non-blocking speech synthesis
    - Interruptible playback (stops current utterance)
    - Priority queue for urgent messages
    - Callback on completion
    - Thread-safe
    """
    
    def __init__(self):
        self._tts_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._current_tts_thread: Optional[threading.Thread] = None
        self._current_request: Optional[TTSRequest] = None
        self._state = TTSState.IDLE
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        # Tiebreaker so same-priority requests never compare TTSRequest
        # objects (which would raise TypeError and drop announcements).
        self._seq = itertools.count()
        # Mute: while set, speak() drops new requests (no queueing, so
        # unmuting never replays stale announcements) and any in-flight
        # speech is interrupted. Toasts/notifications are unaffected.
        self._muted = False
        self._active_lang = "en"
        # Dedup: identical TTS text re-queued within a few seconds (double
        # /api/command fetch, restart + scheduled Gmail cycle racing, etc.)
        # is dropped instead of being spoken twice ~30s apart.
        self._last_speak_text = ""
        self._last_speak_at = 0.0
        self._queued_texts: set = set()

        # ── COM threading model ──────────────────────────────────────
        # SAPI.SpVoice is a single-threaded COM object. Touching it from
        # any thread but its creator is an access violation waiting to
        # happen (exit code 3221225477) — so EVERY COM call happens on the
        # worker thread and nowhere else. Other threads only enqueue data:
        # voice/rate/volume wishes are stored as pendings, interrupts as an
        # event. The worker applies them on its own thread.
        self._sapi_voice = None
        self._sapi_available = False
        self._voices: list = []
        self._sapi_ready = threading.Event()
        self._interrupt_event = threading.Event()
        self._active_voice_id = ""
        self._pending_voice_id: Optional[str] = None
        self._pending_rate: Optional[int] = -1
        self._pending_volume: Optional[int] = None

    # SAPI flags / RunningState values (avoid importing win32 constants).
    _SVS_ASYNC = 1
    _SVS_PURGE = 2
    _SPRS_IS_SPEAKING = 2

    def _init_sapi_on_worker(self):
        """Create and configure SAPI. Runs ONLY on the worker thread."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            import win32com.client
            sapi = win32com.client.Dispatch("SAPI.SpVoice")
            voices = []
            for voice in sapi.GetVoices():
                try:
                    gender = voice.GetAttribute("Gender")
                except Exception:
                    gender = ""
                try:
                    voices.append({
                        "id": voice.Id,
                        "name": voice.GetDescription(),
                        "language": voice.GetAttribute("Language"),
                        "gender": gender or "",
                    })
                except Exception:
                    pass
            self._sapi_voice = sapi
            self._sapi_available = True
            self._voices = voices
            # JARVIS is male: default to a male English voice (David/...),
            # never the Windows default (usually Zira, female).
            self._select_default_male_voice()
            # Slightly slower than the SAPI default — measured gravitas.
            try:
                sapi.Rate = -1
            except Exception:
                pass
            self._pending_rate = None
        except Exception as e:
            print(f"[VoiceSystem] SAPI initialization failed: {e}")
            self._sapi_voice = None
            self._sapi_available = False
            self._voices = []
        finally:
            self._sapi_ready.set()
    
    def _init_sapi(self):
        """Legacy entry point — COM is now created on the worker thread via
        _init_sapi_on_worker(). Kept so external callers never break; it
        simply reports readiness without touching COM itself."""
        return self._sapi_available

    def _select_default_male_voice(self):
        """Point SAPI at the most masculine English voice available.

        WORKER THREAD ONLY — touches COM."""
        try:
            if not getattr(self, "_sapi_available", False) or self._sapi_voice is None:
                return False
            from backend.agent.lang_detect import select_voice_for_lang
            choice = select_voice_for_lang(getattr(self, "_voices", []), "en")
            if choice is None:
                return False
            if self._apply_voice_id(choice.get("id")):
                print(f"[VoiceSystem] Default voice: {choice.get('name')}")
                return True
            return False
        except Exception as exc:
            print(f"[VoiceSystem] Default male voice selection failed: {exc}")
        return False

    def _apply_voice_id(self, voice_id: str) -> bool:
        """Select a SAPI voice by ID. WORKER THREAD ONLY."""
        try:
            if self._sapi_voice is None:
                return False
            for installed in self._sapi_voice.GetVoices():
                if installed.Id == voice_id:
                    self._sapi_voice.Voice = installed
                    self._active_voice_id = voice_id
                    return True
        except Exception as exc:
            print(f"[VoiceSystem] Voice switch failed: {exc}")
        return False

    def _apply_pending_settings(self):
        """Apply queued voice/rate/volume wishes. WORKER THREAD ONLY."""
        if self._sapi_voice is None:
            return
        if self._pending_rate is not None:
            try:
                self._sapi_voice.Rate = max(-10, min(10, int(self._pending_rate)))
            except Exception:
                pass
            self._pending_rate = None
        if self._pending_volume is not None:
            try:
                self._sapi_voice.Volume = max(0, min(100, int(self._pending_volume)))
            except Exception:
                pass
            self._pending_volume = None
        if self._pending_voice_id:
            vid = self._pending_voice_id
            self._pending_voice_id = None
            self._apply_voice_id(vid)
    
    def start(self):
        """Start the TTS worker thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
    
    def stop(self):
        """Stop the TTS worker and interrupt current speech."""
        self._running = False
        self._stop_event.set()
        self.interrupt()
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
    
    def _worker_loop(self):
        """Main worker loop that processes TTS requests. This thread is the
        SOLE owner of the SAPI COM object — see _init_sapi_on_worker."""
        self._init_sapi_on_worker()
        while self._running:
            try:
                # Wait for a request with timeout
                try:
                    _, _, request = self._tts_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Process the request (previous utterance is always fully
                # finished or purged before we get here — the worker is
                # strictly sequential, so there is nothing to preempt).
                self._process_request(request)

            except Exception as e:
                print(f"[VoiceSystem] Worker error: {e}")
                time.sleep(0.1)

    def _speak_sync(self, text: str) -> str:
        """Speak while polling for completion so interrupts stay prompt.

        WORKER THREAD ONLY. Returns 'done', 'interrupted', or 'error'.
        Uses async Speak + RunningState polling (no COM event pumping
        needed) so the worker never blocks uninterruptibly."""
        try:
            self._sapi_voice.Speak(text, self._SVS_ASYNC)
        except Exception as e:
            print(f"[VoiceSystem] Speak failed: {e}")
            return "error"
        while True:
            if self._interrupt_event.is_set():
                try:
                    self._sapi_voice.Speak("", self._SVS_ASYNC | self._SVS_PURGE)
                except Exception:
                    pass
                return "interrupted"
            try:
                running = self._sapi_voice.Status.RunningState
            except Exception:
                return "error"
            if running != self._SPRS_IS_SPEAKING:
                return "done"
            time.sleep(0.05)

    def _process_request(self, request: TTSRequest):
        """Process a single TTS request. WORKER THREAD ONLY."""
        if not self._sapi_available or self._sapi_voice is None:
            with self._lock:
                self._queued_texts.discard(request.text.strip())
            if request.callback:
                try:
                    request.callback(False, "SAPI not available")
                except Exception:
                    pass
            return

        self._interrupt_event.clear()
        self._apply_pending_settings()
        if request.voice_id and request.voice_id != self._active_voice_id:
            self._apply_voice_id(request.voice_id)

        with self._lock:
            self._state = TTSState.SPEAKING
            self._current_request = request

        outcome = self._speak_sync(request.text)

        with self._lock:
            self._state = TTSState.IDLE if outcome == "done" else TTSState.INTERRUPTED
            self._current_request = None
            self._queued_texts.discard(request.text.strip())

        if request.callback:
            try:
                if outcome == "done":
                    request.callback(True, "Completed")
                elif outcome == "interrupted":
                    request.callback(True, "Interrupted")
                else:
                    request.callback(False, "Speech error")
            except Exception:
                pass
    
    def speak(self, text: str, priority: int = 0, interrupt: bool = True, callback: Optional[Callable] = None, metadata: dict = None, lang: Optional[str] = None) -> bool:
        """
        Queue text for speech synthesis.
        
        Args:
            text: Text to speak
            priority: Priority (higher = more urgent)
            interrupt: Whether to interrupt current speech
            callback: Called with (success, message) on completion
            metadata: Optional metadata
            lang: BCP-47-ish code (hi/mr/ur/en/fr/es). Auto-detected from
                the text when omitted; selects a matching installed SAPI
                voice when one exists, otherwise keeps the current voice.
            
        Returns:
            True if queued successfully
        """
        if not text or not text.strip():
            return False
        clean = text.strip()
        now = time.time()
        with self._lock:
            if self._muted:
                return False
            # Drop exact duplicates re-queued within 30s (double fetch /
            # restart+scheduled race). Prevents the "same reply spoken twice"
            # symptom without affecting genuinely new utterances.
            if clean in self._queued_texts:
                return False
            if clean == self._last_speak_text and (now - self._last_speak_at) < 30.0:
                return False
            self._queued_texts.add(clean)
            self._last_speak_text = clean
            self._last_speak_at = now
            # Bound the queue: if >8 pending, drop the stalest low-priority
            # announcement so a burst of mail + reminders can never delay a
            # live reply by ~30s. Replies use priority >= 0, background
            # chatter uses negative priority, so the lowest number is the
            # safest to evict.
            try:
                if self._tts_queue.qsize() >= 8:
                    buf = []
                    try:
                        while True:
                            buf.append(self._tts_queue.get_nowait())
                    except queue.Empty:
                        pass
                    if buf:
                        buf.sort(key=lambda e: e[0], reverse=True)
                        evicted = buf.pop(0)
                        try:
                            self._queued_texts.discard(evicted[2].text.strip())
                        except Exception:
                            pass
                    for entry in buf:
                        self._tts_queue.put(entry)
            except Exception:
                pass
        voice_id = None
        with self._lock:
            # Pure-python language routing over the CACHED voice list — no
            # COM touched here (that would be a cross-thread call). The
            # chosen voice travels with the request; the worker applies it.
            try:
                from backend.agent.lang_detect import detect_lang, select_voice_for_lang
                resolved = (lang or "").strip().lower()[:2] or detect_lang(text)
                if resolved:
                    voice = select_voice_for_lang(getattr(self, "_voices", []), resolved)
                    if voice is not None:
                        voice_id = voice.get("id")
                        self._active_lang = resolved
            except Exception as exc:
                print(f"[VoiceSystem] Language routing failed: {exc}")

        request = TTSRequest(
            text=text.strip(),
            priority=priority,
            interrupt_current=interrupt,
            callback=callback,
            metadata=metadata or {},
            voice_id=voice_id,
        )

        # A new interrupting request cancels whatever is playing right now.
        if interrupt:
            self._interrupt_event.set()

        # Use negative priority for max-heap behavior (higher priority = processed first)
        self._tts_queue.put((-priority, next(self._seq), request))
        return True

    def interrupt(self) -> bool:
        """
        Interrupt current speech immediately.

        Thread-safe: only sets an event. The worker thread performs the
        actual SAPI purge on its own (COM-owning) thread.

        Returns:
            True if speech was interrupted
        """
        with self._lock:
            if self._state == TTSState.SPEAKING:
                self._interrupt_event.set()
                return True
        return False
    
    def pause(self) -> bool:
        """Pause current speech (not fully supported by SAPI, uses interrupt)."""
        return self.interrupt()
    
    def resume(self) -> bool:
        """Resume speech (not supported by SAPI after interrupt)."""
        return False
    
    def get_state(self) -> TTSState:
        """Get current TTS state."""
        with self._lock:
            return self._state
    
    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        with self._lock:
            return self._state == TTSState.SPEAKING
    
    def clear_queue(self):
        """Clear all pending TTS requests."""
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                break

    def set_muted(self, muted: bool) -> bool:
        """Mute or unmute the voice system. Muting interrupts in-flight
        speech and drops the pending queue; unmuting does not replay."""
        with self._lock:
            self._muted = bool(muted)
            should_stop = bool(muted)
        if should_stop:
            self.interrupt()
            self.clear_queue()
        return self._muted

    def is_muted(self) -> bool:
        """Check whether the voice system is muted."""
        with self._lock:
            return self._muted
    
    def get_available_voices(self) -> list:
        """Get list of available voices."""
        return self._voices
    
    def set_voice(self, voice_id: str) -> bool:
        """Request the active voice by ID. The worker applies it on its own
        thread before the next utterance (direct COM access from here would
        be a cross-thread call). Returns False for unknown IDs."""
        try:
            known = {v.get("id") for v in (getattr(self, "_voices", []) or [])
                     if isinstance(v, dict)}
            if voice_id in known:
                with self._lock:
                    self._pending_voice_id = voice_id
                return True
        except Exception:
            pass
        return False

    def set_rate(self, rate: int):
        """Set speech rate (-10 to 10). Applied by the worker thread."""
        with self._lock:
            self._pending_rate = max(-10, min(10, rate))

    def set_volume(self, volume: int):
        """Set volume (0 to 100). Applied by the worker thread."""
        with self._lock:
            self._pending_volume = max(0, min(100, volume))


# Global instance
_voice_system: Optional[VoiceSystem] = None


def get_voice_system() -> VoiceSystem:
    """Get or create the global voice system instance."""
    global _voice_system
    if _voice_system is None:
        _voice_system = VoiceSystem()
        _voice_system.start()
    return _voice_system


def speak(text: str, priority: int = 0, interrupt: bool = True, callback: Optional[Callable] = None, lang: Optional[str] = None) -> bool:
    """Convenience function to speak text."""
    return get_voice_system().speak(text, priority, interrupt, callback, lang=lang)


def interrupt_speech() -> bool:
    """Convenience function to interrupt current speech."""
    return get_voice_system().interrupt()


def get_tts_state() -> TTSState:
    """Get current TTS state."""
    return get_voice_system().get_state()


def set_muted(muted: bool) -> bool:
    """Convenience function to mute/unmute the voice system."""
    return get_voice_system().set_muted(muted)


def is_muted() -> bool:
    """Convenience function to check the mute state."""
    return get_voice_system().is_muted()


# ─────────────────────────────────────────────────────────────────────────────
# STT Integration (browser-native)
# ─────────────────────────────────────────────────────────────────────────────

class STTResult:
    """Result from speech recognition."""
    def __init__(self, text: str, confidence: float = 0.0, is_final: bool = True):
        self.text = text
        self.confidence = confidence
        self.is_final = is_final


class VoiceRecognitionManager:
    """
    Manages speech recognition.
    
    Note: Actual STT is performed in the browser using Web Speech API.
    This class provides the interface for the backend to handle STT results
    and manage recognition state.
    """
    
    def __init__(self):
        self._is_listening = False
        self._callbacks: list = []
        self._last_result: Optional[STTResult] = None
    
    def start_listening(self, callback: Optional[Callable[[STTResult], None]] = None) -> bool:
        """Start listening for speech (frontend handles actual recognition)."""
        self._is_listening = True
        if callback:
            self._callbacks.append(callback)
        return True
    
    def stop_listening(self) -> bool:
        """Stop listening for speech."""
        self._is_listening = False
        return True
    
    def handle_result(self, text: str, confidence: float = 0.0, is_final: bool = True):
        """Handle STT result from frontend."""
        result = STTResult(text, confidence, is_final)
        self._last_result = result
        for callback in self._callbacks:
            try:
                callback(result)
            except Exception as e:
                print(f"[VoiceRecognition] Callback error: {e}")
    
    def is_listening(self) -> bool:
        return self._is_listening
    
    def get_last_result(self) -> Optional[STTResult]:
        return self._last_result


# Global STT manager
_stt_manager: Optional[VoiceRecognitionManager] = None


def get_stt_manager() -> VoiceRecognitionManager:
    global _stt_manager
    if _stt_manager is None:
        _stt_manager = VoiceRecognitionManager()
    return _stt_manager


# ─────────────────────────────────────────────────────────────────────────────
# Voice Command Processing
# ─────────────────────────────────────────────────────────────────────────────

class VoiceCommandProcessor:
    """
    Processes voice commands with interruption handling.
    
    Integrates with AgentCore for mid-task instruction injection.
    """
    
    def __init__(self, agent_core=None):
        self.agent_core = agent_core
        self._processing = False
        self._current_task_id: Optional[str] = None
    
    def set_agent_core(self, agent_core):
        self.agent_core = agent_core
    
    async def process_command(self, text: str, task_state: Optional[Any] = None) -> dict:
        """
        Process a voice command.
        
        If there's an active task, this injects a mid-task instruction.
        Otherwise, starts a new task.
        """
        if not text or not text.strip():
            return {"status": "error", "message": "Empty command"}
        
        text = text.strip()
        
        # Check for interruption keywords
        if self._is_interruption(text):
            interrupt_speech()
            if self.agent_core:
                self.agent_core.request_interrupt("Voice interruption: " + text)
            return {"status": "interrupted", "message": "Speech interrupted"}
        
        # New command while a task runs: merge related changes, queue the rest.
        if task_state and (getattr(task_state, "task", "") or "").strip():
            from backend.agent.clarify import classify_instruction
            verdict = classify_instruction(task_state.task, text)
            if self.agent_core:
                self.agent_core.inject_mid_task_instruction(text)
            if verdict["related"]:
                return {"status": "mid_task_instruction",
                        "message": f"Merged into current task ({verdict['reason']})"}
            return {"status": "task_queued",
                    "message": "Queued to run after the current task, sir."}

        # Otherwise, treat as new command
        return {"status": "new_command", "text": text}
    
    def _is_interruption(self, text: str) -> bool:
        """Check if text is an interruption command."""
        text_lower = text.lower()
        interruption_keywords = [
            "stop", "wait", "halt", "cancel", "abort",
            "interrupt", "pause", "hold on", "hold up",
            "never mind", "forget it", "ignore that",
            "quiet", "shush", "that's enough", "that is enough",
        ]
        return any(kw in text_lower for kw in interruption_keywords)
    
    def _is_mid_task_instruction(self, text: str) -> bool:
        """Check if text is a mid-task instruction (modification to current task)."""
        text_lower = text.lower()
        mid_task_keywords = [
            "actually", "instead", "change", "modify", "update",
            "make it", "make the", "add", "remove", "delete",
            "also", "and then", "then", "after that"
        ]
        return any(kw in text_lower for kw in mid_task_keywords)


# Global command processor
_command_processor: Optional[VoiceCommandProcessor] = None


def get_command_processor() -> VoiceCommandProcessor:
    global _command_processor
    if _command_processor is None:
        _command_processor = VoiceCommandProcessor()
    return _command_processor