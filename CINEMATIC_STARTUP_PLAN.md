# J.A.R.V.I.S. Cinematic 3D Startup & Real Initialization Plan

**Date/Time:** 2026-09-26 11:55 IST  
**Objective:** Upgrade the existing JARVIS React frontend with a production-grade cinematic 3D startup sequence (Three.js WebGL) synchronized with real backend initialization, live source audit, system health checks, real reminders, live AI & local news synthesis, synchronized procedural audio, and a 15–30s dynamic voice briefing.

---

## 1. Current State Assessment
- **Frontend Stack:** React 18, Vite 5, Lucide React, Swiper. `three` is not yet installed.
- **Core Display:** `src/CoreSphere.jsx` is currently a 2D canvas drawing circles and dashed arcs.
- **HUD Grid & Layout:** `src/App.jsx` houses the main dashboard:
  - Left column: `hud-panel-chat` (Transcript/Chat) and `hud-panel-files` (File Bay & Album)
  - Center column: `Telemetry`, `CoreSphere`, and `log-ticker`
  - Right column: `CommandGrid` (Quick Directives) and `PhonePanel` (Phone Mirror)
- **Startup / Audit:** 
  - Backend `main.py` has a background worker with a hard-coded 15-second sleep (`_STARTUP_AUDIT_WAIT_SECONDS = 15`).
  - `code_core.audit_codebase()` discovers Python and JS files (currently 87 files: 68 py, 19 js) and verifies AST / compile / exports.
  - Frontend `StartupAuditBanner.jsx` simply polled `/api/code/audit/latest`.
  - There is no real-time event streaming during boot; the frontend loaded directly into the full dashboard without a cinematic initialization phase.
- **News & Briefing:**
  - `system_ops.py` has `get_weather` (wttr.in) and `get_datetime_info`.
  - Google News RSS can be accessed via `urllib.request` for live AI news and Pune/local news without API keys or external dependencies.
  - Scheduler (`backend/tools/scheduler.py`) provides `list_reminders()`.
  - `todos.json` provides todo tasks.
  - `backend/tools/gmail_notify.py` checks Gmail when authorized via `token_gmail.json`.
  - `main.py` has `/api/voice/tts` and frontend has `SpeechSynthesisUtterance`.

---

## 2. Planned Steps
1. **Dependency & Environment:** Install `three` (compatible Three.js for WebGL core rendering).
2. **Backend Startup Engine (`main.py` / `backend/startup_engine.py`):**
   - Create unified startup initialization endpoint (`POST /api/startup/init` & `GET /api/startup/stream` / `GET /api/startup/status`).
   - Run genuine source audit without artificial delays: discover actual files, report real count (e.g. 87) and real health score.
   - Run genuine subsystem checks: Core, Perception, Tools, Memory, Scheduler, Communications, Weather.
   - Run genuine AI news extraction (3 current items with sources) and local Pune news extraction.
   - Synthesize a dynamic, time-aware voice briefing incorporating verified status, actual reminders, real AI news, and local updates.
3. **Procedural Web Audio Manager (`src/audio/AudioManager.js`):**
   - Centralized audio manager using Web Audio API synthesis (zero external files, zero copyright, 100% offline-ready, responsive, subtle futuristic sound design).
   - Audio events: `CORE_ACTIVATION`, `SPHERE_MATERIALIZATION`, `ORBIT_START`, `ORBIT_COMPLETE`, `PANEL_ENTRY`, `SYSTEM_ONLINE`, `VOICE_BRIEFING_START`.
   - Browser autoplay policy handling: graceful fallback, user interaction unlock, mute toggle for accessibility.
4. **Cinematic 3D Core (`src/components/Jarvis3DCore.jsx`):**
   - Stage 1: Small dark glowing sphere with restrained blue illumination, internal glow, subtle pulse.
   - Stage 2: Surrounding dotted spherical structure progressively materializing from particles/dots with depth and rotation.
   - Stage 3: Three elliptical orbital paths that trace/draw themselves progressively from origin, complete loop, and persist as rotating orbitals.
   - Particle field and dark blue/black environment with subtle cybernetic HUD grid.
   - Performance: Clamped DPR, efficient BufferGeometry, proper resource disposal on unmount.
5. **UI Assembly & Startup State Machine (`src/components/StartupController.jsx`):**
   - Deterministic state machine: `BOOT` -> `CORE_INITIALIZING` -> `CORE_ACTIVE` -> `SPHERE_INITIALIZING` -> `ORBITALS_INITIALIZING` -> `UI_ASSEMBLY` -> `AUDIT_RUNNING` -> `SYSTEM_VERIFYING` -> `SYSTEM_READY` -> `BRIEFING` -> `ONLINE`.
   - Scattered initial positions:
     - Telemetry enters from above, overshoots slightly, settles.
     - Quick Directives enters from right, decelerates, locks.
     - Chat Log enters from below, settles.
     - Chat Transcript enters from left, settles.
     - File Bay emerges from scattered state, converges.
     - Phone Mirror enters below Quick Directives.
   - Seamless convergence into the final dashboard layout.
6. **Voice Briefing Integration:**
   - 15–30s spoken briefing after genuinely ready.
   - Spoken via browser `speechSynthesis` or `/api/voice/tts`.
   - Output to chat transcript.
7. **Verification & Testing:**
   - Test full visual boot sequence on localhost.
   - Verify real audit file count and health score.
   - Verify real AI & local news.
   - Verify panel animations and audio sync.
   - Verify no regressions in chat, voice, phone mirror, code core, files.

---

## 3. Checklist
- [x] Install Three.js dependency
- [x] Create implementation plan in project root
- [x] Implement Backend Startup & Audit Engine (`backend/startup_engine.py`)
- [x] Implement Live News & Briefing Data Provider (RSS-based, zero fake data)
- [x] Implement Centralized Procedural Audio Manager (`src/audio/AudioManager.js`)
- [x] Implement 3D Core with progressive sphere, dotted shell, and traced persistent orbitals (`src/components/Jarvis3DCore.jsx`)
- [ ] Implement Startup State Machine & Scattered UI Assembly
- [ ] Integrate with Main Dashboard (`App.jsx`)
- [ ] Verify Audio, Visuals, and Fallback Modes
- [ ] Verify Real Audited File Count & State Reporting
- [ ] Verify Dynamic Voice Briefing
- [ ] Run full test suite and confirm no regressions
- [ ] Git commit and push verified changes

---

## 4. Verification Requirements
- Real Three.js WebGL canvas rendering.
- Progressive core appearance and dotted sphere materialization.
- Three elliptical orbitals traced and persistent after boot.
- UI panels assemble from scattered positions into exact dashboard locations.
- Real audit executed and actual file count reported.
- Real AI news items with cited sources.
- Real local updates (Pune / Camp / Mohammed Wadi).
- Procedural audio synchronized and browser autoplay compliant.
- No hardcoded numbers or fake timers.
