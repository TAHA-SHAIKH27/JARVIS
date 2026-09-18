import React, { useState, useEffect } from 'react'

const DISMISS_KEY = 'jarvis_audit_dismissed'

export default function StartupAuditBanner({ onOpenCode }) {
  const [phase, setPhase] = useState('loading') // loading | notify | fixing | done | none
  const [report, setReport] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    let cancelled = false
    let tries = 0
    async function load() {
      while (!cancelled && tries < 60) {
        tries += 1
        try {
          const res = await fetch('/api/code/audit/latest')
          if (res.ok) {
            const data = await res.json()
            if (cancelled) return
            if (data && data.issues_count > 0) {
              const stamp = String(data.timestamp || '')
              if (sessionStorage.getItem(DISMISS_KEY) === stamp) {
                setPhase('none')
                return
              }
              setReport(data)
              setPhase('notify')
              return
            }
            setPhase('none')
            return
          }
        } catch (err) {
          // backend not up yet - retry shortly
        }
        await new Promise(r => setTimeout(r, 1500))
      }
      if (!cancelled) setPhase('none')
    }
    load()
    return () => { cancelled = true }
  }, [])

  async function handleFix() {
    setPhase('fixing')
    setResult(null)
    try {
      const res = await fetch('/api/code/audit/fix', { method: 'POST' })
      const data = await res.json()
      setResult(data)
      setPhase('done')
    } catch (err) {
      setResult({ status: 'error', message: 'Could not reach the backend to apply fixes.' })
      setPhase('done')
    }
  }

  function dismiss(remember) {
    if (remember && report) {
      try { sessionStorage.setItem(DISMISS_KEY, String(report.timestamp || new Date().toISOString())) } catch (e) { /* ignore */ }
    }
    setPhase('none')
  }

  if (phase === 'loading' || phase === 'none') return null

  if (phase === 'fixing') {
    return (
      <div className="startup-banner is-fixing">
        <span className="banner-spinner" />
        <span>APPLYING CODE FIXES - Nemotron is repairing each reported file with automatic backup and rollback. This can take a few minutes per file...</span>
      </div>
    )
  }

  if (phase === 'done') {
    const ok = result?.fixed_count || 0
    const bad = result?.failed_count || 0
    const downloads = (result?.results || []).filter(r => r.status === 'success' && r.download_url)
    return (
      <div className={`startup-banner is-done ${result?.status === 'error' ? 'is-error' : ''}`}>
        <div className="banner-head">
          <strong>AUTOFIX COMPLETE</strong>
          <span className="banner-summary">{ok} fixed / {bad} failed</span>
        </div>
        {result?.status === 'error' && result?.message && (
          <div className="banner-msg">{result.message}</div>
        )}
        {downloads.length > 0 && (
          <div className="banner-downloads">
            <span className="banner-downloads-label">Download fixed files:</span>
            {downloads.map(r => (
              <a key={r.file} className="banner-download" href={r.download_url} download title={`Download corrected ${r.file}`}>
                DOWNLOAD {r.file}
              </a>
            ))}
          </div>
        )}
        <div className="banner-actions">
          <button className="banner-btn" onClick={() => window.location.reload()}>REFRESH + RE-AUDIT</button>
          <button className="banner-btn" onClick={() => dismiss(false)}>DISMISS</button>
        </div>
      </div>
    )
  }

  const items = (report?.issues || []).slice(0, 6)
  const extra = Math.max(0, (report?.issues_count || 0) - items.length)
  return (
    <div className="startup-banner is-warn">
      <div className="banner-head">
        <strong>STARTUP CODE CHECK</strong>
        <span className="banner-summary">Health {report?.health_score ?? '--'}% / {report?.issues_count ?? 0} issue(s) detected - read-only scan, nothing changed</span>
      </div>
      <div className="banner-issues">
        {items.map((iss, i) => {
          const range = Array.isArray(iss.line_range) ? iss.line_range : [iss.line, iss.line]
          const a = Number(range?.[0]) || 0
          const b = Number(range?.[1]) || a
          return (
            <div key={i} className="banner-issue">
              <span className={`sev ${String(iss.severity || 'warning')}`}>{String(iss.severity || 'warning').toUpperCase()}</span>
              <code className="banner-file">{iss.file}</code>
              <span className="banner-lines">{a}{b && b !== a ? `-${b}` : ''}</span>
              <span className="banner-msg">{iss.message}</span>
            </div>
          )
        })}
        {extra > 0 && <div className="banner-issue is-more">...and {extra} more issue(s).</div>}
      </div>
      <div className="banner-actions">
        <button className="banner-btn is-primary" onClick={handleFix}>FIX ALL AUTOMATICALLY</button>
        {onOpenCode && <button className="banner-btn" onClick={onOpenCode}>OPEN CODE CORE</button>}
        <button className="banner-btn" onClick={() => dismiss(true)}>SKIP</button>
      </div>
    </div>
  )
}