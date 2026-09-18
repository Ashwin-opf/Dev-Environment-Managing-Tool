# PLATFORM BOUNDARY & ABSTRACTION AUDIT

**Date**: 2026-09-15  
**Project**: PC Doctor  
**Status**: Architectural Analysis of Cross-Platform Abstraction Boundaries  

---

## 1. Architectural Objective

PC Doctor is designed with a tiered cross-platform abstraction model:

```
┌─────────────────────────────────────────────────────────┐
│                       Generic Core                      │
│   (execution_engine, dev_environment_detector,         │
│    risk_engine, verification_engine, recipe_engine)     │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│              Platform Abstraction Layer                 │
│         (backend/platform_abstraction/base.py)          │
│               get_platform_provider()                   │
└───────┬────────────────────┼────────────────────┬───────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│    Windows    │    │     Linux     │    │     macOS     │
│   Provider    │    │   Provider    │    │   Provider    │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│               Package Manager Adapters                  │
│       (winget, choco, scoop, apt, dnf, pacman,          │
│        brew, flatpak, snap, pip, npm, cargo)            │
└─────────────────────────────────────────────────────────┘
```

This audit evaluates how strictly current components adhere to this boundary and documents any remaining direct platform-dependent logic.

---

## 2. Platform Abstraction Layer (`backend/platform_abstraction/`)

### A. Structure & Core Contracts
- **`backend/platform_abstraction/base.py`**:
  - Defines `BasePlatformProvider` abstract interface.
  - Declares canonical contracts:
    - `get_hardware_info()`: Normalized CPU, RAM, GPU, and architecture data.
    - `check_service(name)`: Query OS service state (`Running`, `Stopped`, `NotFound`).
    - `manage_service(name, action)`: Normalized start/stop/restart/enable actions.
    - `get_disk_space(path)`: Total, used, free byte counters.
    - `get_network_interfaces()`: Normalized IP, MAC, and status listing.
    - `read_env_var(name, scope)`: Read user or machine environment variables.
    - `write_env_var(name, value, scope)`: Set persistent environment variables.
    - `is_elevated()`: Check current execution privilege level.
- **`backend/platform_abstraction/capability_matrix.py`**:
  - Declarative matrix mapping OS family (`Windows`, `Linux`, `Darwin`) to supported capabilities (e.g. `service_management`, `hardware_sensors`, `package_adapters`).
- **`backend/platform_abstraction/platform_provider.py`**:
  - Factory function `get_platform_provider()` returning the singleton concrete provider for the host OS.
- **Concrete Providers**:
  - `windows/windows_provider.py`: Implements Windows registry (`winreg`), PowerShell/WMI service inspection, and Win32 privilege checks.
  - `linux/linux_provider.py`: Implements `systemctl`/SysVinit services, `/proc` memory/CPU info, and `os.getuid() == 0` checks.
  - `macos/macos_provider.py`: Implements `launchctl` service management and `sysctl` hardware discovery.

### B. Adherence Verification
- Strictly verified by `tests/test_platform_abstraction_contracts.py` (25 tests passing).
- Guarantees that generic core modules do not directly import `winreg` or emit raw platform scripts when platform abstraction contracts exist.

---

## 3. Detailed Component Boundary Audit

### A. `backend/dev_environment_detector.py`
- **Role**: Discovers installed development runtimes (Python, Node.js, Go, Rust, Java, Docker, Git), identifies PATH misconfigurations, multiple conflicting versions, and stopped dev services.
- **Current State**: **Well-Integrated with Platform Abstraction**.
  - Verified by contracts test: imports `winreg` is 0; raw `Get-Service` is 0; raw `SetEnvironmentVariable` is 0.
  - Delegates service state queries to `get_platform_provider().check_service(...)`.
  - Delegates PATH reads to `platform_abstraction`.
- **Verdict**: **ACTIVE AUTHORITATIVE DETECTOR** (complies with platform boundary).

### B. `backend/platform_hw.py`
- **Role**: Deep low-level hardware sensor and driver inspection (NVIDIA GPU telemetry via `nvidia-smi`, WMI GPU queries on Windows, `lspci`/`lshw` queries on Linux, driver version extraction).
- **Current State**: **Direct Platform Logic (Specialized Hardware Module)**.
  - Contains OS-specific dispatch branches: `_windows_recommended_drivers`, `_linux_recommended_drivers`, `_darwin_recommended_drivers`.
  - Directly queries `nvidia-smi`, Windows WMI via `subprocess`, and Linux package databases.
  - Actively called by `routes_system.py`, `risk_engine.py`, and `test_execution_verification_sync.py`.
- **Relationship to Abstraction**:
  - Currently acts as a specialized hardware utility rather than delegating entirely through `platform_abstraction/base.py`.
  - In Phase 1+, the hardware discovery routines in `platform_hw.py` should be moved into `BasePlatformProvider.get_hardware_info()`.
- **Verdict**: **ACTIVE SPECIALIZED MODULE** (Retain; queue refactoring for Phase 1+).

### C. `backend/tool_detector.py`
- **Role**: Fast binary/heuristic tool presence detector for applications without full runtime CLI probes (VSCode, Docker Desktop, Ollama, Android Studio).
- **Current State**: **Cross-Platform Heuristic Scanner**.
  - Checks binary locations via `shutil.which`, Flatpak IDs, Snap packages, desktop file existence (`.desktop` on Linux, Start Menu shortcuts on Windows, `/Applications` on macOS).
  - Actively called by `routes_system.py`, `routes_ai.py`, `devtools_manager.py`, and `command_adaptation.py`.
- **Verdict**: **ACTIVE DETECTION UTILITY** (Retain).

---

## 4. Package Manager Adapter Audit (`backend/adapters/`)

The repository contains 12 package manager adapters in `backend/adapters/`. All 12 inherit from `BaseAdapter` and are registered in `backend/adapters/registry.py`:

| Adapter File | Target System / Ecosystem | Registered in `registry.py`? | Availability Check | Active Usage in PC Doctor | Status |
|---|---|---|---|---|---|
| `winget.py` | Windows (WinGet) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("winget")` | High (Primary Windows package tool) | **ACTIVE ARCHITECTURAL** |
| `choco.py` | Windows (Chocolatey) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("choco")` | Supported fallback for Windows | **ACTIVE ARCHITECTURAL** |
| `scoop.py` | Windows (Scoop) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("scoop")` | Supported fallback for Windows | **ACTIVE ARCHITECTURAL** |
| `apt.py` | Linux (Debian / Ubuntu) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("apt-get")` | High (Primary Debian/Ubuntu tool) | **ACTIVE ARCHITECTURAL** |
| `dnf.py` | Linux (RHEL / Fedora) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("dnf")` | Supported Linux distribution adapter | **ACTIVE ARCHITECTURAL** |
| `pacman.py` | Linux (Arch Linux) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("pacman")` | Supported Linux distribution adapter | **ACTIVE ARCHITECTURAL** |
| `brew.py` | macOS / Linux (Homebrew) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("brew")` | High (Primary macOS package tool) | **ACTIVE ARCHITECTURAL** |
| `flatpak.py` | Linux (Flatpak) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("flatpak")` | Desktop application sandbox adapter | **ACTIVE ARCHITECTURAL** |
| `snap.py` | Linux (Snapcraft) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("snap")` | Canonical snap package adapter | **ACTIVE ARCHITECTURAL** |
| `pip.py` | Universal (Python PyPI) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("pip")` | Language runtime package manager | **ACTIVE ARCHITECTURAL** |
| `npm.py` | Universal (Node.js NPM) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("npm")` | Language runtime package manager | **ACTIVE ARCHITECTURAL** |
| `cargo.py` | Universal (Rust Crates) | **Yes** (`ALL_ADAPTER_CLASSES`) | `shutil.which("cargo")` | Language runtime package manager | **ACTIVE ARCHITECTURAL** |

### Findings & Decision on Adapters:
- As dictated by Task 0.5 rules: *"Do not remove unused adapters just because no current MVP test uses them. If they are intended architecture components and registered for future/current operations, keep them."*
- Every adapter in `backend/adapters/` is cleanly registered in `registry.py` and accessed dynamically via `get_all_active_adapters()`, `get_adapter(name)`, and `get_system_adapter()`.
- **Verdict**: **ALL 12 ADAPTERS ARE RETAINED AS INTENDED ARCHITECTURAL COMPONENTS**.
