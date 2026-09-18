# J.A.R.V.I.S.

**JARVIS — Windows AI Computer Agent**

A local-first AI assistant that understands natural-language requests, plans multi-step tasks, operates Windows applications, drives a real browser, generates research-backed documents and presentations, performs OCR, audits and repairs its own codebase, and verifies every action before reporting completion.

JARVIS is not a chat wrapper. It is an **agentic runtime**: every request goes through a **Discover → Extract → Clean → Analyze → Compare → Synthesize → Generate → Verify** pipeline, so the things it hands you (Word documents, PowerPoint decks, research reports, source fixes) are built from *analyzed* findings, never pasted webpage text.

---

## What JARVIS can do

### AI agent loop (core intelligence)
- **Natural-language task planning** — the Planner turns free-form requests into validated, dependency-checked action plans.
- **Multi-step execution** with a persistent task state machine: `Understand → Plan → Validate → Execute → Observe → Verify → Recover/Retry → Complete`.
- **Persistent memory & conversation context** across sessions, plus reminders, notes and todos (frontend widgets included).
- **Honest completion reporting** — JARVIS will never claim an action succeeded unless execution and verification confirmed it.
- **Human-in-the-loop escalation** — when a task is genuinely blocked (for example, a CAPTCHA), JARVIS stops automated interaction, tells you exactly what it needs, and resumes automatically once you resolve it.

### Windows computer control
- Semantic **UI Automation** (UIA-first) interaction with any Windows application — element discovery by name/label instead of guessed coordinates.
- Application/window discovery, focus, minimize/maximize, window management.
- Keyboard typing, hotkeys, scrolling, clicking, drag-and-drop, clipboard operations.
- Screenshot capture with optional **OCR** (Tesseract) and optional vision-based inspection.
- Defensive bounds on every automation call (recoverable, bounded, never silent).

### Browser automation
- Full **Chromium control via Playwright** — navigation, searching, form filling, clicks, screenshots, tab management.
- **Boilerplate-stripped web extraction** — navigation, menus, ads, cookies notices and footers are removed from fetched content before analysis, so research never dumps raw websites into your documents.
- **Reverse/broken-page images search** — `search_images()` finds relevant images for slides and documents without disturbing the active research page.

### Research → document & presentation generation
- **Real research pipeline, not scraping**: multiple sources are *deduplicated*, individually **analyzed** (`analyze_source`), **cross-compared** (`compare_sources`), and **synthesized** (`synthesize_research_report`) before any file is generated.
- **Word documents (`python-docx`)** with headings, bullet hierarchies, markdown tables, styled/shaded table headers, striped rows, and embedded **charts** (`[CHART:type]` blocks rendered by the built-in matplotlib chart engine — bar, pie, line, area).
- **PowerPoint decks (`python-pptx`)** generated slide-by-slide from analyzed findings with concise bullets (max 8 words), tables, real comparison charts, speaker notes, and **relevant images** — sourced online first, Hugging Face generation only as a fallback, never random filler.
- **PDF text extraction** (`pdfplumber`) for citation and source reading.
- Every generated artifact lands in the built-in **FILES gallery** (docx/pptx/images) for instant download.

### File analysis & document Q&A
- Upload or select any file; JARVIS **extracts** the text and lets you ask questions about the actual content (analysis, not echoing).
- **OCR for scanned/image documents** — `.png`, `.jpg`, `.jpeg` uploads and scanned/image-only PDFs are automatically read through Gemini vision OCR and analyzed.
- Downloadable corrected versions of uploaded code files (see Code Intelligence).

### Code Intelligence (Code Core)
- **Autonomous self-audit** of the JARVIS codebase: AST syntax checks and `py_compile` integrity scoring with a health score, per-file issue lists and live source-graph UI.
- **Nemotron (NVIDIA NIM) repair engine** — per-issue *Preview Fix* → *Apply Patch* flow with unified diffs, automatic **backups**, validation and **auto-rollback** on failure.
- **Large-file segmented repair** — files above ~50,000 characters are split into small segments and repaired piece-by-piece with compact diff hunks, keeping every AI response small enough for the free NVIDIA tier (no more 504 gateway stalls).
- **Uploaded code inspector** for any language (.py, .js, .jsx, .ts, .cpp, .c, .java, .html, .css, .json, .sql, .sh) — fix bugs, refactor per your instructions, and download the corrected file with a diff.
- Opinionated model routing: the fast, reliable `z-ai/glm-5.3-flash` is the default code-intelligence model (configured slow models are routed away automatically).

### Dashboard (React + Vite, optional Electron shell)
A live HUD with:
- **Core Sphere** task agent console, telemetry, command grid and memory widgets.
- **FILES gallery** — generated documents, presentations and images with live download links.
- **Code Core page** — self-audit, validation suite, unified diff previews, fix-and-validate, and the uploaded-file refactor tool.
- **Notes & Todos**, **Startup self-audit banner**, streaming chat/command/vision panels, Google OAuth status.
- Optional **phone mirroring panel** (ADB-based screen mirror, tap/swipe/text/key injection, OCR).

---

## Architecture

JARVIS separates the **LLM front-end** (Gemini for normal conversation/planning/vision, Nemotron for code intelligence) from the **tool runtime** (Windows automation, Playwright browser, document generators, research synthesizer, verification).

```text
Understand → Plan → Validate → Execute → Observe → Verify → Recover/Retry → Complete
```

### Module map

```text
JARVIS/
├── main.py                     # FastAPI backend: HTTP endpoints + streaming (chat/command/vision/document)
├── agent.py                    # Agent orchestration (planning, prompts, HF/gemini image generation)
├── system_ops.py               # Filesystem + Word/PPT document creators and gallery archive
├── code_core.py                # Code intelligence: audit, Nemotron fixes, segmented large-file repair
├── document_intel.py           # File extraction + document Q&A, image/scanned-PDF OCR routing
├── phone_control.py            # Android/ADB screen mirror, input injection, OCR
├── start_jarvis.py             # One-command launcher for backend + frontend
├── google_oauth.py             # Google OAuth for protected AI features
├── backend/
│   ├── agent/
│   │   ├── core.py             # Agent runtime: task lifecycle, CAPTCHA pause/resume
│   │   ├── planner.py          # Natural-language task planner + action templates
│   │   ├── executor.py         # Action dispatcher (browser, office, system, docs)
│   │   ├── state.py            # Task state machine
│   │   ├── observer.py         # Environment observation / blocker detection
│   │   ├── verifier.py         # Action verification
│   │   ├── research_synthesizer.py  # Analyze → compare → synthesize reports & decks
│   │   └── phase1_memory.py    # Persistent memory layer
│   └── tools/
│       ├── computer.py         # Windows UI Automation / desktop control
│       ├── browser.py          # Playwright browser + boilerplate-stripping + image search
│       ├── office.py           # python-docx / python-pptx document builders
│       ├── charts.py           # matplotlib chart renderer (bar/pie/line/area)
│       └── vision.py           # Gemini vision OCR (images & scanned PDFs)
├── src/                        # React + Vite dashboard (CoreSphere, GalleryPage, CodeCorePage, ...)
├── whisper.cpp/                # Vendored third-party speech toolset (not part of the runtime)
└── ws-scrcpy/                  # Phone-mirroring frontend tooling
```

---

## Deep dive: research-to-document pipeline

```text
Discover sources → Extract relevant content → Remove navigation/boilerplate
→ Analyze each source → Compare sources → Synthesize a structured outline
→ Generate document/presentation → Verify output exists and is well-formed
```

1. **Extraction ≠ Analysis.** Web text is fetched and *cleaned* (menus/ads/boilerplate stripped, deduped). Then each source is read **for meaning** by the Research Synthesizer (`analyze_source`).
2. **Comparison.** The synthesizer cross-compares findings (`compare_sources`) to surface agreements and conflicts.
3. **Synthesis.** The LLM produces a structured research report (or presentation skeleton) from the analysis — concise bullets, charts only where real quantities are compared, images only where they genuinely support a slide.
4. **Generation.** `Office` builds the real `.docx` / `.pptx` (charts, styled tables, images) and the artifact is archived into the built-in FILES gallery.
5. **Verification.** The output is validated before JARVIS reports success.

---

## Requirements

**System**
- Windows 10/11 (UI automation paths are Windows-only)
- Python 3.10–3.14
- Node.js 18+ and npm (frontend)
- Google Chrome/Chromium browser (for Playwright)

**Service credentials (all optional, feature-dependent)**

| Key (in `config.json`) | Powers |
|---|---|
| `gemini_api_key` | Conversation, planning, vision/OCR, document Q&A |
| `nvidia_api_key` | Code intelligence (Nemotron fixes, Code Core) |
| `huggingface_api_key` | Image generation fallback for presentations |
| `google_project_id` + OAuth (`client_secret.json`) | Protected Google features |

No key = JARVIS still runs; the features that need that service simply degrade or report a clean, actionable error.

**Python dependencies** are pinned in `requirements.txt` (FastAPI, Playwright, python-docx, python-pptx, pdfplumber, Pillow, matplotlib, Google/Hugging Face SDKs, and Windows automation libs).

---

## Installation

```bash
git clone https://github.com/TAHA-SHAIKH27/JARVIS.git
cd JARVIS
```

```bash
# Python 3.10–3.14
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

```bash
# Playwright Chromium binaries
python -m playwright install chromium
```

```bash
# Frontend
npm install
```

**Configure services** — create/update `config.json` at the project root with the API keys you want to enable:

```json
{
  "gemini_api_key": "...",
  "nvidia_api_key": "...",
  "huggingface_api_key": "...",
  "nvidia_model": "z-ai/glm-5.3-flash"
}
```

Optional `.env` file is also loaded for additional runtime vars. Do **not** commit `config.json`, `.env`, or `client_secret.json` to GitHub.

---

## Running JARVIS

Simplest:

```bash
python start_jarvis.py        # starts backend (127.0.0.1:8000) + frontend dev server
```

Or separately:

```bash
# Terminal 1 — backend
.venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8000

# Terminal 2 — frontend (Vite)
npm run dev
```

Open the dashboard at **http://localhost:3000** (Vite proxies `/api` to the backend; API docs at http://127.0.0.1:8000/docs).

### Main API surface

| Area | Endpoints |
|---|---|
| Agent | `POST /api/agent/plan`, `/api/agent/run`, `/api/agent/execute`, `GET /api/agent/status`, `POST /api/agent/resume` |
| Streaming | `POST /api/chat/stream`, `/api/command/stream`, `/api/vision/stream` |
| Documents | `POST /api/document/extract`, `/api/document/stream` |
| Files & gallery | `GET /api/files`, `/api/gallery`, `/api/files/serve`, `/api/images/{name}`, read/write/delete |
| Code Core | `POST /api/code/audit`, `/api/code/preview-fix`, `/api/code/apply-fix`, `/api/code/process-file`, `/api/code/download/{file}` |
| Notes / Todos | `GET/POST /api/notes`, `GET/POST/PATCH/DELETE /api/todos` |
| OAuth & config | `/api/oauth/*`, `/api/config`, `/api/status`, `/api/stats` |
| Phone (optional) | `/api/phone/*` (mirror, tap, swipe, text, key, apps, OCR) |

---

## Development principles

1. Prefer semantic UI Automation over guessed coordinates.
2. Observe the application before acting when practical.
3. Verify important actions instead of assuming they succeeded.
4. Retry or re-plan recoverable failures; fail fast, with a clear reason, on deterministic ones.
5. Ask for human intervention when a task is genuinely blocked.
6. Never claim an action was completed when execution or verification did not confirm it.
7. Keep persistent user memory separate from temporary task state.
8. Keep browser and Windows automation bounded and recoverable.
9. Make the smallest targeted change; classify findings (critical/functional/logic/performance/style) and fix root causes, not symptoms.

---

## Security

Never commit to the repository:

- API keys (Gemini, NVIDIA, Hugging Face, Groq) or OAuth credentials
- `.env` files, `config.json` with live keys, or `client_secret.json`
- Personal tokens, authentication cookies, or browser profiles
- Private certificates or private data files

Use environment variables or a **gitignored** local `config.json` instead. Secrets must stay off GitHub.

---

## Status & roadmap

- **Phase 1 — Agent Intelligence:** memory, context, reminders, planner, task state — done.
- **Phase 2 — Computer Use & Vision:** Windows UI Automation, browser control, observation & verification, Agent Mode — done.
- **Phase 3 — Research & Presentation Generation:** extraction→analysis→synthesis pipeline, structured Word/PPT generation — done.
- **Phase 4 — Document Generation & Expansion:** charts, markdown tables, document gallery, broader file support — done.
- **Phase 5 — Code Intelligence (in progress):** self-audit, Nemotron repair with rollback, large-file segmented repair, uploaded-file inspector.

---

## License

No open-source license has been declared yet. Unless a license is added to this repository, the project's source code remains under the repository owner's default copyright.