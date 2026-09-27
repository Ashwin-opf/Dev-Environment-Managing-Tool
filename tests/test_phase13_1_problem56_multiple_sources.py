"""
tests/test_phase13_1_problem56_multiple_sources.py — Phase 13.1 Problem #56 (Multiple installation sources) Test Suite.

Verifies:
1. Cross-platform detection of multiple installation sources (Windows, macOS, Linux).
2. Active PATH resolution (distinguishing active binary from shadowed/redundant binaries).
3. Managed footprint ownership verification:
   - Identifies PC_DOCTOR_MANAGED installations vs EXTERNAL/unmanaged instances.
   - Enforces invariant: Auto-removal permitted ONLY for verified PC_DOCTOR_MANAGED sources.
   - Enforces invariant: Unmanaged/user sources strictly route to REVIEW_REQUIRED.
4. Safe migration sequence:
   - Target source verified BEFORE old redundant source removal.
   - If target verification fails, aborts immediately without touching old source.
   - Removes managed redundant source strictly through CentralizedExecutionEngine.
   - Post-removal verification and state rescan.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution_engine import CentralizedExecutionEngine, ExecutionOutcome
from managed_footprint import ManagedFootprintRegistry, ManagedInstallation, OwnershipState
from multi_source_manager import (
    DetectedInstallation,
    InstallationSourceType,
    MultiSourceAnalysisResult,
    MultiSourceDetector,
    MultiSourceRemediator,
    MultiSourceStatus,
)


def make_outcome(success: bool = True, status: str = "SUCCESS", command: str = "", rc: int = 0) -> ExecutionOutcome:
    return ExecutionOutcome(
        success=success,
        status=status,
        operation="UNINSTALL" if "uninstall" in command or "remove" in command else "INSTALL",
        target="git",
        command=command,
        return_code=rc,
        stdout="ok" if success else "",
        stderr="" if success else "error",
        classification=status,
        verification={},
    )


class TestProblem56MultipleInstallationSources(unittest.TestCase):
    """Authoritative test suite for Problem #56 (Multiple installation sources)."""

    def setUp(self):
        self.mock_registry = MagicMock(spec=ManagedFootprintRegistry)
        self.mock_engine = MagicMock(spec=CentralizedExecutionEngine)

    def test_01_no_conflict_when_single_source_detected(self):
        """Single installation detects no conflict."""
        detector = MultiSourceDetector(footprint_registry=self.mock_registry)
        inst = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.WINGET,
            executable_path="C:\\Program Files\\Git\\cmd\\git.exe",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )

        res = detector.detect_installations("git", custom_installations=[inst])
        self.assertFalse(res.has_conflict)
        self.assertEqual(res.status, MultiSourceStatus.NO_CONFLICT)

    def test_02_detects_multiple_sources_windows_winget_and_choco(self):
        """Detects conflicting WinGet and Chocolatey installations on Windows."""
        detector = MultiSourceDetector(footprint_registry=self.mock_registry)
        inst_winget = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.WINGET,
            executable_path="C:\\Program Files\\Git\\cmd\\git.exe",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        inst_choco = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.CHOCOLATEY,
            executable_path="C:\\ProgramData\\chocolatey\\bin\\git.exe",
            is_active=False,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )

        res = detector.detect_installations("git", custom_installations=[inst_winget, inst_choco])
        self.assertTrue(res.has_conflict)
        self.assertEqual(len(res.installations), 2)
        self.assertEqual(res.active_installation.source_type, InstallationSourceType.WINGET)
        self.assertEqual(res.status, MultiSourceStatus.MULTIPLE_SOURCES_DETECTED)

    def test_03_detects_multiple_sources_macos_brew_and_app(self):
        """Detects conflicting Homebrew and vendor .app installations on macOS."""
        detector = MultiSourceDetector(footprint_registry=self.mock_registry)
        inst_brew = DetectedInstallation(
            canonical_id="neovim",
            source_type=InstallationSourceType.HOMEBREW,
            executable_path="/opt/homebrew/bin/nvim",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        inst_app = DetectedInstallation(
            canonical_id="neovim",
            source_type=InstallationSourceType.MACOS_APP,
            executable_path="/Applications/Neovim.app/Contents/MacOS/nvim",
            is_active=False,
            ownership_state=OwnershipState.EXTERNAL,
        )

        res = detector.detect_installations("neovim", custom_installations=[inst_brew, inst_app])
        self.assertTrue(res.has_conflict)
        self.assertTrue(res.requires_review)
        self.assertEqual(res.status, MultiSourceStatus.REVIEW_REQUIRED)

    def test_04_unmanaged_redundant_source_strictly_requires_review(self):
        """
        Safety Invariant:
        When a redundant installation is NOT managed by PC Doctor (e.g. user-installed in /usr/local or standalone),
        automated deletion is strictly forbidden and routes to REVIEW_REQUIRED.
        """
        remediator = MultiSourceRemediator(execution_engine=self.mock_engine, footprint_registry=self.mock_registry)

        inst_primary = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.APT,
            executable_path="/usr/bin/git",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        # Redundant user-compiled installation in /usr/local/bin
        inst_unmanaged = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.STANDALONE_PATH,
            executable_path="/usr/local/bin/git",
            is_active=False,
            ownership_state=OwnershipState.EXTERNAL,  # User/external installed!
        )

        detector = MultiSourceDetector(footprint_registry=self.mock_registry)
        analysis = detector.detect_installations("git", custom_installations=[inst_primary, inst_unmanaged])

        result = remediator.remediate_multiple_sources(
            canonical_id="git",
            target_source=InstallationSourceType.APT,
            custom_analysis=analysis,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], MultiSourceStatus.REVIEW_REQUIRED.value)
        self.assertTrue(result["requires_review"])
        self.assertIn("not managed by PC Doctor", result["reason"])
        # Invariant: CentralizedExecutionEngine must NOT have been called for unmanaged deletion
        self.mock_engine.execute_command.assert_not_called()

    def test_05_target_verification_failure_halts_without_removing_old_source(self):
        """
        Safety Invariant:
        If target source is being prepared/installed and its verification fails,
        the old redundant source MUST NOT be uninstalled (prevents tool loss).
        """
        remediator = MultiSourceRemediator(execution_engine=self.mock_engine, footprint_registry=self.mock_registry)

        inst_choco = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.CHOCOLATEY,
            executable_path="C:\\ProgramData\\chocolatey\\bin\\git.exe",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )

        detector = MultiSourceDetector(footprint_registry=self.mock_registry)
        analysis = detector.detect_installations("git", custom_installations=[inst_choco])
        analysis.has_conflict = True  # Simulating migration from choco to winget
        analysis.installations.append(
            DetectedInstallation(
                canonical_id="git",
                source_type=InstallationSourceType.WINGET,
                executable_path=None,  # Not installed yet
                is_active=False,
                ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
            )
        )

        # Mock target install failure
        self.mock_engine.execute_command.return_value = make_outcome(
            success=False,
            status="EXECUTION_FAILED",
            command="winget install --id Git.Git --silent",
            rc=1,
        )

        result = remediator.remediate_multiple_sources(
            canonical_id="git",
            target_source=InstallationSourceType.WINGET,
            custom_analysis=analysis,
            target_install_command="winget install --id Git.Git --silent",
            target_verify_fn=lambda: False,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], MultiSourceStatus.TARGET_VERIFICATION_FAILED.value)
        # Verify: Old choco installation was NEVER uninstalled
        calls = [c.kwargs.get("command", "") for c in self.mock_engine.execute_command.call_args_list]
        self.assertFalse(any("choco uninstall" in cmd for cmd in calls))

    def test_06_successful_migration_removes_managed_redundant_source(self):
        """
        Successful safe migration:
        1. Target source (WinGet) is active and verified
        2. Redundant source (Chocolatey) is verified PC_DOCTOR_MANAGED
        3. Redundant source is uninstalled via CentralizedExecutionEngine
        4. Footprint updated
        5. Returns MIGRATION_SUCCESS
        """
        mock_detector = MagicMock(spec=MultiSourceDetector)
        remediator = MultiSourceRemediator(
            execution_engine=self.mock_engine,
            detector=mock_detector,
            footprint_registry=self.mock_registry,
        )

        inst_winget = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.WINGET,
            executable_path="C:\\Program Files\\Git\\cmd\\git.exe",
            is_active=True,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        inst_choco = DetectedInstallation(
            canonical_id="git",
            source_type=InstallationSourceType.CHOCOLATEY,
            executable_path="C:\\ProgramData\\chocolatey\\bin\\git.exe",
            is_active=False,
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
            package_id="git",
        )

        analysis = MultiSourceAnalysisResult(
            canonical_id="git",
            status=MultiSourceStatus.MULTIPLE_SOURCES_DETECTED,
            active_installation=inst_winget,
            installations=[inst_winget, inst_choco],
            has_conflict=True,
        )

        # After removal, final check returns single source
        final_analysis = MultiSourceAnalysisResult(
            canonical_id="git",
            status=MultiSourceStatus.NO_CONFLICT,
            active_installation=inst_winget,
            installations=[inst_winget],
            has_conflict=False,
        )
        mock_detector.detect_installations.return_value = final_analysis

        self.mock_engine.execute_command.return_value = make_outcome(
            success=True,
            status="SUCCESS",
            command="choco uninstall git -y",
            rc=0,
        )

        with patch("state_refresh.state_refresher.refresh_tool_state") as mock_rescan:
            result = remediator.remediate_multiple_sources(
                canonical_id="git",
                target_source=InstallationSourceType.WINGET,
                custom_analysis=analysis,
                target_verify_fn=lambda: True,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["status"], MultiSourceStatus.MIGRATION_SUCCESS.value)
            self.assertEqual(result["target_source"], "winget")
            self.assertIn("choco", result["removed_sources"])

            # Verify uninstallation command executed via engine
            self.mock_engine.execute_command.assert_called_once()
            cmd_called = self.mock_engine.execute_command.call_args.kwargs["command"]
            self.assertEqual(cmd_called, "choco uninstall git -y")

            # Footprint updated and rescan called
            self.mock_registry.record_uninstall.assert_called_once_with("git")
            mock_rescan.assert_called_once_with("git")


if __name__ == "__main__":
    unittest.main()
