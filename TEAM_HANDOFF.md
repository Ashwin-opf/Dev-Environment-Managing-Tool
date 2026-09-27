# PC Doctor — Team Handoff & Project Freeze Documentation

**Date**: September 27, 2026  
**Document Version**: 1.0.0  
**Repository**: `https://github.com/Ashwin-opf/Dev-Environment-Managing-Tool.git`  
**Current Branch**: `main`  
**Frozen Baseline Git Commit**: `02903a6fedd7def015276eaa129202761411adb9`  
**Host Architecture Validated**: Windows 11 Pro 64-bit AMD64 (Build 10.0.26200 / 22631)  

---

## 1. Project Overview

**PC Doctor** is an autonomous developer environment diagnosis, repair, and verification desktop system built with a high-performance **Rust / Tauri 2** native application shell, a **FastAPI / Python 3.13** core analytical backend, and a modern, responsive **HTML5/CSS3/Vanilla JS** frontend interface.

PC Doctor identifies, isolates, remediates, and authoritatively verifies 75 canonical developer environment failure modes across package managers, runtime toolchains, PATH corruptions, service failures, configuration drifts, and version conflicts.

---

## 2. Current Status & Engineering Freeze

The PC Doctor engineering and research implementation is **formally frozen** following the completion of Phase 15.2 and Phase 15.2A:

```text
Phase 12.1   — Final 75-Problem Taxonomy Audit & Boundary Formalization
Phase 13.1   — Empirical Re-Evaluation of Autonomous Repair Feasibility
Phase 13.1A  — Research Dataset Hardening & Artifact Alignment
Phase 14     — Final System Hardening & Centralized Execution Pipeline Consolidation
Phase 15     — Full Research Program & Ablation Evaluation
Phase 15.1   — Publication Evidence Audit & Claim Calibration
Phase 15.1A  — RQ7 Baseline Mutation Count Reconciliation
Phase 15.2   — Independent Code Audit & Cross-Platform Native Validation
Phase 15.2A  — Post-Fix Verification Evidence Reconciliation & Repository Freeze
```

All 75 canonical problem definitions, execution tier boundaries, safety gate invariants, and verification precedence rules are established, validated, and protected by permanent regression tests.

---

## 3. Core Architecture

### 3.1 Authoritative Mutation Boundary
`CentralizedExecutionEngine` (`backend/execution_engine.py`) serves as the **sole and exclusive developer-environment mutation boundary** across the entire codebase.

- An exhaustive audit of all 84 process-spawning and execution primitives confirmed that **100% of mutating operations** route through `CentralizedExecutionEngine._run_subprocess` and `CentralizedExecutionEngine._stream_subprocess`.
- The Rust/Tauri native layer (`src-tauri/`) spawns child processes strictly for backend lifecycle supervision (clearing port 8765, launching `python main.py`). Exactly **zero** developer environment mutations are executed in Rust.
- Exactly **0 mutation bypass paths** exist in the codebase.

### 3.2 End-to-End Execution Pipeline Flow
Every mutating remediation workflow traverses an invariant 11-stage pipeline:

```text
1. Detection        (Diagnostic scan identifies environment fault or drift)
       ↓
2. Decision         (Classifier maps fault to one of 75 canonical scenarios)
       ↓
3. Resolver         (ExecutionResolver evaluates recipe provenance and trust score)
       ↓
4. Plan             (ExecutionPlan assigns execution tier: Tier 1, Tier 2, Tier 3, or Blocked)
       ↓
5. Authorization    (Gate evaluates trust: verified golden recipes auto-authorize; dynamic recipes require approval)
       ↓
6. Safety Gate      (AuthoritativeSafetyLayer.live_pre_execution_gate enforces hard blacklists & platform checks)
       ↓
7. Centralized Exec (CentralizedExecutionEngine executes single subprocess within resource locks)
       ↓
8. Verification     (AuthoritativeVerificationEngine executes multi-level post-mutation probes; L1–L5)
       ↓
9. State Rescan     (refresh_tool_state / refresh_machine_state invalidates cached environment state)
       ↓
10. Result          (Structured outcome returned with authoritative verification status)
       ↓
11. Logging         (Structured telemetry event emitted to append-only log with redacted secrets)
```

### 3.3 Authoritative Verification Precedence (Phase 15.2A Fix)
Post-mutation verification follows strict precedence:
1. `verif_res` (`verification_engine.verify_tool`) is strictly authoritative when present.
2. If `returncode == 0` but verification fails (missing binary, runtime crash, probe timeout), `final_status` is forced to `VERIFICATION_FAILED` or `VERIFICATION_TIMEOUT` with `success = False`.
3. Generic execution success fallbacks cannot override authoritative verification results.
4. Mutation commands execute exactly once (`mutation_count == 1`); verification retries execute read-only probes and **never repeat the mutation**.

---

## 4. Cross-Platform Evidence Status

The table below reflects the actual evidence established across all evaluated platforms:

| Capability | Windows (Host) | Linux (WSL/Container) | macOS (Darwin) | Evidentiary Basis |
| :--- | :---: | :---: | :---: | :--- |
| **Tool & PATH Discovery** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W1: Discovered 21 valid PATH dirs, Git, Python, Node, Winget, Cargo, Rustc live on host |
| **Version Detection / Probing** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W3: Direct executable version probe on `git.exe` returned `2.55.0` live |
| **Package Manager Discovery** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W2: `winget` active system adapter; `choco`/`scoop` absent live |
| **Installation** | **CONTRACT_VALIDATED / MOCK_VALIDATED** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | Formal contract suites; no live host package mutations executed |
| **Update** | **CONTRACT_VALIDATED / MOCK_VALIDATED** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | Formal contract suites; no live host package mutations executed |
| **Uninstall** | **CONTRACT_VALIDATED / MOCK_VALIDATED** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | Formal contract suites; no live host package mutations executed |
| **Verification Failure Handling** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W7 & Live RQ5: Exit 0 targeting missing tool yields `VERIFICATION_FAILED`, 1 mutation |
| **State Rescan** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | Post-mutation tool rescan executed on live host |
| **LIVE Safety Gate (Blacklist/Wrong-OS)**| **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W4 & W5: `rmdir C:\Windows` and `sudo apt-get` intercepted before spawn |
| **Centralized Mutation Boundary** | **NATIVE_LIVE** | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | W6: `approved=False` halts execution before subprocess creation |
| **Multiple Sources (#56)** | **NATIVE_LIVE** (Discovery) / **CONTRACT_VALIDATED** (Migration) | **CONTRACT_VALIDATED** | **CONTRACT_VALIDATED** | Live host discovery; target-first migration contract (6/6 tests passed) |
| **Outdated Repo (#54)** | N/A (Linux Specific) | **CONTRACT_VALIDATED** | N/A | Problem #54 contract suite (8/8 tests passed; refresh failure halts before update) |
| **Elevation / UAC Decline** | **NATIVE_LIVE** | N/A | N/A | W8: `ShellExecuteEx` ERROR_CANCELLED (exit code 1223) yields `USER_DECLINED_ELEVATION` |

---

## 5. Remaining Work for Team

The remaining engineering work relates strictly to **extended physical platform validation**:

1. **Bare-Metal Physical Linux Validation**:
   - Execute live package manager integrations directly on native Linux distributions (Ubuntu/Debian via APT, Fedora/RHEL via DNF, Arch via Pacman, openSUSE via Zypper, Alpine via APK).
   - Verify native sudo elevation and `/etc/os-release` parsing under live Linux kernels.
2. **Bare-Metal Physical macOS Validation**:
   - Execute live Homebrew cask and `/Applications` bundle migrations on physical macOS hardware (Apple Silicon M-series and Intel x86_64).
   - Validate native macOS authorization dialogs and `launchctl` service management.
3. **Phase 16 — IEEE Paper Preparation**:
   - Format final empirical tables using the reconciled publication evidence from `PHASE_15_1_PUBLICATION_EVIDENCE_AUDIT.md` and `PHASE_15_2A_POSTFIX_EVIDENCE_RECONCILIATION.md`.

---

## 6. Verified Setup, Build, and Run Instructions

The following commands were tested and verified on the host system:

### 6.1 Prerequisites
- **Python**: 3.12.x or 3.13.x 64-bit
- **Node.js**: v20.x or v24.x (npm included)
- **Rust**: 1.80+ with `cargo` (for desktop application builds)

### 6.2 Backend Setup
```bash
# 1. Create Python virtual environment
python -m venv backend/.venv

# 2. Activate virtual environment
# Windows (PowerShell):
backend\.venv\Scripts\Activate.ps1
# Windows (CMD):
backend\.venv\Scripts\activate.bat
# Linux/macOS:
source backend/.venv/bin/activate

# 3. Install backend dependencies
pip install -r backend/requirements.txt
```

### 6.3 Frontend Setup
```bash
# Navigate to frontend and install npm packages
cd frontend
npm install
cd ..
```

### 6.4 Database Initialization
The SQLite static knowledge database is pre-populated at `backend/knowledge.db`. To verify or reset:
```bash
python -c "import sqlite3; conn = sqlite3.connect('backend/knowledge.db'); print('Tables:', conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall())"
```

### 6.5 Running in Development Mode
```bash
# Terminal 1: Launch FastAPI backend server (Runs on http://127.0.0.1:8765)
python main.py

# Terminal 2 (Optional standalone frontend dev server):
cd frontend
npm run dev

# Full Tauri Desktop Application (Launches desktop window + manages backend):
npm run tauri dev
```

### 6.6 Running Automated Tests
```bash
# Run focused verification precedence & research evaluation regression:
python -m pytest tests/test_phase15_2_verification_precedence_regression.py tests/test_phase15_research_evaluation.py

# Run targeted live post-fix RQ5 production validation:
python scratch/test_postfix_rq5_live.py

# Run targeted live Windows native capabilities:
python scratch/test_windows_native_live.py

# Run complete workspace regression suite (715 tests):
python -m pytest -q
```

### 6.7 Building Production Release Bundles
```bash
# Build frontend web assets:
cd frontend
npm run build
cd ..

# Build native desktop installers (creates installer in src-tauri/target/release/bundle/):
npm run tauri build
```

---

## 7. Security Policy & Secret Management

- **Zero Tracked Secrets**: PC Doctor contains strictly **zero** embedded API keys, tokens, or credentials in tracked files or build artifacts.
- **Environment Isolation**: External AI provider API keys (OpenAI, Gemini, Anthropic, NVIDIA) are entirely optional. If used, they must be supplied via local `.env` files (see `.env.example`) or machine environment variables.
- **Pre-Execution Gate**: Hard blacklist rules intercept destructive commands (`rm -rf /`, `del System32`, `dd`, disk formatting) before any subprocess is created.
- **Telemetry Redaction**: All logged execution events automatically pass through `backend/structured_logger.py` and `backend/telemetry.py` token-redaction filters.
