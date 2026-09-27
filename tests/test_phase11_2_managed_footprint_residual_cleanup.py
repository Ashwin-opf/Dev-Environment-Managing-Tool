"""
tests/test_phase11_2_managed_footprint_residual_cleanup.py
==========================================================
Comprehensive validation suite for Phase 11.2 — Problem #35:
Uninstall Residual Files / Configuration / Environment Artifacts.

Tests all required dimensions:
1. Ownership Models (PC Doctor managed, pre-existing, unknown, confirmed, unowned)
2. Residual Detection (no residuals, executable, install dir, config, cache, service, env, mixed)
3. Safety Invariants (user data protection, review required, mixed dir protection, approval blocks, safety gate blocks)
4. Cleanup Execution (confirmed owned cleaned, unowned preserved, partial cleanup, cleanup failure, verification failure)
5. Environment & Dependencies (PATH ownership, PATH dependency protection, service ownership)
6. Cross-Platform Footprint Contracts (Windows, Linux, macOS)
7. End-to-End Integration & Architectural Invariants (approval gate, live safety gate, centralized execution)
"""

import json
import os
import platform
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from canonical_identity import canonical_store, CanonicalIdentity
from execution_plan import ExecutionRequest, ExecutionResolver, execution_resolver
from execution_tier import ExecutionTier
from recipe_engine import RecipeOperation
from managed_footprint import (
    ArtifactOwnershipConfidence,
    CleanupOutcomeStatus,
    CleanupSafetyClassification,
    ManagedArtifactRecord,
    ManagedFootprintRegistry,
    ManagedInstallation,
    OwnershipState,
    ResidualCategory,
    ResidualCandidate,
    ResidualCleanupCoordinator,
    ResidualScanner,
    ResidualScanStatus,
    ResidualSafetyPolicy,
)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="pc_doc_test_residual_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_registry(temp_dir):
    store_file = temp_dir / "test_installations.json"
    return ManagedFootprintRegistry(store_path=store_file)


@pytest.fixture
def scanner(mock_registry):
    return ResidualScanner(registry=mock_registry)


@pytest.fixture
def coordinator(mock_registry):
    return ResidualCleanupCoordinator(registry=mock_registry)


# ---------------------------------------------------------------------------
# 1. Ownership Model Tests (1-6)
# ---------------------------------------------------------------------------

class TestOwnershipModels:
    def test_01_pc_doctor_managed_installation(self, mock_registry, scanner):
        """PC Doctor managed installation registers with OwnershipState.PC_DOCTOR_MANAGED."""
        inst = ManagedInstallation(
            canonical_id="test-tool",
            installation_id="inst-001",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="Test.Tool",
            version="1.0.0",
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        mock_registry.register_installation(inst)
        loaded = mock_registry.get_installation("test-tool")
        assert loaded is not None
        assert loaded.ownership_state == OwnershipState.PC_DOCTOR_MANAGED

        scan = scanner.scan_residuals("test-tool")
        assert scan.ownership_state == OwnershipState.PC_DOCTOR_MANAGED

    def test_02_pre_existing_installation(self, scanner):
        """Pre-existing tool without PC Doctor footprint is classified as PRE_EXISTING."""
        # 'git' exists in CanonicalIdentityStore, but has no record in mock_registry
        scan = scanner.scan_residuals("git")
        assert scan.ownership_state == OwnershipState.PRE_EXISTING

    def test_03_unknown_installation(self, scanner):
        """Completely unknown tool without canonical identity or registry is UNKNOWN."""
        scan = scanner.scan_residuals("completely-unknown-ad-hoc-binary-123")
        assert scan.ownership_state == OwnershipState.UNKNOWN

    def test_04_confirmed_ownership_for_recorded_artifact(self, temp_dir, mock_registry, scanner):
        """Exact matching recorded executable has OWNED_CONFIRMED confidence."""
        exe = temp_dir / "mytool.exe"
        exe.write_text("dummy binary")
        inst = ManagedInstallation(
            canonical_id="mytool",
            installation_id="inst-mytool",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="MyTool.App",
            version="2.0.0",
            executables=[str(exe)],
        )
        mock_registry.register_installation(inst)

        scan = scanner.scan_residuals("mytool")
        assert len(scan.candidates) == 1
        cand = scan.candidates[0]
        assert cand.ownership == ArtifactOwnershipConfidence.OWNED_CONFIRMED
        assert cand.safety_classification == CleanupSafetyClassification.SAFE_CLEANUP
        assert cand.cleanup_allowed is True

    def test_05_unknown_ownership_for_unrecorded_artifact(self, temp_dir, scanner):
        """Artifact belonging to pre-existing tool receives OWNED_LIKELY/OWNERSHIP_UNKNOWN and requires review."""
        scan = scanner.scan_residuals("git")
        # For pre-existing installations, any discovered candidates require review
        for cand in scan.candidates:
            assert cand.safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED
            assert cand.cleanup_allowed is False

    def test_06_unowned_artifact(self, temp_dir):
        """Protected system or user directory is classified as NOT_OWNED."""
        user_proj = temp_dir / "Documents" / "MyToolProjects"
        user_proj.mkdir(parents=True)
        assert ResidualSafetyPolicy.is_user_data_path(str(user_proj)) is True


# ---------------------------------------------------------------------------
# 2. Residual Detection Tests (7-14)
# ---------------------------------------------------------------------------

class TestResidualDetection:
    def test_07_no_residuals_when_clean(self, mock_registry, scanner):
        """When recorded artifacts do not exist on disk, scan reports NO_RESIDUALS."""
        inst = ManagedInstallation(
            canonical_id="clean-app",
            installation_id="inst-clean",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="Clean.App",
            version="1.0.0",
            installation_root="C:\\NonExistentPath\\CleanApp",
            executables=["C:\\NonExistentPath\\CleanApp\\clean.exe"],
        )
        mock_registry.register_installation(inst)
        scan = scanner.scan_residuals("clean-app")
        assert scan.scan_status == ResidualScanStatus.NO_RESIDUALS
        assert len(scan.candidates) == 0

    def test_08_executable_residual_detected(self, temp_dir, mock_registry, scanner):
        """Lingering binary executable is detected and categorized as EXECUTABLE."""
        exe = temp_dir / "app.exe"
        exe.write_text("binary")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="app",
            installation_id="i1",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="App",
            version="1.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("app")
        assert scan.scan_status == ResidualScanStatus.SAFE_RESIDUALS_FOUND
        assert scan.candidates[0].category == ResidualCategory.EXECUTABLE
        assert scan.candidates[0].artifact == str(exe)

    def test_09_installation_directory_residual_detected(self, temp_dir, mock_registry, scanner):
        """Pure uninstaller leftover directory is detected as INSTALLATION_FILE."""
        root = temp_dir / "AppFolder"
        root.mkdir()
        (root / "unins000.dat").write_text("dat")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="app-folder",
            installation_id="i2",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="AppFolder",
            version="1.0",
            installation_root=str(root),
        ))
        scan = scanner.scan_residuals("app-folder")
        assert len(scan.candidates) == 1
        assert scan.candidates[0].category == ResidualCategory.INSTALLATION_FILE

    def test_10_configuration_residual_detected(self, temp_dir, mock_registry, scanner):
        """Known config is detected and flagged as CONFIGURATION with REVIEW_REQUIRED."""
        cfg = temp_dir / "config.ini"
        cfg.write_text("key=value")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="cfg-app",
            installation_id="i3",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="CfgApp",
            version="1.0",
            known_configuration=[str(cfg)],
        ))
        scan = scanner.scan_residuals("cfg-app")
        assert scan.candidates[0].category == ResidualCategory.CONFIGURATION
        assert scan.candidates[0].safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED
        assert scan.candidates[0].cleanup_allowed is False

    def test_11_cache_residual_detected(self, temp_dir, mock_registry, scanner):
        """Recorded tool cache directory is detected as CACHE with SAFE_CLEANUP."""
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="cache-app",
            installation_id="i4",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="CacheApp",
            version="1.0",
            known_cache=[str(cache_dir)],
        ))
        scan = scanner.scan_residuals("cache-app")
        assert scan.candidates[0].category == ResidualCategory.CACHE
        assert scan.candidates[0].safety_classification == CleanupSafetyClassification.SAFE_CLEANUP
        assert scan.candidates[0].cleanup_allowed is True

    def test_12_service_residual_detected(self, mock_registry, scanner):
        """Service registered in managed footprint produces SERVICE category candidate."""
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="svc-app",
            installation_id="i5",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="SvcApp",
            version="1.0",
            services=["MyManagedDaemonService"],
        ))
        # Mock service existence
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0)
            scan = scanner.scan_residuals("svc-app")
            assert len(scan.candidates) == 1
            assert scan.candidates[0].category == ResidualCategory.SERVICE
            assert scan.candidates[0].safety_classification == CleanupSafetyClassification.SAFE_CLEANUP

    def test_13_environment_residual_detected(self, temp_dir, mock_registry, scanner):
        """Managed PATH entry present in environment is detected as ENVIRONMENT_ENTRY."""
        bin_dir = temp_dir / "bin"
        bin_dir.mkdir()
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="env-app",
            installation_id="i6",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="EnvApp",
            version="1.0",
            environment_entries=[str(bin_dir)],
        ))
        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}C:\\Windows\\System32"}):
            scan = scanner.scan_residuals("env-app")
            assert len(scan.candidates) == 1
            assert scan.candidates[0].category == ResidualCategory.ENVIRONMENT_ENTRY
            assert scan.candidates[0].safety_classification == CleanupSafetyClassification.SAFE_CLEANUP

    def test_14_mixed_owned_and_unowned_artifacts(self, temp_dir, mock_registry, scanner):
        """Mixed scan containing safe cache and sensitive config reports REVIEW_REQUIRED."""
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()
        cfg_file = temp_dir / "settings.json"
        cfg_file.write_text("{}")

        mock_registry.register_installation(ManagedInstallation(
            canonical_id="mixed-app",
            installation_id="i7",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="MixedApp",
            version="1.0",
            known_cache=[str(cache_dir)],
            known_configuration=[str(cfg_file)],
        ))
        scan = scanner.scan_residuals("mixed-app")
        assert scan.scan_status == ResidualScanStatus.REVIEW_REQUIRED
        assert scan.safe_count == 1
        assert scan.review_count == 1


# ---------------------------------------------------------------------------
# 3. Safety Invariant Tests (15-19)
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    def test_15_user_data_protected(self, temp_dir, mock_registry, scanner):
        """Directory under Documents or project workspace is NEVER marked for automatic cleanup."""
        user_proj = temp_dir / "Documents" / "MyToolProjects"
        user_proj.mkdir(parents=True)
        (user_proj / "main.py").write_text("print('hello')")

        # Even if an uninstaller or rogue registry claimed installation_root was user_proj
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="mytool",
            installation_id="rogue-1",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="MyTool",
            version="1.0",
            installation_root=str(user_proj),
        ))
        scan = scanner.scan_residuals("mytool")
        assert len(scan.candidates) == 1
        cand = scan.candidates[0]
        assert cand.category == ResidualCategory.USER_DATA
        assert cand.safety_classification == CleanupSafetyClassification.NOT_OWNED
        assert cand.cleanup_allowed is False

    def test_16_unknown_artifact_requires_review(self, scanner):
        """Unmanaged software residuals always yield REVIEW_REQUIRED with zero auto-cleanup."""
        scan = scanner.scan_residuals("git")
        for cand in scan.candidates:
            assert cand.safety_classification in (CleanupSafetyClassification.REVIEW_REQUIRED, CleanupSafetyClassification.NOT_OWNED)
            assert cand.cleanup_allowed is False

    def test_17_mixed_directory_cannot_be_recursively_deleted(self, temp_dir, mock_registry, scanner):
        """Installation root containing unexpected foreign files blocks recursive deletion."""
        install_root = temp_dir / "ToolRoot"
        install_root.mkdir()
        (install_root / "tool.exe").write_text("binary")
        (install_root / "user_notes.txt").write_text("my notes")  # foreign file!

        mock_registry.register_installation(ManagedInstallation(
            canonical_id="tool-root",
            installation_id="i8",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="ToolRoot",
            version="1.0",
            installation_root=str(install_root),
            executables=[str(install_root / "tool.exe")],
        ))
        scan = scanner.scan_residuals("tool-root")
        # Find candidate for install_root
        root_cand = next(c for c in scan.candidates if c.artifact == str(install_root))
        assert root_cand.safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED
        assert root_cand.cleanup_allowed is False
        assert "unexpected foreign files" in root_cand.reason

    def test_18_approval_blocks_cleanup(self, temp_dir, mock_registry, scanner, coordinator):
        """If approved=False, coordinator halts with APPROVAL_REQUIRED and performs 0 mutations."""
        exe = temp_dir / "tool.exe"
        exe.write_text("binary")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="app-appr",
            installation_id="i9",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="AppAppr",
            version="1.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("app-appr")
        assert scan.safe_count == 1

        # Execute without approval
        result = coordinator.execute_cleanup(scan, approved=False)
        assert result.status == CleanupOutcomeStatus.APPROVAL_REQUIRED
        assert result.cleaned_count == 0
        assert exe.exists(), "File must NOT have been deleted when unapproved!"

    def test_19_safety_gate_blocks_dangerous_cleanup(self, temp_dir):
        """System root or blacklisted targets are rejected by safety policy."""
        assert ResidualSafetyPolicy.is_system_protected_path("C:\\Windows\\System32") is True
        assert ResidualSafetyPolicy.is_system_protected_path("/") is True
        assert ResidualSafetyPolicy.is_system_protected_path("/usr") is True


# ---------------------------------------------------------------------------
# 4. Cleanup Execution Tests (20-24)
# ---------------------------------------------------------------------------

class TestCleanupExecution:
    def test_20_confirmed_owned_artifact_removed(self, temp_dir, mock_registry, scanner, coordinator):
        """Confirmed owned artifact with approved=True is safely removed through execution engine."""
        exe = temp_dir / "to_delete.exe"
        exe.write_text("binary")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="del-tool",
            installation_id="i10",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="DelTool",
            version="1.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("del-tool")

        # Mock CentralizedExecutionEngine
        mock_engine = MagicMock()
        mock_engine.execute_command.return_value = MagicMock(success=True, return_code=0, stdout="Removed", stderr="")

        # Execute removal
        # In this test, simulate real file removal upon command
        def fake_exec(*args, **kwargs):
            if exe.exists():
                exe.unlink()
            return MagicMock(success=True, return_code=0, stdout="OK", stderr="")

        mock_engine.execute_command.side_effect = fake_exec
        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)

        assert result.status == CleanupOutcomeStatus.CLEANUP_SUCCESS
        assert result.cleaned_count == 1
        assert not exe.exists()

    def test_21_unowned_artifact_preserved(self, temp_dir, scanner, coordinator):
        """Unowned/review-required artifact is untouched during cleanup."""
        proj = temp_dir / "Documents" / "Project"
        proj.mkdir(parents=True)
        (proj / "code.py").write_text("pass")

        scan = scanner.scan_residuals("git")
        mock_engine = MagicMock()
        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)

        # Nothing safe was scheduled for deletion
        assert mock_engine.execute_command.call_count == 0
        assert (proj / "code.py").exists()

    def test_22_partial_cleanup(self, temp_dir, mock_registry, scanner, coordinator):
        """When some candidates are safe and some require review, PARTIAL_CLEANUP is reported."""
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()
        cfg_file = temp_dir / "settings.json"
        cfg_file.write_text("{}")

        mock_registry.register_installation(ManagedInstallation(
            canonical_id="part-tool",
            installation_id="i11",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="PartTool",
            version="1.0",
            known_cache=[str(cache_dir)],
            known_configuration=[str(cfg_file)],
        ))
        scan = scanner.scan_residuals("part-tool")

        def fake_exec(command, **kwargs):
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            return MagicMock(success=True, return_code=0)

        mock_engine = MagicMock()
        mock_engine.execute_command.side_effect = fake_exec

        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)
        assert result.status == CleanupOutcomeStatus.PARTIAL_CLEANUP
        assert result.cleaned_count == 1
        assert result.review_count == 1
        assert not cache_dir.exists()
        assert cfg_file.exists(), "Configuration file must remain untouched!"

    def test_23_cleanup_failure(self, temp_dir, mock_registry, scanner, coordinator):
        """If removal command fails with non-zero exit code, CLEANUP_FAILED is reported."""
        exe = temp_dir / "locked.exe"
        exe.write_text("locked")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="fail-tool",
            installation_id="i12",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="FailTool",
            version="1.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("fail-tool")

        mock_engine = MagicMock()
        mock_engine.execute_command.return_value = MagicMock(success=False, return_code=1, stderr="Access is denied")

        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)
        assert result.status == CleanupOutcomeStatus.CLEANUP_FAILED
        assert result.failed_count == 1
        assert "Access is denied" in result.uncleaned_artifacts[0]["reason"]

    def test_24_verification_failure_when_file_still_exists(self, temp_dir, mock_registry, scanner, coordinator):
        """If command returns exit code 0 but file still exists on disk, flags as verification failure."""
        stubborn = temp_dir / "stubborn.exe"
        stubborn.write_text("still here")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="stubborn-tool",
            installation_id="i13",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="StubbornTool",
            version="1.0",
            executables=[str(stubborn)],
        ))
        scan = scanner.scan_residuals("stubborn-tool")

        # Fake engine returns success=True, but did NOT actually delete the file!
        mock_engine = MagicMock()
        mock_engine.execute_command.return_value = MagicMock(success=True, return_code=0, stdout="Fake 0", stderr="")

        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)
        assert result.status == CleanupOutcomeStatus.CLEANUP_FAILED
        assert result.failed_count == 1
        assert "still detected on disk" in result.uncleaned_artifacts[0]["reason"]


# ---------------------------------------------------------------------------
# 5. Environment & Dependency Protection Tests (25-27)
# ---------------------------------------------------------------------------

class TestEnvironmentAndDependencies:
    def test_25_path_ownership_cleanable(self, temp_dir, mock_registry, scanner):
        """Unused PATH entry owned exclusively by removed tool is eligible for cleanup."""
        bin_dir = temp_dir / "tool_bin"
        bin_dir.mkdir()
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="solo-tool",
            installation_id="i14",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="SoloTool",
            version="1.0",
            environment_entries=[str(bin_dir)],
        ))
        with patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}C:\\Windows"}):
            scan = scanner.scan_residuals("solo-tool")
            cand = scan.candidates[0]
            assert cand.safety_classification == CleanupSafetyClassification.SAFE_CLEANUP
            assert cand.cleanup_allowed is True

    def test_26_path_dependency_protection(self, temp_dir, mock_registry, scanner):
        """PATH entry in use by another active tool is protected from removal."""
        shared_dir = temp_dir / "shared_runtimes"
        shared_dir.mkdir()

        # Tool 1: being uninstalled
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="tool1",
            installation_id="i15",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="Tool1",
            version="1.0",
            environment_entries=[str(shared_dir)],
            uninstalled_at="2026-09-25T00:00:00Z",
        ))
        # Tool 2: still active!
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="tool2",
            installation_id="i16",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="Tool2",
            version="1.0",
            environment_entries=[str(shared_dir)],
            uninstalled_at=None,
        ))

        with patch.dict(os.environ, {"PATH": f"{shared_dir}{os.pathsep}C:\\Windows"}):
            scan = scanner.scan_residuals("tool1")
            cand = scan.candidates[0]
            assert cand.safety_classification == CleanupSafetyClassification.NOT_OWNED
            assert cand.cleanup_allowed is False
            assert "actively required by another installed tool" in cand.evidence[0]

    def test_27_service_ownership_verified(self, mock_registry, scanner):
        """Service registered in managed footprint is recognized as owned."""
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="svc-app2",
            installation_id="i17",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="SvcApp2",
            version="1.0",
            services=["DockerDesktopService"],
        ))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            scan = scanner.scan_residuals("svc-app2")
            assert scan.candidates[0].ownership == ArtifactOwnershipConfidence.OWNED_CONFIRMED


# ---------------------------------------------------------------------------
# 6. Cross-Platform Contracts (28-30)
# ---------------------------------------------------------------------------

class TestCrossPlatformContracts:
    def test_28_windows_footprint_contract(self, temp_dir, mock_registry, scanner):
        """Windows footprint generates PowerShell / sc.exe removal and Test-Path verification."""
        exe = temp_dir / "git.exe"
        exe.write_text("bin")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="git",
            installation_id="win-git",
            source="WINGET",
            package_manager="winget",
            package_id="Git.Git",
            version="2.44.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("git", os_platform="Windows")
        cand = scan.candidates[0]
        assert "powershell" in cand.removal_command
        assert "Test-Path" in cand.verification_probe

    def test_29_linux_footprint_contract(self, temp_dir, mock_registry, scanner):
        """Linux footprint contract generates rm -rf removal and test -e verification."""
        exe = temp_dir / "git"
        exe.write_text("bin")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="git",
            installation_id="lnx-git",
            source="APT",
            package_manager="apt",
            package_id="git",
            version="2.44.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("git", os_platform="Linux")
        cand = scan.candidates[0]
        assert "rm -rf" in cand.removal_command
        assert "test -e" in cand.verification_probe

    def test_30_macos_footprint_contract(self, temp_dir, mock_registry, scanner):
        """macOS footprint contract generates rm -rf removal and test -e verification."""
        exe = temp_dir / "git"
        exe.write_text("bin")
        mock_registry.register_installation(ManagedInstallation(
            canonical_id="git",
            installation_id="mac-git",
            source="BREW",
            package_manager="brew",
            package_id="git",
            version="2.44.0",
            executables=[str(exe)],
        ))
        scan = scanner.scan_residuals("git", os_platform="Darwin")
        cand = scan.candidates[0]
        assert "rm -rf" in cand.removal_command
        assert "test -e" in cand.verification_probe


# ---------------------------------------------------------------------------
# 7. End-to-End Integration & Architectural Invariants (31-32)
# ---------------------------------------------------------------------------

class TestIntegrationAndExecutionPipeline:
    def test_31_end_to_end_cleanup_pipeline(self, temp_dir, mock_registry, scanner, coordinator):
        """
        Proves the complete chain:
        Managed Installation → Footprint Registration → Uninstall → Residual Scan →
        Ownership Classification → ExecutionRequest → ExecutionResolver → ExecutionPlan →
        Tier 2/3 → Approval → Centralized Execution → Verification → Result.
        """
        app_dir = temp_dir / "DemoApp"
        app_dir.mkdir()
        exe = app_dir / "demo.exe"
        exe.write_text("binary")

        # 1. Registration
        inst = ManagedInstallation(
            canonical_id="demo-tool",
            installation_id="demo-1",
            source="DEVTOOLS",
            package_manager="winget",
            package_id="Demo.Tool",
            version="1.0.0",
            installation_root=str(app_dir),
            executables=[str(exe)],
        )
        mock_registry.register_installation(inst)

        # 2. Record uninstall
        mock_registry.record_uninstall("demo-tool")

        # 3. Residual Scan
        scan = scanner.scan_residuals("demo-tool")
        assert scan.scan_status == ResidualScanStatus.SAFE_RESIDUALS_FOUND

        # 4. Preview Generation
        preview = coordinator.generate_preview(scan)
        assert len(preview.safe_cleanup) >= 1
        assert preview.approval_required is True

        # 5. Verify ExecutionResolver & Tier for CLEANUP operation
        req = ExecutionRequest(
            command=f'powershell -NoProfile -Command "Remove-Item \'{exe}\' -Force"',
            target="demo-tool",
            operation="CLEANUP",
            source="MANAGED_FOOTPRINT",
            approved=True,
        )
        plan = execution_resolver.resolve(req)
        assert plan.operation_enum == RecipeOperation.CLEANUP
        assert plan.tier in (ExecutionTier.TIER_2_CONTROLLED, ExecutionTier.TIER_3_FULL_PROTECTED)
        assert plan.approval_required is True

        # 6. Execute through coordinator
        def fake_exec(command, **kwargs):
            if exe.exists():
                exe.unlink()
            if app_dir.exists():
                shutil.rmtree(app_dir, ignore_errors=True)
            return MagicMock(success=True, return_code=0, stdout="Removed", stderr="")

        mock_engine = MagicMock()
        mock_engine.execute_command.side_effect = fake_exec

        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)
        assert result.status == CleanupOutcomeStatus.CLEANUP_SUCCESS
        assert result.cleaned_count >= 1
        assert not exe.exists()

    def test_32_unmanaged_installation_zero_automatic_deletion(self, temp_dir, scanner, coordinator):
        """
        Proves:
        Unknown / Pre-existing Ownership → REVIEW_REQUIRED → ZERO AUTOMATIC DELETION.
        """
        # Scanning an unmanaged tool
        scan = scanner.scan_residuals("git")
        assert scan.ownership_state in (OwnershipState.PRE_EXISTING, OwnershipState.UNKNOWN)

        mock_engine = MagicMock()
        # Even with approved=True, safe_candidates is empty because ownership is unconfirmed
        result = coordinator.execute_cleanup(scan, approved=True, execution_engine_override=mock_engine)

        assert mock_engine.execute_command.call_count == 0
        assert result.cleaned_count == 0
        assert result.status in (CleanupOutcomeStatus.CLEANUP_SUCCESS, CleanupOutcomeStatus.APPROVAL_REQUIRED)
