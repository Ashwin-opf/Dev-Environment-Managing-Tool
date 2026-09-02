# DevEngine — DevTools Store & Control Center

> **A local-first, AI-powered developer tools manager, package store, and system control center.**
> Works on Windows, macOS, and Linux. No cloud. No sign-in. Runs entirely on your machine.

---

## Table of Contents

1. [What This App Does](#what-this-app-does)
2. [Application Features (Full Reference)](#application-features-full-reference)
3. [Project Structure](#project-structure)
4. [Getting Started on a New Machine](#getting-started-on-a-new-machine)
5. [How to Run](#how-to-run)
6. [API Reference](#api-reference)
7. [Customization](#customization)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)

---

## What This App Does

DevEngine is a **local web application** (no internet account required) that lets you:

- **Browse, search, and install** developer tools and packages from a unified marketplace
- **Search online** across Windows Package Manager (Winget), Microsoft Store, NPM, and PyPI in real-time (internet required for search only)
- **Monitor your developer environment health** — which runtimes, compilers, and IDEs are installed
- **Manage installed apps** — see all detected apps with version info and update buttons
- **Review and approve** system-changing operations in a secure Control Center before they execute
- **Maintain system snapshots** and roll back your environment to a previous state
- **Find automated fixes** (RAG-powered) for common developer environment issues
- **Configure security policies** for what needs approval and what can auto-run

---

## Application Features (Full Reference)

### Tab 1 — Dev Tools Store

| Feature | What It Does |
|---|---|
| Universal Search Bar | Type any app name (blender, vlc, spotify, vscode, rust, flutter). Instantly searches the local catalog AND queries Winget, Microsoft Store, NPM, and PyPI live. |
| Category Filter Pills | One-click filter: All, Popular, Trending, 2026 Hot, IDEs, Languages, Frameworks, Databases, DevOps, Git, CLI, Testing |
| Dev Tool Cards | Each card shows: icon, name, category, description, official website link, version, install/manage button |
| Online Package Cards | Live-discovered packages show: source badge (WINGET/NPM/PYPI), publisher, official URL, exact install command |
| Dev Environment Health Banner | Shows % health score, installed/total tool count, status text |
| Re-Scan Button | Probes your PATH for all binaries, updates health score and all card badges instantly |
| Dev Doctor & Auto-Repair | Opens the full diagnostics modal |
| Store Sections | Popular Suites, IDEs, Languages, Package Managers, DevOps, Databases, CLI Tools, All Catalog |
| Ctrl+K shortcut | Focus the search bar from anywhere |

#### Dev Doctor Modal

| Tab | What It Does |
|---|---|
| Health & Diagnostics | Shows score (0-100%), count of ready vs missing tools, per-tool check grid with Ready/Missing status |
| 1-Click Stacks | Curated developer stacks. Each shows its tools with install status. One button installs all missing tools. |
| Auto-Repair Finder (RAG) | Scans environment for issues. Uses a local knowledge base to find verified fixes. Shows anomaly + 1-click fix. |

### Tab 2 — My Applications

| Feature | What It Does |
|---|---|
| Installed Apps Grid | Shows every developer tool DevEngine has detected or installed |
| Filter/Search Bar | Filter installed apps by name or category |
| Stat Cards | Total installed apps, system state, active package managers |
| Manage Button | Opens details/uninstall/update options for each app |
| Update All Button | Queues update commands for all tracked apps |
| Refresh Button | Re-queries the backend for latest installed app list |

### Tab 3 — Control Center

| Feature | What It Does |
|---|---|
| Pending Approval Queue | Every install/uninstall/update queues here before running. Shows: command, risk tier, timestamp. |
| Approve / Reject | Approve runs the command via live terminal. Reject discards with a log entry. |
| Approve All / Reject All | Batch actions for all pending items |
| Risk Filter | Filter queue by High / Medium / Low risk |
| Audit Trail | Immutable log of every operation. Exportable as CSV or JSON. |
| System Snapshots | Environment snapshots saved before high-risk actions |
| Create Manual Snapshot | Create a named restore point at any time |
| Compare Snapshots (Diff) | Select two snapshots and see what changed |
| Live Terminal | macOS-style terminal modal with real-time streaming output |

### Tab 4 — Settings

| Feature | What It Does |
|---|---|
| Theme Selector | 4 themes: Dark Glass, OLED Pure Black, Aurora Nebula, Light Frosted |
| Trust Tier Policies | Configure auto-approve vs. always-require-approval per operation type |
| Environment Information | Shows host OS, architecture, hostname, active package managers |

---

## Project Structure

```
devtools-control-center/
|
+-- backend/                        <- Python FastAPI server
|   +-- main.py                     <- Server entry point, CORS, static file serving
|   +-- routes_devtools.py          <- All DevTools API endpoints (/api/devtools/*)
|   +-- routes_control_center.py    <- Control Center endpoints (/api/control-center/*)
|   |
|   +-- pkg_discovery.py            <- Live multi-registry search (Winget, NPM, PyPI)
|   +-- pkg_resolution.py           <- Package resolution pipeline
|   +-- pkg_catalog.json            <- Curated local catalog of developer tools
|   |
|   +-- devtools_manager.py         <- Managed apps lifecycle & update streaming
|   +-- rag_engine.py               <- Local RAG knowledge base for auto-repair
|   +-- risk_engine.py              <- Command risk classification (Low/Medium/High)
|   +-- sandbox.py                  <- Dry-run simulation engine
|   +-- snapshot.py                 <- Environment snapshot capture & diff
|   |
|   +-- adapters/                   <- Per-package-manager adapters
|   |   +-- registry.py             <- Detects active package managers on the host
|   |
|   +-- knowledge.db                <- SQLite: RAG knowledge base (auto-generated)
|   +-- resolution_cache.db         <- SQLite: search cache (auto-generated)
|   +-- requirements.txt            <- Python dependencies
|   +-- .venv/                      <- Virtual environment (created during setup)
|
+-- frontend/                       <- Pure HTML/CSS/JS single-page application
|   +-- index.html                  <- App shell, all views, all modals
|   +-- style.css                   <- Full glassmorphic design system
|   +-- main.js                     <- All client-side logic (1600+ lines)
|
+-- tests/                          <- Automated test suite
|   +-- test_api.py                 <- 19 pytest unit tests (100% pass)
|   +-- test_runner.py              <- 23 live HTTP integration tests (100% pass)
|
+-- README.md                       <- This file
```

---

## Getting Started on a New Machine

### Prerequisites

Only **Python 3.10 or newer** is required.

- Download Python: https://www.python.org/downloads/
- During installation on Windows: check "Add Python to PATH"

### Step 1 — Copy the project folder

Copy the entire `devtools-control-center/` folder to the new machine.

Note: You can safely delete `backend/snapshots/` before copying — it contains environment data from the original machine. The app will create new snapshots automatically.

### Step 2 — Create the virtual environment

Open a terminal in the `devtools-control-center/` folder and run:

**Windows (PowerShell or Command Prompt):**
```powershell
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
```

**macOS / Linux:**
```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

### Step 3 — Run the server

**Windows:**
```powershell
backend\.venv\Scripts\python backend\main.py
```

**macOS / Linux:**
```bash
backend/.venv/bin/python backend/main.py
```

### Step 4 — Open the app

Open your browser at: **http://127.0.0.1:8790**

---

## How to Run (after setup)

**Windows:**
```powershell
cd devtools-control-center
backend\.venv\Scripts\python backend\main.py
```

**macOS / Linux:**
```bash
cd devtools-control-center
backend/.venv/bin/python backend/main.py
```

Then visit: **http://127.0.0.1:8790**

### Custom port or network access

```powershell
# Custom port
set API_PORT=9000
backend\.venv\Scripts\python backend\main.py

# Allow other devices on your network to access the app
set API_HOST=0.0.0.0
backend\.venv\Scripts\python backend\main.py
```

---

## API Reference

Backend base URL: `http://127.0.0.1:8790`

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Server health check |
| GET | /api/status/system | OS info, hostname, active package managers |
| GET | /api/devtools/catalog | Full curated tool catalog |
| GET | /api/devtools/status | Installation status of all catalog tools |
| GET | /api/devtools/search?q=QUERY | Live online search across Winget, NPM, PyPI |
| POST | /api/devtools/resolve | AI-scored package resolution |
| POST | /api/devtools/extract | Extract install recipe from a tool name |
| GET | /api/devtools/details?tool=NAME | Full details for a specific tool |
| GET | /api/devtools/doctor | Dev environment health scan |
| POST | /api/devtools/doctor/install-stack | Queue a full 1-click stack installation |
| GET | /api/devtools/managed | List DevEngine-managed installed apps |
| POST | /api/devtools/execute-stream | Run a command with SSE live output stream |
| GET | /api/devtools/rag/knowledge | Query the local RAG knowledge base |
| GET | /api/devtools/auto-repair | Get RAG-powered repair suggestions |
| POST | /api/devtools/sandbox/dry-run | Simulate a command without executing it |
| GET | /api/control-center/queue | List approval queue |
| POST | /api/control-center/queue | Add a new action to the queue |
| POST | /api/control-center/approve/{id} | Approve an action |
| POST | /api/control-center/reject/{id} | Reject an action |
| POST | /api/control-center/batch-approve | Approve all pending |
| POST | /api/control-center/batch-reject | Reject all pending |
| GET | /api/control-center/audit | Get audit trail |
| GET | /api/control-center/audit/export | Export as CSV or JSON |
| GET | /api/control-center/snapshots | List snapshots |
| POST | /api/control-center/snapshots | Create a manual snapshot |
| GET | /api/control-center/snapshots/diff | Compare two snapshots |
| GET | /api/control-center/trust-tiers | Get trust tier configuration |
| POST | /api/control-center/trust-tiers | Update trust tier policy |

---

## Customization

### Add a new tool to the catalog

Edit `backend/pkg_catalog.json`:
```json
{
  "name": "My Tool",
  "icon": "MT",
  "description": "What this tool does.",
  "category": "cli",
  "url": "https://mytool.io",
  "version": "1.0.0",
  "popular": false,
  "trending": false,
  "statusKey": "mytool",
  "winget_id": "Publisher.MyTool",
  "npm_pkg": null,
  "pip_pkg": null
}
```

Category values: `ides`, `languages`, `frameworks`, `databases`, `devops`, `vcs`, `cli`, `testing`

### Change the default port

Set environment variable `API_PORT` before running the server.

---

## Testing

```powershell
# Run unit tests (no running server needed)
backend\.venv\Scripts\pytest tests\test_api.py -v

# Run live integration tests (server must be running)
backend\.venv\Scripts\python tests\test_runner.py
```

Expected: **19/19 unit tests** and **23/23 integration tests** passing.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "Python is not recognized" | Reinstall Python and check "Add Python to PATH" |
| "Port 8790 already in use" | Use `set API_PORT=8791` before running |
| "Module not found" | Re-run `pip install -r backend\requirements.txt` |
| App shows "Backend Offline" | Start the server first |
| Search shows no online results | Requires internet. Local catalog works offline. |
| winget commands fail on Mac/Linux | Winget is Windows-only. The app auto-detects brew/apt on other platforms. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Frontend | Vanilla HTML5, CSS3 (Glassmorphic), Vanilla JavaScript (ES2022) |
| Database | SQLite (knowledge.db, resolution_cache.db) |
| Package Search | Winget CLI, NPM Registry API, PyPI JSON API |
| Testing | Pytest, HTTPX |

---

MIT License. Free to use, modify, and distribute.
