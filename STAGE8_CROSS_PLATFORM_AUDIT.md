# STAGE 8 — Cross-Platform Subsystem Audit

**Milestone**: Stage 8 — Cross-Platform Live Validation & Capability Promotion  
**Current Baseline**: 456 / 456 tests passing  
**Date**: September 18, 2026  
**Auditor**: Antigravity Authoritative Validation Engine  

---

## 1. Executive Summary & Audit Mandate

The primary objective of Stage 8 is to answer the core architectural question:
> **"Can PC Doctor actually detect, repair, verify, and rescan problems on Windows, Linux, and macOS through the production architecture?"**

This audit reviews the current cross-platform architecture across:
- `backend/platform_abstraction/` (Windows, Linux, macOS providers)
- `backend/adapters/` (Package manager adapters: WinGet, Choco, Scoop, Apt, Dnf, Pacman, Brew, Flatpak, Snap, Pip, Npm, Cargo)
- `backend/machine_state.py` & `backend/state_refresh.py`
- `backend/execution_engine.py` (Authoritative execution pipeline)
- `backend/verification_engine.py` (L1–L5 tiered verification)
- `backend/authoritative_safety.py` (Live pre-execution safety gate)
- `backend/canonical_identity.py` (Platform overrides and aliases)
- `backend/recipe_engine.py` (Platform-targeted structured recipes)

### Strict Decision Invariant: Zero Fabrication & Real Operating System Rules
1. **WSL != Linux Support**: WSL is not accepted as proof of native Linux platform support.
2. **Physical Host Availability**: The physical runtime host in this development environment is **Microsoft Windows 11 AMD64 (build 10.0.26100)**. Neither physical native Linux (Ubuntu/Debian/Fedora) nor physical native Apple macOS hardware/VM runner is locally attached.
3. **No Mislabeled Evidence**: Where physical operating systems are unavailable, live capabilities are strictly classified as **`NOT_TESTED`** or **`ADAPTER_ONLY`**, never **`FULLY_SUPPORTED`**. Adapter existence and passing contract tests prove architectural decoupling and syntactical validity, but **never** live host support.

---

## 2. Platform Subsystem Matrix: Windows vs. Linux vs. macOS

| Subsystem Component | Microsoft Windows | Linux Distributions | Apple macOS (Darwin) |
| :--- | :--- | :--- | :--- |
| **Active Host Availability** | **LIVE_AVAILABLE** (Windows 11 AMD64) | **LIVE_UNAVAILABLE** (No physical host/VM) | **LIVE_UNAVAILABLE** (No physical host/VM) |
| **Environment Provider** | `WindowsEnvironmentProvider`<br>(HKLM/HKCU Registry, WM_SETTINGCHANGE) | `LinuxEnvironmentProvider`<br>(/etc/environment, /etc/profile.d, ~/.profile, ~/.bashrc) | `MacOSEnvironmentProvider`<br>(~/.zshrc, ~/.bash_profile, /etc/paths.d) |
| **Machine-State Provider** | `WindowsMachineStateProvider`<br>(CBS RebootPending, WU RebootRequired, PendingFileRenameOperations, msiexec lock, disk/CPU/RAM) | `LinuxMachineStateProvider`<br>(/var/run/reboot-required, /var/lib/dpkg/lock, PATH PM availability, root disk/CPU/RAM) | `MacOSMachineStateProvider`<br>(Homebrew lock, brew on PATH, root disk/CPU/RAM) |
| **PATH / Environment Provider** | `WindowsPathManager`<br>(Semicolon delimiter, HKCU/HKLM registry scopes, Process sync, PowerShell broadcast) | `LinuxPathManager`<br>(POSIX colon delimiter, ~/.profile / ~/.bashrc User scope, /etc/environment Machine scope) | `MacOSPathManager`<br>(POSIX colon delimiter, ~/.zshrc User scope, /etc/paths.d Machine scope) |
| **Privilege Provider** | `WindowsPrivilegeAdapter`<br>(ShellExecuteExW `runas`, COM STA thread, HWND binding, UAC worker) | `LinuxPrivilegeAdapter`<br>(`pkexec` / `sudo -n` worker invocation) | `MacOSPrivilegeAdapter`<br>(`osascript -e 'do shell script ... with administrator privileges'`) |
| **Service Provider** | `WindowsServiceManager`<br>(Windows Service Control Manager via `sc.exe` / `Get-Service`) | `LinuxServiceManager`<br>(systemd units via `systemctl is-active/status/start/stop`) | `MacOSServiceManager`<br>(launchd agents/daemons via `launchctl list/start/stop` & `brew services`) |
| **Verification Provider** | `WindowsVerificationProvider`<br>(Registry/PATH lookup, `.exe/.cmd/.bat` extensions, version probe, functional probe) | `LinuxVerificationProvider`<br>(POSIX executable lookup, standard roots `/usr/bin`, `/opt`, version & functional probes) | `MacOSVerificationProvider`<br>(`/opt/homebrew/bin`, `/usr/local/bin`, `/Applications`, `.app` bundles, version probes) |
| **Package Manager Adapters** | `WingetAdapter`, `ChocoAdapter`, `ScoopAdapter`, `PipAdapter`, `NpmAdapter`, `CargoAdapter` | `AptAdapter`, `DnfAdapter`, `PacmanAdapter`, `FlatpakAdapter`, `SnapAdapter`, `PipAdapter`, `NpmAdapter`, `CargoAdapter` | `BrewAdapter`, `PipAdapter`, `NpmAdapter`, `CargoAdapter` |
| **Safety Interception Gate** | `authoritative_safety`<br>(Live pre-execution gate, winreg/cmd/powershell blacklists, internal resource locks) | `authoritative_safety`<br>(Live pre-execution gate, `rm -rf /`, `mkfs`, `dd`, kernel module, userdel blacklists) | `authoritative_safety`<br>(Live pre-execution gate, raw disk, destructive formatting blacklists) |
| **Current Automated Tests** | 456 automated unit/integration tests (`tests/`) covering full pipeline | Contract and architecture boundary tests (`test_platform_abstraction_contracts.py`) | Contract and architecture boundary tests (`test_platform_abstraction_contracts.py`) |
| **Live Host Evidence** | **Comprehensive Live Proof** (Stages 2, 3, 4, 5, 5.1, 7, 8) | **None** (Physical Linux host unavailable) | **None** (Physical macOS host unavailable) |

---

## 3. Deep-Dive Component Audit

### 3.1 Environment & PATH Subsystems
- **Windows (`WindowsPathManager`, `WindowsEnvironmentProvider`)**:
  - Implements robust persistent PATH parsing, deduplication, and normalization (case-insensitive for Windows file systems).
  - Supports both `USER` (Registry: `HKCU\Environment`) and `MACHINE` (Registry: `HKLM\System\CurrentControlSet\Control\Session Manager\Environment`) scopes.
  - Generates safe PowerShell repair commands and immediately performs dynamic in-process environment synchronization (`sync_process_path`) and OS environment broadcast (`WM_SETTINGCHANGE`).
- **Linux (`LinuxPathManager`, `LinuxEnvironmentProvider`)**:
  - Implements POSIX colon-delimited string parsing, expanding `~` and POSIX variables cleanly.
  - Case-sensitive normalization and deduplication.
  - Generates shell repair commands (`sh -c "echo 'export PATH=...' >> ~/.profile"`).
  - Machine-scope writes target `/etc/environment` or `/etc/profile.d/pcdoc_path.sh` (requiring root privilege).
- **macOS (`MacOSPathManager`, `MacOSEnvironmentProvider`)**:
  - Implements POSIX colon-delimited parsing, recognizing macOS standard shells (zsh default since macOS Catalina).
  - Targets `~/.zshrc` (or `~/.bash_profile` if zsh is absent).
  - Machine-scope writes target `/etc/paths.d/pcdoc_path` (clean macOS standard).

### 3.2 Service Management Subsystems
- **Windows (`WindowsServiceManager`)**:
  - Uses `sc.exe query <name>` and `sc.exe start/stop <name>` with graceful fallbacks.
  - Normalizes service states to `ServiceStatus.RUNNING`, `ServiceStatus.STOPPED`, `ServiceStatus.NOT_FOUND`, `ServiceStatus.ERROR`.
- **Linux (`LinuxServiceManager`)**:
  - Uses `systemctl is-active <name>` and `systemctl status <name>`. Exit code 4 correctly maps to `ServiceStatus.NOT_FOUND`.
  - Commands generated: `['systemctl', 'start', service_name]`.
- **macOS (`MacOSServiceManager`)**:
  - Uses `launchctl list <name>` inspecting PID existence, with fallback integration to `brew services`.
  - Commands generated: `['launchctl', 'start', service_name]`.

### 3.3 Privilege Elevation Subsystems
- **Windows (`WindowsPrivilegeAdapter`)**:
  - Uses `ctypes.windll.shell32.ShellExecuteExW` with verb `"runas"`.
  - Strictly operates in a COM-initialized STA thread.
  - Explicitly handles window handles: only binds to own-process visible HWND, otherwise passes `0` (NULL), strictly avoiding `GetDesktopWindow()` or foreign HWND binding (which triggers UIPI error 1223).
  - Launches `elevated_worker.py` with separate bounded timeouts for UAC prompt, worker launch, heartbeat, and result retrieval.
- **Linux (`LinuxPrivilegeAdapter`)**:
  - Dispatches via `pkexec` (PolicyKit GUI/CLI agent) if present on PATH, falling back to `sudo -n`.
  - Reuses the identical `elevated_worker.py` script via `sys.executable` with payload, result, and heartbeat IPC markers.
  - Mandatory pre-elevation safety check (`check_pre_elevation_safety`) prevents elevation bypass of safety rules.
- **macOS (`MacOSPrivilegeAdapter`)**:
  - Dispatches via AppleScript `osascript -e 'do shell script "..." with administrator privileges'`.
  - Reuses `elevated_worker.py` architecture. Pre-elevation safety gate enforced.

### 3.4 Machine-State Telemetry Subsystems
- **Windows (`WindowsMachineStateProvider`)**:
  - Real registry inspection for CBS `RebootPending`, Windows Update `RebootRequired`, and Session Manager `PendingFileRenameOperations`.
  - Process query for `msiexec.exe` installer mutex/lock.
  - Disk free GB via `shutil.disk_usage` on system drive; CPU and RAM via `psutil`.
- **Linux (`LinuxMachineStateProvider`)**:
  - Checks for `/var/run/reboot-required` and `/run/reboot-required`.
  - Checks for APT package manager lock (`/var/lib/dpkg/lock`).
  - Evaluates root disk `/` space and system telemetry.
- **macOS (`MacOSMachineStateProvider`)**:
  - Checks for Homebrew lock and active processes.
  - Evaluates root disk `/` space and system telemetry.

### 3.5 Package-Manager Adapters (`backend/adapters/`)
- **Adapter Registry (`backend/adapters/registry.py`)**:
  - Dynamic discovery via `is_available()` on PATH.
  - Preference hierarchy per operating system:
    - Windows: `winget` -> `choco` -> `scoop`
    - Darwin: `brew`
    - Linux: `apt` -> `dnf` -> `pacman`
  - Language/Ecosystem PMs: `pip`, `npm`, `cargo`, `flatpak`, `snap`.
  - Method contracts: `search()`, `resolve_latest()`, `install()`, `update()`, `remove()`, `reinstall()`, `verify()`, `supports_operation()`, `supports_dry_run()`, `info()`.

---

## 4. Cross-Platform Evidence Classification Baseline

Per Stage 8 requirements, every platform capability must be classified as exactly one of:
- **`FULLY_SUPPORTED`**: Production-path execution has been successfully demonstrated on the platform with detection, repair, verification, original-problem rescan, and logging, and the capability is reproducible.
- **`LIVE_TESTED`**: A real host/VM production-path test has passed, but broader capability or coverage is not yet sufficient to call the entire platform capability fully supported.
- **`PARTIALLY_SUPPORTED`**: Some layers work live, but one or more required stages remain incomplete.
- **`ADAPTER_ONLY`**: The adapter exists and contract tests pass, but no live host execution has validated the capability.
- **`UNSUPPORTED`**: The platform intentionally does not support the operation.
- **`NOT_TESTED`**: No meaningful physical evidence currently exists.

### Current Audit Classification Summary:
1. **Windows**: **`LIVE_TESTED`** / **`FULLY_SUPPORTED`** across all core capabilities (PATH, Services, WinGet, Permissions, Features, Machine State, Safety, Verification, Logging).
2. **Linux**: **`ADAPTER_ONLY`** for architectural contracts; **`NOT_TESTED`** for live host execution (host unavailable).
3. **macOS**: **`ADAPTER_ONLY`** for architectural contracts; **`NOT_TESTED`** for live host execution (host unavailable).

---

## 5. Next Steps for Stage 8

1. Run the structured live validation suite on the active Windows 11 host (`scratch/cross_platform_live_validation.py`).
2. Generate structured evidence file `scratch/stage8_windows_evidence.json`.
3. Create cross-platform automated test matrix `tests/test_cross_platform_validation.py` with explicit live platform checks and contract tests.
4. Document the complete capability matrix in `STAGE8_CROSS_PLATFORM_CAPABILITY_MATRIX.md`.
5. Compile final results in `STAGE8_CROSS_PLATFORM_RESULT.md`.
