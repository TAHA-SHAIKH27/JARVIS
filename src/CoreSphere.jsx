import React, { useEffect, useRef } from 'react'

const COLORS = { idle: '#43d9ff', listening: '#54a8ff', wake: '#72f0b0', processing: '#ffb45c', speaking: '#72f0b0' }

export default function CoreSphere({ state = 'idle' }) {
  const canvasRef = useRef(null)
  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const points = Array.from({ length: 360 }, (_, i) => {
      const y = 1 - (i / 359) * 2
      const r = Math.sqrt(1 - y * y)
      const a = Math.PI * (3 - Math.sqrt(5)) * i
      return { x: Math.cos(a) * r, y, z: Math.sin(a) * r }
    })
    let raf, t = 0
    const render = () => {
      const w = canvas.offsetWidth, h = canvas.offsetHeight
      canvas.width = w * dpr; canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h)
      const level = Math.min(1, Math.max(0, window.jarvisAudioLevel || 0))
      const color = COLORS[state] || COLORS.idle
      const cx = w / 2, cy = h / 2, radius = Math.min(w, h) * .31
      t += state === 'idle' ? .012 : .032
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * .18)
      ;[1, .78, .58].forEach((scale, index) => {
        ctx.beginPath(); ctx.arc(0, 0, radius * scale * (1 + level * .08), 0, Math.PI * 2)
        ctx.strokeStyle = color; ctx.globalAlpha = .18 - index * .04; ctx.lineWidth = index === 0 ? 1 : .6
        ctx.setLineDash(index === 0 ? [2, 8] : [1, 14]); ctx.stroke()
        ctx.rotate(index % 2 ? -.22 : .34)
      })
      ctx.restore()
      const projected = points.map((p, i) => {
        const a = t * (state === 'processing' ? 2 : 1) + p.y * .15
        const x = p.x * Math.cos(a) - p.z * Math.sin(a), z = p.x * Math.sin(a) + p.z * Math.cos(a)
        const ripple = Math.sin(t * 5 + p.y * 8) * level * 20
        const r = radius + ripple
        return { x: cx + x * r, y: cy + p.y * r, z, i }
      }).sort((a, b) => a.z - b.z)
      ctx.shadowBlur = state === 'idle' ? 8 : 22; ctx.shadowColor = color; ctx.fillStyle = color
      projected.forEach(p => { ctx.globalAlpha = .15 + (p.z + 1) * .35; ctx.beginPath(); ctx.arc(p.x, p.y, .7 + (p.z + 1) * 1.1 + level * 2, 0, Math.PI * 2); ctx.fill() })
      ctx.globalAlpha = 1; raf = requestAnimationFrame(render)
    }
    render(); return () => cancelAnimationFrame(raf)
  }, [state])
  const color = COLORS[state] || COLORS.idle
  return <div className={`core-container core-${state}`} style={{ '--core-color': color }}><div className="core-glow" /><div className="core-crosshair" /><canvas ref={canvasRef} className="core-canvas" /></div>
}
