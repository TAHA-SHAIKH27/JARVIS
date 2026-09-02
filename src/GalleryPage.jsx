import React, { useState, useEffect, useCallback } from 'react'
import {
  ArrowLeft, Images, Trash2, X, ChevronLeft, ChevronRight,
  Monitor, Smartphone, Sparkles, FolderOpen, RefreshCw, ZoomIn
} from 'lucide-react'

function formatBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function formatDate(mtime) {
  if (!mtime) return ''
  return new Date(mtime * 1000).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })
}

const CATEGORIES = [
  { key: 'all', label: 'ALL', icon: Images },
  { key: 'pc_screenshot', label: 'PC SHOTS', icon: Monitor },
  { key: 'phone', label: 'PHONE', icon: Smartphone },
  { key: 'generated', label: 'AI GEN', icon: Sparkles },
  { key: 'other', label: 'OTHER', icon: FolderOpen },
]

export default function GalleryPage({ setActiveView }) {
  const [images, setImages] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeCategory, setActiveCategory] = useState('all')
  const [lightboxIdx, setLightboxIdx] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  const fetchGallery = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/gallery')
      if (res.ok) {
        const data = await res.json()
        setImages(data.images || [])
      }
    } catch { }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchGallery() }, [fetchGallery])

  // Close lightbox on Escape, arrow-key navigation
  useEffect(() => {
    if (lightboxIdx === null) return
    function onKey(e) {
      if (e.key === 'Escape') setLightboxIdx(null)
      if (e.key === 'ArrowRight') setLightboxIdx(i => Math.min(i + 1, filtered.length - 1))
      if (e.key === 'ArrowLeft') setLightboxIdx(i => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightboxIdx])  // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = activeCategory === 'all'
    ? images
    : images.filter(img => img.category === activeCategory)

  async function handleDelete(img) {
    if (deleteConfirm !== img.path) {
      setDeleteConfirm(img.path)
      setTimeout(() => setDeleteConfirm(null), 3000)
      return
    }
    setDeleteConfirm(null)
    setDeleting(img.path)
    try {
      const res = await fetch(`/api/files/delete?filename=${encodeURIComponent(img.path)}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        setImages(imgs => imgs.filter(i => i.path !== img.path))
        if (lightboxIdx !== null) setLightboxIdx(null)
      }
    } catch { }
    finally { setDeleting(null) }
  }

  const currentLightboxImg = lightboxIdx !== null ? filtered[lightboxIdx] : null

  const catCounts = {}
  for (const img of images) {
    catCounts[img.category] = (catCounts[img.category] || 0) + 1
  }

  return (
    <div className="fullpage-overlay">
      {/* ── Top bar ── */}
      <div className="fp-topbar">
        <button className="fp-back-btn" onClick={() => setActiveView('core')}>
          <ArrowLeft size={14} /> BACK TO JARVIS
        </button>
        <div className="fp-title">
          <Images size={16} style={{ color: 'var(--cyan)' }} />
          <span>FILES &amp; GALLERY</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 10, color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>
            {images.length} FILE{images.length !== 1 ? 'S' : ''}
          </span>
          <button className="gallery-refresh-btn" onClick={fetchGallery} title="Refresh">
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="gallery-body">
        {/* Category filter rail */}
        <div className="gallery-filter-rail">
          {CATEGORIES.map(cat => {
            const Icon = cat.icon
            const count = cat.key === 'all' ? images.length : (catCounts[cat.key] || 0)
            return (
              <button
                key={cat.key}
                className={`gallery-filter-btn ${activeCategory === cat.key ? 'active' : ''}`}
                onClick={() => setActiveCategory(cat.key)}
              >
                <Icon size={14} />
                <span>{cat.label}</span>
                {count > 0 && <span className="gallery-count-badge">{count}</span>}
              </button>
            )
          })}
        </div>

        {/* Grid area */}
        <div className="gallery-scroll-area">
          {loading && (
            <div className="gallery-empty-state">
              <div className="stream-scanning-ring" style={{ width: 48, height: 48 }} />
              <p style={{ marginTop: 18 }}>Loading gallery…</p>
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="gallery-empty-state">
              <div className="gallery-empty-icon">
                <Images size={52} style={{ color: 'var(--cyan)', opacity: .25 }} />
              </div>
              <p className="gallery-empty-title">No files here yet</p>
              <p className="gallery-empty-sub">
                {activeCategory === 'all'
                  ? 'Take a screenshot, mirror your phone, or generate an image to see it here.'
                  : `No ${CATEGORIES.find(c => c.key === activeCategory)?.label?.toLowerCase()} files yet.`}
              </p>
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <div className="gallery-grid">
              {filtered.map((img, idx) => (
                <div className="gallery-card" key={img.path}>
                  <div
                    className="gallery-thumb-wrap"
                    onClick={() => setLightboxIdx(idx)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => e.key === 'Enter' && setLightboxIdx(idx)}
                  >
                    <img
                      className="gallery-thumb"
                      src={`/api/files/serve?path=${encodeURIComponent(img.path)}`}
                      alt={img.filename}
                      loading="lazy"
                    />
                    <div className="gallery-thumb-overlay">
                      <ZoomIn size={22} style={{ color: 'var(--cyan)' }} />
                    </div>
                  </div>
                  <div className="gallery-card-meta">
                    <span className="gallery-card-name" title={img.filename}>{img.filename}</span>
                    <div className="gallery-card-row2">
                      <span className={`gallery-cat-tag cat-${img.category}`}>
                        {img.category === 'pc_screenshot' ? 'PC' :
                          img.category === 'phone' ? 'PHONE' :
                          img.category === 'generated' ? 'AI' : 'FILE'}
                      </span>
                      <span className="gallery-card-size">{formatBytes(img.size)}</span>
                      <button
                        className={`gallery-delete-btn ${deleteConfirm === img.path ? 'confirm' : ''}`}
                        onClick={() => handleDelete(img)}
                        disabled={deleting === img.path}
                        title={deleteConfirm === img.path ? 'Click again to confirm delete' : 'Delete'}
                        aria-label={`Delete ${img.filename}`}
                      >
                        {deleting === img.path
                          ? '…'
                          : deleteConfirm === img.path
                            ? '✓ Confirm'
                            : <Trash2 size={12} />}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Lightbox ── */}
      {currentLightboxImg && (
        <div
          className="lightbox-overlay"
          onClick={() => setLightboxIdx(null)}
        >
          <div className="lightbox-box" onClick={e => e.stopPropagation()}>
            {/* Nav arrows */}
            {lightboxIdx > 0 && (
              <button className="lightbox-arrow left" onClick={() => setLightboxIdx(i => i - 1)}>
                <ChevronLeft size={22} />
              </button>
            )}
            {lightboxIdx < filtered.length - 1 && (
              <button className="lightbox-arrow right" onClick={() => setLightboxIdx(i => i + 1)}>
                <ChevronRight size={22} />
              </button>
            )}

            {/* Close */}
            <button className="lightbox-close" onClick={() => setLightboxIdx(null)}>
              <X size={16} />
            </button>

            <img
              className="lightbox-img"
              src={`/api/files/serve?path=${encodeURIComponent(currentLightboxImg.path)}`}
              alt={currentLightboxImg.filename}
            />

            {/* Meta footer */}
            <div className="lightbox-footer">
              <div className="lightbox-filename">{currentLightboxImg.filename}</div>
              <div className="lightbox-meta">
                <span>{formatBytes(currentLightboxImg.size)}</span>
                <span style={{ opacity: .5 }}>·</span>
                <span>{formatDate(currentLightboxImg.mtime)}</span>
                <span style={{ opacity: .5 }}>·</span>
                <span>{lightboxIdx + 1} / {filtered.length}</span>
              </div>
              <button
                className={`gallery-delete-btn ${deleteConfirm === currentLightboxImg.path ? 'confirm' : ''}`}
                style={{ marginLeft: 'auto', padding: '6px 14px', gap: 6, display: 'flex', alignItems: 'center' }}
                onClick={() => handleDelete(currentLightboxImg)}
                disabled={deleting === currentLightboxImg.path}
              >
                <Trash2 size={13} />
                {deleteConfirm === currentLightboxImg.path ? 'Confirm delete?' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
