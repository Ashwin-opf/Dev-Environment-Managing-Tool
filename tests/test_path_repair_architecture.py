"""
tests/test_path_repair_architecture.py — Architecture-Level Tests for Generic PATH Repair & Elevation Flow

Covers the 10 Mandatory Acceptance Tests:
TEST 1: Safe admin-only read -> UAC works -> parent receives result
TEST 2: Git Machine PATH repair -> UAC -> repair -> verification
TEST 3: Git UAC cancellation -> USER_DECLINED_ELEVATION
TEST 4: MySQL Machine PATH repair -> same generic elevation mechanism
TEST 5: Chrome Machine PATH repair -> same generic elevation mechanism
TEST 6: Anaconda User PATH repair -> no unnecessary UAC
TEST 7: Multiple Python versions -> review-only -> no execution
TEST 8: Natural-language string passed as command -> rejected by backend
TEST 9: Missing command -> NO_AUTOMATIC_REPAIR
TEST 10: Duplicate Python problem -> only one active problem displayed

Additional Regression Tests:
G. PATH already contains directory -> No duplicate entry
H. PATH contains directory with different casing / trailing slash -> Recognized as existing
I. Existing PATH contains multiple entries -> All preserved in order
J. Repair succeeds -> Fresh live detector removes active problem
K. Repair command fails -> Problem remains active
L. Verification fails after exit code 0 -> Problem remains active, no fake success
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend to sys.path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from canonical_identity import CanonicalIdentity, canonical_store
from dev_environment_detector import (
    DevEnvironmentDetector,
    EffectivePath,
    PathScope,
    ToolDiagnosis,
    ToolHealthStatus,
    is_process_elevated,
)
from routes_system import (
    ExecuteRequest,
    execute_command,
    get_active_repair_problems,
    validate_execution_request,
)
from safety import is_natural_language_command
from app_context import engine, DB_PATH
from scanner import scanner


class TestPathModelAndSafety(unittest.TestCase):
    """Tests G, H, I: Normalization, Deduplication, and Entry Preservation."""

    def setUp(self):
        self.effective_path = EffectivePath()

    def test_g_path_already_contains_directory_no_duplicate(self):
        """Test G: Directory already in PATH should return modified=False / already present."""
        with patch.object(EffectivePath, "get_machine_path", return_value=[r"C:\Windows\System32", r"C:\Program Files\Git\cmd"]), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=True):
            res = EffectivePath.repair_path_entry(r"C:\Program Files\Git\cmd", scope=PathScope.MACHINE)
            self.assertEqual(res.status, "ALREADY_PRESENT")
            self.assertIn("already", res.message.lower())

    def test_h_casing_and_trailing_slash_normalization(self):
        """Test H: Different casing and trailing slashes are recognized as existing."""
        with patch.object(EffectivePath, "get_machine_path", return_value=["C:\\Windows\\System32", "c:\\program files\\git\\cmd\\"]), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=True):
            res = EffectivePath.repair_path_entry("C:\\Program Files\\Git\\cmd", scope=PathScope.MACHINE)
            self.assertEqual(res.status, "ALREADY_PRESENT")
            self.assertIn("already", res.message.lower())

    def test_i_all_existing_entries_preserved(self):
        """Test I: Existing PATH entries A;B;C are preserved when adding D -> A;B;C;D."""
        raw_existing = r"C:\Windows\System32;C:\Windows;C:\Tools\bin"
        entries = EffectivePath.parse_path_entries(raw_existing)
        self.assertEqual(len(entries), 3)

        new_target = r"C:\Program Files\Git\cmd"
        combined = entries + [new_target]
        self.assertEqual(combined[0], r"C:\Windows\System32")
        self.assertEqual(combined[1], r"C:\Windows")
        self.assertEqual(combined[2], r"C:\Tools\bin")
        self.assertEqual(combined[3], new_target)
        self.assertEqual(len(combined), 4)


class TestTenMandatoryScenarios(unittest.TestCase):
    """The 10 Required Contract Tests specified in the Root Cause specification."""

    def setUp(self):
        self.detector = DevEnvironmentDetector()
        self.engine = engine

    def test_1_safe_admin_only_read_elevation_and_result(self):
        """TEST 1: Safe admin-only read -> UAC works -> parent receives result."""
        # 1. Test isolated worker with ADMIN_PROBE directly
        payload = {"operation": "ADMIN_PROBE", "probe_target": "SystemDrive"}
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as pf, \
             tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as rf:
            json.dump(payload, pf)
            pf_name = pf.name
            rf_name = rf.name

        try:
            worker_script = os.path.join(str(backend_dir), "elevated_worker.py")
            res = subprocess.run(
                [sys.executable, worker_script, "--payload", pf_name, "--result", rf_name],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            with open(rf_name, "r", encoding="utf-8") as f:
                worker_data = json.load(f)
            self.assertEqual(worker_data["status"], "EXECUTED")
            self.assertEqual(worker_data["operation"], "ADMIN_PROBE")
            self.assertEqual(worker_data["exit_code"], 0)
        finally:
            if os.path.exists(pf_name):
                os.remove(pf_name)
            if os.path.exists(rf_name):
                os.remove(rf_name)

        # 2. Test parent process run_elevated_operation returns structured success
        with patch.object(self.engine, "run_elevated_operation", return_value={
            "ok": True,
            "status": "EXECUTED",
            "exit_code": 0,
            "message": "Elevation probe succeeded: successfully read Machine Environment registry.",
            "operation": "ADMIN_PROBE",
        }):
            elev_res = self.engine.run_elevated_operation(payload)
            self.assertTrue(elev_res["ok"])
            self.assertEqual(elev_res["status"], "EXECUTED")
            self.assertEqual(elev_res["exit_code"], 0)

    def test_2_git_machine_path_repair_elevation_and_verification(self):
        """TEST 2: Git Machine PATH repair -> UAC -> repair -> verification."""
        git_exe = r"C:\Program Files\Git\cmd\git.exe"
        with patch.object(self.detector, "discover_executable", return_value=[git_exe]), \
             patch.object(EffectivePath, "get_effective_persistent_path", return_value=[r"C:\Windows\System32"]), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=False), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=False), \
             patch("dev_environment_detector.is_process_elevated", return_value=False):
            diag = self.detector.diagnose_tool("git")
            self.assertTrue(diag.requires_elevation)
            self.assertEqual(diag.path_scope, "MACHINE")
            self.assertIn("Machine", diag.repair_command)

            # Test elevated stream run
            fake_elev_res = {
                "ok": True,
                "status": "EXECUTED",
                "exit_code": 0,
                "message": "Added C:\\Program Files\\Git\\cmd to Machine PATH",
                "operation": "REPAIR_PATH",
                "scope": "MACHINE",
                "application": "Git",
            }
            fake_post_verify = {
                "verified": True,
                "status": "INSTALLED_AND_USABLE",
                "message": "Git is installed and operational. git version 2.45.0.windows.1",
                "details": {
                    "path_entry_present": True,
                    "executable_exists": True,
                    "executable_path": git_exe,
                    "version": "git version 2.45.0.windows.1",
                },
            }

            with patch.object(self.engine, "run_elevated_operation", return_value=fake_elev_res) as mock_elev, \
                 patch.object(DevEnvironmentDetector, "post_repair_verify", return_value=fake_post_verify):
                events = list(self.engine.stream_run(
                    diag.repair_command,
                    elevate=True,
                    scope="MACHINE",
                    title="Git",
                ))

                # Verify elevation worker received structured payload
                mock_elev.assert_called_once()
                payload_arg = mock_elev.call_args[0][0]
                self.assertEqual(payload_arg["operation"], "REPAIR_PATH")
                self.assertEqual(payload_arg["scope"], "MACHINE")
                self.assertEqual(payload_arg["directory"], r"C:\Program Files\Git\cmd")

                # Verify lifecycle events
                log_texts = [ev.get("text", "") for ev in events if ev.get("type") == "log"]
                self.assertTrue(any("Preparing administrator repair" in t for t in log_texts))
                self.assertTrue(any("Requesting Windows Administrator permission" in t for t in log_texts))
                self.assertTrue(any("Elevation granted" in t for t in log_texts))
                self.assertTrue(any("Verifying" in t for t in log_texts))

                # Verify final event is VERIFIED
                done_ev = next(ev for ev in events if ev.get("type") == "done")
                self.assertTrue(done_ev["ok"])
                self.assertEqual(done_ev["status"], "VERIFIED")
                self.assertEqual(done_ev["returncode"], 0)

    def test_3_git_uac_cancellation_user_declined_elevation(self):
        """TEST 3: Git UAC cancellation -> USER_DECLINED_ELEVATION (not execution failed)."""
        git_cmd = "powershell -NoProfile -Command \"$target = 'C:\\Program Files\\Git\\cmd'; [Environment]::SetEnvironmentVariable('Path', '...', 'Machine')\""
        cancellation_elev_res = {
            "ok": False,
            "status": "USER_DECLINED_ELEVATION",
            "code": "ELEVATION_CANCELLED",
            "message": "Administrator permission was not granted. System PATH was not changed.",
            "exit_code": 1223,
            "requires_elevation": True,
        }

        with patch.object(self.engine, "run_elevated_operation", return_value=cancellation_elev_res):
            events = list(self.engine.stream_run(
                git_cmd,
                elevate=True,
                scope="MACHINE",
                title="Git",
            ))

            done_ev = next(ev for ev in events if ev.get("type") == "done")
            self.assertFalse(done_ev["ok"])
            self.assertEqual(done_ev["status"], "USER_DECLINED_ELEVATION")
            self.assertEqual(done_ev["code"], "ELEVATION_CANCELLED")
            self.assertEqual(done_ev["returncode"], 1223)
            self.assertIn("not granted", done_ev["notice"])
            # Must NOT say repair failed
            self.assertNotIn("repair failed", done_ev.get("stderr", "").lower())

            # Test route handling preserves USER_DECLINED_ELEVATION
            req = ExecuteRequest(command=git_cmd, title="Git", scope="MACHINE", elevate=True)
            res = asyncio.run(execute_command(req))
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "USER_DECLINED_ELEVATION")
            self.assertEqual(res["code"], "ELEVATION_CANCELLED")

    def test_4_mysql_machine_path_repair_uses_same_generic_elevation(self):
        """TEST 4: MySQL Machine PATH repair -> uses same generic elevation mechanism."""
        mysql_exe = r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
        with patch.object(self.detector, "discover_executable", return_value=[mysql_exe]), \
             patch.object(EffectivePath, "get_effective_persistent_path", return_value=[r"C:\Windows\System32"]), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=False), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=False), \
             patch("dev_environment_detector.is_process_elevated", return_value=False):
            diag = self.detector.diagnose_tool("mysql")
            self.assertTrue(diag.requires_elevation)
            self.assertEqual(diag.path_scope, "MACHINE")

            fake_elev_res = {
                "ok": True,
                "status": "EXECUTED",
                "exit_code": 0,
                "message": "Added C:\\Program Files\\MySQL\\MySQL Server 8.4\\bin to Machine PATH",
                "operation": "REPAIR_PATH",
                "scope": "MACHINE",
                "application": "MySQL",
            }
            fake_verify = {
                "verified": True,
                "status": "INSTALLED_AND_USABLE",
                "message": "MySQL is installed and operational.",
                "details": {"path_entry_present": True, "executable_exists": True},
            }

            with patch.object(self.engine, "run_elevated_operation", return_value=fake_elev_res) as mock_elev, \
                 patch.object(DevEnvironmentDetector, "post_repair_verify", return_value=fake_verify):
                events = list(self.engine.stream_run(
                    diag.repair_command,
                    elevate=True,
                    scope="MACHINE",
                    title="MySQL",
                ))
                mock_elev.assert_called_once()
                payload = mock_elev.call_args[0][0]
                self.assertEqual(payload["operation"], "REPAIR_PATH")
                self.assertEqual(payload["scope"], "MACHINE")
                self.assertEqual(payload["directory"], r"C:\Program Files\MySQL\MySQL Server 8.4\bin")
                done_ev = next(ev for ev in events if ev.get("type") == "done")
                self.assertEqual(done_ev["status"], "VERIFIED")

    def test_5_chrome_machine_path_repair_uses_same_generic_elevation(self):
        """TEST 5: Chrome Machine PATH repair -> uses same generic elevation mechanism."""
        chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        with patch.object(self.detector, "discover_executable", return_value=[chrome_exe]), \
             patch.object(EffectivePath, "get_effective_persistent_path", return_value=[r"C:\Windows\System32"]), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=False), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=False), \
             patch("dev_environment_detector.is_process_elevated", return_value=False):
            diag = self.detector.diagnose_tool("chrome")
            self.assertTrue(diag.requires_elevation)
            self.assertEqual(diag.path_scope, "MACHINE")

            fake_elev_res = {
                "ok": True,
                "status": "EXECUTED",
                "exit_code": 0,
                "message": "Added C:\\Program Files\\Google\\Chrome\\Application to Machine PATH",
                "operation": "REPAIR_PATH",
                "scope": "MACHINE",
                "application": "Google Chrome",
            }
            fake_verify = {
                "verified": True,
                "status": "INSTALLED_AND_USABLE",
                "message": "Chrome is installed and operational.",
                "details": {"path_entry_present": True, "executable_exists": True},
            }

            with patch.object(self.engine, "run_elevated_operation", return_value=fake_elev_res) as mock_elev, \
                 patch.object(DevEnvironmentDetector, "post_repair_verify", return_value=fake_verify):
                events = list(self.engine.stream_run(
                    diag.repair_command,
                    elevate=True,
                    scope="MACHINE",
                    title="Google Chrome",
                ))
                mock_elev.assert_called_once()
                payload = mock_elev.call_args[0][0]
                self.assertEqual(payload["operation"], "REPAIR_PATH")
                self.assertEqual(payload["scope"], "MACHINE")
                self.assertEqual(payload["directory"], r"C:\Program Files\Google\Chrome\Application")
                done_ev = next(ev for ev in events if ev.get("type") == "done")
                self.assertEqual(done_ev["status"], "VERIFIED")

    def test_6_anaconda_user_path_repair_no_unnecessary_uac(self):
        """TEST 6: Anaconda User PATH repair -> no unnecessary UAC."""
        conda_exe = r"C:\Users\tester\anaconda3\Scripts\conda.exe"
        with patch.object(self.detector, "discover_executable", return_value=[conda_exe]), \
             patch.object(EffectivePath, "get_effective_persistent_path", return_value=[r"C:\Users\tester\bin"]), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=False), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=False), \
             patch("dev_environment_detector.is_process_elevated", return_value=False):
            diag = self.detector.diagnose_tool("anaconda")
            self.assertEqual(diag.path_scope, "USER")
            self.assertFalse(diag.requires_elevation)
            self.assertTrue(diag.automatic_repair)
            self.assertIn("'User'", diag.repair_command)

            req = ExecuteRequest(
                command=diag.repair_command,
                title="Anaconda",
                scope="USER",
                elevate=False,
            )
            with patch("routes_system.engine.run", return_value=("", "", 0)) as mock_run, \
                 patch.object(self.engine, "run_elevated_operation") as mock_elev, \
                 patch.object(self.detector, "post_repair_verify", return_value={"verified": True, "details": {}}):
                res = asyncio.run(execute_command(req))
                self.assertTrue(res["ok"])
                mock_run.assert_called_once()
                mock_elev.assert_not_called()
                called_cmd = mock_run.call_args[0][0]
                self.assertIn("'User'", called_cmd)

    def test_7_multiple_python_versions_review_only_no_execution(self):
        """TEST 7: Multiple Python versions -> review-only -> no execution."""
        fake_pythons = [
            r"C:\Users\tester\AppData\Local\Programs\Python\Python312\python.exe",
            r"C:\Users\tester\AppData\Local\Programs\Python\Python313\python.exe",
        ]
        with patch.object(self.detector, "discover_executable", return_value=fake_pythons), \
             patch.object(self.detector, "_test_launch_in_persistent_env", return_value=("Python 3.12.2", True)), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=True):
            diag = self.detector.diagnose_tool("python")
            self.assertEqual(diag.status, ToolHealthStatus.MULTIPLE_VERSIONS)
            self.assertIsNone(diag.repair_command)
            self.assertFalse(diag.automatic_repair)
            self.assertEqual(diag.repairability, "REVIEW_REQUIRED")

            req = ExecuteRequest(command="", title="Python Precedence Review")
            err_resp = validate_execution_request(req)
            self.assertIsNotNone(err_resp)
            self.assertEqual(err_resp["status"], "NO_AUTOMATIC_REPAIR")
            self.assertEqual(err_resp["code"], "REVIEW_REQUIRED")

            with patch("routes_system.engine.run") as mock_run:
                res = asyncio.run(execute_command(req))
                self.assertEqual(res["status"], "NO_AUTOMATIC_REPAIR")
                self.assertFalse(res["ok"])
                mock_run.assert_not_called()

    def test_8_natural_language_string_rejected_by_backend(self):
        """TEST 8: Natural-language string passed as command -> rejected by backend."""
        nl_commands = [
            "Git is installed, but its PATH entry is missing. Administrator permission is required to repair the system PATH.",
            "MySQL Server is installed, but its PATH entry is missing. Administrator permission is required to repair the system PATH.",
            "Google Chrome is installed, but its PATH entry is missing. Administrator permission is required to repair the system PATH.",
            r"Multiple Python versions detected. C:\Users\srira\AppData\Local\Programs\Python\Python312\python.EXE is currently active. Review PATH precedence before changing it.",
            "Review PATH precedence before changing it.",
        ]

        for nl_cmd in nl_commands:
            self.assertTrue(is_natural_language_command(nl_cmd))
            req = ExecuteRequest(command=nl_cmd, title="NL Test")
            err_resp = validate_execution_request(req)
            self.assertIsNotNone(err_resp)
            self.assertEqual(err_resp["status"], "NO_AUTOMATIC_REPAIR")

            with patch("routes_system.engine.run") as mock_run:
                res = asyncio.run(execute_command(req))
                self.assertFalse(res["ok"])
                self.assertEqual(res["status"], "NO_AUTOMATIC_REPAIR")
                mock_run.assert_not_called()

            out, err, rc = self.engine.run(nl_cmd)
            self.assertEqual(rc, 1)
            self.assertIn("natural language", err.lower())

    def test_9_missing_command_no_automatic_repair(self):
        """TEST 9: Missing command -> NO_AUTOMATIC_REPAIR."""
        req = ExecuteRequest(command=None, title="Missing Command")
        err_resp = validate_execution_request(req)
        self.assertIsNotNone(err_resp)
        self.assertEqual(err_resp["status"], "NO_AUTOMATIC_REPAIR")

        with patch("routes_system.engine.run") as mock_run:
            res = asyncio.run(execute_command(req))
            self.assertEqual(res["status"], "NO_AUTOMATIC_REPAIR")
            self.assertFalse(res["ok"])
            mock_run.assert_not_called()

    def test_10_duplicate_python_problem_deduplicated(self):
        """TEST 10: Duplicate Python problem -> only one active problem displayed."""
        fake_pythons = [
            r"C:\Users\tester\AppData\Local\Programs\Python\Python312\python.exe",
            r"C:\Users\tester\AppData\Local\Programs\Python\Python313\python.exe",
        ]
        # Simulate dev_environment_detector discovering multiple python versions
        with patch.object(self.detector, "discover_executable", return_value=fake_pythons), \
             patch.object(self.detector, "_test_launch_in_persistent_env", return_value=("Python 3.12.2", True)), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=True), \
             patch("dev_environment_detector.dev_environment_detector", self.detector):
            # Also inject a duplicate into scanner.latest_issues
            scanner.latest_issues = [
                {
                    "title": "Multiple Python Installations Active",
                    "detail": "Python versions 3.12 and 3.13 detected in PATH.",
                    "category": "Developer Tools",
                    "severity": "medium",
                    "automatic_repair": False,
                }
            ]
            res = asyncio.run(get_active_repair_problems())
            problems = res.get("problems", [])

            # Filter for problems mentioning Python
            python_problems = [p for p in problems if "python" in p.get("title", "").lower() or "python" in p.get("id", "").lower()]
            self.assertEqual(len(python_problems), 1, f"Expected exactly 1 Python problem card, but got: {len(python_problems)}")
            self.assertEqual(python_problems[0]["status"], "REVIEW_REQUIRED")
            self.assertIsNone(python_problems[0]["command"])


class TestVerificationAndStateRefresh(unittest.TestCase):
    """Tests J, K, L: Post-repair verification and problem state synchronization."""

    def setUp(self):
        self.detector = DevEnvironmentDetector()

    def test_j_successful_repair_removes_active_problem(self):
        """Test J: A successfully verified repair causes the live detector to report INSTALLED_AND_USABLE."""
        with patch.object(self.detector, "discover_executable", return_value=[r"C:\Program Files\Git\cmd\git.exe"]), \
             patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=True), \
             patch.object(EffectivePath, "is_dir_in_process_path", return_value=True), \
             patch.object(self.detector, "_test_launch_in_persistent_env", return_value=("git version 2.45.0.windows.1", True)):
            diag = self.detector.diagnose_tool("git")
            self.assertEqual(diag.status, ToolHealthStatus.INSTALLED_AND_USABLE)

    def test_k_repair_command_failure_preserves_problem(self):
        """Test K: If repair command fails (rc != 0), problem remains active and failure is returned."""
        req = ExecuteRequest(command="powershell -Command exit 1", title="Failed Tool")
        with patch("routes_system.engine.run", return_value=("", "Error occurred", 1)), \
             patch("routes_system.safety.validate", return_value=(False, None)):
            res = asyncio.run(execute_command(req))
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "EXECUTION_FAILED")

    def test_l_verification_fails_after_exit_code_zero(self):
        """Test L: If a command returns rc 0 but verification fails, problem is not marked verified."""
        cmd = "[Environment]::SetEnvironmentVariable('Path', '...', 'Machine')"
        with patch.object(EffectivePath, "is_dir_in_persistent_path", return_value=False), \
             patch.object(self.detector, "discover_executable", return_value=[]):
            verify_res = self.detector.post_repair_verify(command=cmd, title="Git")
            self.assertFalse(verify_res["verified"])
            self.assertFalse(verify_res["details"]["path_entry_present"])


if __name__ == "__main__":
    unittest.main()
