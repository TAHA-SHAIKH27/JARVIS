import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Settings, Send, Camera, Activity, Volume2, VolumeX, Volume1,
  Play, SkipForward, SkipBack, Search, FolderPlus, Trash2, Eye,
  File as FileIcon, Folder, X, RotateCcw,
  Lock, Moon, Battery, Wifi, Cloud, Clock, Smartphone, Power, RefreshCw, MessageSquare, ImagePlus,
  Mic, MicOff
} from 'lucide-react'
import Header from './Header';
import Telemetry from './Telemetry';
import CommandGrid from './CommandGrid';
import CoreSphere from './CoreSphere';
import PhonePanel from './PhonePanel';
import { useVoice } from './hooks/useVoice';

function formatBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function TimerWidget({ timerData, onCancel }) {
  const [remaining, setRemaining] = useState(timerData.seconds)
  const totalRef = useRef(timerData.seconds)
  const intervalRef = useRef(null)

  useEffect(() => {
    setRemaining(timerData.seconds)
    totalRef.current = timerData.seconds
    if (intervalRef.current) clearInterval(intervalRef.current)
    intervalRef.current = setInterval(() => {
      setRemaining(r => {
        if (r <= 1) { clearInterval(intervalRef.current); return 0 }
        return r - 1
      })
    }, 1000)
    return () => clearInterval(intervalRef.current)
  }, [timerData])

  const h = Math.floor(remaining / 3600)
  const m = Math.floor((remaining % 3600) / 60)
  const s = remaining % 60
  const display = h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  const pct = totalRef.current > 0 ? (remaining / totalRef.current) * 100 : 0
  const urgent = remaining <= 30 && remaining > 0
  const done = remaining === 0

  return (
    <div className="timer-strip">
      <div className="timer-icon">{done ? 'Γ£à' : 'ΓÅ▒∩╕Å'}</div>
      <div className="timer-info">
        <div className="timer-label">{timerData.label || 'TIMER'}</div>
        <div className={`timer-countdown ${urgent ? 'urgent' : ''}`}>
          {done ? "TIME'S UP!" : display}
        </div>
        <div className="timer-bar-wrap">
          <div className="timer-bar-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <button className="timer-cancel-btn" onClick={onCancel}>Γ£ò Cancel</button>
    </div>
  )
}

export default function App() {
  const [online, setOnline] = useState(true)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState({ cpu: 0, memory: 0, disk: 0, processes: [] })
  const [files, setFiles] = useState([])
  const [messages, setMessages] = useState([
    { role: 'jarvis', text: 'All systems online, sir. I am at your disposal.' }
  ])
  const [prompt, setPrompt] = useState('')
  const [fileData, setFileData] = useState(null)
  const [imageData, setImageData] = useState(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [geminiKey, setGeminiKey] = useState('')
  const [hfKey, setHfKey] = useState('')
  const [geminiProjectId, setGeminiProjectId] = useState('')
  const [groqKey, setGroqKey] = useState('')
  const [saveNote, setSaveNote] = useState('')
  const [googleLinked, setGoogleLinked] = useState(null)
  const [oauthBusy, setOauthBusy] = useState(false)
  const [oauthMsg, setOauthMsg] = useState('')
  const [logs, setLogs] = useState([])
  const [chatMode, setChatMode] = useState(false)
  const [pendingImage, setPendingImage] = useState(null)
  const [pendingDocument, setPendingDocument] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [timerData, setTimerData] = useState(null)
  const [booting, setBooting] = useState(true)
  const [activeView, setActiveView] = useState('core')

  useEffect(() => {
    const timer = setTimeout(() => setBooting(false), 1800)
    return () => clearTimeout(timer)
  }, [])

  // New voice system
  const voiceHook = useVoice({
    onTranscript: (event) => {
      // onTranscript only adds the user bubble — actual command execution
      // happens via runVoiceCommand (set on _setExecuteCommand below)
      if (event.type === 'final') {
        setMessages(m => [...m, { role: 'user', text: event.text }]);
      }
    },
    onError: (error) => {
      setMessages(m => [...m, { role: 'jarvis', text: `Voice error: ${error}` }]);
    },
  });

  const {
    isListening: voiceActive,
    isWakeDetected,
    isProcessing,
    isSpeaking: ttsSpeaking,
    transcript,
    partialTranscript,
    latency,
    startListening,
    stopListening,
    toggleListening,
    isPushToTalkActive,
    startPushToTalk,
    stopPushToTalk,
    _setExecuteCommand,
  } = voiceHook;

  // runVoiceCommand: like runCommand but does NOT add a user bubble
  // (the voice hook already adds it via onTranscript)
  async function runVoiceCommand(text) {
    if (!text.trim() || busy) return
    setBusy(true)
    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setMessages(m => [...m, { role: 'jarvis', text: err.detail || 'Command failed, sir.' }])
        setBusy(false)
        return
      }
      const data = await res.json()
      setMessages(m => [...m, { role: 'jarvis', text: data.speak }])
      speak(data.speak)
      setLogs(data.logs || [])
      setFileData(data.file_data || null)
      setImageData(data.image_data || null)
      if (data.timer_data) setTimerData(data.timer_data)
      if (data.refresh_files) refreshFiles()
      const logLines = data.logs || []

    } catch {
      setMessages(m => [...m, { role: 'jarvis', text: 'I lost connection to the core service, sir. Is the backend running?' }])
    } finally {
      setBusy(false)
    }
  }

  // Wire the execute command ref in the hook so auto-silence PTT can execute commands
  useEffect(() => {
    _setExecuteCommand?.(runVoiceCommand);
  }, [_setExecuteCommand])

  async function togglePushToTalk() {
    if (isPushToTalkActive) {
      // stopPushToTalk fires onTranscript (user bubble) + executeCommandRef (JARVIS reply)
      // We just stop it — execution is handled inside the hook via executeCommandRef
      await stopPushToTalk();
    } else {
      await startPushToTalk();
    }
  }

  const chatEndRef = useRef(null)
  const fileInputRef = useRef(null)
  const runCommandRef = useRef(() => { })

  function playBeep() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 800
    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.1)
  }

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status')
      setOnline(res.ok)
    } catch {
      setOnline(false)
    }
  }, [])

  const refreshStats = useCallback(async () => {
    try {
      const res = await fetch('/api/stats')
      if (res.ok) setStats(await res.json())
    } catch { }
  }, [])

  const refreshFiles = useCallback(async () => {
    try {
      const res = await fetch('/api/files')
      if (res.ok) {
        const data = await res.json()
        setFiles(data.files || [])
      }
    } catch { }
  }, [])

  useEffect(() => {
    refreshStatus()
    refreshStats()
    refreshFiles()
    const statusTimer = setInterval(refreshStatus, 8000)
    const statsTimer = setInterval(refreshStats, 4000)
    return () => { clearInterval(statusTimer); clearInterval(statsTimer) }
  }, [refreshStatus, refreshStats, refreshFiles])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    fetch('/api/config').then(r => r.ok ? r.json() : null).then(cfg => {
      if (cfg) {
        setGeminiKey(cfg.gemini_api_key || '')
        setHfKey(cfg.huggingface_api_key || '')
        setGeminiProjectId(cfg.gemini_project_id || '')
        setGroqKey(cfg.groq_api_key || '')
      }
    }).catch(() => { })
  }, [])

  const refreshOAuthStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/oauth/status')
      if (res.ok) {
        const data = await res.json()
        setGoogleLinked(!!data.authenticated)
      } else {
        setGoogleLinked(false)
      }
    } catch {
      setGoogleLinked(false)
    }
  }, [])

  useEffect(() => { refreshOAuthStatus() }, [refreshOAuthStatus])
  useEffect(() => { if (settingsOpen) refreshOAuthStatus() }, [settingsOpen, refreshOAuthStatus])

  useEffect(() => { runCommandRef.current = chatMode ? runStreamingChat : runCommand })

  function speak(text) {
    if (!text || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(text)
    utter.rate = 1
    utter.pitch = 0.85
    utter.onstart = () => setIsSpeaking(true)
    utter.onend = () => setIsSpeaking(false)
    utter.onerror = () => setIsSpeaking(false)
    window.speechSynthesis.speak(utter)
  }

  function toggleVoice() {
    toggleListening()
  }

  async function runCommand(text) {
    if (!text.trim() || busy) return
    setMessages(m => [...m, { role: 'user', text }])
    setPrompt('')
    setBusy(true)
    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setMessages(m => [...m, { role: 'jarvis', text: err.detail || 'Command failed, sir.' }])
        setBusy(false)
        return
      }
      const data = await res.json()
      setMessages(m => [...m, { role: 'jarvis', text: data.speak }])
      speak(data.speak)
      setLogs(data.logs || [])
      setFileData(data.file_data || null)
      setImageData(data.image_data || null)
      if (data.timer_data) setTimerData(data.timer_data)
      if (data.refresh_files) refreshFiles()
      const logLines = data.logs || []

    } catch {
      setMessages(m => [...m, { role: 'jarvis', text: 'I lost connection to the core service, sir. Is the backend running?' }])
    } finally {
      setBusy(false)
    }
  }

  async function runStreamingChat(text) {
    if (!text.trim() || busy) return
    setMessages(m => [...m, { role: 'user', text }, { role: 'jarvis', text: '' }])
    setPrompt('')
    setBusy(true)
    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      })
      if (!res.ok || !res.body) {
        setMessages(m => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'jarvis', text: 'I lost connection to the core service, sir.' }
          return copy
        })
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let full = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        full += decoder.decode(value, { stream: true })
        setMessages(m => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'jarvis', text: full }
          return copy
        })
      }
      if (full) speak(full)
    } catch {
      setMessages(m => {
        const copy = [...m]
        copy[copy.length - 1] = { role: 'jarvis', text: 'I lost connection to the core service, sir. Is the backend running?' }
        return copy
      })
    } finally {
      setBusy(false)
    }
  }

  function handleFileSelect(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    if (file.type.startsWith('image/')) {
      setPendingDocument(null)
      const reader = new FileReader()
      reader.onload = () => {
        const dataUrl = reader.result
        const base64 = dataUrl.split(',')[1] || ''
        setPendingImage({ base64, mimeType: file.type, previewUrl: dataUrl, fileName: file.name })
      }
      reader.readAsDataURL(file)
      return
    }

    setPendingImage(null)
    setExtracting(true)
    const formData = new FormData()
    formData.append('file', file)
    fetch('/api/document/extract', { method: 'POST', body: formData })
      .then(async res => {
        const data = await res.json().catch(() => ({}))
        if (res.ok) {
          setPendingDocument({ text: data.text, fileName: file.name, charCount: data.char_count, truncated: data.truncated })
        } else {
          setMessages(m => [...m, { role: 'jarvis', text: data.detail || `I couldn't read ${file.name}, sir.` }])
        }
      })
      .catch(() => {
        setMessages(m => [...m, { role: 'jarvis', text: 'I lost connection while uploading that file, sir.' }])
      })
      .finally(() => setExtracting(false))
  }

  async function runDocumentAnalysis(text, doc) {
    if (busy || !doc) return
    const questionText = text.trim() || 'Summarize this document for me, sir, and note any key points.'
    setMessages(m => [...m, { role: 'user', text: questionText, docName: doc.fileName }, { role: 'jarvis', text: '' }])
    setPrompt('')
    setPendingDocument(null)
    setBusy(true)
    try {
      const res = await fetch('/api/document/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_text: doc.text, filename: doc.fileName, prompt: questionText })
      })
      if (!res.ok || !res.body) {
        setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: 'I lost connection.' }; return copy })
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let full = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        full += decoder.decode(value, { stream: true })
        setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: full }; return copy })
      }
      if (full) speak(full)
    } catch {
      setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: 'Connection lost.' }; return copy })
    } finally {
      setBusy(false)
    }
  }

  async function runImageAnalysis(text, image) {
    if (busy || !image) return
    const questionText = text.trim() || 'Describe this image in detail, sir.'
    setMessages(m => [...m, { role: 'user', text: questionText, image: image.previewUrl }, { role: 'jarvis', text: '' }])
    setPrompt('')
    setPendingImage(null)
    setBusy(true)
    try {
      const res = await fetch('/api/vision/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: image.base64, mime_type: image.mimeType, prompt: questionText })
      })
      if (!res.ok || !res.body) {
        setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: 'Connection lost.' }; return copy })
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let full = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        full += decoder.decode(value, { stream: true })
        setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: full }; return copy })
      }
      if (full) speak(full)
    } catch {
      setMessages(m => { const copy = [...m]; copy[copy.length - 1] = { role: 'jarvis', text: 'Connection lost.' }; return copy })
    } finally {
      setBusy(false)
    }
  }

  function handleSend() {
    if (pendingImage) { runImageAnalysis(prompt, pendingImage); return }
    if (pendingDocument) { runDocumentAnalysis(prompt, pendingDocument); return }
    if (chatMode) runStreamingChat(prompt)
    else runCommand(prompt)
  }

  async function saveKeys() {
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gemini_api_key: geminiKey,
          huggingface_api_key: hfKey,
          gemini_project_id: geminiProjectId,
          groq_api_key: groqKey
        })
      })
      if (res.ok) {
        setSaveNote('Configuration saved.')
        setTimeout(() => setSaveNote(''), 2500)
      }
    } catch {
      setSaveNote('Save failed ΓÇö check connection.')
    }
  }

  async function linkGoogle() {
    setOauthBusy(true)
    setOauthMsg('Opening browser to sign in with GoogleΓÇª')
    try {
      const res = await fetch('/api/oauth/login', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (res.ok) { setOauthMsg(data.message || 'Google account linked.'); setGoogleLinked(true) }
      else setOauthMsg(data.detail || 'Failed to link Google account.')
    } catch {
      setOauthMsg('Could not reach the core service.')
    } finally {
      setOauthBusy(false)
      setTimeout(() => setOauthMsg(''), 5000)
    }
  }

  async function unlinkGoogle() {
    setOauthBusy(true)
    try {
      const res = await fetch('/api/oauth/logout', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      setOauthMsg(data.message || 'Google account unlinked.')
      setGoogleLinked(false)
    } catch {
      setOauthMsg('Could not reach the core service.')
    } finally {
      setOauthBusy(false)
      setTimeout(() => setOauthMsg(''), 3500)
    }
  }

  async function deleteFile(name) {
    try {
      const res = await fetch(`/api/files/delete?filename=${encodeURIComponent(name)}`, { method: 'DELETE' })
      if (res.ok) refreshFiles()
    } catch { }
  }

  async function viewFile(name) {
    try {
      const res = await fetch(`/api/files/read?filename=${encodeURIComponent(name)}`)
      if (res.ok) {
        const data = await res.json()
        setImageData(null)
        setFileData({ filename: data.filename, content: data.content })
      }
    } catch { }
  }

  const quickActions = [
    { label: 'Screenshot', icon: Camera, cmd: 'take a screenshot' },
    { label: 'PC Health', icon: Activity, cmd: 'check pc health' },
    { label: 'Vol +', icon: Volume2, cmd: 'volume up' },
    { label: 'Vol -', icon: Volume1, cmd: 'volume down' },
    { label: 'Mute', icon: VolumeX, cmd: 'mute' },
    { label: 'Play/Pause', icon: Play, cmd: 'play pause' },
    { label: 'Next Track', icon: SkipForward, cmd: 'next track' },
    { label: 'Prev Track', icon: SkipBack, cmd: 'previous track' },
    { label: 'Weather', icon: Cloud, cmd: 'weather in London' },
    { label: 'Date/Time', icon: Clock, cmd: 'what time is it' },
    { label: 'Battery', icon: Battery, cmd: 'battery status' },
    { label: 'Network', icon: Wifi, cmd: 'network info' },
    { label: 'Lock PC', icon: Lock, cmd: 'lock screen' },
    { label: 'Sleep', icon: Moon, cmd: 'sleep' },
    { label: 'Restart', icon: RefreshCw, cmd: 'restart the pc' },
    { label: 'Shutdown', icon: Power, cmd: 'shutdown' },
    { label: 'Clear Chat', icon: RotateCcw, cmd: 'clear chat' },
  ]

  const sphereState = ttsSpeaking ? 'speaking' : (busy || isProcessing) ? 'processing' : (voiceActive || isPushToTalkActive) ? 'listening' : isWakeDetected ? 'wake' : 'idle'

  return (
    <div className={`jarvis-root ${booting ? 'is-booting' : 'is-ready'}`}>
      {booting && (
        <div className="boot-screen" role="status" aria-live="polite">
          <div className="boot-mark">J</div>
          <p className="boot-kicker">STARK INDUSTRIES // SYSTEM STARTUP</p>
          <h1>J.A.R.V.I.S.</h1>
          <div className="boot-progress"><span /></div>
          <p className="boot-status">INITIALIZING NEURAL CORE <span>OK</span></p>
        </div>
      )}
      {/* TOP BAR */}
      <Header
        online={online}
        busy={busy}
        chatMode={chatMode}
        setChatMode={setChatMode}
        isSpeaking={ttsSpeaking}
        onOpenSettings={() => setSettingsOpen(true)}
        voiceActive={voiceActive}
        toggleVoice={toggleVoice}
        voiceEnabled={true}
        setVoiceEnabled={() => { }}
      />

      {/* MAIN 3-COLUMN GRID */}
      <nav className="module-rail" aria-label="JARVIS modules">
        <button className={activeView === 'core' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('core')}><Activity size={16} /><span>CORE</span></button>
        <button className={activeView === 'files' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('files')}><Folder size={16} /><span>FILES</span></button>
        <button className={activeView === 'phone' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('phone')}><Smartphone size={16} /><span>PHONE</span></button>
      </nav>
      <div className={`hud-grid view-${activeView}`}>

        {/* ΓöÇΓöÇ LEFT COLUMN: Chat + File Bay ΓöÇΓöÇ */}
        <div className="hud-left">

          {/* Chat / Transcript */}
          <div className="panel hud-panel-chat">
            <p className="panel-label"><span>Transcript</span><span>{messages.length} entries</span></p>
            <div className="chat-log">
              {messages.map((m, i) => (
                <div key={i} className={`bubble ${m.role === 'user' ? 'user' : 'jarvis'}`}>
                  <span className="who">{m.role === 'user' ? 'You' : 'Jarvis'}</span>
                  {m.image && <img className="bubble-image" src={m.image} alt="attachment" />}
                  {m.docName && (
                    <span className="bubble-doc-tag"><FileIcon size={12} /> {m.docName}</span>
                  )}
                  {m.text}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Pending image chip */}
            {pendingImage && (
              <div className="pending-image-chip">
                <img src={pendingImage.previewUrl} alt="preview" />
                <span className="pending-image-name">{pendingImage.fileName}</span>
                <button onClick={() => setPendingImage(null)}>Γ£ò</button>
              </div>
            )}
            {pendingDocument && (
              <div className="pending-image-chip">
                <FileIcon size={14} />
                <span className="pending-image-name">{pendingDocument.fileName}</span>
                <button onClick={() => setPendingDocument(null)}>Γ£ò</button>
              </div>
            )}
            {extracting && <div className="listening-hint">Extracting documentΓÇª</div>}

            {/* Input row */}
            <div className="input-row">
              <input
                type="file"
                ref={fileInputRef}
                style={{ display: 'none' }}
                accept="image/*,.pdf,.docx,.pptx,.txt,.md"
                onChange={handleFileSelect}
              />
              <button className="icon-btn" onClick={() => fileInputRef.current?.click()} title="Attach image or document">
                <ImagePlus size={15} />
              </button>
              <button
                className={`icon-btn ptt-btn ${isPushToTalkActive ? 'active-recording' : ''}`}
                onClick={togglePushToTalk}
                title={isPushToTalkActive ? 'Click to stop recording' : 'Click to talk (Push-to-Talk)'}
                style={{ color: isPushToTalkActive ? 'var(--neon-red, #ff3b30)' : 'inherit' }}
              >
                {isPushToTalkActive ? <Mic className="pulsing" size={15} /> : <Mic size={15} />}
              </button>
              <input
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
                placeholder={chatMode ? 'Chat with Jarvis…' : 'Give a command…'}
                disabled={busy}
              />
              <button className="send-btn" onClick={handleSend} disabled={busy || (!prompt.trim() && !pendingImage && !pendingDocument)}>
                {busy ? '…' : 'SEND'}
              </button>
            </div>
          </div>

          {/* File Bay */}
          <div className="panel hud-panel-files">
            <p className="panel-label"><span>File Bay</span><span>{files.length} items</span></p>
            <div className="file-bay">
              {files.length === 0 && <div className="empty-state">Workspace is empty, sir.</div>}
              {files.map(f => (
                <div className="file-row" key={f.relative_path}>
                  <span className="file-name">
                    {f.is_dir ? <Folder size={13} /> : <FileIcon size={13} />} {f.name}
                  </span>
                  <span className="file-actions">
                    {!f.is_dir && <span className="file-size">{formatBytes(f.size)}</span>}
                    {!f.is_dir && (
                      <button onClick={() => viewFile(f.name)} aria-label={`View ${f.name}`}><Eye size={12} /></button>
                    )}
                    <button className="danger" onClick={() => deleteFile(f.name)} aria-label={`Delete ${f.name}`}><Trash2 size={12} /></button>
                  </span>
                </div>
              ))}
            </div>
            {imageData?.image_base64 && (
              <img className="preview-img" src={`data:image/png;base64,${imageData.image_base64}`} alt={imageData.filename} />
            )}
            {fileData?.content && <div className="preview-text">{fileData.content}</div>}
          </div>
        </div>

        {/* ΓöÇΓöÇ CENTER COLUMN: Telemetry + Sphere + Logs ΓöÇΓöÇ */}
        <div className="hud-center">
          <Telemetry stats={stats} />

          <div className="panel hud-panel-sphere">
            <div className="core-display-container">
              <CoreSphere state={sphereState} />
            </div>
          </div>

          {logs.length > 0 && (
            <div className="panel log-ticker">
              {[...logs].reverse().map((l, i) => (
                <div key={i} className={`line ${l.startsWith('ACTION') ? 'exec' : l.startsWith('RESULT') ? 'result' : ''}`}>
                  {l}
                </div>
              ))}
            </div>
          )}

          {/* Timer Widget (center bottom) */}
          {timerData && <TimerWidget timerData={timerData} onCancel={() => setTimerData(null)} />}
        </div>

        {/* ΓöÇΓöÇ RIGHT COLUMN: Quick Actions + Notes + Phone Mirror ΓöÇΓöÇ */}
        <div className="hud-right">
          <CommandGrid quickActions={quickActions} runCommand={runCommand} busy={busy} />
          <PhonePanel />
        </div>
      </div>

      {/* Settings Modal */}
      {settingsOpen && (
        <div className="modal-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <button className="icon-btn" style={{ position: 'absolute', top: 16, right: 16 }} onClick={() => setSettingsOpen(false)} aria-label="Close">
              <X size={15} />
            </button>
            <p className="modal-title">CONFIGURATION</p>
            <p className="modal-sub">// neural processor credentials</p>

            {/* Google OAuth */}
            <div className="field">
              <label>Google Account (Gemini API via OAuth)</label>
              <div className="oauth-row">
                <div className="oauth-status">
                  <span className={`oauth-dot ${googleLinked === null ? 'checking' : googleLinked ? 'linked' : ''}`} />
                  {googleLinked === null ? 'CheckingΓÇª' : googleLinked ? 'Google account linked' : 'Not linked'}
                </div>
                {googleLinked
                  ? <button className="btn-secondary" onClick={unlinkGoogle} disabled={oauthBusy}>Unlink</button>
                  : <button className="btn-secondary" onClick={linkGoogle} disabled={oauthBusy}>Link Google</button>
                }
              </div>
              {oauthMsg && <div className="save-note" style={{ color: 'var(--cyan)' }}>{oauthMsg}</div>}
              <p className="oauth-hint">Linking lets Jarvis use your Google account for Gemini without an API key.</p>
            </div>

            <div className="field">
              <label>Gemini API Key</label>
              <input
                type="password"
                value={geminiKey}
                onChange={e => setGeminiKey(e.target.value)}
                placeholder="AIzaΓÇª"
              />
            </div>
            <div className="field">
              <label>Google Cloud Project ID (Vertex AI)</label>
              <input
                value={geminiProjectId}
                onChange={e => setGeminiProjectId(e.target.value)}
                placeholder="my-gcp-project-id"
              />
            </div>
            <div className="field">
              <label>HuggingFace API Key (Image Gen)</label>
              <input
                type="password"
                value={hfKey}
                onChange={e => setHfKey(e.target.value)}
                placeholder="hf_ΓÇª"
              />
            </div>
            <div className="field">
              <label>Groq API Key (Voice STT Fallback)</label>
              <input
                type="password"
                value={groqKey}
                onChange={e => setGroqKey(e.target.value)}
                placeholder="gsk_ΓÇª"
              />
              <p className="oauth-hint">Get free key at console.groq.com ΓÇö used as cloud fallback for voice transcription.</p>
            </div>
            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => setSettingsOpen(false)}>Cancel</button>
              <button className="send-btn" style={{ padding: '9px 20px' }} onClick={saveKeys}>Save</button>
            </div>
            {saveNote && <div className="save-note">{saveNote}</div>}
          </div>
        </div>
      )}
    </div>
  )
}
