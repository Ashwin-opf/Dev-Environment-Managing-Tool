"""
tests/test_phase13_1_problem54_linux_outdated_repo.py — Phase 13.1 Problem #54 (Linux repository package outdated) Test Suite.

Verifies:
1. All Linux package manager providers (APT, DNF, Pacman, Zypper, APK) implement build_refresh_command().
2. Multi-step execution plan for outdated repository packages:
   - Detect distro/PM
   - Refresh official repository metadata first
   - Execute native package update command
   - Functional Level 2 version verification probe
   - Machine and tool state rescan
   - Structured audit logging and canonical result
3. Single mutation authority: All mutations strictly pass through CentralizedExecutionEngine.
4. Robust failure handling:
   - Unsupported / unknown distribution routes strictly to REVIEW_REQUIRED with zero mutations.
   - Repository refresh failure halts and reports REPOSITORY_UNAVAILABLE.
   - Package update failure halts and reports failure status.
   - Version mismatch or unchanged version honestly reports VERIFICATION_FAILED without hallucinating success.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution_engine import CentralizedExecutionEngine, ExecutionOutcome
from platform_abstraction.linux.linux_distribution import (
    LinuxArchitecture,
    LinuxDistribution,
    LinuxDistributionFamily,
    LinuxDistributionProvider,
)
from platform_abstraction.linux.linux_package_manager import (
    ApkPackageManagerProvider,
    AptPackageManagerProvider,
    DnfPackageManagerProvider,
    LinuxPackageManagerName,
    LinuxPackageManagerProvider,
    LinuxPackageManagerResolver,
    PackageOperationStatus,
    PackageVerificationState,
    PacmanPackageManagerProvider,
    ZypperPackageManagerProvider,
)


def make_linux_distro(
    distribution: str = "ubuntu",
    family: LinuxDistributionFamily = LinuxDistributionFamily.DEBIAN,
    version: str = "24.04",
    pm: str = "apt",
    is_supported: bool = True,
) -> LinuxDistribution:
    return LinuxDistribution(
        distribution=distribution,
        distribution_name=f"{distribution.title()} {version}",
        distribution_family=family,
        distribution_version=version,
        distribution_codename="test",
        architecture="x86_64",
        primary_package_manager=pm,
        available_package_managers=[pm] if is_supported else [],
        init_system="systemd",
        is_supported=is_supported,
        is_family_compatible=is_supported,
    )


def make_outcome(
    success: bool = True,
    status: str = "SUCCESS",
    command: str = "",
    rc: int = 0,
    stderr: str = "",
) -> ExecutionOutcome:
    return ExecutionOutcome(
        success=success,
        status=status,
        operation="UPDATE",
        target="git",
        command=command,
        return_code=rc,
        stdout="ok" if success else "",
        stderr=stderr,
        classification=status,
        verification={},
    )


class TestProblem54LinuxOutdatedRepository(unittest.TestCase):
    """Authoritative test suite for Problem #54 (Linux repository package outdated)."""

    def setUp(self):
        self.mock_engine = MagicMock(spec=CentralizedExecutionEngine)

    def test_01_all_providers_implement_build_refresh_command(self):
        """All 5 providers return the correct native metadata refresh command."""
        apt = AptPackageManagerProvider()
        self.assertEqual(apt.build_refresh_command(), ["apt-get", "update"])

        dnf = DnfPackageManagerProvider()
        self.assertEqual(dnf.build_refresh_command(), ["dnf", "makecache"])

        pacman = PacmanPackageManagerProvider()
        self.assertEqual(pacman.build_refresh_command(), ["pacman", "-Sy"])

        zypper = ZypperPackageManagerProvider()
        self.assertEqual(zypper.build_refresh_command(), ["zypper", "--non-interactive", "refresh"])

        apk = ApkPackageManagerProvider()
        self.assertEqual(apk.build_refresh_command(), ["apk", "update"])

    def test_02_successful_multi_step_remediation_ubuntu_apt(self):
        """
        Full lifecycle test for Ubuntu / APT:
        1. Distro detected as Ubuntu (Debian family)
        2. Refresh command 'apt-get update' executed first
        3. Upgrade command 'apt-get install --only-upgrade -y git' executed second
        4. Version probe verifies updated version
        5. Returns SUCCESS with full telemetry
        """
        distro = make_linux_distro("ubuntu", LinuxDistributionFamily.DEBIAN, "24.04", "apt", True)

        versions = {"current": "2.34.1"}

        def mock_apt_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "dpkg-query" in cmd:
                return (0, versions["current"], "")
            return (0, "", "")

        prov = AptPackageManagerProvider(runner=mock_apt_runner)
        prov.is_available = MagicMock(return_value=True)
        custom_providers = {LinuxPackageManagerName.APT: prov}
        resolver = LinuxPackageManagerResolver(distro, custom_providers=custom_providers)

        refresh_outcome = make_outcome(success=True, status="SUCCESS", command="apt-get update", rc=0)
        update_outcome = make_outcome(success=True, status="SUCCESS", command="apt-get install --only-upgrade -y git", rc=0)

        def mock_exec_command(**kwargs):
            if kwargs.get("operation") == "REFRESH_METADATA":
                return refresh_outcome
            elif kwargs.get("operation") == "UPDATE":
                versions["current"] = "2.44.0"
                return update_outcome
            return make_outcome(success=False, status="FAILED")

        self.mock_engine.execute_command.side_effect = mock_exec_command

        with patch("state_refresh.state_refresher.refresh_tool_state") as mock_rescan:
            result = resolver.remediate_outdated_repository(
                canonical_id="git",
                expected_version="2.44.0",
                distro=distro,
                execution_engine=self.mock_engine,
                approved=True,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["initial_version"], "2.34.1")
            self.assertEqual(result["final_version"], "2.44.0")
            self.assertEqual(result["package_manager"], "apt")

            calls = self.mock_engine.execute_command.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0].kwargs["command"], "apt-get update")
            self.assertEqual(calls[1].kwargs["command"], "apt-get install --only-upgrade -y git")
            mock_rescan.assert_called_once_with("git")

    def test_03_successful_remediation_fedora_dnf(self):
        """Full lifecycle test for Fedora / DNF."""
        distro = make_linux_distro("fedora", LinuxDistributionFamily.REDHAT, "40", "dnf", True)

        versions = {"current": "13.0.0"}

        def mock_dnf_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "rpm" in cmd and "-q" in cmd:
                return (0, versions["current"], "")
            return (0, "", "")

        prov = DnfPackageManagerProvider(runner=mock_dnf_runner)
        prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.DNF: prov})

        def mock_exec_command(**kwargs):
            if kwargs.get("operation") == "UPDATE":
                versions["current"] = "14.1.0"
            return make_outcome(success=True, status="SUCCESS", rc=0)

        self.mock_engine.execute_command.side_effect = mock_exec_command

        with patch("state_refresh.state_refresher.refresh_tool_state"):
            result = resolver.remediate_outdated_repository(
                canonical_id="ripgrep",
                expected_version="14.1.0",
                distro=distro,
                execution_engine=self.mock_engine,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["final_version"], "14.1.0")
            self.assertEqual(result["package_manager"], "dnf")

    def test_04_unknown_distribution_strictly_routes_to_review_required(self):
        """Unsupported or unknown Linux distribution halts with REVIEW_REQUIRED and zero mutations."""
        distro = make_linux_distro("custom_unknown_linux", LinuxDistributionFamily.UNKNOWN, "1.0", "unknown", False)

        resolver = LinuxPackageManagerResolver(distro)

        result = resolver.remediate_outdated_repository(
            canonical_id="git",
            distro=distro,
            execution_engine=self.mock_engine,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn("Manual review required", result["message"])
        self.mock_engine.execute_command.assert_not_called()

    def test_05_metadata_refresh_failure_halts_without_updating(self):
        """If repository metadata refresh fails (e.g. network/unreachable), update is never attempted."""
        distro = make_linux_distro("ubuntu", LinuxDistributionFamily.DEBIAN, "24.04", "apt", True)

        prov = AptPackageManagerProvider(runner=lambda cmd: (0, "2.34.1", ""))
        prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.APT: prov})

        self.mock_engine.execute_command.return_value = make_outcome(
            success=False,
            status="EXECUTION_FAILED",
            stderr="Could not resolve archive.ubuntu.com: Temporary failure in name resolution",
            rc=100,
        )

        result = resolver.remediate_outdated_repository(
            canonical_id="git",
            distro=distro,
            execution_engine=self.mock_engine,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "REPOSITORY_UNAVAILABLE")
        self.assertEqual(self.mock_engine.execute_command.call_count, 1)

    def test_06_package_update_failure_reported_honestly(self):
        """If package upgrade fails (e.g. dependency broken), failure is reported honestly."""
        distro = make_linux_distro("ubuntu", LinuxDistributionFamily.DEBIAN, "24.04", "apt", True)

        prov = AptPackageManagerProvider(runner=lambda cmd: (0, "2.34.1", ""))
        prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.APT: prov})

        def mock_exec_command(**kwargs):
            if kwargs.get("operation") == "REFRESH_METADATA":
                return make_outcome(success=True, status="SUCCESS", rc=0)
            return make_outcome(
                success=False,
                status="PACKAGE_OPERATION_FAILED",
                stderr="E: Broken packages",
                rc=100,
            )

        self.mock_engine.execute_command.side_effect = mock_exec_command

        result = resolver.remediate_outdated_repository(
            canonical_id="git",
            distro=distro,
            execution_engine=self.mock_engine,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "PACKAGE_OPERATION_FAILED")

    def test_07_version_unchanged_reports_verification_failed(self):
        """
        If update executes with rc 0, but installed version does NOT change,
        the engine honestly reports VERIFICATION_FAILED (never hallucinates success).
        """
        distro = make_linux_distro("ubuntu", LinuxDistributionFamily.DEBIAN, "24.04", "apt", True)

        prov = AptPackageManagerProvider(runner=lambda cmd: (0, "2.34.1", ""))
        prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.APT: prov})

        self.mock_engine.execute_command.return_value = make_outcome(
            success=True,
            status="SUCCESS",
            rc=0,
        )

        with patch("state_refresh.state_refresher.refresh_tool_state"):
            result = resolver.remediate_outdated_repository(
                canonical_id="git",
                distro=distro,
                execution_engine=self.mock_engine,
            )

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "VERIFICATION_FAILED")
            self.assertIn("version did not change", result["message"])

    def test_08_version_mismatch_reports_verification_failed(self):
        """
        If expected version is 2.45.0, but post-update version is 2.40.0,
        it reports VERIFICATION_FAILED honestly.
        """
        distro = make_linux_distro("ubuntu", LinuxDistributionFamily.DEBIAN, "24.04", "apt", True)

        versions = {"current": "2.34.1"}

        def mock_apt_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "dpkg-query" in cmd:
                return (0, versions["current"], "")
            return (0, "", "")

        prov = AptPackageManagerProvider(runner=mock_apt_runner)
        prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.APT: prov})

        def mock_exec_command(**kwargs):
            if kwargs.get("operation") == "UPDATE":
                versions["current"] = "2.40.0"  # Did not reach 2.45.0
            return make_outcome(success=True, status="SUCCESS", rc=0)

        self.mock_engine.execute_command.side_effect = mock_exec_command

        with patch("state_refresh.state_refresher.refresh_tool_state"):
            result = resolver.remediate_outdated_repository(
                canonical_id="git",
                expected_version="2.45.0",
                distro=distro,
                execution_engine=self.mock_engine,
            )

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "VERIFICATION_FAILED")
            self.assertIn("verification failed", result["message"])


if __name__ == "__main__":
    unittest.main()
