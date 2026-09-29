# PC Doctor — Team Handoff & Project Freeze Documentation

**Date**: September 29, 2026  
**Document Version**: 1.2.0 (Phase 15.5 Desktop Packaging & Distribution)  
**Repository**: `https://github.com/Ashwin-opf/Dev-Environment-Managing-Tool.git`  
**Current Branch**: `main`  
**Frozen Baseline Git Commit**: `b31ca277db4226c04aedbac5b2787a5611cd8c31` (and subsequent packaging commits)  
**Host Architecture Validated**: Windows 11 Pro 64-bit AMD64 (Build 10.0.26200 / 22631)  

---

## 1. Project Overview

**PC Doctor** is an autonomous developer environment diagnosis, repair, and verification desktop system built with a high-performance **Rust / Tauri 2** native application shell, a **FastAPI / Python 3.12+** core analytical backend, and a modern, responsive **HTML5/CSS3/Vanilla JS** frontend interface.

PC Doctor identifies, isolates, remediates, and authoritatively verifies 75 canonical developer environment failure modes across package managers, runtime toolchains, PATH corruptions, service failures, configuration drifts, and version conflicts.

---

## 2. Current Status & Engineering Freeze

The PC Doctor engineering and research implementation is **formally frozen** following the completion of Phase 12.1 through Phase 15.5:

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
Phase 15.3   — Cross-Platform Validation via GitHub Actions & External OS Environments
Phase 15.5   — Cross-Platform Desktop Packaging & Real Distribution Artifacts
```

All 75 canonical problem definitions, execution tier boundaries, safety gate invariants, verification precedence rules, and cross-platform CI pipelines are established, validated, and protected by permanent regression tests.

---

## 3. Core Architecture

### 3.1 Authoritative Mutation Boundary
`CentralizedExecutionEngine` (`backend/execution_engine.py`) serves as the **sole and exclusive developer-environment mutation boundary** across the entire codebase.

- An exhaustive audit of all process-spawning and execution primitives confirmed that **100% of mutating operations** route through `CentralizedExecutionEngine._run_subprocess` and `CentralizedExecutionEngine._stream_subprocess`.
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

### 3.3 Authoritative Verification Precedence (Phase 15.2 Fix)
Post-mutation verification follows strict precedence:
1. `verif_res` (`verification_engine.verify_tool`) is strictly authoritative when present.
2. If `returncode == 0` but verification fails (missing binary, runtime crash, probe timeout), `final_status` is forced to `VERIFICATION_FAILED` or `VERIFICATION_TIMEOUT` with `success = False`.
3. Generic execution success fallbacks cannot override authoritative verification results.
4. Mutation commands execute exactly once (`mutation_count == 1`); verification retries execute read-only probes and **never repeat the mutation**.

---

## 4. Cross-Platform Evidence Status

The table below reflects the actual evidence established across all evaluated platforms under Phase 15.3:

| # | Capability | Windows Local | Windows CI | Linux CI | macOS CI | Evidentiary Basis |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Detection** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Host platform adapter, kernel, and machine signals parsed live |
| **2** | **Version probing** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Direct executable probe on `git`, `python`, `node`, `cargo`, `rustc` |
| **3** | **Provider selection** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` (APT) / `CONTRACT_VALIDATED` (others) | `GITHUB_HOSTED_MACOS` | WinGet (Windows), Homebrew (Darwin), APT (Ubuntu); DNF/Pacman/Zypper/APK contracts |
| **4** | **Installation** | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | Formal provider contract suites; no uncoordinated CI package mutations |
| **5** | **Update** | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | Formal provider contract suites; safe upgrade syntax verified |
| **6** | **Uninstall** | `NATIVE_WINDOWS` (policy) / `CONTRACT_VALIDATED` | `GITHUB_HOSTED_WINDOWS` (policy) / `CONTRACT_VALIDATED` | `GITHUB_HOSTED_LINUX` (policy) / `CONTRACT_VALIDATED` | `GITHUB_HOSTED_MACOS` (policy) / `CONTRACT_VALIDATED` | Invariant: External unmanaged source routes to REVIEW_REQUIRED (0 deletions) |
| **7** | **Verification** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Normal pass + Phase 15.2 precedence defect regression (exit 0 + probe fail -> VERIFICATION_FAILED) |
| **8** | **Rescan** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Post-repair machine state and tool rescan executed on live host |
| **9** | **Safety Gate** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Destructive commands (`rm -rf /`, `del System32`) & Wrong-OS commands blocked (0 subprocesses) |
| **10** | **Centralized mutation**| `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Sole mutation boundary audit: all recipes dispatch via CentralizedExecutionEngine |
| **11** | **Multiple sources** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | MultiSourceDetector resolves active PATH; flags shadowed/redundant binaries |
| **12** | **#54 (Outdated Repo)** | `CONTRACT_VALIDATED` | `CONTRACT_VALIDATED` | `GITHUB_HOSTED_LINUX` (APT) / `CONTRACT_VALIDATED` (others) | `CONTRACT_VALIDATED` | Multi-step refresh plan: refresh metadata first, update package, probe version |
| **13** | **#56 (Multi-Source)** | `NATIVE_WINDOWS` | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Safe migration invariant: target source verified BEFORE redundant source removal |
| **14** | **Tauri build** | `STATIC_ANALYSIS_ONLY`* | `GITHUB_HOSTED_WINDOWS` | `GITHUB_HOSTED_LINUX` | `GITHUB_HOSTED_MACOS` | Frontend production bundle verified; cargo check verified on hosted runners |

*\*Note on Tauri Local Windows: On the local developer machine, corporate/sandbox Windows Application Control (AppLocker / WDAC) policies prevent custom build scripts from executing within `src-tauri/target/debug/build/` (os error 4551). In contrast, GitHub-hosted virtual runners operate without application control restrictions and compile the Tauri crate without issue.*

### 4.1 Explicit Evidence Distinction
- **No False Native Claims**: GitHub-hosted Linux (`ubuntu-latest`) and macOS (`macos-latest`) runners provide authentic OS system calls and execution environments, but they are virtualized hosted environments rather than physical hardware.
- **Physical Machine Validation Reserved**: Results on bare-metal physical Linux or macOS machines will be recorded separately as `SELF_HOSTED_NATIVE` or `NATIVE_LIVE`.
- **Containers & Emulators**: Neither WSL2 nor Docker is presented as native macOS or bare-metal Linux.

---

## 5. Remaining Work for Team

The remaining engineering work relates strictly to **extended physical platform validation**:

1. **Bare-Metal Physical Linux Validation (`SELF_HOSTED_NATIVE` / `NATIVE_LIVE`)**:
   - Execute live package manager integrations directly on native Linux physical hardware (Ubuntu/Debian via APT, Fedora/RHEL via DNF, Arch via Pacman, openSUSE via Zypper, Alpine via APK).
   - Verify native sudo elevation and `/etc/os-release` parsing under live Linux kernels.
2. **Bare-Metal Physical macOS Validation (`SELF_HOSTED_NATIVE` / `NATIVE_LIVE`)**:
   - Execute live Homebrew cask and `/Applications` bundle migrations on physical macOS hardware (Apple Silicon M-series and Intel x86_64).
   - Validate native macOS authorization dialogs and `launchctl` service management.
3. **Phase 16 — IEEE Paper Preparation**:
   - Format final empirical tables using the publication evidence from `PHASE_15_1_PUBLICATION_EVIDENCE_AUDIT.md`, `PHASE_15_2A_POSTFIX_EVIDENCE_RECONCILIATION.md`, and `PHASE_15_3_CROSS_PLATFORM_CI_VALIDATION.md`.

---

## 6. Verified Setup, Build, and Run Instructions

The following commands were tested and verified on the host system:

### 6.1 Prerequisites
- **Python**: 3.12.x or 3.13.x 64-bit
- **Node.js**: v20.x, v22.x, or v24.x (npm included)
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
pip install -r backend/requirements.txt pytest httpx
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
python backend/populate_static_db.py
```

### 6.5 Running in Development Mode
```bash
# Terminal 1: Launch FastAPI backend server (Runs on http://127.0.0.1:8765)
python backend/main.py

# Terminal 2 (Optional standalone frontend dev server):
cd frontend
npm run dev

# Full Tauri Desktop Application (Launches desktop window + manages backend):
npm run tauri dev
```

### 6.6 Running Automated Tests
```bash
# Run focused Phase 15.3 Authoritative Cross-Platform CI Runner:
python scratch/run_phase15_3_cross_platform_ci.py

# Run verification precedence & research evaluation regression:
python -m pytest tests/test_phase15_2_verification_precedence_regression.py tests/test_cross_platform_validation.py tests/test_authoritative_safety_hardening.py tests/test_phase13_1_problem54_linux_outdated_repo.py tests/test_phase13_1_problem56_multiple_sources.py tests/test_platform_abstraction_contracts.py -q

# Run complete workspace regression suite:
python -m pytest tests/ -q
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

### 6.8 Desktop Distribution Packages (Phase 15.5)

Phase 15.5 introduces pre-compiled, self-contained desktop distribution packages across Windows, Linux, and macOS. These packages bundle the complete Tauri frontend and the standalone FastAPI backend (`pc-doctor-backend`), eliminating the need for host Python, Node.js, or dev servers.

#### Windows Distribution
1. **Windows Installer (`PC_Doctor_WINDOWS_INSTALLER.exe`):**
   * Double-click the installer and follow the setup wizard.
   * Installs into `%LOCALAPPDATA%\Programs\PC Doctor`.
   * Creates Start Menu and Desktop shortcuts.
   * Automatically starts and stops the bundled backend on launch/close.
   * *Evidence Calibration (`GITHUB_HOSTED_WINDOWS`):* Validated in GitHub Actions hosted Windows runners (`windows-latest`). Local Windows validation is authoritatively established via the portable ZIP due to local developer machine WDAC/AppLocker execution policies.
2. **Windows Portable (`PC_Doctor_WINDOWS_PORTABLE.zip`):**
   * Extract the ZIP archive to any directory.
   * Double-click `run_portable.bat`.
   * The bundled standalone backend spawns automatically on `127.0.0.1:8765`, probes `/health`, and opens the application interface.
   * To shut down, press any key in the launcher console or run `stop_portable.bat`.
   * No developer Python or Node installation is required.
   * *Evidence Calibration (`NATIVE_WINDOWS & GITHUB_HOSTED_WINDOWS`):* Fully validated locally in an isolated directory and on CI runners.

#### Linux Distribution
1. **Debian / Ubuntu (`PC_Doctor_LINUX.deb`):**
   * Recommended for Debian, Ubuntu, Linux Mint, Pop!_OS, and derivatives.
   * Install via terminal:
     ```bash
     sudo dpkg -i PC_Doctor_LINUX.deb || sudo apt-get install -f
     ```
   * Launches via Application Menu or typing `pc-doctor` in terminal.
2. **Fedora / RHEL / openSUSE (`PC_Doctor_LINUX.rpm`):**
   * Recommended for RPM-based distributions (Fedora, RHEL, CentOS Stream, openSUSE).
   * Install via terminal:
     ```bash
     sudo dnf install ./PC_Doctor_LINUX.rpm   # Fedora/RHEL
     sudo zypper install ./PC_Doctor_LINUX.rpm # openSUSE
     ```
   * *Evidence Calibration (`NOT_TESTED` for native launch):* Package structure, files, and metadata are validated via `rpm -qp --info` and `rpm -qlp`. Native RPM launch testing remains marked `NOT_TESTED` in the Ubuntu CI environment, reserved for physical Fedora/RHEL hardware testing.
3. **General Portable Linux (`PC_Doctor_LINUX.AppImage`):**
   * Broad portable option across modern Linux desktop distributions.
   * Make executable and launch:
     ```bash
     chmod +x PC_Doctor_LINUX.AppImage
     ./PC_Doctor_LINUX.AppImage
     ```
   * *Compatibility Limitation:* On modern distributions (Ubuntu 22.04+, Debian 12+) where FUSE 2 is deprecated, install `libfuse2` if the AppImage prompts for FUSE support (`sudo apt install libfuse2`).
4. **Architectural Distinction Reminder:**
   * **Target Package Managers:** APT, DNF, Pacman, Zypper, and APK are supported developer-environment package managers that PC Doctor *diagnoses and repairs*.
   * **Distribution Formats:** `.deb`, `.rpm`, and `.AppImage` are the packaging formats used to *distribute the PC Doctor application itself*.

#### macOS Distribution
1. **Apple Disk Image (`PC_Doctor.dmg`):**
   * Recommended primary distribution format for macOS (Universal: Apple Silicon arm64 + Intel x86_64).
   * Double-click `PC_Doctor.dmg` to mount the disk image.
   * Drag `PC Doctor.app` into the `/Applications` folder.
   * Unmount the DMG.
2. **Signing & Notarization Status:**
   * Packages are **ad-hoc signed** for internal and team testing; they are **unnotarized** because Apple Developer certificates are deliberately excluded from the public git repository.
   * *Gatekeeper Override:* On first launch, macOS Gatekeeper may flag the unnotarized binary. Right-click `PC Doctor.app` in `/Applications` -> Click **Open** -> Click **Open** in the dialog; or run:
     ```bash
     xattr -cr /Applications/"PC Doctor.app"
     ```

#### Distribution Readiness
* **Status:** `READY FOR INTERNAL / TEAM DISTRIBUTION AND CROSS-PLATFORM CI VALIDATION`
* **Production Public Release Pre-requisite:** Public production distribution will additionally require platform-specific code signing and notarization. Windows public distribution should use a valid Authenticode certificate; SmartScreen reputation and warning behavior are controlled by Microsoft’s trust and reputation systems and are not guaranteed solely by signing. macOS distribution requires an Apple Developer ID certificate with notary service ticket stapling (`xcrun notarytool`), and Linux repository distributions require GPG signing.

---

## 7. Security Policy & Secret Management

- **Zero Tracked Secrets**: PC Doctor contains strictly **zero** embedded API keys, tokens, or credentials in tracked files or build artifacts.
- **Environment Isolation**: External AI provider API keys (OpenAI, Gemini, Anthropic, NVIDIA) are entirely optional. If used, they must be supplied via local `.env` files (see `.env.example`) or machine environment variables.
- **Pre-Execution Gate**: Hard blacklist rules intercept destructive commands (`rm -rf /`, `del System32`, `dd`, disk formatting) before any subprocess is created.
- **Telemetry Redaction**: All logged execution events automatically pass through `backend/structured_logger.py` and `backend/telemetry.py` token-redaction filters.
