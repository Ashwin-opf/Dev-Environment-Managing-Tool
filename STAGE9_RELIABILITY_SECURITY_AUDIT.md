# Stage 9 Reliability & Security Audit

**Document Version:** 1.0  
**Target Milestone:** Stage 9 — Reliability, Security, and Failure-Path Hardening  
**Target Architecture:** PC Doctor Intelligent Cross-Platform Developer Environment Manager  
**Platforms Covered:** Windows 11, Ubuntu 24.04 (Linux), macOS  

---

## 1. Executive Summary

Stage 9 is a dedicated **Reliability, Security, and Failure-Path Hardening audit and hardening milestone** following the successful native live validation established in Stage 8.1.

The architectural execution sequence remains frozen:
```text
Request
→ Detect
→ Diagnose
→ Recipe
→ Tier
→ Approval
→ Privilege
→ LIVE SAFETY GATE
→ Execute
→ Monitor
→ Verify
→ Rescan
→ Canonical Result
→ SSE / UI
→ Log
```

Stage 9 hardens this pipeline against duplicate concurrent mutations, stale machine states, shell and command injection, credential leakage, unhandled timeouts/cancellations, and false-positive completions.

---

## 2. Audit Findings & Hardening Matrix

### 2.1 Concurrency & Duplicate Mutation Prevention
- **Audit Area:** `backend/plan_freeze.py` (`ResourceLockManager`), `backend/execution_engine.py`.
- **Observed Problem:** If a resource lock had a timeout of `0.0`, lock acquisition logic might fail to perform an immediate availability check. Resource identifiers lacked uniform casing/whitespace normalization. Execution engine lacked explicit tracking of whether the current operation actually acquired the lock before releasing it.
- **Root Cause:** Incomplete lock acquisition verification on zero-timeout and missing identifier canonicalization.
- **Production Classification:** Concurrency / Data Integrity.
- **Hardening Applied:**
  1. `ResourceLockManager.acquire_resources` now normalizes all resource IDs via `.strip().lower()` and guarantees an immediate lock availability check on `timeout=0.0`.
  2. `ResourceLockManager.get_lock_owner(resource)` added for lock ownership inspection.
  3. `CentralizedExecutionEngine.execute_command` and `stream_execute_command` explicitly track `lock_acquired = True/False` and only release resources if actually acquired by the running operation.
  4. Blocked acquisitions immediately yield/return `status = "BLOCKED"`, `classification = "RESOURCE_BUSY"`, and spawn **0 mutation subprocesses**.
- **Regression Tests:** `test_01_duplicate_mutation_same_resource`, `test_02_concurrent_operations_independent_resources`.

---

### 2.2 Authoritative Final-State Consistency
- **Audit Area:** `backend/execution_engine.py`, `backend/routes_system.py`.
- **Observed Problem:** A zero process exit code (`returncode == 0`) could theoretically be misconstrued as success before authoritative verification had passed.
- **Root Cause:** Reliance on intermediate process exit codes rather than downstream authoritative verification status.
- **Production Classification:** Correctness / Invariant Enforcement.
- **Hardening Applied:**
  1. For mutation/repair operations, `ok = True` / `success = True` is **only** granted when both process execution succeeds (`returncode == 0`) **and** the required verification level succeeds (`verif_res.status == VerificationStatus.VERIFIED`).
  2. If functional verification fails, status and classification are set to `VERIFICATION_FAILED`, and `ok = False`.
  3. If verification times out, status and classification are set to `VERIFICATION_TIMEOUT`, and `ok = False`.
- **Regression Tests:** `test_03_canonical_final_result_consistency`, `test_04_zero_exit_verification_failure`, `test_05_nonzero_exit_execution_failure`.

---

### 2.3 SSE Final-Event Integrity
- **Audit Area:** `/api/execute-stream` in `backend/routes_system.py` and `stream_execute_command` in `backend/execution_engine.py`.
- **Observed Problem:** The final `done` event sent via Server-Sent Events must agree with the authoritative final result across all fields (`ok`, `status`, `classification`, `returncode`, `verification_status`, `message`).
- **Root Cause:** Independent assignment of SSE payload fields.
- **Production Classification:** API / Telemetry Integrity.
- **Hardening Applied:**
  1. The final `done` event synchronizes `ok`, `status`, `classification`, `returncode`, and `verification_status` directly from the authoritative result.
  2. History records are only marked successful if `last_done_event.get("ok") is True`.
- **Regression Tests:** `test_17_sse_done_event_integrity`, `test_21_client_disconnect_no_false_success`.

---

### 2.4 Subprocess Timeout & Reaping
- **Audit Area:** Subprocess management in `backend/execution_engine.py`.
- **Observed Problem:** Process timeouts must safely terminate and reap the subprocess to prevent leaked background processes, close stdio pipes, and yield an explicit timeout state without universal hardcoding of POSIX exit code 124 in cross-platform logic.
- **Root Cause:** Lack of guaranteed process termination and wait reaping on timeout.
- **Production Classification:** Subprocess / Resource Leakage.
- **Hardening Applied:**
  1. In `stream_execute_command`, upon exceeding timeout, the engine executes `proc.kill()` followed by `proc.wait(timeout=2.0)` and closes pipes.
  2. In `execute_command`, `subprocess.TimeoutExpired` explicitly tracks `is_proc_timeout = True`, producing `classification = "EXECUTION_TIMEOUT"`.
  3. Verification timeouts only retry verification probes, never re-executing the mutation.
- **Regression Tests:** `test_06_verification_timeout_without_mutation_retry`, `test_20_interrupted_operation_truthful_final_state`.

---

### 2.5 Command and Shell-Injection Security
- **Audit Area:** `backend/authoritative_safety.py` (`HARD_BLACKLIST`).
- **Observed Problem:** Dangerous command chaining, pipe-to-shell patterns (`curl | sh`, `wget | bash`), subshell substitution (`$()`, backticks), and dangerous permission alterations (`chmod 777 /`) must be blocked while preserving legitimate developer commands that use pipes or flags.
- **Root Cause:** Static pattern blacklist had gaps for pipe-to-interpreter and subshell execution.
- **Production Classification:** Security / Vulnerability Prevention.
- **Hardening Applied:**
  1. Added patterns to `HARD_BLACKLIST`:
     - `(?:curl|wget)\s+.*?\s*\|\s*(?:sh|bash|zsh|dash|python|perl|ruby)`
     - `(?:\$\(|`[^`]+`)`
     - `(?:;|&&|\|\|)\s*(?:rm\s+-rf|del\s+/|format\s+[A-Za-z]:)`
     - `powershell.*?(?:iex|-c|-command).*?(?:downloadstring|webclient)`
     - `chmod\s+.*?(?:777|666)\s+/`
  2. Preserved legitimate developer invocations (e.g. `npm install`, `brew update`, `winget install`, `export PATH=...`).
- **Regression Tests:** `test_13_dangerous_ai_command_rejection`, `test_14_command_injection_rejection`.

---

### 2.6 Cross-Platform Privilege & Elevation Boundary
- **Audit Area:** `backend/privilege_manager.py` (`WindowsPrivilegeAdapter`, `LinuxPrivilegeAdapter`, `MacOSPrivilegeAdapter`).
- **Observed Problem:** Cancellation of elevation by the user should be normalized across all platforms without hardcoding Windows exit code `1223` as universal cross-platform logic.
- **Root Cause:** Exit code `1223` is Windows-specific (`ERROR_CANCELLED`), whereas Linux uses `126`/exit 1 on pkexec cancel, and macOS uses `-128` (User Canceled) in AppleScript.
- **Production Classification:** Cross-Platform Privilege Handling.
- **Hardening Applied:**
  1. Added `is_cancelled_by_user(returncode, stderr, status)` method to `BasePrivilegeAdapter` and each platform adapter.
  2. Platform adapters normalize native cancellation signals into canonical `ElevationState.USER_DECLINED_ELEVATION` and `status = "USER_DECLINED_ELEVATION"`.
  3. Live safety gate rejects dangerous commands **before** elevation is ever initiated.
- **Regression Tests:** `test_08_tier3_safety_gate_block_zero_mutation`, `test_10_elevation_cancellation_normalized_correctly`.

---

### 2.7 Secret & API-Key Redaction
- **Audit Area:** `backend/structured_logger.py`, `backend/logger.py`.
- **Observed Problem:** API keys, personal access tokens, passwords, and bearer tokens must be redacted at every logging boundary, including fallback loggers and CLI arguments.
- **Root Cause:** Regex patterns in `SECRET_PATTERNS` only matched key-value pairs (`token: xyz`), missing CLI flag formats (`--token xyz`).
- **Production Classification:** Security / Credential Protection.
- **Hardening Applied:**
  1. Expanded `SECRET_PATTERNS` with:
     - `AIza[0-9A-Za-z-_]{20,}` (Gemini / Google AI API keys)
     - `sk-(?:proj-)?[a-zA-Z0-9_-]{10,}` (OpenAI keys)
     - `ghp_[a-zA-Z0-9]{20,}`, `github_pat_[a-zA-Z0-9_]{20,}` (GitHub tokens)
     - `--?(?:api[_\-]?key|token|password|secret)\s*[:=\s]\s*[^\s&|]+` (CLI arguments)
     - `bearer\s+[a-zA-Z0-9_\-\.]{12,}` (Bearer tokens)
  2. `StructuredLogger.log_event` redacts all message, command, version, and verification entries.
  3. `backend/logger.py` fallback file logger applies `redact_secrets` prior to write.
- **Regression Tests:** `test_15_gemini_key_redaction`, `test_16_openai_github_token_redaction`, `test_22_fallback_logger_redacts_secrets`.

---

### 2.8 Verification Integrity & Shadowing Detection
- **Audit Area:** `backend/verification_engine.py`.
- **Observed Problem:** An executable installed at one location might be shadowed by an older/broken binary located earlier on `PATH`, leading to false verification.
- **Root Cause:** Path resolution checked `shutil.which` without validating if the resolved binary matches the expected canonical installation target.
- **Production Classification:** Verification / Correctness.
- **Hardening Applied:**
  1. Verification probes cross-reference `which` with canonical identity `matches_expected_executable`.
  2. If shadowed, verification fails with `SHADOWED_BY_PREVIOUS_INSTALLATION`.
- **Regression Tests:** `test_19_shadowing_detection_truthful_failure`, `test_07_verification_failure_recovered_through_policy`.

---

### 2.9 Stale Machine-State Protection & Failure Classification
- **Audit Area:** `backend/authoritative_safety.py`.
- **Observed Problem:** State changes between planning and execution (disk space drops, package manager disappears, dependency locks) must be re-evaluated immediately before mutation. Failure reasons must retain distinct semantics rather than collapsing to generic failure.
- **Root Cause:** Cached safety results must be invalidated when dynamic machine state changes.
- **Production Classification:** Dynamic Safety / Diagnostic Accuracy.
- **Hardening Applied:**
  1. `SafetyEvaluationCache` computes dynamic machine state signatures (`reboot:`, `disk:`, `lock:`, `pm_avail:`). Any state change invalidates cached clearances.
  2. Distinct failure enums preserved:
     - `PACKAGE_MANAGER_UNAVAILABLE`
     - `UNSUPPORTED_METHOD`
     - `OUTDATED_RECIPE`
     - `MISSING_RECIPE`
     - `IDENTITY_UNRESOLVED`
     - `RESOURCE_BUSY`
- **Regression Tests:** `test_11_stale_package_manager_state_rejection`, `test_12_stale_disk_space_rejection`, `test_18_distinct_package_manager_failure_classifications`.

---

## 3. GitHub Actions CI Node.js 24 Compatibility

As required by Stage 9, the GitHub Actions workflows `.github/workflows/stage8_1_linux.yml` and `.github/workflows/stage8_1_macos.yml` have been updated to official Node-24-compatible releases:
```yaml
actions/checkout@v7
actions/setup-python@v7
actions/upload-artifact@v6
```
The execution trigger remains strictly `workflow_dispatch` for live mutation validation, eliminating deprecation warnings while preserving manual gating.
