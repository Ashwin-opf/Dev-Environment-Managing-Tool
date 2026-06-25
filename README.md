# PC Doctor

PC Doctor is a cross-platform desktop application for intelligent system scanning, repair recipes, optimization, driver checks, action logs, and an optional offline AI terminal powered by Ollama.

Works on **Windows, Linux, and macOS** — no modification required.

```text
Tauri desktop UI (Rust)
  -> FastAPI backend on http://127.0.0.1:8765
  -> SQLite repair database in backend/knowledge.db
  -> Optional local Ollama models for AI
```

## Features

- Dashboard with RAM and storage views
- Scan page for system and developer-tool checks
- Repair page with reviewed commands before execution
- Optimize page for cleanup and maintenance actions
- Dev Tools status and repair helpers
- Driver scan and update page
- AI Terminal using local Ollama models
- Action Logs with newest executions first

## Requirements

- **Node.js** 18 or newer
- **Python** 3.10 or newer
- **Rust + Cargo** (only needed if building the Tauri desktop binary — not needed for dev mode)
- Ollama (optional, for AI features)

## Setup — Any OS

```bash
npm run setup
```

This auto-detects your OS and handles everything: creating the Python venv, installing dependencies, and seeding the knowledge database.

## Run — Any OS

```bash
npm start
```

Starts the Python backend and Vite frontend simultaneously. Open `http://localhost:5173` in your browser, or use the Tauri desktop window if you've built the app with `npm run build`.

## Optional AI

```bash
# Install Ollama (see https://ollama.com for your OS)
ollama pull phi3:mini
```

## Project Structure

```text
PC Doc/
├── src-tauri/           # Tauri Rust native wrapper
├── frontend/            # HTML/CSS/JS UI (Vite)
├── backend/             # FastAPI backend + repair engine (Python)
├── scripts/             # Cross-platform setup.js, start.js, setup.sh, setup.ps1
├── tests/               # Playwright and Python tests
├── package.json         # Root npm scripts (setup, start, dev, build)
└── config/              # Local app settings
```

## Notes

- Every repair command is shown to the user before execution.
- Some repair actions may request administrator / sudo access.
- AI features require Ollama and a pulled model.
- The backend is auto-started by the Tauri host. If it shows as offline, click **Start Backend** in the top bar.
