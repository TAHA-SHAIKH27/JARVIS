import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  ArrowLeft, Smartphone, SmartphoneNfc, WifiOff,
  StopCircle, Home, ChevronLeft, LayoutGrid, Volume2, Volume1,
  Camera, RotateCcw, Send, ImagePlus, Mic, Play
} from 'lucide-react'

const WS_SCRCPY_HOST = 'localhost:8080'
const WS_SCRCPY_URL = `http://${WS_SCRCPY_HOST}`
// ws-scrcpy's internal ADB proxy port (fixed — see ws-scrcpy/src/common/Constants.ts SERVER_PORT)
const WS_SCRCPY_ADB_PORT = 8886

function buildStreamUrl(udid) {
  const wsUrl = new URL(`ws://${WS_SCRCPY_HOST}/`)
  wsUrl.searchParams.set('action', 'proxy-adb')
  wsUrl.searchParams.set('remote', `tcp:${WS_SCRCPY_ADB_PORT}`)
  wsUrl.searchParams.set('udid', udid)

  const hash = new URLSearchParams({
    action: 'stream',
    udid,
    // WebCodecsPlayer applies a CSS transform-scale down to a hardcoded
    // 480x480 default bounds (top-left origin) unless larger video
    // settings were previously saved via ws-scrcpy's own "Configure
    // stream" page — that's what makes it render tiny in the corner and
    // stutter on renegotiation. MsePlayer has no such hack: it's a plain
    // <video> that fills its container via CSS, so it's what we use here.
    player: 'mse',
    ws: wsUrl.toString(),
    fitToScreen: 'true',
  })

  return `${WS_SCRCPY_URL}/#!${hash.toString()}`
}

export default function PhoneMirrorPage({
  setActiveView,
  messages,
  prompt,
  setPrompt,
  busy,
  handleSend,
  isPushToTalkActive,
  togglePushToTalk,
  fileInputRef,
  pendingImage,
  setPendingImage,
  pendingDocument,
  setPendingDocument,
  extracting,
}) {
  const [mirrorActive, setMirrorActive] = useState(false)
  const [deviceStatus, setDeviceStatus] = useState('checking') // checking | connected | disconnected | no_adb
  const [deviceInfo, setDeviceInfo] = useState(null)
  const [wsScrcpyReady, setWsScrcpyReady] = useState(false)
  const [takingScreenshot, setTakingScreenshot] = useState(false)
  const [screenshotMsg, setScreenshotMsg] = useState('')
  const [controlFeedback, setControlFeedback] = useState('')
  const chatEndRef = useRef(null)
  const iframeRef = useRef(null)

  // Poll ws-scrcpy server availability
  const checkWsScrcpy = useCallback(async () => {
    try {
      const res = await fetch(WS_SCRCPY_URL, { mode: 'no-cors' })
      setWsScrcpyReady(true)
    } catch {
      setWsScrcpyReady(false)
    }
  }, [])

  // Poll ADB device status
  const pollDevices = useCallback(async () => {
    try {
      const res = await fetch('/api/phone/devices')
      if (!res.ok) { setDeviceStatus('disconnected'); return }
      const data = await res.json()
      const ready = (data.devices || []).find(d => d.status === 'device')
      if (data.status === 'error' && data.message?.includes('ADB')) {
        setDeviceStatus('no_adb')
        setDeviceInfo(null)
      } else if (ready) {
        setDeviceStatus('connected')
        setDeviceInfo(ready)
      } else {
        setDeviceStatus('disconnected')
        setDeviceInfo(null)
      }
    } catch {
      setDeviceStatus('disconnected')
    }
  }, [])

  useEffect(() => {
    pollDevices()
    checkWsScrcpy()
    const deviceTimer = setInterval(pollDevices, 6000)
    const scrcpyTimer = setInterval(checkWsScrcpy, 5000)
    return () => { clearInterval(deviceTimer); clearInterval(scrcpyTimer) }
  }, [pollDevices, checkWsScrcpy])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function startMirroring() {
    setMirrorActive(true)
  }

  function stopMirroring() {
    setMirrorActive(false)
    // Blank the iframe src to kill the WS connection cleanly
    if (iframeRef.current) iframeRef.current.src = 'about:blank'
  }

  async function sendPhoneKey(key) {
    try {
      const res = await fetch('/api/phone/key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key })
      })
      const data = await res.json().catch(() => ({}))
      setControlFeedback(data.message || key)
      setTimeout(() => setControlFeedback(''), 1800)
    } catch {
      setControlFeedback('Control failed')
      setTimeout(() => setControlFeedback(''), 1800)
    }
  }

  async function captureScreenshot() {
    if (takingScreenshot) return
    setTakingScreenshot(true)
    setScreenshotMsg('Capturing…')
    try {
      const res = await fetch('/api/phone/screenshot', { method: 'POST' })
      setScreenshotMsg(res.ok ? '✓ Saved' : '✗ Failed')
    } catch {
      setScreenshotMsg('✗ Failed')
    } finally {
      setTakingScreenshot(false)
      setTimeout(() => setScreenshotMsg(''), 2500)
    }
  }

  const statusColor = {
    connected: 'var(--green)',
    disconnected: 'var(--red)',
    no_adb: 'var(--amber)',
    checking: 'var(--text-faint)',
  }[deviceStatus]

  const statusLabel = {
    connected: mirrorActive ? 'PHONE CONNECTED · MIRRORING ACTIVE' : 'PHONE CONNECTED',
    disconnected: 'NO DEVICE FOUND',
    no_adb: 'ADB NOT INSTALLED',
    checking: 'SCANNING…',
  }[deviceStatus]

  const canMirror = deviceStatus === 'connected' && wsScrcpyReady

  return (
    <div className="fullpage-overlay">
      {/* ── Top bar ── */}
      <div className="fp-topbar">
        <button className="fp-back-btn" onClick={() => setActiveView('core')}>
          <ArrowLeft size={14} /> BACK TO JARVIS
        </button>
        <div className="fp-title">
          <SmartphoneNfc size={16} style={{ color: 'var(--cyan)' }} />
          <span>PHONE MIRRORING</span>
          <span style={{ fontSize: 9, color: 'var(--text-faint)', fontFamily: 'var(--font-mono)', letterSpacing: '.08em' }}>
            // ws-scrcpy
          </span>
        </div>
        <div className="mirror-status-bar">
          <span className="mirror-dot" style={{ background: statusColor, boxShadow: `0 0 8px ${statusColor}` }} />
          <span style={{ color: statusColor, fontSize: 10, letterSpacing: '.12em', fontFamily: 'var(--font-mono)' }}>
            {statusLabel}
          </span>
          {deviceInfo && (
            <span style={{ color: 'var(--text-faint)', fontSize: 9, fontFamily: 'var(--font-mono)', marginLeft: 8 }}>
              [{deviceInfo.serial}]
            </span>
          )}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="fp-body">

        {/* ── LEFT: Chat sidebar ── */}
        <div className="fp-chat-sidebar">
          <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <p className="panel-label"><span>Assistant</span><span>{messages.length} entries</span></p>
            <div className="chat-log" style={{ flex: 1 }}>
              {messages.map((m, i) => (
                <div key={i} className={`bubble ${m.role === 'user' ? 'user' : 'jarvis'}`}>
                  <span className="who">{m.role === 'user' ? 'You' : 'Jarvis'}</span>
                  {m.text}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            {pendingImage && (
              <div className="pending-image-chip">
                <img src={pendingImage.previewUrl} alt="preview" />
                <span className="pending-image-name">{pendingImage.fileName}</span>
                <button onClick={() => setPendingImage(null)}>✕</button>
              </div>
            )}
            {pendingDocument && (
              <div className="pending-image-chip">
                <span className="pending-image-name">{pendingDocument.fileName}</span>
                <button onClick={() => setPendingDocument(null)}>✕</button>
              </div>
            )}
            {extracting && <div className="listening-hint">Extracting document…</div>}
            <div className="input-row">
              <button className="icon-btn" onClick={() => fileInputRef.current?.click()} title="Attach">
                <ImagePlus size={14} />
              </button>
              <button
                className={`icon-btn ptt-btn ${isPushToTalkActive ? 'active-recording' : ''}`}
                onClick={togglePushToTalk}
                title="Push to talk"
                style={{ color: isPushToTalkActive ? 'var(--neon-red, #ff3b30)' : 'inherit' }}
              >
                {isPushToTalkActive ? <Mic className="pulsing" size={14} /> : <Mic size={14} />}
              </button>
              <input
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
                placeholder="Give a command…"
                disabled={busy}
                style={{ fontSize: 11 }}
              />
              <button
                className="send-btn"
                onClick={handleSend}
                disabled={busy || (!prompt.trim() && !pendingImage && !pendingDocument)}
              >
                {busy ? '…' : <Send size={13} />}
              </button>
            </div>
          </div>
        </div>

        {/* ── CENTER: ws-scrcpy embed ── */}
        <div className="fp-stream-area">
          <div className="phone-stream-container">

            {/* ws-scrcpy iframe embed — fills the screen area */}
            <div className="wss-embed-frame">
              {/* Scanning state */}
              {!mirrorActive && deviceStatus === 'checking' && (
                <div className="stream-placeholder">
                  <div className="stream-scanning-ring" />
                  <p style={{ marginTop: 16, color: 'var(--cyan)' }}>Scanning for devices…</p>
                </div>
              )}

              {/* No ADB */}
              {!mirrorActive && deviceStatus === 'no_adb' && (
                <div className="stream-placeholder">
                  <WifiOff size={44} style={{ color: 'var(--amber)', opacity: .5 }} />
                  <p style={{ color: 'var(--amber)', marginTop: 12 }}>ADB Not Found</p>
                  <p style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 6, maxWidth: 280, textAlign: 'center', lineHeight: 1.7 }}>
                    Install Android platform-tools and add adb to PATH,<br />
                    or set <code style={{ color: 'var(--amber)' }}>JARVIS_ADB_PATH</code> in .env
                  </p>
                </div>
              )}

              {/* No device */}
              {!mirrorActive && deviceStatus === 'disconnected' && (
                <div className="stream-placeholder">
                  <WifiOff size={44} style={{ color: 'var(--red)', opacity: .5 }} />
                  <p style={{ color: 'var(--red)', marginTop: 12 }}>No Device Connected</p>
                  <p style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 6, maxWidth: 280, textAlign: 'center', lineHeight: 1.7 }}>
                    Connect your phone via USB, enable USB debugging,<br />
                    and accept the "Allow USB debugging?" prompt.
                  </p>
                  <button className="mirror-retry-btn" onClick={pollDevices} style={{ marginTop: 14 }}>
                    <RotateCcw size={12} /> RETRY
                  </button>
                </div>
              )}

              {/* ws-scrcpy not running */}
              {!mirrorActive && deviceStatus === 'connected' && !wsScrcpyReady && (
                <div className="stream-placeholder">
                  <Smartphone size={44} style={{ color: 'var(--amber)', opacity: .5 }} />
                  <p style={{ color: 'var(--amber)', marginTop: 12 }}>ws-scrcpy Starting…</p>
                  <p style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 6, maxWidth: 280, textAlign: 'center', lineHeight: 1.7 }}>
                    The ws-scrcpy server is initialising on port 8080.<br />
                    It starts automatically with JARVIS — please wait.
                  </p>
                  <div className="stream-scanning-ring" style={{ marginTop: 16 }} />
                </div>
              )}

              {/* Ready — waiting for user to start */}
              {!mirrorActive && deviceStatus === 'connected' && wsScrcpyReady && (
                <div className="stream-placeholder">
                  <div className="wss-ready-glow">
                    <Smartphone size={52} style={{ color: 'var(--cyan)' }} />
                  </div>
                  <p style={{ color: 'var(--cyan)', marginTop: 16, fontSize: 12, letterSpacing: '.14em', fontFamily: 'var(--font-mono)' }}>
                    DEVICE READY
                  </p>
                  <p style={{ fontSize: 10, color: 'var(--text-faint)', margin: '6px 0 20px', fontFamily: 'var(--font-mono)' }}>
                    {deviceInfo?.serial}
                  </p>
                  <button
                    className="send-btn"
                    style={{ padding: '11px 32px', fontSize: 11, letterSpacing: '.14em', display: 'flex', alignItems: 'center', gap: 8 }}
                    onClick={startMirroring}
                  >
                    <Play size={13} /> START MIRRORING
                  </button>
                </div>
              )}

              {/* Live ws-scrcpy iframe */}
              {mirrorActive && deviceInfo?.serial && (
                <iframe
                  ref={iframeRef}
                  src={buildStreamUrl(deviceInfo.serial)}
                  title="ws-scrcpy Phone Mirror"
                  allow="fullscreen; autoplay"
                  className="wss-iframe"
                />
              )}
            </div>

            {/* Controls strip — available when device connected */}
            {deviceStatus === 'connected' && (
              <div className="phone-controls-strip">
                <button className="phone-ctrl-btn" onClick={() => sendPhoneKey('back')} title="Back">
                  <ChevronLeft size={16} />
                  <span>Back</span>
                </button>
                <button className="phone-ctrl-btn" onClick={() => sendPhoneKey('home')} title="Home">
                  <Home size={16} />
                  <span>Home</span>
                </button>
                <button className="phone-ctrl-btn" onClick={() => sendPhoneKey('recents')} title="Recents">
                  <LayoutGrid size={16} />
                  <span>Recents</span>
                </button>
                <div className="phone-ctrl-divider" />
                <button className="phone-ctrl-btn" onClick={() => sendPhoneKey('volume_up')} title="Vol +">
                  <Volume2 size={16} />
                  <span>Vol+</span>
                </button>
                <button className="phone-ctrl-btn" onClick={() => sendPhoneKey('volume_down')} title="Vol -">
                  <Volume1 size={16} />
                  <span>Vol-</span>
                </button>
                <div className="phone-ctrl-divider" />
                <button className="phone-ctrl-btn" onClick={captureScreenshot} disabled={takingScreenshot} title="Screenshot">
                  <Camera size={16} />
                  <span>{screenshotMsg || 'Shot'}</span>
                </button>
              </div>
            )}

            {controlFeedback && (
              <div className="phone-ctrl-feedback">{controlFeedback}</div>
            )}
          </div>

          {/* Action row */}
          <div className="fp-action-row">
            {mirrorActive ? (
              <button className="fp-end-btn" onClick={stopMirroring}>
                <StopCircle size={14} /> END MIRRORING
              </button>
            ) : (
              <button
                className="send-btn"
                style={{ padding: '10px 28px', fontSize: 11, letterSpacing: '.1em', display: 'flex', alignItems: 'center', gap: 8 }}
                onClick={startMirroring}
                disabled={!canMirror}
              >
                <Play size={13} /> START MIRRORING
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
