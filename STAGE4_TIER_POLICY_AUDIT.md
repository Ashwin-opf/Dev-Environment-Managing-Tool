# STAGE 4 — MACHINE-STATE & TIER-POLICY CORRECTNESS: ARCHITECTURAL AUDIT

**Date:** 2026-09-17  
**Stage:** Stage 4 — Machine-State & Tier-Policy Correctness  
**Status:** In Progress / Audit Complete  

---

## 1. Executive Summary

Stages 1, 2, and 3 successfully established and verified:
1. Complete dead-code removal and test suite stabilization (270/270 tests).
2. Authoritative execution pipeline consolidation with real host Git call-chain execution (282/282 tests).
3. Generic identity-driven executable verification and effective environment refresh (299/299 tests).

Stage 4 focuses strictly on **machine-state correctness** and **execution-tier policy correctness**. The objective is to eliminate stale, unpopulated, or hardcoded tier selection mechanisms, ensuring that tier assignment is a pure, configuration-driven policy function evaluated against real, normalized host signals.

---

## 2. Comprehensive Component Audit

### 2.1 Current Tier Thresholds (`backend/execution_tier.py`)
Currently, tier boundaries are hardcoded as static module-level constants:
```python
FAST_PATH_TRUST_MIN = 0.85
FAST_PATH_RISK_MAX = 0.30
FAST_PATH_CONFIDENCE_MIN = 0.80

CONTROLLED_RISK_MAX = 0.70
```
In addition, `select_execution_tier()` embeds magic numbers directly in its control flow:
- Full Protected ceiling: `if risk_score < 0.90:`
- Blocked threshold: `risk_score >= 0.90`

**Defects & Limitations:**
- **Zero Configurability:** Thresholds cannot be tuned, customized, or overridden per deployment environment without editing source code.
- **No Type Validation:** No schema or validator exists to ensure thresholds satisfy invariant constraints ($0.0 \le \text{risk\_max} \le 1.0$, $\text{fast\_risk\_max} < \text{controlled\_risk\_max}$).

---

### 2.2 Current Trust Calculation & Missing Controlled Trust Condition
In `backend/execution_tier.py`:
```python
def select_execution_tier(
    recipe: StructuredRecipe,
    trust_score: float = 0.9,
    risk_score: float = 0.2,
    confidence_score: float = 1.0,
    machine_state: Optional[Dict[str, Any]] = None,
) -> Tuple[ExecutionTier, str]:
    ...
    # Fast Path Evaluation
    if (
        trust_score >= FAST_PATH_TRUST_MIN
        and risk_score <= FAST_PATH_RISK_MAX
        and confidence_score >= FAST_PATH_CONFIDENCE_MIN
        and not has_conflict
        and not unusual_state
    ):
        return ExecutionTier.TIER_1_FAST, "Eligible for Fast Path automated execution."

    # Controlled Path Evaluation
    if risk_score <= CONTROLLED_RISK_MAX:
        return ExecutionTier.TIER_2_CONTROLLED, "Routed to Controlled Path (requires standard user review/confirmation)."
```

**Critical Defect — Missing Trust Gating for Controlled Tier:**
- Controlled tier evaluation **only** checks `if risk_score <= CONTROLLED_RISK_MAX:`.
- `trust_score` is **completely ignored** in Controlled tier selection!
- Consequence: An untrusted dynamic recipe or an unknown third-party command with low risk (e.g. `risk = 0.25`, `trust = 0.10`) would be erroneously routed to `TIER_2_CONTROLLED` rather than escalating to `TIER_3_FULL_PROTECTED` or `BLOCKED`.
- Architectural requirement: Controlled tier MUST enforce `risk <= controlled_max_risk AND trust >= controlled_min_trust`.

---

### 2.3 Current Risk Calculation (`compute_live_risk`)
`compute_live_risk()` combines:
1. Base recipe risk: `{"Low": 0.15, "Medium": 0.45, "High": 0.75}`
2. Operation type weighting: `VERSION_CHECK/VERIFY` (0.05), `INSTALL` (+0.05), `UPDATE/REPAIR` (+0.10), `UNINSTALL/REINSTALL` (+0.20)
3. Elevation requirement: (+0.15)
4. Data impact weighting: `NONE` (0.0), `LOW` (0.05), `MEDIUM` (0.15), `HIGH` (0.25)
5. Rollback difficulty weighting: `TRIVIAL` (0.0), `EASY` (0.05), `MEDIUM` (0.10), `HARD` (0.20)
6. Machine state impact:
   ```python
   if machine_state:
       cpu = machine_state.get("cpu_percent", 0.0)
       ram = machine_state.get("ram_percent", 0.0)
       free_disk = machine_state.get("free_disk_gb", 100.0)
       if cpu > 80.0 or ram > 85.0:
           risk += 0.15
       if free_disk < 5.0:
           risk += 0.20
   ```

**Defects & Disconnections:**
- While `compute_live_risk` checks `cpu_percent` and `ram_percent`, the real machine state collector in `state_refresh.py` **never populated them**! They were permanently evaluated as `0.0`.
- The risk calculation lacks awareness of pending reboots, package manager locks, and environment drift.

---

### 2.4 Machine-State Fields & Origin / Consumption Analysis

| Signal Concept | Currently in `state_refresh.py`? | Expected in `execution_tier.py`? | Current Value at Runtime |
| :--- | :---: | :---: | :---: |
| `free_disk_gb` | **Yes** (`shutil.disk_usage`) | Yes | Float (e.g. `120.4`) |
| `total_disk_gb` | **Yes** (`shutil.disk_usage`) | No | Float (e.g. `512.0`) |
| `low_disk_space` | **No** (omitted) | Implicit (`free_disk < 5.0`) | Not a dedicated signal |
| `cpu_percent` | **No** (omitted) | Yes (`cpu > 80.0`) | Evaluated as `0.0` |
| `ram_percent` | **No** (omitted) | Yes (`ram > 85.0`) | Evaluated as `0.0` |
| `conflicts` | **No** (omitted) | Yes (`get("conflicts", False)`) | Always `False` |
| `unusual_state` | **No** (omitted) | Yes (`get("unusual_state", False)`) | Always `False` |
| `pending_reboot` | **No** (omitted) | **No** (unsupported) | Ignored |
| `relevant_service_unexpected_state` | **No** (omitted) | **No** (unsupported) | Ignored |
| `dependency_or_resource_lock` | **No** (omitted) | **No** (unsupported) | Ignored |
| `package_manager_unavailable` | **No** (omitted) | **No** (unsupported) | Ignored |
| `installation_state_changed` | **No** (omitted) | **No** (unsupported) | Ignored |
| `previous_execution_failure` | **No** (omitted) | **No** (unsupported) | Ignored |
| `environment_drift` | **No** (omitted) | **No** (unsupported) | Ignored |

**Origins:**
- Production calls: `backend/execution_engine.py` calls `state_refresher.refresh_machine_state()` (lines 102, 695, 1044).
- Testing calls: Mock dicts in `test_fault_injection_lab.py`, `test_execution_verification_sync.py`, `test_runner.py`.

**Consumption:**
- `execution_tier.compute_live_risk()` and `execution_tier.select_execution_tier()`.

---

### 2.5 Hard Override Support
Currently, `execution_tier.py` contains **zero hard override logic**.
- All routing decisions go through arithmetic score comparisons.
- If an operation touches high-consequence system areas (destructive boot configuration via `bcdedit`, protected firewall configuration via `netsh`, or credential manipulation), it could theoretically be assigned a lower tier if base risk metadata is set to Low and trust is high.
- Safety Layer vs Tier Policy separation:
  - `authoritative_safety.py` decides if an operation is **allowed** (rejects blacklisted commands like `rm -rf /` or `format C:`).
  - `execution_tier.py` must decide **how much protection/approval** is required for an allowed operation.
  - A hard override must intercept critical/protected configurations prior to normal scoring and force `TIER_3_FULL_PROTECTED` or `BLOCKED`.

---

### 2.6 Scope Coupling Violation
In `backend/execution_engine.py`:
```python
# Line 705 and Line 1054:
if elevate or scope == "machine":
    tier = ExecutionTier.TIER_3_ELEVATED_ADMIN
```
**Architectural Violation:**
- The prompt explicitly mandates:
  > "Scope, OS, operation, or application identity must NOT directly determine the tier. Preserve the architectural rule: MACHINE scope does NOT automatically mean CONTROLLED, and USER scope does NOT automatically mean FAST PATH. Scope can influence: permission requirement, operation risk, machine impact, but it must be only an input to policy."
- Hardcoding `if scope == "machine": tier = TIER_3` bypasses policy and breaks scope invariance.

---

### 2.7 Silent Boolean Defaulting & UNKNOWN State Handling
- `select_execution_tier` defaulted missing flags to `False`:
  ```python
  has_conflict = bool(machine_state.get("conflicts", False))
  unusual_state = bool(machine_state.get("unusual_state", False))
  ```
- If a machine probe fails or cannot determine reboot/disk/service status, silently assuming `False` treats an unverified machine state as "safe", violating the safety principle.
- Unverifiable machine states must be represented as `UNKNOWN` and handled conservatively by policy (e.g. ineligible for automated Fast Path).

---

## 3. Action Plan & Architectural Blueprint

```
PLATFORM ADAPTERS (Windows, Linux, Darwin)
  ├── WindowsMachineStateProvider
  ├── LinuxMachineStateProvider
  └── DarwinMachineStateProvider
             ↓
NORMALIZED MACHINE-STATE MODEL (MachineState dataclass / typed schema)
  ├── pending_reboot, low_disk_space, cpu_percent, ram_percent
  ├── dependency_or_resource_lock, package_manager_unavailable
  ├── relevant_service_unexpected_state, previous_execution_failure
  ├── environment_drift, conflicts, unusual_state
  └── Explicit UNKNOWN representation
             ↓
CONFIGURABLE TIER POLICY (TierPolicyConfig)
  ├── Fast Path: trust >= min_trust AND risk <= max_risk AND confidence >= min_conf AND no conflict AND normal state
  ├── Controlled: trust >= controlled_min_trust AND risk <= controlled_max_risk
  ├── Full Protected: high risk OR hard override OR untrusted/low trust
  └── Blocked: safety violation OR insurmountable risk
             ↓
PURE POLICY SELECTOR (select_execution_tier)
  1. Read-only operation check (Tier 0)
  2. Hard Safety Override evaluation (Tier 3 or Blocked)
  3. Machine State assessment (Unknown / Conflict / Unusual checks)
  4. Configurable Scoring & Gating (Tier 1 Fast vs Tier 2 Controlled vs Tier 3 Full Protected vs Blocked)
```
