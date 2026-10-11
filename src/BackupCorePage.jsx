import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ShieldCheck, ShieldAlert, HardDrive, RefreshCw, Play, Pause,
  RotateCcw, Search, Filter, Server, Laptop, CheckCircle, AlertTriangle,
  ArrowLeft, ArrowUpRight, Folder, File, FileText, FileCode, Image as ImageIcon,
  Archive, Database, Download, Settings, Terminal, Activity, Zap, Check, X,
  Copy, ExternalLink, Clock, Wifi, Lock, AlertCircle, Grid, List, Sparkles
} from 'lucide-react';
import Backup3DCore from './components/Backup3DCore';
import './backup-core.css';

function formatBytes(n) {
  if (!n || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let val = Number(n);
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDate(ts) {
  if (!ts) return 'Never';
  const d = new Date(ts * 1000);
  return d.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function getFileIcon(category) {
  switch (category) {
    case 'document': return <FileText size={16} />;
    case 'code': return <FileCode size={16} />;
    case 'media': return <ImageIcon size={16} />;
    case 'archive': return <Archive size={16} />;
    case 'data': return <Database size={16} />;
    default: return <File size={16} />;
  }
}

export default function BackupCorePage({ setActiveView }) {
  // Navigation tabs
  const [activeTab, setActiveTab] = useState('overview'); // overview | explorer | queue | restore | settings

  // Live Backend Data
  const [backupStatus, setBackupStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  // Explorer filters
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [viewMode, setViewMode] = useState('list'); // list | grid
  const [sortField, setSortField] = useState('updated_at'); // name | size | updated_at | status
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);

  // Restore State
  const [restoreJob, setRestoreJob] = useState(null);
  const [restoreCustomDest, setRestoreCustomDest] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState(null);

  // Settings Form State
  const [settingsForm, setSettingsForm] = useState({});
  const [testingConn, setTestingConn] = useState(false);
  const [testConnResult, setTestConnResult] = useState(null);

  // Node inspection modal (from 3D scene click)
  const [inspectedNode, setInspectedNode] = useState(null);

  // Toast helper
  const showToast = useCallback((message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4500);
  }, []);

  // Fetch status and jobs from real FastAPI backend
  const fetchAll = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [statusRes, jobsRes, configRes] = await Promise.all([
        fetch('/api/backup/status'),
        fetch('/api/backup/jobs?limit=500'),
        fetch('/api/backup/config'),
      ]);

      if (statusRes.ok) {
        const sData = await statusRes.json();
        setBackupStatus(sData.backup || null);
      }
      if (jobsRes.ok) {
        const jData = await jobsRes.json();
        setJobs(jData.jobs || []);
      }
      if (configRes.ok) {
        const cData = await configRes.json();
        setConfig(cData.config || null);
        setSettingsForm((prev) => (Object.keys(prev).length > 0 ? prev : (cData.config || {})));
      }
    } catch (err) {
      console.error('Failed to query backup API:', err);
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchAll();
  }, []);

  // Live periodic refresh (every 4 seconds) to track real-time queue & transfers
  useEffect(() => {
    const timer = setInterval(() => {
      fetchAll(true);
    }, 4000);
    return () => clearInterval(timer);
  }, [fetchAll]);

  // Trigger Backend Action
  const performAction = async (endpoint, body = {}) => {
    setBusy(true);
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.detail || data.message || 'Action failed, sir.', 'error');
      } else {
        showToast('Command executed successfully.', 'success');
        await fetchAll(true);
      }
    } catch (err) {
      showToast('Network error contacting backup daemon.', 'error');
    } finally {
      setBusy(false);
    }
  };

  // Test Connection Action
  const handleTestConnection = async () => {
    setTestingConn(true);
    setTestConnResult(null);
    try {
      const res = await fetch('/api/backup/test', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setTestConnResult(data);
        if (data.reachable) {
          showToast(`Server reachable! Ping latency: ${data.latency_ms}ms`, 'success');
        } else {
          showToast(`Server unreachable: ${data.message || 'Check IP or SSH daemon'}`, 'error');
        }
      } else {
        showToast(data.detail || 'Connection probe failed.', 'error');
      }
      await fetchAll(true);
    } catch (err) {
      showToast('Failed to run test connection probe.', 'error');
    } finally {
      setTestingConn(false);
    }
  };

  // Save Settings Action
  const handleSaveSettings = async (e) => {
    if (e) e.preventDefault();
    if (!settingsForm) return;
    setBusy(true);
    try {
      const res = await fetch('/api/backup/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settingsForm),
      });
      const data = await res.json();
      if (res.ok) {
        setConfig(data.config);
        showToast('Backup configuration saved and persisted, sir.', 'success');
      } else {
        showToast(data.detail || 'Failed to save configuration.', 'error');
      }
    } catch (err) {
      showToast('Error saving settings.', 'error');
    } finally {
      setBusy(false);
    }
  };

  // Restore Action
  const handleRestoreFile = async () => {
    if (!restoreJob) return;
    setRestoring(true);
    setRestoreResult(null);
    try {
      const res = await fetch('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: restoreJob.id,
          dest_dir: restoreCustomDest.trim(),
        }),
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setRestoreResult({
          success: true,
          path: data.path,
          host: data.host,
        });
        showToast(`File successfully restored and SHA-256 verified!`, 'success');
      } else {
        setRestoreResult({
          success: false,
          error: data.message || data.detail || 'Restore failed.',
        });
        showToast(`Restore failed: ${data.message || 'Checksum error or network timeout'}`, 'error');
      }
    } catch (err) {
      setRestoreResult({
        success: false,
        error: 'Network connection failed during restore transfer.',
      });
      showToast('Failed to complete restore request.', 'error');
    } finally {
      setRestoring(false);
    }
  };

  // Copy helper
  const copyToClipboard = (text, label) => {
    navigator.clipboard.writeText(text);
    showToast(`Copied ${label} to clipboard.`, 'info');
  };

  // Filtered & Sorted Jobs for Explorer
  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      // Category filter
      if (categoryFilter !== 'all' && j.category !== categoryFilter) return false;
      // Status filter
      if (statusFilter !== 'all' && j.status !== statusFilter) return false;
      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = (j.rel || '').toLowerCase().includes(q);
        const matchesSource = (j.source || '').toLowerCase().includes(q);
        if (!matchesName && !matchesSource) return false;
      }
      return true;
    }).sort((a, b) => {
      let vA, vB;
      if (sortField === 'name') {
        vA = (a.rel || a.source || '').toLowerCase();
        vB = (b.rel || b.source || '').toLowerCase();
      } else if (sortField === 'size') {
        vA = a.size || 0;
        vB = b.size || 0;
      } else if (sortField === 'status') {
        vA = a.status || '';
        vB = b.status || '';
      } else {
        vA = a.updated_at || a.mtime || 0;
        vB = b.updated_at || b.mtime || 0;
      }
      if (vA < vB) return sortAsc ? -1 : 1;
      if (vA > vB) return sortAsc ? 1 : -1;
      return 0;
    });
  }, [jobs, categoryFilter, statusFilter, searchQuery, sortField, sortAsc]);

  // Derived counts
  const counts = backupStatus?.counts || {};
  const server = backupStatus?.server || {};
  const localSys = backupStatus?.local_system || {};
  const isServerReachable = server?.reachable ?? false;
  const isPaused = backupStatus?.paused ?? false;

  return (
    <div className="backup-container">
      {/* ── Top Header ── */}
      <header className="backup-header">
        <div className="backup-header-left">
          <button
            className="backup-btn secondary"
            onClick={() => setActiveView('core')}
            title="Return to Core HUD"
          >
            <ArrowLeft size={14} />
            <span>CORE HUD</span>
          </button>

          <div className="backup-title-wrap">
            <h1 className="backup-title">
              <HardDrive size={18} className="codecore-icon" />
              <span>JARVIS BACKUP CORE // 3D DATA MATRIX</span>
            </h1>
            <span className="backup-subtitle">
              LOCAL-FIRST AIR-GAPPED BACKUP ENGINE · UBUNTU {backupStatus?.host || '192.168.1.110'}
            </span>
          </div>
        </div>

        <div className="backup-header-right">
          <div className={`node-status-pill ${isServerReachable ? 'online' : 'offline'}`}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: isServerReachable ? '#72f0b0' : '#ff6275',
              boxShadow: `0 0 8px ${isServerReachable ? '#72f0b0' : '#ff6275'}`
            }} />
            <span>{isServerReachable ? `UBUNTU CONNECTED (${server.host || backupStatus?.host})` : 'UBUNTU UNREACHABLE'}</span>
          </div>

          <button
            className="backup-btn"
            onClick={() => fetchAll(false)}
            disabled={loading || busy}
            title="Refresh Core Telemetry"
          >
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
            <span>REFRESH</span>
          </button>

          <button
            className="backup-btn primary"
            onClick={() => performAction('/api/backup/scan')}
            disabled={busy}
            title="Trigger Immediate Reconciliation Scan"
          >
            <Zap size={13} />
            <span>SCAN NOW</span>
          </button>
        </div>
      </header>

      {/* ── Toast Alert Banner ── */}
      {toast && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '24px',
          zIndex: 9999,
          background: toast.type === 'error' ? 'rgba(255, 98, 117, 0.95)' : toast.type === 'success' ? 'rgba(114, 240, 176, 0.95)' : 'rgba(67, 217, 255, 0.95)',
          color: '#05080d',
          padding: '10px 18px',
          borderRadius: '8px',
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: '12px',
          fontWeight: '600',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.5)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}>
          {toast.type === 'error' ? <AlertCircle size={15} /> : <Check size={15} />}
          <span>{toast.message}</span>
        </div>
      )}

      {/* ── Navigation Tabs Rail ── */}
      <nav className="backup-tabs-rail" aria-label="Backup Core Sections">
        <button
          className={`backup-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <Activity size={14} />
          <span>3D CORE OVERVIEW</span>
        </button>

        <button
          className={`backup-tab-btn ${activeTab === 'explorer' ? 'active' : ''}`}
          onClick={() => setActiveTab('explorer')}
        >
          <Folder size={14} />
          <span>FILE EXPLORER</span>
          <span className="backup-tab-badge">{jobs.length}</span>
        </button>

        <button
          className={`backup-tab-btn ${activeTab === 'queue' ? 'active' : ''}`}
          onClick={() => setActiveTab('queue')}
        >
          <Terminal size={14} />
          <span>LIVE BACKUP QUEUE</span>
          {counts.uploading > 0 && <span className="backup-tab-badge" style={{ background: '#72f0b0', color: '#000' }}>ACTIVE</span>}
          {(counts.pending > 0 || counts.retrying > 0) && <span className="backup-tab-badge">{counts.pending + (counts.retrying || 0)}</span>}
        </button>

        <button
          className={`backup-tab-btn ${activeTab === 'restore' ? 'active' : ''}`}
          onClick={() => setActiveTab('restore')}
        >
          <Download size={14} />
          <span>RESTORE CENTER</span>
          <span className="backup-tab-badge">{counts.completed || 0}</span>
        </button>

        <button
          className={`backup-tab-btn ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveTab('settings')}
        >
          <Settings size={14} />
          <span>BACKUP SETTINGS</span>
        </button>
      </nav>

      {/* ── TAB 1: 3D CORE OVERVIEW ── */}
      {activeTab === 'overview' && (
        <div className="backup-tab-content">
          {/* Active in-flight transfer banner if present */}
          {backupStatus?.active_transfer && (
            <div className="active-transfer-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                <div style={{
                  width: 38, height: 38, borderRadius: '50%',
                  background: 'rgba(114, 240, 176, 0.2)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#72f0b0',
                }}>
                  <Zap size={20} className="spin" />
                </div>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: '600', color: '#72f0b0', letterSpacing: '0.06em' }}>
                    IN-FLIGHT SCP STREAM // TRANSFER IN PROGRESS
                  </div>
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-dim)' }}>
                    {backupStatus.active_transfer.rel} ({formatBytes(backupStatus.active_transfer.size)})
                  </div>
                </div>
              </div>
              <div style={{ minWidth: '180px' }}>
                <div className="progress-bar-wrap">
                  <div className="progress-bar-fill" style={{ width: '75%' }} />
                </div>
                <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono, monospace)', color: '#72f0b0', marginTop: '4px', textAlign: 'right' }}>
                  STREAMING TO UBUNTU...
                </div>
              </div>
            </div>
          )}

          {/* 3D WebGL Holographic Core Viewport */}
          <div className="backup-3d-viewport-card">
            <span className="viewport-corner-tag tl">JARVIS 3D BACKUP MATRIX // R3F PIPELINE</span>
            <span className="viewport-corner-tag tr">HARDWARE-ACCELERATED OPENGL CORE</span>
            <span className="viewport-corner-tag bl">AES-256 GCM ENCRYPTION · SHA-256 VERIFICATION</span>
            <span className="viewport-corner-tag br">NODE LINK: {backupStatus?.host || '192.168.1.110'}</span>

            <Backup3DCore
              backupStatus={backupStatus}
              activeTransfer={backupStatus?.active_transfer}
              onSelectNode={(nodeName) => setInspectedNode(nodeName)}
            />
          </div>

          {/* Telemetry Metric Cards Grid */}
          <div className="backup-metrics-grid">
            <div className="backup-metric-card">
              <div className="metric-header">
                <span>FILES INDEXED</span>
                <Folder size={14} color="var(--cyan)" />
              </div>
              <div className="metric-value">
                <span>{backupStatus?.total_jobs || 0}</span>
                <span className="metric-sub">tracked</span>
              </div>
              <div className="metric-sub">
                Total size: {formatBytes(backupStatus?.total_bytes)}
              </div>
            </div>

            <div className="backup-metric-card">
              <div className="metric-header">
                <span>VERIFIED BACKUPS</span>
                <ShieldCheck size={14} color="var(--green)" />
              </div>
              <div className="metric-value" style={{ color: 'var(--green)' }}>
                <span>{counts.completed || 0}</span>
                <span className="metric-sub">verified</span>
              </div>
              <div className="metric-sub">
                Passed SHA-256: {formatBytes(backupStatus?.verified_bytes)}
              </div>
            </div>

            <div className="backup-metric-card">
              <div className="metric-header">
                <span>QUEUE STATUS</span>
                <Activity size={14} color="var(--amber)" />
              </div>
              <div className="metric-value" style={{ color: (counts.pending || 0) > 0 ? 'var(--amber)' : 'var(--text)' }}>
                <span>{(counts.pending || 0) + (counts.retrying || 0)}</span>
                <span className="metric-sub">pending</span>
              </div>
              <div className="metric-sub">
                {counts.uploading || 0} transferring · {isPaused ? 'PAUSED' : 'AUTO-PROCESSING'}
              </div>
            </div>

            <div className="backup-metric-card">
              <div className="metric-header">
                <span>FAILED / RETRIES</span>
                <ShieldAlert size={14} color="var(--red)" />
              </div>
              <div className="metric-value" style={{ color: (counts.failed || 0) > 0 ? 'var(--red)' : 'var(--text)' }}>
                <span>{counts.failed || 0}</span>
                <span className="metric-sub">failed</span>
              </div>
              <div className="metric-sub">
                Retrying: {counts.retrying || 0} jobs
              </div>
            </div>
          </div>

          {/* Node Diagnostics Row */}
          <div className="backup-nodes-row">
            {/* Windows Laptop Node Card */}
            <div className="node-hud-card">
              <div className="node-hud-header">
                <div className="node-hud-title">
                  <Laptop size={16} />
                  <span>LOCAL WINDOWS CLIENT (PRIMARY NODE)</span>
                </div>
                <div className="node-status-pill online">
                  <span>SYSTEM ONLINE</span>
                </div>
              </div>

              <div className="node-spec-list">
                <div className="node-spec-item">
                  <span className="node-spec-label">PLATFORM / OS</span>
                  <span className="node-spec-value">{localSys.platform || 'Windows 11'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">HOSTNAME</span>
                  <span className="node-spec-value">{localSys.hostname || 'JARVIS-LAPTOP'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">LOCAL DRIVE STORAGE</span>
                  <span className="node-spec-value">
                    {localSys.disk_total > 0
                      ? `${formatBytes(localSys.disk_free)} free / ${formatBytes(localSys.disk_total)}`
                      : 'Telemetry connecting...'}
                  </span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">LAST RECONCILIATION SCAN</span>
                  <span className="node-spec-value">{formatDate(backupStatus?.last_scan)}</span>
                </div>
              </div>

              {localSys.disk_total > 0 && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontFamily: 'var(--font-mono, monospace)', marginBottom: '4px', color: 'var(--text-dim)' }}>
                    <span>C: DRIVE UTILIZATION</span>
                    <span>{Math.round(((localSys.disk_used || 0) / localSys.disk_total) * 100)}%</span>
                  </div>
                  <div className="progress-bar-wrap">
                    <div
                      className="progress-bar-fill"
                      style={{ width: `${Math.round(((localSys.disk_used || 0) / localSys.disk_total) * 100)}%` }}
                    />
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
                <button className="backup-btn" onClick={() => performAction('/api/backup/scan')} disabled={busy}>
                  <Zap size={12} />
                  <span>SCAN MONITORED ROOTS</span>
                </button>
                <button className="backup-btn secondary" onClick={() => setActiveTab('explorer')}>
                  <Folder size={12} />
                  <span>BROWSE LOCAL FILES</span>
                </button>
              </div>
            </div>

            {/* Ubuntu Server Node Card */}
            <div className="node-hud-card">
              <div className="node-hud-header">
                <div className="node-hud-title">
                  <Server size={16} />
                  <span>REMOTE UBUNTU SERVER (BACKUP REPOSITORY)</span>
                </div>
                <div className={`node-status-pill ${isServerReachable ? 'online' : 'offline'}`}>
                  <span>{isServerReachable ? 'SSH REACHABLE' : 'UNREACHABLE'}</span>
                </div>
              </div>

              <div className="node-spec-list">
                <div className="node-spec-item">
                  <span className="node-spec-label">IPV4 ADDRESS</span>
                  <span className="node-spec-value">{backupStatus?.host || '192.168.1.110'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">SSH USER</span>
                  <span className="node-spec-value">{backupStatus?.user || 'taha'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">REMOTE TARGET DIRECTORY</span>
                  <span className="node-spec-value">{backupStatus?.remote_root || '/home/taha/JARVIS-Backups/'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">LAST VERIFIED BACKUP</span>
                  <span className="node-spec-value">{formatDate(backupStatus?.last_success)}</span>
                </div>
              </div>

              <div style={{
                background: 'rgba(5, 12, 20, 0.6)',
                border: '1px solid rgba(67, 217, 255, 0.1)',
                borderRadius: '6px',
                padding: '8px 12px',
                fontSize: '11px',
                fontFamily: 'var(--font-mono, monospace)',
                color: isServerReachable ? '#72f0b0' : 'var(--text-dim)',
              }}>
                {isServerReachable
                  ? `Probe successful: ${server.message || 'OpenSSH connection alive and responding.'}`
                  : `Offline safeguard: Local changes queue safely without blocking JARVIS tasks.`}
              </div>

              <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
                <button
                  className="backup-btn"
                  onClick={handleTestConnection}
                  disabled={testingConn}
                >
                  <Wifi size={12} className={testingConn ? 'spin' : ''} />
                  <span>TEST CONNECTION</span>
                </button>
                <button
                  className="backup-btn secondary"
                  onClick={() => performAction('/api/backup/retry', { all_failed: true })}
                  disabled={busy || counts.failed === 0}
                >
                  <RotateCcw size={12} />
                  <span>RETRY FAILED ({counts.failed || 0})</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 2: FILE EXPLORER ── */}
      {activeTab === 'explorer' && (
        <div className="backup-tab-content">
          {/* Explorer Toolbar */}
          <div className="explorer-toolbar">
            <div className="explorer-search-wrap">
              <Search size={14} color="var(--cyan)" />
              <input
                type="text"
                className="explorer-search-input"
                placeholder="Search indexed files, documents, artifacts..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button className="icon-btn" onClick={() => setSearchQuery('')} style={{ background: 'none', border: 'none', color: 'var(--text-dim)' }}>
                  <X size={13} />
                </button>
              )}
            </div>

            {/* Category Filter Pills */}
            <div className="category-filter-pills">
              {[
                { id: 'all', label: 'All Files' },
                { id: 'document', label: 'Documents' },
                { id: 'code', label: 'Code' },
                { id: 'media', label: 'Media' },
                { id: 'archive', label: 'Archives' },
                { id: 'data', label: 'Data' },
              ].map((cat) => (
                <button
                  key={cat.id}
                  className={`category-pill ${categoryFilter === cat.id ? 'active' : ''}`}
                  onClick={() => setCategoryFilter(cat.id)}
                >
                  {cat.label}
                </button>
              ))}
            </div>

            {/* Status Filter & View Toggle */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <select
                className="settings-input"
                style={{ padding: '6px 10px', fontSize: '11px', height: '34px' }}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="completed">Verified Only</option>
                <option value="pending">Pending</option>
                <option value="uploading">Uploading</option>
                <option value="retrying">Retrying</option>
                <option value="failed">Failed</option>
              </select>

              <div style={{ display: 'flex', background: 'rgba(10, 18, 27, 0.8)', border: '1px solid rgba(67, 217, 255, 0.2)', borderRadius: '6px', padding: '2px' }}>
                <button
                  className="icon-btn"
                  style={{ padding: '6px', background: viewMode === 'list' ? 'var(--cyan)' : 'transparent', color: viewMode === 'list' ? '#000' : 'var(--text-dim)', border: 'none', borderRadius: '4px' }}
                  onClick={() => setViewMode('list')}
                  title="List View"
                >
                  <List size={14} />
                </button>
                <button
                  className="icon-btn"
                  style={{ padding: '6px', background: viewMode === 'grid' ? 'var(--cyan)' : 'transparent', color: viewMode === 'grid' ? '#000' : 'var(--text-dim)', border: 'none', borderRadius: '4px' }}
                  onClick={() => setViewMode('grid')}
                  title="Grid View"
                >
                  <Grid size={14} />
                </button>
              </div>
            </div>
          </div>

          {/* Table / Grid Render */}
          {filteredJobs.length === 0 ? (
            <div style={{
              padding: '60px 20px',
              textAlign: 'center',
              background: 'rgba(10, 18, 27, 0.6)',
              border: '1px dashed rgba(67, 217, 255, 0.2)',
              borderRadius: '10px',
              color: 'var(--text-dim)',
            }}>
              <Folder size={36} color="rgba(67, 217, 255, 0.4)" style={{ marginBottom: '12px' }} />
              <div style={{ fontFamily: 'var(--font-display)', fontSize: '15px', color: 'var(--cyan)', marginBottom: '6px' }}>
                No backup files found matching filter criteria
              </div>
              <p style={{ fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                Try clearing search terms or triggering a reconciliation scan now.
              </p>
              <button
                className="backup-btn"
                style={{ marginTop: '14px' }}
                onClick={() => performAction('/api/backup/scan')}
              >
                <Zap size={13} />
                <span>SCAN MONITORED ROOTS</span>
              </button>
            </div>
          ) : viewMode === 'list' ? (
            <div className="backup-table-wrap">
              <table className="backup-table">
                <thead>
                  <tr>
                    <th style={{ width: '40px' }}>TYPE</th>
                    <th>FILE NAME & RELATIVE PATH</th>
                    <th>SIZE</th>
                    <th>STATUS</th>
                    <th>MODIFIED / QUEUED</th>
                    <th>SHA-256 CHECKSUM</th>
                    <th style={{ textAlign: 'right' }}>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map((j) => (
                    <tr key={j.id} onClick={() => setSelectedFile(j)} style={{ cursor: 'pointer' }}>
                      <td>{getFileIcon(j.category)}</td>
                      <td>
                        <div style={{ fontWeight: '600', color: '#fff' }}>
                          {(j.rel || j.source || '').split('/').pop()}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                          {j.rel || j.source}
                        </div>
                      </td>
                      <td>{formatBytes(j.size)}</td>
                      <td>
                        <span className={`status-tag ${j.status}`}>
                          {j.status === 'completed' && 'VERIFIED'}
                          {j.status === 'uploading' && 'STREAMING'}
                          {j.status === 'pending' && 'QUEUED'}
                          {j.status === 'retrying' && `RETRYING (${j.retries})`}
                          {j.status === 'failed' && 'FAILED'}
                        </span>
                      </td>
                      <td>{formatDate(j.updated_at || j.mtime)}</td>
                      <td>
                        {j.sha256 ? (
                          <span className="hash-chip" title={j.sha256}>
                            <Lock size={10} />
                            {j.sha256.slice(0, 10)}…
                          </span>
                        ) : (
                          <span style={{ fontSize: '10px', color: 'var(--text-faint)' }}>Pending transfer</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {j.status === 'completed' ? (
                          <button
                            className="backup-btn success"
                            style={{ padding: '4px 8px', fontSize: '10px' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setRestoreJob(j);
                              setActiveTab('restore');
                            }}
                          >
                            <Download size={11} />
                            <span>RESTORE</span>
                          </button>
                        ) : j.status === 'failed' ? (
                          <button
                            className="backup-btn"
                            style={{ padding: '4px 8px', fontSize: '10px' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              performAction('/api/backup/retry', { job_id: j.id });
                            }}
                          >
                            <RotateCcw size={11} />
                            <span>RETRY</span>
                          </button>
                        ) : (
                          <span style={{ fontSize: '11px', color: 'var(--text-faint)' }}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="explorer-grid">
              {filteredJobs.map((j) => (
                <div key={j.id} className="file-card" onClick={() => setSelectedFile(j)}>
                  <div className="file-card-top">
                    <div className="file-icon-box">
                      {getFileIcon(j.category)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="file-card-name">
                        {(j.rel || j.source || '').split('/').pop()}
                      </div>
                      <div className="file-card-path">
                        {j.rel || j.source}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                      {formatBytes(j.size)}
                    </span>
                    <span className={`status-tag ${j.status}`}>
                      {j.status === 'completed' ? 'VERIFIED' : j.status.toUpperCase()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 3: LIVE BACKUP QUEUE ── */}
      {activeTab === 'queue' && (
        <div className="backup-tab-content">
          {/* Queue Top Actions */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: '14px', color: 'var(--cyan)' }}>
                DAEMON WORKER STATUS: {isPaused ? <span style={{ color: 'var(--amber)' }}>PAUSED</span> : <span style={{ color: 'var(--green)' }}>RUNNING</span>}
              </div>
              <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                · Single-flight OpenSSH queue
              </span>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              {isPaused ? (
                <button
                  className="backup-btn success"
                  onClick={() => performAction('/api/backup/pause', { paused: false })}
                  disabled={busy}
                >
                  <Play size={13} />
                  <span>RESUME DAEMON</span>
                </button>
              ) : (
                <button
                  className="backup-btn danger"
                  onClick={() => performAction('/api/backup/pause', { paused: true })}
                  disabled={busy}
                >
                  <Pause size={13} />
                  <span>PAUSE DAEMON</span>
                </button>
              )}

              <button
                className="backup-btn"
                onClick={() => performAction('/api/backup/retry', { all_failed: true })}
                disabled={busy || counts.failed === 0}
              >
                <RotateCcw size={13} />
                <span>RETRY ALL FAILED ({counts.failed || 0})</span>
              </button>

              <button
                className="backup-btn primary"
                onClick={() => performAction('/api/backup/scan')}
                disabled={busy}
              >
                <Zap size={13} />
                <span>SCAN NOW</span>
              </button>
            </div>
          </div>

          {/* Queue Job Table */}
          <div className="backup-table-wrap">
            <table className="backup-table">
              <thead>
                <tr>
                  <th>JOB ID</th>
                  <th>FILE PATH</th>
                  <th>SIZE</th>
                  <th>STATUS</th>
                  <th>RETRIES</th>
                  <th>LAST ERROR / DIAGNOSTIC</th>
                  <th style={{ textAlign: 'right' }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {jobs.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-dim)' }}>
                      No queued jobs at this time. All tracked files are verified on Ubuntu.
                    </td>
                  </tr>
                ) : (
                  jobs.map((j) => (
                    <tr key={j.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-faint)' }}>
                        {j.id.slice(0, 8)}
                      </td>
                      <td>
                        <div style={{ fontWeight: '600' }}>{j.rel || j.source}</div>
                      </td>
                      <td>{formatBytes(j.size)}</td>
                      <td>
                        <span className={`status-tag ${j.status}`}>
                          {j.status === 'completed' && 'VERIFIED'}
                          {j.status === 'uploading' && 'STREAMING NOW'}
                          {j.status === 'pending' && 'PENDING'}
                          {j.status === 'retrying' && 'RETRYING'}
                          {j.status === 'failed' && 'FAILED'}
                        </span>
                      </td>
                      <td>{j.retries || 0} / 20</td>
                      <td style={{ color: j.last_error ? 'var(--red)' : 'var(--text-dim)', fontSize: '11px', maxWidth: '300px', wordBreak: 'break-word' }}>
                        {j.last_error || 'None — normal operation'}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {j.status === 'failed' && (
                          <button
                            className="backup-btn"
                            style={{ padding: '3px 8px', fontSize: '10px' }}
                            onClick={() => performAction('/api/backup/retry', { job_id: j.id })}
                            disabled={busy}
                          >
                            <RotateCcw size={10} />
                            <span>RETRY</span>
                          </button>
                        )}
                        {j.status === 'completed' && (
                          <button
                            className="backup-btn secondary"
                            style={{ padding: '3px 8px', fontSize: '10px' }}
                            onClick={() => {
                              setRestoreJob(j);
                              setActiveTab('restore');
                            }}
                          >
                            <Download size={10} />
                            <span>RESTORE</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── TAB 4: RESTORE CENTER ── */}
      {activeTab === 'restore' && (
        <div className="backup-tab-content">
          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '22px' }}>
            {/* Left: Available Verified Backups list */}
            <div className="node-hud-card">
              <div className="node-hud-header">
                <div className="node-hud-title">
                  <Download size={16} />
                  <span>SELECT REMOTE BACKUP FOR RESTORATION</span>
                </div>
                <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--green)' }}>
                  {jobs.filter((j) => j.status === 'completed').length} VERIFIED FILES
                </span>
              </div>

              <div style={{ maxHeight: '440px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {jobs.filter((j) => j.status === 'completed').length === 0 ? (
                  <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-dim)' }}>
                    No completed remote backups available yet.
                  </div>
                ) : (
                  jobs.filter((j) => j.status === 'completed').map((j) => (
                    <div
                      key={j.id}
                      onClick={() => {
                        setRestoreJob(j);
                        setRestoreResult(null);
                      }}
                      style={{
                        padding: '12px 14px',
                        borderRadius: '8px',
                        background: restoreJob?.id === j.id ? 'rgba(67, 217, 255, 0.15)' : 'rgba(5, 12, 20, 0.6)',
                        border: restoreJob?.id === j.id ? '1px solid var(--cyan)' : '1px solid rgba(67, 217, 255, 0.1)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '12px',
                        transition: 'all .2s ease',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: '600', color: '#fff', fontSize: '13px' }}>
                          {(j.rel || j.source).split('/').pop()}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                          {j.rel || j.source}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--green)', marginTop: '2px' }}>
                          SHA-256: {j.sha256 ? j.sha256.slice(0, 16) + '…' : 'Verified'}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)' }}>{formatBytes(j.size)}</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{formatDate(j.completed_at)}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Right: Restoration Details & Trigger Panel */}
            <div className="node-hud-card">
              <div className="node-hud-header">
                <div className="node-hud-title">
                  <ShieldCheck size={16} />
                  <span>RESTORE OPERATION SAFEGUARD</span>
                </div>
              </div>

              {restoreJob ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div style={{ background: 'rgba(5, 12, 20, 0.7)', padding: '14px', borderRadius: '8px', border: '1px solid rgba(67, 217, 255, 0.15)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginBottom: '4px' }}>SELECTED FILE FOR RESTORE:</div>
                    <div style={{ fontWeight: '700', fontSize: '14px', color: 'var(--cyan)' }}>
                      {(restoreJob.rel || restoreJob.source).split('/').pop()}
                    </div>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text)', marginTop: '4px' }}>
                      Size: {formatBytes(restoreJob.size)} · SHA-256: {restoreJob.sha256}
                    </div>
                  </div>

                  <div className="settings-field">
                    <label>OPTIONAL CUSTOM DESTINATION FOLDER (LEAVE EMPTY FOR DEFAULT DIR):</label>
                    <input
                      type="text"
                      className="settings-input"
                      placeholder="e.g. C:\Users\taha\Downloads"
                      value={restoreCustomDest}
                      onChange={(e) => setRestoreCustomDest(e.target.value)}
                    />
                  </div>

                  {/* Overwrite Protection Warning Notice */}
                  <div style={{
                    background: 'rgba(255, 180, 92, 0.08)',
                    border: '1px solid rgba(255, 180, 92, 0.35)',
                    borderRadius: '8px',
                    padding: '12px',
                    fontSize: '11px',
                    color: 'var(--amber)',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '10px',
                    lineHeight: '1.4',
                  }}>
                    <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
                    <div>
                      <strong>OVERWRITE PROTECTION ACTIVE:</strong> Files are safely downloaded with a <code>-restored</code> suffix if an existing file exists. Remote copies are NEVER deleted or overwritten. SHA-256 is recalculated locally upon receipt to guarantee zero file corruption.
                    </div>
                  </div>

                  <button
                    className="backup-btn primary"
                    style={{ padding: '12px', fontSize: '12px', justifyContent: 'center' }}
                    onClick={handleRestoreFile}
                    disabled={restoring}
                  >
                    <Download size={14} className={restoring ? 'spin' : ''} />
                    <span>{restoring ? 'COPYING FROM UBUNTU & VERIFYING CHECKSUM...' : 'START RESTORE & VERIFY CHECKSUM'}</span>
                  </button>

                  {/* Result Box */}
                  {restoreResult && (
                    <div style={{
                      padding: '14px',
                      borderRadius: '8px',
                      background: restoreResult.success ? 'rgba(114, 240, 176, 0.12)' : 'rgba(255, 98, 117, 0.12)',
                      border: restoreResult.success ? '1px solid rgba(114, 240, 176, 0.4)' : '1px solid rgba(255, 98, 117, 0.4)',
                      color: restoreResult.success ? 'var(--green)' : 'var(--red)',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                    }}>
                      {restoreResult.success ? (
                        <div>
                          <div style={{ fontWeight: '700', fontSize: '13px', marginBottom: '4px' }}>✓ RESTORATION VERIFIED!</div>
                          <div>Saved to: <strong>{restoreResult.path}</strong></div>
                          <div style={{ fontSize: '10px', marginTop: '4px', opacity: 0.85 }}>Host: {restoreResult.host} · SHA-256 integrity match confirmed.</div>
                        </div>
                      ) : (
                        <div>
                          <div style={{ fontWeight: '700', fontSize: '13px', marginBottom: '4px' }}>✗ RESTORE FAILED</div>
                          <div>{restoreResult.error}</div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  <Download size={32} color="rgba(67, 217, 255, 0.3)" style={{ marginBottom: '10px' }} />
                  <p style={{ fontSize: '12px', fontFamily: 'var(--font-mono)' }}>Select a file on the left to review restore parameters and trigger download.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 5: BACKUP SETTINGS ── */}
      {activeTab === 'settings' && (
        <div className="backup-tab-content">
          <form onSubmit={handleSaveSettings}>
            <div className="settings-grid">
              {/* Card 1: Remote Ubuntu Host & SSH */}
              <div className="settings-card">
                <div className="node-hud-title">
                  <Server size={16} />
                  <span>UBUNTU SERVER & SSH CONNECTION</span>
                </div>

                <div className="settings-field">
                  <label>UBUNTU HOST (LAN IP OR HOSTNAME):</label>
                  <input
                    type="text"
                    className="settings-input"
                    value={settingsForm?.host || ''}
                    onChange={(e) => setSettingsForm({ ...settingsForm, host: e.target.value })}
                  />
                </div>

                <div className="settings-field">
                  <label>FALLBACK HOST (OPTIONAL TAILSCALE / VPN IP):</label>
                  <input
                    type="text"
                    className="settings-input"
                    placeholder="e.g. 100.x.y.z"
                    value={settingsForm?.fallback_host || ''}
                    onChange={(e) => setSettingsForm({ ...settingsForm, fallback_host: e.target.value })}
                  />
                </div>

                <div className="settings-field">
                  <label>SSH USERNAME:</label>
                  <input
                    type="text"
                    className="settings-input"
                    value={settingsForm?.user || ''}
                    onChange={(e) => setSettingsForm({ ...settingsForm, user: e.target.value })}
                  />
                </div>

                <div className="settings-field">
                  <label>SSH PRIVATE KEY PATH (ED25519 ON WINDOWS):</label>
                  <input
                    type="text"
                    className="settings-input"
                    value={settingsForm?.key_path || ''}
                    onChange={(e) => setSettingsForm({ ...settingsForm, key_path: e.target.value })}
                  />
                </div>

                <div className="settings-field">
                  <label>REMOTE BACKUP ROOT ON UBUNTU:</label>
                  <input
                    type="text"
                    className="settings-input"
                    value={settingsForm?.remote_root || ''}
                    onChange={(e) => setSettingsForm({ ...settingsForm, remote_root: e.target.value })}
                  />
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                  <button
                    type="button"
                    className="backup-btn"
                    onClick={handleTestConnection}
                    disabled={testingConn}
                  >
                    <Wifi size={13} className={testingConn ? 'spin' : ''} />
                    <span>TEST SSH CONNECTION NOW</span>
                  </button>
                  {testConnResult && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      color: testConnResult.reachable ? 'var(--green)' : 'var(--red)',
                    }}>
                      <span>{testConnResult.reachable ? `✓ Connected (${testConnResult.latency_ms}ms)` : `✗ Unreachable`}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Card 2: Monitored Roots & Exclusions */}
              <div className="settings-card">
                <div className="node-hud-title">
                  <HardDrive size={16} />
                  <span>MONITORED LOCAL ROOTS & POLICIES</span>
                </div>

                <div className="settings-field">
                  <label>LOCAL BACKUP ROOTS (COMMA-SEPARATED PATHS):</label>
                  <input
                    type="text"
                    className="settings-input"
                    value={(settingsForm?.roots || []).join(', ')}
                    onChange={(e) => setSettingsForm({
                      ...settingsForm,
                      roots: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                    })}
                  />
                </div>

                <div className="settings-field">
                  <label>RECONCILIATION SCAN INTERVAL (SECONDS):</label>
                  <input
                    type="number"
                    className="settings-input"
                    value={settingsForm?.scan_interval_seconds || 300}
                    onChange={(e) => setSettingsForm({
                      ...settingsForm,
                      scan_interval_seconds: Number(e.target.value),
                    })}
                  />
                </div>

                <div className="settings-field">
                  <label>MAX RETRIES BEFORE JOB MARKED FAILED:</label>
                  <input
                    type="number"
                    className="settings-input"
                    value={settingsForm?.max_retries || 20}
                    onChange={(e) => setSettingsForm({
                      ...settingsForm,
                      max_retries: Number(e.target.value),
                    })}
                  />
                </div>

                <div className="settings-field">
                  <label>MAX INDIVIDUAL FILE SIZE (BYTES):</label>
                  <input
                    type="number"
                    className="settings-input"
                    value={settingsForm?.max_file_bytes || 524288000}
                    onChange={(e) => setSettingsForm({
                      ...settingsForm,
                      max_file_bytes: Number(e.target.value),
                    })}
                  />
                </div>

                <div style={{
                  background: 'rgba(5, 12, 20, 0.6)',
                  padding: '12px',
                  borderRadius: '6px',
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-dim)',
                  lineHeight: '1.4',
                }}>
                  🔒 Sensitive patterns excluded by default: <code>.env*, *secret*, *token*, *credential*, *.pem, *.key</code>.
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                  <button type="submit" className="backup-btn primary" disabled={busy}>
                    <Check size={13} />
                    <span>SAVE CONFIGURATION</span>
                  </button>
                  <button
                    type="button"
                    className="backup-btn secondary"
                    onClick={() => setSettingsForm(config || {})}
                  >
                    <span>RESET</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* ── File Details Modal ── */}
      {selectedFile && (
        <div className="backup-modal-backdrop" onClick={() => setSelectedFile(null)}>
          <div className="backup-modal-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(67, 217, 255, 0.2)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px', fontWeight: '700', color: 'var(--cyan)' }}>
                {getFileIcon(selectedFile.category)}
                <span>FILE INSPECTOR // {(selectedFile.rel || selectedFile.source).split('/').pop()}</span>
              </div>
              <button className="icon-btn" onClick={() => setSelectedFile(null)} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            <div className="node-spec-list" style={{ gridTemplateColumns: '1fr' }}>
              <div className="node-spec-item">
                <span className="node-spec-label">FULL LOCAL SOURCE PATH:</span>
                <span className="node-spec-value" style={{ wordBreak: 'break-all' }}>{selectedFile.source}</span>
              </div>
              <div className="node-spec-item">
                <span className="node-spec-label">RELATIVE REPOSITORY PATH:</span>
                <span className="node-spec-value">{selectedFile.rel}</span>
              </div>
              <div className="node-spec-item">
                <span className="node-spec-label">FILE SIZE & CATEGORY:</span>
                <span className="node-spec-value">{formatBytes(selectedFile.size)} ({selectedFile.category.toUpperCase()})</span>
              </div>
              <div className="node-spec-item">
                <span className="node-spec-label">VERIFIED SHA-256 CHECKSUM:</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="node-spec-value" style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>
                    {selectedFile.sha256 || 'Pending verification on Ubuntu'}
                  </span>
                  {selectedFile.sha256 && (
                    <button
                      className="icon-btn"
                      style={{ background: 'none', border: 'none', color: 'var(--cyan)', cursor: 'pointer' }}
                      onClick={() => copyToClipboard(selectedFile.sha256, 'SHA-256')}
                      title="Copy Hash"
                    >
                      <Copy size={12} />
                    </button>
                  )}
                </div>
              </div>
              <div className="node-spec-item">
                <span className="node-spec-label">STATUS & RETRIES:</span>
                <span className="node-spec-value">{selectedFile.status.toUpperCase()} (Retries: {selectedFile.retries || 0})</span>
              </div>
              {selectedFile.last_error && (
                <div className="node-spec-item">
                  <span className="node-spec-label" style={{ color: 'var(--red)' }}>LAST REPORTED ERROR:</span>
                  <span className="node-spec-value" style={{ color: 'var(--red)' }}>{selectedFile.last_error}</span>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
              {selectedFile.status === 'completed' && (
                <button
                  className="backup-btn success"
                  onClick={() => {
                    setRestoreJob(selectedFile);
                    setSelectedFile(null);
                    setActiveTab('restore');
                  }}
                >
                  <Download size={13} />
                  <span>RESTORE THIS FILE</span>
                </button>
              )}
              {selectedFile.status === 'failed' && (
                <button
                  className="backup-btn"
                  onClick={() => {
                    performAction('/api/backup/retry', { job_id: selectedFile.id });
                    setSelectedFile(null);
                  }}
                >
                  <RotateCcw size={13} />
                  <span>RETRY JOB</span>
                </button>
              )}
              <button className="backup-btn secondary" onClick={() => setSelectedFile(null)}>
                <span>CLOSE</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Node Telemetry Modal (from 3D scene click) ── */}
      {inspectedNode && (
        <div className="backup-modal-backdrop" onClick={() => setInspectedNode(null)}>
          <div className="backup-modal-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(67, 217, 255, 0.2)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px', fontWeight: '700', color: 'var(--cyan)' }}>
                {inspectedNode === 'windows' ? <Laptop size={18} /> : inspectedNode === 'ubuntu' ? <Server size={18} /> : <HardDrive size={18} />}
                <span>NODE TELEMETRY // {inspectedNode.toUpperCase()}</span>
              </div>
              <button className="icon-btn" onClick={() => setInspectedNode(null)} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            {inspectedNode === 'windows' && (
              <div className="node-spec-list" style={{ gridTemplateColumns: '1fr' }}>
                <div className="node-spec-item">
                  <span className="node-spec-label">ROLE:</span>
                  <span className="node-spec-value">Primary local laptop node. Files are ALWAYS written and verified here first.</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">SYSTEM SPECS:</span>
                  <span className="node-spec-value">{localSys.platform || 'Windows 11'} · Host: {localSys.hostname}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">DISK CAPACITY:</span>
                  <span className="node-spec-value">{formatBytes(localSys.disk_free)} free of {formatBytes(localSys.disk_total)}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">MONITORED FOLDERS:</span>
                  <span className="node-spec-value">{(backupStatus?.roots || []).join(', ')}</span>
                </div>
              </div>
            )}

            {inspectedNode === 'ubuntu' && (
              <div className="node-spec-list" style={{ gridTemplateColumns: '1fr' }}>
                <div className="node-spec-item">
                  <span className="node-spec-label">ROLE:</span>
                  <span className="node-spec-value">Secondary LAN backup server. Receives verified SHA-256 replicas.</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">IP ADDRESS & USER:</span>
                  <span className="node-spec-value">{backupStatus?.user}@{backupStatus?.host || '192.168.1.110'}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">DESTINATION ROOT:</span>
                  <span className="node-spec-value">{backupStatus?.remote_root}</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">CURRENT REACHABILITY:</span>
                  <span className="node-spec-value" style={{ color: isServerReachable ? 'var(--green)' : 'var(--red)' }}>
                    {isServerReachable ? 'Connected and responding via OpenSSH' : 'Unreachable on LAN — queueing jobs safely'}
                  </span>
                </div>
              </div>
            )}

            {inspectedNode === 'core' && (
              <div className="node-spec-list" style={{ gridTemplateColumns: '1fr' }}>
                <div className="node-spec-item">
                  <span className="node-spec-label">CORE INTEGRITY PROTOCOL:</span>
                  <span className="node-spec-value">Local-First Atomic Transport with Remote Checksum Verification</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">ENCRYPTION & TRANSPORT:</span>
                  <span className="node-spec-value">OpenSSH Client · Ed25519 Dedicated Key · BatchMode · AES-GCM Ciphers</span>
                </div>
                <div className="node-spec-item">
                  <span className="node-spec-label">INTEGRITY GUARANTEE:</span>
                  <span className="node-spec-value">SHA-256 calculated locally, sent via temp .part-file, committed and verified remotely.</span>
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
              <button className="backup-btn primary" onClick={() => setInspectedNode(null)}>
                <span>ACKNOWLEDGED</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
