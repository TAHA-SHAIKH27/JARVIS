"""
Voice System — Local/browser-native STT and TTS with interruption support.

Uses Windows SAPI for TTS (no external dependencies).
STT is handled by the frontend (browser Web Speech API) and sent via /api/voice/command.
"""
import asyncio
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
        
        # Initialize Windows SAPI
        self._init_sapi()
    
    def _init_sapi(self):
        """Initialize Windows SAPI voice."""
        try:
            import win32com.client
            self._sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._sapi_available = True
            
            # Get available voices
            self._voices = []
            for voice in self._sapi_voice.GetVoices():
                self._voices.append({
                    "id": voice.Id,
                    "name": voice.GetDescription(),
                    "language": voice.GetAttribute("Language")
                })
        except Exception as e:
            print(f"[VoiceSystem] SAPI initialization failed: {e}")
            self._sapi_voice = None
            self._sapi_available = False
            self._voices = []
    
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
        """Main worker loop that processes TTS requests."""
        while self._running:
            try:
                # Wait for a request with timeout
                try:
                    priority, request = self._tts_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Check if we should interrupt current speech
                if request.interrupt_current:
                    self.interrupt()
                
                # Process the request
                self._process_request(request)
                
            except Exception as e:
                print(f"[VoiceSystem] Worker error: {e}")
                time.sleep(0.1)
    
    def _process_request(self, request: TTSRequest):
        """Process a single TTS request."""
        with self._lock:
            if not self._sapi_available or self._sapi_voice is None:
                if request.callback:
                    try:
                        request.callback(False, "SAPI not available")
                    except Exception:
                        pass
                return
            
            self._state = TTSState.SPEAKING
            self._current_request = request
            self._stop_event.clear()
        
        try:
            # Speak the text (this blocks until complete or interrupted)
            # SAPI Speak with SVSFlagsAsync would be non-blocking but harder to interrupt
            # Using synchronous Speak with interrupt via stop_event
            self._sapi_voice.Speak(request.text)
            
            with self._lock:
                self._state = TTSState.IDLE
                self._current_request = None
            
            if request.callback:
                try:
                    request.callback(True, "Completed")
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"[VoiceSystem] Speech error: {e}")
            with self._lock:
                self._state = TTSState.IDLE
                self._current_request = None
            if request.callback:
                try:
                    request.callback(False, str(e))
                except Exception:
                    pass
    
    def speak(self, text: str, priority: int = 0, interrupt: bool = True, callback: Optional[Callable] = None, metadata: dict = None) -> bool:
        """
        Queue text for speech synthesis.
        
        Args:
            text: Text to speak
            priority: Priority (higher = more urgent)
            interrupt: Whether to interrupt current speech
            callback: Called with (success, message) on completion
            metadata: Optional metadata
            
        Returns:
            True if queued successfully
        """
        if not text or not text.strip():
            return False
        
        request = TTSRequest(
            text=text.strip(),
            priority=priority,
            interrupt_current=interrupt,
            callback=callback,
            metadata=metadata or {}
        )
        
        # Use negative priority for max-heap behavior (higher priority = processed first)
        self._tts_queue.put((-priority, request))
        return True
    
    def interrupt(self) -> bool:
        """
        Interrupt current speech immediately.
        
        Returns:
            True if speech was interrupted
        """
        with self._lock:
            if self._state == TTSState.SPEAKING and self._sapi_voice:
                try:
                    self._sapi_voice.Speak("", 1)  # SVSFlagsAsync = 1, empty string stops current
                    self._state = TTSState.INTERRUPTED
                    self._current_request = None
                    return True
                except Exception as e:
                    print(f"[VoiceSystem] Interrupt failed: {e}")
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
    
    def get_available_voices(self) -> list:
        """Get list of available voices."""
        return self._voices
    
    def set_voice(self, voice_id: str) -> bool:
        """Set the active voice by ID."""
        if not self._sapi_available or self._sapi_voice is None:
            return False
        try:
            for voice in self._sapi_voice.GetVoices():
                if voice.Id == voice_id:
                    self._sapi_voice.Voice = voice
                    return True
        except Exception:
            pass
        return False
    
    def set_rate(self, rate: int):
        """Set speech rate (-10 to 10)."""
        if self._sapi_voice:
            self._sapi_voice.Rate = max(-10, min(10, rate))
    
    def set_volume(self, volume: int):
        """Set volume (0 to 100)."""
        if self._sapi_voice:
            self._sapi_voice.Volume = max(0, min(100, volume))


# Global instance
_voice_system: Optional[VoiceSystem] = None


def get_voice_system() -> VoiceSystem:
    """Get or create the global voice system instance."""
    global _voice_system
    if _voice_system is None:
        _voice_system = VoiceSystem()
        _voice_system.start()
    return _voice_system


def speak(text: str, priority: int = 0, interrupt: bool = True, callback: Optional[Callable] = None) -> bool:
    """Convenience function to speak text."""
    return get_voice_system().speak(text, priority, interrupt, callback)


def interrupt_speech() -> bool:
    """Convenience function to interrupt current speech."""
    return get_voice_system().interrupt()


def get_tts_state() -> TTSState:
    """Get current TTS state."""
    return get_voice_system().get_state()


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
        
        # Check for mid-task instruction
        if self._is_mid_task_instruction(text) and task_state and task_state.task:
            if self.agent_core:
                self.agent_core.inject_mid_task_instruction(text)
            return {"status": "mid_task_instruction", "message": f"Injected instruction: {text}"}
        
        # Otherwise, treat as new command
        return {"status": "new_command", "text": text}
    
    def _is_interruption(self, text: str) -> bool:
        """Check if text is an interruption command."""
        text_lower = text.lower()
        interruption_keywords = [
            "stop", "wait", "halt", "cancel", "abort",
            "interrupt", "pause", "hold on", "hold up",
            "never mind", "forget it", "ignore that"
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