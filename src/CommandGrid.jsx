import React from 'react';

export default function CommandGrid({ quickActions, runCommand, busy }) {
  return (
    <div className="hud-command-grid panel">
      <p className="panel-label"><span>Quick Directives</span></p>
      <div className="action-grid">
        {quickActions.map(a => (
          <button key={a.label} className="action-btn" onClick={() => runCommand(a.cmd)} disabled={busy}>
            <a.icon size={16} /> {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
