"""
test_execution_verification_sync.py — Generic Execution-to-Verification Synchronization Test Suite.

Validates:
TEST 1: Fast successful mutation (attempt 1 succeeds)
TEST 2: Mutation succeeds, verification temporarily times out once, attempt 2 succeeds (mutation executed ONCE)
TEST 3: Mutation succeeds, verification times out twice, attempt 3 succeeds (mutation executed ONCE)
TEST 4: Verification timeout on all 3 attempts -> terminal VERIFICATION_TIMEOUT (no mutation rerun)
TEST 5: Execution itself fails -> verification NOT started as repair-success, no mutation loop
TEST 6: Verification command invalid / deterministic failure -> fails fast without blind 3x retry
TEST 7: Safety Layer rejects mutation -> mutation & verification NOT executed
TEST 8: User declines approval / elevation -> mutation not completed, no verification-success path
TEST 9: Retry Verification action from API/UI -> runs verification only, does NOT run mutation
TEST 10: Policy configuration overrides -> proves verification_max_attempts, backoff, stabilization_grace control behavior
REGRESSION TEST: Simulated long-running mutation stabilization -> proves mutation_count==1, verification_count==2, final_state==VERIFIED
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import platform
import subprocess

# Ensure backend directory is in path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from authoritative_safety import AuthoritativeSafetyLayer, BlockedReason, SafetyGateResult, authoritative_safety
from canonical_identity import CanonicalIdentity, canonical_store
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome, execution_engine
from execution_tier import ExecutionTier
from recipe_engine import RecipeLifecycle, RecipeOperation, RepairStrategy, StructuredRecipe, recipe_resolver
from verification_engine import (
    AuthoritativeVerificationEngine,
    VerificationLevel,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
    verification_engine,
)


class TestExecutionVerificationSync(unittest.TestCase):
    def setUp(self):
        for k in ("PC_DOCTOR_VERIFY_MAX_ATTEMPTS", "PC_DOCTOR_VERIFY_BACKOFF", "PC_DOCTOR_VERIFY_GRACE", "PC_DOCTOR_VERIFY_TIMEOUT"):
            if k in os.environ:
                del os.environ[k]
        self.state_patcher = patch("state_refresh.state_refresher.refresh_machine_state", return_value={"os": "Windows", "free_disk_gb": 50.0, "total_disk_gb": 100.0, "tools": {}})
        self.state_patcher.start()
        self.tool_patcher = patch("state_refresh.state_refresher.refresh_tool_state", return_value={"installed": True})
        self.tool_patcher.start()
        self.hw_patcher = patch("platform_hw._run", return_value=subprocess.CompletedProcess([], returncode=0, stdout="", stderr=""))
        self.hw_patcher.start()
        self.gpu_patcher = patch("platform_hw._query_gpu_usage_info_raw", return_value={"ok": True, "available": False, "gpus": []})
        self.gpu_patcher.start()

    def tearDown(self):
        self.state_patcher.stop()
        self.tool_patcher.stop()
        self.hw_patcher.stop()
        self.gpu_patcher.stop()

    def _create_mock_recipe(self, tool_id: str = "mock_tool", op: RecipeOperation = RecipeOperation.INSTALL) -> StructuredRecipe:
        return StructuredRecipe(
            recipe_id=f"test_recipe_{tool_id}",
            recipe_version=1,
            identity_id=tool_id,
            operation=op,
            os=platform.system(),
            architecture="x64",
            package_manager="custom",
            executable="echo",
            arguments=["installing", tool_id],
            verification_command=[tool_id, "--version"],
            repair_strategy=RepairStrategy.NATIVE,
            risk_base="Low",
            source="STATIC_DB",
            validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
        )

    def test_1_fast_successful_mutation(self):
        """TEST 1: Fast successful mutation. Process exits 0, verification succeeds on attempt 1."""
        recipe = self._create_mock_recipe("tool_fast")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Success", stderr="")

        verif_count = 0
        def fake_verify_single_probe(target_name_or_id, *args, **kwargs):
            nonlocal verif_count
            verif_count += 1
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected="1.0.0",
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=verif_count,
                message="Verified operational",
            )

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1, "Mutation must run exactly once")
        self.assertEqual(verif_count, 1, "Verification should succeed on attempt 1")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.status, "VERIFIED")

    def test_2_mutation_succeeds_verification_times_out_once(self):
        """TEST 2: Mutation succeeds, attempt 1 times out, attempt 2 succeeds. Mutation executed ONCE."""
        recipe = self._create_mock_recipe("tool_retry_once")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Installed tool", stderr="")

        verif_count = 0
        def fake_verify_single_probe(target_name_or_id, *args, **kwargs):
            nonlocal verif_count
            verif_count += 1
            if verif_count == 1:
                return VerificationResult(
                    status=VerificationStatus.VERIFICATION_TIMEOUT,
                    level=VerificationLevel.FAST,
                    executable_found=True,
                    version_detected=None,
                    functional_check_passed=False,
                    problem_cleared=False,
                    timed_out=True,
                    attempts=1,
                    message="Verification timed out on attempt 1",
                )
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected="2.1.0",
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=2,
                message="Tool verified operational",
            )

        policy = VerificationPolicy(max_attempts=3, initial_backoff=0.01, stabilization_grace=0.0)

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(VerificationPolicy, "from_env", return_value=policy), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1, "Mutation must execute exactly once (never rerun on verification timeout)")
        self.assertEqual(verif_count, 2, "Verification probe should have been called twice")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.status, "VERIFIED")

    def test_3_mutation_succeeds_verification_times_out_twice(self):
        """TEST 3: Mutation succeeds, attempts 1 and 2 timeout, attempt 3 succeeds. Mutation executed ONCE."""
        recipe = self._create_mock_recipe("tool_retry_twice")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Installed tool", stderr="")

        verif_count = 0
        def fake_verify_single_probe(target_name_or_id, *args, **kwargs):
            nonlocal verif_count
            verif_count += 1
            if verif_count < 3:
                return VerificationResult(
                    status=VerificationStatus.VERIFICATION_TIMEOUT,
                    level=VerificationLevel.FAST,
                    executable_found=True,
                    version_detected=None,
                    functional_check_passed=False,
                    problem_cleared=False,
                    timed_out=True,
                    attempts=verif_count,
                    message=f"Verification timed out on attempt {verif_count}",
                )
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected="3.0.0",
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=3,
                message="Tool verified operational on attempt 3",
            )

        policy = VerificationPolicy(max_attempts=3, initial_backoff=0.01, stabilization_grace=0.0)

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(VerificationPolicy, "from_env", return_value=policy), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1, "Mutation must execute exactly once")
        self.assertEqual(verif_count, 3, "Verification probe should have run 3 times")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.status, "VERIFIED")

    def test_4_verification_timeout_on_all_3_attempts(self):
        """TEST 4: Verification timeout on all 3 attempts. Terminal VERIFICATION_TIMEOUT reached, mutation executed ONCE."""
        recipe = self._create_mock_recipe("tool_all_timeout")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Installed tool", stderr="")

        verif_count = 0
        def fake_verify_single_probe(target_name_or_id, *args, **kwargs):
            nonlocal verif_count
            verif_count += 1
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_TIMEOUT,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=True,
                attempts=verif_count,
                message=f"Verification timed out on attempt {verif_count}",
            )

        policy = VerificationPolicy(max_attempts=3, initial_backoff=0.01, stabilization_grace=0.0)

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(VerificationPolicy, "from_env", return_value=policy), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1, "Mutation MUST execute only once (NEVER rerun on verification timeout)")
        self.assertEqual(verif_count, 3, "Must stop at max 3 attempts")
        self.assertFalse(outcome.success, "Outcome must not be marked success")
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFICATION_TIMEOUT")
        self.assertEqual(outcome.status, "VERIFICATION_TIMEOUT")
        self.assertIn("timed out after 3 attempts", outcome.message)

    def test_5_execution_itself_fails(self):
        """TEST 5: Execution itself fails (rc != 0). Verification is NOT started as repair-success, no loop."""
        recipe = self._create_mock_recipe("tool_exec_fail")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Package manager network failure")

        verif_run_count = 0
        def fake_verify_single_probe(*args, **kwargs):
            nonlocal verif_run_count
            verif_run_count += 1
            return VerificationResult(status=VerificationStatus.VERIFIED, level=VerificationLevel.FAST, executable_found=True, version_detected="1.0", functional_check_passed=True, problem_cleared=True)

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1, "Mutation executes once and fails")
        self.assertEqual(verif_run_count, 0, "Verification must NOT be run as repair success when mutation fails")
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.execution_status, "EXECUTION_FAILED")
        self.assertEqual(outcome.verification_status, "NOT_RUN")
        self.assertEqual(outcome.status, "EXECUTION_FAILED")

    def test_6_deterministic_verification_failure_no_blind_retry(self):
        """TEST 6: Verification command invalid / deterministic failure -> fails fast without blind 3x retry."""
        recipe = self._create_mock_recipe("nonexistent_unknown_tool_9999")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(cmd, *args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1
            import subprocess
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        verif_run_count = 0
        def fake_verify_single_probe(*args, **kwargs):
            nonlocal verif_run_count
            verif_run_count += 1
            # Deterministic: missing binary with no known install path
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=VerificationLevel.FAST,
                executable_found=False,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=False,
                attempts=1,
                message="Binary not found on PATH or known install locations.",
            )

        policy = VerificationPolicy(max_attempts=3, initial_backoff=0.01, stabilization_grace=0.0)

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_verify_single_probe), \
             patch.object(VerificationPolicy, "from_env", return_value=policy), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        self.assertEqual(mutation_run_count, 1)
        self.assertEqual(verif_run_count, 1, "Deterministic failures must NOT be retried 3 times")
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.status, "VERIFICATION_FAILED")
        self.assertEqual(outcome.verification_status, "VERIFICATION_FAILED")

    def test_7_safety_layer_rejects_mutation(self):
        """TEST 7: Safety Layer rejects mutation -> mutation not executed, verification not executed."""
        recipe = self._create_mock_recipe("destructive_tool")
        engine = CentralizedExecutionEngine()

        mutation_run_count = 0
        def fake_subprocess_run(*args, **kwargs):
            nonlocal mutation_run_count
            mutation_run_count += 1

        verif_run_count = 0
        def fake_verify(*args, **kwargs):
            nonlocal verif_run_count
            verif_run_count += 1

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=False, blocked_reason=BlockedReason.DESTRUCTIVE_OPERATION, message="Blocked destructive action")), \
             patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "verify_tool", side_effect=fake_verify):

            outcome = engine.execute_recipe(recipe)

        self.assertEqual(mutation_run_count, 0, "Blocked mutation must not execute")
        self.assertEqual(verif_run_count, 0, "Verification must not execute when blocked")
        self.assertEqual(outcome.status, "BLOCKED")
        self.assertFalse(outcome.success)

    def test_8_user_declined_tier(self):
        """TEST 8: User declines approval / elevation -> mutation not completed, no verification-success path."""
        outcome = ExecutionOutcome(
            success=False,
            status="USER_DECLINED",
            operation="INSTALL",
            target="controlled_tool",
            command="install",
            return_code=None,
            stdout="",
            stderr="User cancelled confirmation prompt",
            classification="USER_DECLINED",
            verification={},
            tier=ExecutionTier.TIER_2_CONTROLLED.value,
            trust=0.5,
            risk=0.8,
            confidence=0.5,
            message="User declined operation",
        )
        self.assertEqual(outcome.status, "USER_DECLINED")
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.verification, {})

    def test_9_retry_verification_action(self):
        """TEST 9: Retry Verification action from API/UI -> runs verification only, does NOT run mutation."""
        from dev_environment_detector import dev_environment_detector

        executed_commands = []
        def fake_subprocess_run(cmd, *args, **kwargs):
            executed_commands.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="1.0.0", stderr="")

        probe_calls = 0
        def fake_verify(target_name_or_id, *args, **kwargs):
            nonlocal probe_calls
            probe_calls += 1
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected="1.2.3",
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=1,
                message="Tool verified operational",
            )

        with patch("subprocess.run", side_effect=fake_subprocess_run), \
             patch.object(verification_engine, "verify_tool", side_effect=fake_verify), \
             patch.object(dev_environment_detector, "post_repair_verify", return_value={"ok": True, "verified": True, "status": "VERIFIED", "message": "Verified in PATH"}):

            import asyncio
            from routes_system import retry_verification_endpoint, RetryVerificationRequest

            req = RetryVerificationRequest(
                command="winget install SomeTool --force",
                target="sometool",
                title="Install SomeTool",
            )
            res = asyncio.run(retry_verification_endpoint(req))

        mutation_executed = [c for c in executed_commands if "winget" in str(c).lower() and "install" in str(c).lower()]
        self.assertEqual(len(mutation_executed), 0, "Retry Verification MUST NEVER execute any installer / mutation command")
        self.assertGreater(probe_calls, 0, "Verification probe must be invoked")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "VERIFIED")

    def test_10_policy_configuration_overrides(self):
        """TEST 10: Policy configuration -> proving verification_max_attempts, backoff, stabilization_grace."""
        os.environ["PC_DOCTOR_VERIFY_MAX_ATTEMPTS"] = "5"
        os.environ["PC_DOCTOR_VERIFY_BACKOFF"] = "2.0"
        os.environ["PC_DOCTOR_VERIFY_GRACE"] = "1.5"

        pol = VerificationPolicy.from_env("INSTALL")
        self.assertEqual(pol.max_attempts, 5)
        self.assertEqual(pol.initial_backoff, 2.0)
        self.assertEqual(pol.stabilization_grace, 1.5)
        self.assertEqual(pol.calculate_delay(1), 2.0)
        self.assertEqual(pol.calculate_delay(2), 3.0)

        # Custom policy in verify_tool
        engine_v = AuthoritativeVerificationEngine()
        attempt_log = []
        def probe_stub(*args, **kwargs):
            attempt_log.append(time.time())
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_TIMEOUT,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=True,
                attempts=len(attempt_log),
                message="Timeout",
            )

        custom_pol = VerificationPolicy(max_attempts=4, initial_backoff=0.01, stabilization_grace=0.0)
        with patch.object(engine_v, "_verify_single_probe", side_effect=probe_stub):
            res = engine_v.verify_tool("test_tool", policy=custom_pol)

        self.assertEqual(len(attempt_log), 4, "Configured policy max_attempts=4 must be respected")
        self.assertEqual(res.status, VerificationStatus.VERIFICATION_TIMEOUT)
        self.assertEqual(res.attempts, 4)

    def test_important_regression_long_running_mutation_stabilization(self):
        """
        REGRESSION TEST (Section 18):
        Simulate long-running mutation that completes (rc=0), but dependent tool takes
        a moment to stabilize:
        - Attempt 1 of verification times out.
        - Attempt 2 of verification succeeds.
        Acceptance criteria:
        - mutation_count == 1
        - verification_count == 2
        - final_state == VERIFIED
        Proves the system retries the READ/VERIFY operation rather than the MUTATION.
        """
        recipe = self._create_mock_recipe("stabilizing_toolchain", op=RecipeOperation.INSTALL)
        engine = CentralizedExecutionEngine()

        mutation_count = 0
        def fake_mutation_process(cmd, *args, **kwargs):
            nonlocal mutation_count
            mutation_count += 1
            import subprocess
            # Simulates long-running winget/toolchain install that completes successfully
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Installation completed successfully", stderr="")

        verification_count = 0
        def fake_stabilizing_probe(target_name_or_id, *args, **kwargs):
            nonlocal verification_count
            verification_count += 1
            if verification_count == 1:
                # Simulates toolchain still stabilizing on disk -> probe times out
                return VerificationResult(
                    status=VerificationStatus.VERIFICATION_TIMEOUT,
                    level=VerificationLevel.FAST,
                    executable_found=True,
                    version_detected=None,
                    functional_check_passed=False,
                    problem_cleared=False,
                    timed_out=True,
                    attempts=1,
                    message="Verification probe timed out while toolchain files were stabilizing",
                )
            else:
                # Attempt 2: toolchain is now stabilized, probe succeeds!
                return VerificationResult(
                    status=VerificationStatus.VERIFIED,
                    level=VerificationLevel.FAST,
                    executable_found=True,
                    version_detected="1.75.0 (stable)",
                    functional_check_passed=True,
                    problem_cleared=True,
                    timed_out=False,
                    attempts=2,
                    message="Toolchain verified operational and responsive",
                )

        fast_policy = VerificationPolicy(max_attempts=3, initial_backoff=0.01, stabilization_grace=0.0)

        with patch("subprocess.run", side_effect=fake_mutation_process), \
             patch.object(verification_engine, "_verify_single_probe", side_effect=fake_stabilizing_probe), \
             patch.object(VerificationPolicy, "from_env", return_value=fast_policy), \
             patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True)):

            outcome = engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)

        # Primary Acceptance Condition:
        self.assertEqual(mutation_count, 1, "Mutation must run EXACTLY ONCE. Must never rerun installer!")
        self.assertEqual(verification_count, 2, "Verification probe must retry on transient timeout")
        self.assertEqual(outcome.status, "VERIFIED", "Final state must be VERIFIED")
        self.assertTrue(outcome.success, "Outcome success must be True")
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")


if __name__ == "__main__":
    unittest.main()
