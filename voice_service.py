"""
voice_service.py
----------------
Standalone voice service for J.A.R.V.I.S. - runs as separate process.
Uses openWakeWord for wake word detection (no account needed, fully local).
Local STT: faster-whisper | Cloud fallback: Groq Whisper API
"""

import os
import sys
import time
import json
import wave
import tempfile
import requests
import struct
import subprocess
import numpy as np

try:
    import pyaudio
    from openwakeword import Model
    from faster_whisper import WhisperModel
    from groq import Groq
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install: pip install pyaudio openwakeword onnxruntime faster-whisper groq")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()


class VoiceService:
    def __init__(self):
        self.running = False
        self.backend_url = os.getenv("JARVIS_BACKEND_URL", "http://127.0.0.1:8000")
        
        # openWakeWord
        self.wake_model = None
        self.wake_threshold = 0.5
        
        # Audio
        self.audio = None
        self.stream = None
        self.sample_rate = 16000
        self.chunk_size = 1280  # openWakeWord expects 1280 samples (80ms at 16kHz)
        
        # Local STT (faster-whisper)
        self.whisper_model = None
        self.whisper_model_size = os.getenv("WHISPER_MODEL", "base.en")
        
        # Groq fallback
        self.groq_client = None
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        
        # Recording
        self.recording = False
        self.recorded_frames = []
        self.silence_threshold = 500
        self.silence_frames = 0
        self.max_silence_frames = int(1.5 * self.sample_rate / self.chunk_size)
        self.min_record_frames = int(1.0 * self.sample_rate / self.chunk_size)
        
    def initialize(self):
        """Initialize all components."""
        print("[Voice] Initializing...")
        
        # openWakeWord
        try:
            print("[Voice] Loading openWakeWord model...")
            self.wake_model = Model(
                wakeword_models=["hey_jarvis"],  # built-in model
                inference_framework="onnx"
            )
            print("[Voice] openWakeWord ready (hey_jarvis)")
        except Exception as e:
            print(f"[Voice] openWakeWord init failed: {e}")
            print("Trying to download model...")
            try:
                self.wake_model = Model(
                    wakeword_models=["hey_jarvis.onnx"],
                    inference_framework="onnx"
                )
                print("[Voice] openWakeWord ready (downloaded)")
            except Exception as e2:
                print(f"[Voice] Failed to load wake word model: {e2}")
                return False
        
        # Audio - openWakeWord needs 16kHz, 1280 samples per chunk
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                rate=self.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            print(f"[Voice] Audio stream opened: {self.sample_rate}Hz, chunk={self.chunk_size}")
        except Exception as e:
            print(f"[Voice] Audio init failed: {e}")
            return False
        
        # Local Whisper
        try:
            print(f"[Voice] Loading faster-whisper model: {self.whisper_model_size}...")
            self.whisper_model = WhisperModel(
                self.whisper_model_size,
                device="cpu",
                compute_type="int8"
            )
            print("[Voice] Local Whisper ready")
        except Exception as e:
            print(f"[Voice] Whisper init failed: {e}")
            return False
        
        # Groq client (optional)
        if self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
                print("[Voice] Groq client ready (fallback)")
            except Exception as e:
                print(f"[Voice] Groq init failed: {e}")
        else:
            print("[Voice] No Groq API key - local only mode")
        
        return True
    
    def record_audio(self, max_duration=8):
        """Record audio after wake word until silence or max duration."""
        self.recording = True
        self.recorded_frames = []
        self.silence_frames = 0
        start_time = time.time()
        
        print("[Voice] Recording... (speak now)")
        
        while self.recording and (time.time() - start_time) < max_duration:
            try:
                pcm = self.stream.read(self.chunk_size, exception_on_overflow=False)
                self.recorded_frames.append(pcm)
                
                # Simple voice activity detection
                audio_data = struct.unpack_from("h" * self.chunk_size, pcm)
                energy = sum(abs(x) for x in audio_data) / len(audio_data)
                
                if energy < self.silence_threshold:
                    self.silence_frames += 1
                else:
                    self.silence_frames = 0
                
                # Stop on silence after minimum recording
                if (self.silence_frames >= self.max_silence_frames and 
                    len(self.recorded_frames) >= self.min_record_frames):
                    print("[Voice] Silence detected, stopping recording")
                    break
                    
            except Exception as e:
                print(f"[Voice] Recording error: {e}")
                break
        
        self.recording = False
        
        if len(self.recorded_frames) < self.min_record_frames:
            print("[Voice] Recording too short, discarding")
            return None
            
        # Save to temp WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wf = wave.open(f.name, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(self.recorded_frames))
            wf.close()
            return f.name
    
    def transcribe_local(self, wav_path):
        """Transcribe using whisper.cpp (fast local C++) with faster-whisper fallback."""
        # 1. Try whisper.cpp executable first (fastest local C++ STT)
        try:
            whisper_cpp_cli = os.path.join(os.path.dirname(__file__), "whisper.cpp", "build", "bin", "Release", "whisper-cli.exe")
            model_path = os.path.join(os.path.dirname(__file__), "whisper.cpp", "models", "ggml-base.en.bin")
            
            if os.path.exists(whisper_cpp_cli) and os.path.exists(model_path):
                cmd = [whisper_cpp_cli, "-m", model_path, "-f", wav_path, "-nt", "-np"]
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                if res.returncode == 0 and res.stdout.strip():
                    text = res.stdout.strip()
                    print(f"[Voice] whisper.cpp STT: '{text}'")
                    return text
        except Exception as e:
            print(f"[Voice] whisper.cpp error: {e}, falling back")

        # 2. Fallback to faster-whisper
        if self.whisper_model:
            try:
                segments, info = self.whisper_model.transcribe(
                    wav_path,
                    language="en",
                    beam_size=1,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500)
                )
                
                text = " ".join([seg.text for seg in segments]).strip()
                
                # Confidence heuristic
                seg_list = list(segments)
                avg_logprob = sum(seg.avg_logprob for seg in seg_list) / max(1, len(seg_list))
                
                print(f"[Voice] Local STT: '{text}' (confidence: {avg_logprob:.2f})")
                
                if text and avg_logprob > -1.0:
                    return text
                return None
                
            except Exception as e:
                print(f"[Voice] Local transcription error: {e}")
                return None
        return None
    
    def transcribe_groq(self, wav_path):
        """Transcribe using Groq Whisper API (fallback)."""
        if not self.groq_client:
            return None
            
        try:
            with open(wav_path, "rb") as f:
                transcript = self.groq_client.audio.transcriptions.create(
                    file=(os.path.basename(wav_path), f.read()),
                    model="whisper-large-v3-turbo",
                    language="en",
                    response_format="text",
                    temperature=0.0
                )
            
            text = transcript.strip() if transcript else ""
            print(f"[Voice] Groq STT: '{text}'")
            return text if text else None
            
        except Exception as e:
            print(f"[Voice] Groq transcription error: {e}")
            return None
    
    def send_to_backend(self, text):
        """Send recognized command to JARVIS backend."""
        try:
            resp = requests.post(
                f"{self.backend_url}/api/voice/command",
                json={"prompt": text},
                timeout=10
            )
            if resp.ok:
                data = resp.json()
                print(f"[Voice] JARVIS: {data.get('speak', 'OK')}")
            else:
                print(f"[Voice] Backend error: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"[Voice] Backend request failed: {e}")
    
    def cleanup_temp(self, wav_path):
        """Clean up temp WAV file."""
        try:
            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)
        except Exception:
            pass
    
    def play_beep(self):
        """Play a short beep for wake word feedback."""
        try:
            import winsound
            winsound.Beep(800, 100)
        except Exception:
            pass
    
    def run(self):
        """Main loop: wake word -> record -> transcribe -> send."""
        if not self.initialize():
            return
        
        self.running = True
        print("[Voice] Listening for wake word... (say 'Hey Jarvis')")
        
        try:
            while self.running:
                # Read audio chunk (1280 samples for openWakeWord)
                pcm = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio_chunk = np.frombuffer(pcm, dtype=np.int16)
                
                # Wake word detection
                prediction = self.wake_model.predict(audio_chunk)
                score = prediction.get("hey_jarvis", 0)
                
                if score >= self.wake_threshold:
                    print(f"[Voice] Wake word detected! (score={score:.2f})")
                    self.play_beep()
                    
                    # Record command
                    wav_path = self.record_audio(max_duration=8)
                    
                    if wav_path:
                        # Try local first
                        text = self.transcribe_local(wav_path)
                        
                        # Fallback to Groq if local failed
                        if not text and self.groq_client:
                            print("[Voice] Local STT failed, trying Groq...")
                            text = self.transcribe_groq(wav_path)
                        
                        if text:
                            print(f"[Voice] Final: '{text}'")
                            self.send_to_backend(text)
                        else:
                            print("[Voice] Could not transcribe")
                        
                        self.cleanup_temp(wav_path)
                    
                    # Small cooldown to avoid re-triggering
                    time.sleep(0.5)
                    
                    # Reset wake model state
                    self.wake_model.reset()
                    
        except KeyboardInterrupt:
            print("\n[Voice] Stopping...")
        finally:
            self.shutdown()
    
    def shutdown(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio:
            self.audio.terminate()
        print("[Voice] Shutdown complete")


def main():
    service = VoiceService()
    service.run()


if __name__ == "__main__":
    main()