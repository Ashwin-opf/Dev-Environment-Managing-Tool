# Phase 11.4 — macOS Homebrew vs Official Installer Source Awareness Architecture

**Milestone**: Phase 11.4 — macOS Installation Source Intelligence & Problem #55 Completion  
**Target Problem**: **#55 — macOS Homebrew vs Official Installer**  
**Authoritative Baseline**: PC Doctor Developer Environment Manager  
**Validation Date**: September 25, 2026  
**Status**: **DETECT_AND_REPAIR** (Promoted from `PARTIALLY_IMPLEMENTED`)  

---

## 1. Executive Summary

Phase 11.4 delivers the authoritative macOS source-awareness intelligence layer for PC Doctor, resolving Problem #55 (**macOS Homebrew vs Official Installer**). On macOS systems, developer applications (e.g. Git, Docker, Node.js, Python, VS Code) frequently coexist across disparate packaging channels:
1. **Homebrew Formulae** (compiled CLI tools installed under `/opt/homebrew/Cellar` or `/usr/local/Cellar`)
2. **Homebrew Casks** (GUI or binary packages installed under `/opt/homebrew/Caskroom`)
3. **Official Vendor `.app` Bundles** (installed in `/Applications` or `~/Applications`)
4. **Official Vendor Frameworks / Binaries** (e.g. `/usr/local/go/bin/go`, `/Library/Frameworks/Python.framework`)
5. **Apple System Tools** (pre-installed macOS/Xcode shims in `/usr/bin`, e.g. Apple Git)
6. **Manual / Custom PATH Binaries** (developer-compiled or portable tools in `~/.local/bin` or custom paths)

### Key Architectural Invariants Enforced:
1. **Pure Intelligence / Non-Mutating Provider**:
   The source-awareness layer (`backend/platform_abstraction/macos/macos_source_awareness.py`) is strictly diagnostic, analytical, and recommendation-focused. It **never** directly executes mutations, shell commands, `rm -rf`, `brew uninstall`, or `.app` bundle deletion outside the centralized pipeline.
2. **Zero Blanket Preference**:
   There is **no blanket preference** where "Homebrew always wins" or "Vendor always wins". Updates and migrations strictly evaluate per-tool policies, active PATH precedence, and human review fallback.
3. **Strict PATH Precedence Resolution**:
   When multiple installations exist simultaneously, the active executable is resolved strictly by evaluating directory order in `PATH` (or bundle context). The system **never blindly chooses the numerically highest version number**.
4. **Ownership Preservation (Phase 11.2 Integration)**:
   The layer checks the `ManagedFootprintRegistry` (Phase 11.2). If a source installation is pre-existing or unmanaged by PC Doctor, it is flagged as `PRE_EXISTING` / `UNMANAGED` and cannot be deleted during migration without explicit, separate human authorization.
5. **Trusted Source Verification (Phase 11.1 Integration)**:
   Vendor source metadata and official download channels are anchored strictly to Phase 11.1 `TrustedSourceIntelligence` and `CanonicalIdentity`. AI, RAG, search engines, and arbitrary web pages cannot establish an official macOS vendor source.
6. **Explicit User Authorization & Safety Gate**:
   Cross-source migrations are classified as `TIER_2_CONTROLLED` operations requiring `approval_required=True`. Unapproved requests result in `APPROVAL_REQUIRED` with zero mutations executed.

---

## 2. Frozen Execution Architecture

The frozen mutation pipeline remains intact and authoritative:

```text
Request
  ↓
Detection / Multi-Source Diagnosis (Phase 11.4)
  ↓
Source / Installation-Method Analysis (Phase 11.4)
  ↓
Recipe / Migration Plan
  ↓
ExecutionResolver
  ↓
ExecutionPlan
  ↓
Tier (TIER_2_CONTROLLED)
  ↓
Approval (approval_required = True)
  ↓
Privilege
  ↓
LIVE Safety Gate
  ↓
Centralized Execution Engine
  ↓
Execution
  ↓
Verification (Source + Version + Architecture + PATH)
  ↓
Rescan (Multi-source Environment Rescan)
  ↓
Canonical Result
  ↓
Structured Logging (16-field action audit)
```

---

## 3. macOS Installation Source Model & Data Structures

Defined in [`backend/platform_abstraction/macos/macos_source_awareness.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/platform_abstraction/macos/macos_source_awareness.py):

### 3.1 Normalization Enums

```python
class MacOSInstallSource(str, Enum):
    HOMEBREW = "HOMEBREW"
    VENDOR_INSTALLER = "VENDOR_INSTALLER"
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"
    OTHER_TRUSTED = "OTHER_TRUSTED"
    UNKNOWN = "UNKNOWN"

class MacOSBrewType(str, Enum):
    FORMULA = "FORMULA"
    CASK = "CASK"
    NONE = "NONE"

class MacOSArchitecture(str, Enum):
    ARM64 = "arm64"
    X86_64 = "x86_64"
    UNIVERSAL = "universal"
    UNKNOWN = "unknown"

class MacOSSourceDecisionStatus(str, Enum):
    SOURCE_CONFIRMED = "SOURCE_CONFIRMED"
    MULTIPLE_SOURCES_DETECTED = "MULTIPLE_SOURCES_DETECTED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    SOURCE_POLICY_REQUIRES_REVIEW = "SOURCE_POLICY_REQUIRES_REVIEW"
    ARCHITECTURE_CONFLICT = "ARCHITECTURE_CONFLICT"
```

### 3.2 Inventory Models

```python
@dataclass
class MacOSInstallation:
    canonical_id: str
    display_name: str
    source: MacOSInstallSource
    version: Optional[str] = None
    package_manager: str = "none"
    package_id: Optional[str] = None
    executable_path: Optional[str] = None
    application_bundle_path: Optional[str] = None
    installation_scope: str = "SYSTEM"
    architecture: MacOSArchitecture = MacOSArchitecture.UNKNOWN
    owner: str = "UNKNOWN"
    brew_type: MacOSBrewType = MacOSBrewType.NONE
    bundle_id: Optional[str] = None
    bundle_version: Optional[str] = None
    is_active: bool = False
    managed_by_pc_doctor: bool = False
    notes: str = ""
```

---

## 4. Multi-Source Detection Pipeline

The detection pipeline inspects:

1. **Homebrew Formulae**:
   - Inspects `/opt/homebrew/Cellar/<package>/<version>/bin/<tool>` and `/usr/local/Cellar`.
   - Resolves symlinks in `/opt/homebrew/bin/<tool>`.
   - Extracts exact installed formula version and scope.
2. **Homebrew Casks**:
   - Inspects `/opt/homebrew/Caskroom/<package>/<version>/<app>.app`.
   - Parses `Contents/Info.plist` for `CFBundleIdentifier`, `CFBundleShortVersionString`, and `CFBundleExecutable`.
3. **Official Vendor Applications & Frameworks**:
   - Inspects `/Applications` and `~/Applications` for `<Tool>.app`.
   - Inspects configured vendor installation paths from canonical identity (e.g. `/usr/local/go/bin/go`).
   - Validates authentic bundle structures using standard Python `plistlib`.
4. **Apple System Binaries**:
   - Inspects `/usr/bin` and `/bin` for Apple-shipped developer binaries (e.g. Xcode Command Line Tools shims).
   - Identifies `APPLE_SYSTEM` ownership to block illegal system-file modification attempts.
5. **Manual / PATH Binaries**:
   - Parses `PATH` directories in order.
   - Categorizes unknown binaries as `MANUAL` (owner `USER`).
6. **Pure In-Process Mach-O Binary Header Inspection**:
   - Reads the initial 32 bytes of the target executable without spawning subprocesses:
     - `0xCAFEBABE` / `0xBEBAFECA` → `MacOSArchitecture.UNIVERSAL` (fat binary)
     - `0xFEEDFACF` / `0xCFFAEDFE` with cputype `12` (`CPU_TYPE_ARM64`) → `MacOSArchitecture.ARM64`
     - `0xFEEDFACF` / `0xCFFAEDFE` with cputype `7` (`CPU_TYPE_X86_64`) → `MacOSArchitecture.X86_64`
   - Detects architecture mismatches (e.g. `arm64` Homebrew vs `x86_64` Vendor) and flags `ARCHITECTURE_CONFLICT`.

---

## 5. Active Installation Resolution & Policy Engine

### 5.1 Strict PATH Precedence
When multiple sources are present (e.g. Homebrew Git 2.43.0 and Apple System Git 2.39.0):
- Iterates through the directories in effective `PATH`.
- Matches the directory containing each candidate executable.
- The earliest match in `PATH` becomes the single active installation (`is_active = True`).
- All other installations are marked available alternatives (`is_active = False`).
- Reversing PATH directories immediately and deterministically switches the active tool.

### 5.2 Per-Tool Policy & Ambiguity Handling
- `package_manager_first`: If Homebrew is installed and active, updates existing Homebrew package (`brew upgrade <pkg>`).
- `prefer_upstream`: If Vendor is active, updates existing Vendor package through trusted upstream URL.
- **Ambiguous Conflict**: When conflicting installations exist without an explicit policy override, the decision defaults to:
  ```python
  action = "REVIEW_REQUIRED"
  review_required = True
  ```
  No silent, destructive, or unilateral source selection is ever performed.

---

## 6. Safe Cross-Source Migration Workflow

When migrating across sources (e.g. Vendor → Homebrew or Homebrew → Vendor):

1. **Identification**: Identifies existing source, version, architecture, and bundle path.
2. **Target Resolution**: Synthesizes the target installation command via `ExecutionResolver`.
3. **Execution Tier**: Assigns `ExecutionTier.TIER_2_CONTROLLED`.
4. **Approval Enforcement**:
   - If `approved=False`: `CentralizedExecutionEngine` rejects execution with `status = "APPROVAL_REQUIRED"` and zero mutations.
5. **Footprint Check**:
   - Queries `footprint_registry.get_installation(canonical_id)`.
   - If the pre-existing source is unmanaged by PC Doctor, notes explicitly mandate:
     `"Existing <source> installation is PRE-EXISTING / UNMANAGED and will NOT be deleted."`
6. **Two-Stage Execution**:
   - Installs and verifies the new source first.
   - Deletion of the old source requires separate, explicit authorization.

---

## 7. Verification and Test Evidence

### 7.1 Focused Phase 11.4 Test Suite
The dedicated test suite [`tests/test_phase11_4_macos_source_awareness.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/tests/test_phase11_4_macos_source_awareness.py) provides 32 authoritative tests:

```text
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_01_homebrew_formula_tool_detected PASSED [  3%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_02_vendor_installed_app_bundle_detected PASSED [  6%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_03_manual_tool_in_local_bin_detected PASSED [  9%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_04_unknown_source_detected PASSED [ 12%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_05_homebrew_cask_detected PASSED [ 15%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_06_apple_system_binary_detected PASSED [ 18%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_07_app_bundle_info_plist_extraction PASSED [ 21%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSourceDetection::test_08_architecture_detection_macho_headers PASSED [ 25%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSMultipleInstallations::test_09_multiple_installations_homebrew_plus_vendor PASSED [ 28%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSMultipleInstallations::test_10_multiple_installations_homebrew_plus_manual PASSED [ 31%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSMultipleInstallations::test_11_multiple_versions_detected PASSED [ 34%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSMultipleInstallations::test_12_active_executable_resolved_strictly_via_path PASSED [ 37%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSMultipleInstallations::test_13_architecture_conflict_detected PASSED [ 40%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSPolicyAndUpdateDecisions::test_14_explicit_homebrew_source_policy_applied PASSED [ 43%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSPolicyAndUpdateDecisions::test_15_explicit_vendor_source_policy_applied PASSED [ 46%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSPolicyAndUpdateDecisions::test_16_ambiguous_source_conflict_triggers_review PASSED [ 50%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSPolicyAndUpdateDecisions::test_17_review_required_fallback PASSED [ 53%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSPolicyAndUpdateDecisions::test_18_no_blanket_homebrew_preference PASSED [ 56%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSOwnershipAndManagedFootprint::test_19_pc_doctor_managed_homebrew_installation PASSED [ 59%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSOwnershipAndManagedFootprint::test_20_pc_doctor_managed_vendor_installation PASSED [ 62%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSOwnershipAndManagedFootprint::test_21_pre_existing_homebrew_installation_flagged_unmanaged PASSED [ 65%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSOwnershipAndManagedFootprint::test_22_pre_existing_vendor_installation_flagged_unmanaged PASSED [ 68%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSOwnershipAndManagedFootprint::test_23_unmanaged_source_removal_strictly_blocked PASSED [ 71%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSafetyAndExecutionBoundary::test_24_source_migration_requires_user_approval PASSED [ 75%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSafetyAndExecutionBoundary::test_25_unapproved_source_migration_blocks_mutation PASSED [ 78%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSafetyAndExecutionBoundary::test_26_safety_gate_rejects_unapproved_command PASSED [ 81%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSSafetyAndExecutionBoundary::test_27_source_migration_cannot_bypass_centralized_execution PASSED [ 84%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSEndToEndIntegration::test_28_source_aware_update_decision_flow PASSED [ 87%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSEndToEndIntegration::test_29_source_migration_proposal_workflow PASSED [ 90%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSEndToEndIntegration::test_30_migration_verification_probe PASSED [ 93%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSEndToEndIntegration::test_31_path_source_consistency PASSED [ 96%]
tests/test_phase11_4_macos_source_awareness.py::TestMacOSEndToEndIntegration::test_32_duplicate_source_rescan_workflow PASSED [100%]

============================= 32 passed in 32.03s =============================
```

### 7.2 Native vs Mock Evidence Disclosure
- **Host Test Environment**: Windows AMD64 Python 3.13.7.
- **Evidence Classification**: `MOCK_UNIT` and `CONTRACT_VALIDATED`.
- **Truthful Assertion**: As executed on a Windows workstation, all macOS filesystem hierarchies, `.app` bundle structures, `Info.plist` manifests, and Mach-O binary headers are simulated via temporary filesystem mocks and binary byte generation. This implementation is rigorously verified against POSIX/Darwin contracts and AST inspection; it is **not** claimed as `LIVE_NATIVE` macOS validation.

---

## 8. Updated 75-Problem Master Metrics

With Problem #55 promoted to `DETECT_AND_REPAIR`, all 75 canonical problems are now fully accounted for, and **no partially implemented or unimplemented problems remain**:

### 8.1 Primary Classification Distribution

| Classification | Count | % | Change |
| :--- | :---: | :---: | :---: |
| **`FULLY_SOLVABLE`** | **21** | 28.00% | No change |
| **`DETECT_AND_REPAIR`** | **27** | 36.00% | **+1 (#55)** |
| **`DETECT_ONLY`** | **11** | 14.67% | No change |
| **`REVIEW_ONLY`** | **10** | 13.33% | No change |
| **`BLOCKED_BY_POLICY`** | **6** | 8.00% | No change |
| **`PARTIALLY_IMPLEMENTED`** | **0** | **0.00%** | **-1 (0 remaining!)** |
| **`NOT_IMPLEMENTED`** | **0** | **0.00%** | **0 (0 remaining!)** |
| **Total Canonical Problems** | **75** | **100.00%** | **100.00% Complete** |

### 8.2 Canonical Metrics

- **Detection Coverage**: `75 / 75 = 100.00%` (Every single canonical problem has an authoritative, validated detection mechanism)
- **Actionable Repair Boundary**: `(21 + 27) / 75 = 48 / 75 = 64.00%`
- **Review / Blocked Safety Coverage**: `(10 + 6) / 75 = 16 / 75 = 21.33%`
- **Detect-Only Diagnostic Coverage**: `11 / 75 = 14.67%`
- **Remaining Partial Problems**: **0**
- **Not Implemented Problems**: **0**

---

## 9. Limitations & Boundary Guarantees

1. **Native macOS Verification Pending**: Live Darwin kernel verification requires execution on an authentic macOS runner.
2. **Proprietary Vendor Bundles**: Certain third-party applications with non-standard bundle layouts (e.g. non-standard plist paths or nested helper daemons) require manual review fallback (`REVIEW_REQUIRED`).
3. **Dual Package Management**: If a user intentionally desires both Homebrew and vendor installations side-by-side for development workflows, PC Doctor respects both without auto-deleting either.

---

## 10. Conclusion

Phase 11.4 is complete, verified, and strictly isolated to Problem #55. The frozen execution architecture has been preserved with zero direct mutations and 100% test passing rate.
