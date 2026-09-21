# STAGE 11 — Final 75-Problem Capability Matrix

**Milestone**: Stage 11 — Final 75-Problem Capability Audit  
**Authoritative Baseline**: PC Doctor v1.0.0-rc.1 Release Candidate  
**Audit Scope**: Complete 75 Canonical Developer-Environment Problems  
**Ground Truth Principle**: Strictly evidence-grounded. Implementation without verification is never marked fully solved.  

---

## 1. Primary Classification Taxonomy

| Classification | Definition | Count | % |
| :--- | :--- | :---: | :---: |
| **`FULLY_SOLVABLE`** | Complete workflow verified (Detection → Identity → Diagnosis → Recipe → Safety → Execution → Verification → Rescan) with live runtime or rigorous automated proof. | 21 | 28.00% |
| **`DETECT_AND_REPAIR`** | Reliable detection and verified repair path exist, with partial rescan or bounded scope. | 21 | 28.00% |
| **`DETECT_ONLY`** | Reliably detects and diagnoses problem, but automated repair is intentionally absent or unsupported. | 11 | 14.67% |
| **`REVIEW_ONLY`** | Automation is intentionally deferred to a human due to contextual ambiguity, high risk, or breaking changes. | 9 | 12.00% |
| **`BLOCKED_BY_POLICY`** | Operation deliberately refused by the Authoritative Safety Gate as unsafe, destructive, or invalid. | 6 | 8.00% |
| **`PARTIALLY_IMPLEMENTED`** | Architecture or adapter exists, but full detection/repair/verification/rescan pipeline is incomplete. | 6 | 8.00% |
| **`NOT_IMPLEMENTED`** | No meaningful implementation or validation currently exists. | 1 | 1.33% |
| **Total** | **Authoritative Canonical Problem Catalog** | **75** | **100.00%** |

---

## 2. Canonical 75-Problem Master Matrix

| # | Problem | Detection | Identity | Diagnosis | Recipe | Safety | Execution | Verification | Rescan | Status | Evidence | Platforms |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|---|---|
| 1 | Package manager says installed but tool is unusable / PATH problem | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_git_mvp_runtime_call_chain.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 2 | Multiple versions installed | YES | YES | YES | NO | YES | NO | YES | YES | REVIEW_ONLY | AUTOMATED: test_elevation_architecture.py::test_multiple_python_versions_review_only | Win:TEST | Lnx:TEST | Mac:TEST |
| 3 | Update exists but package manager cannot perform it | YES | YES | YES | NO | YES | YES | NO | YES | DETECT_AND_REPAIR | AUTOMATED: test_update_classifier.py::test_publisher_managed_winget_output | Win:TEST | Lnx:TEST | Mac:TEST |
| 4 | Package manager says no update but official source has newer version | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 5 | Manual installation not recognized | YES | YES | YES | NO | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_tool_detector.py::test_detect_tool_from_path | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 6 | Package-manager ID differs from display name | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py::test_canonical_identity_decouples_names_and_ids | Win:LIVE | Lnx:TEST | Mac:TEST |
| 7 | Executable name differs from application name | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py::test_executable_separated_from_arguments | Win:LIVE | Lnx:TEST | Mac:TEST |
| 8 | Inconsistent version output | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_verification_environment_hardening.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 9 | --version does not work | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_verification_environment_hardening.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 10 | GUI application has no CLI in PATH | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 11 | User PATH vs System PATH | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_path_repair_architecture.py::test_1_git_machine_path_repair_with_uac | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |
| 12 | Stale PATH | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_path_repair_architecture.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 13 | PATH order selects wrong version | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_verification_environment_hardening.py::test_executable_shadowing_detection | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 14 | Terminal restart needed | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_verification_environment_hardening.py::test_refresh_effective_environment_reads_registry | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |
| 15 | Reboot required | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_machine_state_policy.py (26 tests) | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |
| 16 | Service not running | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_stage7_coverage.py::TestSC1ServiceRepairRecipes | Win:LIVE | Lnx:TEST | Mac:TEST |
| 17 | Service will not start | YES | YES | YES | NO | YES | NO | YES | YES | DETECT_ONLY | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 18 | Port conflict | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_fault_injection_lab.py::test_07_port_conflict_fault_lifecycle | Win:TEST | Lnx:TEST | Mac:TEST |
| 19 | Dependency has wrong version | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dependency_graph.py (38 tests) | Win:TEST | Lnx:TEST | Mac:TEST |
| 20 | Dependency installed but undiscoverable | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 21 | JAVA_HOME points to wrong JDK | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:NOT_ | Mac:NOT_ |
| 22 | JAVA_HOME points to JRE | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:NOT_ | Mac:NOT_ |
| 23 | Architecture mismatch | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_authoritative_safety_hardening.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 24 | Installer architecture mismatch | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_update_classifier.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 25 | Package manager outdated | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_stage7_coverage.py::TestSC4PackageManagerSelfUpdate | Win:TEST | Lnx:TEST | Mac:TEST |
| 26 | Repository unavailable | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_update_classifier.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 27 | Network failure | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_update_classifier.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 28 | Checksum/signature failure | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_tier3_safety_boundary.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 29 | Corrupted installer | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_fault_injection_lab.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 30 | Insufficient disk space | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_fault_injection_lab.py::test_10_simulated_disk_space_blocked | Win:TEST | Lnx:TEST | Mac:TEST |
| 31 | Permissions | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_stage7_coverage.py::TestSC2PermissionRepairRecipes | Win:LIVE | Lnx:TEST | Mac:TEST |
| 32 | UAC / privilege problem | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_elevation_architecture.py (16 tests) | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |
| 33 | Installer requires GUI | YES | YES | YES | NO | YES | YES | NO | NO | REVIEW_ONLY | AUTOMATED: test_machine_state_policy.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 34 | Silent flags differ | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 35 | Uninstall leaves data | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_stage7_coverage.py::TestSC5ResidualCleanupRecipes | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 36 | Reinstall can destroy user environments | YES | YES | YES | NO | YES | NO | YES | YES | REVIEW_ONLY | AUTOMATED: test_authoritative_backend.py::test_reinstall_strategy_distinct_from_native_repair | Win:TEST | Lnx:TEST | Mac:TEST |
| 37 | Update changes installation path | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 38 | Update changes executable names | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 39 | Package ID changes | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 40 | Multiple channels | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_stage7_coverage.py::TestSC7ChannelFieldOnCanonicalIdentity | Win:TEST | Lnx:TEST | Mac:TEST |
| 41 | Accidental downgrade | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_repair_engine.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 42 | Latest version is not always appropriate | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 43 | Breaking changes | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_verification_environment_hardening.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 44 | Dependency compatibility | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dependency_graph.py::TestTopologicalSort | Win:TEST | Lnx:TEST | Mac:TEST |
| 45 | Lock files / package environments | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 46 | Virtual environments hide tools | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 47 | Node version managers | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 48 | Java version managers | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 49 | Docker Desktop vs Docker Engine | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_stage7_coverage.py::TestSC1ServiceRepairRecipes | Win:LIVE | Lnx:TEST | Mac:TEST |
| 50 | WSL dependency problems | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_stage7_coverage.py::TestSC3WindowsFeatureRecipes | Win:TEST | Lnx:NOT_ | Mac:NOT_ |
| 51 | Windows feature disabled | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_stage7_coverage.py::TestSC3WindowsFeatureRecipes | Win:TEST | Lnx:NOT_ | Mac:NOT_ |
| 52 | Linux package-manager differences | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_platform_abstraction_contracts.py | Win:NOT_ | Lnx:TEST | Mac:NOT_ |
| 53 | Linux distro differences | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_platform_abstraction_contracts.py | Win:NOT_ | Lnx:TEST | Mac:NOT_ |
| 54 | Repository package outdated | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_problem_coverage_matrix.py | Win:NOT_ | Lnx:TEST | Mac:NOT_ |
| 55 | macOS Homebrew vs official installer | NO | YES | NO | NO | YES | NO | NO | NO | PARTIALLY_IMPLEMENTED | AUTOMATED: test_platform_abstraction_contracts.py | Win:NOT_ | Lnx:NOT_ | Mac:TEST |
| 56 | Multiple installation sources | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 57 | Stale package-manager information | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_dev_environment_detection.py | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 58 | Another program changes the environment | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_safety_hardening.py::test_13_frozen_plan_cannot_bypass_changed_safety_state | Win:LIVE | Lnx:TEST | Mac:TEST |
| 59 | Verification command is wrong | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_verification_environment_hardening.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 60 | Successful command does not mean usable application | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_execution_verification_sync.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 61 | Verification succeeds but application remains unusable | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_verification_environment_hardening.py::test_generic_functional_probe_from_canonical_identity | Win:LIVE | Lnx:TEST | Mac:TEST |
| 62 | Repair succeeds but original problem remains | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_verification_environment_hardening.py::test_l5_real_detector_rescan_still_present | Win:LIVE | Lnx:TEST | Mac:TEST |
| 63 | Repair can make the problem worse | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_tier3_safety_boundary.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 64 | Risk level is context-dependent | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_machine_state_policy.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 65 | RAG extracts outdated command | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_execution_pipeline_consolidation.py::test_04_ai_rag_cannot_directly_spawn_mutation_processes | Win:TEST | Lnx:TEST | Mac:TEST |
| 66 | AI misunderstands documentation | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_path_repair_architecture.py::test_8_natural_language_string_rejected_by_backend | Win:TEST | Lnx:TEST | Mac:TEST |
| 67 | AI extracts wrong-OS command | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_repair_engine.py::TestSafetyLayer::test_os_mismatch | Win:TEST | Lnx:TEST | Mac:TEST |
| 68 | AI extracts dangerous commands | YES | YES | YES | NO | YES | NO | YES | NO | BLOCKED_BY_POLICY | AUTOMATED: test_tier3_safety_boundary.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 69 | Documentation contains multiple versions | YES | YES | YES | NO | YES | NO | YES | NO | REVIEW_ONLY | AUTOMATED: test_problem_coverage_matrix.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 70 | Official website is not necessarily the update source | YES | YES | YES | NO | YES | NO | YES | NO | DETECT_ONLY | AUTOMATED: test_authoritative_backend.py | Win:TEST | Lnx:TEST | Mac:TEST |
| 71 | Official URL redirects | NO | NO | NO | NO | NO | NO | NO | NO | NOT_IMPLEMENTED | NOT_TESTED: None | Win:NOT_ | Lnx:NOT_ | Mac:NOT_ |
| 72 | Application renamed | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_authoritative_backend.py | Win:LIVE | Lnx:TEST | Mac:TEST |
| 73 | Uninstall/reinstall changes permissions | YES | YES | YES | YES | YES | YES | YES | YES | DETECT_AND_REPAIR | AUTOMATED: test_stage7_coverage.py::TestSC2PermissionRepairRecipes | Win:TEST | Lnx:ADAP | Mac:ADAP |
| 74 | PC Doctor admin vs normal environment visibility | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_path_repair_architecture.py | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |
| 75 | User-specific vs machine-wide installation | YES | YES | YES | YES | YES | YES | YES | YES | FULLY_SOLVABLE | LIVE: test_path_repair_architecture.py::test_6_anaconda_user_path_repair_no_unnecessary_uac | Win:LIVE | Lnx:NOT_ | Mac:NOT_ |

---

## 3. Metric Calculations

- **Actionable Repair Boundary**: `(FULLY_SOLVABLE + DETECT_AND_REPAIR) / 75 = (21 + 21) / 75 = 42 / 75 = 56.00%`
- **Detection Coverage**: `Problems with reliable detection / 75 = 68 / 75 = 90.67%`
- **Review/Blocked Safety Coverage**: `(REVIEW_ONLY + BLOCKED_BY_POLICY) / 75 = (9 + 6) / 75 = 15 / 75 = 20.00%`
- **Detect-Only Diagnostic Coverage**: `DETECT_ONLY / 75 = 11 / 75 = 14.67%`
- **Unimplemented / Partial Coverage**: `(PARTIALLY_IMPLEMENTED + NOT_IMPLEMENTED) / 75 = (6 + 1) / 75 = 7 / 75 = 9.33%`

---

## 4. Platform Validation Breakdown

- **Windows Validated Capabilities**: 42 actionable repairs (21 LIVE_VALIDATED + 21 TEST_VALIDATED) + 22 safety/review/detect capabilities = 64 total validated capabilities
- **Linux Validated Capabilities**: 46 TEST_VALIDATED capabilities (including universal safety gate, canonical identity, package manager contracts, POSIX permissions, dependency graph) + 26 ADAPTER_ONLY / NOT_APPLICABLE
- **macOS Validated Capabilities**: 46 TEST_VALIDATED capabilities (including universal safety gate, canonical identity, Homebrew adapter contracts, POSIX permissions, dependency graph) + 26 ADAPTER_ONLY / NOT_APPLICABLE
