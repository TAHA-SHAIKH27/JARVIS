import React, { useState, useEffect } from 'react';
import {
  Terminal, ShieldCheck, AlertTriangle, CheckCircle, RefreshCw,
  FileCode, Play, ArrowLeft, Download, Eye, Zap, Cpu, History
} from 'lucide-react';

export default function CodeCorePage({ setActiveView }) {
  const [auditData, setAuditData] = useState(null);
  const [auditing, setAuditing] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationLog, setValidationLog] = useState('');
  
  // Diff preview state
  const [previewData, setPreviewData] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);

  // Uploaded file refactor state
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadContent, setUploadContent] = useState('');
  const [uploadInstructions, setUploadInstructions] = useState('');
  const [processingUpload, setProcessingUpload] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [showUploadDiff, setShowUploadDiff] = useState(false);
  const [scanClock, setScanClock] = useState(0);
  const [selectedFile, setSelectedFile] = useState(null);

  const fallbackFiles = [
    'main.py', 'agent.py', 'system_ops.py', 'phone_control.py',
    'backend/agent/core.py', 'backend/agent/executor.py', 'src/App.jsx', 'src/CoreSphere.jsx'
  ];
  const issueFiles = new Set((auditData?.issues || []).map(issue => issue.file));
  const scannedFiles = auditData?.files?.length ? auditData.files : fallbackFiles;
  const scanProgress = auditing ? Math.min(96, 8 + scanClock * 4) : auditData ? 100 : 0;
  const scanPhase = auditing ? (scanProgress < 35 ? 'INDEXING SOURCE TREE' : scanProgress < 75 ? 'RUNNING STATIC ANALYSIS' : 'VERIFYING REPAIR SURFACE') : auditData ? 'AUDIT COMPLETE // CORE STABLE' : 'AWAITING SCAN COMMAND';

  useEffect(() => {
    if (!auditing) { setScanClock(0); return undefined; }
    const timer = window.setInterval(() => setScanClock(value => value + 1), 120);
    return () => window.clearInterval(timer);
  }, [auditing]);

  useEffect(() => {
    runAudit();
  }, []);

  async function runAudit() {
    setAuditing(true);
    setApplyResult(null);
    try {
      const res = await fetch('/api/code/audit', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setAuditData(data);
        setSelectedFile(data.files?.[0] || fallbackFiles[0]);
      }
    } catch (err) {
      console.error('Audit failed:', err);
    } finally {
      setAuditing(false);
    }
  }

  async function previewFix(filepath, issueMsg) {
    setPreviewing(true);
    setPreviewData(null);
    setApplyResult(null);
    try {
      const res = await fetch('/api/code/preview-fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: filepath, issue: issueMsg })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setPreviewData(data);
      } else {
        alert(data.message || 'Failed to generate preview.');
      }
    } catch (err) {
      alert('Error querying NVIDIA AI for fix preview.');
    } finally {
      setPreviewing(false);
    }
  }

  async function applyFix() {
    if (!previewData) return;
    setApplying(true);
    setApplyResult(null);
    try {
      const res = await fetch('/api/code/apply-fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file: previewData.file,
          proposed_content: previewData.proposed_content
        })
      });
      const data = await res.json();
      setApplyResult(data);
      if (data.status === 'success') {
        runAudit(); // Refresh audit
      }
    } catch (err) {
      setApplyResult({ status: 'error', message: 'Failed to communicate with backend.' });
    } finally {
      setApplying(false);
    }
  }

  async function runValidationSuite() {
    setValidating(true);
    setValidationLog('Executing multi-tier validation checks...\n');
    try {
      const res = await fetch('/api/code/audit', { method: 'POST' });
      const data = await res.json();
      let log = `Validation Timestamp: ${new Date().toLocaleTimeString()}\n`;
      log += `Files scanned: ${data.total_files_checked}\n`;
      log += `Python AST & Syntax Integrity: ${data.issues_count === 0 ? '✓ PASS (0 errors)' : `✗ FAIL (${data.issues_count} issues)`}\n`;
      log += `System Health Score: ${data.health_score}%\n`;
      log += `Status: ${data.status.toUpperCase()}\n`;
      setValidationLog(log);
    } catch (err) {
      setValidationLog(`Validation check failed: ${err.message}`);
    } finally {
      setValidating(false);
    }
  }

  function handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => {
      setUploadContent(ev.target?.result || '');
    };
    reader.readAsText(file);
  }

  async function processUploadedCode() {
    if (!uploadFile || !uploadContent) return;
    setProcessingUpload(true);
    setUploadResult(null);
    try {
      const res = await fetch('/api/code/process-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: uploadFile.name,
          content: uploadContent,
          instructions: uploadInstructions
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setUploadResult(data);
      } else {
        alert(data.message || 'File processing failed.');
      }
    } catch (err) {
      alert(`Error during uploaded file refactoring: ${err.message || 'Check if backend server is running.'}`);
    } finally {
      setProcessingUpload(false);
    }
  }

  return (
    <div className="codecore-container">
      {/* Top Navigation */}
      <div className="codecore-header">
        <div className="codecore-title-wrap">
          <button className="back-btn" onClick={() => setActiveView('core')}>
            <ArrowLeft size={16} /> CORE HUD
          </button>
          <div className="codecore-title">
            <Terminal size={20} className="codecore-icon" />
            <span>CODE CORE // AUTONOMOUS DEVELOPER ENGINE</span>
          </div>
        </div>

        <div className="codecore-actions">
          <div className={`codecore-live-state ${auditing ? 'is-scanning' : 'is-ready'}`}><span className="live-dot" /> {auditing ? 'CORE SCANNING' : auditData ? 'CORE READY' : 'CORE STANDBY'}</div>
          <button className="codecore-btn" onClick={runAudit} disabled={auditing}>
            <RefreshCw size={14} className={auditing ? 'spinning' : ''} />
            {auditing ? 'AUDITING...' : 'SELF-AUDIT CODEBASE'}
          </button>
          <button className="codecore-btn secondary" onClick={runValidationSuite} disabled={validating}>
            <ShieldCheck size={14} />
            {validating ? 'TESTING...' : 'VALIDATE SYSTEM'}
          </button>
        </div>
      </div>

      {/* Autonomous scan workspace */}
      <section className="codecore-scan-console">
        <div className="scan-console-topline"><span><Cpu size={14} /> SELF-HEALING ENGINE // LIVE SOURCE INSPECTOR</span><span className="scan-phase">{scanPhase}</span></div>
        <div className="scan-console-grid">
          <div className="scan-progress-orb"><div className="scan-orb-ring"><span>{scanProgress}%</span></div><small>CODEBASE SCAN</small></div>
          <div className="scan-progress-main"><div className="scan-progress-heading"><strong>{auditing ? 'Analyzing source integrity' : auditData ? 'Source integrity mapped' : 'Ready to inspect source'}</strong><span>{scannedFiles.length} FILE NODES</span></div><div className="scan-track"><span style={{ width: `${scanProgress}%` }} /></div><div className="scan-progress-meta"><span>NODE COVERAGE {scanProgress}%</span><span>{auditData?.issues_count || 0} ANOMALIES</span><span>HEALTH {auditData?.health_score ?? '--'}%</span></div></div>
          <div className="scan-current-file"><small>ACTIVE FILE NODE</small><strong><FileCode size={14} /> {auditing ? scannedFiles[Math.floor(scanClock / 2) % scannedFiles.length] : selectedFile || 'Awaiting source index'}</strong><span>{auditing ? 'Reading syntax and dependency graph...' : 'Select a file node to inspect its health state.'}</span></div>
        </div>
        <div className="scan-file-strip">{scannedFiles.map((file, index) => { const hasIssue = issueFiles.has(file); const isActive = selectedFile === file || (auditing && index === Math.floor(scanClock / 2) % scannedFiles.length); return <button key={file} className={`scan-file-node ${isActive ? 'active' : ''} ${hasIssue ? 'warning' : 'verified'}`} onClick={() => setSelectedFile(file)}><span className="file-node-status">{hasIssue ? '!' : isActive && auditing ? '·' : '✓'}</span><span>{file}</span><small>{hasIssue ? 'REVIEW' : isActive && auditing ? 'SCANNING' : 'VERIFIED'}</small></button>; })}</div>
      </section>

      {/* Main Grid Layout */}
      <div className="codecore-grid">
        
        {/* Left Column: Health & Audit Issues */}
        <div className="codecore-col">
          
          {/* Health Summary Card */}
          <div className="codecore-card health-card">
            <div className="card-header"><span className="card-title">AUTONOMOUS CORE STATUS</span><span className="engine-chip"><Zap size={11} /> SELF-HEALING</span></div>
            <div className="engine-status-copy"><strong>{auditing ? 'JARVIS is tracing its own execution surface.' : auditData ? 'No source node is outside the repair perimeter.' : 'Initialize a source scan to begin.'}</strong><span>Every file node is indexed, scored, and queued for safe repair before a patch can be applied.</span></div>
          </div>
          <div className="codecore-card activity-card">
            <div className="card-header"><span className="card-title">CORE ACTIVITY STREAM</span><History size={14} /></div>
            <div className="activity-stream"><div><span className="activity-time">NOW</span><span>{auditing ? 'Traversing source graph and checking syntax...' : 'Source graph synchronized.'}</span></div><div><span className="activity-time">SYS</span><span>{auditData ? `${auditData.total_files_checked} file nodes returned a health signal.` : 'Waiting for audit telemetry.'}</span></div><div><span className="activity-time">SAFE</span><span>Backup and rollback guards armed for every repair.</span></div></div>
          </div>

          <div className="codecore-card health-card">
            <div className="card-header">
              <span className="card-title">CODEBASE INTEGRITY & SAFETY</span>
              <span className={`status-badge ${auditData?.status || 'healthy'}`}>
                {auditData?.status?.toUpperCase() || 'CHECKING'}
              </span>
            </div>

            <div className="health-metrics">
              <div className="metric-box">
                <div className="metric-val">{auditData ? `${auditData.health_score}%` : '--'}</div>
                <div className="metric-lbl">Health Score</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{auditData ? auditData.total_files_checked : '--'}</div>
                <div className="metric-lbl">Files Inspected</div>
              </div>
              <div className="metric-box">
                <div className="metric-val">{auditData ? auditData.issues_count : '--'}</div>
                <div className="metric-lbl">Issues Detected</div>
              </div>
            </div>

            <div className="safety-note">
              <ShieldCheck size={14} className="safety-icon" />
              <span>Safe Patch System: Backups created before every edit. Automatic rollback on validation failure.</span>
            </div>
          </div>

          {/* Detected Issues List */}
          <div className="codecore-card">
            <div className="card-header">
              <span className="card-title">DETECTED ISSUES & WARNINGS</span>
              <span className="count-pill">{auditData?.issues?.length || 0}</span>
            </div>

            <div className="issues-list">
              {auditData?.issues?.length === 0 ? (
                <div className="empty-issues">
                  <CheckCircle size={32} className="check-icon" />
                  <p>All source files verified healthy. Zero syntax errors detected.</p>
                </div>
              ) : (
                auditData?.issues?.map((iss, idx) => (
                  <div key={idx} className="issue-row">
                    <div className="issue-info">
                      <div className="issue-file">
                        <FileCode size={13} />
                        <span>{iss.file}</span>
                        {iss.line > 0 && <span className="line-tag">Line {iss.line}</span>}
                      </div>
                      <div className="issue-msg">{iss.message}</div>
                      {iss.snippet && <pre className="issue-snippet">{iss.snippet}</pre>}
                    </div>
                    <button
                      className="preview-fix-btn"
                      onClick={() => previewFix(iss.file, iss.message)}
                      disabled={previewing}
                    >
                      <Zap size={12} /> Preview Fix
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Validation Suite Console */}
          {validationLog && (
            <div className="codecore-card">
              <div className="card-header">
                <span className="card-title">VALIDATION OUTPUT</span>
              </div>
              <pre className="val-console">{validationLog}</pre>
            </div>
          )}

        </div>

        {/* Right Column: Diff Preview & File Refactorer */}
        <div className="codecore-col">
          
          {/* Diff Previewer Box */}
          {previewData && (
            <div className="codecore-card diff-card">
              <div className="card-header">
                <span className="card-title">UNIFIED DIFF PREVIEW // {previewData.file}</span>
                <span className="diff-tag">NVIDIA NIM GENERATED</span>
              </div>

              <div className="diff-viewer">
                <pre className="diff-content">
                  {previewData.diff.split('\n').map((line, i) => {
                    let cl = 'diff-line';
                    if (line.startsWith('+') && !line.startsWith('+++')) cl += ' diff-add';
                    else if (line.startsWith('-') && !line.startsWith('---')) cl += ' diff-del';
                    else if (line.startsWith('@@')) cl += ' diff-hdr';
                    return <div key={i} className={cl}>{line}</div>;
                  })}
                </pre>
              </div>

              <div className="diff-actions">
                <button className="codecore-btn danger" onClick={() => setPreviewData(null)}>
                  DISCARD PREVIEW
                </button>
                <button className="codecore-btn success" onClick={applyFix} disabled={applying}>
                  <Zap size={14} />
                  {applying ? 'APPLYING & TESTING...' : 'APPLY PATCH & VALIDATE'}
                </button>
              </div>

              {applyResult && (
                <div className={`apply-alert ${applyResult.status}`}>
                  {applyResult.status === 'success' ? (
                    <div>✓ {applyResult.message}</div>
                  ) : (
                    <div>✗ {applyResult.message}</div>
                  )}
                  {applyResult.backup && <div className="backup-loc">Backup: {applyResult.backup}</div>}
                </div>
              )}
            </div>
          )}

          {/* Uploaded File Bug Fixer & Refactor Tool */}
          <div className="codecore-card upload-card">
            <div className="card-header">
              <span className="card-title">CODE FILE INSPECTOR & REFACTOR TOOL</span>
              <span className="diff-tag">ANY LANGUAGE</span>
            </div>

            <p className="card-subtext">
              Upload any broken script or code file. JARVIS will analyze errors, apply fixes, and provide a downloadable corrected version.
            </p>

            <div className="upload-input-wrap">
              <input
                type="file"
                id="code-upload-input"
                style={{ display: 'none' }}
                onChange={handleFileSelect}
                accept=".py,.js,.jsx,.ts,.tsx,.cpp,.c,.java,.html,.css,.json,.sql,.sh"
              />
              <button className="codecore-btn secondary" onClick={() => document.getElementById('code-upload-input')?.click()}>
                <FileCode size={14} /> {uploadFile ? `Selected: ${uploadFile.name}` : 'CHOOSE CODE FILE'}
              </button>

              <input
                className="refactor-prompt-input"
                value={uploadInstructions}
                onChange={e => setUploadInstructions(e.target.value)}
                placeholder="Optional instructions (e.g. 'Fix memory leaks, handle exceptions')..."
              />

              <button
                className="codecore-btn"
                onClick={processUploadedCode}
                disabled={!uploadFile || processingUpload}
              >
                <Play size={14} />
                {processingUpload ? 'INSPECTING & FIXING...' : 'ANALYZE & FIX'}
              </button>
            </div>

            {/* Upload Result */}
            {uploadResult && (
              <div className="upload-result-box">
                <div className="result-header">
                  <span className="result-title">REFACTOR COMPLETE</span>
                  <a
                    href={uploadResult.download_url}
                    download={uploadResult.download_filename}
                    className="download-chip-btn"
                  >
                    <Download size={13} /> DOWNLOAD {uploadResult.download_filename}
                  </a>
                </div>

                <div className="result-summary">{uploadResult.summary}</div>

                <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', letterSpacing: '0.5px' }}>
                    Fixed file saved to downloads. Ready for instant download.
                  </span>
                  <button
                    className="codecore-btn secondary"
                    style={{ fontSize: '11px', padding: '4px 10px' }}
                    onClick={() => setShowUploadDiff(!showUploadDiff)}
                  >
                    <Eye size={12} /> {showUploadDiff ? 'HIDE DIFF' : 'VIEW DIFF'}
                  </button>
                </div>

                {showUploadDiff && (
                  <div className="diff-viewer mini" style={{ marginTop: '10px' }}>
                    <pre className="diff-content">
                      {uploadResult.diff.split('\n').map((line, i) => {
                        let cl = 'diff-line';
                        if (line.startsWith('+') && !line.startsWith('+++')) cl += ' diff-add';
                        else if (line.startsWith('-') && !line.startsWith('---')) cl += ' diff-del';
                        else if (line.startsWith('@@')) cl += ' diff-hdr';
                        return <div key={i} className={cl}>{line}</div>;
                      })}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
}
