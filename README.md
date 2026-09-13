# J.A.R.V.I.S.

**JARVIS — Windows AI Computer Agent**

A local-first AI assistant designed to understand natural-language requests, plan tasks, operate Windows applications, control a browser, create documents and presentations, and verify its actions before reporting completion.

## Current capabilities

- AI task planning and execution
- Persistent memory and conversation context
- Reminder/context support
- Windows computer control
- Windows UI Automation with UIA-first interaction
- Application/window discovery and focus
- Semantic UI inspection and element finding
- Keyboard, typing, scrolling, clicking and drag/drop actions
- Browser automation with Playwright
- Word document generation with `python-docx`
- PowerPoint generation with `python-pptx`
- PDF text extraction with `pdfplumber`
- Image handling with Pillow
- Hugging Face integration support
- Execution verification and error recovery foundations
- Human intervention support for blocked tasks such as CAPTCHAs

## Architecture

JARVIS is organized around an agent workflow:

**Understand → Plan → Validate → Execute → Observe → Verify → Recover/Retry → Complete**

The project is being developed in phases:

### Phase 1 — Agent Intelligence

- Persistent memory
- Conversation context
- Reminders
- Planner context
- Task state and execution tracking

### Phase 2 — Computer Use & Vision

- Windows application control
- UI Automation
- Browser control
- Observation and verification
- Window management
- Agent Mode execution

### Phase 3 — Research & Presentation Generation

Planned improvements include structured web research, source extraction, analysis, comparison and high-quality PPT generation with relevant images.

### Phase 4 — Document Generation & Expansion

Planned improvements include stronger research-to-document workflows and broader device/ecosystem capabilities.

## Project structure

```text
JARVIS/
├── backend/
│   ├── agent/          # Planner, executor, state, verification and runtime layers
│   ├── tools/          # Browser, computer and content tools
│   └── data/           # Local runtime data such as persistent memory
├── frontend/            # JARVIS web interface
├── requirements.txt     # Python dependencies
└── README.md
```

## Requirements

- Windows 10/11
- Python 3.10+
- Node.js/npm for the frontend
- Google/Gemini credentials if Gemini-powered features are enabled
- Optional Hugging Face token for supported AI-generation features

Python dependencies are listed in `requirements.txt`.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/TAHA-SHAIKH27/JARVIS.git
cd JARVIS
```

### 2. Create a Python virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browser binaries

```bash
python -m playwright install chromium
```

### 5. Configure environment variables

Create a local `.env` file and add the API credentials required by the features you enable. Do **not** commit API keys or secrets to GitHub.

## Running JARVIS

Start the backend using the project's backend entry point and start the frontend using the project's frontend development command.

The current development setup uses:

- Frontend: `http://localhost:3000`
- Backend: `http://127.0.0.1:8000`

Use the commands already defined in the repository's frontend/backend setup rather than hard-coding production deployment assumptions.

## Development principles

JARVIS should:

1. Prefer semantic UI Automation over guessed coordinates.
2. Observe the application before acting when practical.
3. Verify important actions instead of assuming they succeeded.
4. Retry or re-plan recoverable failures.
5. Ask for human intervention when a task is genuinely blocked.
6. Never claim an action was completed when execution or verification did not confirm it.
7. Keep persistent user memory separate from temporary task state.
8. Avoid exposing API keys, tokens or other secrets.
9. Keep browser and Windows automation bounded and recoverable.

## Research and document quality

When JARVIS performs research, it should **not** dump raw webpage text into a document. The intended workflow is:

**Discover sources → Extract relevant content → Remove navigation/boilerplate → Analyze → Compare → Synthesize → Generate document/presentation → Verify output**

This keeps generated reports focused on useful information rather than menus, buttons, headers or unrelated webpage content.

## Security

Never commit:

- API keys
- OAuth credentials
- `.env` files containing secrets
- Personal tokens
- Private certificates
- Authentication cookies or browser profiles

Use environment variables or local secret storage instead.

## Status

JARVIS is under active development. Phase 1 and the Phase 2 architecture are implemented, while Windows end-to-end testing and later-generation features continue to evolve.

## License

No open-source license has been declared yet. Unless a license is added to this repository, the project's source code remains under the repository owner's default copyright.
