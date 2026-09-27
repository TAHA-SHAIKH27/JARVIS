import React from 'react';
import { Settings, Mic, MicOff, Brain, X, Bell } from 'lucide-react';

export default function Header({ online, busy, chatMode, setChatMode, isSpeaking, onOpenSettings, voiceActive, toggleVoice, voiceEnabled, setVoiceEnabled, agentMode, setAgentMode, agentStatus, unreadCount = 0, onOpenNotifications }) {
  let statusLabel = 'ONLINE';
  let statusClass = '';
  if (!online) statusLabel = 'OFFLINE', statusClass = 'offline';
  else if (busy) statusLabel = 'PROCESSING', statusClass = 'busy';
  else if (isSpeaking) statusLabel = 'SPEAKING', statusClass = 'awake';
  else if (voiceActive) statusLabel = 'LISTENING', statusClass = 'awake';
  else if (agentMode) statusLabel = 'AGENT', statusClass = 'agent';

  return (
    <div className="topbar-header">
      <div className="wordmark">J.A.R.V.I.S.</div>

      <div className="header-cluster">
        <div className="status-pill">
          <span className={`status-dot ${statusClass}`} />
          {statusLabel}
        </div>

        <button
          className={`icon-btn mic-btn ${voiceActive ? 'active' : ''}`}
          onClick={toggleVoice}
          title={voiceActive ? 'Disable Wake Word (listening)' : 'Enable Wake Word (offline)'}
        >
          {voiceActive ? <Mic size={15} /> : <MicOff size={15} />}
        </button>

        <button
          className={`icon-btn chat-mode-btn ${chatMode ? 'active' : ''}`}
          onClick={() => setChatMode(v => !v)}
          title={chatMode ? 'Chat mode — click for command mode' : 'Command mode — click for chat mode'}
        >
          {chatMode ? '💬' : '⚡'}
        </button>

        <button
          className={`icon-btn ${agentMode ? 'active' : ''}`}
          onClick={() => setAgentMode(!agentMode)}
          title={agentMode ? 'Exit Agent Mode' : 'Enter Agent Mode'}
        >
          {agentMode ? <X size={15} /> : <Brain size={15} />}
        </button>

        <button
          className="icon-btn notif-btn"
          onClick={onOpenNotifications}
          title={unreadCount > 0 ? `${unreadCount} unread notification${unreadCount === 1 ? '' : 's'} — open Notification Center` : 'Open Notification Center'}
          aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        >
          <Bell size={15} />
          {unreadCount > 0 && (
            <span className="notif-badge" aria-hidden="true">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>

        <button
          className={`icon-btn ${voiceEnabled ? 'active' : ''}`}
          onClick={() => setVoiceEnabled(v => !v)}
          title={voiceEnabled ? 'Voice on' : 'Voice off'}
        >
          {voiceEnabled ? '🔊' : '🔇'}
        </button>

        <button className="icon-btn" onClick={onOpenSettings} title="Settings" aria-label="Settings">
          <Settings size={15} />
        </button>
      </div>

      {agentMode && (
        <div className="agent-status-bar">
          <span>Agent: {agentStatus}</span>
        </div>
      )}
    </div>
  );
}
