# PHASE 11.3 — Linux Package-Manager Differences (#52) & Linux Distribution Differences (#53)

**Milestone**: Phase 11.3 — Linux Platform & Package Provider Abstraction  
**Baseline**: Phase 11.2 (597 passed, 2 skipped, 0 failures)  
**Scope**: Strictly Problems #52 and #53 (Problem #55 intentionally untouched)  
**Authoritative Execution Boundary**: Frozen Centralized Pipeline (`Request → Detection → Provider Resolution → Recipe/Repair → ExecutionResolver → ExecutionPlan → Tier → Approval → Privilege → LIVE Safety Gate → Centralized Execution Engine → Verification → Rescan → Result → Logging`)  
**Direct Subprocess Mutation Bypasses**: ZERO (Linux package providers are inspection and command generation abstractions only; never direct mutation engines).

---

## 1. Problem #52 — Linux Package-Manager Differences

### 1.1 Supported Package Managers
The Linux package manager layer implements structured providers for the 5 primary Linux package management ecosystems:
1. **APT (`apt-get` / `dpkg`)**: Debian, Ubuntu, Linux Mint, Pop!_OS
2. **DNF (`dnf` / `rpm`)**: Fedora, RHEL 8+, Rocky Linux, AlmaLinux, CentOS Stream
3. **Pacman (`pacman`)**: Arch Linux, Manjaro, EndeavourOS
4. **Zypper (`zypper` / `rpm`)**: openSUSE Tumbleweed, openSUSE Leap, SUSE Linux Enterprise Server
5. **APK (`apk`)**: Alpine Linux

### 1.2 Provider Contract Interface (`LinuxPackageManagerProvider`)
All providers conform to the standardized `LinuxPackageManagerProvider` abstract contract:
- `is_available() -> bool`: Probes binary existence and PATH discoverability.
- `version() -> Optional[str]`: Retrieves active package manager version with regex parsing.
- `identify_package(canonical_id: str) -> str`: Normalizes canonical application IDs (e.g. `docker`, `nodejs`, `ripgrep`) to distribution-specific package names (e.g. `docker.io` vs `docker-ce` vs `docker`).
- `is_installed(package_name: str) -> bool`: Deterministically checks package installation via local database query (`dpkg-query`, `rpm -q`, `pacman -Q`, `apk info -e`).
- `installed_version(package_name: str) -> Optional[str]`: Retrieves installed package version.
- `candidate_version(package_name: str) -> Optional[str]`: Probes repository metadata for upstream available version (`apt-cache policy`, `dnf info`, `pacman -Si`, `zypper info`, `apk policy`).
- `install_command(package_name: str, candidate_version: Optional[str]) -> str`: Emits non-interactive install command with mandatory flags (`-y`, `--noconfirm`, `--non-interactive`).
- `update_command(package_name: str, target_version: Optional[str]) -> str`: Emits update command syntax.
- `uninstall_command(package_name: str, purge: bool) -> str`: Emits removal command (`apt-get purge -y`, `dnf remove -y`, `pacman -Rns --noconfirm`, `zypper rm -y`, `apk del`).
- `verify(package_name: str, expected_state: str, expected_version: Optional[str]) -> LinuxPackageOperationResult`: Emits verification probe results distinguishing `INSTALLED`, `REMOVED`, `VERSION_MATCH`, `WRONG_VERSION`, and `VERIFICATION_FAILED`.
- `ownership_check(binary_path: str) -> Tuple[bool, Optional[str]]`: Queries local package database to verify binary file ownership:
  - APT: `dpkg -S <path>`
  - DNF / Zypper: `rpm -qf <path>`
  - Pacman: `pacman -Qo <path>`
  - APK: `apk info -W <path>`

### 1.3 Privilege & Security Requirements
- **Privilege Declaration**: All package manager mutations (`install`, `update`, `uninstall`) declare `requires_elevation = True`.
- **Zero Command-Line Injections**: Providers NEVER inject `sudo` or `pkexec` directly into generated commands. Privilege elevation is resolved centrally by `PrivilegeProvider` and `ExecutionResolver`.
- **Deterministic Failure Classification**:
  - `PACKAGE_MANAGER_UNAVAILABLE`: Binary not on PATH or execution failed.
  - `PACKAGE_NOT_FOUND`: Package not in repository indexes.
  - `RESOURCE_LOCKED`: Lockfile held by another process (`/var/lib/dpkg/lock-frontend`, `/var/run/dnf.pid`, `/var/lib/pacman/db.lck`).
  - `REPOSITORY_UNAVAILABLE`: Network failure or unreachable mirror.
  - `PERMISSION_DENIED`: Operation rejected due to insufficient privileges.
  - `PACKAGE_OPERATION_FAILED`: Exit code non-zero with stderr details preserved.
  - `VERSION_PARSE_FAILED`: Unparseable version string.
  - `UNSUPPORTED_OPERATION`: Operation not supported by the provider.

### 1.4 Unsupported Cases & Review Trigger
- Specialty package managers (**Nix**, **Guix**, **Slackpkg**, **XBPS**, **Portage**) are explicitly marked unsupported.
- When an unsupported package manager is detected or no recognized package manager is available, resolution fails safe to `REVIEW_REQUIRED` with zero automated mutation attempts.

---

## 2. Problem #53 — Linux Distribution Differences

### 2.1 Distribution Detection & Metadata Normalization
The `LinuxDistributionProvider` inspects standard OS metadata files without raw shell execution:
- **Primary Source**: `/etc/os-release` (and `/usr/lib/os-release` fallback).
- **Safe Parsing**: Evaluates standard `KEY="VALUE"` or `KEY=VALUE` pairs with quote stripping. No `source` or `eval` execution.
- **Normalized Data Model (`LinuxDistribution`)**:
  - `distribution: str` (e.g. `ubuntu`, `fedora`, `arch`, `alpine`, `unknown`)
  - `distribution_family: LinuxDistributionFamily` (`DEBIAN`, `REDHAT`, `ARCH`, `SUSE`, `ALPINE`, `UNKNOWN`)
  - `distribution_version: Optional[str]` (e.g. `24.04`, `40`, `3.19.1`)
  - `distribution_codename: Optional[str]` (e.g. `noble`, `bookworm`, `tumbleweed`)
  - `architecture: LinuxArchitecture` (`x86_64`, `aarch64`, `armhf`, `i686`, `riscv64`, `UNKNOWN`)
  - `package_manager: Optional[LinuxPackageManagerName]` (`APT`, `DNF`, `PACMAN`, `ZYPPER`, `APK`, `UNKNOWN`)
  - `init_system: Optional[str]` (`systemd`, `openrc`, `runit`, `sysvinit`, `unknown`)
  - `is_supported: bool`

### 2.2 Distribution Families & Normalization Rules
1. **Debian Family**:
   - `ID=ubuntu`, `ID=debian`, `ID=linuxmint`, `ID=pop`, `ID_LIKE~=debian/ubuntu` → `LinuxDistributionFamily.DEBIAN` → Default PM: `APT`
2. **Red Hat Family**:
   - `ID=fedora`, `ID=rhel`, `ID=rocky`, `ID=almalinux`, `ID=centos`, `ID_LIKE~=rhel/fedora` → `LinuxDistributionFamily.REDHAT` → Default PM: `DNF`
3. **Arch Family**:
   - `ID=arch`, `ID=manjaro`, `ID=endeavouros`, `ID_LIKE~=arch` → `LinuxDistributionFamily.ARCH` → Default PM: `PACMAN`
4. **SUSE Family**:
   - `ID=opensuse-tumbleweed`, `ID=opensuse-leap`, `ID=sles`, `ID_LIKE~=suse` → `LinuxDistributionFamily.SUSE` → Default PM: `ZYPPER`
5. **Alpine Family**:
   - `ID=alpine` → `LinuxDistributionFamily.ALPINE` → Default PM: `APK`

### 2.3 Architecture Normalization
Machine architectures from `os.uname().machine` or `uname -m` are normalized to canonical standards:
- `x86_64`, `amd64`, `x64` → `LinuxArchitecture.x86_64`
- `aarch64`, `arm64`, `armv8b`, `armv8l` → `LinuxArchitecture.aarch64`
- `armv7l`, `armv6l`, `armhf` → `LinuxArchitecture.armhf`
- `i386`, `i686`, `x86` → `LinuxArchitecture.i686`
- `riscv64` → `LinuxArchitecture.riscv64`

### 2.4 Unknown Distribution & Fallback Policy
- If `/etc/os-release` is missing or contains an unrecognized `ID` with no compatible `ID_LIKE`:
  - `distribution_family` resolves to `UNKNOWN`.
  - `is_supported` resolves to `False`.
  - `LinuxPackageManagerResolver` strictly raises a review state (`REVIEW_REQUIRED`).
  - **No Blind Fallback**: The system NEVER assumes an unknown distribution is Debian-compatible.

---

## 3. Architecture & Authoritative Execution Integration

### 3.1 Architectural Separation
```text
Linux Host
    ↓
LinuxDistributionProvider (/etc/os-release)
    ↓
LinuxDistribution (Family, Version, Codename, Arch, Init)
    ↓
LinuxPackageManagerResolver (Ownership Precedence + Distro Policy)
    ↓
LinuxPackageManagerProvider (Apt, Dnf, Pacman, Zypper, Apk)
    ↓ (Emits structured command & requirements; NO subprocess spawned)
RecipeEngine / ExecutionResolver
    ↓
ExecutionPlan (Tier 2/3, approval_required=True, requires_elevation=True)
    ↓
Approval Layer (Explicit user consent)
    ↓
Privilege Layer (Elevated runner resolution)
    ↓
LIVE Safety Gate (Pre-execution validation)
    ↓
CentralizedExecutionEngine (The ONLY authoritative mutation engine)
    ↓
Verification Engine (Provider probe + functional verification)
    ↓
State Rescan & Logging
```

### 3.2 Proof of Mutation Boundary Preservation
- **AST and Unit Verification**: `LinuxPackageManagerProvider` and its concrete subclasses contain zero imports of `subprocess`, `os.system`, or `pty`.
- **Safety Gate Integration**: An unapproved execution request (`approved=False`) for any Linux package manager command entering `ExecutionResolver` and `CentralizedExecutionEngine` yields `outcome.status == "APPROVAL_REQUIRED"` and executes ZERO child processes.

---

## 4. Cross-Platform Evidence Classification

| Platform | Evidence Classification | Scope & Verification Details |
| :--- | :--- | :--- |
| **Windows** | `LIVE_NATIVE` / `TEST_VALIDATED` | Host development platform; 42 actionable repairs verified on live environment; all regression suites pass. |
| **Linux** | `CONTRACT_VALIDATED` / `MOCK_UNIT` | Ubuntu, Debian, Fedora, Rocky Linux, Arch Linux, openSUSE, Alpine Linux contracts verified against realistic `/etc/os-release` fixtures, simulated tool databases, and mock probe responses. |
| **macOS** | `CONTRACT_VALIDATED` / `MOCK_UNIT` | Preserved existing Homebrew and macOS platform adapters; Problem #55 remains deliberately untouched. |

---

## 5. Verification Test Suite Results

### 5.1 Focused Phase 11.3 Suite
`tests/test_phase11_3_linux_package_distribution_providers.py`:
- 30 tests executed, **30 PASSED**, 0 failed.
- Test matrix coverage:
  - Ubuntu 24.04 (Debian family, noble codename, APT default)
  - Debian 12 (Debian family, bookworm codename, APT default)
  - Fedora 40 (RedHat family, DNF default)
  - Rocky Linux 9 (RedHat family via `ID_LIKE`, DNF default)
  - Arch Linux (Rolling release, Pacman default)
  - openSUSE Tumbleweed (SUSE family, Zypper default)
  - Alpine Linux 3.19.1 (Alpine family, OpenRC init, APK default)
  - Unknown Custom Distro (Missing ID_LIKE, requires review, zero mutation)
  - Missing `/etc/os-release` (Resilient handling, requires review)
  - Malformed `/etc/os-release` (Comment lines, empty lines, quote mismatch resilience)
  - Architecture Normalization Matrix (`x86_64`, `aarch64`, `armhf`, `i686`)
  - Provider Operations & Contracts for APT, DNF, Pacman, Zypper, APK
  - Failure Classifications (lock contention, repo unavailable, missing package, permissions)
  - Verification Probe States (installed, uninstalled, version match, wrong version)
  - Ownership Precedence (`dpkg -S`, `rpm -qf`, `pacman -Qo`, `apk -W`)
  - Safety Gate and Approval Enforcement (Zero unapproved mutations)
  - Recipe Engine Command Synthesis for Linux Package Managers
  - End-to-End Supported and Unknown Distro Lifecycles

### 5.2 Contract & Audit Suites
- `tests/test_platform_abstraction_contracts.py`: **25 PASSED**, 0 failed.
- `tests/test_stage11_75_problem_audit.py`: **10 PASSED**, 0 failed.
- `tests/test_problem_coverage_matrix.py`: **4 PASSED**, 0 failed.

---

## 6. Updated 75-Problem Matrix Metrics

Following the completion of Phase 11.3:
- **Problem #52 (Linux package-manager differences)**: Promoted from `PARTIALLY_IMPLEMENTED` to **`DETECT_AND_REPAIR`**.
- **Problem #53 (Linux distribution differences)**: Promoted from `PARTIALLY_IMPLEMENTED` to **`DETECT_AND_REPAIR`**.
- **Problem #55 (macOS Homebrew vs official installer)**: Retained as **`PARTIALLY_IMPLEMENTED`** (strictly untouched per instructions).
- **Problems #4, #35, #54, #71**: Retained unchanged.
- **Actionable Repair Boundary**: **47 / 75 (62.67%)** (up from 45/75).
- **Detection Coverage**: **74 / 75 (98.67%)** (up from 72/75).
- **Remaining Partially Implemented**: **1 / 75 (1.33%)** (Problem #55 only).
- **Not Implemented**: **0 / 75 (0.00%)**.

---

## 7. Limitations & Operational Boundaries

1. **Host-Native Execution**: Since tests were executed on a Windows host with mock OS-release structures and simulated command runners, Linux platform operations are `CONTRACT_VALIDATED` / `TEST_VALIDATED`. Real-world production deployment requires physical or containerized Linux validation.
2. **Unsupported Init Systems**: While `systemd` and `openrc` commands are recognized, non-standard init systems (e.g. `s6`, custom container shims) yield `SERVICE_PROVIDER_UNAVAILABLE`.
3. **Complex Repositories / Third-Party PPAs**: Third-party repository additions (e.g., custom apt PPAs, Copr repositories, AUR helpers like `yay`/`paru`) require human review to prevent supply chain tampering.
4. **macOS Homebrew Isolation**: Problem #55 remains isolated in `PARTIALLY_IMPLEMENTED` and was not modified in Phase 11.3.
