import React, { useState } from 'react';
import { Bell, Check, X, Clock } from 'lucide-react';

// Horizontal reminder bar shown above Quick Directives while a triggered,
// unread reminder needs attention. Dismissing the bar only marks the reminder
// read/dismissed on the backend — the record stays available in the
// Notification Center history.
export default function ReminderBar({ reminder, moreCount = 0, onSnooze, onRead, onDismiss, onOpenCenter, busy }) {
  const [snoozeChoice, setSnoozeChoice] = useState('10');

  if (!reminder) return null;

  const dueLabel = (() => {
    try {
      const d = new Date(reminder.due_at || reminder.ts);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
    } catch { return ''; }
  })();

  function handleSnooze() {
    if (snoozeChoice === 'tomorrow') {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      onSnooze(reminder.id, { when: d.toISOString() });
    } else {
      onSnooze(reminder.id, { minutes: Number(snoozeChoice) });
    }
  }

  // Priority accent: urgent glows red-ish, important amber, normal cyan.
  const prio = reminder.priority === 'urgent' ? 'prio-urgent'
    : reminder.priority === 'important' ? 'prio-important' : '';

  return (
    <div className={`reminder-bar ${prio}`} role="alert" aria-live="polite" aria-label={`Reminder: ${reminder.body}`}>
      <span className="reminder-bar-icon"><Bell size={15} /></span>
      <div className="reminder-bar-text" onClick={onOpenCenter} title="Open Notification Center">
        <span className="reminder-bar-body">{reminder.body}</span>
        {dueLabel && <span className="reminder-bar-time">{dueLabel}</span>}
        {moreCount > 0 && <span className="reminder-bar-more">+{moreCount} more</span>}
      </div>
      <label className="reminder-snooze-wrap" title="Snooze this reminder">
        <Clock size={13} />
        <select
          className="reminder-snooze-select"
          value={snoozeChoice}
          onChange={e => setSnoozeChoice(e.target.value)}
          disabled={busy}
          aria-label="Snooze duration"
        >
          <option value="10">10m</option>
          <option value="30">30m</option>
          <option value="60">1h</option>
          <option value="tomorrow">Tomorrow</option>
        </select>
        <button className="reminder-bar-btn" onClick={handleSnooze} disabled={busy} title="Snooze">Snooze</button>
      </label>
      <button className="reminder-bar-btn" onClick={() => onRead(reminder.id)} disabled={busy} title="Mark as read" aria-label="Mark reminder as read">
        <Check size={14} />
      </button>
      <button className="reminder-bar-btn danger" onClick={() => onDismiss(reminder.id)} disabled={busy} title="Dismiss" aria-label="Dismiss reminder">
        <X size={14} />
      </button>
    </div>
  );
}
