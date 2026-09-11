import React from 'react';

export default function CommandGrid({ quickActions, runCommand, busy, agentMode }) {
  return (
    <div className={`hud-command-grid panel ${agentMode ? 'agent-panel' : ''}`}>
      <p className="panel-label"><span>Quick Directives</span>{agentMode && <span className="agent-badge">AGENT</span>}</p>
      <div className="action-grid">
        {quickActions.map(a => (
          <button key={a.label} className={`action-btn ${a.cmd === 'toggle agent' ? 'agent-action' : ''} ${agentMode && a.cmd === 'toggle agent' ? 'active' : ''}`} onClick={() => runCommand(a.cmd)} disabled={busy} aria-pressed={a.cmd === 'toggle agent' ? agentMode : undefined}>
            <a.icon size={16} /> {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
