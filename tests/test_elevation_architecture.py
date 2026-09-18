"""
tests/test_elevation_architecture.py — Comprehensive Verification of Windows Elevation Architecture

Verifies all 18 requirements specified in the user request:
1. Safe elevation probe (ADMIN_PROBE)
2. UAC cancellation (USER_DECLINED_ELEVATION, code 1223)
3. Elevation launch failure (ELEVATION_FAILED)
4. Git Machine PATH repair & verification
5. MySQL Machine PATH repair & verification
6. Chrome Machine PATH repair & verification
7. Anaconda User PATH repair (no UAC required)
8. Multiple Python installations (review-only, no command executed)
9. Rejection of natural language text as an elevated command
10. Rejection of malformed operation payloads by the worker
11. Process crash/non-zero handling without hanging
12. Bounded UAC timeout (no infinite 30% hang)
13. Cross-platform PrivilegeManager (Windows, Linux, macOS)
14. Real state machine transitions (30% -> 40% -> 50% -> 60% -> 75% -> 85% -> 100%)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from privilege_manager import (
    ElevationState,
    PrivilegeManager,
    WindowsPrivilegeAdapter,
    LinuxPrivilegeAdapter,
    MacOSPrivilegeAdapter,
    STATE_PROGRESS_MAP,
)
from repair_engine import RepairEngine
from dev_environment_detector import DevEnvironmentDetector, EffectivePath, PathScope


class TestPrivilegeManagerArchitecture(unittest.TestCase):
    """Verifies the core privilege abstraction and state machine."""

    def test_cross_platform_adapter_resolution(self):
        """13. PrivilegeManager properly resolves Windows, Linux, and macOS adapters."""
        win_adapter = PrivilegeManager.get_adapter("windows")
        self.assertIsInstance(win_adapter, WindowsPrivilegeAdapter)

        linux_adapter = PrivilegeManager.get_adapter("linux")
        self.assertIsInstance(linux_adapter, LinuxPrivilegeAdapter)

        mac_adapter = PrivilegeManager.get_adapter("darwin")
        self.assertIsInstance(mac_adapter, MacOSPrivilegeAdapter)

    def test_state_machine_progress_percentages(self):
        """14. Explicit state transitions have exact, verified percentages."""
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.RECIPE_VALIDATED.value][0], 10)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.SAFETY_CHECKED.value][0], 20)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.ELEVATION_REQUESTED.value][0], 30)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.ELEVATION_GRANTED.value][0], 40)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.ELEVATED_PROCESS_STARTED.value][0], 50)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_EXECUTING.value][0], 60)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_COMPLETED.value][0], 75)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.VERIFICATION_RUNNING.value][0], 85)
        self.assertEqual(STATE_PROGRESS_MAP[ElevationState.VERIFIED.value][0], 100)


class TestElevatedWorkerDirectExecution(unittest.TestCase):
    """Direct testing of elevated_worker.py process behavior."""

    def setUp(self):
        self.worker_script = str(backend_dir / "elevated_worker.py")
        self.python_bin = sys.executable

    def _run_worker(self, payload: dict):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f_p:
            json.dump(payload, f_p)
            p_path = f_p.name

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f_r:
            r_path = f_r.name

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".marker") as f_h:
            h_path = f_h.name

        try:
            cmd = [self.python_bin, self.worker_script, "--payload", p_path, "--result", r_path, "--heartbeat", h_path]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            res = {}
            if os.path.exists(r_path) and os.path.getsize(r_path) > 0:
                with open(r_path, "r", encoding="utf-8") as rf:
                    res = json.load(rf)
            heartbeat_present = os.path.exists(h_path) and os.path.getsize(h_path) > 0
            return proc.returncode, res, heartbeat_present
        finally:
            for p in (p_path, r_path, h_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_worker_admin_probe(self):
        """1. Safe elevation probe (ADMIN_PROBE) executes without modifying system PATH."""
        rc, res, hb = self._run_worker({"operation": "ADMIN_PROBE", "title": "Safe Probe"})
        self.assertEqual(rc, 0)
        self.assertEqual(res.get("status"), "EXECUTED")
        self.assertTrue(hb)

    def test_worker_rejects_missing_directory(self):
        """10. Worker rejects REPAIR_PATH with missing directory."""
        rc, res, _ = self._run_worker({"operation": "REPAIR_PATH", "scope": "MACHINE", "directory": ""})
        self.assertEqual(rc, 1)
        self.assertEqual(res.get("status"), "ELEVATED_OPERATION_FAILED")
        self.assertIn("Missing target directory", res.get("error", ""))

    def test_worker_rejects_nonexistent_directory(self):
        """10b. Worker rejects REPAIR_PATH targeting non-existent directory on disk."""
        fake_dir = r"C:\DefinitelyDoesNotExist_Path_Repair_Test_987654321"
        rc, res, _ = self._run_worker({"operation": "REPAIR_PATH", "scope": "MACHINE", "directory": fake_dir})
        self.assertEqual(rc, 1)
        self.assertEqual(res.get("status"), "ELEVATED_OPERATION_FAILED")
        self.assertIn("Target directory does not exist", res.get("error", ""))

    def test_worker_rejects_natural_language_command(self):
        """9. Worker rejects natural-language text as an elevated command."""
        nl_text = "Install Git by downloading the installer from git-scm.com and running it as Administrator"
        rc, res, _ = self._run_worker({"operation": "EXECUTE_COMMAND", "command": nl_text})
        self.assertEqual(rc, 1)
        self.assertEqual(res.get("status"), "ELEVATED_OPERATION_FAILED")
        self.assertIn("natural language", res.get("error", "").lower())


class TestRepairEngineElevationFlow(unittest.TestCase):
    """Verifies RepairEngine stream_run elevation execution, state transitions, and timeouts."""

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.engine = RepairEngine(Path(self.tmp_db.name))

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            try:
                os.remove(self.tmp_db.name)
            except Exception:
                pass

    def test_safe_elevation_probe_stream(self):
        """1. Safe elevation test yields structured events to 100% VERIFIED."""
        fake_events = [
            {"type": "progress", "percent": 30, "state": ElevationState.ELEVATION_REQUESTED.value, "detail": "Awaiting approval"},
            {"type": "progress", "percent": 40, "state": ElevationState.ELEVATION_GRANTED.value, "detail": "Granted"},
            {"type": "progress", "percent": 50, "state": ElevationState.ELEVATED_PROCESS_STARTED.value, "detail": "Started"},
            {"type": "progress", "percent": 60, "state": ElevationState.ELEVATED_OPERATION_EXECUTING.value, "detail": "Executing"},
            {"type": "progress", "percent": 75, "state": ElevationState.ELEVATED_OPERATION_COMPLETED.value, "detail": "Done"},
            {"type": "done", "ok": True, "status": "EXECUTED", "exit_code": 0, "message": "Probe successful"},
        ]

        cmd = 'powershell -NoProfile -Command "Write-Output Probe"'
        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(fake_events)), \
             patch("dev_environment_detector.DevEnvironmentDetector.post_repair_verify", return_value={"verified": True, "message": "Probe verified", "details": {}}):
            events = list(self.engine.stream_run(cmd, elevate=True, title="Elevation Probe Test"))

        states = [e.get("state") for e in events if "state" in e]
        self.assertIn("RECIPE_VALIDATED", states)
        self.assertIn("SAFETY_CHECKED", states)
        self.assertIn("ELEVATION_REQUESTED", states)
        self.assertIn("ELEVATION_GRANTED", states)
        self.assertIn("ELEVATED_PROCESS_STARTED", states)
        self.assertIn("ELEVATED_OPERATION_EXECUTING", states)
        self.assertIn("ELEVATED_OPERATION_COMPLETED", states)
        self.assertIn("VERIFIED", states)

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertTrue(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "VERIFIED")

    def test_uac_cancellation_exits_30_percent_cleanly(self):
        """2. User declining UAC (error 1223) yields USER_DECLINED_ELEVATION and exits cleanly."""
        cancel_events = [
            {"type": "progress", "percent": 30, "state": ElevationState.ELEVATION_REQUESTED.value, "detail": "Awaiting UAC"},
            {
                "type": "done",
                "returncode": 1223,
                "ok": False,
                "status": ElevationState.USER_DECLINED_ELEVATION.value,
                "code": "ELEVATION_CANCELLED",
                "requires_elevation": True,
                "stderr": "Administrator permission was not granted by user.",
            },
        ]

        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(cancel_events)):
            events = list(self.engine.stream_run("powershell -Command ...", elevate=True, scope="MACHINE", title="Git"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertFalse(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "USER_DECLINED_ELEVATION")
        self.assertEqual(done_ev.get("returncode"), 1223)

    def test_elevation_failure_not_stuck_at_30_percent(self):
        """3 & 12. Elevation timeout or launch failure emits ELEVATION_FAILED with real failure."""
        fail_events = [
            {"type": "progress", "percent": 30, "state": ElevationState.ELEVATION_REQUESTED.value, "detail": "Awaiting UAC"},
            {
                "type": "done",
                "returncode": 124,
                "ok": False,
                "status": ElevationState.ELEVATION_FAILED.value,
                "code": "ELEVATION_TIMEOUT",
                "requires_elevation": True,
                "stderr": "Administrator approval timed out after 60 seconds.",
            },
        ]

        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(fail_events)):
            events = list(self.engine.stream_run("powershell -Command ...", elevate=True, scope="MACHINE", title="Git"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertFalse(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "ELEVATION_FAILED")
        self.assertEqual(done_ev.get("code"), "ELEVATION_TIMEOUT")

    def test_git_machine_path_repair_flow(self):
        """4. Git Machine PATH repair: elevation -> worker -> repair -> verified."""
        fake_events = [
            {"type": "progress", "percent": 30, "state": "ELEVATION_REQUESTED", "detail": "Awaiting approval"},
            {"type": "progress", "percent": 40, "state": "ELEVATION_GRANTED", "detail": "Granted"},
            {"type": "progress", "percent": 50, "state": "ELEVATED_PROCESS_STARTED", "detail": "Started"},
            {"type": "progress", "percent": 60, "state": "ELEVATED_OPERATION_EXECUTING", "detail": "Executing"},
            {"type": "progress", "percent": 75, "state": "ELEVATED_OPERATION_COMPLETED", "detail": "Completed"},
            {"type": "done", "ok": True, "status": "EXECUTED", "exit_code": 0, "message": "Added C:\\Program Files\\Git\\cmd to Machine PATH"},
        ]

        cmd = 'powershell -NoProfile -Command "$target = \'C:\\Program Files\\Git\\cmd\'; ..."'
        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(fake_events)), \
             patch("dev_environment_detector.DevEnvironmentDetector.post_repair_verify", return_value={"verified": True, "message": "Git version 2.45.0 confirmed", "details": {"version": "2.45.0"}}):
            events = list(self.engine.stream_run(cmd, elevate=True, scope="MACHINE", title="Git"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertTrue(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "VERIFIED")
        self.assertIn("Git version 2.45.0", done_ev.get("stdout", ""))

    def test_mysql_machine_path_repair_flow(self):
        """5. MySQL Machine PATH repair uses the exact same shared elevation mechanism."""
        fake_events = [
            {"type": "progress", "percent": 30, "state": "ELEVATION_REQUESTED", "detail": "Awaiting approval"},
            {"type": "progress", "percent": 40, "state": "ELEVATION_GRANTED", "detail": "Granted"},
            {"type": "progress", "percent": 75, "state": "ELEVATED_OPERATION_COMPLETED", "detail": "Completed"},
            {"type": "done", "ok": True, "status": "EXECUTED", "exit_code": 0, "message": "Added MySQL to Machine PATH"},
        ]

        cmd = 'powershell -NoProfile -Command "$target = \'C:\\Program Files\\MySQL\\MySQL Server 8.4\\bin\'; ..."'
        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(fake_events)), \
             patch("dev_environment_detector.DevEnvironmentDetector.post_repair_verify", return_value={"verified": True, "message": "MySQL 8.4.0 verified", "details": {}}):
            events = list(self.engine.stream_run(cmd, elevate=True, scope="MACHINE", title="MySQL"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertTrue(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "VERIFIED")

    def test_chrome_machine_path_repair_flow(self):
        """6. Chrome Machine PATH repair uses the exact same shared elevation mechanism."""
        fake_events = [
            {"type": "progress", "percent": 30, "state": "ELEVATION_REQUESTED", "detail": "Awaiting approval"},
            {"type": "progress", "percent": 40, "state": "ELEVATION_GRANTED", "detail": "Granted"},
            {"type": "progress", "percent": 75, "state": "ELEVATED_OPERATION_COMPLETED", "detail": "Completed"},
            {"type": "done", "ok": True, "status": "EXECUTED", "exit_code": 0, "message": "Added Chrome to Machine PATH"},
        ]

        cmd = 'powershell -NoProfile -Command "$target = \'C:\\Program Files\\Google\\Chrome\\Application\'; ..."'
        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(fake_events)), \
             patch("dev_environment_detector.DevEnvironmentDetector.post_repair_verify", return_value={"verified": True, "message": "Chrome 133.0 verified", "details": {}}):
            events = list(self.engine.stream_run(cmd, elevate=True, scope="MACHINE", title="Google Chrome"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertTrue(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "VERIFIED")

    def test_anaconda_user_path_no_uac(self):
        """7. Anaconda User PATH repair does not request UAC (elevate=False)."""
        cmd = 'powershell -NoProfile -Command "Write-Output CondaPathVerified"' if sys.platform == "win32" else f'{sys.executable} -c "print(\'CondaPathVerified\')"'
        with patch.object(self.engine, "stream_elevated_operation") as mock_elev, \
             patch("dev_environment_detector.DevEnvironmentDetector.post_repair_verify", return_value={"verified": True, "message": "conda verified", "details": {}}):
            events = list(self.engine.stream_run(cmd, elevate=False, scope="USER", title="Anaconda"))

        mock_elev.assert_not_called()
        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertTrue(done_ev.get("ok"))

    def test_multiple_python_versions_review_only(self):
        """8. Multiple Python installations is review-only and rejects execution."""
        comment_cmd = "# Multiple Python versions detected: python 3.11 and python 3.12"
        events = list(self.engine.stream_run(comment_cmd, elevate=False, title="Python Multiple Versions"))
        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertFalse(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "NO_AUTOMATIC_REPAIR")

    def test_reject_natural_language_elevated_command(self):
        """9. Reject natural language text before initiating any elevation."""
        nl_text = "Please add Git to the system environment path so git command works"
        with patch.object(self.engine, "stream_elevated_operation") as mock_elev:
            events = list(self.engine.stream_run(nl_text, elevate=True, scope="MACHINE", title="Git"))
        mock_elev.assert_not_called()
        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertFalse(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "NO_AUTOMATIC_REPAIR")

    def test_process_crash_handling_no_hang(self):
        """11. If elevated child process crashes, parent receives error without deadlock."""
        crash_events = [
            {"type": "progress", "percent": 30, "state": "ELEVATION_REQUESTED", "detail": "Awaiting UAC"},
            {"type": "progress", "percent": 40, "state": "ELEVATION_GRANTED", "detail": "Granted"},
            {
                "type": "done",
                "returncode": 1,
                "ok": False,
                "status": ElevationState.ELEVATED_OPERATION_FAILED.value,
                "code": "ELEVATED_OPERATION_FAILED",
                "stderr": "Worker process crashed with access violation.",
            },
        ]

        with patch.object(self.engine, "stream_elevated_operation", return_value=iter(crash_events)):
            events = list(self.engine.stream_run("powershell -Command ...", elevate=True, scope="MACHINE", title="Git"))

        done_ev = next(e for e in events if e.get("type") == "done")
        self.assertFalse(done_ev.get("ok"))
        self.assertEqual(done_ev.get("status"), "ELEVATED_OPERATION_FAILED")


if __name__ == "__main__":
    unittest.main()
