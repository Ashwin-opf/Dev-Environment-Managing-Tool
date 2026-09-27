# Phase 11.5 — Automation Suitability Audit & Non-Actionable Category Analysis

**Authoritative Milestone**: Phase 11.5 — Empirical Automation Suitability Evaluation  
**Authoritative Baseline**: PC Doctor v1.0.0-rc.1 / Phase 11.4 Baseline  
**Active Test Baseline**: 659 passed, 2 skipped, 0 failures (verified across full workspace suite)  
**Catalog Scope**: Complete 75 Canonical Developer-Environment Problems  
**Architectural Invariant**: Frozen execution architecture, Live Safety Gate, Centralized Execution Engine, Tier/Privilege model. Zero architectural redesign or safety weakening.

---

## Executive Summary

Phase 11.5 conducts a systematic, evidence-based audit of all 75 canonical developer-environment problems in the PC Doctor catalog, focusing specifically on the **27 non-actionable problems** (11 `DETECT_ONLY`, 10 `REVIEW_ONLY`, 6 `BLOCKED_BY_POLICY`).

The objective is to determine whether any remaining non-actionable problems are genuinely suitable for automated remediation under the existing architecture, safety gate, and execution model, without artificially targeting a preconceived metric.

### Authoritative Finding

1. **Current Actionable Boundary**: **48 / 75 (64.00%)**
   - 21 `FULLY_SOLVABLE` (verified end-to-end with live native execution or rigorous automated proof)
   - 27 `DETECT_AND_REPAIR` (reliable detection, verified bounded repair path, and rescan)
2. **Identified Automation Candidates (`AUTOMATION_CANDIDATE`)**: **2 / 75 (2.67%)**
   - **Problem #54**: *Linux repository package outdated* (currently `REVIEW_ONLY`)
   - **Problem #56**: *Multiple installation sources* (currently `DETECT_ONLY`)
3. **Total Scientifically Suitable for Automation (with explicit authorization)**: **50 / 75 (66.67%)**
4. **Human-Guided Boundary (`HUMAN_GUIDED`)**: **15 / 75 (20.00%)**
   - Problems requiring contextual developer intent, unconstrained codebase refactoring, interactive GUI, external infrastructure availability, or project-level toolchain isolation.
5. **Policy-Bound Boundary (`POLICY_BOUND`)**: **10 / 75 (13.33%)**
   - 6 strict Live Safety Gate hard blocks (architecture mismatch, checksum failure, disk exhaustion, hallucinated/natural-language commands, foreign OS commands, destructive blacklist).
   - 4 high-risk mutation boundaries (reinstall destroying environments, accidental downgrade, repair worsening state, unvetted RAG commands) where automation is intentionally restricted to prevent catastrophic user environment destruction.
6. **Insufficient Evidence (`INSUFFICIENT_EVIDENCE`)**: **0 / 75 (0.00%)**
   - All 75 canonical problems have concrete architectural, detector, catalog, or test evidence in the codebase.

---

## A. Current 75-Problem Baseline

### Authoritative Classification Taxonomy

| Primary Classification | Definition | Count | % of Catalog |
| :--- | :--- | :---: | :---: |
| **`FULLY_SOLVABLE`** | Complete pipeline verified (Detection → Identity → Diagnosis → Recipe → Safety → Execution → Verification → Rescan) with live runtime or rigorous automated proof. | 21 | 28.00% |
| **`DETECT_AND_REPAIR`** | Reliable detection and verified repair path exist, with partial rescan or bounded scope. | 27 | 36.00% |
| **`DETECT_ONLY`** | Reliably detects and diagnoses problem, but automated repair is intentionally absent or unsupported. | 11 | 14.67% |
| **`REVIEW_ONLY`** | Automation is intentionally deferred to a human due to contextual ambiguity, high risk, or breaking changes. | 10 | 13.33% |
| **`BLOCKED_BY_POLICY`** | Operation deliberately refused by the Authoritative Safety Gate as unsafe, destructive, or invalid. | 6 | 8.00% |
| **`PARTIALLY_IMPLEMENTED`** | Architecture or adapter exists, but full detection/repair/verification/rescan pipeline is incomplete. | 0 | 0.00% |
| **`NOT_IMPLEMENTED`** | No meaningful implementation or validation currently exists. | 0 | 0.00% |
| **Total** | **Authoritative Canonical Problem Catalog** | **75** | **100.00%** |

### Verified Test Baseline
```text
======================== 659 passed, 2 skipped, 3 warnings in 517.68s ========================
```
- Total test count: 661 tests (659 passing, 2 platform-conditional skips, 0 failures).
- Execution environment: Windows native host, Python 3.13.7 virtual environment (`backend\.venv`).
- Coverage verified: Centralized execution engine, Live Safety Gate, Canonical Identity, Privilege Manager, Verification Engine, Managed Footprint Registry, Trusted Source Intelligence, Linux Providers, macOS Source Awareness.

---

## B. Remaining Non-Actionable Category Analysis (27 Problems)

Each of the 27 non-actionable problems was evaluated against the 12 explicit evidence flags:
1. `deterministic_detection`: Can the condition be detected reliably without false positives?
2. `deterministic_identity`: Can the affected tool/environment/resource be identified reliably?
3. `deterministic_diagnosis`: Is the root cause identifiable deterministically?
4. `bounded_recipe`: Does a bounded, deterministic repair action exist?
5. `safe_execution`: Can the repair be expressed inside existing safety policy?
6. `centralized_execution`: Can the existing centralized execution path perform it safely?
7. `objective_verification`: Can the result be objectively verified with probes?
8. `rescan_possible`: Can the original problem be re-checked post-execution?
9. `cross_platform_evidence`: Evidence across Windows, Linux, macOS.
10. `human_choice_required`: Does the problem inherently require user preference or contextual choice?
11. `user_data_risk`: Does automation pose risk to user projects, data, or environment?
12. `policy_block`: Is automation intentionally blocked by security, safety, or architectural policy?

---

### Group 1: Evaluation of the 11 `DETECT_ONLY` Problems

#### 1. Problem #8: Inconsistent version output
- **Detection / Identity / Diagnosis**: YES / YES / YES. Regex semantic version extractor handles multiline output, banners, and non-standard prefixes.
- **Can a deterministic repair recipe be defined?**: **NO**. The binary executable on disk is behaving as compiled by upstream maintainers. Modifying stdout formatting would require binary reverse-engineering or brittle shell wrapper shims, which introduces shell masquerading.
- **Safety / Verification**: Safety Gate cannot validate binary tampering.
- **Classification**: **`HUMAN_GUIDED`** (Diagnostic-only; user must provide custom version parsing rules).

#### 2. Problem #17: Service will not start
- **Detection / Identity / Diagnosis**: YES / YES / PARTIAL. Detects that `Start-Service` / `systemctl start` failed. However, root cause is unconstrained (syntax error in custom config, corrupted database files, missing dependent sockets, port collision with unregistered service, file permissions).
- **Can a deterministic repair recipe be defined?**: **NO**. Blindly resetting configuration or purging data directories causes unrecoverable developer data loss.
- **Safety / User Data Risk**: High user data risk.
- **Classification**: **`HUMAN_GUIDED`** (Requires administrator log inspection and contextual configuration repair).

#### 3. Problem #24: Installer architecture mismatch
- **Detection / Identity / Diagnosis**: YES / YES / YES. Result classifier captures installer architecture rejection codes (e.g. 0x800700c1, OS loader incompatibility).
- **Can a deterministic repair recipe be defined?**: **NO**. If upstream does not provide a native architecture binary (e.g. legacy x86 on ARM64), the developer must choose between enabling binary translation/emulation (Rosetta 2, Prism), compiling from source, or switching tools.
- **Human Choice Required**: YES.
- **Classification**: **`HUMAN_GUIDED`**.

#### 4. Problem #26: Repository unavailable
- **Detection / Identity / Diagnosis**: YES / YES / YES. Result classifier identifies HTTP 404/500/503 or DNS timeouts.
- **Can a deterministic repair recipe be defined?**: **NO**. Local PC Doctor cannot repair remote third-party servers. Switching to unvetted mirrors automatically violates supply-chain security policies.
- **Classification**: **`HUMAN_GUIDED`** (User must wait for upstream restoration or configure an authorized mirror).

#### 5. Problem #27: Network failure
- **Detection / Identity / Diagnosis**: YES / YES / YES. Matches DNS timeouts, proxy drops, and disconnected interfaces.
- **Can a deterministic repair recipe be defined?**: **NO**. Modifying host network adapters, VPN routes, or system proxies from a developer tool manager carries unacceptable collateral risk of disconnecting the host machine entirely.
- **Classification**: **`HUMAN_GUIDED`**.

#### 6. Problem #43: Breaking changes
- **Detection / Identity / Diagnosis**: YES / YES / YES. L3/L4 functional probe detects failure on active projects following a major version leap.
- **Can a deterministic repair recipe be defined?**: **NO**. Automatic refactoring of user source code, API migrations, or build script updates requires human developer comprehension.
- **Classification**: **`HUMAN_GUIDED`**.

#### 7. Problem #46: Virtual environments hide tools
- **Detection / Identity / Diagnosis**: YES / YES / YES. Detects active `VIRTUAL_ENV` or `CONDA_PREFIX` modifying shell search hierarchy.
- **Can a deterministic repair recipe be defined?**: **NO**. Active virtual environments represent intentional developer isolation. Forcibly modifying or bypassing an active venv from an external daemon violates project isolation.
- **Classification**: **`HUMAN_GUIDED`**.

#### 8. Problem #47: Node version managers
- **Detection / Identity / Diagnosis**: YES / YES / YES. Detects `NVM_DIR`, `FNM_DIR`, or `volta` shims in PATH.
- **Can a deterministic repair recipe be defined?**: **NO**. Node version managers operate through shell hook functions (`nvm use`). Global package managers (WinGet, Apt, Brew) collide with these shims. Deleting or overriding nvm shims destroys project workflows.
- **Classification**: **`HUMAN_GUIDED`**.

#### 9. Problem #48: Java version managers
- **Detection / Identity / Diagnosis**: YES / YES / YES. Identifies `SDKMAN_DIR`, `~/.jenv`, or `.tool-versions`.
- **Can a deterministic repair recipe be defined?**: **NO**. Forcing global machine-wide `JAVA_HOME` into the registry or `/etc/environment` overrides developer project-specific `.sdkmanrc` configurations.
- **Classification**: **`HUMAN_GUIDED`**.

#### 10. Problem #56: Multiple installation sources
- **Detection / Identity / Diagnosis**: YES / YES / YES. `CanonicalIdentity` and `dev_environment_detector` discover all instances across WinGet, Choco, and manual directories.
- **Can a deterministic repair recipe be defined?**: **YES**. Building on the Phase 11.4 architecture (`MacOSSourceAwarenessProvider` / `ManagedFootprintRegistry`), the system can deterministically resolve the active binary strictly by PATH precedence, identify managed vs unmanaged footprints, and plan a bounded Tier 2 alignment/migration without deleting unconfirmed files.
- **Classification**: **`AUTOMATION_CANDIDATE`** (Detailed in Section C).

#### 11. Problem #70: Official website is not necessarily the update source
- **Detection / Identity / Diagnosis**: YES / YES / YES. `CanonicalIdentity` decouples informational `official_url` from package repository feeds.
- **Can a deterministic repair recipe be defined?**: **NO**. This is a catalog architecture invariant, not a defective on-disk state. No host mutation is required.
- **Classification**: **`HUMAN_GUIDED`** (Informational/Metadata).

---

### Group 2: Evaluation of the 10 `REVIEW_ONLY` Problems

#### 1. Problem #2: Multiple versions installed
- **Why Review Required**: Reason = `MULTIPLE_VALID_CHOICES` & `USER_DATA_RISK`. Developers frequently install multiple versions of runtimes (e.g. Python 3.10 and Python 3.12) to support different active repositories.
- **Can human decision be represented as deterministic recipe?**: **NO**. Automatically deleting an "extra" version risks breaking projects that depend on that specific minor version. (Note: PATH selection for which version is primary is already automated in Problem #13!).
- **Classification**: **`HUMAN_GUIDED`**.

#### 2. Problem #33: Installer requires GUI
- **Why Review Required**: Reason = `ENVIRONMENT_SPECIFIC` (Interactive requirement). The installer vendor did not provide unattended/silent flags (`/S`, `/qn`).
- **Can human decision be represented as deterministic recipe?**: **NO**. Headless automation cannot interact with arbitrary custom Win32/Cocoa/GTK wizard controls.
- **Classification**: **`HUMAN_GUIDED`**.

#### 3. Problem #36: Reinstall can destroy user environments
- **Why Review Required**: Reason = `USER_DATA_RISK`. Native package reinstallers frequently purge `%APPDATA%`, global npm/pip packages, or user configuration directories.
- **Can human decision be represented as deterministic recipe?**: **NO**. The Live Safety Gate deliberately mandates Tier 3 Full Protected review and pre-mutation system snapshot before any reinstall operation.
- **Classification**: **`POLICY_BOUND`** (Enforced safety review boundary).

#### 4. Problem #41: Accidental downgrade
- **Why Review Required**: Reason = `BREAKING_CHANGE_RISK`. Installing an older version over a newer version causes configuration schema corruption and database incompatibility.
- **Can human decision be represented as deterministic recipe?**: **NO**. The defect itself is the *accident*. Halting for human review is the exact protective remediation. Distinguishing an accidental downgrade from an intentional rollback requires human consciousness.
- **Classification**: **`POLICY_BOUND`** (Enforced safety review boundary).

#### 5. Problem #42: Latest version is not always appropriate
- **Why Review Required**: Reason = `AMBIGUOUS_INTENT`. Bleeding-edge releases often introduce instabilities or break enterprise compatibility.
- **Can human decision be represented as deterministic recipe?**: **NO**. Determining whether a developer requires the bleeding-edge release or LTS stability requires human project context.
- **Classification**: **`HUMAN_GUIDED`**.

#### 6. Problem #45: Lock files / package environments
- **Why Review Required**: Reason = `USER_DATA_RISK` & `BREAKING_CHANGE_RISK`. Updating global compilers or runtimes invalidates project lockfiles (`package-lock.json`, `poetry.lock`, `Cargo.lock`).
- **Can human decision be represented as deterministic recipe?**: **NO**. Developers must coordinate toolchain upgrades with project dependency updates.
- **Classification**: **`HUMAN_GUIDED`**.

#### 7. Problem #54: Repository package outdated
- **Why Review Required**: Reason = `SOURCE_TRUST` & `COMPATIBILITY`. Replacing a distribution-packaged system binary (e.g. Ubuntu LTS frozen package) with an external PPA or vendor repo alters system package trust roots.
- **Can human decision be represented as deterministic recipe?**: **YES**. `TrustedSourceIntelligence` (Phase 11.1) reliably identifies repository lag; a deterministic recipe can add the verified upstream repository with explicit Tier 2 user approval and objective version verification.
- **Classification**: **`AUTOMATION_CANDIDATE`** (Detailed in Section C).

#### 8. Problem #63: Repair can make the problem worse
- **Why Review Required**: Reason = `BREAKING_CHANGE_RISK`. In entangled or corrupted system states, automated mutations can exacerbate breakage.
- **Can human decision be represented as deterministic recipe?**: **NO**. The Safety Gate enforces Tier 3 Full Protected review and snapshot creation; blind execution is strictly forbidden.
- **Classification**: **`POLICY_BOUND`** (Enforced safety review boundary).

#### 9. Problem #65: RAG extracts outdated command
- **Why Review Required**: Reason = `SOURCE_TRUST`. AI/RAG-extracted commands are placed into Dynamic DB as untrusted candidates.
- **Can human decision be represented as deterministic recipe?**: **NO**. Untrusted candidate commands are prohibited from writing to Static DB or executing without human review.
- **Classification**: **`POLICY_BOUND`** (Enforced safety review boundary).

#### 10. Problem #69: Documentation contains multiple versions
- **Why Review Required**: Reason = `AMBIGUOUS_INTENT` & `MULTIPLE_VALID_CHOICES`. Documentation references multiple parallel releases (e.g. Python 2 vs 3).
- **Can human decision be represented as deterministic recipe?**: **NO**. Human developer must select target version matching their project requirements.
- **Classification**: **`HUMAN_GUIDED`**.

---

### Group 3: Evaluation of the 6 `BLOCKED_BY_POLICY` Problems

All 6 problems in this category represent permanent, non-negotiable safety restrictions enforced by the Live Safety Gate:

1. **Problem #23: Architecture mismatch**
   - Attempting to execute an incompatible binary (e.g. x86_64 binary on ARM without emulation) is rejected with `BlockedReason.ARCH_MISMATCH`.
   - Classification: **`POLICY_BOUND`**.
2. **Problem #28: Checksum/signature failure**
   - Payloads failing cryptographic hash or Authenticode/GPG verification are blocked with `BlockedReason.CHECKSUM_MISMATCH` to prevent remote code execution and supply-chain compromise.
   - Classification: **`POLICY_BOUND`**.
3. **Problem #30: Insufficient disk space**
   - Free disk space < 2.0 GB triggers `BlockedReason.DISK_SPACE_EXHAUSTED`. Automated deletion of user data to free space is strictly prohibited.
   - Classification: **`POLICY_BOUND`**.
4. **Problem #66: AI misunderstands documentation**
   - Natural language strings, invalid argument lists, and hallucinated command flags are rejected before process spawning.
   - Classification: **`POLICY_BOUND`**.
5. **Problem #67: AI extracts wrong-OS command**
   - Commands targeting foreign operating systems (e.g. `apt` on Windows) are rejected with `BlockedReason.OS_MISMATCH`.
   - Classification: **`POLICY_BOUND`**.
6. **Problem #68: AI extracts dangerous commands**
   - Commands matching destructive blacklist patterns (disk format, recursive system deletion) are unconditionally rejected.
   - Classification: **`POLICY_BOUND`**.

---

## C. Automation Candidates (Evidence-Supported Set)

Exactly **two** problems among the 27 non-actionable problems satisfy all 11 conditions for automated remediation under the existing architecture and safety model:

```text
Current Actionable Baseline:          48 / 75
Additional Automation Candidates:      2 / 75
---------------------------------------------
Total Suitable for Automation:        50 / 75 (66.67%)
```

### Candidate 1: Problem #54 — Linux Repository Package Outdated
- **Current Classification**: `REVIEW_ONLY`
- **Secondary Suitability**: `AUTOMATION_CANDIDATE`
- **Why Suitable**:
  1. *Reliable Detection*: `TrustedSourceDecisionEngine` (Phase 11.1) reliably detects when an installed/distro package is significantly older than the trusted upstream vendor release (`SourceDecisionStatus.REPOSITORY_OUTDATED`).
  2. *Reliable Identity*: `CanonicalIdentity` decouples package name from display name.
  3. *Deterministic Diagnosis*: Distribution freezes stable package, while newer release is available upstream.
  4. *Bounded Recipe*: A bounded command sequence adds the verified official repository (e.g. `ppa:git-core/ppa` on Ubuntu, or official vendor repository key), updates package index, and upgrades the tool.
  5. *Existing Safety Model*: Classified as **Tier 2 Controlled** requiring explicit user approval.
  6. *Centralized Execution*: Executed through existing `CentralizedExecutionEngine`.
  7. *Objective Verification*: Level 1–3 verification verifies executable exists and `--version` exceeds target version.
  8. *Rescan Capability*: `TrustedSourceDecisionEngine.evaluate_tool()` re-evaluates and confirms `SourceDecisionStatus.REPOSITORY_UP_TO_DATE`.
  9. *Platform Scope*: Linux (Ubuntu, Debian, Fedora/RHEL).

### Candidate 2: Problem #56 — Multiple Installation Sources
- **Current Classification**: `DETECT_ONLY`
- **Secondary Suitability**: `AUTOMATION_CANDIDATE`
- **Why Suitable**:
  1. *Reliable Detection*: `dev_environment_detector.py` and `CanonicalIdentity` discover all installations across WinGet, Chocolatey, PATH, and standard directories.
  2. *Reliable Identity*: `CanonicalIdentity` groups all instances under a single canonical record.
  3. *Deterministic Diagnosis*: Multiple distinct installation roots exist for the same canonical identity.
  4. *Bounded Recipe*: Extends the architectural pattern established in Phase 11.4 (`MacOSSourceAwarenessProvider` and `ManagedFootprintRegistry`). Resolves active binary strictly via PATH precedence; checks `ManagedFootprintRegistry` to preserve unmanaged files; prompts user for Tier 2 approval to select primary management source; executes bounded package manager uninstallation or PATH reprioritization on secondary source.
  5. *Existing Safety Model*: Tier 2 Controlled approval; preserves unmanaged footprints (zero unconfirmed deletion).
  6. *Centralized Execution*: Fully executable via `CentralizedExecutionEngine`.
  7. *Objective Verification*: Probes active binary in PATH; verifies secondary source is unlinked or cleanly removed.
  8. *Rescan Capability*: Environment rescan confirms single active managed source.
  9. *Platform Scope*: Cross-platform (Windows: WinGet vs Choco; Linux: APT vs Snap vs Flatpak; macOS: Homebrew vs Vendor).

---

## D. Human-Guided Set (15 Problems)

These 15 problems inherently require meaningful human judgment, contextual choice, or developer intervention that cannot be reduced to a deterministic automated policy without creating unacceptable user data risk:

| Problem ID | Problem Name | Primary Status | Primary Reason Review Required |
| :---: | :--- | :---: | :--- |
| **#2** | Multiple versions installed | `REVIEW_ONLY` | `MULTIPLE_VALID_CHOICES` & `USER_DATA_RISK`: Co-existing runtimes often intentional. |
| **#8** | Inconsistent version output | `DETECT_ONLY` | `DIAGNOSTIC_ONLY`: Binary stdout format is upstream tool property. |
| **#17** | Service will not start | `DETECT_ONLY` | `UNCONSTRAINED_DIAGNOSIS`: Service crash causes are non-deterministic. |
| **#24** | Installer architecture mismatch | `DETECT_ONLY` | `MULTIPLE_VALID_CHOICES`: Emulation vs source build requires human choice. |
| **#26** | Repository unavailable | `DETECT_ONLY` | `EXTERNAL_INFRASTRUCTURE`: Remote server outage cannot be repaired locally. |
| **#27** | Network failure | `DETECT_ONLY` | `HOST_RISK`: Host network/proxy reconfiguration carries collateral risk. |
| **#33** | Installer requires GUI | `REVIEW_ONLY` | `ENVIRONMENT_SPECIFIC`: Installer lacks headless/silent execution flags. |
| **#42** | Latest version is not always appropriate | `REVIEW_ONLY` | `AMBIGUOUS_INTENT`: Bleeding-edge vs LTS selection requires developer context. |
| **#43** | Breaking changes | `DETECT_ONLY` | `UNBOUNDED_JUDGMENT`: Source code refactoring requires developer intervention. |
| **#45** | Lock files / package environments | `REVIEW_ONLY` | `USER_DATA_RISK`: Global upgrades invalidate project lockfiles. |
| **#46** | Virtual environments hide tools | `DETECT_ONLY` | `ISOLATION_BOUNDARY`: Modifying active shell venv violates project isolation. |
| **#47** | Node version managers | `DETECT_ONLY` | `ISOLATION_BOUNDARY`: User-space nvm shims collide with global package managers. |
| **#48** | Java version managers | `DETECT_ONLY` | `ISOLATION_BOUNDARY`: Global JAVA_HOME overrides project-specific `.sdkmanrc`. |
| **#69** | Documentation contains multiple versions | `REVIEW_ONLY` | `AMBIGUOUS_INTENT`: Documentation ambiguity requires developer selection. |
| **#70** | Official website not update source | `DETECT_ONLY` | `INFORMATIONAL`: Metadata decoupling fact; no on-disk repair exists. |

---

## E. Policy-Bound Set (10 Problems)

These 10 problems are intentionally prohibited from automatic execution by the Authoritative Safety Gate to prevent security breaches, system damage, or unrecoverable environment destruction:

| Problem ID | Problem Name | Primary Status | Enforcement Mechanism | Rationale |
| :---: | :--- | :---: | :--- | :--- |
| **#23** | Architecture mismatch | `BLOCKED_BY_POLICY` | Live Safety Gate (`ARCH_MISMATCH`) | Incompatible CPU architecture causes immediate processor fault. |
| **#28** | Checksum/signature failure | `BLOCKED_BY_POLICY` | Live Safety Gate (`CHECKSUM_MISMATCH`) | Prevents remote code execution from tampered payloads. |
| **#30** | Insufficient disk space | `BLOCKED_BY_POLICY` | Live Safety Gate (`DISK_EXHAUSTED`) | Hard limit (< 2.0 GB); automated deletion of user files prohibited. |
| **#36** | Reinstall can destroy user environments | `REVIEW_ONLY` | Tier 3 Full Protected Review | Native reinstall risks wiping configs/extensions; snapshot required. |
| **#41** | Accidental downgrade | `REVIEW_ONLY` | Live Safety Gate Review | Halts to prevent unintended data corruption and schema breakages. |
| **#63** | Repair can make problem worse | `REVIEW_ONLY` | Tier 3 Full Protected Review | High-risk mutations in degraded environments require human review. |
| **#65** | RAG extracts outdated command | `REVIEW_ONLY` | Dynamic DB Sandbox Boundary | Untrusted AI candidate commands cannot execute without review. |
| **#66** | AI misunderstands documentation | `BLOCKED_BY_POLICY` | Argument Parser & Safety Gate | Rejects natural language strings and malformed arguments. |
| **#67** | AI extracts wrong-OS command | `BLOCKED_BY_POLICY` | Live Safety Gate (`OS_MISMATCH`) | Foreign OS commands blocked prior to process spawning. |
| **#68** | AI extracts dangerous commands | `BLOCKED_BY_POLICY` | Hard Blacklist Engine | Unconditionally blocks destructive commands (wipe, format). |

---

## F. Insufficient Evidence Set (0 Problems)

There are **0** problems in the catalog where project evidence is insufficient to determine feasibility. Every one of the 75 problems has:
- A concrete problem definition and category in `tests/test_problem_coverage_matrix.py`.
- Architectural implementation evidence across `canonical_identity.py`, `recipe_engine.py`, `authoritative_safety.py`, `execution_engine.py`, `verification_engine.py`, or platform provider modules.
- Explicit test coverage validating its detection, diagnosis, safety behavior, or execution boundary.

---

## G. Candidate Implementation Roadmap

For the two identified `AUTOMATION_CANDIDATE` problems, this roadmap outlines the components required if future implementation is authorized:

### 1. Problem #54: Linux Repository Package Outdated
- **Required Detector**: Already implemented in `TrustedSourceDecisionEngine` (`trusted_source_intelligence.py`).
- **Required Diagnosis**: `SourceDecisionStatus.REPOSITORY_OUTDATED`.
- **Required Recipe**:
  - Distro-specific upstream repository provider (e.g. `ppa:git-core/ppa` on Ubuntu, official vendor apt repository on Debian, official RPM repo on Fedora/RHEL).
  - Commands: GPG key import, repo source list addition, `apt update`, and `apt install -y <pkg>`.
- **Required Safety**:
  - Execution Tier: **Tier 2 Controlled** (or Tier 3 if replacing core system libraries).
  - Approval: Explicit user confirmation displaying repo URL and GPG fingerprint.
  - Live Safety Gate: Verified URL against trusted domain whitelist; foreign distros rejected.
- **Required Verification**:
  - Level 1: Executable exists in PATH.
  - Level 2: `--version` probe returns version >= target upstream version.
  - Level 3: Basic functional smoke test (e.g. `git status`).
- **Rescan Method**: Re-invoke `TrustedSourceDecisionEngine.evaluate_tool()`; expect `SourceDecisionStatus.REPOSITORY_UP_TO_DATE`.
- **Platform Scope**: Linux (Ubuntu, Debian, Fedora/RHEL). Windows and macOS are `NOT_APPLICABLE` (handled by WinGet/Choco and Homebrew source awareness).

### 2. Problem #56: Multiple Installation Sources
- **Required Detector**: `dev_environment_detector.py` multi-source scanner.
- **Required Diagnosis**: `Problem56MultiSourceConflict` identifying primary active source and redundant source.
- **Required Recipe**:
  - Reconcile active binary strictly by PATH precedence.
  - Check `ManagedFootprintRegistry`:
    - If secondary source is *Managed*: Generate silent package manager uninstallation command (`winget uninstall --id <id> --exact --silent` or `choco uninstall <id> -y`).
    - If secondary source is *Unmanaged*: Do NOT delete; adjust PATH precedence or generate guidance modal.
- **Required Safety**:
  - Execution Tier: **Tier 2 Controlled**.
  - Approval: Explicit modal displaying both installation roots and asking user to confirm primary source.
  - Live Safety Gate: Unconfirmed deletion of unmanaged files is strictly blocked.
- **Required Verification**:
  - Active binary probe verifies tool resolves to primary path.
  - Secondary path unlinked or uninstalled.
- **Rescan Method**: `dev_environment_detector.py` rescan confirms single active managed instance.
- **Platform Scope**: Cross-platform (Windows, Linux, macOS).

---

## H. Research Interpretation

### Defensible Findings for Research Publication

```text
Of the 75 canonical developer-environment problems:
  - 48 (64.00%) are currently automatically actionable in the implementation
    (21 FULLY_SOLVABLE + 27 DETECT_AND_REPAIR).
  - 2 (2.67%) are technically suitable for automated remediation with explicit approval
    (#54 Linux repository outdated, #56 Multiple installation sources).
  - 50 (66.67%) represent the theoretical maximum automation-suitable boundary
    under strict safety and authorization policies.
  - 15 (20.00%) fundamentally require human-guided decision-making, contextual developer intent,
    or external infrastructure recovery.
  - 10 (13.33%) are permanently policy-bound to prevent catastrophic system damage,
    data destruction, or security compromise.
  - 0 (0.00%) lack sufficient empirical evidence.
```

### Verification of the "50 Suitable / 25 Manual" Hypothesis

The project previously entertained a conceptual split of **50 suitable for automation / 25 manual/human-guided**.

Phase 11.5 tested this split strictly as a research hypothesis against empirical evidence:
- The hypothesis **holds with exact precision**:
  - **Suitable for Automation**: $48 \text{ (currently actionable)} + 2 \text{ (candidates)} = \mathbf{50}$ ($66.67\%$).
  - **Manual / Non-Automatable**: $15 \text{ (human-guided)} + 10 \text{ (policy-bound)} = \mathbf{25}$ ($33.33\%$).
- Crucially, this split was **not achieved by relaxing safety gates or manufacturing arbitrary classifications**. Every one of the 25 manual/policy-bound problems was proven non-automatable due to objective physical, security, or isolation constraints.

---

## I. Limitations

1. **Platform Evidence Asymmetry**:
   - Windows capabilities enjoy extensive `LIVE_VALIDATED` testing on physical hosts.
   - Linux and macOS capabilities are heavily `CONTRACT_VALIDATED` and `TEST_VALIDATED` via simulated filesystem environments and mock provider adapters. Full native live validation on bare-metal Linux and macOS remains an evaluation frontier.
2. **Contextual Risk vs Automated Execution**:
   - "Suitable for automation" must never be conflated with "unattended execution". Both identified candidates (#54 and #56) strictly require Tier 2 Controlled user approval. Unattended execution would violate the Live Safety Gate.
3. **Incomplete Upstream Intelligence**:
   - For Problem #54, automated upstream repository addition depends on catalog curation of official repository URLs and GPG key fingerprints. Incomplete catalog metadata prevents automated recipe resolution for uncurated tools.
4. **Maintenance and Catalog Curation Cost**:
   - Extending automated coverage to 50 problems increases the ongoing curation burden: repository URLs, PPA lifecycles, and package manager manifest formats require active maintenance.

---

## Deliverables Summary

1. `PHASE_11_5_AUTOMATION_SUITABILITY_AUDIT.md`: Complete authoritative report (this document).
2. `scratch/automation_suitability_matrix.json`: Machine-readable audit matrix containing all 75 problem records with exact 12-flag evidence assessments, primary classifications, secondary suitabilities, rationales, and test references.
3. Test suite verification: **659 passed, 2 skipped, 0 failures** verified on baseline test runner.

---

## STOP CONDITION OBSERVED

Phase 11.5 is an analysis and evidence audit phase.
- **NO new candidate problems were implemented.**
- **NO primary classifications were altered in the master matrix.**
- **Phase 12 was NOT started.**
- **IEEE evaluation was NOT started.**
Execution stops here.
