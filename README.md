# J.A.R.V.I.S.

## Just A Rather Very Intelligent System

**A Windows-first, local-first AI agent that can understand a task, plan it, control the computer, observe what happened, verify the result, recover from failures, and continue.**

[![Python](https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Playwright](https://img.shields.io/badge/Browser-Playwright-45BA4B?logo=playwright&logoColor=white)](https://playwright.dev/)

> **JARVIS is built around an agent loop, not a chat-only interface:**  
> **Understand → Plan → Validate → Execute → Observe → Verify → Recover/Retry → Continue**

---

## What is JARVIS?

JARVIS is an open development project for a **general-purpose AI computer agent for Windows**.

Instead of only generating text, JARVIS is designed to turn natural-language instructions into real computer actions and then check whether those actions actually worked.

The goal is a single agent with many tools — not a collection of disconnected mini-agents.

### Core idea

```text
                    USER
                      │
                      ▼
              ┌───────────────┐
              │    J.A.R.V.I.S│
              │   Agent Core  │
              └───────┬───────┘
                      │
             Understand → Plan
                      │
                      ▼
                   Execute
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    COMPUTER       BROWSER        OFFICE
        │             │             │
        └─────────────┼─────────────┘
                      ▼
                   OBSERVE
                      │
                      ▼
                   VERIFY
                      │
                ┌─────┴─────┐
                │           │
             SUCCESS     FAILURE
                │           │
                ▼           ▼
             CONTINUE    RECOVER
                            │
                            ▼
                         CONTINUE
```

---

## What can JARVIS do?

### 🧠 Agentic task execution

- Natural-language task understanding and planning
- Multi-step task execution
- Persistent task state and context
- Observation after actions
- Verification before reporting completion
- Recovery and retry for recoverable failures
- Human-in-the-loop escalation when automation is genuinely blocked
- Persistent conversation/memory features

### 🖥️ Windows computer control

- Windows UI Automation (UIA)
- Application and window discovery
- Semantic element discovery
- Clicking, typing, scrolling and keyboard shortcuts
- Clipboard operations
- Window management
- Screenshots
- OCR and vision-assisted inspection
- Bounded, recoverable automation

### 🌐 Browser automation

- Chromium control through Playwright
- Navigation and searching
- Form filling and interaction
- Tabs and screenshots
- Web-content extraction
- Boilerplate/navigation cleanup before research analysis
- Image searching for generated documents and presentations

### 📄 Research → Word / PowerPoint

JARVIS is designed to **analyze research before generating an artifact**.

```text
Discover
   ↓
Extract
   ↓
Clean
   ↓
Analyze
   ↓
Compare
   ↓
Synthesize
   ↓
Generate
   ↓
Verify
```

It can generate:

- Word documents with `python-docx`
- PowerPoint presentations with `python-pptx`
- Tables and charts
- Research reports
- Source-based summaries
- Presentation images
- PDF text extraction

Generated artifacts are exposed through the JARVIS files/gallery system.

### 📁 File analysis & document Q&A

- Analyze uploaded files
- Extract document text
- Ask questions about file contents
- OCR image/scanned documents
- Process code files
- Produce corrected versions of supported files

### 🛠️ Code Intelligence

JARVIS includes a Code Core for inspecting and repairing its own codebase.

- AST / syntax checks
- `py_compile` validation
- Per-file issue detection
- Code health information
- Nemotron/NVIDIA-powered repair
- Preview → Apply Patch workflow
- Validation after changes
- Automatic rollback on failed repairs
- Large-file segmented repair
- Uploaded-file inspection and refactoring

### 🎙️ Voice

JARVIS includes Windows/browser-oriented voice capabilities and is designed to support natural voice interaction as the project evolves.

### 📱 Additional capabilities

JARVIS also contains **Android/ADB and phone-mirroring functionality**.

These capabilities are part of the project but are **not the current primary development focus**. Current development is concentrated on the Windows agent, computer use, browser control, observation, verification, memory, research, voice and code intelligence.

The same principle applies to supporting utilities such as the watchdog: they remain part of the project where implemented, even when they are not the current development priority.

---

## Architecture

JARVIS separates the model layer from the tool/runtime layer.

### Model roles

- **Gemini** — normal conversation, planning and supported vision tasks
- **NVIDIA NIM / Nemotron** — code intelligence and repair workflows
- Other configured providers can be used for supported optional features

### Runtime

```text
JARVIS
│
├── Agent Core
│   ├── Planner
│   ├── Executor
│   ├── State
│   ├── Observer
│   ├── Verifier
│   ├── Recovery
│   └── Memory
│
├── Computer Tools
│   └── Windows UI Automation
│
├── Browser Tools
│   └── Playwright / Chromium
│
├── Office Tools
│   ├── Word
│   ├── PowerPoint
│   └── Charts
│
├── Research
│   └── Analyze → Compare → Synthesize
│
├── Vision / OCR
│
├── Code Core
│   └── Audit → Repair → Validate → Rollback
│
├── Voice
│
├── Android / ADB
│
└── React + Vite Dashboard
```

### Repository structure

```text
JARVIS/
├── main.py
├── agent.py
├── system_ops.py
├── code_core.py
├── document_intel.py
├── phone_control.py
├── start_jarvis.py
├── google_oauth.py
│
├── backend/
│   ├── agent/
│   │   ├── core.py
│   │   ├── planner.py
│   │   ├── executor.py
│   │   ├── state.py
│   │   ├── observer.py
│   │   ├── verifier.py
│   │   ├── recovery_engine.py
│   │   ├── research_synthesizer.py
│   │   └── phase1_memory.py
│   │
│   └── tools/
│       ├── computer.py
│       ├── browser.py
│       ├── office.py
│       ├── charts.py
│       └── vision.py
│
├── src/                    # React + Vite dashboard
├── tests/
├── requirements.txt
└── README.md
```

---

## Why JARVIS?

The project is focused on moving from:

```text
AI that tells you what to do
          ↓
AI that plans what to do
          ↓
AI that actually does it
          ↓
AI that checks whether it worked
          ↓
AI that can recover and continue
```

The important part is **closed-loop execution**.

JARVIS should not simply say:

> "Done."

It should have evidence from execution and verification before reporting success.

---

## Requirements

### System

- Windows 10/11
- Python 3.10–3.14
- Node.js 18+
- npm
- Google Chrome/Chromium for Playwright

### Optional service credentials

JARVIS can use configured external AI services for specific capabilities. Credentials are feature-dependent.

| Configuration | Purpose |
|---|---|
| `gemini_api_key` | Conversation, planning, supported vision/OCR and document Q&A |
| `nvidia_api_key` | Code intelligence / Nemotron workflows |
| `huggingface_api_key` | Optional image-generation fallback |
| Google OAuth configuration | Supported protected Google features |

The project is designed so that missing optional credentials produce a clear feature-specific limitation rather than silently pretending a capability worked.

Python dependencies are listed in **`requirements.txt`**.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/TAHA-SHAIKH27/JARVIS.git
cd JARVIS
```

Create a virtual environment:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

Install Playwright Chromium:

```bash
python -m playwright install chromium
```

Install frontend dependencies:

```bash
npm install
```

Configure the services you want to use through the project's local configuration.

**Never commit API keys, OAuth secrets, browser credentials or personal data.**

---

## Running JARVIS

The convenience launcher can start the backend and frontend:

```bash
python start_jarvis.py
```

Or run them separately:

```bash
# Backend
.venv\\Scripts\\activate
uvicorn main:app --host 127.0.0.1 --port 8000

# Frontend
npm run dev
```

The dashboard normally runs at:

```text
http://localhost:3000
```

The FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

---

## Development principles

1. Prefer semantic UI Automation over guessed coordinates.
2. Observe the environment before acting when practical.
3. Verify important actions instead of assuming they succeeded.
4. Recover or re-plan recoverable failures.
5. Ask for human intervention when automation is genuinely blocked.
6. Never claim an action succeeded without execution/verification evidence.
7. Keep persistent memory separate from temporary task state.
8. Keep automation bounded and recoverable.
9. Make targeted changes and fix root causes rather than symptoms.
10. Preserve existing working functionality while expanding the agent.

---

## Security

Never commit:

- API keys
- OAuth credentials
- `.env` files containing secrets
- `config.json` containing live credentials
- `client_secret.json`
- Authentication cookies
- Browser profiles containing personal sessions
- Private certificates
- Personal/private data

Use environment variables or a **gitignored** local configuration file.

---

## Current development focus

JARVIS contains many capabilities, but development is intentionally focused rather than attempting to build everything simultaneously.

### Current priority

- Agent intelligence
- Computer Use
- Browser automation
- Observation and perception
- Verification
- Recovery
- Memory
- Voice
- Research and document generation
- Code Intelligence / self-debugging

### Existing but lower-priority capabilities

- Android / ADB integration
- Phone mirroring
- Watchdog/support utilities
- Additional experimental integrations

These are **not removed from JARVIS**. They are simply outside the main development path at the moment.

---

## Roadmap

### Phase 1 — Agent Intelligence
Memory, context, reminders, planner and task state.

### Phase 2 — Computer Use & Vision
Windows UI Automation, browser control, observation, verification and agent execution.

### Phase 3 — Research & Presentation Generation
Source extraction, analysis, comparison, synthesis and structured Word/PPT generation.

### Phase 4 — Document & File Expansion
Charts, tables, document gallery and broader file support.

### Phase 5 — Code Intelligence
Self-audit, Nemotron repair, validation, rollback and uploaded-file inspection.

### Future expansion

Continue improving the core agent while gradually bringing additional existing capabilities and experimental integrations into the main workflow.

---

## Contributing

JARVIS is an evolving project.

If you want to contribute:

1. Understand the current agent architecture.
2. Keep changes focused.
3. Preserve existing functionality.
4. Test changes before submitting them.
5. Document meaningful architectural changes.
6. Avoid committing secrets, generated runtime state or personal files.

---

## License

No open-source license has currently been declared in this repository. Until a license is added, the source remains subject to the repository owner's default copyright.

---

## Project

**J.A.R.V.I.S. — Just A Rather Very Intelligent System**

Built with the goal of creating a capable, transparent and extensible AI agent that can move beyond conversation into real computer interaction.
