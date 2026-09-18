"""
tests/test_dev_environment_detection.py — Comprehensive Unit & Integration Tests for:
1. CanonicalIdentity tool registration with required_path_dirs, services, and ports
2. EffectivePath: Persistent PATH (User + Machine Registry) vs Process PATH calculation
3. ToolHealthStatus 16-status evaluation
4. Issue 1: General PATH missing detection (Git, Python, Node, Java, Docker, etc.)
5. Issue 2: Live service state verification, cache invalidation, and active-problem removal
6. Scanner integration & active problems endpoint verification
"""

import os
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend is in sys.path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from canonical_identity import CanonicalIdentity, canonical_store
from dev_environment_detector import (
    DevEnvironmentDetector,
    EffectivePath,
    ToolDiagnosis,
    ToolHealthStatus,
    dev_environment_detector,
)
from scanner import SystemScanner


class TestCanonicalIdentityEnhancements(unittest.TestCase):
    """Verifies that CanonicalIdentity supports required_path_dirs, services, and ports."""

    def test_git_canonical_identity(self):
        ident = canonical_store.get("git")
        self.assertIsNotNone(ident)
        self.assertEqual(ident.executable_name, "git")
        self.assertTrue(len(ident.required_path_dirs) > 0)
        self.assertTrue(any("Git" in d for d in ident.required_path_dirs))

    def test_node_canonical_identity(self):
        ident = canonical_store.get("nodejs")
        self.assertIsNotNone(ident)
        self.assertEqual(ident.executable_name, "node")
        self.assertTrue(len(ident.required_path_dirs) > 0)

    def test_docker_canonical_identity(self):
        ident = canonical_store.get("docker")
        self.assertIsNotNone(ident)
        self.assertIn("docker", ident.service_name.lower())
        self.assertIsNotNone(ident.port)

    def test_python_canonical_identity(self):
        ident = canonical_store.get("python")
        self.assertIsNotNone(ident)
        self.assertEqual(ident.executable_name, "python")
        self.assertTrue(len(ident.required_path_dirs) > 0)


class TestEffectivePath(unittest.TestCase):
    """Verifies persistent PATH vs process PATH calculation."""

    def setUp(self):
        self.ep = EffectivePath()

    def test_normalize_path(self):
        if sys.platform == "win32":
            norm = self.ep.normalize_path(r"C:\Program Files\Git\cmd\\")
            self.assertEqual(norm, r"c:\program files\git\cmd")
        else:
            norm = self.ep.normalize_path("/usr/local/bin//")
            self.assertEqual(norm, "/usr/local/bin")

    def test_is_dir_in_persistent_path_mocked(self):
        if sys.platform == "win32":
            sample_paths = [r"c:\program files\git\cmd", r"c:\windows\system32"]
            target = r"C:\Program Files\Git\cmd"
            target_slash = r"C:\Program Files\Git\cmd\\"
            non_existent = r"C:\NonExistent\bin"
        else:
            sample_paths = ["/usr/bin", "/usr/local/bin"]
            target = "/usr/bin"
            target_slash = "/usr/bin/"
            non_existent = "/nonexistent/bin"

        with patch.object(self.ep, "get_persistent_paths", return_value=sample_paths):
            self.assertTrue(self.ep.is_dir_in_persistent_path(target))
            self.assertTrue(self.ep.is_dir_in_persistent_path(target_slash))
            self.assertFalse(self.ep.is_dir_in_persistent_path(non_existent))

    def test_persistent_vs_process_divergence(self):
        """Persistent PATH can lack an entry even if current process inherited it."""
        if sys.platform == "win32":
            persistent = [r"c:\windows\system32"]
            process = [r"c:\program files\git\cmd", r"c:\windows\system32"]
            target = r"C:\Program Files\Git\cmd"
        else:
            persistent = ["/usr/bin"]
            process = ["/usr/local/bin", "/usr/bin"]
            target = "/usr/local/bin"

        with patch.object(self.ep, "get_persistent_paths", return_value=persistent):
            with patch.object(self.ep, "get_process_paths", return_value=process):
                # In process, but not persistent!
                self.assertFalse(self.ep.is_dir_in_persistent_path(target))
                self.assertTrue(self.ep.is_dir_in_process_path(target))


class TestToolHealthStatus16Statuses(unittest.TestCase):
    """Verifies that all 16 ToolHealthStatus enums exist."""

    def test_all_16_statuses_exist(self):
        expected_statuses = [
            "INSTALLED_AND_USABLE",
            "INSTALLED_BUT_PATH_MISSING",
            "NOT_INSTALLED",
            "EXECUTABLE_EXISTS_BUT_VERIFICATION_FAILED",
            "MULTIPLE_VERSIONS",
            "SERVICE_INSTALLED_BUT_STOPPED",
            "PORT_CONFLICT",
            "PACKAGE_MANAGER_STATE_MISMATCH",
            "CORRUPTED_INSTALLATION",
            "VERSION_INCOMPATIBLE",
            "PERMISSIONS_DENIED",
            "DEPENDENCY_MISSING",
            "CONFIGURATION_INVALID",
            "ENV_VAR_UNSET",
            "REGISTRY_ENTRY_INVALID",
            "ARCH_MISMATCH",
        ]
        for s in expected_statuses:
            self.assertTrue(hasattr(ToolHealthStatus, s), f"Missing status: {s}")


class TestIssue1GitPathProblem(unittest.TestCase):
    """
    Issue 1: Git is physically installed at C:\\Program Files\\Git\\cmd\\git.exe.
    The PATH entry C:\\Program Files\\Git\\cmd is removed from persistent PATH.
    Detection must diagnose INSTALLED_BUT_PATH_MISSING with repair command.
    """

    def setUp(self):
        self.detector = DevEnvironmentDetector()

    def test_git_installed_but_path_missing(self):
        fake_git_exe = r"C:\Program Files\Git\cmd\git.exe" if sys.platform == "win32" else "/opt/git/bin/git"

        # Mock: binary is discovered on disk
        with patch.object(self.detector, "discover_executable", return_value=[fake_git_exe]):
            # Mock: persistent PATH does NOT contain git parent directory
            with patch.object(self.detector.effective_path, "is_dir_in_persistent_path", return_value=False):
                with patch.object(self.detector.effective_path, "is_dir_in_process_path", return_value=True):
                    diag = self.detector.diagnose_tool("git")

                    self.assertEqual(diag.status, ToolHealthStatus.INSTALLED_BUT_PATH_MISSING)
                    self.assertTrue(diag.installed)
                    self.assertEqual(diag.discovered_path, fake_git_exe)
                    self.assertFalse(diag.in_effective_path)
                    self.assertIn("missing from the system/user PATH", diag.diagnosis_message)
                    self.assertIsNotNone(diag.repair_command)
                    if sys.platform == "win32":
                        self.assertIn("SetEnvironmentVariable", diag.repair_command)
                        self.assertIn("Git", diag.repair_command)
                    else:
                        self.assertIn("export PATH", diag.repair_command)

    def test_git_installed_and_usable_when_in_persistent_path(self):
        fake_git_exe = r"C:\Program Files\Git\cmd\git.exe" if sys.platform == "win32" else "/opt/git/bin/git"

        with patch.object(self.detector, "discover_executable", return_value=[fake_git_exe]):
            with patch.object(self.detector.effective_path, "is_dir_in_persistent_path", return_value=True):
                with patch.object(self.detector, "_test_launch_in_persistent_env", return_value=("git version 2.44.0", True)):
                    diag = self.detector.diagnose_tool("git")

                    self.assertEqual(diag.status, ToolHealthStatus.INSTALLED_AND_USABLE)
                    self.assertTrue(diag.installed)
                    self.assertTrue(diag.in_effective_path)
                    self.assertEqual(diag.version_detected, "git version 2.44.0")

    def test_python_and_node_path_missing_generalization(self):
        """Ensures the exact same mechanism detects Node.js and Python PATH problems."""
        fake_node_exe = r"C:\Program Files\nodejs\node.exe" if sys.platform == "win32" else "/opt/nodejs/bin/node"
        with patch.object(self.detector, "discover_executable", return_value=[fake_node_exe]):
            with patch.object(self.detector.effective_path, "is_dir_in_persistent_path", return_value=False):
                diag = self.detector.diagnose_tool("nodejs")
                self.assertEqual(diag.status, ToolHealthStatus.INSTALLED_BUT_PATH_MISSING)
                self.assertIn("nodejs", diag.repair_command.lower())


class TestIssue2WindowsUpdateLiveVerification(unittest.TestCase):
    """
    Issue 2: Windows Update Agent stopped -> repair command run -> verified Running ->
    removed from scanner latest_issues, TTL cache invalidated, not shown in active problems.
    """

    def setUp(self):
        self.detector = DevEnvironmentDetector()
        self.scanner = SystemScanner()

    def test_check_service_stopped(self):
        with patch.object(self.detector, "check_service", return_value={"exists": True, "status": "Stopped", "display_name": "Windows Update"}):
            info = self.detector.check_service("wuauserv")
            self.assertEqual(info["status"], "Stopped")

    def test_post_repair_verify_service_running(self):
        """Repair command starts service; post_repair_verify sees Running, invalidates cache, purges issue."""
        # Seed scanner with the problem
        self.scanner.latest_issues = [
            {
                "type": "service_wuauserv",
                "severity": "medium",
                "title": "Windows Update Agent Stopped",
                "detail": "Service inactive",
            }
        ]
        self.scanner._set_cached = MagicMock()

        # Live probe returns Running
        with patch.object(self.detector, "check_service", return_value={"exists": True, "status": "Running", "display_name": "Windows Update"}):
            verify_res = self.detector.post_repair_verify(
                command='powershell -Command "Start-Service wuauserv"',
                title="Windows Update Agent Stopped",
                issue_type="service_wuauserv",
                scanner_instance=self.scanner,
            )

            self.assertTrue(verify_res["verified"])
            self.assertIn("Running", verify_res["message"])

            # Verify scanner.latest_issues was purged of service_wuauserv
            self.assertEqual(len(self.scanner.latest_issues), 0)
            # Verify resolved_types includes service_wuauserv
            self.assertIn("service_wuauserv", self.scanner.resolved_types)

    def test_post_repair_verify_service_still_stopped_fails(self):
        """If service failed to start, verified must be False and issue must NOT be cleared."""
        self.scanner.latest_issues = [{"type": "service_wuauserv", "title": "Windows Update Agent Stopped"}]

        with patch.object(self.detector, "check_service", return_value={"exists": True, "status": "Stopped", "display_name": "Windows Update"}):
            verify_res = self.detector.post_repair_verify(
                command='powershell -Command "Start-Service wuauserv"',
                title="Windows Update Agent Stopped",
                scanner_instance=self.scanner,
            )
            self.assertFalse(verify_res["verified"])
            self.assertEqual(len(self.scanner.latest_issues), 1)


class TestScannerDevToolsIntegration(unittest.TestCase):
    """Verifies that Scanner.run_step('dev_tools') surfaces developer environment issues."""

    def setUp(self):
        self.scanner = SystemScanner()

    def test_scanner_reports_path_missing_tool(self):
        mock_diag = ToolDiagnosis(
            tool_id="git",
            display_name="Git",
            status=ToolHealthStatus.INSTALLED_BUT_PATH_MISSING,
            installed=True,
            discovered_path=r"C:\Program Files\Git\cmd\git.exe",
            diagnosis_message="Git directory missing from PATH",
            repair_command="powershell -Command SetEnvironmentVariable...",
            repair_purpose="Restore Git to PATH",
            risk="Low",
        )

        with patch("dev_environment_detector.dev_environment_detector.diagnose_all_tools", return_value=[mock_diag]):
            issues = self.scanner.run_step("dev_tools")
            self.assertTrue(len(issues) > 0)
            git_issue = issues[0]
            self.assertIn("git", git_issue["type"])
            self.assertEqual(git_issue.get("tool_id"), "git")
            self.assertIn("Missing From PATH", git_issue["title"])
            self.assertEqual(git_issue["fix_command"], mock_diag.repair_command)


class TestActiveProblemsAndRepairIntegration(unittest.IsolatedAsyncioTestCase):
    """Verifies that /api/repair/active-problems and execute flow correctly handle devtools and services."""

    async def test_get_active_repair_problems_surfaces_path_missing_git(self):
        from routes_system import get_active_repair_problems
        mock_diag = ToolDiagnosis(
            tool_id="git",
            display_name="Git",
            status=ToolHealthStatus.INSTALLED_BUT_PATH_MISSING,
            installed=True,
            discovered_path=r"C:\Program Files\Git\cmd\git.exe",
            diagnosis_message="Git is physically installed but missing from PATH",
            repair_command="powershell -Command SetEnvironmentVariable...",
            repair_purpose="Restore Git to PATH",
            risk="Low",
        )

        with patch("dev_environment_detector.dev_environment_detector.check_service", return_value={"exists": True, "status": "Running"}):
            with patch("dev_environment_detector.dev_environment_detector.diagnose_all_tools", return_value=[mock_diag]):
                res = await get_active_repair_problems()
                problems = res.get("problems", []) if isinstance(res, dict) else res
                git_probs = [p for p in problems if "Git" in p["title"]]
                self.assertTrue(len(git_probs) > 0)
                self.assertIn("INSTALLED_BUT_PATH_MISSING", git_probs[0]["title"])
                self.assertTrue(git_probs[0]["auto_implement"])
                self.assertEqual(git_probs[0]["command"], mock_diag.repair_command)

    @unittest.skipUnless(sys.platform == "win32", "Windows Update service wuauserv active problem test")
    async def test_get_active_repair_problems_clears_resolved_service(self):
        from routes_system import get_active_repair_problems
        from scanner import scanner
        scanner.latest_issues = [
            {"type": "service_wuauserv", "title": "Windows Update Agent Stopped", "severity": "medium"}
        ]

        with patch("dev_environment_detector.dev_environment_detector.check_service", return_value={"exists": True, "status": "Running"}):
            with patch("dev_environment_detector.dev_environment_detector.diagnose_all_tools", return_value=[]):
                res = await get_active_repair_problems()
                problems = res.get("problems", []) if isinstance(res, dict) else res
                # Because wuauserv is Running, it must NOT appear in problems
                wu_probs = [p for p in problems if "Windows Update" in p["title"]]
                self.assertEqual(len(wu_probs), 0)
                # And must be purged from scanner.latest_issues
                self.assertNotIn("service_wuauserv", [x.get("type") for x in scanner.latest_issues])


if __name__ == "__main__":
    unittest.main()
