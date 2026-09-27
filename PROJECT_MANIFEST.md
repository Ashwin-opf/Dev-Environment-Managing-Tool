# PC Doctor — Project Manifest & System Architecture Reference

**Document Version**: 1.0.0  
**Status**: Frozen Baseline (Phase 15.2A)  
**Target Systems**: Windows 11, Linux (Debian/Ubuntu, Fedora, Arch, openSUSE, Alpine), macOS (13+ Ventura, Sonoma, Sequoia)  

---

## 1. Directory Structure

```text
pc-doc/
├── backend/                             # Python FastAPI analytical and remediation core
│   ├── adapters/                        # Package manager adapter drivers
│   │   ├── base.py                      # BaseAdapter abstract contract
│   │   ├── winget.py, choco.py, scoop.py # Windows package managers
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
│   ├── test_elevation_architecture.py                        # UAC / sudo privilege management
│   ├── test_execution_pipeline_consolidation.py              # Centralized mutation boundary tests
│   └── ...                                                  # Additional integration & unit tests
├── scratch/                             # Machine-readable research datasets & evidence
│   ├── phase15_results.json             # N=75 canonical evaluation records
│   ├── phase15_1_claim_matrix.json      # Audited research claim matrix (IEEE publication)
│   ├── phase15_2a_postfix_evidence.json # Post-fix reconciliation machine-readable record
│   ├── test_postfix_rq5_live.py         # Live production post-fix RQ5 test script
│   └── test_windows_native_live.py      # Bare-metal Windows native validation suite
├── main.py                              # Backend startup entry point (FastAPI server on 8765)
├── README.md                            # High-level project summary
├── TEAM_HANDOFF.md                      # Comprehensive team handoff guide
├── PROJECT_MANIFEST.md                  # This document
├── .env.example                         # Environment configuration template
└── pytest.ini                           # Test runner configuration
```

---

## 2. Important Entry Points

| Subsystem | Entry Point File | Description | Verification Method |
| :--- | :--- | :--- | :--- |
| **Backend Server** | [`main.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/main.py) | Initializes FastAPI app, mounts routes, starts Uvicorn on `127.0.0.1:8765` | Run `python main.py` |
| **Frontend Shell** | [`frontend/index.html`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/frontend/index.html) | Single-page UI with diagnosis dashboard, repair console, and settings | Serve via Tauri or `npm run dev` |
| **Tauri Desktop** | [`src-tauri/src/main.rs`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/src-tauri/src/main.rs) | Rust binary: spawns Python backend child process, creates native window | Run `npm run tauri dev` |
| **Execution Engine**| [`backend/execution_engine.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/execution_engine.py) | Sole mutation boundary (`CentralizedExecutionEngine`) | Covered by regression suites |
| **Safety Gate** | [`backend/authoritative_safety.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/authoritative_safety.py) | Intercepts commands against blacklist and OS policies before execution | Verified via `test_phase14_system_hardening.py` |
| **Verification** | [`backend/verification_engine.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/verification_engine.py) | 5-level post-mutation verification engine (`AuthoritativeVerificationEngine`) | Verified via `test_phase15_2_verification_precedence_regression.py` |

---

## 3. Database & Static Knowledge Architecture

PC Doctor relies on a local SQLite static database to provide deterministic, verified remediation:
- **Location**: `backend/knowledge.db`
- **Tables**:
  - `canonical_recipes`: Verified golden recipes (`STATIC_DB`) for canonical developer tools with trust scores $\ge 0.90$.
  - `problem_taxonomy`: Definitions, categories, and feasibility classifications for all 75 canonical problems.
  - `tool_identities`: Tool metadata, aliases, executable filenames, and probe arguments.
- **Determinism**: The application functions 100% autonomously offline using local database recipes, without requiring active internet connectivity or external LLM API calls for standard repairs.

---

## 4. AI & Dynamic Provider Architecture

When users query the AI assistant or encounter uncataloged developer environment problems:
- **Location**: `backend/routes_ai.py` and `backend/ai/`
- **Supported Providers**: OpenAI (`gpt-4o`), Google Gemini (`gemini-2.0-flash`), Anthropic Claude (`claude-3-5-sonnet`), NVIDIA NIM (`meta/llama-3.1-70b-instruct`), and Local Ollama.
- **Strict Provenance Boundary**: All recipes proposed by AI models are classified as `ProvenanceSource.AI_RAG` or `ProvenanceSource.WEB_RAG` with low initial trust scores ($< 0.85$). They **strictly require explicit user approval** (`approved=True`) and must pass the Live Safety Gate before execution.

---

## 5. Build & Run Commands

```bash
# 1. Install Backend Dependencies
python -m venv backend/.venv
backend\.venv\Scripts\activate
pip install -r backend/requirements.txt

# 2. Install Frontend Dependencies
cd frontend
npm install
cd ..

# 3. Launch Backend in Development Mode
python main.py

# 4. Launch Full Tauri Desktop Application
npm run tauri dev

# 5. Run Test Regression Suite
python -m pytest tests/test_phase15_2_verification_precedence_regression.py tests/test_phase15_research_evaluation.py
python -m pytest -q

# 6. Production Bundle Build
cd frontend && npm run build && cd ..
npm run tauri build
```

---

## 6. Known Limitations & Research Boundaries

1. **Hardware & OS Asymmetry**: Native bare-metal live execution was comprehensively validated on Windows 11 AMD64. Linux (APT, DNF, Pacman, Zypper, APK) and macOS (Homebrew, `/Applications` bundles) capabilities are validated via formal contract and mock test suites. Live field deployment on physical Linux and macOS hardware remains an avenue for future extension.
2. **75-Problem Taxonomy Scope**: The system addresses the 75 canonical scenarios defined in the research taxonomy. Uncataloged third-party software with custom proprietary installers falls back to human-guided review.
3. **Hardware & Kernel Drivers**: In accordance with safety policies, low-level kernel driver installations (e.g., NVIDIA GPU display drivers, BIOS updates) route strictly to human-guided instructions rather than automated unattended mutation.
