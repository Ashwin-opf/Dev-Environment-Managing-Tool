# STAGE 4 — MACHINE-STATE & TIER-POLICY CORRECTNESS RESULT

## 1. Executive Summary

Stage 4 achieves strict correctness in machine-state ingestion, risk assessment, and execution-tier policy determination. All hardcoded heuristics, silent assumptions, and direct platform calls in policy evaluation have been systematically eliminated in favor of a normalized, typed, platform-abstracted architecture.

### Key Verification Metrics
- **Baseline Test Suite (Stages 1–3)**: 299/299 passed
- **Stage 4 Machine-State Policy Test Suite** (`tests/test_machine_state_policy.py`): 26/26 passed
- **Total Stage 4 Test Suite**: **325/325 passed** (0 failures, 100% pass rate in 311.62s)
- **Live Windows Git Runtime Proof**: **5/5 stages succeeded** (real Windows host pending reboot detected, live risk scored at 0.40, Controlled Tier routed with user approval required, safety gate passed, full post-execution verification confirmed).

---

## 2. Machine-State Signals & Collection Architecture

### Architectural Separation
Policy decision code (`backend/execution_tier.py`) is now completely isolated from host operating system mechanics. AST analysis verifies that `backend/execution_tier.py` contains **zero imports** of `subprocess`, `winreg`, or platform shell modules.

Machine-state signals are collected exclusively via the platform abstraction layer:
```
backend/platform_abstraction/
  ├── base.py                         (MachineStateProvider abstract base class)
  ├── windows/windows_machine_state.py (WindowsMachineStateProvider)
  ├── linux/linux_machine_state.py     (LinuxMachineStateProvider)
  └── macos/macos_machine_state.py     (MacOSMachineStateProvider)
```

### Normalized Signals Model (`backend/machine_state.py`)
Each signal is represented as a typed, normalized field with tri-state support (`True`, `False`, or `None` for `UNKNOWN`):

| Signal | Type | Collection Mechanism (Windows) | Fallback / Cross-Platform |
| :--- | :--- | :--- | :--- |
| `pending_reboot` | `Optional[bool]` | Registry keys (`CBS\RebootPending`, `WindowsUpdate\Auto Update\RebootRequired`, `Session Manager\PendingFileRenameOperations`) | `/var/run/reboot-required` (Linux) |
| `low_disk_space` | `Optional[bool]` | `shutil.disk_usage()` on system drive (< 5 GB threshold) | `shutil.disk_usage()` |
| `service_issue` | `Optional[bool]` | Service control manager probe | `systemctl` / `launchctl` |
| `dependency_lock` | `Optional[bool]` | Registry `Installer\InProgress` mutex probe | Package manager lock files |
| `package_manager_available` | `Optional[bool]` | Executable discovery (`winget`, `choco`, `scoop`) | `apt`, `yum`, `brew` |
| `installation_state_changed` | `Optional[bool]` | Machine state transition tracker | In-memory cache tracker |
| `previous_failure` | `Optional[bool]` | Tool telemetry and execution history cache | Telemetry database |
| `environment_drift` | `Optional[bool]` | Registry vs process environment delta inspection | Snapshot comparison |
| `conflicts` | `Optional[bool]` | Path collision and process locking scanner | Process list |
| `unusual_state` | `Optional[bool]` | Aggregation of abnormal indicators | Aggregated flags |
| `cpu_percent` | `Optional[float]` | `psutil.cpu_percent(interval=0.1)` | `psutil` or `os.getloadavg()` |
| `ram_percent` | `Optional[float]` | `psutil.virtual_memory().percent` | `psutil` |

---

## 3. Handling of UNKNOWN Signals

A critical vulnerability of legacy systems is treating unprobed or indeterminate states as `SAFE`. In PC Doctor:
1. **No Silent `UNKNOWN` $\to$ `SAFE` Conversions**: If a probe fails, times out, or cannot access permissions to inspect a signal, it is recorded as `None` (`UNKNOWN`).
2. **Conservative Fast Path Invariant**: Fast Path execution (`TIER_1_FAST`) strictly requires all relevant safety signals to be affirmatively `False` (confirmed normal). If `pending_reboot`, `low_disk_space`, or `dependency_lock` is `None` (`UNKNOWN`), Fast Path is disqualified.
3. **Audit Trail**: `MachineState.is_normal_state()` returns `(False, reasons)` whenever an unconfirmed state is encountered, explicitly documenting why automated fast-tracking was withheld.

---

## 4. Controlled Tier & Explicit Trust Requirement

### Policy Definition
Controlled Tier (`TIER_2_CONTROLLED`) is designed for non-destructive or moderate-risk actions that require explicit user awareness and confirmation. It was previously possible for recipes with acceptable risk to execute under Tier 2 even when untrusted.

Under the new policy:
$$\text{Controlled Path} \iff (\text{live\_risk} \le \text{controlled\_risk\_max}) \land (\text{trust} \ge \text{controlled\_trust\_min})$$

### Default Thresholds
- `controlled_risk_max`: `0.70`
- `controlled_trust_min`: `0.60`

### Why Trust Is Required
A command with moderate risk (e.g., 0.45) generated dynamically or supplied from an unverified source must not be executed with only casual user interaction. If `trust < 0.60`, the execution automatically escalates to `TIER_3_FULL_PROTECTED` (requiring full isolation/elevation checkpoints) or is `BLOCKED` if risk exceeds protective bounds.

---

## 5. Configurable & Typed Policy Thresholds

Hardcoded numeric literals have been replaced with a validated configuration object:
```python
@dataclass
class TierPolicyConfig:
    fast_path_trust_min: float = 0.85
    fast_path_risk_max: float = 0.30
    fast_path_confidence_min: float = 0.80
    controlled_trust_min: float = 0.60
    controlled_risk_max: float = 0.70
    controlled_confidence_min: float = 0.50
    protected_risk_max: float = 0.90
    allow_fast_path_with_drift: bool = False
```

### Validation Invariants
The configuration enforces strict monotonic ordering upon creation and modification:
- $0.0 \le \text{controlled\_trust\_min} \le \text{fast\_path\_trust\_min} \le 1.0$
- $0.0 \le \text{fast\_path\_risk\_max} \le \text{controlled\_risk\_max} \le \text{protected\_risk\_max} \le 1.0$

Policy thresholds can be tuned per-environment via `set_tier_policy(config)` and restored via `reset_tier_policy()`.

---

## 6. Hard Safety Overrides

Before evaluating mathematical trust and risk models, the policy runs deterministic pattern analysis against high-consequence system boundaries:

```python
check_hard_safety_override(command: str) -> Optional[Tuple[ExecutionTier, str]]
```

### Protected Operation Classes
1. **Boot Configuration**: `bcdedit`, `bootcfg`, EFI partition manipulation.
2. **Network Perimeter / Kernel Filtering**: `netsh advfirewall`, driver unloading, kernel module manipulation.
3. **Security Principals & Credentials**: `net user`, `vssadmin delete shadows`, SAM/credential dump vectors.

When triggered, hard overrides immediately force **`TIER_3_FULL_PROTECTED`** (or safety rejection) with an unambiguous justification message, completely bypassing lower-tier heuristics regardless of trust score.

---

## 7. Decoupling of Scope from Tier

In legacy code, `if scope == "machine": tier = ExecutionTier.TIER_3_ELEVATED_ADMIN` was hardcoded directly inside the execution engine. This conflated operational impact area with privilege policy.

### New Architecture
1. **Pure Function Invariant**: `determine_tier(...)` is a pure function taking normalized metrics (`trust`, `risk`, `confidence`, `machine_state`).
2. **Scope as a Risk Input**: Machine scope legitimately contributes to the **risk assessment** (`requires_elevation=True` in `compute_live_risk()`), increasing risk according to system exposure.
3. **Independent Policy Evaluation**: If a machine-scoped operation has verified trust and low live risk, the policy determines the tier based on objective rules rather than an ad-hoc conditional.

---

## 8. Live Host Git Runtime Proof

The end-to-end call chain was executed on the live Windows host against Git using the real production route (`scratch/stage4_git_runtime_proof.py`).

```
============================================================
STAGE 4: LIVE GIT RUNTIME PROOF TELEMETRY
============================================================
1. Machine-State Collection:
   - Operating System: Windows
   - Real Pending Reboot Detected: TRUE (Session Manager PendingFileRenameOperations)
   - Unusual State Flagged: TRUE
   - Free Disk Space: 320.52 GB
   - Host CPU: 23.1% | Host RAM: 65.4%
   - Confirmed Normal: FALSE (disqualified from Fast Path)

2. Live Risk Calculation:
   - Base Risk: Low
   - Computed Live Risk: 0.40 (elevated from 0.15 due to host pending reboot)

3. Tier Selection:
   - Trust Score: 1.00 (verified static recipe)
   - Confidence: 1.00
   - Selected Tier: TIER_2_CONTROLLED
   - Approval Required: TRUE
   - Reason: "Routed to Controlled Path. [Machine state abnormal: Pending reboot]"

4. Authoritative Safety Gate:
   - Command Evaluated: "git --version"
   - Live Gate Result: PASSED (Allowed)

5. Pipeline Execution & Full Verification:
   - Tier Executed: TIER_2_CONTROLLED
   - Return Code: 0
   - Standard Output: "git version 2.55.0.windows.3"
   - Execution Status: EXECUTION_SUCCEEDED
   - Verification Status: VERIFIED (Level: FULL)
   - Executable Resolved: C:\Program Files\Git\cmd\git.EXE
   - Diagnosis Cleared: TRUE
============================================================
```

All telemetry was captured and archived in `scratch/stage4_git_evidence.json`.

---

## 9. Verification Summary

| Test Suite | File | Tests Run | Passed | Failed |
| :--- | :--- | :--- | :--- | :--- |
| **Baseline Project Tests (Stages 1–3)** | `tests/test_*.py` | 299 | 299 | 0 |
| **Stage 4 Machine-State Policy** | `tests/test_machine_state_policy.py` | 26 | 26 | 0 |
| **Stage 4 Full Regression** | **Stage 4 Codebase** | **325** | **325** | **0** |

Stage 4 is fully verified and complete. Machine-state ingestion, conservative UNKNOWN handling, trust-gated Controlled routing, typed policy configurations, and hard safety overrides are operational across the entire PC Doctor engine.
