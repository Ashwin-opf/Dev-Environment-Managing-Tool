# PC Doctor — 75-Problem Evidence Registry (Stage 6 Re-Audit)

**Audit Date**: 2026-09-18  
**Authoritative Baseline**: Stage 5.1 Complete — 359/359 Tests Passing  
**Host Environment**: Windows 11 AMD64 / Python 3.13.5  
**Core Invariant**: Every file, class, function, test name, and database entry cited below physically exists in the repository. Zero inferred or fabricated citations.

---

### Problem 1: Package manager says installed but tool is unusable / PATH problem
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_path.py`
- **Function/class**: `DevEnvironmentDetector.diagnose_tool`, `EffectivePath.repair_path_entry`
- **Test**: `tests/test_git_mvp_runtime_call_chain.py::test_git_mvp_production_route_end_to_end`, `tests/test_path_repair_architecture.py::TestTenMandatoryScenarios::test_1_git_machine_path_repair_with_uac`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Real Git production-route execution call chain verified in Stage 2; `GIT_MACHINE_PATH_MISSING` fault in `backend/test_lab/catalog.py`
- **Relevant database/recipe**: `knowledge_static.db` (Git.Git PATH & install recipes)
- **Current limitation**: Automated repair verified end-to-end on Windows; POSIX shell profile exports require corresponding shell restart

---

### Problem 2: Multiple versions installed
- **Source file**: `backend/dev_environment_detector.py`, `backend/canonical_identity.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`, `ToolDiagnosis.repairability`
- **Test**: `tests/test_elevation_architecture.py::TestRepairEngineElevationFlow::test_multiple_python_versions_review_only`, `tests/test_path_repair_architecture.py::TestTenMandatoryScenarios::test_7_multiple_python_versions_review_only_no_execution`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: `PYTHON_MULTIPLE_VERSIONS_REVIEW` in `backend/test_lab/catalog.py`
- **Relevant database/recipe**: Review-only policy; no automatic destructive uninstall recipe
- **Current limitation**: Intentionally requires human review (`automatic_repair=False`); automatic prioritization heuristic across multiple major runtimes is intentionally not supported to prevent breaking user projects

---

### Problem 3: Update exists but package manager cannot perform it
- **Source file**: `backend/update_classifier.py`, `backend/result_classifier.py`
- **Function/class**: `UpdateClassifier.classify_update_output`, `ResultClassifier.classify_result`
- **Test**: `tests/test_update_classifier.py::TestUpdateClassifier::test_publisher_managed_winget_output`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: WinGet output parser captured and classified in test suite
- **Relevant database/recipe**: `knowledge_static.db` (publisher fallback URL links)
- **Current limitation**: Recognizes and classifies publisher-managed status; automated downloading and silent headless invocation of arbitrary third-party proprietary installers is not fully automated

---

### Problem 4: Package manager says no update but official source has newer version
- **Source file**: `backend/canonical_identity.py`, `backend/pkg_discovery.py`
- **Function/class**: `CanonicalIdentity.official_url`, `PackageDiscoveryEngine`
- **Test**: `tests/test_problem_coverage_matrix.py::TestProblemCoverageMatrix::test_all_problems_have_complete_handling_path`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None on real host
- **Relevant database/recipe**: `knowledge_static.db`
- **Current limitation**: Canonical identity models store official URLs and version extraction commands, but background periodic scraping workers polling external GitHub/publisher release feeds are not active

---

### Problem 5: Manual installation not recognized
- **Source file**: `backend/dev_environment_detector.py`, `backend/tool_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`, `ToolDetector.detect_tool`
- **Test**: `tests/test_tool_detector.py::TestToolDetector::test_detect_tool_from_path`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Filesystem directory walking across Program Files and AppData
- **Relevant database/recipe**: `knowledge_static.db` (PATH registration recipes)
- **Current limitation**: Discovers existing binaries across standard installation folders, but does not reverse-engineer custom non-standard directories outside standard roots

---

### Problem 6: Package-manager ID differs from display name
- **Source file**: `backend/canonical_identity.py`
- **Function/class**: `CanonicalIdentity`, `CanonicalIdentityStore.resolve`
- **Test**: `tests/test_authoritative_backend.py::TestCanonicalIdentity::test_canonical_identity_decouples_names_and_ids`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Production route queries "Git" and executes "Git.Git"
- **Relevant database/recipe**: `canonical_identity.py` default catalog (18 tools)
- **Current limitation**: None for registered tools; uncataloged applications require dynamic identity discovery

---

### Problem 7: Executable name differs from application name
- **Source file**: `backend/canonical_identity.py`, `backend/recipe_engine.py`
- **Function/class**: `CanonicalIdentity.executable`, `StructuredRecipe.to_command_string`
- **Test**: `tests/test_authoritative_backend.py::TestCanonicalIdentity::test_executable_separated_from_arguments`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Production pipeline runs `code` for VS Code, `psql` for PostgreSQL, `git` for Git
- **Relevant database/recipe**: `canonical_identity.py`, `knowledge_static.db`
- **Current limitation**: None; executable and arguments are strictly separated across all models

---

### Problem 8: Inconsistent version output
- **Source file**: `backend/verification_engine.py`
- **Function/class**: `VerificationEngine._extract_version_string`
- **Test**: `tests/test_verification_environment_hardening.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Unit regex parser verification
- **Relevant database/recipe**: Regex fallback rules in `verification_engine.py`
- **Current limitation**: Probes `--version`, `-v`, `-V`, `version`; non-standard custom banners without semantic version numbers fall back to raw output capture

---

### Problem 9: --version does not work
- **Source file**: `backend/canonical_identity.py`, `backend/verification_engine.py`
- **Function/class**: `CanonicalIdentity.version_command`, `VerificationEngine._run_probe`
- **Test**: `tests/test_verification_environment_hardening.py::test_generic_functional_probe_from_canonical_identity`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Verified with Java (`java -version`) and Go (`go version`)
- **Relevant database/recipe**: Canonical identity custom `version_command` lists
- **Current limitation**: Custom command must be predefined in tool catalog or recipe

---

### Problem 10: GUI application has no CLI in PATH
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Discovers VS Code and Chrome CLI entries in `AppData` and `Program Files`
- **Relevant database/recipe**: `knowledge_static.db`
- **Current limitation**: Proposes adding application directory to PATH; automatic creation of executable CLI wrapper shims is not currently implemented

---

### Problem 11: User PATH vs System PATH
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_path.py`
- **Function/class**: `EffectivePath.get_user_path`, `EffectivePath.get_machine_path`, `WindowsPathManager.add_path_entry`
- **Test**: `tests/test_path_repair_architecture.py::TestTenMandatoryScenarios::test_1_git_machine_path_repair_with_uac`, `test_6_anaconda_user_path_repair_no_unnecessary_uac`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Live Windows registry reads from `HKCU\Environment` and `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`
- **Relevant database/recipe**: `windows_path.py`
- **Current limitation**: Windows implementation is authoritative and tested; Linux/macOS multi-file profile hierarchy (`.bashrc`, `.profile`, `/etc/environment`) uses basic adapter stubs

---

### Problem 12: Stale PATH
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_path.py`
- **Function/class**: `EffectivePath.remove_from_persistent_path`, `WindowsPathManager.remove_path_entry`
- **Test**: `tests/test_path_repair_architecture.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: In-memory and test registry validation
- **Relevant database/recipe**: `windows_path.py`
- **Current limitation**: Network shares that are temporarily offline could trigger false stale classifications if timeouts are short

---

### Problem 13: PATH order selects wrong version
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_path.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`, `WindowsPathManager.parse_path_entries`
- **Test**: `tests/test_verification_environment_hardening.py::test_executable_shadowing_detection`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Shadowing probe verifies which directory takes precedence
- **Relevant database/recipe**: `windows_path.py`
- **Current limitation**: Reordering system PATH entries requires administrative elevation and user confirmation

---

### Problem 14: Terminal restart needed
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_environment.py`
- **Function/class**: `EffectivePath.sync_process_path`, `EffectivePath.broadcast_environment_change`
- **Test**: `tests/test_verification_environment_hardening.py::test_refresh_effective_environment_reads_registry`, `test_windows_path_concatenation_machine_first`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Live environment sync and Windows `SendMessageTimeout` broadcast
- **Relevant database/recipe**: Platform abstraction layer
- **Current limitation**: Broadcast notifies top-level shells and Windows Explorer; already-running command prompts or PowerShell consoles require manual reload or new terminal tab

---

### Problem 15: Reboot required
- **Source file**: `backend/machine_state.py`, `backend/authoritative_safety.py`
- **Function/class**: `MachineStateEvaluator.is_reboot_pending`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_machine_state_policy.py` (26 tests including `test_pending_reboot_blocks_tier1_auto`)
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Stage 4 live pending reboot proof on Windows host
- **Relevant database/recipe**: `machine_state.py`
- **Current limitation**: Non-Windows reboot indicators (`/var/run/reboot-required`) implemented in Linux adapter stubs but untested on live host

---

### Problem 16: Service not running
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_service.py`
- **Function/class**: `DevEnvironmentDetector.check_service`, `WindowsServiceManager.status`, `WindowsServiceManager.start`
- **Test**: `tests/test_dev_environment_detection.py::TestActiveProblemsAndRepairIntegration::test_get_active_repair_problems_clears_resolved_service`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: `DEVELOPER_SERVICE_STOPPED` (MySQL80) fault injection in `backend/test_lab/catalog.py`
- **Relevant database/recipe**: `windows_service.py`
- **Current limitation**: Windows Service Control Manager queries supported; systemd unit management on Linux is mock-tested only

---

### Problem 17: Service will not start
- **Source file**: `backend/dev_environment_detector.py`, `backend/test_lab/catalog.py`
- **Function/class**: `DevEnvironmentDetector.diagnose_tool`, `ToolHealthStatus.SERVICE_PRESENT_BUT_FAILED_TO_START`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: SCM exit code capture
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Recognizes service start failure; automated parsing of Windows Event Viewer logs for deep root-cause diagnosis is not implemented

---

### Problem 18: Port conflict
- **Source file**: `backend/dev_environment_detector.py`, `backend/test_lab/catalog.py`
- **Function/class**: `DevEnvironmentDetector.check_port`
- **Test**: `tests/test_fault_injection_lab.py::TestFaultInjectionLab::test_07_port_conflict_fault_lifecycle`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: `CONTROLLED_PORT_CONFLICT` (port 18765) ephemeral socket binding in Test Lab
- **Relevant database/recipe**: `canonical_identity.py` port mappings (MySQL 3306, PostgreSQL 5432, Jenkins 8080)
- **Current limitation**: Detects conflict reliably via socket probe; terminating the conflicting process requires user review and elevated kill command

---

### Problem 19: Dependency has wrong version
- **Source file**: `backend/pkg_resolution.py`
- **Function/class**: `DependencyResolver`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: `pkg_resolution.py`
- **Current limitation**: Basic dependency graph representation exists; full SAT solver for cross-tool version resolution is incomplete

---

### Problem 20: Dependency installed but undiscoverable
- **Source file**: `backend/dev_environment_detector.py`, `backend/canonical_identity.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`, `CanonicalIdentity.env_var`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Tests verify environment variable configuration (`JAVA_HOME`, `GOROOT`, `CARGO_HOME`)
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Configures persistent environment variable; symlink generation on Windows requires Developer Mode or elevation

---

### Problem 21: JAVA_HOME points to wrong JDK
- **Source file**: `backend/dev_environment_detector.py`, `backend/canonical_identity.py`
- **Function/class**: `DevEnvironmentDetector.diagnose_tool`, `EffectivePath`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Compares JDK folder vs `java -version` path
- **Relevant database/recipe**: `canonical_identity.py` (Java identity definition)
- **Current limitation**: Sets `JAVA_HOME` registry key; terminal session synchronization requires terminal restart

---

### Problem 22: JAVA_HOME points to JRE
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.diagnose_tool`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Probes `javac.exe` inside `JAVA_HOME\bin`
- **Relevant database/recipe**: `knowledge_static.db` (JDK install recipes)
- **Current limitation**: Detects JRE; automatic JDK upgrade requires package manager execution

---

### Problem 23: Architecture mismatch
- **Source file**: `backend/authoritative_safety.py`, `backend/recipe_engine.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.ARCHITECTURE_MISMATCH`
- **Test**: `tests/test_authoritative_safety_hardening.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Evaluates system architecture against recipe metadata
- **Relevant database/recipe**: `recipe_engine.py`
- **Current limitation**: Strictly blocked by safety policy; automated binary emulation advice is not generated

---

### Problem 24: Installer architecture mismatch
- **Source file**: `backend/result_classifier.py`
- **Function/class**: `ResultClassifier.classify_result`
- **Test**: `tests/test_update_classifier.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Error classifier matches architecture mismatch error patterns
- **Relevant database/recipe**: `result_classifier.py`
- **Current limitation**: Classifies failure cleanly; does not automatically re-query repository for alternate architecture variant

---

### Problem 25: Package manager outdated
- **Source file**: `backend/pkg_discovery.py`, `backend/adapters/winget.py`
- **Function/class**: `PackageDiscoveryEngine`, `WinGetAdapter.version`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: `knowledge_static.db`
- **Current limitation**: Probes PM version; self-bootstrap upgrade recipes for winget/choco require elevated installer execution

---

### Problem 26: Repository unavailable
- **Source file**: `backend/result_classifier.py`, `backend/authoritative_safety.py`
- **Function/class**: `ResultClassifier.classify_result`
- **Test**: `tests/test_update_classifier.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Captures HTTP 404/503 and network timeout outputs
- **Relevant database/recipe**: `result_classifier.py`
- **Current limitation**: Classifies repository as unavailable; automated mirror failover is not implemented

---

### Problem 27: Network failure
- **Source file**: `backend/result_classifier.py`, `backend/authoritative_safety.py`
- **Function/class**: `ResultClassifier.classify_result`, `BlockedReason.NETWORK_ERROR`
- **Test**: `tests/test_update_classifier.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Regex pattern matching for network drops
- **Relevant database/recipe**: `result_classifier.py`
- **Current limitation**: Marks error as recoverable network issue; does not manage network adapter state

---

### Problem 28: Checksum/signature failure
- **Source file**: `backend/authoritative_safety.py`, `backend/execution_engine.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.INTEGRITY_COMPROMISED`
- **Test**: `tests/test_tier3_safety_boundary.py`, `tests/test_authoritative_safety_hardening.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Checksum verification failure triggers hard block
- **Relevant database/recipe**: Safety rules
- **Current limitation**: Deliberately blocked by policy; unverified binaries are never executed

---

### Problem 29: Corrupted installer
- **Source file**: `backend/result_classifier.py`, `backend/recipe_engine.py`
- **Function/class**: `ResultClassifier.classify_result`, `RecipeOperation.REINSTALL`
- **Test**: `tests/test_fault_injection_lab.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Error classifier matches exit code 1603 / CRC errors
- **Relevant database/recipe**: `knowledge_static.db` (cache purge recipes)
- **Current limitation**: Purges cache and retries; deeply damaged MSI installer databases require Windows Installer service repair

---

### Problem 30: Insufficient disk space
- **Source file**: `backend/authoritative_safety.py`, `backend/test_lab/catalog.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.DISK_FULL`
- **Test**: `tests/test_fault_injection_lab.py::TestFaultInjectionLab::test_10_simulated_disk_space_blocked`, `tests/test_authoritative_safety_hardening.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: `LOW_DISK_SPACE_SIMULATED` fault in Test Lab; live safety gate blocks mutation when free space < 2.0 GB
- **Relevant database/recipe**: Safety rules
- **Current limitation**: Deliberately blocked by policy; automatic deletion of user files to free disk space is prohibited

---

### Problem 31: Permissions
- **Source file**: `backend/privilege_manager.py`, `backend/dev_environment_detector.py`
- **Function/class**: `PrivilegeManager.is_elevated`, `DevEnvironmentDetector.diagnose_tool`
- **Test**: `tests/test_elevation_architecture.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Detects permission denied on system directories
- **Relevant database/recipe**: `privilege_manager.py`
- **Current limitation**: Identifies permission errors and routes to elevated worker or user scope

---

### Problem 32: UAC / privilege problem
- **Source file**: `backend/privilege_manager.py`, `backend/authoritative_safety.py`
- **Function/class**: `PrivilegeManager.execute_elevated_command`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_elevation_architecture.py` (16 tests), `tests/test_tier3_safety_boundary.py`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Live UAC elevation execution verified on Windows in Stage 5 & 5.1
- **Relevant database/recipe**: `privilege_manager.py`
- **Current limitation**: UAC elevation prompts interactive Windows dialog; non-interactive headless elevation requires pre-elevated service

---

### Problem 33: Installer requires GUI
- **Source file**: `backend/dev_environment_detector.py`, `backend/execution_tier.py`
- **Function/class**: `ExecutionTierRouter`, `DevEnvironmentDetector.diagnose_tool`
- **Test**: `tests/test_machine_state_policy.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Routes to Controlled Tier with modal notice
- **Relevant database/recipe**: Canonical identity metadata
- **Current limitation**: Awaits user interaction in GUI; cannot automate arbitrary third-party GUI wizards

---

### Problem 34: Silent flags differ
- **Source file**: `backend/adapters/winget.py`, `backend/adapters/choco.py`, `backend/adapters/apt.py`
- **Function/class**: `WinGetAdapter.install`, `ChocoAdapter.install`, `AptAdapter.install`
- **Test**: `tests/test_authoritative_backend.py::TestAdapters`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Live winget silent executions in Stage 2 & 5
- **Relevant database/recipe**: Adapter implementations
- **Current limitation**: Proprietary custom MSIs with unknown silent flags require manual review

---

### Problem 35: Uninstall leaves data
- **Source file**: `backend/recipe_engine.py`
- **Function/class**: `RecipeOperation.UNINSTALL`, `RepairStrategy.CONFIG_RESET`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Matrix definitions
- **Relevant database/recipe**: `recipe_engine.py`
- **Current limitation**: Residual purge directories are defined for some tools; universal residual filesystem scanning is incomplete

---

### Problem 36: Reinstall can destroy user environments
- **Source file**: `backend/recipe_engine.py`, `backend/authoritative_safety.py`
- **Function/class**: `RepairStrategy.REINSTALL`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_authoritative_backend.py::TestRecipeEngine::test_reinstall_strategy_distinct_from_native_repair`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Architectural invariant: REINSTALL is never mislabeled as native REPAIR
- **Relevant database/recipe**: `recipe_engine.py`
- **Current limitation**: Enforces human confirmation; pre-reinstall automatic configuration backup is not universally implemented

---

### Problem 37: Update changes installation path
- **Source file**: `backend/dev_environment_detector.py`, `backend/state_refresh.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`, `StateRefreshEngine.refresh_environment`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Discovers new versioned folder and triggers PATH update
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Discovers new location upon rescan; real-time filesystem watchers are not running continuously

---

### Problem 38: Update changes executable names
- **Source file**: `backend/canonical_identity.py`
- **Function/class**: `CanonicalIdentity.aliases`, `CanonicalIdentityStore.resolve`
- **Test**: `tests/test_authoritative_backend.py`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Alias resolution verified in test suite
- **Relevant database/recipe**: `canonical_identity.py` alias definitions
- **Current limitation**: Aliases must be registered in the canonical identity store

---

### Problem 39: Package ID changes
- **Source file**: `backend/canonical_identity.py`
- **Function/class**: `CanonicalIdentityStore._pkg_id_map`, `CanonicalIdentityStore.resolve`
- **Test**: `tests/test_authoritative_backend.py`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Package ID resolution verified in test suite
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Requires upstream alias mapping in identity store

---

### Problem 40: Multiple channels
- **Source file**: `backend/canonical_identity.py`, `backend/execution_tier.py`
- **Function/class**: `CanonicalIdentity.package_id`, `ExecutionTierRouter`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Defaults to stable channel; channel switching UI selector is not exposed in the frontend

---

### Problem 41: Accidental downgrade
- **Source file**: `backend/repair_engine.py`, `backend/authoritative_safety.py`
- **Function/class**: `RepairEngine`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_repair_engine.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Downgrade protection prevents unintended version regressions
- **Relevant database/recipe**: Safety rules
- **Current limitation**: Review-only; intentional rollback requires explicit override

---

### Problem 42: Latest version is not always appropriate
- **Source file**: `backend/canonical_identity.py`, `backend/recipe_engine.py`
- **Function/class**: `CanonicalIdentity`, `StructuredRecipe`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: Version pinning metadata
- **Current limitation**: Review-only; user must specify pinned version constraint

---

### Problem 43: Breaking changes
- **Source file**: `backend/verification_engine.py`, `backend/canonical_identity.py`
- **Function/class**: `VerificationEngine.verify_tool`, `CanonicalIdentity.functional_probe_command`
- **Test**: `tests/test_verification_environment_hardening.py::test_generic_functional_probe_from_canonical_identity`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: L3 functional probe runs `node -e` / `python -c`
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Detects breakage via functional probe; automated rollback without existing snapshot is unsupported

---

### Problem 44: Dependency compatibility
- **Source file**: `backend/pkg_resolution.py`
- **Function/class**: `DependencyResolver`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: `pkg_resolution.py`
- **Current limitation**: Partial model; multi-package co-upgrade solver is not fully operational

---

### Problem 45: Lock files / package environments
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Lockfile detection logic
- **Relevant database/recipe**: Review-only policy
- **Current limitation**: Flags presence of lockfile; does not modify project-level lockfiles

---

### Problem 46: Virtual environments hide tools
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Detects active `VIRTUAL_ENV` and `CONDA_PREFIX`
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Reports isolation; does not inject virtual environment binaries into global PATH

---

### Problem 47: Node version managers
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Detects `nvm` and `fnm` on PATH
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Detects version managers; does not execute `nvm use` shell shims

---

### Problem 48: Java version managers
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Detects `SDKMAN_DIR` and `jenv`
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Detects switcher; does not execute sdkman bash wrapper

---

### Problem 49: Docker Desktop vs Docker Engine
- **Source file**: `backend/canonical_identity.py`, `backend/dev_environment_detector.py`
- **Function/class**: `CanonicalIdentity(identity_id="docker")`, `DevEnvironmentDetector.check_service`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Probes `com.docker.service` and port 2375
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Starts background service; WSL 2 distribution enablement requires user interaction

---

### Problem 50: WSL dependency problems
- **Source file**: `backend/authoritative_safety.py`, `backend/dev_environment_detector.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Windows vs WSL boundary check
- **Relevant database/recipe**: Safety rules
- **Current limitation**: Recognizes boundary mismatch; does not automatically configure WSL distributions

---

### Problem 51: Windows feature disabled
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: DISM recipe definitions
- **Current limitation**: Review-only; enabling Windows optional features requires reboot

---

### Problem 52: Linux package-manager differences
- **Source file**: `backend/adapters/apt.py`, `backend/adapters/dnf.py`, `backend/adapters/pacman.py`
- **Function/class**: `AptAdapter`, `DnfAdapter`, `PacmanAdapter`
- **Test**: `tests/test_platform_abstraction_contracts.py::TestGenericDetectorWithMockPlatform`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None on real Linux host
- **Relevant database/recipe**: `backend/adapters/`
- **Current limitation**: Adapter classes exist and pass mock tests; no live Linux host test evidence

---

### Problem 53: Linux distro differences
- **Source file**: `backend/platform_abstraction/linux/linux_environment.py`
- **Function/class**: `LinuxEnvironmentProvider`
- **Test**: `tests/test_platform_abstraction_contracts.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None on real Linux host
- **Relevant database/recipe**: `platform_abstraction/linux/`
- **Current limitation**: Distro parsing logic exists; untested on actual Linux distributions

---

### Problem 54: Repository package outdated
- **Source file**: `backend/adapters/apt.py`
- **Function/class**: `AptAdapter`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: PPA recipe suggestions
- **Current limitation**: Untested on live host; adding third-party PPAs requires elevated review

---

### Problem 55: macOS Homebrew vs official installer
- **Source file**: `backend/platform_abstraction/macos/macos_adapter.py`, `backend/adapters/brew.py`
- **Function/class**: `MacOSAdapter`, `BrewAdapter`
- **Test**: `tests/test_platform_abstraction_contracts.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None on real macOS host
- **Relevant database/recipe**: `platform_abstraction/macos/`
- **Current limitation**: Adapter classes exist; untested on live macOS host

---

### Problem 56: Multiple installation sources
- **Source file**: `backend/canonical_identity.py`, `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.discover_executable`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Identifies tool present in multiple independent locations
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Flags conflict for review; automatic uninstallation of duplicates is prohibited to avoid data loss

---

### Problem 57: Stale package-manager information
- **Source file**: `backend/dev_environment_detector.py`, `backend/adapters/winget.py`
- **Function/class**: `ToolHealthStatus.PACKAGE_MANAGER_STATE_MISMATCH`, `WinGetAdapter`
- **Test**: `tests/test_dev_environment_detection.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Probes package manager vs real disk executable
- **Relevant database/recipe**: `knowledge_static.db`
- **Current limitation**: Triggers source update command (`winget source update`); full registry purge requires elevated repair

---

### Problem 58: Another program changes the environment
- **Source file**: `backend/authoritative_safety.py`, `backend/state_refresh.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `StateRefreshEngine`
- **Test**: `tests/test_authoritative_safety_hardening.py::test_13_frozen_plan_cannot_bypass_changed_safety_state`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Stage 5 & 5.1 tests prove frozen plan cannot bypass live safety gate when environment degrades
- **Relevant database/recipe**: Authoritative safety gate
- **Current limitation**: None; pre-execution gate dynamically re-evaluates environment immediately prior to subprocess spawn

---

### Problem 59: Verification command is wrong
- **Source file**: `backend/verification_engine.py`
- **Function/class**: `VerificationEngine.verify_tool`, `VerificationEngine._run_probe`
- **Test**: `tests/test_verification_environment_hardening.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Bounded retry and fallback probing in test suite
- **Relevant database/recipe**: `verification_engine.py`
- **Current limitation**: Falls back to canonical version probe; dynamic generation of complex argument flags is rule-based

---

### Problem 60: Successful command does not mean usable application
- **Source file**: `backend/verification_engine.py`, `backend/execution_engine.py`
- **Function/class**: `VerificationEngine.verify_tool`, `CentralizedExecutionEngine.execute_action`
- **Test**: `tests/test_execution_verification_sync.py`, `tests/test_verification_environment_hardening.py`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Stage 3 live Git verification verified: exit code 0 is never treated as success without multi-level verification
- **Relevant database/recipe**: Verification levels L1–L4
- **Current limitation**: None; architectural invariant EXECUTED != VERIFIED strictly enforced

---

### Problem 61: Verification succeeds but application remains unusable
- **Source file**: `backend/verification_engine.py`, `backend/canonical_identity.py`
- **Function/class**: `VerificationEngine.verify_tool`, `CanonicalIdentity.functional_probe_command`
- **Test**: `tests/test_verification_environment_hardening.py::test_generic_functional_probe_from_canonical_identity`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Level 3 functional probe executes tool commands (`node -e`, `python -c`, `git help`)
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Probes verify runtime invocation; complex multi-module integration workloads require full test lab runner

---

### Problem 62: Repair succeeds but original problem remains
- **Source file**: `backend/verification_engine.py`, `backend/dev_environment_detector.py`
- **Function/class**: `VerificationEngine._rescan_original_problem`
- **Test**: `tests/test_verification_environment_hardening.py::test_l5_real_detector_rescan_still_present`, `test_l5_real_detector_rescan_cleared`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: L5 rescan re-invokes `DevEnvironmentDetector.diagnose_tool` post-repair
- **Relevant database/recipe**: Verification Engine L5 pipeline
- **Current limitation**: Rescans original diagnostic condition; if condition persists, status transitions to `VERIFICATION_FAILED`

---

### Problem 63: Repair can make the problem worse
- **Source file**: `backend/authoritative_safety.py`, `backend/snapshot.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `SnapshotEngine`
- **Test**: `tests/test_tier3_safety_boundary.py`, `tests/test_authoritative_safety_hardening.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Enforces Tier 3 Full Protected Path for destructive operations
- **Relevant database/recipe**: Safety policies
- **Current limitation**: Review-only; destructive operations cannot execute automatically; snapshots require VSS/filesystem support

---

### Problem 64: Risk level is context-dependent
- **Source file**: `backend/risk_engine.py`, `backend/authoritative_safety.py`
- **Function/class**: `DynamicRiskEngine.calculate_risk`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_machine_state_policy.py`, `tests/test_authoritative_safety_hardening.py`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Low disk space or pending reboot elevates Tier 1 operations to Tier 2 Controlled or blocks them
- **Relevant database/recipe**: Risk policy rules
- **Current limitation**: None; hard safety policy strictly overrides composite numerical risk scores

---

### Problem 65: RAG extracts outdated command
- **Source file**: `backend/shce_engine.py`, `backend/authoritative_safety.py`
- **Function/class**: `SHCEEngine`, `AuthoritativeSafety.live_pre_execution_gate`
- **Test**: `tests/test_execution_pipeline_consolidation.py::TestExecutionPipelineConsolidation::test_04_ai_rag_cannot_directly_spawn_mutation_processes`, `tests/test_shce.py`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: RAG output placed into Dynamic DB as untrusted CANDIDATE; cannot write to Static DB
- **Relevant database/recipe**: `knowledge_dynamic.db`
- **Current limitation**: Candidate requires user approval and dry-run syntax validation before execution

---

### Problem 66: AI misunderstands documentation
- **Source file**: `backend/authoritative_safety.py`, `backend/execution_engine.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.UNAPPROVED_COMMAND_PATTERN`
- **Test**: `tests/test_path_repair_architecture.py::TestTenMandatoryScenarios::test_8_natural_language_string_rejected_by_backend`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Natural language strings and non-executable hallucinated commands rejected
- **Relevant database/recipe**: Authoritative safety gate
- **Current limitation**: None; safety gate rejects unapproved command patterns without spawning subprocesses

---

### Problem 67: RAG extracts wrong-OS command
- **Source file**: `backend/authoritative_safety.py`, `backend/repair_engine.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.OS_MISMATCH`
- **Test**: `tests/test_repair_engine.py::TestSafetyLayer::test_os_mismatch`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Linux commands (`apt`, `dpkg`) rejected on Windows host
- **Relevant database/recipe**: Safety rules
- **Current limitation**: Deliberately blocked by policy; cross-OS translation requires adapted recipe resolver

---

### Problem 68: AI extracts dangerous commands
- **Source file**: `backend/authoritative_safety.py`
- **Function/class**: `AuthoritativeSafety.live_pre_execution_gate`, `BlockedReason.DESTRUCTIVE_OPERATION`
- **Test**: `tests/test_tier3_safety_boundary.py`, `tests/test_authoritative_safety_hardening.py::test_01_destructive_command_blocked_at_safety_gate`
- **Test type**: INTEGRATION
- **Runtime/Test Lab evidence**: Destructive commands (`rm -rf`, `del /s /q C:\`, diskpart, format) blocked with zero subprocess spawns
- **Relevant database/recipe**: Hard blacklist in `authoritative_safety.py`
- **Current limitation**: Deliberately blocked by policy; AI can NEVER override or bypass the authoritative safety gate

---

### Problem 69: Documentation contains multiple versions
- **Source file**: `backend/recipe_engine.py`, `backend/canonical_identity.py`
- **Function/class**: `StructuredRecipe.recipe_version`, `CanonicalIdentity`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: `knowledge_static.db`
- **Current limitation**: Review-only; user must select desired version stream when multiple incompatible documentation versions exist

---

### Problem 70: Official website is not necessarily the update source
- **Source file**: `backend/canonical_identity.py`
- **Function/class**: `CanonicalIdentity.official_url`, `CanonicalIdentity.package_manager`
- **Test**: `tests/test_authoritative_backend.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Identity records separate official URLs from package manager manifests
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Detects divergence; automated cross-referencing of direct download feeds vs PM feeds is not implemented

---

### Problem 71: Official URL redirects
- **Source file**: None
- **Function/class**: None
- **Test**: None
- **Test type**: NO_TEST
- **Runtime/Test Lab evidence**: None
- **Relevant database/recipe**: None
- **Current limitation**: Not implemented; no active redirect-following or domain verification worker exists

---

### Problem 72: Application renamed
- **Source file**: `backend/canonical_identity.py`
- **Function/class**: `CanonicalIdentity.aliases`, `CanonicalIdentityStore.resolve`
- **Test**: `tests/test_authoritative_backend.py::TestCanonicalIdentity`
- **Test type**: REAL_RUNTIME / UNIT
- **Runtime/Test Lab evidence**: Resolves `code-oss` to `vscode`, `msys2-gcc` to `gcc`
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Aliases must be maintained in the canonical store

---

### Problem 73: Uninstall/reinstall changes permissions
- **Source file**: `backend/dev_environment_detector.py`
- **Function/class**: `DevEnvironmentDetector.diagnose_tool`
- **Test**: `tests/test_problem_coverage_matrix.py`
- **Test type**: UNIT
- **Runtime/Test Lab evidence**: Probes file access permissions
- **Relevant database/recipe**: `dev_environment_detector.py`
- **Current limitation**: Detects permission restriction; automated restoration of file ACLs requires elevated `icacls` execution

---

### Problem 74: PC Doctor admin vs normal environment visibility
- **Source file**: `backend/dev_environment_detector.py`, `backend/platform_abstraction/windows/windows_path.py`
- **Function/class**: `is_process_elevated`, `WindowsPathManager.get_path_entries`
- **Test**: `tests/test_path_repair_architecture.py`, `tests/test_verification_environment_hardening.py`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: Live Windows registry isolation verified in Stage 3 & 4
- **Relevant database/recipe**: Platform abstraction layer
- **Current limitation**: Windows dual-scope registry isolation is authoritative; POSIX daemon user-switching requires `su`/`sudo -u` handling

---

### Problem 75: User-specific vs machine-wide installation
- **Source file**: `backend/canonical_identity.py`, `backend/dev_environment_detector.py`
- **Function/class**: `CanonicalIdentity.install_scope`, `CanonicalIdentity.user_system_scope`, `DevEnvironmentDetector.diagnose_tool`
- **Test**: `tests/test_authoritative_backend.py`, `tests/test_path_repair_architecture.py::TestTenMandatoryScenarios::test_6_anaconda_user_path_repair_no_unnecessary_uac`
- **Test type**: REAL_RUNTIME / INTEGRATION
- **Runtime/Test Lab evidence**: VS Code User installer vs System installer, Anaconda User installer live tests
- **Relevant database/recipe**: `canonical_identity.py`
- **Current limitation**: Scope explicitly tracked; non-standard installers that ignore scope switches fall back to manual review
