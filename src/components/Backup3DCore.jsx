import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';

/**
 * Creates a futuristic text label sprite using an offscreen canvas
 */
function createHUDLabel(title, subtitle, statusColor = '#00e5ff') {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 160;
  const ctx = canvas.getContext('2d');

  // Background panel with futuristic cut corners
  ctx.fillStyle = 'rgba(5, 12, 22, 0.85)';
  ctx.strokeStyle = statusColor;
  ctx.lineWidth = 2;

  ctx.beginPath();
  ctx.moveTo(16, 8);
  ctx.lineTo(496, 8);
  ctx.lineTo(504, 24);
  ctx.lineTo(504, 136);
  ctx.lineTo(488, 152);
  ctx.lineTo(8, 152);
  ctx.lineTo(8, 24);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Subtle accent line
  ctx.strokeStyle = statusColor;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(20, 68);
  ctx.lineTo(492, 68);
  ctx.stroke();

  // Status dot
  ctx.fillStyle = statusColor;
  ctx.beginPath();
  ctx.arc(36, 40, 6, 0, Math.PI * 2);
  ctx.fill();

  // Text title
  ctx.font = 'bold 24px "Space Grotesk", sans-serif';
  ctx.fillStyle = '#ffffff';
  ctx.fillText(title, 56, 48);

  // Subtitle / Telemetry
  ctx.font = '16px "DM Mono", monospace';
  ctx.fillStyle = 'rgba(180, 220, 240, 0.9)';
  ctx.fillText(subtitle, 24, 110);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const spriteMat = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.set(2.8, 0.88, 1);
  return { sprite, texture, canvas, update: (newSub, newColor) => {
    ctx.clearRect(0, 0, 512, 160);
    ctx.fillStyle = 'rgba(5, 12, 22, 0.85)';
    ctx.strokeStyle = newColor || statusColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(16, 8);
    ctx.lineTo(496, 8);
    ctx.lineTo(504, 24);
    ctx.lineTo(504, 136);
    ctx.lineTo(488, 152);
    ctx.lineTo(8, 152);
    ctx.lineTo(8, 24);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.strokeStyle = newColor || statusColor;
    ctx.beginPath();
    ctx.moveTo(20, 68);
    ctx.lineTo(492, 68);
    ctx.stroke();

    ctx.fillStyle = newColor || statusColor;
    ctx.beginPath();
    ctx.arc(36, 40, 6, 0, Math.PI * 2);
    ctx.fill();

    ctx.font = 'bold 24px "Space Grotesk", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(title, 56, 48);

    ctx.font = '16px "DM Mono", monospace';
    ctx.fillStyle = 'rgba(180, 220, 240, 0.9)';
    ctx.fillText(newSub, 24, 110);
    texture.needsUpdate = true;
  }};
}

export default function Backup3DCore({
  backupStatus,
  activeTransfer,
  onSelectNode,
  className = '',
}) {
  const containerRef = useRef(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [webGLSupported, setWebGLSupported] = useState(true);

  // Store mutable refs for values accessed in the animation loop
  const statusRef = useRef(backupStatus);
  const transferRef = useRef(activeTransfer);
  const onSelectNodeRef = useRef(onSelectNode);

  useEffect(() => {
    statusRef.current = backupStatus;
    transferRef.current = activeTransfer;
    onSelectNodeRef.current = onSelectNode;
  }, [backupStatus, activeTransfer, onSelectNode]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // WebGL support check
    try {
      const testCanvas = document.createElement('canvas');
      const gl = testCanvas.getContext('webgl') || testCanvas.getContext('experimental-webgl');
      if (!gl) {
        setWebGLSupported(false);
        return;
      }
    } catch (e) {
      setWebGLSupported(false);
      return;
    }

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 450;

    // 1. Scene & Fog
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x040810, 0.028);

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 0, 11.2);

    // 3. Renderer
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    container.appendChild(renderer.domElement);

    // 4. Lights
    const ambientLight = new THREE.AmbientLight(0x0d2847, 1.2);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0x43d9ff, 1.5);
    dirLight.position.set(5, 8, 6);
    scene.add(dirLight);

    const corePointLight = new THREE.PointLight(0x00e5ff, 2.8, 12);
    corePointLight.position.set(0, 0, 0);
    scene.add(corePointLight);

    // 5. Central Data Core
    const coreGroup = new THREE.Group();
    coreGroup.name = 'core';
    scene.add(coreGroup);

    // Inner Glowing Orb
    const innerCoreGeo = new THREE.SphereGeometry(0.9, 32, 32);
    const innerCoreMat = new THREE.MeshStandardMaterial({
      color: 0x011a33,
      emissive: 0x00e5ff,
      emissiveIntensity: 0.85,
      roughness: 0.2,
      metalness: 0.8,
    });
    const innerCoreMesh = new THREE.Mesh(innerCoreGeo, innerCoreMat);
    coreGroup.add(innerCoreMesh);

    // Outer Wireframe Holographic Sphere
    const wireGeo = new THREE.IcosahedronGeometry(1.35, 2);
    const wireMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.45,
    });
    const wireMesh = new THREE.Mesh(wireGeo, wireMat);
    coreGroup.add(wireMesh);

    // Holographic Core Halo
    const haloGeo = new THREE.SphereGeometry(1.5, 32, 32);
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.15,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
    });
    const haloMesh = new THREE.Mesh(haloGeo, haloMat);
    coreGroup.add(haloMesh);

    // Gimbal Orbital Rings
    const ringGeo1 = new THREE.TorusGeometry(1.85, 0.02, 16, 100);
    const ringMat1 = new THREE.MeshBasicMaterial({
      color: 0x43d9ff,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
    });
    const ring1 = new THREE.Mesh(ringGeo1, ringMat1);
    ring1.rotation.x = Math.PI / 3;
    ring1.rotation.y = Math.PI / 6;
    coreGroup.add(ring1);

    const ringGeo2 = new THREE.TorusGeometry(2.1, 0.018, 16, 100);
    const ringMat2 = new THREE.MeshBasicMaterial({
      color: 0x0284c7,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
    });
    const ring2 = new THREE.Mesh(ringGeo2, ringMat2);
    ring2.rotation.x = -Math.PI / 4;
    ring2.rotation.z = Math.PI / 5;
    coreGroup.add(ring2);

    // Orbiting File Data Particles around Core
    const particleCount = 45;
    const particlePositions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);
    const colorCyan = new THREE.Color(0x00e5ff);
    const colorGreen = new THREE.Color(0x72f0b0);
    const colorAmber = new THREE.Color(0xffb45c);

    for (let i = 0; i < particleCount; i++) {
      const radius = 2.3 + Math.random() * 0.8;
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI * 0.8;
      particlePositions[i * 3] = radius * Math.cos(theta) * Math.cos(phi);
      particlePositions[i * 3 + 1] = radius * Math.sin(phi);
      particlePositions[i * 3 + 2] = radius * Math.sin(theta) * Math.cos(phi);

      const c = i % 3 === 0 ? colorGreen : i % 5 === 0 ? colorAmber : colorCyan;
      particleColors[i * 3] = c.r;
      particleColors[i * 3 + 1] = c.g;
      particleColors[i * 3 + 2] = c.b;
    }

    const particlesGeo = new THREE.BufferGeometry();
    particlesGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    particlesGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));
    const particlesMat = new THREE.PointsMaterial({
      size: 0.07,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const orbitalParticles = new THREE.Points(particlesGeo, particlesMat);
    coreGroup.add(orbitalParticles);

    // Core Label
    const coreLabel = createHUDLabel('DATA CORE', 'SHA-256 INTEGRITY // AES GCM', '#00e5ff');
    coreLabel.sprite.position.set(0, -2.2, 0);
    coreLabel.sprite.scale.set(2.4, 0.75, 1);
    scene.add(coreLabel.sprite);

    // 6. Node 1: Windows Client Node (Left)
    const winGroup = new THREE.Group();
    winGroup.name = 'windows';
    winGroup.position.set(-4.3, 0.2, 0);
    scene.add(winGroup);

    // Laptop Base Slab
    const lapBaseGeo = new THREE.BoxGeometry(1.2, 0.08, 0.85);
    const nodeMat = new THREE.MeshStandardMaterial({
      color: 0x071526,
      emissive: 0x034b75,
      emissiveIntensity: 0.5,
      roughness: 0.3,
      metalness: 0.7,
    });
    const lapBase = new THREE.Mesh(lapBaseGeo, nodeMat);
    winGroup.add(lapBase);

    // Laptop Screen
    const lapScreenGeo = new THREE.BoxGeometry(1.15, 0.75, 0.05);
    const lapScreenMat = new THREE.MeshStandardMaterial({
      color: 0x031830,
      emissive: 0x00e5ff,
      emissiveIntensity: 0.4,
      roughness: 0.2,
      metalness: 0.8,
    });
    const lapScreen = new THREE.Mesh(lapScreenGeo, lapScreenMat);
    lapScreen.position.set(0, 0.42, -0.38);
    lapScreen.rotation.x = -0.18;
    winGroup.add(lapScreen);

    // Glowing screen display face
    const screenDisplayGeo = new THREE.PlaneGeometry(1.05, 0.65);
    const screenDisplayMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.65,
    });
    const screenDisplay = new THREE.Mesh(screenDisplayGeo, screenDisplayMat);
    screenDisplay.position.set(0, 0.42, -0.35);
    screenDisplay.rotation.x = -0.18;
    winGroup.add(screenDisplay);

    // Windows Pedestal Ring
    const winPedestalGeo = new THREE.TorusGeometry(1.1, 0.02, 16, 64);
    const winPedestalMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.5,
    });
    const winPedestal = new THREE.Mesh(winPedestalGeo, winPedestalMat);
    winPedestal.rotation.x = Math.PI / 2;
    winPedestal.position.y = -0.25;
    winGroup.add(winPedestal);

    // Windows Label Sprite
    const winLabel = createHUDLabel('WINDOWS 11', 'PRIMARY NODE // LOCAL FIRST', '#43d9ff');
    winLabel.sprite.position.set(-4.3, 1.35, 0);
    scene.add(winLabel.sprite);

    // 7. Node 2: Ubuntu Server Node (Right)
    const ubuGroup = new THREE.Group();
    ubuGroup.name = 'ubuntu';
    ubuGroup.position.set(4.3, 0.2, 0);
    scene.add(ubuGroup);

    // Server Tower Rack
    const serverGeo = new THREE.BoxGeometry(0.85, 1.4, 0.85);
    const serverMat = new THREE.MeshStandardMaterial({
      color: 0x091424,
      emissive: 0x0284c7,
      emissiveIntensity: 0.45,
      roughness: 0.35,
      metalness: 0.65,
    });
    const serverMesh = new THREE.Mesh(serverGeo, serverMat);
    serverMesh.position.y = 0.5;
    ubuGroup.add(serverMesh);

    // Server Rack LED Slits
    const ledCount = 5;
    const ledMeshes = [];
    for (let i = 0; i < ledCount; i++) {
      const ledGeo = new THREE.BoxGeometry(0.65, 0.05, 0.02);
      const ledMat = new THREE.MeshBasicMaterial({
        color: 0x00e5ff,
        transparent: true,
        opacity: 0.85,
      });
      const led = new THREE.Mesh(ledGeo, ledMat);
      led.position.set(0, 0.15 + i * 0.18, 0.43);
      ubuGroup.add(led);
      ledMeshes.push(led);
    }

    // Ubuntu Pedestal Ring
    const ubuPedestalGeo = new THREE.TorusGeometry(1.1, 0.02, 16, 64);
    const ubuPedestalMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.5,
    });
    const ubuPedestal = new THREE.Mesh(ubuPedestalGeo, ubuPedestalMat);
    ubuPedestal.rotation.x = Math.PI / 2;
    ubuPedestal.position.y = -0.25;
    ubuGroup.add(ubuPedestal);

    // Ubuntu Label Sprite
    const ubuLabel = createHUDLabel('UBUNTU SERVER', '192.168.1.110 // SSH:22', '#72f0b0');
    ubuLabel.sprite.position.set(4.3, 1.6, 0);
    scene.add(ubuLabel.sprite);

    // 8. Holographic Spline Connection Curve
    const p0 = new THREE.Vector3(-3.8, 0.2, 0);
    const p1 = new THREE.Vector3(-1.8, 1.2, 0.8);
    const p2 = new THREE.Vector3(1.8, 1.2, -0.8);
    const p3 = new THREE.Vector3(3.8, 0.2, 0);
    const connectionCurve = new THREE.CubicBezierCurve3(p0, p1, p2, p3);

    const curvePoints = connectionCurve.getPoints(80);
    const curveGeo = new THREE.BufferGeometry().setFromPoints(curvePoints);
    const curveMat = new THREE.LineBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.55,
      linewidth: 2,
    });
    const connectionLine = new THREE.Line(curveGeo, curveMat);
    scene.add(connectionLine);

    // Outer Glow Curve
    const glowTubeGeo = new THREE.TubeGeometry(connectionCurve, 64, 0.035, 8, false);
    const glowTubeMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.2,
      blending: THREE.AdditiveBlending,
    });
    const glowTube = new THREE.Mesh(glowTubeGeo, glowTubeMat);
    scene.add(glowTube);

    // 9. Transfer Data Packet Pulses along Curve
    const pulseCount = 6;
    const pulseMeshes = [];
    const pulseGeo = new THREE.SphereGeometry(0.09, 16, 16);
    const pulseMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
    });

    for (let i = 0; i < pulseCount; i++) {
      const pMesh = new THREE.Mesh(pulseGeo, pulseMat.clone());
      pMesh.visible = false;
      scene.add(pMesh);
      pulseMeshes.push({
        mesh: pMesh,
        offset: i / pulseCount,
      });
    }

    // 10. Background Cyber Grid Particles
    const bgCount = 180;
    const bgPositions = new Float32Array(bgCount * 3);
    for (let i = 0; i < bgCount; i++) {
      bgPositions[i * 3] = (Math.random() - 0.5) * 26;
      bgPositions[i * 3 + 1] = (Math.random() - 0.5) * 16;
      bgPositions[i * 3 + 2] = (Math.random() - 0.5) * 12 - 4;
    }
    const bgGeo = new THREE.BufferGeometry();
    bgGeo.setAttribute('position', new THREE.BufferAttribute(bgPositions, 3));
    const bgMat = new THREE.PointsMaterial({
      color: 0x0d3859,
      size: 0.06,
      transparent: true,
      opacity: 0.45,
    });
    const bgPoints = new THREE.Points(bgGeo, bgMat);
    scene.add(bgPoints);

    // 11. Interaction & Raycasting
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2(-999, -999);
    let isDragging = false;
    let prevMousePos = { x: 0, y: 0 };
    let targetYaw = 0;
    let targetPitch = 0;
    let currentYaw = 0;
    let currentPitch = 0;

    const interactiveObjects = [
      { mesh: lapScreen, name: 'windows' },
      { mesh: lapBase, name: 'windows' },
      { mesh: serverMesh, name: 'ubuntu' },
      { mesh: innerCoreMesh, name: 'core' },
      { mesh: wireMesh, name: 'core' },
    ];

    const onPointerMove = (e) => {
      const rect = container.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      if (isDragging) {
        const dx = e.clientX - prevMousePos.x;
        const dy = e.clientY - prevMousePos.y;
        targetYaw += dx * 0.005;
        targetPitch = Math.max(-0.4, Math.min(0.4, targetPitch + dy * 0.005));
        prevMousePos = { x: e.clientX, y: e.clientY };
      } else {
        // Gentle parallax
        targetYaw = mouse.x * 0.18;
        targetPitch = mouse.y * 0.12;
      }
    };

    const onPointerDown = (e) => {
      isDragging = true;
      prevMousePos = { x: e.clientX, y: e.clientY };
      container.style.cursor = 'grabbing';
    };

    const onPointerUp = (e) => {
      isDragging = false;
      container.style.cursor = 'default';

      // Check click raycast
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(interactiveObjects.map((o) => o.mesh));
      if (intersects.length > 0) {
        const hit = interactiveObjects.find((o) => o.mesh === intersects[0].object);
        if (hit && onSelectNodeRef.current) {
          onSelectNodeRef.current(hit.name);
        }
      }
    };

    container.addEventListener('pointermove', onPointerMove);
    container.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointerup', onPointerUp);

    // 12. Animation Loop
    let animId;
    let clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const elapsed = clock.getElapsedTime();

      // Camera lerp
      currentYaw += (targetYaw - currentYaw) * 0.05;
      currentPitch += (targetPitch - currentPitch) * 0.05;
      camera.position.x = Math.sin(currentYaw) * 11.2;
      camera.position.z = Math.cos(currentYaw) * 11.2;
      camera.position.y = currentPitch * 4.0;
      camera.lookAt(0, 0, 0);

      // Core rotation
      coreGroup.rotation.y = elapsed * 0.25;
      wireMesh.rotation.x = elapsed * 0.15;
      wireMesh.rotation.z = elapsed * 0.12;
      ring1.rotation.z = elapsed * 0.4;
      ring2.rotation.z = -elapsed * 0.35;
      orbitalParticles.rotation.y = -elapsed * 0.2;

      // Status-dependent visual dynamics
      const status = statusRef.current;
      const isReachable = status?.server?.reachable ?? true;
      const isPaused = status?.paused ?? false;
      const uploadingCount = status?.counts?.uploading || 0;
      const pendingCount = (status?.counts?.pending || 0) + (status?.counts?.retrying || 0);
      const failedCount = status?.counts?.failed || 0;
      const isTransferring = uploadingCount > 0 || !!transferRef.current;

      // Node subtle float
      winGroup.position.y = 0.2 + Math.sin(elapsed * 1.5) * 0.06;
      ubuGroup.position.y = 0.2 + Math.cos(elapsed * 1.5) * 0.06;
      winPedestal.rotation.z = elapsed * 0.5;
      ubuPedestal.rotation.z = -elapsed * 0.5;

      // Server LED blink
      ledMeshes.forEach((led, idx) => {
        if (!isReachable) {
          led.material.color.setHex(0xff4455);
          led.material.opacity = Math.sin(elapsed * 4 + idx) > 0 ? 0.7 : 0.1;
        } else if (isTransferring) {
          led.material.color.setHex(0x72f0b0);
          led.material.opacity = Math.sin(elapsed * 8 + idx * 1.5) > 0 ? 0.95 : 0.2;
        } else {
          led.material.color.setHex(0x00e5ff);
          led.material.opacity = (Math.sin(elapsed * 2 + idx) + 1) * 0.35 + 0.2;
        }
      });

      // Update Connection Line appearance
      if (!isReachable) {
        curveMat.color.setHex(0xff5555);
        curveMat.opacity = 0.35;
        glowTubeMat.color.setHex(0xff3344);
        glowTubeMat.opacity = 0.08;
      } else if (isTransferring) {
        curveMat.color.setHex(0x72f0b0);
        curveMat.opacity = 0.85;
        glowTubeMat.color.setHex(0x72f0b0);
        glowTubeMat.opacity = 0.32;
      } else {
        curveMat.color.setHex(0x00e5ff);
        curveMat.opacity = 0.5;
        glowTubeMat.color.setHex(0x00e5ff);
        glowTubeMat.opacity = 0.18;
      }

      // Update transfer pulses
      pulseMeshes.forEach((p, idx) => {
        if (!isReachable || isPaused) {
          p.mesh.visible = false;
        } else if (isTransferring || pendingCount > 0) {
          p.mesh.visible = true;
          const speed = isTransferring ? 0.75 : 0.22;
          const t = (elapsed * speed + p.offset) % 1.0;
          const pos = connectionCurve.getPoint(t);
          p.mesh.position.copy(pos);
          p.mesh.material.color.setHex(isTransferring ? 0x72f0b0 : 0x00e5ff);
          p.mesh.scale.setScalar(isTransferring ? 1.3 : 0.95);
        } else {
          // Heartbeat single pulse
          if (idx === 0) {
            p.mesh.visible = true;
            const t = (elapsed * 0.18) % 1.0;
            const pos = connectionCurve.getPoint(t);
            p.mesh.position.copy(pos);
            p.mesh.material.color.setHex(0x00e5ff);
            p.mesh.scale.setScalar(0.8);
          } else {
            p.mesh.visible = false;
          }
        }
      });

      // Core point light pulse
      corePointLight.intensity = 2.4 + Math.sin(elapsed * 3) * 0.6;
      if (failedCount > 0) {
        wireMat.color.setHex(0xffb45c);
      } else if (isTransferring) {
        wireMat.color.setHex(0x72f0b0);
      } else {
        wireMat.color.setHex(0x38bdf8);
      }

      // Raycast hover check
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(interactiveObjects.map((o) => o.mesh));
      if (intersects.length > 0) {
        const hit = interactiveObjects.find((o) => o.mesh === intersects[0].object);
        if (hit) {
          container.style.cursor = 'pointer';
          setHoveredNode(hit.name);
        }
      } else {
        if (!isDragging) container.style.cursor = 'default';
        setHoveredNode(null);
      }

      renderer.render(scene, camera);
    };

    animate();

    // 13. Resize Handler
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || 800;
      const h = container.clientHeight || 450;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);

    // 14. Cleanup
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      container.removeEventListener('pointermove', onPointerMove);
      container.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);

      // Dispose scene
      innerCoreGeo.dispose();
      innerCoreMat.dispose();
      wireGeo.dispose();
      wireMat.dispose();
      haloGeo.dispose();
      haloMat.dispose();
      ringGeo1.dispose();
      ringMat1.dispose();
      ringGeo2.dispose();
      ringMat2.dispose();
      particlesGeo.dispose();
      particlesMat.dispose();
      lapBaseGeo.dispose();
      nodeMat.dispose();
      lapScreenGeo.dispose();
      lapScreenMat.dispose();
      screenDisplayGeo.dispose();
      screenDisplayMat.dispose();
      winPedestalGeo.dispose();
      winPedestalMat.dispose();
      serverGeo.dispose();
      serverMat.dispose();
      ubuPedestalGeo.dispose();
      ubuPedestalMat.dispose();
      curveGeo.dispose();
      curveMat.dispose();
      glowTubeGeo.dispose();
      glowTubeMat.dispose();
      pulseGeo.dispose();
      pulseMat.dispose();
      bgGeo.dispose();
      bgMat.dispose();

      coreLabel.texture.dispose();
      coreLabel.sprite.material.dispose();
      winLabel.texture.dispose();
      winLabel.sprite.material.dispose();
      ubuLabel.texture.dispose();
      ubuLabel.sprite.material.dispose();

      renderer.dispose();
      if (renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  if (!webGLSupported) {
    return (
      <div className={`backup-3d-fallback ${className}`} style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '3rem',
        background: 'rgba(5, 12, 22, 0.8)',
        border: '1px solid rgba(67, 217, 255, 0.2)',
        borderRadius: '12px',
        color: '#dcecf4',
        textAlign: 'center',
        minHeight: '380px',
      }}>
        <div style={{ fontSize: '32px', marginBottom: '12px' }}>⚙️</div>
        <h3 style={{ fontFamily: 'Space Grotesk', fontSize: '18px', color: '#43d9ff', marginBottom: '8px' }}>
          3D HOLOGRAPHIC CORE — 2D FALLBACK ACTIVE
        </h3>
        <p style={{ fontFamily: 'DM Mono', fontSize: '13px', opacity: 0.8, maxWidth: '440px' }}>
          WebGL hardware acceleration is unavailable. Data telemetry, real-time queues, file browser, and restoration tools remain 100% functional.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`backup-3d-container ${className}`}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        minHeight: '380px',
        overflow: 'hidden',
        userSelect: 'none',
      }}
      aria-label="JARVIS 3D Backup Core Visualization"
    >
      {/* Telemetry Overlays */}
      <div style={{
        position: 'absolute',
        top: '36px',
        left: '16px',
        pointerEvents: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '11px',
          fontFamily: 'var(--font-mono, monospace)',
          letterSpacing: '1px',
          color: 'var(--cyan, #43d9ff)',
        }}>
          <span style={{
            display: 'inline-block',
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: backupStatus?.server?.reachable ? '#72f0b0' : '#ff6275',
            boxShadow: `0 0 10px ${backupStatus?.server?.reachable ? '#72f0b0' : '#ff6275'}`,
          }} />
          <span>REAL-TIME 3D TELEMETRY</span>
        </div>
        <div style={{
          fontSize: '10px',
          fontFamily: 'var(--font-mono, monospace)',
          color: 'rgba(255,255,255,0.5)',
        }}>
          DRAG TO ORBIT · HOVER / CLICK NODES TO INSPECT
        </div>
      </div>

      {hoveredNode && (
        <div style={{
          position: 'absolute',
          bottom: '16px',
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(5, 12, 22, 0.92)',
          border: '1px solid rgba(67, 217, 255, 0.4)',
          borderRadius: '6px',
          padding: '6px 16px',
          fontSize: '11px',
          fontFamily: 'var(--font-mono, monospace)',
          color: '#43d9ff',
          letterSpacing: '1px',
          pointerEvents: 'none',
          boxShadow: '0 4px 20px rgba(0, 229, 255, 0.2)',
          backdropFilter: 'blur(8px)',
        }}>
          CLICK TO INSPECT {hoveredNode.toUpperCase()} DETAILS
        </div>
      )}
    </div>
  );
}
