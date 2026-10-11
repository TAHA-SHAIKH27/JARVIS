import React, { useState, useEffect, useCallback } from 'react'

/**
 * BackupPanel — minimal Ubuntu-backup status UI for the Settings modal.
 * Uses the same field/oauth-row/btn-secondary conventions as the Gmail
 * watcher section. Only "completed" jobs passed SHA-256 verification;
 * a reachable server alone never marks files backed up.
 */
export default function BackupPanel({ visible, onOpenBackupCore }) {
  const [backup, setBackup] = useState(null)
  const [jobs, setJobs] = useState([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/backup/status')
      if (res.ok) {
        const data = await res.json()
        setBackup(data.backup || null)
      }
      const jr = await fetch('/api/backup/jobs?limit=10')
      if (jr.ok) {
        const jdata = await jr.json()
        setJobs(jdata.jobs || [])
      }
    } catch (e) { /* backend down — panel simply stays empty */ }
  }, [])

  useEffect(() => { if (visible) refresh() }, [visible, refresh])

  async function post(path, body) {
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) setMsg(data.detail || 'Action failed.')
      else setMsg('Done, sir.');
      await refresh()
    } catch (e) {
      setMsg('Could not reach the core service.')
    }
    setBusy(false)
    setTimeout(() => setMsg(''), 4000)
  }

  const counts = (backup && backup.counts) || {}
  const server = (backup && backup.server) || {}
  const lastOk = backup && backup.last_success
    ? new Date(backup.last_success * 1000).toLocaleString() : 'never'

  return (
    <div className="field">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label>Ubuntu Backups (local-first automatic backup)</label>
        {onOpenBackupCore && (
          <button
            type="button"
            className="btn-secondary"
            style={{ color: 'var(--cyan)', borderColor: 'var(--cyan)', fontSize: '11px', padding: '3px 8px' }}
            onClick={onOpenBackupCore}
          >
            Launch 3D Core ↗
          </button>
        )}
      </div>
      <div className="oauth-row">
        <div className="oauth-status">
          <span className={`oauth-dot ${server.reachable ? 'linked' : ''}`} />
          {backup === null
            ? 'Checking…'
            : (server.reachable ? `Server reachable (${server.host || backup.host})` : 'Server unreachable — jobs queue safely')}
        </div>
        <button className="btn-secondary" onClick={refresh} disabled={busy}>Refresh</button>
      </div>
      {backup && (
        <div className="oauth-status" style={{ marginTop: 6 }}>
          Pending {counts.pending || 0} · Retrying {counts.retrying || 0} · Failed {counts.failed || 0} · Completed {counts.completed || 0}
          {backup.paused ? ' · PAUSED' : ''} · Last verified backup: {lastOk}
        </div>
      )}
      {jobs.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 12, opacity: 0.85 }}>
          {jobs.slice(0, 5).map(j => (
            <div key={j.id}>
              {(j.rel || j.source || '').split('/').pop()} — {j.status}{j.last_error ? `: ${String(j.last_error).slice(0, 90)}` : ''}
            </div>
          ))}
        </div>
      )}
      <div className="oauth-row" style={{ marginTop: 8 }}>
        <button className="btn-secondary" onClick={() => post('/api/backup/scan')} disabled={busy}>Scan now</button>
        {backup && backup.paused
          ? <button className="btn-secondary" onClick={() => post('/api/backup/pause', { paused: false })} disabled={busy}>Resume</button>
          : <button className="btn-secondary" onClick={() => post('/api/backup/pause', { paused: true })} disabled={busy}>Pause</button>}
        <button className="btn-secondary" onClick={() => post('/api/backup/retry', { all_failed: true })} disabled={busy}>Retry failed</button>
        {onOpenBackupCore && (
          <button className="btn-secondary" onClick={onOpenBackupCore}>
            Open 3D Core
          </button>
        )}
      </div>
      {msg && <div className="save-note" style={{ color: 'var(--cyan)' }}>{msg}</div>}
      <p className="oauth-hint">Files save on this laptop first; verified SHA-256 copies go to the Ubuntu backup root. Local deletes never remove remote copies.</p>
    </div>
  )
}
