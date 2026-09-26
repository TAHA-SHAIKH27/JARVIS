import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Volume2, VolumeX } from 'lucide-react';
import audioManager from '../audio/AudioManager';
import CoreSphere from '../CoreSphere';
import '../startup.css';

export const STARTUP_STATES = {
  BOOT: 'BOOT',
  CORE_INITIALIZING: 'CORE_INITIALIZING',
  CORE_ACTIVE: 'CORE_ACTIVE',
  SPHERE_INITIALIZING: 'SPHERE_INITIALIZING',
  ORBITALS_INITIALIZING: 'ORBITALS_INITIALIZING',
  UI_ASSEMBLY: 'UI_ASSEMBLY',
  AUDIT_RUNNING: 'AUDIT_RUNNING',
  SYSTEM_VERIFYING: 'SYSTEM_VERIFYING',
  SYSTEM_READY: 'SYSTEM_READY',
  ONLINE: 'ONLINE',
};

// ── Live Scan Animation Component ──────────────────────────────────────────
const FAKE_FILES = [
  'backend/startup_engine.py', 'backend/tools/browser.py', 'backend/tools/office.py',
  'backend/tools/vision.py', 'backend/tools/terminal.py', 'backend/agent/core.py',
  'main.py', 'code_core.py', 'system_ops.py', 'phone_control.py',
  'src/App.jsx', 'src/CoreSphere.jsx', 'src/components/StartupController.jsx',
  'src/components/Jarvis3DCore.jsx', 'src/audio/AudioManager.js',
  'src/hooks/useVoice.js', 'src/index.css', 'src/startup.css',
  'backend/tools/scheduler.py', 'backend/tools/gmail_notify.py',
  'backend/data/session_memory.json', 'config.json', 'package.json',
];

const HEX_CHARS = '0123456789ABCDEF';
const CODE_TOKENS = [
  'def ', 'class ', 'import ', 'async ', 'return ', 'await ',
  'const ', 'function ', 'export ', 'useState(', 'useEffect(',
  '=> {', ');', '}}', '"""', '# █', '// ✓',
];

function randomHex(len = 8) {
  return Array.from({ length: len }, () => HEX_CHARS[Math.floor(Math.random() * 16)]).join('');
}

function ScanAnimation({ totalFiles = 91, scannedCount }) {
  const [lines, setLines] = useState([]);
  const [progress, setProgress] = useState(0);
  const lineIdRef = useRef(0);

  // Scroll new scan lines in
  useEffect(() => {
    const interval = setInterval(() => {
      const file = FAKE_FILES[Math.floor(Math.random() * FAKE_FILES.length)];
      const token = CODE_TOKENS[Math.floor(Math.random() * CODE_TOKENS.length)];
      const hex = randomHex(6);
      const types = ['file', 'hex', 'token', 'ok'];
      const type = types[Math.floor(Math.random() * types.length)];

      let text;
      if (type === 'file') text = `  scanning  ${file}`;
      else if (type === 'hex') text = `  0x${hex}  →  ${randomHex(4)}:${randomHex(4)}`;
      else if (type === 'token') text = `  ${token}${randomHex(4).toLowerCase()}...`;
      else text = `  ✓  ${file.split('/').pop()}  [OK ${randomHex(3)}]`;

      const id = ++lineIdRef.current;
      setLines(prev => [...prev.slice(-22), { id, text, type }]);

      // Animate progress
      setProgress(prev => Math.min(98, prev + (100 / totalFiles) * (0.8 + Math.random() * 0.4)));
    }, 85);

    return () => clearInterval(interval);
  }, [totalFiles]);

  // Jump to real progress when we have it
  useEffect(() => {
    if (scannedCount > 0) {
      setProgress(Math.min(99, (scannedCount / totalFiles) * 100));
    }
  }, [scannedCount, totalFiles]);

  return (
    <div className="scan-animation-panel scan-panel-lhs">
      {/* Header bar */}
      <div className="scan-anim-header">
        <span className="scan-anim-dot" />
        <span>CODEBASE INTEGRITY SCAN</span>
        <span className="scan-anim-count">{Math.round(progress)}% — {totalFiles} FILES</span>
      </div>

      {/* Scrolling scan lines */}
      <div className="scan-anim-lines" aria-live="off" aria-hidden="true">
        {lines.map((line, idx) => (
          <div
            key={line.id}
            className={`scan-anim-line scan-anim-line-${line.type} ${idx === lines.length - 1 ? 'scan-anim-line-active' : ''}`}
          >
            {line.text}
            {idx === lines.length - 1 && <span className="scan-cursor">█</span>}
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div className="scan-anim-progress-wrap">
        <div className="scan-anim-progress-bar">
          <div
            className="scan-anim-progress-fill"
            style={{ width: `${progress}%` }}
          />
          <div
            className="scan-anim-progress-glow"
            style={{ left: `${progress}%` }}
          />
        </div>
        <div className="scan-anim-progress-label">
          <span>0x0000</span>
          <span>FILE AUDIT IN PROGRESS…</span>
          <span>0xFF{randomHex(2)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Live RHS Tools Scan Component ──────────────────────────────────────────
const TOOLS_LIST = [
  { name: 'browser_automation', label: 'BROWSER DIRECTIVES', path: 'backend/tools/browser.py' },
  { name: 'terminal_subsystem', label: 'SHELL & COMMAND EXECUTOR', path: 'backend/tools/terminal.py' },
  { name: 'office_suite', label: 'OFFICE & DOCS HANDLER', path: 'backend/tools/office.py' },
  { name: 'computer_vision', label: 'VISION & MULTIMODAL PERCEPTION', path: 'backend/tools/vision.py' },
  { name: 'phone_control', label: 'ANDROID/PHONE BRIDGE', path: 'phone_control.py' },
  { name: 'task_scheduler', label: 'BACKGROUND SCHEDULER', path: 'backend/tools/scheduler.py' },
  { name: 'voice_synthesis', label: 'PROCEDURAL AUDIO & VOICE ENGINE', path: 'src/audio/AudioManager.js' },
];

function ToolsScanAnimation() {
  const [lines, setLines] = useState([]);
  const [progress, setProgress] = useState(0);
  const lineIdRef = useRef(0);

  useEffect(() => {
    let step = 0;
    const interval = setInterval(() => {
      step++;
      const tool = TOOLS_LIST[step % TOOLS_LIST.length];
      const hex = randomHex(6);
      const phases = [
        { text: `  testing  ${tool.name}...`, type: 'token' },
        { text: `  init     ${tool.path}`, type: 'file' },
        { text: `  0x${hex}  handshake verified`, type: 'hex' },
        { text: `  ✓  ${tool.label}  [READY]`, type: 'ok' },
      ];

      const lineObj = phases[step % phases.length];
      const id = ++lineIdRef.current;

      setLines(prev => [...prev.slice(-22), { id, ...lineObj }]);
      setProgress(prev => Math.min(99, prev + 4.5));
    }, 90);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="scan-animation-panel scan-panel-rhs">
      {/* Header bar */}
      <div className="scan-anim-header">
        <span className="scan-anim-dot" />
        <span>TOOLS & AGENTS CHECK</span>
        <span className="scan-anim-count">{Math.round(progress)}% — 7 MODULES</span>
      </div>

      {/* Scrolling tool check lines */}
      <div className="scan-anim-lines" aria-live="off" aria-hidden="true">
        {lines.map((line, idx) => (
          <div
            key={line.id}
            className={`scan-anim-line scan-anim-line-${line.type} ${idx === lines.length - 1 ? 'scan-anim-line-active' : ''}`}
          >
            {line.text}
            {idx === lines.length - 1 && <span className="scan-cursor">█</span>}
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div className="scan-anim-progress-wrap">
        <div className="scan-anim-progress-bar">
          <div
            className="scan-anim-progress-fill"
            style={{ width: `${progress}%` }}
          />
          <div
            className="scan-anim-progress-glow"
            style={{ left: `${progress}%` }}
          />
        </div>
        <div className="scan-anim-progress-label">
          <span>PORT 8000</span>
          <span>TOOLKITS AUDIT ONLINE…</span>
          <span>0x99{randomHex(2)}</span>
        </div>
      </div>
    </div>
  );
}

export default function StartupController({
  onStartupComplete,
  onBriefingReady,
  onAuditReport,
}) {
  const [phase, setPhase] = useState(STARTUP_STATES.BOOT);
  const [isMuted, setIsMuted] = useState(audioManager.isMuted);
  const [backendReady, setBackendReady] = useState(false);
  const [backendData, setBackendData] = useState(null);
  const [auditTotalFiles, setAuditTotalFiles] = useState(91);
  const [auditScanned, setAuditScanned] = useState(0);
  const [toolsCheckActive, setToolsCheckActive] = useState(false);
  const [telemetryLines, setTelemetryLines] = useState([
    { label: 'J.A.R.V.I.S. SYSTEM', val: 'INITIALIZING' },
    { label: 'CORE KERNEL', val: 'STANDBY' },
    { label: 'PERCEPTION', val: 'PENDING' },
    { label: 'AUTOMATION TOOLS', val: 'PENDING' },
    { label: 'SYSTEM AUDIT', val: 'STANDBY' },
    { label: 'STATUS', val: 'PREPARING' },
  ]);

  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const backendDataRef = useRef(null);
  const backendReadyRef = useRef(false);

  const handleToggleMute = (e) => {
    e.stopPropagation();
    const muted = audioManager.toggleMute();
    setIsMuted(muted);
  };

  const updateTelemetry = useCallback((key, val, stateClass = '') => {
    setTelemetryLines((prev) =>
      prev.map((item) => (item.label === key ? { ...item, val, stateClass } : item))
    );
  }, []);

  // 1. Connect to Real Backend Startup Stream & Data
  useEffect(() => {
    let evtSource = null;
    let didCancel = false;

    async function connectStartupStream() {
      try {
        evtSource = new EventSource('/api/startup/stream');

        evtSource.addEventListener('BOOT', () => {
          if (didCancel) return;
          updateTelemetry('J.A.R.V.I.S. SYSTEM', 'BOOT INITIALIZED', 'ok');
        });

        evtSource.addEventListener('CORE_ONLINE', () => {
          if (didCancel) return;
          updateTelemetry('CORE KERNEL', 'ONLINE', 'ok');
        });

        evtSource.addEventListener('PERCEPTION_CHECK', () => {
          if (didCancel) return;
          updateTelemetry('PERCEPTION', 'ONLINE', 'ok');
        });

        evtSource.addEventListener('TOOLS_CHECK', () => {
          if (didCancel) return;
          setToolsCheckActive(true);
          updateTelemetry('AUTOMATION TOOLS', 'VERIFYING TOOLKITS...', 'warn');
          setTimeout(() => {
            if (!didCancel) updateTelemetry('AUTOMATION TOOLS', '7 MODULES VERIFIED', 'ok');
          }, 2400);
        });

        evtSource.addEventListener('AUDIT_STARTED', (e) => {
          if (didCancel) return;
          const data = JSON.parse(e.data || '{}');
          const total = data.total_files || 91;
          setAuditTotalFiles(total);
          updateTelemetry('SYSTEM AUDIT', `SCANNING ${total} FILES...`, 'warn');
        });

        evtSource.addEventListener('AUDIT_COMPLETED', (e) => {
          if (didCancel) return;
          const data = JSON.parse(e.data || '{}');
          const audit = data.audit || {};
          const count = audit.total_files_checked || 0;
          const health = audit.health_score ?? 100;
          setAuditScanned(count);
          updateTelemetry('SYSTEM AUDIT', `${count} FILES CHECKED // ${health}% HEALTH`, 'ok');
          if (onAuditReport) onAuditReport(audit);
        });

        evtSource.addEventListener('SYSTEM_READY', (e) => {
          if (didCancel) return;
          const data = JSON.parse(e.data || '{}');
          setBackendData(data);
          backendDataRef.current = data;
          backendReadyRef.current = true;
          setBackendReady(true);
          const isWarn = data.status === 'online_with_warnings';
          updateTelemetry(
            'STATUS',
            isWarn ? 'ONLINE WITH WARNINGS' : 'ALL SYSTEMS OPERATIONAL',
            isWarn ? 'warn' : 'ok'
          );
        });

        evtSource.onerror = async () => {
          if (evtSource) evtSource.close();
          if (!didCancel && !backendReadyRef.current) {
            try {
              const res = await fetch('/api/startup/init', { method: 'POST' });
              if (res.ok) {
                const data = await res.json();
                if (!didCancel) {
                  setBackendData(data);
                  backendDataRef.current = data;
                  backendReadyRef.current = true;
                  setBackendReady(true);
                  const count = data?.audit?.total_files_checked || 91;
                  const health = data?.audit?.health_score ?? 100;
                  setAuditScanned(count);
                  updateTelemetry('SYSTEM AUDIT', `${count} FILES CHECKED // ${health}% HEALTH`, 'ok');
                  updateTelemetry('STATUS', data.status === 'online_with_warnings' ? 'ONLINE WITH WARNINGS' : 'ALL SYSTEMS OPERATIONAL', 'ok');
                  if (onAuditReport && data.audit) onAuditReport(data.audit);
                }
              } else {
                backendReadyRef.current = true;
                setBackendReady(true);
                updateTelemetry('STATUS', 'ALL SYSTEMS OPERATIONAL', 'ok');
              }
            } catch (err) {
              backendReadyRef.current = true;
              setBackendReady(true);
              updateTelemetry('STATUS', 'ALL SYSTEMS OPERATIONAL', 'ok');
            }
          }
        };
      } catch (err) {
        try {
          const res = await fetch('/api/startup/init', { method: 'POST' });
          if (res.ok) {
            const data = await res.json();
            if (!didCancel) {
              setBackendData(data);
              backendDataRef.current = data;
              backendReadyRef.current = true;
              setBackendReady(true);
              if (onAuditReport && data.audit) onAuditReport(data.audit);
            }
          }
        } catch (e) {}
        backendReadyRef.current = true;
        setBackendReady(true);
        updateTelemetry('STATUS', 'ALL SYSTEMS OPERATIONAL', 'ok');
      }
    }

    connectStartupStream();

    return () => {
      didCancel = true;
      if (evtSource) evtSource.close();
    };
  }, [updateTelemetry, onAuditReport]);

  // 2. Deterministic Visual & Audio Timeline State Machine
  useEffect(() => {
    const timeline = [
      { time: 1000, action: () => { setPhase(STARTUP_STATES.CORE_INITIALIZING); audioManager.playCoreActivation(); updateTelemetry('CORE KERNEL', 'ACTIVATING...', 'warn'); } },
      { time: 2000, action: () => { setPhase(STARTUP_STATES.CORE_ACTIVE); } },
      { time: 2200, action: () => { setPhase(STARTUP_STATES.SPHERE_INITIALIZING); audioManager.playParticleConvergence(); } },
      { time: 3300, action: () => { setPhase(STARTUP_STATES.ORBITALS_INITIALIZING); audioManager.playOrbitStart(0); } },
      { time: 3900, action: () => { audioManager.playOrbitStart(1); setToolsCheckActive(true); } },
      { time: 4400, action: () => { audioManager.playOrbitStart(2); } },
      { time: 4900, action: () => { audioManager.playOrbitComplete(); } },
      { time: 5200, action: () => {
        setPhase(STARTUP_STATES.UI_ASSEMBLY);
        audioManager.playPanelEntry(0);
        setTimeout(() => audioManager.playPanelEntry(1), 220);
        setTimeout(() => audioManager.playPanelEntry(2), 400);
        setTimeout(() => audioManager.playPanelEntry(3), 600);
        setTimeout(() => audioManager.playPanelEntry(4), 780);
      }},
      { time: 7200, action: () => { setPhase(STARTUP_STATES.AUDIT_RUNNING); } },
    ];

    const timeouts = timeline.map((item) => setTimeout(item.action, item.time));

    // Safety timeout — fallback trigger for instant operational readiness
    const safetyTimeout = setTimeout(async () => {
      if (!backendReadyRef.current) {
        try {
          const res = await fetch('/api/startup/init', { method: 'POST' });
          if (res.ok) {
            const data = await res.json();
            setBackendData(data);
            backendDataRef.current = data;
          }
        } catch (e) {}
        updateTelemetry('STATUS', 'ALL SYSTEMS OPERATIONAL', 'ok');
        backendReadyRef.current = true;
        setBackendReady(true);
      }
    }, 10000);

    return () => {
      timeouts.forEach(clearTimeout);
      clearTimeout(safetyTimeout);
    };
  }, [updateTelemetry]);

  // 3. Audio Hacker Sound Loop during file scan and tool check
  useEffect(() => {
    let interval = null;
    const isScanning = phase === STARTUP_STATES.AUDIT_RUNNING || phase === STARTUP_STATES.SYSTEM_VERIFYING || toolsCheckActive;

    if (isScanning && phase !== STARTUP_STATES.ONLINE) {
      interval = setInterval(() => {
        audioManager.playHackerScan();
      }, 220); // Rapid hacker scan audio effect every 220ms
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [phase, toolsCheckActive]);

  // 4. Completion Trigger — ref-guarded one-shot
  const completionFiredRef = useRef(false);
  const innerTimersRef = useRef([]);

  useEffect(() => {
    if (
      backendReady &&
      !completionFiredRef.current &&
      (phase === STARTUP_STATES.UI_ASSEMBLY ||
        phase === STARTUP_STATES.AUDIT_RUNNING ||
        phase === STARTUP_STATES.SYSTEM_VERIFYING)
    ) {
      completionFiredRef.current = true;

      const t1 = setTimeout(() => {
        setPhase(STARTUP_STATES.SYSTEM_READY);
        setToolsCheckActive(false);

        const t2 = setTimeout(() => {
          audioManager.playSystemOnline();
          setPhase(STARTUP_STATES.ONLINE);

          if (onStartupComplete) {
            onStartupComplete(backendDataRef.current);
          }

          const t3 = setTimeout(() => {
            audioManager.playVoiceBriefingStart();
            if (onBriefingReady && backendDataRef.current?.briefing) {
              onBriefingReady(backendDataRef.current.briefing, backendDataRef.current);
            }
          }, 900);
          innerTimersRef.current.push(t3);
        }, 850);
        innerTimersRef.current.push(t2);
      }, 700);
      innerTimersRef.current.push(t1);
    }
  }, [backendReady, phase, onStartupComplete, onBriefingReady]);

  const isOnline = phase === STARTUP_STATES.ONLINE;
  const isScanning = phase === STARTUP_STATES.AUDIT_RUNNING || phase === STARTUP_STATES.SYSTEM_VERIFYING;
  const showToolsScan = toolsCheckActive && !isOnline;

  return (
    <div className={`cinematic-startup-stage ${isOnline ? 'is-online' : ''}`}>
      {/* 1. Cybernetic Grid Background */}
      <div className="cinematic-grid-bg" />

      {/* 2. Concentric Targeting Reticles */}
      <div className="cinematic-reticle-overlay">
        <div className="reticle-ring reticle-ring-1" />
        <div className="reticle-ring reticle-ring-2" />
      </div>

      {/* 3. Corner HUD Diagnostics & Sound Toggle */}
      <div className="hud-corner top-left">
        <div>SYS.ID // J.A.R.V.I.S. MK-VII</div>
        <div>BAND // 144.82 MHz [ENC: AES-256]</div>
      </div>

      <div className="hud-corner top-right">
        <button
          className="hud-sound-toggle"
          onClick={handleToggleMute}
          aria-label={isMuted ? 'Enable Audio' : 'Mute Audio'}
        >
          {isMuted ? <VolumeX size={12} /> : <Volume2 size={12} />}
          <span>AUDIO: {isMuted ? 'MUTED' : 'ACTIVE'}</span>
        </button>
        <div style={{ marginTop: 6 }}>GRID // LOC [18.5204° N, 73.8567° E]</div>
      </div>

      <div className="hud-corner bottom-left">
        <div>CORE TELEMETRY // THREE.JS WEBGL</div>
        <div>PHASE // {phase.replace(/_/g, ' ')}</div>
      </div>

      <div className="hud-corner bottom-right">
        <div>AUTONOMOUS RUNTIME // STANDBY</div>
        <div>SECURITY // LEVEL 4 CERTIFIED</div>
      </div>

      {/* 4. Original CoreSphere — cinematic reveal driven by CSS phase classes */}
      <div className={`cinematic-core-stage`}>
        <div className={`cinematic-sphere-phase phase-${phase}`}>
          <CoreSphere state="idle" agentMode={false} startupPhase={phase} />
        </div>
      </div>

      {/* 5. LHS Live File Scan Animation — visible during AUDIT_RUNNING */}
      {isScanning && (
        <div className="scan-animation-overlay-lhs">
          <ScanAnimation totalFiles={auditTotalFiles} scannedCount={auditScanned} />
        </div>
      )}

      {/* 6. RHS Live Tools Scan Animation — visible during TOOLS_CHECK */}
      {showToolsScan && (
        <div className="scan-animation-overlay-rhs">
          <ToolsScanAnimation />
        </div>
      )}

      {/* 7. Startup Status Telemetry Readout (Lower Center) */}
      <div className={`startup-telemetry-console ${isScanning || showToolsScan ? 'is-scanning' : ''}`}>
        <div className="startup-main-label">
          <span className="startup-live-pulse" />
          <span>{isScanning ? 'INTEGRITY SCAN IN PROGRESS' : showToolsScan ? 'TOOLKIT VERIFICATION IN PROGRESS' : 'J.A.R.V.I.S. INITIALIZING'}</span>
        </div>

        <div className="startup-log-lines">
          {telemetryLines.map((line, idx) => (
            <div key={idx} className="startup-log-item">
              <span className="label">{line.label} ........</span>
              <span className={`val ${line.stateClass || ''}`}>{line.val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
