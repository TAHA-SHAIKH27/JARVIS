import React, { useState, useEffect, useRef, useCallback } from 'react'

import {

  Settings, Send, Camera, Activity, Volume2, VolumeX, Volume1,

  Play, SkipForward, SkipBack, Search, FolderPlus, Trash2, Eye,

  File as FileIcon, Folder, X, RotateCcw,

  Lock, Moon, Battery, Wifi, Cloud, Clock, Smartphone, Power, RefreshCw, MessageSquare, ImagePlus,

  Mic, MicOff, Brain, Terminal

} from 'lucide-react'

import Header from './Header';

import Telemetry from './Telemetry';

import CommandGrid from './CommandGrid';

import CoreSphere from './CoreSphere';
import Jarvis3DCore from './components/Jarvis3DCore';
import StartupController from './components/StartupController';
import PhonePanel from './PhonePanel';

import PhoneMirrorPage from './PhoneMirrorPage';

import GalleryPage from './GalleryPage';

import CodeCorePage from './CodeCorePage';

import StartupAuditBanner from './StartupAuditBanner';

import ReminderBar from './components/ReminderBar';
import NotificationCenter from './components/NotificationCenter';
import { detectLang, pickBrowserVoice, voiceGender } from './langDetect';

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

      <div className="timer-icon">{done ? 'âœ“' : 'â³'}</div>

      <div className="timer-info">

        <div className="timer-label">{timerData.label || 'TIMER'}</div>

        <div className={`timer-countdown ${urgent ? 'urgent' : ''}`}>

          {done ? "TIME'S UP!" : display}

        </div>

        <div className="timer-bar-wrap">

          <div className="timer-bar-fill" style={{ width: `${pct}%` }} />

        </div>

      </div>

      <button className="timer-cancel-btn" onClick={onCancel}>âœ• Cancel</button>

    </div>

  )

}



export default function App() {

  const [online, setOnline] = useState(true)
  const [netState, setNetState] = useState('online')

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
  const [nvidiaKey, setNvidiaKey] = useState('')
  const [nvidiaModel, setNvidiaModel] = useState('meta/llama-3.3-70b-instruct')

  const [saveNote, setSaveNote] = useState('')

  const [googleLinked, setGoogleLinked] = useState(null)

  const [oauthBusy, setOauthBusy] = useState(false)

  const [oauthMsg, setOauthMsg] = useState('')

  const [notices, setNotices] = useState([])
  const knownNoticeIds = useRef(new Set())
  // Dismissed toast ids stay hidden even if a later poll still returns them
  // (e.g. the dismiss POST raced a blocked backend). Without this, a toast
  // that failed to dismiss server-side pops straight back and looks
  // "not removable".
  const dismissedNoticeIds = useRef(new Set())
  // Guards against double /api/command submits: `busy` state is stale inside
  // the voice-hook callback ref, so mirror it in a ref + ignore an identical
  // prompt re-sent within 3s (double-click Send, PTT echo, wake-word echo).
  const busyRef = useRef(false)
  const lastSentRef = useRef({ text: '', at: 0 })

  // ── Notification Center state (backend is the source of truth) ──
  const [unreadCount, setUnreadCount] = useState(0)
  const [activeReminders, setActiveReminders] = useState([])
  const [centerOpen, setCenterOpen] = useState(false)
  const [centerData, setCenterData] = useState(null)
  const [centerLoading, setCenterLoading] = useState(false)
  const [notifBusy, setNotifBusy] = useState(false)

  const [gmailLinked, setGmailLinked] = useState(null)

  const [gmailBusy, setGmailBusy] = useState(false)

  const [gmailMsg, setGmailMsg] = useState('')

  const [logs, setLogs] = useState([])

  const [chatMode, setChatMode] = useState(false)

  const [pendingImage, setPendingImage] = useState(null)
  const [pendingDocument, setPendingDocument] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [timerData, setTimerData] = useState(null)
  const [booting, setBooting] = useState(true)
  const [assembling, setAssembling] = useState(false) // true briefly after startup to play entry animations
  const [activeView, setActiveView] = useState('core')
  const [agentMode, setAgentMode] = useState(false)
  const [agentStatus, setAgentStatus] = useState('ready')
  const [agentEvents, setAgentEvents] = useState([])
  const [agentRunId, setAgentRunId] = useState('')
  const [agentWaitingForHuman, setAgentWaitingForHuman] = useState(false)
  const [agentQuestion, setAgentQuestion] = useState(null)
  const [queuedTasks, setQueuedTasks] = useState([])
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [clarificationPending, setClarificationPending] = useState(null)

  const [startupPayload, setStartupPayload] = useState(null)

  const handleStartupComplete = useCallback((payload) => {
    setBooting(false)
    setAssembling(true) // trigger panel entry animations
    if (payload) {
      setStartupPayload(payload)
    }
    // Clear assembling after animations complete (~1.5s)
    setTimeout(() => setAssembling(false), 1500)
  }, [])

  const handleBriefingReady = useCallback((briefingText) => {
    if (briefingText) {
      setMessages((m) => [...m, { role: 'jarvis', text: briefingText }])
      speak(briefingText, detectLang(briefingText))
    }
  }, [voiceEnabled])

  // New voice system
  const voiceHook = useVoice({
    muted: !voiceEnabled,
    onTranscript: (event) => {
      // onTranscript only adds the user bubble â€” actual command execution
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
  //
  // Bare stop-words spoken while JARVIS talks ("stop", "wait", …) silence
  // him instantly via this pattern — no backend round-trip needed.
  const LOCAL_STOP_RE = /^(stop|wait|hold on|halt|quiet|shush|never mind|that'?s enough)$/i

  function claimSendSlot(clean) {
    const now = Date.now()
    if (busyRef.current) return false
    const last = lastSentRef.current
    if (last.text === clean && (now - last.at) < 3000) return false
    lastSentRef.current = { text: clean, at: now }
    busyRef.current = true
    setBusy(true)
    return true
  }

  function releaseSendSlot() {
    busyRef.current = false
    setBusy(false)
  }

  // ── ChatGPT-style thinking bubble (in-transcript progress) ──────────────
  // A temporary jarvis message { thinking:true, stage, detail } sits at the
  // end of the transcript while the backend works. Stages mirror ChatGPT:
  // "Reading prompt" → "Thinking" → "Writing answer". Agent mode reuses the
  // same bubble but streams live step detail into it.
  // The bubble speaks the user's language: Devanagari prompt → Hindi labels.
  // Transcript language: Devanagari prompt → Hindi, unless Marathi
  // markers win (shared script). Drives thinking-bubble labels.
  const MR_MARK = ['माझा', 'माझं', 'माझी', 'तुम्ही', 'आम्ही', 'कसे', 'कशी', 'कुठे', 'आहे', 'नाही', 'नको', 'मला', 'तुला', 'होय', 'पाहिजे', 'करतो', 'करते', 'तुझा', 'तुझी', 'काय '];
  const HI_MARK = ['है', 'हैं', 'नहीं', 'मुझे', 'तुम्हें', 'कैसे', 'कहाँ', 'क्या', 'मेरा', 'मेरी', 'आपका', 'होगा', 'रहा', 'रही'];
  function textLang(t) {
    try {
      const s = t || '';
      if (!/[ऀ-ॿ]/.test(s)) return 'en';
      let mr = 0, hi = 0;
      for (const m of MR_MARK) if (s.includes(m)) mr++;
      for (const m of HI_MARK) if (s.includes(m)) hi++;
      return mr > hi ? 'mr' : 'hi';
    } catch { return 'en'; }
  }
  function isHindiText(t) {
    try { return textLang(t) === 'hi' } catch { return false }
  }
  function stageLabel(stage, lang) {
    if (lang === 'mr') {
      return stage === 'reading' ? 'वाचत आहे' : stage === 'thinking' ? 'विचार करत आहे' : 'लिहित आहे'
    }
    if (lang === 'hi') {
      return stage === 'reading' ? 'पढ़ रहा हूँ' : stage === 'thinking' ? 'सोच रहा हूँ' : 'लिख रहा हूँ'
    }
    return stage === 'reading' ? 'Reading prompt' : stage === 'thinking' ? 'Thinking' : 'Writing answer'
  }
  function pushThinking(userText, initialStage = 'reading') {
    const lang = textLang(userText)
    setMessages(m => [...m, { role: 'user', text: userText }, { role: 'jarvis', thinking: true, stage: initialStage, detail: '', text: '', lang }])
    setPrompt('')
  }

  function pushThinkingNoBubble(initialStage = 'reading', userText = '') {
    const lang = textLang(userText)
    setMessages(m => [...m, { role: 'jarvis', thinking: true, stage: initialStage, detail: '', text: '', lang }])
    setPrompt('')
  }

  function setThinkingStage(stage, detail) {
    setMessages(m => {
      const copy = [...m]
      const last = copy[copy.length - 1]
      if (!last || !last.thinking) return m
      copy[copy.length - 1] = { ...last, stage, ...(detail !== undefined ? { detail } : {}) }
      return copy
    })
  }

  function streamIntoThinking(fullText) {
    setMessages(m => {
      const copy = [...m]
      const last = copy[copy.length - 1]
      if (!last || !last.thinking) return m
      copy[copy.length - 1] = { ...last, stage: 'writing', text: fullText }
      return copy
    })
  }

  function resolveThinking(finalText) {
    setMessages(m => {
      const copy = [...m]
      const last = copy[copy.length - 1]
      if (last && last.thinking) {
        copy[copy.length - 1] = { role: 'jarvis', text: finalText }
      } else {
        copy.push({ role: 'jarvis', text: finalText })
      }
      return copy
    })
  }

  // Yield one paint frame so "Reading prompt" actually appears while the
  // payload is prepared (trim + language detect). Every transition after
  // that is driven by a REAL event — request dispatched, response received,
  // first stream chunk, SSE step — never by fixed seconds.
  function paintReadingFrame() {
    return new Promise((resolve) => {
      try {
        requestAnimationFrame(() => resolve())
      } catch {
        setTimeout(resolve, 0)
      }
    })
  }

  // ── Human word-by-word typewriter (ChatGPT-style writing) ─────────────
  // Normal + agentic replies arrive as one JSON string. Instead of dumping
  // the whole answer at once, we reveal it word-by-word so it reads like
  // Jarvis is writing/reading it live. Streaming endpoints reuse the same
  // rhythm via pushStreamChunk() so network chunks never dump mid-sentence.
  const typewriterRef = useRef(null)

  function stopTypewriter() {
    const tw = typewriterRef.current
    if (tw) {
      try { clearInterval(tw.timer) } catch { }
      try { tw.resolve && tw.resolve() } catch { }
      typewriterRef.current = null
    }
  }

  function setTypingBubble(shown, done) {
    setMessages(m => {
      const copy = [...m]
      const last = copy[copy.length - 1]
      if (!last) return m
      if (last.thinking) {
        copy[copy.length - 1] = { role: 'jarvis', text: shown, typing: !done }
      } else if (last.role === 'jarvis') {
        copy[copy.length - 1] = { ...last, text: shown, typing: !done }
      } else {
        copy.push({ role: 'jarvis', text: shown, typing: !done })
      }
      return copy
    })
  }

  function typewriteReply(fullText) {
    const full = (fullText || '').toString()
    stopTypewriter()
    if (!full) {
      resolveThinking('')
      return Promise.resolve()
    }
    // Tokenize into words, keeping whitespace so wrapping stays natural.
    const tokens = full.split(/(\s+)/).filter(t => t.length > 0)
    // Adaptive pace: short replies feel deliberate, long ones stay snappy.
    // ~1 word / 45ms for short, up to ~4 words / 28ms for long essays.
    const words = tokens.filter(t => /\S/.test(t)).length
    let wordsPerTick = 1
    let ms = 48
    if (words > 220) { wordsPerTick = 4; ms = 26 }
    else if (words > 120) { wordsPerTick = 3; ms = 30 }
    else if (words > 45) { wordsPerTick = 2; ms = 36 }
    return new Promise((resolve) => {
      let shownTokens = 0
      let shownWords = 0
      setTypingBubble('', false)
      const timer = setInterval(() => {
        // Emit N words (plus their trailing whitespace) per tick.
        let emitted = 0
        while (shownTokens < tokens.length && emitted < wordsPerTick) {
          const tok = tokens[shownTokens]
          shownTokens += 1
          if (/\S/.test(tok)) emitted += 1
          // Consume following whitespace with the word so we never stall
          // on a lone space token.
          while (shownTokens < tokens.length && /^\s+$/.test(tokens[shownTokens])) {
            shownTokens += 1
          }
        }
        shownWords += emitted
        const shown = tokens.slice(0, shownTokens).join('')
        const done = shownTokens >= tokens.length
        setTypingBubble(shown, done)
        if (done) {
          clearInterval(timer)
          if (typewriterRef.current && typewriterRef.current.timer === timer) {
            typewriterRef.current = null
          }
          resolve()
        }
      }, ms)
      typewriterRef.current = { timer, full, resolve }
    })
  }

  function completeTypingNow() {
    const tw = typewriterRef.current
    if (!tw) return
    try { clearInterval(tw.timer) } catch { }
    setTypingBubble(tw.full, true)
    try { tw.resolve && tw.resolve() } catch { }
    typewriterRef.current = null
  }

  // Streaming smoother: network chunks land in bursts — buffer them and
  // reveal word-by-word through the same typewriter bubble.
  const smoothStreamRef = useRef(null)

  function startSmoothStream() {
    try { if (smoothStreamRef.current) clearInterval(smoothStreamRef.current.timer) } catch { }
    setTypingBubble('', false)
    const state = { target: '', shown: '', timer: null, done: false }
    state.timer = setInterval(() => {
      if (state.shown.length >= state.target.length) {
        if (state.done) {
          clearInterval(state.timer)
          setTypingBubble(state.target, true)
          if (smoothStreamRef.current === state) smoothStreamRef.current = null
        }
        return
      }
      // Reveal up to the next word boundary (or a few chars for CJK/no-space text).
      let next = state.shown.length
      let wordsOut = 0
      const t = state.target
      while (next < t.length && wordsOut < 2) {
        // Consume non-space run (a word).
        while (next < t.length && !/\s/.test(t[next])) next += 1
        // Consume trailing spaces with the word.
        while (next < t.length && /\s/.test(t[next])) next += 1
        wordsOut += 1
        if (next - state.shown.length > 60) break
      }
      // Fallback: never stall when there are no spaces at all.
      if (next <= state.shown.length) next = Math.min(t.length, state.shown.length + 24)
      state.shown = t.slice(0, next)
      const finished = state.done && state.shown.length >= state.target.length
      setTypingBubble(state.shown, finished)
      if (finished) {
        clearInterval(state.timer)
        if (smoothStreamRef.current === state) smoothStreamRef.current = null
      }
    }, 42)
    smoothStreamRef.current = state
    return state
  }

  function pushStreamChunk(piece) {
    const st = smoothStreamRef.current
    if (!st) return
    st.target += (piece || '').toString()
  }

  async function finishSmoothStream() {
    const st = smoothStreamRef.current
    if (!st) return ''
    st.done = true
    // Wait (bounded) until the revealer catches up with the full target.
    const t0 = Date.now()
    while (smoothStreamRef.current === st && Date.now() - t0 < 15000) {
      if (st.shown.length >= st.target.length) break
      await new Promise(r => setTimeout(r, 60))
    }
    try { clearInterval(st.timer) } catch { }
    setTypingBubble(st.target, true)
    if (smoothStreamRef.current === st) smoothStreamRef.current = null
    return st.target
  }

  function abortSmoothStream() {
    try {
      const st = smoothStreamRef.current
      if (st) clearInterval(st.timer)
    } catch { }
    smoothStreamRef.current = null
  }

  async function runVoiceCommand(text) {
    const clean = (text || '').trim()
    if (!clean) return
    // Agent mid-run: route voice into the live run (merge / queue / interrupt)
    // instead of starting a separate normal-mode command.
    if (agentMode && agentRunId) {
      await sendInstruct(clean, false)
      return
    }
    // Local instant-stop: bare stop-word while JARVIS speaks silences him
    // immediately (frontend + backend voice) with no backend round-trip.
    if ((ttsSpeaking || isSpeaking) && LOCAL_STOP_RE.test(clean.replace(/[.?!]+$/, ''))) {
      try { window.speechSynthesis?.cancel() } catch { }
      setIsSpeaking(false)
      fetch('/api/voice/tts/interrupt', { method: 'POST' }).catch(() => {})
      setMessages(m => [...m, { role: 'jarvis', text: 'Stopped, sir.' }])
      return
    }
    if (!claimSendSlot(clean)) return
    // Voice path already added the user bubble via onTranscript — only the
    // thinking bubble goes in here.
    stopTypewriter()
    pushThinkingNoBubble('reading', clean)
    try {
      await paintReadingFrame()
      // Request is now on the wire — backend is thinking.
      setThinkingStage('thinking')
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: clean })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setThinkingStage('writing')
        await typewriteReply(err.detail || `Something went wrong on my end (HTTP ${res.status}) — please try again.`)
        releaseSendSlot()
        return
      }
      const data = await res.json()
      // Full reply received — now genuinely writing it out word by word.
      setThinkingStage('writing')
      speak(data.speak, data.speak_lang || detectLang(data.speak, clean))
      await typewriteReply(data.speak)
      setLogs(data.logs || [])
      setFileData(data.file_data || null)
      setImageData(data.image_data || null)
      if (data.timer_data) setTimerData(data.timer_data)
      if (data.refresh_files) refreshFiles()

    } catch {
      setThinkingStage('writing')
      await typewriteReply('I lost connection to the core service — is the backend running?')
    } finally {
      stopTypewriter()
      releaseSendSlot()
    }
  }

  // Wire the execute command ref in the hook so auto-silence PTT can execute commands.
  // No dep array: runs every render so the ref never holds a stale `busy` closure.
  useEffect(() => {
    _setExecuteCommand?.(runVoiceCommand);
  })

  async function togglePushToTalk() {
    if (isPushToTalkActive) {
      // stopPushToTalk fires onTranscript (user bubble) + executeCommandRef (JARVIS reply)
      // We just stop it â€” execution is handled inside the hook via executeCommandRef
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
      if (!res.ok) {
        setOnline(false)
        setNetState('backend_offline')
        return
      }
      setOnline(true)
    } catch {
      setOnline(false)
      setNetState('backend_offline')
      return
    }
    // Backend is up — now ask it about real internet connectivity so the
    // HUD can tell Wi-Fi-off / router-no-internet / Google-down apart.
    try {
      const net = await fetch('/api/network/status')
      if (net.ok) {
        const data = await net.json()
        setNetState(data.state || 'online')
      }
    } catch {
      /* keep last known netState */
    }
  }, [])

  const refreshNotices = useCallback(async () => {
    try {
      const res = await fetch('/api/notifications')
      if (!res.ok) return
      const data = await res.json()
      const items = (data.notifications || []).filter(n => !dismissedNoticeIds.current.has(n.id))
      const fresh = items.filter(n => !knownNoticeIds.current.has(n.id))
      if (fresh.length) {
        fresh.forEach(n => knownNoticeIds.current.add(n.id))
        playBeep()
      }
      setNotices(items.slice(0, 5))
      if (typeof data.unread_count === 'number') setUnreadCount(data.unread_count)
    } catch { }
  }, [])

  const refreshReminders = useCallback(async () => {
    // Active bar items only; the badge total arrives via /api/notifications.
    try {
      const res = await fetch('/api/reminders')
      if (!res.ok) return
      const data = await res.json()
      setActiveReminders(data.active || [])
    } catch { }
  }, [])

  // Backend-confirmed notification actions: mutate backend first, mirror
  // the confirmed state locally. On failure the item stays visible.
  async function notifAction(path, body, afterOk) {
    setNotifBusy(true)
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMessages(m => [...m, { role: 'jarvis', text: data.detail || 'That did not work, sir. The item is unchanged.' }])
        return null
      }
      if (typeof data.unread_count === 'number') setUnreadCount(data.unread_count)
      await refreshReminders()
      if (afterOk) await afterOk(data)
      return data
    } catch {
      setMessages(m => [...m, { role: 'jarvis', text: 'I lost connection to the core service, sir. Nothing was changed.' }])
      return null
    } finally {
      setNotifBusy(false)
    }
  }

  const snoozeReminder = useCallback((id, opts) => {
    const body = { id }
    if (opts && opts.when) body.when = opts.when
    else body.minutes = (opts && opts.minutes) || 10
    return notifAction('/api/notifications/snooze', body)
  }, [refreshReminders])

  const readReminder = useCallback((id) => notifAction('/api/notifications/read', { id }), [refreshReminders])
  const dismissReminder = useCallback((id) => notifAction('/api/notifications/dismiss', { id }), [refreshReminders])

  const fetchCenter = useCallback(async () => {
    setCenterLoading(true)
    try {
      const res = await fetch('/api/notifications/center')
      if (res.ok) {
        const data = await res.json()
        setCenterData(data)
        if (typeof data.unread_count === 'number') setUnreadCount(data.unread_count)
      }
    } catch { }
    finally { setCenterLoading(false) }
  }, [])

  const openNotifications = useCallback(() => {
    setCenterOpen(true)
    fetchCenter()
  }, [fetchCenter])

  // Notification Center actions: backend first, then re-pull the snapshot.
  const centerRefreshAfter = useCallback(async (data) => {
    if (data) await fetchCenter()
    return data
  }, [fetchCenter])

  const centerRead = useCallback((id) => notifAction('/api/notifications/read', { id }, centerRefreshAfter), [fetchCenter])
  const centerUnread = useCallback((id) => notifAction('/api/notifications/unread', { id }, centerRefreshAfter), [fetchCenter])
  const centerDelete = useCallback((id) => notifAction('/api/notifications/delete', { id }, centerRefreshAfter), [fetchCenter])
  const centerSnooze = useCallback((id, opts) => {
    const body = { id }
    if (opts && opts.when) body.when = opts.when
    else body.minutes = (opts && opts.minutes) || 10
    return notifAction('/api/notifications/snooze', body, centerRefreshAfter)
  }, [fetchCenter])
  const centerReschedule = useCallback((id, when) => {
    const bare = String(id).replace(/^scheduled:/, '')
    return notifAction(`/api/scheduled/${encodeURIComponent(bare)}/reschedule`, { when }, centerRefreshAfter)
  }, [fetchCenter])
  const centerReadAll = useCallback(() => notifAction('/api/notifications/read-all', {}, centerRefreshAfter), [fetchCenter])
  const centerClearHistory = useCallback(() => notifAction('/api/notifications/clear-history', {}, centerRefreshAfter), [fetchCenter])

  async function dismissNotice(id) {
    // Optimistic + sticky: remember locally so a slow/failed POST can never
    // pop the toast straight back on the next 8s poll.
    if (id) dismissedNoticeIds.current.add(id)
    else {
      try {
        const res = await fetch('/api/notifications')
        if (res.ok) {
          const data = await res.json()
          ;(data.notifications || []).forEach(n => dismissedNoticeIds.current.add(n.id))
        }
      } catch { }
    }
    setNotices(prev => (id ? prev.filter(n => n.id !== id) : []))
    try {
      const res = await fetch('/api/notifications/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(id ? { id } : { all: true })
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        if (typeof data.unread_count === 'number') setUnreadCount(data.unread_count)
      }
    } catch { }
  }

  // Declared up here (before the mount/poll effect below): the effect's
  // dependency array is evaluated during render, so this must already be
  // initialized — otherwise the whole page blanks with a TDZ ReferenceError.
  const refreshVoiceMute = useCallback(async () => {
    try {
      const res = await fetch('/api/voice/mute')
      if (res.ok) {
        const data = await res.json()
        if (typeof data.muted === 'boolean') setVoiceEnabled(!data.muted)
      }
    } catch { }
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
    refreshNotices()
    refreshReminders()
    refreshVoiceMute()
    const statusTimer = setInterval(() => { refreshStatus(); refreshNotices(); refreshReminders(); refreshVoiceMute() }, 8000)
    const statsTimer = setInterval(refreshStats, 4000)
    return () => { clearInterval(statusTimer); clearInterval(statsTimer) }
  }, [refreshStatus, refreshStats, refreshFiles, refreshNotices, refreshReminders, refreshVoiceMute])

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
        setNvidiaKey(cfg.nvidia_api_key || '')
        if (cfg.nvidia_model) setNvidiaModel(cfg.nvidia_model)
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

  const refreshGmailStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/gmail/status')
      if (res.ok) {
        const data = await res.json()
        setGmailLinked(!!data.linked)
      } else setGmailLinked(false)
    } catch {
      setGmailLinked(false)
    }
  }, [])

  useEffect(() => { refreshOAuthStatus() }, [refreshOAuthStatus])
  useEffect(() => { if (settingsOpen) refreshOAuthStatus() }, [settingsOpen, refreshOAuthStatus])
  useEffect(() => { refreshGmailStatus() }, [refreshGmailStatus])
  useEffect(() => { if (settingsOpen) refreshGmailStatus() }, [settingsOpen, refreshGmailStatus])

  useEffect(() => { runCommandRef.current = chatMode ? runStreamingChat : runCommand })

  const SPEAK_LOCALE = { hi: 'hi-IN', mr: 'mr-IN', ur: 'ur-PK', en: 'en-IN', fr: 'fr-FR', es: 'es-ES' }

  function speak(text, lang) {
    if (!voiceEnabled || !text || !window.speechSynthesis) return
    // Speak in the reply's language (Hindi/Urdu/Marathi/French/Spanish/English):
    // set the utterance locale and pick a matching installed voice.
    let resolved = (lang || '').slice(0, 2).toLowerCase()
    if (!resolved) {
      try { resolved = detectLang(text) } catch { resolved = 'en' }
    }
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(text)
    utter.rate = 0.88
    utter.pitch = 0.85
    try {
      utter.lang = SPEAK_LOCALE[resolved] || SPEAK_LOCALE.en
      const voice = pickBrowserVoice(resolved)
      if (voice) {
        utter.voice = voice
        try { console.log('[JARVIS voice]', voice.name, voice.lang) } catch { }
        // If the only voice for this language is female, say so plainly
        // (once per session) instead of mysteriously sounding wrong.
        try {
          if (!window.__jarvisVoiceWarned && ['hi', 'mr', 'ur'].includes(resolved)
              && voiceGender(voice.name) === 'female') {
            window.__jarvisVoiceWarned = true;
            console.warn('[JARVIS voice] No male ' + resolved + ' voice is installed — using '
              + voice.name + '. For a male Hindi voice, install "Microsoft Madhur": '
              + 'Windows Settings → Time & language → Language → add Hindi, then '
              + 'Speech → Manage voices → add Hindi. JARVIS will pick it up automatically.');
          }
        } catch { }
      }
    } catch { /* default voice stays */ }
    utter.onstart = () => setIsSpeaking(true)
    utter.onend = () => setIsSpeaking(false)
    utter.onerror = () => setIsSpeaking(false)
    window.speechSynthesis.speak(utter)
  }

  // The single "mute JARVIS" control: stops in-flight frontend speech
  // immediately and syncs backend speech (reminders/announcements) too.
  const toggleVoiceEnabled = useCallback(async () => {
    const next = !voiceEnabled
    setVoiceEnabled(next)
    if (!next) {
      try { window.speechSynthesis?.cancel() } catch { }
      setIsSpeaking(false)
    }
    try {
      const res = await fetch('/api/voice/mute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ muted: !next })
      })
      if (!res.ok) {
        setMessages(m => [...m, { role: 'jarvis', text: 'Frontend voice muted, sir — but I could not reach the backend voice, so PC announcements may still speak.' }])
      }
    } catch {
      setMessages(m => [...m, { role: 'jarvis', text: 'Frontend voice muted, sir — but I could not reach the backend voice, so PC announcements may still speak.' }])
    }
  }, [voiceEnabled])

  function toggleVoice() {
    toggleListening()
  }

  async function runCommand(text) {
    const cleanText = (text || '').trim()
    if (!cleanText) return
    // Handle agent mode toggle
    if (cleanText.toLowerCase() === 'toggle agent') {
      setAgentMode(!agentMode)
      setMessages(m => [...m, { role: 'jarvis', text: "Agent mode " + (agentMode ? 'deactivated' : 'activated') + ", sir." }])
      setPrompt('')
      return
    }
    if (!claimSendSlot(cleanText)) return
    stopTypewriter()
    pushThinking(text, 'reading')
    try {
      await paintReadingFrame()
      // Request is now on the wire — backend is thinking.
      setThinkingStage('thinking')
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setThinkingStage('writing')
        await typewriteReply(err.detail || `Something went wrong on my end (HTTP ${res.status}) — please try again.`)
        releaseSendSlot()
        return
      }
      const data = await res.json()
      // Full reply received — now genuinely writing it out word by word.
      setThinkingStage('writing')
      // Voice + typing start together — like Jarvis reads it aloud while writing.
      speak(data.speak, data.speak_lang || detectLang(data.speak, text))
      await typewriteReply(data.speak)
      setLogs(data.logs || [])
      setFileData(data.file_data || null)
      setImageData(data.image_data || null)
      if (data.timer_data) setTimerData(data.timer_data)
      if (data.refresh_files) refreshFiles()
      if (data.clarification_needed) {
        setClarificationPending({
          ...data.clarification_needed,
          originalPrompt: text
        })
      } else {
        setClarificationPending(null)
      }
      const logLines = data.logs || []

    } catch {
      setThinkingStage('writing')
      await typewriteReply('I lost connection to the core service — is the backend running?')
    } finally {
      stopTypewriter()
      releaseSendSlot()
    }
  }

  async function runStreamingChat(text) {
    const cleanChat = (text || '').trim()
    if (!cleanChat || !claimSendSlot(cleanChat)) return
    stopTypewriter()
    abortSmoothStream()
    pushThinking(text, 'reading')
    try {
      await paintReadingFrame()
      // Request is now on the wire — backend is thinking.
      setThinkingStage('thinking')
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      })
      if (!res.ok || !res.body) {
        setThinkingStage('writing')
        await typewriteReply('I lost connection to the core service.')
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let firstChunk = true
      startSmoothStream()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const piece = decoder.decode(value, { stream: true })
        if (firstChunk && piece) {
          firstChunk = false
          // First bytes arrived — genuinely writing now.
          setThinkingStage('writing')
        }
        // Buffer network bursts, reveal word-by-word like live writing.
        pushStreamChunk(piece)
      }
      const full = await finishSmoothStream()
      if (full) speak(full, detectLang(full, text))
      if (!full) await typewriteReply('I lost connection to the core service.')
    } catch {
      abortSmoothStream()
      setThinkingStage('writing')
      await typewriteReply('I lost connection to the core service.')
    } finally {
      abortSmoothStream()
      stopTypewriter()
      releaseSendSlot()
    }
  }

  async function runAgentMode(text) {
    const cleanAgent = (text || '').trim()
    if (!cleanAgent || !claimSendSlot(cleanAgent)) return
    stopTypewriter()
    pushThinking(text, 'reading')
    await paintReadingFrame()
    setAgentEvents([])
    setAgentRunId('')
    setAgentWaitingForHuman(false)
    setAgentQuestion(null)
    setQueuedTasks([])
    setAgentStatus('planning')
    setThinkingStage('thinking', 'Breaking down your request…')

    try {
      const res = await fetch('/api/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      })

      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}))
        await typewriteReply(err.detail || 'The agent failed to start — nothing was changed.')
        setAgentStatus('error')
        releaseSendSlot()
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalSpeak = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Parse SSE lines
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          try {
            const event = JSON.parse(raw)
            const { type, message, icon } = event

            if (type === 'run_started' && event.data?.run_id) setAgentRunId(event.data.run_id)
            if (type === 'human_intervention_required' || type === 'waiting_for_user') setAgentWaitingForHuman(true)
            if (type === 'clarification_required') {
              const q = event.data?.question || message
              setAgentWaitingForHuman(true)
              setAgentQuestion(q)
              speak(q)
            }

            // Update agent status + mirror live progress into the chat bubble
            if (type === 'planning' || type === 'plan_created' || type === 'plan_validated') { setAgentStatus('planning'); setThinkingStage('thinking', message || 'Drafting the plan…') }
            else if (type === 'step_started' || type === 'tool_started' || type === 'retrying' || type === 'replanning') { setAgentStatus('executing'); setThinkingStage('thinking', message || 'Working through the steps…') }
            else if (type === 'observing' || type === 'verification_started' || type === 'step_completed') { setAgentStatus('observing'); setThinkingStage('thinking', message || 'Checking that step…') }
            else if (type === 'human_intervention_required' || type === 'waiting_for_user' || type === 'clarification_required') { setAgentStatus('blocked'); setThinkingStage('thinking', message || 'I need you on this one…') }
            else if (type === 'step_failed' || type === 'verification_failed' || type === 'task_failed' || type === 'error') { setAgentStatus('error'); setThinkingStage('thinking', message || 'Hit a snag — recovering…') }
            else if (type === 'task_completed' || type === 'task_partial' || type === 'done') { setAgentStatus('completed'); setThinkingStage('writing', 'Wrapping up your answer…') }
            else if (type === 'final_verification') { setThinkingStage('thinking', 'Verifying the final result…') }

            // Accumulate event log
            if (type !== 'done') {
              const prefix = icon || (type === 'action_done' ? 'âœ“' : type === 'action_error' ? 'âœ—' : 'â†’')
              setAgentEvents(ev => [
                ...ev,
                { text: `${prefix} ${message}`, type }
              ])
            }

            // Capture final speak text
            if (type === 'task_completed' || type === 'task_partial' || type === 'task_failed') {
              finalSpeak = message
              setAgentWaitingForHuman(false)
              setAgentQuestion(null)
              if (Array.isArray(event.data?.queued)) setQueuedTasks(event.data.queued)
            }
            if (type === 'done') setAgentQuestion(null)
            if (type === 'task_queued' && Array.isArray(event.data?.queue)) setQueuedTasks(event.data.queue)
            if (type === 'task_queued_summary' && Array.isArray(event.data?.queued)) setQueuedTasks(event.data.queued)
          } catch { /* ignore parse errors */ }
        }
      }

      // Final answer types out word-by-word like live writing.
      const reply = finalSpeak || 'Done — that task is complete.'
      setThinkingStage('writing', 'Writing your answer…')
      speak(reply, detectLang(reply, text))
      await typewriteReply(reply)
      refreshFiles()

    } catch (err) {
      await typewriteReply('Lost the agent connection — is the backend still running?')
      setAgentStatus('error')
    } finally {
      stopTypewriter()
      releaseSendSlot()
    }
  }

  async function sendInstruct(text, withBubble = true) {
    // New command while a run is active: merge related changes, queue the rest.
    // Voice callers pass withBubble=false (the transcript bubble already exists).
    if (withBubble) setMessages(m => [...m, { role: 'user', text }])
    setPrompt('')
    try {
      const res = await fetch('/api/agent/instruct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: agentRunId, text })
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setAgentEvents(ev => [...ev, { text: `âœ• Instruction rejected: ${data.detail || 'run finished'}`, type: 'step_failed' }])
        return
      }
      setAgentEvents(ev => [...ev, { text: `â†’ ${data.speak || 'Noted, sir.'}`, type: data.status === 'queued' ? 'task_queued' : 'plan_restarted' }])
      if (Array.isArray(data.queued)) setQueuedTasks(data.queued)
      if (data.speak) speak(data.speak, detectLang(data.speak, text))
    } catch {
      setAgentEvents(ev => [...ev, { text: 'âœ• Could not reach the agent instruct endpoint.', type: 'step_failed' }])
    }
  }

  async function answerAgentQuestion(answer) {
    try {
      const res = await fetch('/api/agent/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: agentRunId, resolution: { answer } })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setAgentEvents(ev => [...ev, { text: `âœ• Could not send answer: ${err.detail || 'unknown error'}`, type: 'step_failed' }])
        return
      }
      setAgentQuestion(null)
      setAgentWaitingForHuman(false)
      setAgentStatus('executing')
      setAgentEvents(ev => [...ev, { text: 'â–¶ Answer received â€” carrying on.', type: 'resuming' }])
    } catch {
      setAgentEvents(ev => [...ev, { text: 'âœ• Could not reach the agent resume endpoint.', type: 'step_failed' }])
    }
  }

  async function resumeAgentAfterHuman() {
    if (!agentRunId || !agentWaitingForHuman) return
    try {
      const res = await fetch('/api/agent/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: agentRunId, resolution: { completed: true } })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setAgentEvents(ev => [...ev, { text: `âœ• Could not resume: ${err.detail || 'unknown error'}`, type: 'step_failed' }])
        return
      }
      setAgentWaitingForHuman(false)
      setAgentStatus('executing')
      setAgentEvents(ev => [...ev, { text: 'â–¶ Human verification acknowledged; resuming agent.', type: 'resuming' }])
    } catch {
      setAgentEvents(ev => [...ev, { text: 'âœ• Could not reach the agent resume endpoint.', type: 'step_failed' }])
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
          setMessages(m => [...m, { role: 'jarvis', text: data.detail || "I couldn't read " + file.name + ", sir." }])
        }
      })
      .catch(() => {
        setMessages(m => [...m, { role: 'jarvis', text: 'I lost connection while uploading that file, sir.' }])
      })
      .finally(() => setExtracting(false))
  }

  async function runDocumentAnalysis(text, doc) {
    if (busy || !doc) return
    const questionText = text.trim() || 'Summarize this document for me and note any key points.'
    stopTypewriter()
    abortSmoothStream()
    setMessages(m => [...m, { role: 'user', text: questionText, docName: doc.fileName }, { role: 'jarvis', thinking: true, stage: 'reading', detail: textLang(questionText) === 'mr' ? 'तुमचा दस्तऐवज वाचत आहे…' : isHindiText(questionText) ? 'आपका दस्तावेज़ पढ़ रहा हूँ…' : 'Reading your document…', text: '', lang: textLang(questionText) }])
    setPrompt('')
    setPendingDocument(null)
    setBusy(true)
    busyRef.current = true
    try {
      await paintReadingFrame()
      // Upload + backend read underway — thinking until words arrive.
      setThinkingStage('thinking', 'Working through it…')
      const res = await fetch('/api/document/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_text: doc.text, filename: doc.fileName, prompt: questionText })
      })
      if (!res.ok || !res.body) {
        setThinkingStage('writing')
        await typewriteReply('I lost connection while reading that.')
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let firstDocChunk = true
      startSmoothStream()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const piece = decoder.decode(value, { stream: true })
        // First bytes arrived — genuinely writing now.
        if (firstDocChunk && piece) { firstDocChunk = false; setThinkingStage('writing', 'Writing up the summary…') }
        pushStreamChunk(piece)
      }
      const full = await finishSmoothStream()
      if (full) speak(full, detectLang(full, questionText))
      if (!full) await typewriteReply('I lost connection while reading that.')
    } catch {
      abortSmoothStream()
      setThinkingStage('writing')
      await typewriteReply('Connection lost while reading that.')
    } finally {
      abortSmoothStream()
      stopTypewriter()
      busyRef.current = false
      setBusy(false)
    }
  }

  async function runImageAnalysis(text, image) {
    if (busy || !image) return
    const questionText = text.trim() || 'Describe this image in detail.'
    stopTypewriter()
    abortSmoothStream()
    setMessages(m => [...m, { role: 'user', text: questionText, image: image.previewUrl }, { role: 'jarvis', thinking: true, stage: 'reading', detail: textLang(questionText) === 'mr' ? 'तुमचं चित्र बघत आहे…' : isHindiText(questionText) ? 'आपकी तस्वीर देख रहा हूँ…' : 'Looking at your image…', text: '', lang: textLang(questionText) }])
    setPrompt('')
    setPendingImage(null)
    setBusy(true)
    busyRef.current = true
    try {
      await paintReadingFrame()
      // Upload + vision pass underway — thinking until words arrive.
      setThinkingStage('thinking', 'Studying the pixels…')
      const res = await fetch('/api/vision/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: image.base64, mime_type: image.mimeType, prompt: questionText })
      })
      if (!res.ok || !res.body) {
        setThinkingStage('writing')
        await typewriteReply('I lost connection while looking at that.')
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let firstImgChunk = true
      startSmoothStream()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const piece = decoder.decode(value, { stream: true })
        // First bytes arrived — genuinely writing now.
        if (firstImgChunk && piece) { firstImgChunk = false; setThinkingStage('writing', 'Describing what I see…') }
        pushStreamChunk(piece)
      }
      const full = await finishSmoothStream()
      if (full) speak(full, detectLang(full, questionText))
      if (!full) await typewriteReply('I lost connection while looking at that.')
    } catch {
      abortSmoothStream()
      setThinkingStage('writing')
      await typewriteReply('Connection lost while looking at that.')
    } finally {
      abortSmoothStream()
      stopTypewriter()
      busyRef.current = false
      setBusy(false)
    }
  }

  function handleSend() {
    // Answering a live agent question: reply into the paused run, no new task.
    if (agentWaitingForHuman && agentQuestion && agentRunId) {
      const answer = prompt.trim()
      if (!answer) return
      setMessages(m => [...m, { role: 'user', text: answer }])
      setPrompt('')
      answerAgentQuestion(answer)
      return
    }
    // Agent is mid-run: new commands merge into the plan or queue up.
    if (busy && agentRunId && agentMode && prompt.trim()) {
      sendInstruct(prompt.trim())
      return
    }
    if (pendingImage) { runImageAnalysis(prompt, pendingImage); return }
    if (pendingDocument) { runDocumentAnalysis(prompt, pendingDocument); return }
    if (clarificationPending) {
      const option = prompt.trim()
      const orig = clarificationPending.originalPrompt || ''
      setClarificationPending(null)
      const fullPrompt = orig ? `${orig} via ${option}` : option
      if (agentMode) runAgentMode(fullPrompt)
      else if (chatMode) runStreamingChat(fullPrompt)
      else runCommand(fullPrompt)
      return
    }
    if (agentMode) { runAgentMode(prompt); return }
    if (chatMode) runStreamingChat(prompt)
    else runCommand(prompt)
  }

  function handleClarificationSelect(option) {
    const orig = clarificationPending?.originalPrompt || ''
    const ctx = clarificationPending?.context || ''
    setClarificationPending(null)
    let fullPrompt = option
    if (orig) {
      if (ctx === 'messaging_app') {
        fullPrompt = `${orig} via ${option}`
      } else {
        fullPrompt = `${orig} (${option})`
      }
    }
    if (agentMode) runAgentMode(fullPrompt)
    else if (chatMode) runStreamingChat(fullPrompt)
    else runCommand(fullPrompt)
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
          groq_api_key: groqKey,
          nvidia_api_key: nvidiaKey,
          nvidia_model: nvidiaModel
        })
      })
      if (res.ok) {
        setSaveNote('Configuration saved.')
        setTimeout(() => setSaveNote(''), 2500)
      }
    } catch {
      setSaveNote('Save failed â€” check connection.')
    }
  }

  async function linkGoogle() {
    setOauthBusy(true)
    setOauthMsg('Opening browser to sign in with Googleâ€¦')
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

  async function linkGmail() {
    setGmailBusy(true)
    setGmailMsg('Opening browser to link Gmail (read-only)â€¦')
    try {
      const res = await fetch('/api/gmail/login', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (res.ok) { setGmailMsg(data.message || 'Gmail linked.'); setGmailLinked(true) }
      else setGmailMsg(data.detail || 'Failed to link Gmail.')
    } catch {
      setGmailMsg('Could not reach the core service.')
    } finally {
      setGmailBusy(false)
      setTimeout(() => setGmailMsg(''), 5000)
    }
  }

  async function unlinkGmail() {
    setGmailBusy(true)
    try {
      const res = await fetch('/api/gmail/logout', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      setGmailMsg(data.message || 'Gmail unlinked.')
      setGmailLinked(false)
    } catch {
      setGmailMsg('Could not reach the core service.')
    } finally {
      setGmailBusy(false)
      setTimeout(() => setGmailMsg(''), 3500)
    }
  }

  async function deleteFile(path) {
    try {
      const res = await fetch(`/api/files/delete?filename=${encodeURIComponent(path)}`, { method: 'DELETE' })
      if (res.ok) refreshFiles()
    } catch { }
  }

  async function viewFile(path) {
    try {
      const res = await fetch(`/api/files/read?filename=${encodeURIComponent(path)}`)
      if (res.ok) {
        const data = await res.json()
        setImageData(null)
        setFileData({ filename: data.filename, content: data.content })
      }
    } catch { }
  }

  const quickActions = [
    { label: 'Screenshot', icon: Camera, cmd: 'take a screenshot' },
    { label: 'Phone Mirroring', icon: Smartphone, cmd: 'mirror phone' },
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
    { label: 'Agent Mode', icon: Brain, cmd: 'toggle agent' },
  ]

  const sphereState = ttsSpeaking ? 'speaking' : (busy || isProcessing) ? 'processing' : (voiceActive || isPushToTalkActive) ? 'listening' : isWakeDetected ? 'wake' : 'idle'

  return (
    <div className={`jarvis-root ${booting ? 'is-booting' : 'is-ready'}`}>
      <StartupController
        onStartupComplete={handleStartupComplete}
        onBriefingReady={handleBriefingReady}
      />
      <StartupAuditBanner onOpenCode={() => setActiveView('code')} />
      {/* â”€â”€ Proactive notifications (Gmail watcher) â”€â”€ */}
      {notices.length > 0 && (
        <div style={{ position: 'fixed', top: 64, right: 16, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 360 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="notif-mini-btn" onClick={() => dismissNotice(null)} title="Dismiss all notifications" style={{ background: 'rgba(0,0,0,0.6)' }}>
              Clear all ({notices.length})
            </button>
          </div>
          {notices.map(n => (
            <div key={n.id} className="modal-box" style={{ padding: '10px 12px', borderLeft: '3px solid var(--cyan)', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <MessageSquare size={16} style={{ flexShrink: 0, marginTop: 2, color: 'var(--cyan)' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{n.title}</div>
                {n.body && <div style={{ fontSize: 12, opacity: 0.85, overflow: 'hidden', textOverflow: 'ellipsis' }}>{n.body}</div>}
              </div>
              <button className="icon-btn" onClick={() => dismissNotice(n.id)} aria-label="Dismiss" title="Dismiss">
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      {/* â”€â”€ Full-page overlays (Phone / Gallery) â”€â”€ */}
      {activeView === 'phone' && (
        <PhoneMirrorPage
          setActiveView={setActiveView}
          messages={messages}
          prompt={prompt}
          setPrompt={setPrompt}
          busy={busy}
          handleSend={handleSend}
          isPushToTalkActive={isPushToTalkActive}
          togglePushToTalk={togglePushToTalk}
          fileInputRef={fileInputRef}
          pendingImage={pendingImage}
          setPendingImage={setPendingImage}
          pendingDocument={pendingDocument}
          setPendingDocument={setPendingDocument}
          extracting={extracting}
        />
      )}
      {activeView === 'files' && (
        <GalleryPage setActiveView={setActiveView} />
      )}
      {activeView === 'code' && (
        <CodeCorePage setActiveView={setActiveView} />
      )}

      {/* â”€â”€ Core view (hidden when phone/files active) â”€â”€ */}
      <div className={agentMode ? 'agent-mode' : ''} style={{ display: activeView === 'core' ? 'contents' : 'none' }}>


      {/* TOP BAR */}
      <div className={assembling ? 'assemble-header' : ''}>
        <Header
          online={online}
          netState={netState}
          busy={busy}
          chatMode={chatMode}
          setChatMode={setChatMode}
          isSpeaking={ttsSpeaking}
          onOpenSettings={() => setSettingsOpen(true)}
          voiceActive={voiceActive}
          toggleVoice={toggleVoice}
          voiceEnabled={voiceEnabled}
          setVoiceEnabled={setVoiceEnabled}
          onToggleVoiceEnabled={toggleVoiceEnabled}
          agentMode={agentMode}
          setAgentMode={setAgentMode}
          agentStatus={agentStatus}
          unreadCount={unreadCount}
          onOpenNotifications={openNotifications}
        />
      </div>

      {/* MAIN 3-COLUMN GRID */}
      <nav className={`module-rail ${assembling ? 'assemble-rail' : ''}`} aria-label="JARVIS modules">
        <button className={activeView === 'core' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('core')}><Activity size={16} /><span>CORE</span></button>
        <button className={activeView === 'code' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('code')}><Terminal size={16} /><span>CODE CORE</span></button>
        <button className={activeView === 'files' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('files')}><Folder size={16} /><span>FILES</span></button>
        <button className={activeView === 'phone' ? 'rail-btn active' : 'rail-btn'} onClick={() => setActiveView('phone')}><Smartphone size={16} /><span>PHONE</span></button>
      </nav>
      <div className="hud-grid">

        {/* â”€â”€ LEFT COLUMN: Chat + File Bay â”€â”€ */}
        <div className="hud-left">

          {/* Chat / Transcript */}
          <div className={`panel hud-panel-chat ${assembling ? 'assemble-chat' : ''}`}>
            <p className="panel-label"><span>Transcript</span><span>{messages.length} entries</span></p>
            <div className="chat-log">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`bubble ${m.role === 'user' ? 'user' : 'jarvis'}${m.thinking ? ' thinking' : ''}${m.typing ? ' typing' : ''}`}
                  onClick={() => { if (m.typing) completeTypingNow() }}
                  title={m.typing ? 'Click to show full reply' : undefined}
                >
                  <span className="who">{m.role === 'user' ? 'You' : 'Jarvis'}</span>
                  {m.image && <img className="bubble-image" src={m.image} alt="attachment" />}
                  {m.docName && (
                    <span className="bubble-doc-tag"><FileIcon size={12} /> {m.docName}</span>
                  )}
                  {m.thinking ? (
                    <span className="thinking-row" aria-live="polite">
                      <span className="thinking-spinner" aria-hidden="true" />
                      <span className="thinking-stage">
                        {stageLabel(m.stage, m.lang)}
                      </span>
                      <span className="thinking-dots" aria-hidden="true"><span /><span /><span /></span>
                      {m.detail ? <span className="thinking-detail">{m.detail}</span> : null}
                      {m.text ? <span className="thinking-partial">{m.text}</span> : null}
                    </span>
                  ) : (
                    <span className="reply-text">{m.text}{m.typing ? <span className="typing-caret" aria-hidden="true" /> : null}</span>
                  )}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Pending image chip */}
            {pendingImage && (
              <div className="pending-image-chip">
                <img src={pendingImage.previewUrl} alt="preview" />
                <span className="pending-image-name">{pendingImage.fileName}</span>
                <button onClick={() => setPendingImage(null)}>âœ•</button>
              </div>
            )}
            {pendingDocument && (
              <div className="pending-image-chip">
                <FileIcon size={14} />
                <span className="pending-image-name">{pendingDocument.fileName}</span>
                <button onClick={() => setPendingDocument(null)}>âœ•</button>
              </div>
            )}
            {extracting && <div className="listening-hint">Extracting documentâ€¦</div>}

            {/* Clarification prompt panel */}
            {clarificationPending && (
              <div className="clarification-panel">
                <div className="clarification-hint">
                  <Brain className="clarification-icon" size={13} />
                  <span>CLARIFICATION REQUIRED</span>
                </div>
                <div style={{ color: 'var(--text)', fontSize: '12px', marginBottom: '8px', fontWeight: 500 }}>
                  {clarificationPending.question}
                </div>
                {clarificationPending.options && clarificationPending.options.length > 0 && (
                  <div className="clarification-options">
                    {clarificationPending.options.map((opt, idx) => (
                      <button
                        key={idx}
                        className="quick-reply-btn"
                        onClick={() => handleClarificationSelect(opt)}
                        disabled={busy}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Input row */}
            <div className={`input-row ${clarificationPending ? 'awaiting-clarification' : ''}`}>
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
                placeholder={agentQuestion ? `Answer: "${agentQuestion}"` : (busy && agentRunId) ? 'JARVIS is working â€” instruct or queueâ€¦' : clarificationPending ? `Answer: "${clarificationPending.question}"` : chatMode ? 'Chat with Jarvisâ€¦' : 'Give a commandâ€¦'}
                disabled={busy && !agentRunId && !(agentWaitingForHuman && agentQuestion)}
              />
              <button className="send-btn" onClick={handleSend} disabled={(busy && !agentRunId && !(agentWaitingForHuman && agentQuestion)) || (!prompt.trim() && !pendingImage && !pendingDocument && !clarificationPending)}>
                {busy ? 'â€¦' : 'SEND'}
              </button>
            </div>
          </div>

          {/* File Bay */}
          <div className={`panel hud-panel-files ${assembling ? 'assemble-files' : ''}`}>
            <p className="panel-label" onClick={() => setActiveView('files')} style={{ cursor: 'pointer' }} title="Click to open full Files & Gallery Album">
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Folder size={12} style={{ color: 'var(--cyan)' }} /> File Bay &amp; Album
              </span>
              <span className="clickable-tag" style={{ background: 'rgba(0,242,254,0.15)', padding: '2px 8px', borderRadius: 4, color: 'var(--cyan)', fontSize: 10 }}>
                OPEN ALBUM â†—
              </span>
            </p>
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
                      <button onClick={() => viewFile(f.relative_path)} aria-label={`View ${f.name}`}><Eye size={12} /></button>
                    )}
                    <button className="danger" onClick={() => deleteFile(f.relative_path)} aria-label={`Delete ${f.name}`}><Trash2 size={12} /></button>
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

        {/* â”€â”€ CENTER COLUMN: Telemetry + Sphere + Logs â”€â”€ */}
        <div className="hud-center">
          <div className={assembling ? 'assemble-telemetry' : ''}>
            <Telemetry stats={stats} />
          </div>

          <div className="panel hud-panel-sphere">
            <div className="core-display-container">
              <CoreSphere
                state={sphereState}
                agentMode={agentMode}
              />
            </div>
          </div>

          {/* Show agent events in Agent Mode, otherwise show normal logs */}
          {agentMode && agentEvents.length > 0 && (
            <div className={`panel log-ticker ${assembling ? 'assemble-ticker' : ''}`}>
              {agentWaitingForHuman && (
                <div className="line exec">
                  Human verification is required in the browser or app. Complete it, then{' '}
                  <button className="btn-secondary" onClick={resumeAgentAfterHuman}>RESUME AGENT</button>
                </div>
              )}
              {queuedTasks.length > 0 && (
                <div className="line exec">
                  â³ Queued ({queuedTasks.length}): {queuedTasks[0].slice(0, 70)}{' '}
                  <button className="btn-secondary" onClick={() => { const [next, ...rest] = queuedTasks; setQueuedTasks(rest); runAgentMode(next) }}>RUN NEXT</button>{' '}
                  <button className="btn-secondary" onClick={() => setQueuedTasks([])}>CLEAR</button>
                </div>
              )}
              {[...agentEvents].reverse().map((ev, i) => (
                <div key={i} className={`line ${ev.type === 'step_completed' ? 'result' : ev.type === 'step_failed' ? 'exec' : ev.type === 'planning' ? 'exec' : ''}`}>
                  {ev.text}
                </div>
              ))}
            </div>
          )}
          {!agentMode && logs.length > 0 && (
            <div className={`panel log-ticker ${assembling ? 'assemble-ticker' : ''}`}>
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

        {/* â”€â”€ RIGHT COLUMN: Quick Actions + Notes + Phone Mirror â”€â”€ */}
        <div className="hud-right">
          {activeReminders.length > 0 && (
            <ReminderBar
              reminder={activeReminders[0]}
              moreCount={activeReminders.length - 1}
              onSnooze={snoozeReminder}
              onRead={readReminder}
              onDismiss={dismissReminder}
              onOpenCenter={openNotifications}
              busy={notifBusy}
            />
          )}
          <div className={assembling ? 'assemble-directives' : ''}>
            <CommandGrid quickActions={quickActions} runCommand={runCommand} busy={busy} agentMode={agentMode} />
          </div>
          <div className={assembling ? 'assemble-phone' : ''}>
            <PhonePanel />
          </div>
        </div>
      </div>
      </div>{/* end core-view wrapper */}

      {/* Notification Center overlay (JARVIS-native panel, Esc to close) */}
      {centerOpen && (
        <NotificationCenter
          data={centerData}
          loading={centerLoading}
          busy={notifBusy}
          onClose={() => setCenterOpen(false)}
          onRead={centerRead}
          onUnread={centerUnread}
          onDelete={centerDelete}
          onSnooze={centerSnooze}
          onReschedule={centerReschedule}
          onReadAll={centerReadAll}
          onClearHistory={centerClearHistory}
          onRefresh={fetchCenter}
        />
      )}

      {/* Settings Modal (always rendered so it can open from any view) */}
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
                  {googleLinked === null ? 'Checkingâ€¦' : googleLinked ? 'Google account linked' : 'Not linked'}
                </div>
                {googleLinked
                  ? <button className="btn-secondary" onClick={unlinkGoogle} disabled={oauthBusy}>Unlink</button>
                  : <button className="btn-secondary" onClick={linkGoogle} disabled={oauthBusy}>Link Google</button>
                }
              </div>
              {oauthMsg && <div className="save-note" style={{ color: 'var(--cyan)' }}>{oauthMsg}</div>}
              <p className="oauth-hint">Linking lets Jarvis use your Google account for Gemini without an API key.</p>
            </div>

            {/* Gmail watcher (proactive important-mail announcements) */}
            <div className="field">
              <label>Gmail Watcher (important-mail announcements)</label>
              <div className="oauth-row">
                <div className="oauth-status">
                  <span className={`oauth-dot ${gmailLinked === null ? 'checking' : gmailLinked ? 'linked' : ''}`} />
                  {gmailLinked === null ? 'Checkingâ€¦' : gmailLinked ? 'Gmail linked' : 'Not linked'}
                </div>
                {gmailLinked
                  ? <button className="btn-secondary" onClick={unlinkGmail} disabled={gmailBusy}>Unlink</button>
                  : <button className="btn-secondary" onClick={linkGmail} disabled={gmailBusy}>Link Gmail</button>
                }
              </div>
              {gmailMsg && <div className="save-note" style={{ color: 'var(--cyan)' }}>{gmailMsg}</div>}
              <p className="oauth-hint">Read + send. Jarvis checks on restart + every 30 min and speaks + toasts VIP/urgent mail. VIP senders list: backend/data/gmail_watch.json</p>
            </div>

            <div className="field">
              <label>Gemini API Key</label>
              <input
                type="password"
                value={geminiKey}
                onChange={e => setGeminiKey(e.target.value)}
                placeholder="AIzaâ€¦"
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
                placeholder="hf_â€¦"
              />
            </div>
            <div className="field">
              <label>Groq API Key (Voice STT Fallback)</label>
              <input
                type="password"
                value={groqKey}
                onChange={e => setGroqKey(e.target.value)}
                placeholder="gsk_..."
              />
              <p className="oauth-hint">Get free key at console.groq.com â€” used as cloud fallback for voice transcription.</p>
            </div>
            <div className="field">
              <label>NVIDIA NIM API Key (Autonomous Code Core)</label>
              <input
                type="password"
                value={nvidiaKey}
                onChange={e => setNvidiaKey(e.target.value)}
                placeholder="nvapi-..."
              />
              <p className="oauth-hint">Get free key at build.nvidia.com â€” powers specialized code audits, bug repairs, and refactoring.</p>
            </div>
            <div className="field">
              <label>NVIDIA NIM Coding Model</label>
              <input
                value={nvidiaModel}
                onChange={e => setNvidiaModel(e.target.value)}
                placeholder="meta/llama-3.3-70b-instruct"
              />
              <p className="oauth-hint">Examples: meta/llama-3.3-70b-instruct, deepseek-ai/deepseek-r1, qwen/qwen2.5-coder-32b-instruct</p>
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

