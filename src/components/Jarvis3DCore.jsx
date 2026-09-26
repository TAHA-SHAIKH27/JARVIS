import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

const THEME_COLORS = {
  normal: {
    coreGlow: 0x00e5ff,
    coreDeep: 0x011328,
    dots: 0x38bdf8,
    orbitals: [0x00e5ff, 0x0284c7, 0x38bdf8],
    particles: 0x0284c7,
    grid: 0x03284c,
  },
  agent: {
    coreGlow: 0xffd32f,
    coreDeep: 0x221a02,
    dots: 0xffe04f,
    orbitals: [0xffd32f, 0xf59e0b, 0xfef08a],
    particles: 0xf59e0b,
    grid: 0x3d3204,
  },
};

/**
 * Generate Fibonacci sphere points
 */
function createFibonacciSpherePoints(samples = 480, radius = 2.5) {
  const positions = new Float32Array(samples * 3);
  const reveals = new Float32Array(samples);
  const phi = Math.PI * (3 - Math.sqrt(5)); // Golden angle

  for (let i = 0; i < samples; i++) {
    const y = 1 - (i / (samples - 1)) * 2;
    const radiusAtY = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = phi * i;

    positions[i * 3] = Math.cos(theta) * radiusAtY * radius;
    positions[i * 3 + 1] = y * radius;
    positions[i * 3 + 2] = Math.sin(theta) * radiusAtY * radius;

    // Organic reveal order: clustered by height and angle
    reveals[i] = (y + 1) * 0.4 + ((theta % (Math.PI * 2)) / (Math.PI * 2)) * 0.2;
  }
  return { positions, reveals };
}

export default function Jarvis3DCore({
  phase = 'ONLINE', // BOOT | CORE_INITIALIZING | CORE_ACTIVE | SPHERE_INITIALIZING | ORBITALS_INITIALIZING | UI_ASSEMBLY | ONLINE
  isDocked = false,
  state = 'idle',
  agentMode = false,
  onCoreReady,
}) {
  const containerRef = useRef(null);
  const phaseRef = useRef(phase);
  const isDockedRef = useRef(isDocked);
  const stateRef = useRef(state);
  const agentModeRef = useRef(agentMode);

  useEffect(() => {
    phaseRef.current = phase;
    isDockedRef.current = isDocked;
    stateRef.current = state;
    agentModeRef.current = agentMode;
  }, [phase, isDocked, state, agentMode]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || 400;
    const height = container.clientHeight || 400;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x020713, 0.035);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 0, isDockedRef.current ? 8.2 : 9.5);

    // 2. Renderer
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    // Color theme
    const theme = agentModeRef.current ? THEME_COLORS.agent : THEME_COLORS.normal;

    // 3. Central Core Sphere Group
    const coreGroup = new THREE.Group();
    scene.add(coreGroup);

    // 3a. Inner Dark Glowing Sphere
    const coreGeo = new THREE.SphereGeometry(0.88, 36, 36);
    const coreMat = new THREE.MeshStandardMaterial({
      color: theme.coreDeep,
      emissive: theme.coreGlow,
      emissiveIntensity: 0.7,
      roughness: 0.18,
      metalness: 0.85,
      wireframe: false,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    coreGroup.add(coreMesh);

    // 3b. Outer Core Aura (Additive Glow Shell)
    const glowGeo = new THREE.SphereGeometry(1.02, 32, 32);
    const glowMat = new THREE.MeshBasicMaterial({
      color: theme.coreGlow,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
    });
    const glowMesh = new THREE.Mesh(glowGeo, glowMat);
    coreGroup.add(glowMesh);

    // 4. Progressive Dotted Sphere
    const { positions: dotPositions, reveals: dotReveals } = createFibonacciSpherePoints(480, 2.35);
    const dotsGeo = new THREE.BufferGeometry();
    dotsGeo.setAttribute('position', new THREE.BufferAttribute(dotPositions, 3));
    dotsGeo.setAttribute('reveal', new THREE.BufferAttribute(dotReveals, 1));

    // Custom shader material for individual dot progressive materialization
    const dotsMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uProgress: { value: 0 },
        uColor: { value: new THREE.Color(theme.dots) },
        uPulse: { value: 1.0 },
      },
      vertexShader: `
        attribute float reveal;
        uniform float uProgress;
        uniform float uTime;
        uniform float uPulse;
        varying float vAlpha;
        void main() {
          float distFromReveal = uProgress - reveal;
          vAlpha = clamp(distFromReveal * 3.5, 0.0, 1.0);
          
          vec3 pos = position * uPulse;
          // subtle organic breath
          pos += normalize(position) * sin(uTime * 2.0 + position.y * 3.0) * 0.04;
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = (2.8 + vAlpha * 2.2) * (18.0 / -mvPosition.z);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        varying float vAlpha;
        void main() {
          vec2 coord = gl_PointCoord - vec2(0.5);
          float dist = length(coord);
          if (dist > 0.5) discard;
          float strength = 1.0 - smoothstep(0.0, 0.5, dist);
          gl_FragColor = vec4(uColor, strength * vAlpha * 0.85);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const dotsMesh = new THREE.Points(dotsGeo, dotsMat);
    coreGroup.add(dotsMesh);

    // 5. Three Elliptical Orbital Paths
    const orbitalParams = [
      { a: 3.4, b: 2.1, tiltX: 0.42, tiltY: 0.15, tiltZ: 0.28, rotSpeed: 0.45, color: theme.orbitals[0] },
      { a: 3.9, b: 2.6, tiltX: -0.65, tiltY: 0.35, tiltZ: -0.22, rotSpeed: -0.38, color: theme.orbitals[1] },
      { a: 3.6, b: 3.1, tiltX: 0.25, tiltY: -0.72, tiltZ: 0.55, rotSpeed: 0.40, color: theme.orbitals[2] },
    ];

    const orbitalSystems = orbitalParams.map((p, idx) => {
      const segments = 160;
      const points = [];
      for (let i = 0; i <= segments; i++) {
        const theta = (i / segments) * Math.PI * 2;
        points.push(new THREE.Vector3(Math.cos(theta) * p.a, Math.sin(theta) * p.b, 0));
      }
      const geo = new THREE.BufferGeometry().setFromPoints(points);
      
      const mat = new THREE.LineBasicMaterial({
        color: p.color,
        transparent: true,
        opacity: 0.0,
        blending: THREE.AdditiveBlending,
        linewidth: 1.5,
      });

      const line = new THREE.Line(geo, mat);
      line.rotation.set(p.tiltX, p.tiltY, p.tiltZ);
      coreGroup.add(line);

      // Orbital head tracer beacon
      const headGeo = new THREE.SphereGeometry(0.07, 12, 12);
      const headMat = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.0,
        blending: THREE.AdditiveBlending,
      });
      const headMesh = new THREE.Mesh(headGeo, headMat);
      line.add(headMesh);

      return {
        line,
        geo,
        mat,
        headMesh,
        segments,
        params: p,
        progress: 0.0,
        isTraced: false,
      };
    });

    // 6. Background Subtle Particle Field
    const bgParticleCount = 180;
    const bgPositions = new Float32Array(bgParticleCount * 3);
    for (let i = 0; i < bgParticleCount; i++) {
      bgPositions[i * 3] = (Math.random() - 0.5) * 24;
      bgPositions[i * 3 + 1] = (Math.random() - 0.5) * 18;
      bgPositions[i * 3 + 2] = (Math.random() - 0.5) * 14 - 4;
    }
    const bgGeo = new THREE.BufferGeometry();
    bgGeo.setAttribute('position', new THREE.BufferAttribute(bgPositions, 3));
    const bgMat = new THREE.PointsMaterial({
      color: theme.particles,
      size: 0.06,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending,
    });
    const bgParticles = new THREE.Points(bgGeo, bgMat);
    scene.add(bgParticles);

    // 7. Ambient & Subtle Directional Lighting
    const ambientLight = new THREE.AmbientLight(0x020713, 1.2);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(theme.coreGlow, 2.5, 12, 1.8);
    pointLight.position.set(0, 0, 0);
    scene.add(pointLight);

    // Drag / Parallax Interaction
    let mouseX = 0;
    let mouseY = 0;
    let targetYaw = 0;
    let targetPitch = 0;
    let currentYaw = 0;
    let currentPitch = 0;
    let isDragging = false;
    let lastPointerX = 0;
    let lastPointerY = 0;

    const onPointerDown = (e) => {
      isDragging = true;
      lastPointerX = e.clientX;
      lastPointerY = e.clientY;
    };

    const onPointerMove = (e) => {
      if (isDragging) {
        const dx = e.clientX - lastPointerX;
        const dy = e.clientY - lastPointerY;
        targetYaw += dx * 0.008;
        targetPitch = Math.max(-0.8, Math.min(0.8, targetPitch + dy * 0.008));
        lastPointerX = e.clientX;
        lastPointerY = e.clientY;
      } else {
        // Subtle mouse parallax
        const rect = container.getBoundingClientRect();
        mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
      }
    };

    const onPointerUp = () => {
      isDragging = false;
    };

    container.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    // 8. Animation Loop
    let animId = 0;
    let clock = new THREE.Clock();
    let coreScale = 0.001;
    let dotProgress = 0.0;
    let smoothedAudio = 0.0;

    const animate = () => {
      animId = requestAnimationFrame(animate);

      const delta = Math.min(clock.getDelta(), 0.1);
      const elapsed = clock.getElapsedTime();
      const currentPhase = phaseRef.current;
      const docked = isDockedRef.current;

      // Audio level reactivity from window.jarvisAudioLevel
      const rawAudio = Math.min(1.0, Math.max(0, Number(window.jarvisAudioLevel) || 0));
      smoothedAudio += (rawAudio - smoothedAudio) * 0.15;
      const pulseFactor = 1.0 + smoothedAudio * 0.28 + Math.sin(elapsed * 3.5) * 0.025;

      // Dynamic Camera Position based on Docked status
      const targetCamZ = docked ? 8.2 : 9.5;
      camera.position.z += (targetCamZ - camera.position.z) * 0.08;

      // Core Scale & Appearance according to Phase
      if (currentPhase === 'BOOT') {
        coreScale += (0.001 - coreScale) * 0.1;
      } else if (currentPhase === 'CORE_INITIALIZING' || currentPhase === 'CORE_ACTIVE') {
        coreScale += (1.0 - coreScale) * 0.06;
      } else {
        coreScale += (1.0 - coreScale) * 0.1;
      }
      coreGroup.scale.set(coreScale * pulseFactor, coreScale * pulseFactor, coreScale * pulseFactor);

      // Core emissive pulsing
      coreMat.emissiveIntensity = 0.6 + smoothedAudio * 1.2 + Math.sin(elapsed * 2.8) * 0.15;
      glowMat.opacity = (0.2 + smoothedAudio * 0.4) * Math.min(1.0, coreScale);

      // Dotted Sphere Progressive Reveal
      if (['SPHERE_INITIALIZING', 'ORBITALS_INITIALIZING', 'UI_ASSEMBLY', 'AUDIT_RUNNING', 'SYSTEM_VERIFYING', 'SYSTEM_READY', 'BRIEFING', 'ONLINE'].includes(currentPhase)) {
        dotProgress = Math.min(1.0, dotProgress + delta * 0.65);
      } else if (currentPhase === 'BOOT') {
        dotProgress = 0.0;
      }
      dotsMat.uniforms.uTime.value = elapsed;
      dotsMat.uniforms.uProgress.value = dotProgress;
      dotsMat.uniforms.uPulse.value = 1.0 + smoothedAudio * 0.12;

      // Orbital Tracing and Persistent Rotation
      const shouldTraceOrbitals = ['ORBITALS_INITIALIZING', 'UI_ASSEMBLY', 'AUDIT_RUNNING', 'SYSTEM_VERIFYING', 'SYSTEM_READY', 'BRIEFING', 'ONLINE'].includes(currentPhase);

      orbitalSystems.forEach((orb, i) => {
        if (shouldTraceOrbitals) {
          // Staggered tracing onset
          const delay = i * 0.35;
          const traceSpeed = 0.68;
          if (elapsed > delay) {
            orb.progress = Math.min(1.0, orb.progress + delta * traceSpeed);
          }
          if (orb.progress >= 1.0) {
            orb.isTraced = true;
          }
        }

        if (orb.progress > 0.0) {
          const drawCount = Math.floor(orb.progress * orb.segments);
          orb.geo.setDrawRange(0, drawCount + 1);
          orb.mat.opacity = Math.min(0.75, orb.progress * 0.85);

          // Update orbital head position
          const angle = orb.progress * Math.PI * 2;
          orb.headMesh.position.set(Math.cos(angle) * orb.params.a, Math.sin(angle) * orb.params.b, 0);
          orb.headMesh.material.opacity = orb.isTraced ? (Math.sin(elapsed * 4 + i) * 0.3 + 0.5) : 0.95;
        }

        // Persistent continuous 3D rotation of completed orbitals
        if (orb.progress > 0) {
          orb.line.rotation.z += orb.params.rotSpeed * delta * (stateRef.current === 'processing' ? 1.8 : 0.85);
        }
      });

      // Smooth Rotation & Parallax
      currentYaw += (targetYaw + mouseX * 0.3 - currentYaw) * 0.08;
      currentPitch += (targetPitch - mouseY * 0.25 - currentPitch) * 0.08;

      coreGroup.rotation.y = currentYaw + elapsed * 0.12;
      coreGroup.rotation.x = currentPitch;

      // Slow background particle drift
      bgParticles.rotation.y = elapsed * 0.02;
      bgParticles.rotation.x = Math.sin(elapsed * 0.015) * 0.05;

      renderer.render(scene, camera);
    };

    animate();

    // 9. Resize Handler
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || 400;
      const h = container.clientHeight || 400;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);

    // 10. Cleanup
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      container.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);

      coreGeo.dispose();
      coreMat.dispose();
      glowGeo.dispose();
      glowMat.dispose();
      dotsGeo.dispose();
      dotsMat.dispose();
      bgGeo.dispose();
      bgMat.dispose();

      orbitalSystems.forEach((orb) => {
        orb.geo.dispose();
        orb.mat.dispose();
        orb.headMesh.geometry.dispose();
        orb.headMesh.material.dispose();
      });

      renderer.dispose();
      if (renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`jarvis-3d-core ${isDocked ? 'is-docked' : 'is-cinematic'}`}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        overflow: 'hidden',
        cursor: 'grab',
      }}
      aria-label="JARVIS 3D WebGL Core"
    />
  );
}
