# STAGE 3 — VERIFICATION & EFFECTIVE ENVIRONMENT HARDENING: ARCHITECTURAL AUDIT

**Date:** 2026-09-17  
**Status:** Audit Complete  
**Goal:** Verify real post-mutation machine state instead of stale PC Doctor process state.

---

## 1. Executive Summary & Verification Flow

The authoritative Stage 2 execution pipeline established the 9-stage sequence:
```
REAL USER ACTION / API
    ↓
01. LIVE ROUTE
    ↓
02. TIER / APPROVAL
    ↓
03. PRIVILEGE RESOLUTION
    ↓
04. LIVE SAFETY GATE
    ↓
05. SUBPROCESS / MUTATION
    ↓
06. VERIFICATION
    ↓
07. RESCAN
    ↓
08. STRUCTURED LOG
    ↓
09. UI / SSE FINAL RESULT
```

Stage 3 hardens the verification layer (`Stage 06: VERIFICATION`) so that verification probes observe the **real post-mutation environment** rather than stale state inherited from the already-running PC Doctor parent process.

The target verification dataflow:
```
MUTATION (Elevated Worker / Subprocess)
    ↓
EFFECTIVE ENVIRONMENT REFRESH (Platform Abstraction)
    ↓
EXPLICIT SUBPROCESS INVOCATION (env=effective_environment)
    ↓
EXACT EXECUTABLE RESOLUTION (Canonical Identity Expected Executable)
    ↓
L1–L4 TIERED VERIFICATION PROBES (Exit, Version, Functional, PATH)
    ↓
L5 ORIGINAL-PROBLEM RESCAN (Real Detector Re-Run, Semantic Evaluation)
```

---

## 2. Current Implementation Audit

### 2.1 Environment Refresh (`backend/verification_engine.py`)
- **Current Code:**
  ```python
  def _refresh_verification_environment() -> None:
      """Refreshes the current process environment and PATH from persistent platform sources."""
      try:
          from platform_abstraction import get_path_manager, get_environment_provider
          pm = get_path_manager()
          if pm:
              eff_entries = pm.get_effective_path()
              for p in eff_entries:
                  if p and os.path.exists(p):
                      pm.sync_process_path(p)
          ep = get_environment_provider()
          if ep:
              ep.refresh_environment_state()
      except Exception:
          pass
  ```
- **Findings & Defects:**
  1. **Interface Mismatch**: `pm.sync_process_path(p)` does not exist on the public `PathManager` base class in `backend/platform_abstraction/base.py`. In `WindowsPathManager`, line 31, the method was named `_sync_process_path(self, target_dir: str)`. In `LinuxPathManager` and `MacPathManager`, it does not exist at all.
  2. **Silent Failure Swallowing**: The `AttributeError: 'WindowsPathManager' object has no attribute 'sync_process_path'` is caught by `except Exception: pass`. The environment refresh fails silently on every invocation without warning or diagnostic telemetry.
  3. **No Effective Environment Construction**: It attempts only to mutate `os.environ["PATH"]` of the parent process. It does not construct an explicit `effective_environment` dictionary.

### 2.2 Current PATH & Environment Source (`backend/platform_abstraction/windows/`)
- **Current Code:**
  - `WindowsPathManager.get_path_entries()` queries `HKLM` (Machine) and `HKCU` (User) registry keys.
  - `WindowsEnvironmentProvider.get_effective_environment()` does:
    ```python
    merged = dict(self.get_machine_environment())
    merged.update(self.get_user_environment())
    return merged
    ```
- **Findings & Defects:**
  1. **Path Clobbering**: In Windows, User PATH does **not** override Machine PATH; the Windows shell and loader concatenate `Machine_PATH;User_PATH`. Doing `merged.update(user)` completely overwrites Machine PATH with User PATH, stripping critical system folders (`C:\Windows\System32`, `C:\Program Files`, etc.).
  2. **Case Sensitivity**: Windows environment variable lookups are case-insensitive (`Path` vs `PATH`), but standard Python dictionaries are case-sensitive. Multiple casings can coexist or collide improperly.
  3. **Variable Expansion**: Registry values stored as `REG_EXPAND_SZ` (such as `%USERPROFILE%`, `%SystemRoot%`, `%APPDATA%`) are read without structured variable expansion across interdependent variables.

### 2.3 Subprocess Environment Behavior (`_run_probe`)
- **Current Code:**
  ```python
  def _run_probe(cmd: List[str], timeout: int = 10) -> Tuple[subprocess.CompletedProcess, bool]:
      try:
          proc = subprocess.run(
              cmd,
              capture_output=True,
              text=True,
              encoding="utf-8",
              errors="replace",
              timeout=timeout,
          )
          return proc, False
  ```
- **Findings & Defects:**
  1. **No Explicit Environment**: `subprocess.run` does not pass `env=...`. The child process inherits `os.environ` from the running Python process.
  2. **Stale PATH**: If a repair command modified the machine/user PATH in the Windows registry, child processes spawned by PC Doctor cannot see the new directory unless PC Doctor restarts or explicit environment dictionaries are passed to `subprocess.run`.

### 2.4 Executable Resolution
- **Current Code:**
  - `shutil.which(exec_name)` checks only the stale host `os.environ["PATH"]`.
  - Fallback loops over `identity.installation_paths`.
  - Hardcoded branches for functional probes:
    ```python
    if exec_name.lower() in ("python", "python3"):
        ...
    elif exec_name.lower() in ("node", "nodejs"):
        ...
    elif exec_name.lower() == "git":
        ...
    ```
- **Findings & Defects:**
  1. **Non-Generic / Hardcoded**: Functional checks are hardcoded with `if/elif` statements rather than using `CanonicalIdentity` metadata.
  2. **No Exact Executable Verification**: Cannot distinguish "some `git.exe` on PATH" from "the expected Git installation at `C:\Program Files\Git\cmd\git.exe`". It cannot detect PATH shadowing (e.g. older user-scoped executable shadowing machine installation).

### 2.5 L5 Original Problem Rescan
- **Current Code:**
  ```python
  # Level 3: FULL verification (Environment + Problem Rescan)
  problem_cleared = True
  if original_problem:
      if "not recognized" in original_problem.lower() and found_path:
          problem_cleared = True
      elif "version" in original_problem.lower() and version_str:
          problem_cleared = True
  ```
- **Findings & Defects:**
  1. **Naive String Matching**: Infers resolution purely by checking if substring `"not recognized"` or `"version"` is in `original_problem`.
  2. **No Detector Execution**: Does not invoke the real diagnostic detector (`DevEnvironmentDetector` or problem detector) that originally flagged the fault.
  3. **No Semantic Problem State**: Lacks semantic outcomes like `CLEARED`, `STILL_PRESENT`, `CHANGED`, `UNRESOLVED`.

### 2.6 Retry Implementation
- **Current Code:**
  - `verify_tool()` implements a bounded retry loop up to `max_attempts`.
  - Only retries when `result.timed_out == True`. Deterministic errors fail immediately without retry.
  - Configurable backoff, probe timeout, and stabilization grace.
  - Mutation is never retried from verification.
- **Findings:**
  - The retry mechanism is sound and complies with Stage 2 safety invariants. It must be strictly preserved.

---

## 3. Identified Defects Matrix

| ID | Component | Defect Description | Architectural Impact |
| :--- | :--- | :--- | :--- |
| **D1** | `verification_engine.py` | `pm.sync_process_path` mismatch (`_sync_process_path` private) | `AttributeError` on every environment refresh attempt |
| **D2** | `verification_engine.py` | `except Exception: pass` around environment refresh | Silent failure swallowing; pretends refresh succeeded |
| **D3** | `windows_environment.py` | `get_effective_environment` overwrites Machine PATH with User PATH | User PATH drops all system directories from effective environment |
| **D4** | `windows_environment.py` | Missing case-insensitive key normalization & `REG_EXPAND_SZ` expansion | Stale or unexpanded environment variables |
| **D5** | `verification_engine.py` | `_run_probe` lacks `env=effective_environment` | Child processes inherit stale `os.environ` |
| **D6** | `verification_engine.py` | `shutil.which` uses stale `os.environ["PATH"]` | Cannot discover newly PATH-added binaries without restart |
| **D7** | `verification_engine.py` | Hardcoded `if exec_name == "git"` functional probes | Violates generic metadata-driven architecture |
| **D8** | `canonical_identity.py` | Lacks expected executable & exact-match resolution metadata | Cannot detect wrong PATH ordering or executable shadowing |
| **D9** | `verification_engine.py` | L5 uses naive `"not recognized"` substring matching | False positives; never re-runs original diagnostic detector |

---

## 4. Files Requiring Modification

1. **`backend/platform_abstraction/base.py`**:
   - Add public methods: `refresh_effective_environment()`, `get_effective_environment()`, `sync_process_path(dir_path: str)`.
   - Update `EnvironmentProvider` and `PathManager` contracts.
2. **`backend/platform_abstraction/windows/windows_environment.py`**:
   - Implement Windows effective environment reconstruction (Machine + User, proper `PATH` concatenation `Machine;User`, case-insensitive dictionary, recursive variable expansion).
   - Implement `refresh_effective_environment()`.
3. **`backend/platform_abstraction/windows/windows_path.py`**:
   - Expose public `sync_process_path(dir_path: str)` method conforming to `PathManager`.
4. **`backend/platform_abstraction/linux/` & `backend/platform_abstraction/macos/`**:
   - Implement `sync_process_path()` and `refresh_effective_environment()` to keep Linux/macOS adapters in sync with the base contract.
5. **`backend/canonical_identity.py`**:
   - Add expected executable path resolution and functional probe command metadata to `CanonicalIdentity`.
6. **`backend/verification_engine.py`**:
   - Replace private calls with `pm.sync_process_path()` and `ep.refresh_effective_environment()`.
   - Eliminate silent exception swallowing; record structured diagnostic on environment refresh error.
   - Supply `effective_environment` to `shutil.which(..., path=...)` and `subprocess.run(..., env=...)`.
   - Generic exact executable resolution comparing resolved executable with expected executable metadata.
   - Replace hardcoded application branches with identity-driven functional probe command.
   - Implement real L5 detector rescan: query `DevEnvironmentDetector` to confirm original problem state (`CLEARED`, `STILL_PRESENT`, `CHANGED`).
7. **`tests/test_verification_environment_hardening.py`**:
   - Implement the complete 16-test suite specified in the Stage 3 requirements.
