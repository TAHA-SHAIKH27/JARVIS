import React, { useEffect, useRef } from 'react'

const COLORS = { idle: '#43d9ff', listening: '#54a8ff', wake: '#72f0b0', processing: '#ffb45c', speaking: '#72f0b0' }
const TAU = Math.PI * 2

function seeded(i) {
  const x = Math.sin(i * 91.733) * 43758.5453
  return x - Math.floor(x)
}

export default function CoreSphere({ state = 'idle' }) {
  const canvasRef = useRef(null)
  const rotationOffsetRef = useRef({ yaw: 0, pitch: 0 })
  const draggingRef = useRef(false)
  const lastPointerRef = useRef({ x: 0, y: 0 })

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25)
    const shell = Array.from({ length: 300 }, (_, i) => {
      const y = 1 - (i / 299) * 2
      const r = Math.sqrt(Math.max(0, 1 - y * y))
      const a = Math.PI * (3 - Math.sqrt(5)) * i
      return { x: Math.cos(a) * r, y, z: Math.sin(a) * r, seed: seeded(i) }
    })
    const sparks = Array.from({ length: 56 }, (_, i) => ({
      a: seeded(i + 700) * TAU, y: seeded(i + 900) * 2 - 1, r: .72 + seeded(i + 1100) * .62, speed: .3 + seeded(i + 1300) * 1.2, size: .5 + seeded(i + 1500) * 1.5
    }))
    let raf = 0
    let t = 0
    let smoothed = 0
    let lastFrame = 0
    const render = (now = 0) => {
      if (now - lastFrame < 28) {
        raf = requestAnimationFrame(render)
        return
      }
      lastFrame = now
      const w = canvas.offsetWidth || 400
      const h = canvas.offsetHeight || 400
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const input = Math.min(1, Math.max(0, Number(window.jarvisAudioLevel) || 0))
      const fallback = .08 + (Math.sin(t * 3.2) * .5 + .5) * .04
      smoothed += ((input > .015 ? input : fallback) - smoothed) * .14
      const color = COLORS[state] || COLORS.idle
      const cx = w / 2, cy = h / 2, base = Math.min(w, h) * .36
      const pulse = 1 + smoothed * .24 + Math.sin(t * 4) * smoothed * .025
      const rotation = t * (state === 'processing' ? 1.9 : .68) + rotationOffsetRef.current.yaw
      const pitch = rotationOffsetRef.current.pitch + Math.sin(t * .35) * .12
      t += state === 'idle' ? .022 : .04

      ctx.save()
      ctx.translate(cx, cy)
      ctx.globalCompositeOperation = 'lighter'
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, base * 1.5 * pulse)
      glow.addColorStop(0, `${color}55`); glow.addColorStop(.34, `${color}18`); glow.addColorStop(1, `${color}00`)
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(0, 0, base * 1.5 * pulse, 0, TAU); ctx.fill()

      const project = (x, y, z, scale = 1) => {
        const perspective = 1 / (1.85 - z * .7)
        return { x: x * base * scale * perspective, y: y * base * scale * perspective, z: perspective }
      }
      const points = shell.map((p, i) => {
        const wobble = Math.sin(t * 3.5 + p.y * 11 + p.seed * 8) * smoothed * .1
        const rr = 1 + wobble
        const x0 = p.x * rr, y0 = p.y * rr, z0 = p.z * rr
        const x1 = x0 * Math.cos(rotation) - z0 * Math.sin(rotation)
        const z1 = x0 * Math.sin(rotation) + z0 * Math.cos(rotation)
        const y = y0 * Math.cos(pitch) - z1 * Math.sin(pitch)
        const z = y0 * Math.sin(pitch) + z1 * Math.cos(pitch)
        const x = x1
        const q = project(x, y, z, pulse)
        return { ...q, z, i }
      })
      points.forEach((p) => {
        const front = (p.z + 1) / 2
        ctx.globalAlpha = .1 + front * .7
        ctx.fillStyle = color
        ctx.shadowBlur = 3 + front * 4
        ctx.shadowColor = color
        ctx.beginPath(); ctx.arc(p.x, p.y, .45 + front * 1.3 + smoothed * 2.2, 0, TAU); ctx.fill()
      })

      const drawOrbit = (rx, ry, tilt, phase, alpha, dash = []) => {
        ctx.save(); ctx.rotate(tilt + Math.sin(t * .35 + phase) * .08)
        ctx.scale(1, ry / rx); ctx.rotate(phase)
        ctx.beginPath(); ctx.arc(0, 0, rx * pulse, 0, TAU)
        ctx.strokeStyle = color; ctx.globalAlpha = alpha + smoothed * .24; ctx.lineWidth = 1.35 + smoothed * 2; ctx.shadowBlur = 10 + smoothed * 16; ctx.shadowColor = color; ctx.setLineDash(dash); ctx.stroke(); ctx.restore()
      }
      drawOrbit(base * 1.27, base * .57, .24, rotation * .36, .38, [3, 8])
      drawOrbit(base * 1.18, base * .74, -1.06, -rotation * .25, .3, [1, 7])
      drawOrbit(base * 1.42, base * .3, -.55, rotation * .16, .25, [2, 12])
      drawOrbit(base * 1.08, base * .96, .8, -rotation * .42, .2, [1, 15])
      drawOrbit(base * .46, base * .2, -.72, rotation * .9, .62, [2, 5])

      sparks.forEach((p) => {
        const a = p.a + t * p.speed
        const rr = p.r * base * (1 + smoothed * .65)
        const x = Math.cos(a) * rr, y = p.y * base * .72 * (1 + smoothed * .3), z = Math.sin(a) * rr
        const q = project(x / base, y / base, z / base, 1)
        ctx.globalAlpha = Math.max(0, .08 + smoothed * .55 - Math.abs(p.y) * .04)
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(q.x, q.y, p.size * (1 + smoothed * 2), 0, TAU); ctx.fill()
      })

      ctx.globalAlpha = .9; ctx.shadowBlur = 28 + smoothed * 25; ctx.shadowColor = color
      const core = ctx.createRadialGradient(0, 0, 0, 0, 0, base * .26 * pulse)
      core.addColorStop(0, '#ffffff'); core.addColorStop(.16, color); core.addColorStop(.55, `${color}88`); core.addColorStop(1, `${color}00`)
      ctx.fillStyle = core; ctx.beginPath(); ctx.arc(0, 0, base * .3 * pulse, 0, TAU); ctx.fill()
      ctx.restore()
      raf = requestAnimationFrame(render)
    }
    render()
    return () => cancelAnimationFrame(raf)
  }, [state])

  const color = COLORS[state] || COLORS.idle
  const handlePointerDown = (event) => {
    draggingRef.current = true
    lastPointerRef.current = { x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const handlePointerMove = (event) => {
    if (!draggingRef.current) return
    const dx = event.clientX - lastPointerRef.current.x
    const dy = event.clientY - lastPointerRef.current.y
    rotationOffsetRef.current.yaw += dx * 0.018
    rotationOffsetRef.current.pitch = Math.max(-1.2, Math.min(1.2, rotationOffsetRef.current.pitch + dy * 0.014))
    lastPointerRef.current = { x: event.clientX, y: event.clientY }
  }
  const handlePointerUp = (event) => {
    draggingRef.current = false
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }
  return <div className={`core-container core-${state}`} style={{ '--core-color': color }}><canvas ref={canvasRef} className="core-canvas" aria-label="Audio reactive JARVIS 3D core" onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} /> </div>
}

