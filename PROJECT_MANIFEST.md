# PC Doctor — Project Manifest & System Architecture Reference

**Document Version**: 1.1.0 (Phase 15.3 Re-Freeze)  
**Status**: Frozen Baseline (Phase 15.3)  
**Target Systems**: Windows 11, Linux (Debian/Ubuntu, Fedora, Arch, openSUSE, Alpine), macOS (13+ Ventura, Sonoma, Sequoia)  
**Current Commit**: `b31ca277db4226c04aedbac5b2787a5611cd8c31` (and subsequent handoff documentation commit)  

---

## 1. Directory Structure

```text
pc-doc/
├── .github/                             # Continuous Integration workflows
│   └── workflows/
│       ├── cross-platform-validation.yml# Authoritative Phase 15.3 multi-OS matrix workflow
│       ├── release_candidate.yml        # Release candidate packaging workflow
│       ├── stage8_1_linux.yml           # Linux live validation workflow
│       └── stage8_1_macos.yml           # macOS live validation workflow
├── backend/                             # Python FastAPI analytical and remediation core
│   ├── adapters/                        # Package manager adapter drivers
│   │   ├── base.py                      # BaseAdapter abstract contract
│   │   ├── winget.py, choco.py, scoop.py# Windows package managers
│   │   ├── apt.py, dnf.py, pacman.py    # Linux distribution package managers
│   │   ├── zypper.py, apk.py            # Extended Linux providers (openSUSE, Alpine)
│   │   ├── brew.py                      # macOS Homebrew adapter
│   │   ├── pip.py, npm.py, cargo.py     # Language-level package managers
│   │   └── registry.py                  # Dynamic adapter discovery & active registry
│   ├── platform_abstraction/            # OS-specific abstraction layer
│   │   ├── base.py                      # PlatformAdapter base class
│   │   ├── windows/                     # Windows services, registry, and UAC elevation
│   │   ├── linux/                       # Linux distributions, os-release, and sudo providers
│   │   └── macos/                       # macOS Homebrew and bundle detection
│   ├── execution_engine.py              # CentralizedExecutionEngine (Sole Mutation Boundary)
│   ├── execution_plan.py                # ExecutionResolver & ExecutionPlan definitions
│   ├── execution_tier.py                # Execution tier specifications (Tier 1-3, Blocked)
│   ├── authoritative_safety.py          # Pre-execution live safety gate & hard blacklists
│   ├── verification_engine.py           # Multi-level authoritative post-mutation verification
│   ├── state_refresh.py                 # Tool & machine state refresher and cache invalidation
│   ├── multi_source_manager.py          # Multiple installation source detector & migration
│   ├── managed_footprint.py             # Residual cleanup & managed footprint registry
│   ├── canonical_identity.py            # Canonical tool identity mapper & store
│   ├── recipe_engine.py                 # Golden recipe catalog & recipe resolver
│   ├── repair_engine.py                 # RepairEngine dispatcher and executor
│   ├── routes_system.py                 # FastAPI system routes (/api/execute, devtools)
│   ├── routes_shce.py                   # Self-Healing Command Engine endpoints
│   ├── routes_agent.py                  # Agent goal runner and tool execution endpoints
│   ├── routes_ai.py                     # AI diagnostic chat and suggestions
│   ├── knowledge.db                     # SQLite static golden recipe database
│   ├── knowledge_static.db              # Sealed static knowledge partition
│   └── requirements.txt                 # Python backend package dependencies
├── frontend/                            # Web frontend user interface
│   ├── index.html                       # Application shell and single-page container
│   ├── main.js                          # Frontend client logic and API integration
│   ├── style.css                        # Modern CSS styling, glassmorphism, responsive UI
│   ├── animations.js                    # UI micro-animations and status transitions
│   └── package.json                     # Frontend build scripts and tooling
├── src-tauri/                           # Rust desktop application wrapper (Tauri 2)
│   ├── src/
│   │   ├── main.rs                      # Native application entry point & process supervision
│   │   └── lib.rs                       # IPC command handlers and lifecycle hooks
│   ├── Cargo.toml                       # Rust crate dependencies
│   └── tauri.conf.json                  # Window configuration, capabilities, and bundling specs
├── tests/                               # Comprehensive automated test suite
│   ├── test_phase15_2_verification_precedence_regression.py  # Phase 15.2 verification precedence
│   ├── test_phase15_research_evaluation.py                   # Phase 15 RQ1-RQ8 research evaluations
│   ├── test_phase14_system_hardening.py                      # Phase 14 centralized pipeline & safety
│   ├── test_phase13_1_problem54_linux_outdated_repo.py       # Problem #54 contract test suite
│   ├── test_phase13_1_problem56_multiple_sources.py          # Problem #56 multi-source contract suite
│   ├── test_phase13_1_trusted_authorization.py               # Provenance trust & authorization
│   ├── test_cross_platform_validation.py                     # Stage 8 / cross-platform contracts
│   ├── test_authoritative_safety_hardening.py                # Pre-execution safety gate tests
│   └── ...                                                  # Additional integration & unit tests
├── scratch/                             # Machine-readable research datasets & evidence
│   ├── run_phase15_3_cross_platform_ci.py                    # Phase 15.3 authoritative CI runner
│   ├── phase15_3_cross_platform_ci_results.json              # Phase 15.3 structured JSON evidence
│   ├── phase15_3_cross_platform_ci_results.csv               # Phase 15.3 structured CSV evidence
│   ├── phase15_2a_postfix_evidence.json                      # Post-fix reconciliation record
│   ├── phase15_2a_postfix_evidence.csv                       # Post-fix reconciliation table
│   ├── phase15_1_claim_matrix.json                           # Audited research claim matrix (IEEE)
│   ├── phase15_results.json                                  # N=75 canonical evaluation records
│   ├── test_postfix_rq5_live.py                              # Live production post-fix RQ5 test script
│   └── test_windows_native_live.py                           # Bare-metal Windows native validation suite
├── README.md                            # High-level project summary
├── TEAM_HANDOFF.md                      # Comprehensive team handoff guide
├── PROJECT_MANIFEST.md                  # This document
├── PHASE_15_3_CROSS_PLATFORM_CI_VALIDATION.md # Phase 15.3 validation report
├── PHASE_15_2A_POSTFIX_EVIDENCE_RECONCILIATION.md # Phase 15.2A post-fix report
├── PHASE_15_2_INDEPENDENT_CODE_AND_CROSS_PLATFORM_VALIDATION.md # Phase 15.2 report
├── PHASE_15_1_PUBLICATION_EVIDENCE_AUDIT.md # Phase 15.1 publication audit report
├── PHASE_15_FINAL_RESEARCH_EVALUATION.md # Phase 15 research evaluation report
├── .env.example                         # Environment configuration template
└── pytest.ini                           # Test runner configuration
```

---

## 2. Important Entry Points

| Subsystem | Entry Point File | Description | Verification Method |
| :--- | :--- | :--- | :--- |
| **Backend Server** | [`backend/main.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/main.py) | Initializes FastAPI app, mounts routes, starts Uvicorn on `127.0.0.1:8765` | Run `python backend/main.py` |
| **Frontend Shell** | [`frontend/index.html`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/frontend/index.html) | Single-page UI with diagnosis dashboard, repair console, and settings | Serve via Tauri or `npm run dev` |
| **Tauri Desktop** | [`src-tauri/src/main.rs`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/src-tauri/src/main.rs) | Rust binary: spawns Python backend child process, creates native window | Run `npm run tauri dev` |
| **Execution Engine**| [`backend/execution_engine.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/execution_engine.py) | Sole mutation boundary (`CentralizedExecutionEngine`) | Covered by regression suites |
| **Safety Gate** | [`backend/authoritative_safety.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/authoritative_safety.py) | Intercepts commands against blacklist and OS policies before execution | Verified via `test_authoritative_safety_hardening.py` |
| **Verification** | [`backend/verification_engine.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/verification_engine.py) | 5-level post-mutation verification engine (`AuthoritativeVerificationEngine`) | Verified via `test_phase15_2_verification_precedence_regression.py` |
| **CI Runner** | [`scratch/run_phase15_3_cross_platform_ci.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/scratch/run_phase15_3_cross_platform_ci.py) | Authoritative cross-platform evaluation script | Run `python scratch/run_phase15_3_cross_platform_ci.py` |

---

## 3. Database & Static Knowledge Architecture

PC Doctor relies on a local SQLite static database to provide deterministic, verified remediation:
- **Location**: `backend/knowledge.db`
- **Tables**:
  - `canonical_recipes`: Verified golden recipes (`STATIC_DB`) for canonical developer tools with trust scores $\ge 0.90$.
  - `failure_patterns`: Symptom signatures matching environment errors to canonical problem IDs (1–75).
- **Seeding & Maintenance**:
  ```bash
  python backend/populate_static_db.py
  ```

---

## 4. Setup, Run, Build, and Test Commands

### 4.1 Setup Environment
```bash
# Python backend virtualenv
python -m venv backend/.venv
# Windows:
backend\.venv\Scripts\Activate.ps1
# POSIX:
source backend/.venv/bin/activate
pip install -r backend/requirements.txt pytest httpx

# Frontend dependencies
cd frontend && npm install && cd ..
```

### 4.2 Run in Development
```bash
# Backend standalone
python backend/main.py

# Tauri desktop application
npm run tauri dev
```

### 4.3 Automated Test Execution
```bash
# Phase 15.3 Authoritative Cross-Platform CI Runner:
python scratch/run_phase15_3_cross_platform_ci.py

# Targeted core cross-platform test suites:
pytest tests/test_cross_platform_validation.py \
       tests/test_authoritative_safety_hardening.py \
       tests/test_phase15_2_verification_precedence_regression.py \
       tests/test_phase13_1_problem54_linux_outdated_repo.py \
       tests/test_phase13_1_problem56_multiple_sources.py \
       tests/test_platform_abstraction_contracts.py -q
```

### 4.4 Build Production Bundle
```bash
# Frontend build
cd frontend && npm run build && cd ..

# Tauri desktop build
npm run tauri build
```
