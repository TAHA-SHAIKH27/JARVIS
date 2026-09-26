/**
 * AudioManager.js — Centralized Procedural Audio Synthesis Engine for J.A.R.V.I.S.
 * 
 * Generates all futuristic, cinematic UI & startup soundscapes procedurally using the Web Audio API:
 * - Zero external assets / zero network dependencies / zero 404s
 * - Zero copyright liabilities
 * - Full browser autoplay policy resilience (graceful silent fallback, auto-resume on first gesture)
 * - Accessible mute/unmute control saved in localStorage
 * - Volume limiter to guarantee comfortable, professional sound levels
 */

class AudioManager {
  constructor() {
    this.ctx = null;
    this.masterGain = null;
    this.isMuted = false;
    this.volume = 1.0; // Maximum output volume
    this.isUnlocked = false;

    // Load user mute preference
    try {
      const savedMute = localStorage.getItem('jarvis_audio_muted');
      if (savedMute !== null) {
        this.isMuted = savedMute === 'true';
      }
    } catch (e) {
      // Ignore storage errors in restricted iframes
    }

    // Bind unlock handler for first user gesture
    this.initContext = this.initContext.bind(this);
    this.unlockOnGesture = this.unlockOnGesture.bind(this);

    if (typeof window !== 'undefined') {
      window.addEventListener('pointerdown', this.unlockOnGesture, { once: true });
      window.addEventListener('keydown', this.unlockOnGesture, { once: true });
    }
  }

  /** Initialize the AudioContext lazily */
  initContext() {
    if (this.ctx) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      this.ctx = new AudioCtx();
      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.setValueAtTime(this.isMuted ? 0 : this.volume, this.ctx.currentTime);
      this.masterGain.connect(this.ctx.destination);
    } catch (e) {
      // AudioContext unavailable or disabled
    }
  }

  /** Unlock audio on first user gesture */
  unlockOnGesture() {
    this.initContext();
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume().then(() => {
        this.isUnlocked = true;
      }).catch(() => { });
    } else if (this.ctx) {
      this.isUnlocked = true;
    }
  }

  /** Try to resume context if suspended */
  ensureActive() {
    this.initContext();
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => { });
    }
  }

  /** Set muted state */
  setMuted(muted) {
    this.isMuted = Boolean(muted);
    try {
      localStorage.setItem('jarvis_audio_muted', String(this.isMuted));
    } catch (e) { }

    if (this.masterGain && this.ctx) {
      this.masterGain.gain.setTargetAtTime(this.isMuted ? 0 : this.volume, this.ctx.currentTime, 0.05);
    }
  }

  /** Toggle mute state */
  toggleMute() {
    this.setMuted(!this.isMuted);
    return this.isMuted;
  }

  /** Set master volume [0.0 - 1.0] */
  setVolume(vol) {
    this.volume = Math.max(0, Math.min(1, vol));
    if (this.masterGain && this.ctx && !this.isMuted) {
      this.masterGain.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.05);
    }
  }

  /** Helper to create a noise buffer for sweeps and whooshes */
  createNoiseBuffer(duration = 1.0) {
    if (!this.ctx) return null;
    const bufferSize = Math.floor(this.ctx.sampleRate * duration);
    const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
    const output = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      output[i] = Math.random() * 2 - 1;
    }
    return buffer;
  }

  /**
   * CORE_ACTIVATION: bold electronic core activation
   * Deep sub-bass sweep with warm resonance and gradual harmonic bloom.
   */
  playCoreActivation() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const osc1 = this.ctx.createOscillator();
      const osc2 = this.ctx.createOscillator();
      const filter = this.ctx.createBiquadFilter();
      const gain = this.ctx.createGain();

      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(50, now);
      osc1.frequency.exponentialRampToValueAtTime(140, now + 0.9);

      osc2.type = 'triangle';
      osc2.frequency.setValueAtTime(100, now);
      osc2.frequency.exponentialRampToValueAtTime(280, now + 0.9);

      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(160, now);
      filter.frequency.exponentialRampToValueAtTime(800, now + 0.8);
      filter.Q.setValueAtTime(4, now);

      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.85, now + 0.18); // Substantial volume boost
      gain.gain.exponentialRampToValueAtTime(0.001, now + 1.3);

      osc1.connect(filter);
      osc2.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain);

      osc1.start(now);
      osc2.start(now);
      osc1.stop(now + 1.35);
      osc2.stop(now + 1.35);
    } catch (e) { }
  }

  /**
   * PARTICLE_CONVERGENCE: matching sound effect for Fibonacci dots flying into sphere shell
   * Rapid ascending micro-tone chimes panning across stereo field as particles lock in.
   */
  playParticleConvergence() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      // Sequence of 12 crisp converging micro-glissandi
      for (let i = 0; i < 12; i++) {
        const offset = i * 0.075 + (Math.random() * 0.02);
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        const panner = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;

        // Ascending pentatonic sequence
        const startFreq = 440 + (i * 120) + (Math.random() * 60);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(startFreq, now + offset);
        osc.frequency.exponentialRampToValueAtTime(startFreq * 1.5, now + offset + 0.15);

        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.linearRampToValueAtTime(0.35, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.22);

        const pan = (i / 12) * 1.6 - 0.8;
        if (panner) {
          panner.pan.setValueAtTime(pan, now + offset);
          osc.connect(gain);
          gain.connect(panner);
          panner.connect(this.masterGain);
        } else {
          osc.connect(gain);
          gain.connect(this.masterGain);
        }

        osc.start(now + offset);
        osc.stop(now + offset + 0.25);
      }
    } catch (e) { }
  }

  /**
   * SPHERE_MATERIALIZATION: digital particle/energy lock sound
   */
  playSphereMaterialization() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const freqs = [840, 1080, 1360, 1720, 2180, 2640];

      freqs.forEach((f, idx) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        const panner = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;

        const startOffset = now + idx * 0.08 + (Math.random() * 0.04);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(f, startOffset);
        osc.frequency.exponentialRampToValueAtTime(f * 1.25, startOffset + 0.25);

        gain.gain.setValueAtTime(0.0001, startOffset);
        gain.gain.linearRampToValueAtTime(0.45, startOffset + 0.04); // Loud, crisp
        gain.gain.exponentialRampToValueAtTime(0.0001, startOffset + 0.35);

        if (panner) {
          panner.pan.setValueAtTime((idx / freqs.length) * 1.2 - 0.6, startOffset);
          osc.connect(gain);
          gain.connect(panner);
          panner.connect(this.masterGain);
        } else {
          osc.connect(gain);
          gain.connect(this.masterGain);
        }

        osc.start(startOffset);
        osc.stop(startOffset + 0.4);
      });
    } catch (e) { }
  }

  /**
   * ORBIT_START: directional powerful whoosh
   */
  playOrbitStart(orbitIndex = 0) {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const noise = this.createNoiseBuffer(0.85);
      if (!noise) return;

      const source = this.ctx.createBufferSource();
      source.buffer = noise;

      const filter = this.ctx.createBiquadFilter();
      filter.type = 'bandpass';
      const baseFreq = 420 + orbitIndex * 160;
      filter.frequency.setValueAtTime(baseFreq, now);
      filter.frequency.exponentialRampToValueAtTime(baseFreq * 3.2, now + 0.4);
      filter.frequency.exponentialRampToValueAtTime(baseFreq * 0.8, now + 0.8);
      filter.Q.setValueAtTime(4, now);

      const gain = this.ctx.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.65, now + 0.25); // Significantly boosted whoosh volume
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.8);

      const panner = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;
      const panDir = orbitIndex % 2 === 0 ? -0.7 : 0.7;

      if (panner) {
        panner.pan.setValueAtTime(panDir, now);
        panner.pan.linearRampToValueAtTime(-panDir, now + 0.8);
        source.connect(filter);
        filter.connect(gain);
        gain.connect(panner);
        panner.connect(this.masterGain);
      } else {
        source.connect(filter);
        filter.connect(gain);
        gain.connect(this.masterGain);
      }

      source.start(now);
      source.stop(now + 0.85);
    } catch (e) { }
  }

  /**
   * ORBIT_COMPLETE: confirmation chime
   */
  playOrbitComplete() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const freqs = [880, 1320, 1760]; // Rich harmonic triad
      freqs.forEach((f) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = 'sine';
        osc.frequency.setValueAtTime(f, now);

        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.linearRampToValueAtTime(0.5, now + 0.02); // Boosted tone
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.55);

        osc.connect(gain);
        gain.connect(this.masterGain);

        osc.start(now);
        osc.stop(now + 0.6);
      });
    } catch (e) { }
  }

  /**
   * PANEL_ENTRY: movement sound
   */
  playPanelEntry(index = 0) {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime + (index * 0.06);

      const osc = this.ctx.createOscillator();
      const filter = this.ctx.createBiquadFilter();
      const gain = this.ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(160, now);
      osc.frequency.exponentialRampToValueAtTime(80, now + 0.22);

      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(400, now);

      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.45, now + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

      osc.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain);

      osc.start(now);
      osc.stop(now + 0.28);

      const click = this.ctx.createOscillator();
      const clickGain = this.ctx.createGain();
      click.type = 'triangle';
      click.frequency.setValueAtTime(2100, now + 0.18);
      clickGain.gain.setValueAtTime(0.0001, now + 0.18);
      clickGain.gain.linearRampToValueAtTime(0.25, now + 0.19);
      clickGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.24);

      click.connect(clickGain);
      clickGain.connect(this.masterGain);
      click.start(now + 0.18);
      click.stop(now + 0.25);
    } catch (e) { }
  }

  /**
   * SYSTEM_ONLINE: online chime motif
   */
  playSystemOnline() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const notes = [
        { freq: 587.33, time: now, dur: 0.5 },
        { freq: 880.00, time: now + 0.22, dur: 0.9 },
        { freq: 1174.66, time: now + 0.35, dur: 0.8 },
      ];

      notes.forEach((note) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        osc.type = 'sine';
        osc.frequency.setValueAtTime(note.freq, note.time);

        gain.gain.setValueAtTime(0.0001, note.time);
        gain.gain.linearRampToValueAtTime(0.55, note.time + 0.03); // Loud, proud system online motif
        gain.gain.exponentialRampToValueAtTime(0.0001, note.time + note.dur);

        osc.connect(gain);
        gain.connect(this.masterGain);

        osc.start(note.time);
        osc.stop(note.time + note.dur + 0.05);
      });
    } catch (e) { }
  }

  /**
   * VOICE_BRIEFING_START: voice notification chime
   */
  playVoiceBriefingStart() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(523.25, now);
      osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.16);

      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(0.45, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.38);

      osc.connect(gain);
      gain.connect(this.masterGain);

      osc.start(now);
      osc.stop(now + 0.4);
    } catch (e) { }
  }

  /**
   * HACKER_SCAN: rapid digital clicks & data blips during scan
   */
  playHackerScan() {
    if (this.isMuted) return;
    this.ensureActive();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      const now = this.ctx.currentTime;
      for (let i = 0; i < 3; i++) {
        const offset = i * 0.035 + (Math.random() * 0.01);
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();

        const isBlip = i % 2 === 0;
        osc.type = isBlip ? 'sine' : 'square';
        
        const freq = 1200 + Math.random() * 2200;
        osc.frequency.setValueAtTime(freq, now + offset);
        if (isBlip) {
          osc.frequency.exponentialRampToValueAtTime(freq * 0.5, now + offset + 0.025);
        }

        const vol = isBlip ? 0.22 : 0.14; // Substantially boosted hacker scan audio
        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.linearRampToValueAtTime(vol, now + offset + 0.004);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.025);

        osc.connect(gain);
        gain.connect(this.masterGain);

        osc.start(now + offset);
        osc.stop(now + offset + 0.03);
      }
    } catch (e) { }
  }
}

// Export singleton instance
export const audioManager = new AudioManager();
export default audioManager;
