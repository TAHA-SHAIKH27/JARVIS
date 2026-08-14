import React, { useRef, useEffect } from 'react';

// Color map based on J.A.R.V.I.S. states
const STATE_COLORS = {
  idle:      'rgba(46, 214, 255, 1)',    // Cyan/Blue - mic off
  listening: 'rgba(46, 214, 255, 1)',    // Blue - mic on, waiting for wake word
  wake:      'rgba(94, 255, 155, 1)',    // Green - wake word detected!
  processing:'rgba(255, 138, 61,  1)',   // Amber - processing command
  speaking:  'rgba(94, 255, 155, 1)',    // Green - speaking response
};

export default function CoreSphere({ state = 'idle' }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');

    let animationFrameId;
    let rotationX = 0;
    let rotationY = 0;
    let time = 0;

    // Sphere parameters
    const numDots = 550;
    const baseRadius = 115;
    const dots = [];

    // Fibonacci sphere distribution for even dot spacing
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < numDots; i++) {
      const y = 1 - (i / (numDots - 1)) * 2;
      const radiusAtY = Math.sqrt(1 - y * y);
      const theta = phi * i;
      const x = Math.cos(theta) * radiusAtY;
      const z = Math.sin(theta) * radiusAtY;
      dots.push({ x, y, z });
    }

    const render = () => {
      // Read live audio level set by App.jsx (0–1)
      const audioLevel = Math.min(1, Math.max(0, window.jarvisAudioLevel || 0));

      const width  = canvas.width  = canvas.offsetWidth  * (window.devicePixelRatio || 1);
      const height = canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
      ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

      ctx.clearRect(0, 0, canvas.offsetWidth, canvas.offsetHeight);

      const centerX = canvas.offsetWidth  / 2;
      const centerY = canvas.offsetHeight / 2;

      time += 0.04;

      // Faster rotation when active
      const speedMult = (state === 'processing' || state === 'speaking' || state === 'wake') ? 2.5 : 1;
      rotationX += 0.002 * speedMult;
      rotationY += 0.004 * speedMult;

      const cosX = Math.cos(rotationX);
      const sinX = Math.sin(rotationX);
      const cosY = Math.cos(rotationY);
      const sinY = Math.sin(rotationY);

      const color = STATE_COLORS[state] || STATE_COLORS.idle;

      ctx.shadowBlur  = 14;
      ctx.shadowColor = color;
      ctx.fillStyle   = color;

      const projected = [];
      for (let i = 0; i < dots.length; i++) {
        let { x, y, z } = dots[i];

        // Rotate around X
        let xy = cosX * y - sinX * z;
        let xz = sinX * y + cosX * z;
        y = xy; z = xz;

        // Rotate around Y
        let yx = cosY * x + sinY * z;
        let yz = -sinY * x + cosY * z;
        x = yx; z = yz;

        // Audio ripple: wave travels along Y, amplitude driven by mic level
        const rippleAmp = audioLevel * 40;
        const ripple = Math.sin(time * 3 + y * 6) * rippleAmp;
        const radiusWithRipple = baseRadius + ripple + audioLevel * 12;

        // Perspective projection
        const scale = 260 / (260 - z * radiusWithRipple);
        const xProj = centerX + x * radiusWithRipple * scale;
        const yProj = centerY + y * radiusWithRipple * scale;

        // Depth fade
        const alpha = Math.max(0.1, (z + 1) / 2);

        projected.push({ x: xProj, y: yProj, scale, alpha, z });
      }

      // Sort back-to-front
      projected.sort((a, b) => a.z - b.z);

      for (const p of projected) {
        ctx.globalAlpha = p.alpha;
        ctx.beginPath();
        const dotSize = Math.max(0.5, 1.3 * p.scale + audioLevel * 2);
        ctx.arc(p.x, p.y, dotSize, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      animationFrameId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationFrameId);
  }, [state]);

  return (
    <div className="core-container">
      <div className="core-glow" style={{
        boxShadow: `0 0 80px ${STATE_COLORS[state]}`,
        backgroundColor: STATE_COLORS[state],
        opacity: 0.06,
      }} />
      <canvas
        ref={canvasRef}
        className="core-canvas"
        style={{ width: '100%', height: '100%', display: 'block', position: 'relative', zIndex: 2 }}
      />
    </div>
  );
}
