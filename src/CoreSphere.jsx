import React, { useEffect, useRef } from 'react'

const COLORS = { idle: '#43d9ff', listening: '#54a8ff', wake: '#72f0b0', processing: '#ffb45c', speaking: '#72f0b0' }
const AGENT_COLORS = { idle: '#ffe04f', listening: '#fff06a', wake: '#fff7a8', processing: '#ffd32f', speaking: '#fff06a' }
const TAU = Math.PI * 2

function seeded(i) {
  const x = Math.sin(i * 91.733) * 43758.5453
  return x - Math.floor(x)
}

export default function CoreSphere({ state = 'idle', agentMode = false, startupPhase = null }) {
  const canvasRef = useRef(null)
  const rotationOffsetRef = useRef({ yaw: 0, pitch: 0 })
  const zoomRef = useRef(1.0)
  const draggingRef = useRef(false)
  const lastPointerRef = useRef({ x: 0, y: 0 })

  // Ref tracking animation time since startup mount
  const startupStartTimeRef = useRef(Date.now())

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25)

    // Shell particles with randomized origin directions far outside viewport for smooth convergence
    const shell = Array.from({ length: 220 }, (_, i) => {
      const y = 1 - (i / 219) * 2
      const r = Math.sqrt(Math.max(0, 1 - y * y))
      const a = Math.PI * (3 - Math.sqrt(5)) * i
      // Random outer space origins (far offscreen in 3D space)
      const angle = seeded(i + 300) * TAU
      const dist = 6.5 + seeded(i + 500) * 8.0 // Fly in from offscreen boundaries
      const origX = Math.cos(angle) * dist
      const origY = (seeded(i + 800) * 2 - 1) * dist
      const origZ = Math.sin(angle) * dist
      return { 
        targetX: Math.cos(a) * r, 
        targetY: y, 
        targetZ: Math.sin(a) * r, 
        origX, origY, origZ,
        delay: seeded(i + 100) * 1.5, // staggered arrival delay
        seed: seeded(i) 
      }
    })

    const sparks = Array.from({ length: 40 }, (_, i) => ({
      a: seeded(i + 700) * TAU, y: seeded(i + 900) * 2 - 1, r: .72 + seeded(i + 1100) * .62, speed: .3 + seeded(i + 1300) * 1.2, size: .5 + seeded(i + 1500) * 1.5
    }))

    let raf = 0
    let t = 0
    let smoothed = 0
    let lastFrame = 0

    const render = (now = 0) => {
      if (now - lastFrame < 15) {
        raf = requestAnimationFrame(render)
        return
      }
      lastFrame = now
      const w = canvas.offsetWidth || 450
      const h = canvas.offsetHeight || 450
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const input = Math.min(1, Math.max(0, Number(window.jarvisAudioLevel) || 0))
      const fallback = .08 + (Math.sin(t * 3.2) * .5 + .5) * .04
      smoothed += ((input > .015 ? input : fallback) - smoothed) * .14
      const color = (agentMode ? AGENT_COLORS : COLORS)[state] || (agentMode ? AGENT_COLORS : COLORS).idle

      // Time elapsed since mount (seconds)
      const elapsedSec = (Date.now() - startupStartTimeRef.current) / 1000
      const isStartupActive = startupPhase && startupPhase !== 'ONLINE';

      // Scale factors for sequential reveal:
      // Phase 1 (0s-1.0s): Core glows first
      // Phase 2 (0.6s-4.0s): Dots fly in smoothly from outside screen to form sphere
      // Phase 3 (3.4s+): Orbital rings emerge
      const dotsProgress = isStartupActive ? Math.max(0, Math.min(1, (elapsedSec - 0.6) / 3.4)) : 1.0;
      const orbitProgress = isStartupActive ? Math.max(0, Math.min(1, (elapsedSec - 3.4) / 1.6)) : 1.0;

      const userZoom = zoomRef.current
      const cx = w / 2, cy = h / 2
      const base = Math.min(w, h) * .42 * userZoom
      const pulse = 1 + smoothed * .24 + Math.sin(t * 4) * smoothed * .025
      const orbitPulse = state === 'listening' ? .88 + smoothed * .1 : pulse
      const rotation = t * (state === 'processing' ? 1.9 : .68) + rotationOffsetRef.current.yaw
      const pitch = rotationOffsetRef.current.pitch + Math.sin(t * .35) * .12
      t += state === 'idle' ? .022 : .04

      ctx.save()
      ctx.translate(cx, cy)
      ctx.globalCompositeOperation = 'lighter'

      // 1. Inner Glowy Core Core (Comes FIRST)
      const coreAlpha = isStartupActive ? Math.min(1, elapsedSec * 1.5) : 0.95;
      ctx.globalAlpha = coreAlpha;
      const core = ctx.createRadialGradient(0, 0, 0, 0, 0, base * .28 * pulse)
      core.addColorStop(0, '#ffffff'); core.addColorStop(.16, color); core.addColorStop(.55, `${color}88`); core.addColorStop(1, `${color}00`)
      ctx.fillStyle = core; ctx.beginPath(); ctx.arc(0, 0, base * .32 * pulse, 0, TAU); ctx.fill()

      // Outer aura glow
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, base * 1.5 * pulse)
      glow.addColorStop(0, `${color}55`); glow.addColorStop(.34, `${color}18`); glow.addColorStop(1, `${color}00`)
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(0, 0, base * 1.5 * pulse, 0, TAU); ctx.fill()

      const cosRot = Math.cos(rotation), sinRot = Math.sin(rotation)
      const cosPit = Math.cos(pitch), sinPit = Math.sin(pitch)

      // 2. Fibonacci Dot Sphere (Fly in smoothly from outside the screen to form sphere)
      if (dotsProgress > 0) {
        ctx.fillStyle = color
        shell.forEach((p) => {
          const rawProg = dotsProgress >= 1 ? 1 : Math.max(0, Math.min(1, (dotsProgress * 1.4) - p.delay * 0.3));
          // Ultra-smooth quintic ease-out curve (1 - (1-x)^5) for natural screen fly-in
          const easeProg = dotsProgress >= 1 ? 1 : 1 - Math.pow(1 - rawProg, 5);

          if (easeProg <= 0.001) return;

          const currX = dotsProgress >= 1 ? p.targetX : p.origX * (1 - easeProg) + p.targetX * easeProg;
          const currY = dotsProgress >= 1 ? p.targetY : p.origY * (1 - easeProg) + p.targetY * easeProg;
          const currZ = dotsProgress >= 1 ? p.targetZ : p.origZ * (1 - easeProg) + p.targetZ * easeProg;

          const wobble = Math.sin(t * 3.5 + currY * 11 + p.seed * 8) * smoothed * .1
          const rr = 1 + wobble
          const x0 = currX * rr, y0 = currY * rr, z0 = currZ * rr
          const x1 = x0 * cosRot - z0 * sinRot
          const z1 = x0 * sinRot + z0 * cosRot
          const y = y0 * cosPit - z1 * sinPit
          const z = y0 * sinPit + z1 * cosPit
          const perspective = 1 / (1.85 - z * .7)
          const px = x1 * base * pulse * perspective
          const py = y * base * pulse * perspective
          const front = (z + 1) / 2

          ctx.globalAlpha = (0.15 + front * 0.75) * Math.min(1, easeProg * 1.5);
          ctx.beginPath(); ctx.arc(px, py, .5 + front * 1.4 + smoothed * 2.2, 0, TAU); ctx.fill()
        })
      }

      // 3. Orbitals (Fade & Scale in third)
      if (orbitProgress > 0) {
        const drawOrbit = (rx, ry, tilt, phase, alpha, dash = []) => {
          ctx.save(); ctx.rotate(tilt + Math.sin(t * .35 + phase) * .08)
          ctx.scale(1, ry / rx); ctx.rotate(phase)
          ctx.beginPath(); ctx.arc(0, 0, rx * orbitPulse * (0.4 + orbitProgress * 0.6), 0, TAU)
          ctx.strokeStyle = color; ctx.globalAlpha = (alpha + smoothed * .24) * orbitProgress; ctx.lineWidth = 1.35 + smoothed * 2; ctx.setLineDash(dash); ctx.stroke(); ctx.restore()
        }
        drawOrbit(base * 1.27, base * .57, .24, rotation * .36, .38, [3, 8])
        drawOrbit(base * 1.18, base * .74, -1.06, -rotation * .25, .3, [1, 7])
        drawOrbit(base * 1.42, base * .3, -.55, rotation * .16, .25, [2, 12])
        drawOrbit(base * 1.08, base * .96, .8, -rotation * .42, .2, [1, 15])
        drawOrbit(base * .46, base * .2, -.72, rotation * .9, .62, [2, 5])

        ctx.fillStyle = color
        sparks.forEach((p) => {
          const a = p.a + t * p.speed
          const rr = p.r * base * (1 + smoothed * .65)
          const x = Math.cos(a) * rr, y = p.y * base * .72 * (1 + smoothed * .3), z = Math.sin(a) * rr
          const perspective = 1 / (1.85 - (z / base) * .7)
          const px = x * perspective, py = y * perspective
          ctx.globalAlpha = Math.max(0, .1 + smoothed * .55 - Math.abs(p.y) * .04) * orbitProgress
          ctx.beginPath(); ctx.arc(px, py, p.size * (1 + smoothed * 2), 0, TAU); ctx.fill()
        })
      }

      ctx.restore()
      raf = requestAnimationFrame(render)
    }
    render()
    return () => cancelAnimationFrame(raf)
  }, [state, agentMode, startupPhase])

  const color = (agentMode ? AGENT_COLORS : COLORS)[state] || (agentMode ? AGENT_COLORS : COLORS).idle
  
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
  
  // Mouse wheel listener for zooming the sphere enormously or making it smaller
  const handleWheel = (event) => {
    event.preventDefault()
    const zoomDelta = event.deltaY < 0 ? 0.12 : -0.12
    zoomRef.current = Math.max(0.4, Math.min(3.8, zoomRef.current + zoomDelta))
  }

  return (
    <div className={`core-container core-${state}`} style={{ '--core-color': color }}>
      <canvas
        ref={canvasRef}
        className="core-canvas"
        aria-label="Audio reactive JARVIS 3D core"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
      />
    </div>
  )
}

