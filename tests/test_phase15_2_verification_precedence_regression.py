"""
tests/test_phase15_2_verification_precedence_regression.py
==========================================================
Phase 15.2 Regression Test: Verification Engine Authority Precedence.

Verifies that when authoritative verification_engine.verify_tool produces a result,
its verdict is strictly authoritative. A failed verification (VERIFICATION_FAILED)
must NEVER be overridden or masked as successful by generic post_repair_verify fallbacks.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution_engine import CentralizedExecutionEngine, ExecutionOutcome
from verification_engine import VerificationResult, VerificationStatus, VerificationLevel
from authoritative_safety import SafetyGateResult, authoritative_safety
from plan_freeze import resource_lock_mgr


class TestVerificationPrecedenceRegression(unittest.TestCase):
    """Ensures authoritative verification_engine.verify_tool cannot be overridden by post_repair_verify."""

    def setUp(self):
        self.engine = CentralizedExecutionEngine()
        resource_lock_mgr.clear_all()

    def tearDown(self):
        resource_lock_mgr.clear_all()

    def test_failed_authoritative_verification_not_overridden_by_generic_post_verify(self):
        """When verify_tool returns VERIFICATION_FAILED, execute_command must report failure despite post_verify=True."""
        mock_verif_res = VerificationResult(
            status=VerificationStatus.VERIFICATION_FAILED,
            level=VerificationLevel.CONTROLLED,
            executable_found=False,
            version_detected=None,
            functional_check_passed=False,
            problem_cleared=False,
            message="Tool not found in path",
            attempts=1,
            timed_out=False,
        )
        mock_post_verify = {
            "verified": True,  # generic fallback from dev_environment_detector
            "status": "VERIFIED",
            "message": "Command execution completed: echo test",
            "details": {},
        }

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"), \
             patch("subprocess.run") as mock_sp_run, \
             patch("execution_engine.verification_engine.verify_tool", return_value=mock_verif_res), \
             patch("dev_environment_detector.dev_environment_detector.post_repair_verify", return_value=mock_post_verify):
            
            mock_sp_run.return_value = MagicMock(returncode=0, stdout="success output", stderr="")
            
            outcome = self.engine.execute_command(
                command="echo test",
                target="git",
                operation="INSTALL",
                source="STATIC_DB",
                approved=True,
            )

            self.assertEqual(outcome.return_code, 0)
            self.assertFalse(outcome.success, "Outcome success must be False when authoritative verification fails")
            self.assertEqual(outcome.status, "VERIFICATION_FAILED")
            self.assertEqual(outcome.verification_status, "VERIFICATION_FAILED")

    def test_stream_failed_authoritative_verification_not_overridden(self):
        """In streaming execution, failed authoritative verification must result in VERIFICATION_FAILED."""
        mock_verif_res = VerificationResult(
            status=VerificationStatus.VERIFICATION_FAILED,
            level=VerificationLevel.CONTROLLED,
            executable_found=False,
            version_detected=None,
            functional_check_passed=False,
            problem_cleared=False,
            message="Tool not found in path",
            attempts=1,
            timed_out=False,
        )
        mock_post_verify = {
            "verified": True,
            "status": "VERIFIED",
            "message": "Command execution completed: echo test",
            "details": {},
        }

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"), \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution_engine.verification_engine.verify_tool", return_value=mock_verif_res), \
             patch("dev_environment_detector.dev_environment_detector.post_repair_verify", return_value=mock_post_verify):
            
            proc_mock = MagicMock()
            proc_mock.poll.side_effect = [None, 0]
            proc_mock.returncode = 0
            proc_mock.stdout.readline.side_effect = ["line 1\n", ""]
            proc_mock.stderr.readline.side_effect = [""]
            mock_popen.return_value = proc_mock

            events = list(self.engine.stream_execute_command(
                command="echo test",
                target="git",
                operation="INSTALL",
                source="STATIC_DB",
                approved=True,
            ))

            done_events = [e for e in events if e.get("type") == "done"]
            self.assertTrue(len(done_events) > 0)
            last_done = done_events[-1]
            self.assertFalse(last_done.get("ok", True), "Done event ok must be False")
            self.assertEqual(last_done.get("status"), "VERIFICATION_FAILED")


if __name__ == "__main__":
    unittest.main()

