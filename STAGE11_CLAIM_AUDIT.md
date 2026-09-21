# STAGE 11 — Overclaim & Capability Boundary Audit

**Milestone**: Stage 11 — Final Evidence-Grounded 75-Problem Capability Audit  
**Authoritative Baseline**: PC Doctor v1.0.0-rc.1 Release Candidate  
**Purpose**: Rigorous audit of marketing, documentation, and code claims against verified empirical evidence to eliminate overclaiming and establish precise scientific boundaries.

---

## 1. Audit Methodology

Every statement in repository documentation, comments, and manifests asserting broad capabilities (e.g. *"works on any OS"*, *"automatic repair"*, *"solves"*, *"cross-platform"*, *"fully supported"*) was evaluated against:
1. Actual source code implementation.
2. Verified regression tests across Windows, Linux, and macOS.
3. The authoritative 75-problem capability matrix (`STAGE11_FINAL_75_PROBLEM_MATRIX.md`).

Claims are classified as:
- **SUPPORTED**: Grounded in active code and live/automated test verification.
- **PARTIALLY SUPPORTED / REQUIRES SCOPING**: True for specific subsystems or platforms, but requires explicit boundary definition to prevent generalization.
- **UNSUPPORTED / OVERCLAIM**: Not supported by evidence; requires correction or qualification.

---

## 2. Claim Audit Table

| # | Claim Statement | Location | Empirical Evidence | Supported? | Required Clarification / Correction |
| :-: | :--- | :--- | :--- | :---: | :--- |
| **1** | *"Works on Windows, Linux, and macOS — no modification required."* | `README.md:5` | The desktop application host (Tauri + Vite frontend + FastAPI backend) starts and runs on all three OSes, and test suites pass on Windows, Ubuntu 24.04, and macOS 15. However, automated tool repair capabilities vary by OS (Windows has 42 actionable repairs; Linux/macOS have 46 verified universal/adapter capabilities, with distro-specific edge cases held in review or partial). | **PARTIALLY SUPPORTED** | Clarify: *"Application shell and core diagnostic engine run cross-platform on Windows, Linux, and macOS. Automated repair recipes are actively supported on Windows and standard POSIX environments, with platform-specific operations cleanly isolated."* |
| **2** | *"Automatic Repair Finder: Actively diagnoses local environment anomalies and automatic repair recommendations."* | `devtools-control-center/backend/rag_engine.py:35, 124` | Diagnoses anomalies and generates candidate repair commands. However, RAG candidates are untrusted (`DYNAMIC_DB`) and can **never** bypass user review or the Live Safety Gate. | **PARTIALLY SUPPORTED** | Clarify: *"Recommends candidate repair recipes. In accordance with Stage 5.1/9 safety invariants, untrusted AI recommendations require explicit user review and mandatory Live Safety Gate evaluation before execution."* |
| **3** | *"WinGet: Fully Supported"* | `PC_DOCTOR_75_PROBLEM_SOLVABILITY_REPORT_V2.md:122` | WinGet CLI detection, silent execution, package discovery, and result classification are fully supported and live-verified on Windows. However, Problem #3 (publisher-managed updates) requires external installer handling. | **SUPPORTED (SCOPED)** | Retain with explicit note: *"WinGet CLI package management is fully verified on Windows for standard packages; publisher-managed installers are flagged for manual guidance."* |
| **4** | *"Arbitrary Windows features can be automatically enabled"* | Historical feature discussions | Only a strictly bounded whitelist of 5 virtualization/container features (`Microsoft-Windows-Subsystem-Linux`, `VirtualMachinePlatform`, `HypervisorPlatform`, `Microsoft-Hyper-V`, `Containers`) has verified automated recipes with reboot tags (Stage 7 Decision 1). | **UNSUPPORTED (OVERCLAIM)** | Enforced policy: *"Arbitrary feature enablement is prohibited. Automated repair is strictly bounded to the 5 developer virtualization features; all other Windows features remain REVIEW_ONLY."* |
| **5** | *"Residual Data Cleanup completely cleans and uninstalls all traces"* | Historical Stage 6 notes | While `CACHE_CLEAR` recipes exist in Static DB, universal directory rollback snapshots are not yet proven in live tests (Stage 7 Decision 2). | **UNSUPPORTED (OVERCLAIM)** | Enforced status: Problem #35 remains strictly `PARTIALLY_IMPLEMENTED`. Residual directory deletion is never labeled fully solvable without universal volume snapshotting. |
| **6** | *"Exit code 0 guarantees successful repair"* | Common CI / dev tooling assumption | Stage 3 and Stage 9 proved that an installer or command returning 0 can still leave an unconfigured PATH, shadow another tool, or fail functional probes. | **REFUTED & ENFORCED** | Enforced invariant: $\text{Exit code } 0 \ne \text{Success}$. All operations require L1–L5 verification and post-repair original problem rescan. |
| **7** | *"Tier 3 or User Approval authorizes execution"* | Common privilege escalation design | Stage 5.1 and Stage 9 proved that neither user approval, privilege elevation, nor Tier 3 assignment authorizes execution. | **REFUTED & ENFORCED** | Enforced invariant: $\text{Tier 3 / Elevation / Approval } \ne \text{Execution Clearance}$. The Live Safety Gate is the sole, non-bypassable last-mile authority. |
| **8** | *"PC Doctor solves all 75 developer-environment problems automatically"* | Hypothetical marketing claim | The actual actionable repair boundary is **42 / 75 (56.00%)**. 15 problems (20.00%) are intentionally guarded by human review or hard safety blocking, 11 are detect-only, 6 are partially implemented, and 1 is unimplemented. | **UNSUPPORTED (OVERCLAIM)** | Enforced boundary: State exact metrics (42 actionable, 15 review/blocked, 11 detect-only, 7 partial/unimplemented). Never claim 100% automated resolution. |

---

## 3. Summary of Boundaries Established

1. **Actionable Boundary**: Bounded to **42 / 75 (56.00%)**. Claims of 100% automated repair are scientifically false and rejected.
2. **Review & Policy Boundary**: **15 / 75 (20.00%)** of problems are designed *not* to be automatically repaired. Automation in these areas constitutes unsafe behavior.
3. **Cross-Platform Parity**: PC Doctor achieves cross-platform diagnostic and architecture parity, with primary deep OS-level mutation validation on Windows and contract/adapter validation on Linux and macOS.
