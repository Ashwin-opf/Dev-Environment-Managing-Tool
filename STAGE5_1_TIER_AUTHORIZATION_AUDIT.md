# STAGE 5.1 — TIER AUTHORIZATION AUDIT

## Purpose & Scope
This audit examines the exact execution and authorization paths across PC Doctor:
- `backend/execution_tier.py`
- `backend/authoritative_safety.py`
- `backend/execution_engine.py`
- `backend/plan_freeze.py`
- `backend/privilege_manager.py`

The objective is to verify that the invariant:
$$\text{ExecutionTier describes protection/approval level} \ne \text{Execution Authorization}$$
is permanently and centrally locked across all execution routes.

---

## 1. Tracing the 5 Critical Pipeline Stages

```
   [1. Detection / Diagnosis]
              │
              ▼
   [2. Canonical Recipe]
              │
              ▼
   [3. Live Risk & Tier Selection] ──► Tier describes protection level (FAST, CONTROLLED, FULL_PROTECTED)
              │                       *Hard safety overrides escalate here*
              ▼
   [4. User Review / Approval]    ──► User approval satisfies review requirement for Tier 2/3
              │                       *Approval != safety authorization*
              ▼
   [5. Privilege Resolution]      ──► Resolves platform adapter (UAC / pkexec / sudo)
              │                       *Elevation availability != safety authorization*
              ▼
╔═══════════════════════════════════════════════════════════════════════╗
║            6. LIVE AUTHORITATIVE PRE-EXECUTION GATE                   ║
║            (authoritative_safety.live_pre_execution_gate)             ║
║            *The SOLE authority for mutation permission*               ║
╚═══════════════════════════════════════════════════════════════════════╝
              │
      ┌───────┴───────┐
      ▼               ▼
  [ALLOWED]       [BLOCKED]
      │               │
      │               ▼
      │        Zero Subprocess Spawns
      │        Return ExecutionOutcome(status="BLOCKED")
      ▼
   [7. Subprocess / Worker Mutation]
              │
              ▼
   [8. Verification & Rescan]
              │
              ▼
   [9. Structured Telemetry Logging]
```

### Stage 1: Where is Tier Selected?
- **File**: [`backend/execution_tier.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/execution_tier.py)
- **Function**: `select_execution_tier(recipe, trust_score, risk_score, confidence_score, machine_state, policy)`
- **Called by**:
  - `CentralizedExecutionEngine.execute_recipe()` (line 106)
  - `CentralizedExecutionEngine.execute_command()` (line 711)
  - `CentralizedExecutionEngine.stream_execute_command()` (line 1062)
  - `create_frozen_batch_plan()` in `plan_freeze.py` (line 115)
- **Semantics**: Pure policy selection returning `(ExecutionTier, reason)`.
  - Hard safety overrides (regex matching boot configuration, credentials, firewalls, kernel modules) force `ExecutionTier.TIER_3_FULL_PROTECTED`.
  - **Invariant**: Tier selection merely specifies the required operational safeguards (automated vs user review vs pre-execution snapshot + UAC elevation). **It does not authorize execution.**

### Stage 2: Where is Approval Evaluated?
- **Files**:
  - Web UI / Control Center approval endpoints (`routes_shce.py`, `routes_system.py`)
  - `privilege_manager.py`: Windows UAC elevation consent prompt (`ShellExecuteExW` with verb `"runas"`)
- **Semantics**: Approval confirms user consent for medium-to-high risk operations (`TIER_2_CONTROLLED` and `TIER_3_FULL_PROTECTED`).
- **Invariant**: **Approval is NOT safety authorization.** Even if a user clicks "Approve" or accepts a UAC prompt, a command that violates safety policies (e.g. destructive disk formatting, kernel wiping, or corrupted natural language) MUST be blocked.

### Stage 3: Where is Privilege Resolved?
- **File**: [`backend/privilege_manager.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/privilege_manager.py)
- **Function**: `PrivilegeManager.resolve_privilege(tier=tier, elevate=elevate, scope=scope)`
- **Called by**:
  - `CentralizedExecutionEngine.execute_recipe()` (line 174)
  - `CentralizedExecutionEngine.execute_command()` (line 742)
  - `CentralizedExecutionEngine.stream_execute_command()` (line 1086)
- **Semantics**: Determines whether the operation requires the Windows, Linux, or macOS privilege adapter and initializes platform capability tracking.
- **Invariant**: **Elevation availability is NOT safety authorization.** Administrative privileges grant OS capabilities, not permission to bypass safety policy.

### Stage 4: Where is the FINAL Safety Decision Made?
- **File**: [`backend/authoritative_safety.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/backend/authoritative_safety.py)
- **Function**: `AuthoritativeSafetyLayer.live_pre_execution_gate(...)`
- **Called by**:
  - `CentralizedExecutionEngine.execute_recipe()` (line 178)
  - `CentralizedExecutionEngine.stream_execute_recipe()` (line 377)
  - `CentralizedExecutionEngine.execute_command()` (line 745)
  - `CentralizedExecutionEngine.stream_execute_command()` (line 1089)
  - `evaluate_step_live_safety_gate()` in `plan_freeze.py` (line 136)
- **Return Type**: `SafetyGateResult(allowed: bool, blocked_reason: Optional[BlockedReason], message: str, ...)`
- **Semantics**: This is the **SOLE last-mile gate** authorizing execution. It evaluates:
  1. Static blacklist patterns & destructive command signatures.
  2. Natural language string heuristics (e.g., `"fix my git"`).
  3. Recipe vs Host OS platform compatibility.
  4. Required package manager availability on system PATH.
  5. Active OS installer locks and concurrent resource contention.
  6. Live pending reboot policy (allowing read-only queries, blocking system mutations).
  7. Live free disk space (minimum 2 GB threshold).
  8. Host RAM saturation (< 98%).
- **Invariant**: If `allowed is False`, execution is immediately halted with zero process spawns.

### Stage 5: Where is Subprocess Creation Performed?
- **Files**:
  - `CentralizedExecutionEngine.execute_recipe()` (line 225): `subprocess.run(cmd_str, ...)`
  - `CentralizedExecutionEngine.stream_execute_recipe()` (line 409): `asyncio.create_subprocess_shell(cmd_str, ...)`
  - `CentralizedExecutionEngine.execute_command()`:
    - Elevated: line 800 `privilege_manager.run_with_elevation(clean_cmd, ...)`
    - Non-elevated: line 838 `subprocess.run(clean_cmd, ...)`
  - `CentralizedExecutionEngine.stream_execute_command()`:
    - Elevated: line 1158 `privilege_manager.stream_elevated_operation(payload, ...)`
    - Non-elevated: line 1215 `subprocess.Popen(...)`
  - `WindowsPrivilegeAdapter.execute_elevated()` (lines 351, 388): `kernel32.CreateProcessW` / `shell32.ShellExecuteExW`
- **Invariant**: Subprocess spawning occurs **strictly after** `live_pre_execution_gate` has returned `allowed=True`.

---

## 2. Potential Bypass Routes & Hardening Action Plan

### Vulnerability 1: Direct Privilege Manager Elevation Calls
- **Observation**: If external code or tests invoke `privilege_manager.run_with_elevation(command)` or `PrivilegeManager.run_elevated_operation(payload)` directly without routing through `execution_engine`, the elevated worker could theoretically be launched for a dangerous command.
- **Hardening Fix**: Add last-mile safety gate verification inside `BasePrivilegeAdapter.execute_elevated()`. If `authoritative_safety.live_pre_execution_gate` rejects the command in the payload, immediately yield `USER_DECLINED_ELEVATION` / `BLOCKED` with zero subprocess/UAC spawns.

### Vulnerability 2: Missing Structurally Centralized Authorization Assertion
- **Observation**: In `CentralizedExecutionEngine`, each entrypoint inspects `if not safety_res.allowed:`. While correct, future edits could inadvertently introduce fallback logic or conditional tier bypasses (e.g., `if tier == ExecutionTier.TIER_3: ...`).
- **Hardening Fix**: Introduce an explicit central authorization validator in `CentralizedExecutionEngine`:
  ```python
  @staticmethod
  def _assert_mutation_authorized(safety_res: Optional[SafetyGateResult]) -> None:
      if safety_res is None or not safety_res.allowed:
          raise SafetyAuthorizationViolation("Mutation attempted without explicit Live Safety Gate clearance.")
  ```
  And explicitly enforce this check immediately before every `subprocess.run`, `subprocess.Popen`, and `privilege_manager.run_with_elevation`.

### Vulnerability 3: DevTools Update Stream Direct Execution
- **Observation**: In `backend/routes_system.py` at line 3022 (`/api/devtools/update-stream`), `create_subprocess_shell` was called on `update_command` without an explicit pre-execution safety gate check.
- **Hardening Fix**: Wrap the launch in `/api/devtools/update-stream` with `authoritative_safety.live_pre_execution_gate()`.

---

## 3. Invariant Locking Verification Strategy
To permanently safeguard this invariant, we will construct a dedicated regression test suite:
[`tests/test_tier3_safety_boundary.py`](file:///c:/Users/srira/.gemini/antigravity/scratch/pc-doc/tests/test_tier3_safety_boundary.py) covering:
1. **Tier 3 + Safety Blocked**: Command triggering hard override routes to Tier 3, safety gate returns `BLOCKED` $\to$ zero subprocess spawns.
2. **Tier 3 + Safety Allowed**: Command legitimately requiring Tier 3 executes normally when safety gate returns `ALLOWED`.
3. **Hard Override Cannot Bypass Safety**: Hard override escalates tier, but safety gate still blocks if command is destructive $\to$ zero subprocess spawns.
4. **Approval Cannot Bypass Safety**: User approval `True`, tier `TIER_3`, safety gate `BLOCKED` $\to$ zero subprocess spawns.
5. **Elevation Cannot Bypass Safety**: Administrative privileges available, tier `TIER_3`, safety gate `BLOCKED` $\to$ zero worker/UAC spawns.
6. **Frozen Plan Cannot Bypass Live Safety**: Plan frozen at `TIER_3`, machine conditions degrade $\to$ step is blocked by live gate.
7. **Truth Table Matrix**: Exhaustive test over $\{\text{Tier 1}, \text{Tier 2}, \text{Tier 3}\} \times \{\text{Safety Allowed}, \text{Safety Blocked}\}$ proving that execution occurs if and only if Safety is Allowed.
8. **Static AST Analysis**: AST scanner ensuring `CentralizedExecutionEngine` has no code branch connecting tier or approval directly to subprocess creation without passing through `live_pre_execution_gate`.
