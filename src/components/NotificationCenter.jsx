import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, CalendarClock, Check, CheckCheck, Clock, Mail, MessageSquare, Search, Trash2, X } from 'lucide-react';

// Large overlay panel: views over reminders, scheduled messages and
// standalone notifications. Opening it never deletes anything; every state
// change goes through the backend first and the UI mirrors the confirmation.
const TABS = [
  { id: 'all', label: 'All' },
  { id: 'unread', label: 'Unread' },
  { id: 'reminders', label: 'Reminders' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'notifications', label: 'Notifications' },
];

const UPCOMING_STATUSES = new Set(['scheduled', 'snoozed', 'pending']);

function kindIcon(kind) {
  if (kind === 'reminder') return <Bell size={15} />;
  if (kind === 'scheduled') return <CalendarClock size={15} />;
  if (kind === 'gmail') return <Mail size={15} />;
  if (kind === 'whatsapp') return <MessageSquare size={15} />;
  return <Bell size={15} />;
}

function fmtTs(ts) {
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return '';
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const time = d.toLocaleString([], { hour: 'numeric', minute: '2-digit' });
    if (sameDay) return `Today, ${time}`;
    if (d.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  } catch { return ''; }
}

function CenterItem({ item, busy, onRead, onUnread, onDelete, onSnooze, onReschedule }) {
  const [showResched, setShowResched] = useState(false);
  const [reschedValue, setReschedValue] = useState('');
  const isReminder = item.kind === 'reminder';
  const isScheduled = item.kind === 'scheduled';
  const isPendingScheduled = isScheduled && item.status === 'pending';
  const prio = item.priority === 'urgent' ? 'prio-urgent' : item.priority === 'important' ? 'prio-important' : '';

  function tomorrow9am() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    return d.toISOString();
  }

  return (
    <div className={`notif-item ${item.read ? '' : 'is-unread'} ${prio}`}>
      <span className="notif-item-icon">{kindIcon(item.kind)}</span>
      <div className="notif-item-main">
        <div className="notif-item-title">{item.title || (isReminder ? 'Reminder' : isScheduled ? 'Scheduled message' : 'Notification')}</div>
        {item.body && <div className="notif-item-body">{item.body}</div>}
        <div className="notif-item-meta">
          <span className="notif-item-kind">{item.kind}</span>
          {item.status && <span>{item.status}</span>}
          {item.priority && item.priority !== 'normal' && <span>{item.priority}</span>}
          {item.ts && <span>{fmtTs(item.ts)}</span>}
          {!item.read && <span>unread</span>}
        </div>
        <div className="notif-item-buttons">
          {item.read
            ? <button className="notif-mini-btn" onClick={() => onUnread(item.id)} disabled={busy || isPendingScheduled} title={isPendingScheduled ? 'Scheduled messages have no unread state' : 'Mark as unread'}>Mark unread</button>
            : <button className="notif-mini-btn" onClick={() => onRead(item.id)} disabled={busy} title="Mark as read"><Check size={11} style={{ verticalAlign: -1 }} /> Read</button>}
          {isReminder && (
            <>
              <button className="notif-mini-btn warn" onClick={() => onSnooze(item.id, { minutes: 10 })} disabled={busy} title="Snooze 10 minutes">10m</button>
              <button className="notif-mini-btn warn" onClick={() => onSnooze(item.id, { minutes: 30 })} disabled={busy} title="Snooze 30 minutes">30m</button>
              <button className="notif-mini-btn warn" onClick={() => onSnooze(item.id, { minutes: 60 })} disabled={busy} title="Snooze 1 hour">1h</button>
              <button className="notif-mini-btn warn" onClick={() => onSnooze(item.id, { when: tomorrow9am() })} disabled={busy} title="Snooze until tomorrow 9 AM">Tomorrow</button>
            </>
          )}
          {isPendingScheduled && (
            showResched ? (
              <>
                <input
                  type="datetime-local"
                  className="notif-mini-btn"
                  value={reschedValue}
                  onChange={e => setReschedValue(e.target.value)}
                  aria-label="New send time"
                />
                <button
                  className="notif-mini-btn"
                  disabled={busy || !reschedValue}
                  onClick={() => {
                    const iso = new Date(reschedValue).toISOString();
                    setShowResched(false);
                    setReschedValue('');
                    onReschedule(item.id, iso);
                  }}
                >
                  Apply
                </button>
                <button className="notif-mini-btn danger" onClick={() => setShowResched(false)}>Cancel</button>
              </>
            ) : (
              <button className="notif-mini-btn warn" onClick={() => setShowResched(true)} disabled={busy} title="Move to a new time"><Clock size={11} style={{ verticalAlign: -1 }} /> Reschedule</button>
            )
          )}
          <button
            className="notif-mini-btn danger"
            onClick={() => {
              const label = isPendingScheduled ? 'Cancel this scheduled message' : `Delete this ${item.kind}`;
              if (window.confirm(`${label}?${isPendingScheduled ? ' It will be kept as cancelled history.' : ''}`)) onDelete(item.id, isPendingScheduled);
            }}
            disabled={busy}
            title={isPendingScheduled ? 'Cancel (kept as history)' : 'Delete permanently'}
          >
            <Trash2 size={11} style={{ verticalAlign: -1 }} /> {isPendingScheduled ? 'Cancel' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function NotificationCenter({ data, loading, busy, onClose, onRead, onUnread, onDelete, onSnooze, onReschedule, onReadAll, onClearHistory, onRefresh }) {
  const [tab, setTab] = useState('all');
  const [query, setQuery] = useState('');
  const closeRef = useRef(null);

  useEffect(() => {
    closeRef.current?.focus();
    function onKey(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const allItems = useMemo(() => {
    if (!data) return [];
    const out = [];
    (data.notifications || []).forEach(n => out.push({ ...n }));
    (data.reminders?.active || []).forEach(r => out.push({ ...r }));
    (data.reminders?.upcoming || []).forEach(r => out.push({ ...r }));
    (data.reminders?.history || []).forEach(r => out.push({ ...r }));
    (data.scheduled || []).forEach(j => out.push({ ...j }));
    const seen = new Set();
    return out.filter(i => (seen.has(i.id) ? false : (seen.add(i.id), true)));
  }, [data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allItems.filter(i => {
      if (tab === 'unread' && i.read) return false;
      if (tab === 'reminders' && i.kind !== 'reminder') return false;
      if (tab === 'scheduled' && i.kind !== 'scheduled') return false;
      if (tab === 'notifications' && (i.kind === 'reminder' || i.kind === 'scheduled')) return false;
      if (q && !`${i.title || ''} ${i.body || ''}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allItems, tab, query]);

  const sections = useMemo(() => {
    const today = [];
    const upcoming = [];
    const history = [];
    const nowDate = new Date().toDateString();
    for (const i of filtered) {
      if (UPCOMING_STATUSES.has(i.status)) { upcoming.push(i); continue; }
      try {
        const d = new Date(i.ts);
        if (!isNaN(d.getTime()) && d.toDateString() === nowDate) { today.push(i); continue; }
      } catch { /* fall through to history */ }
      history.push(i);
    }
    const byTs = (a, b) => String(b.ts || '').localeCompare(String(a.ts || ''));
    today.sort(byTs); upcoming.sort((a, b) => String(a.ts || '').localeCompare(String(b.ts || ''))); history.sort(byTs);
    return { today, upcoming, history };
  }, [filtered]);

  const unread = data?.unread_count ?? 0;

  function renderSection(label, items) {
    if (!items.length) return null;
    return (
      <div key={label}>
        <div className="notif-section-label">{label} ({items.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {items.map(i => (
            <CenterItem key={i.id} item={i} busy={busy} onRead={onRead} onUnread={onUnread} onDelete={onDelete} onSnooze={onSnooze} onReschedule={onReschedule} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="notif-center-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Notification Center">
      <div className="notif-center-panel" onClick={e => e.stopPropagation()}>
        <div className="notif-center-head">
          <Bell size={16} style={{ color: 'var(--cyan)' }} />
          <span className="notif-center-title">NOTIFICATIONS</span>
          {unread > 0 && <span className="notif-center-unread">{unread} UNREAD</span>}
          <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close Notification Center" title="Close (Esc)">
            <X size={15} />
          </button>
        </div>

        <div className="notif-center-search">
          <Search size={14} style={{ alignSelf: 'center', color: 'var(--text-faint)', flexShrink: 0 }} />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search notifications…"
            aria-label="Search notifications"
          />
        </div>

        <div className="notif-center-tabs" role="tablist" aria-label="Notification categories">
          {TABS.map(t => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={`notif-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="notif-center-actions">
          <button className="notif-mini-btn" onClick={async () => { await onReadAll(); onRefresh(); }} disabled={busy} title="Mark everything as read">
            <CheckCheck size={11} style={{ verticalAlign: -1 }} /> Mark all read
          </button>
          <button
            className="notif-mini-btn danger"
            onClick={() => {
              if (window.confirm('Clear read notification history? Unread items, future reminders and scheduled messages are kept.')) {
                onClearHistory().then(() => onRefresh());
              }
            }}
            disabled={busy}
            title="Delete read notification history (keeps unread, future and scheduled)"
          >
            <Trash2 size={11} style={{ verticalAlign: -1 }} /> Clear read history
          </button>
          <button className="notif-mini-btn" onClick={onRefresh} disabled={busy || loading} title="Reload from backend">Refresh</button>
        </div>

        <div className="notif-center-list">
          {loading && <div className="notif-empty">Loading notifications, sir…</div>}
          {!loading && filtered.length === 0 && (
            <div className="notif-empty">
              <span className="notif-empty-icon"><Bell size={28} /></span>
              {query ? 'No notifications match your search, sir.' : tab === 'unread' ? 'All caught up, sir. Nothing unread.' : 'No notifications here yet, sir.'}
            </div>
          )}
          {!loading && renderSection('Today', sections.today)}
          {!loading && renderSection('Upcoming', sections.upcoming)}
          {!loading && renderSection('History', sections.history)}
        </div>
      </div>
    </div>
  );
}
