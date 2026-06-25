# Quick Start

PC Doctor works on **Windows, Linux, and macOS** using the same commands.

## Prerequisites

You need **Node.js 18+** and **Python 3.10+** installed.

| OS | How to install |
|---|---|
| **Windows** | `winget install OpenJS.NodeJS.LTS` and `winget install Python.Python.3.12` |
| **macOS** | `brew install node python` |
| **Linux (Debian/Ubuntu)** | `sudo apt-get install -y nodejs npm python3 python3-pip python3-venv` |

---

## First-Time Setup (Any OS)

Open a terminal in the `PC Doc` folder and run:

```bash
npm run setup
```

This single command will:
- Detect your OS automatically
- Create a Python virtual environment
- Install all Python backend dependencies
- Seed the repair knowledge database
- Install all Node.js dependencies

---

## Start the App (Any OS)

```bash
npm start
```

This launches the Python backend on `http://127.0.0.1:8765` and the Vite frontend at `http://localhost:5173` in parallel.

---

## Optional — AI Terminal Support

Install Ollama and pull a model:

```bash
# Windows
winget install Ollama.Ollama

# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

Then pull the recommended model:

```bash
ollama pull phi3:mini
```

---

## Troubleshooting

**Backend won't start?** Run it manually to see the error:

```bash
# Any OS (uses the virtual environment created by setup)
node -e "
const path = require('path');
const { spawnSync } = require('child_process');
const isWin = process.platform === 'win32';
const py = path.join('backend', '.venv', isWin ? 'Scripts/python.exe' : 'bin/python3');
spawnSync(py, ['backend/main.py'], { stdio: 'inherit', cwd: process.cwd() });
"
```

**Port 8765 already in use?** Another instance is running. On Windows: `netstat -ano | findstr 8765` then `taskkill /F /PID <pid>`. On Linux/macOS: `fuser -k 8765/tcp`.
