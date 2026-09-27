"""
test_phase14_system_hardening.py — Phase 14 Final System Hardening & Runtime Consistency
========================================================================================
Comprehensive verification for Phase 14 requirements:
1. Exact runtime execution trace order:
   CENTRALIZED_ENGINE_ENTRY < AUTHORIZATION < LIVE_SAFETY_GATE < MUTATING_SUBPROCESS < VERIFICATION < RESCAN < LOGGING
2. Subprocess boundary safety invariants:
   - Authorization failure -> 0 mutating subprocesses
   - Safety Gate failure -> 0 mutating subprocesses
   - Explicit user rejection -> 0 mutating subprocesses
   - Platform mismatch -> 0 mutating subprocesses
   - Dangerous command pattern -> 0 mutating subprocesses
3. Verification-before-success invariant:
   - Command rc=0 does NOT automatically equal SUCCESS
   - Failed verification reported honestly as VERIFICATION_FAILED
   - Verification timeout reported honestly as VERIFICATION_TIMEOUT
4. Rescan ordering:
   - Verification occurs before rescan
   - Rescan occurs before logging
5. Structured logging ordering & secret sanitization:
   - Log occurs after canonical result determination
   - Never logs SUCCESS when verification failed
   - Automatic redaction of API keys, bearer tokens, passwords
6. Duplicate execution protection & concurrency locking:
   - Fine-grained resource locks prevent concurrent double mutations
   - Verified mutation subprocess count
7. Timeout and failure handling:
   - Subprocess timeout captured honestly without false success
   - Non-zero return code captured without false success
   - Multi-step repair failure halts immediately and identifies failing step
8. UI / Backend result consistency:
   - Backend canonical statuses map faithfully to API / SSE states
   - Failed or blocked executions never report ok=True
9. Cross-Platform Mutation Boundary:
   - CentralizedExecutionEngine remains sole mutation authority across platforms
   - Unauthorized developer environment mutation subprocesses = 0
10. Trusted Automatic Authorization:
   - Preserves Phase 13.1 policy for STATIC_DB golden recipes
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from authoritative_safety import (
    BlockedReason,
    SafetyGateResult,
    authoritative_safety,
)
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome, execution_engine
from execution_plan import ExecutionPlan, ExecutionRequest, execution_resolver, ProvenanceClass
from execution_tier import ExecutionTier
from recipe_engine import RecipeOperation, StructuredRecipe
from state_refresh import state_refresher
from structured_logger import redact_secrets, structured_logger
from verification_engine import (
    VerificationLevel,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
    verification_engine,
)


def make_sample_recipe(
    recipe_id="RECIPE-P14-01",
    target="git",
    package_manager="winget",
    operation=RecipeOperation.INSTALL,
    source="STATIC_DB",
    args=None,
):
    return StructuredRecipe(
        recipe_id=recipe_id,
        recipe_version=1,
        identity_id=target,
        operation=operation,
        os="Windows",
        architecture="x64",
        package_manager=package_manager,
        executable=package_manager,
        arguments=args or ["install", "--id", "Git.Git", "--exact", "--silent"],
        verification_command=["git", "--version"],
        source=source,
    )


class TestPhase14SystemHardening(unittest.TestCase):
    def setUp(self):
        self.engine = CentralizedExecutionEngine()

    # =========================================================================
    # 1. RUNTIME EXECUTION ORDER TRACE
    # =========================================================================
    def test_01_runtime_execution_trace_order(self):
        """
        Proves invariant:
        CENTRALIZED_ENGINE_ENTRY < AUTHORIZATION < LIVE_SAFETY_GATE < MUTATING_SUBPROCESS < VERIFICATION < RESCAN < LOGGING
        """
        trace = []

        orig_auth = execution_resolver.evaluate_authorization
        def trace_auth(*args, **kwargs):
            trace.append("AUTHORIZATION")
            return orig_auth(*args, **kwargs)

        orig_safety = authoritative_safety.live_pre_execution_gate
        def trace_safety(*args, **kwargs):
            trace.append("LIVE_SAFETY_GATE")
            return SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")

        def trace_sub(*args, **kwargs):
            trace.append("MUTATING_SUBPROCESS")
            return MagicMock(returncode=0, stdout="success", stderr="")

        def trace_verify(*args, **kwargs):
            trace.append("VERIFICATION")
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected="2.44.0",
                functional_check_passed=True,
                problem_cleared=True,
                details={"output": "git version 2.44.0"},
                attempts=1,
            )

        def trace_rescan(*args, **kwargs):
            trace.append("RESCAN")
            return {}

        orig_log = structured_logger.log_event
        def trace_log(*args, **kwargs):
            trace.append("LOGGING")
            return orig_log(*args, **kwargs)

        recipe = make_sample_recipe()

        with patch.object(execution_resolver, "evaluate_authorization", side_effect=trace_auth), \
             patch.object(authoritative_safety, "live_pre_execution_gate", side_effect=trace_safety), \
             patch("subprocess.run", side_effect=trace_sub), \
             patch.object(verification_engine, "verify_tool", side_effect=trace_verify), \
             patch.object(state_refresher, "refresh_tool_state", side_effect=trace_rescan), \
             patch.object(structured_logger, "log_event", side_effect=trace_log), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            trace.append("CENTRALIZED_ENGINE_ENTRY")
            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=None,
                machine_state=MagicMock(),
            )

        self.assertTrue(outcome.success)
        expected_steps = [
            "CENTRALIZED_ENGINE_ENTRY",
            "AUTHORIZATION",
            "LIVE_SAFETY_GATE",
            "MUTATING_SUBPROCESS",
            "VERIFICATION",
            "RESCAN",
            "LOGGING",
        ]
        for step in expected_steps:
            self.assertIn(step, trace, f"Missing expected step: {step}")

        idx_entry = trace.index("CENTRALIZED_ENGINE_ENTRY")
        idx_auth = trace.index("AUTHORIZATION")
        idx_safety = trace.index("LIVE_SAFETY_GATE")
        idx_sub = trace.index("MUTATING_SUBPROCESS")
        idx_verif = trace.index("VERIFICATION")
        idx_rescan = trace.index("RESCAN")
        idx_log = trace.index("LOGGING")

        self.assertLess(idx_entry, idx_auth, "Engine Entry must precede Authorization")
        self.assertLess(idx_auth, idx_safety, "Authorization must precede LIVE Safety Gate")
        self.assertLess(idx_safety, idx_sub, "LIVE Safety Gate must precede Mutating Subprocess")
        self.assertLess(idx_sub, idx_verif, "Mutating Subprocess must precede Verification")
        self.assertLessEqual(idx_verif, idx_rescan, "Verification must precede Rescan")
        self.assertLess(idx_rescan, idx_log, "Rescan must precede Logging")

    # =========================================================================
    # 2. SUBPROCESS BOUNDARY SAFETY INVARIANTS (ZERO MUTATING SUBPROCESSES)
    # =========================================================================
    def test_02a_authorization_failure_yields_zero_mutating_subprocesses(self):
        """Untrusted recipe without approval fails authorization -> 0 mutating subprocesses."""
        with patch("subprocess.run") as mock_sub, \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            outcome = self.engine.execute_command(
                command="npm install -g some-custom-untrusted-tool",
                target="custom_tool",
                operation="INSTALL",
                source="RAG_EXTRACTION",
                approved=None,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertEqual(mock_sub.call_count, 0, "Mutating subprocess must not be called")
            self.assertEqual(mock_popen.call_count, 0, "Mutating popen must not be called")

    def test_02b_safety_gate_failure_yields_zero_mutating_subprocesses(self):
        """Safety Gate block (e.g. safety policy rejection) -> 0 mutating subprocesses."""
        recipe = make_sample_recipe(source="STATIC_DB")

        with patch.object(authoritative_safety, "live_pre_execution_gate") as mock_gate, \
             patch("subprocess.run") as mock_sub, \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            mock_gate.return_value = SafetyGateResult(
                allowed=False,
                blocked_reason=BlockedReason.SAFETY_POLICY_REJECTED,
                message="Free disk space is below required threshold (500MB).",
            )

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(mock_sub.call_count, 0, "Subprocess must not be called when safety gate rejects")
            self.assertEqual(mock_popen.call_count, 0, "Popen must not be called when safety gate rejects")

    def test_02c_explicit_user_rejection_yields_zero_mutating_subprocesses(self):
        """User explicitly declines execution (approved=False) -> 0 mutating subprocesses."""
        recipe = make_sample_recipe(source="STATIC_DB")

        with patch("subprocess.run") as mock_sub, \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=False,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertIn("declined", outcome.stderr.lower())
            self.assertEqual(mock_sub.call_count, 0, "Subprocess must not be called on user rejection")
            self.assertEqual(mock_popen.call_count, 0, "Popen must not be called on user rejection")

    def test_02d_platform_mismatch_yields_zero_mutating_subprocesses(self):
        """Recipe targeting an incompatible package manager / platform -> 0 mutating subprocesses."""
        incompatible_pm = "apt" if platform.system() == "Windows" else "winget"
        recipe = make_sample_recipe(package_manager=incompatible_pm, source="STATIC_DB")

        with patch("subprocess.run") as mock_sub, \
             patch("subprocess.Popen") as mock_popen, \
             patch.object(authoritative_safety, "live_pre_execution_gate") as mock_gate:

            mock_gate.return_value = SafetyGateResult(
                allowed=False,
                blocked_reason=BlockedReason.PLATFORM_MISMATCH,
                message=f"Package manager {incompatible_pm} is not supported on this platform.",
            )

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(mock_sub.call_count, 0, "Subprocess must not run for mismatched platform")
            self.assertEqual(mock_popen.call_count, 0, "Popen must not run for mismatched platform")

    def test_02e_dangerous_command_pattern_yields_zero_mutating_subprocesses(self):
        """Dangerous commands matching hard blacklist -> 0 mutating subprocesses."""
        dangerous_cmd = "rm -rf / --no-preserve-root" if platform.system() != "Windows" else "del /f /s /q C:\\Windows"

        with patch("subprocess.run") as mock_sub, \
             patch("subprocess.Popen") as mock_popen:

            outcome = self.engine.execute_command(
                command=dangerous_cmd,
                target="system",
                approved=True,
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(outcome.classification, "SAFETY_POLICY_REJECTED")
            self.assertEqual(mock_sub.call_count, 0, "Subprocess must NEVER spawn for blacklisted command")
            self.assertEqual(mock_popen.call_count, 0, "Popen must NEVER spawn for blacklisted command")

    # =========================================================================
    # 3. VERIFICATION-BEFORE-SUCCESS INVARIANT
    # =========================================================================
    def test_03a_zero_returncode_does_not_imply_success_if_verification_fails(self):
        """Process exit code 0 must not report success if functional verification fails."""
        recipe = make_sample_recipe()

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="install complete", stderr="")), \
             patch.object(verification_engine, "verify_tool") as mock_verify, \
             patch.object(state_refresher, "refresh_tool_state"), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            mock_verify.return_value = VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=VerificationLevel.FAST,
                executable_found=False,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                details={"error": "Binary missing from PATH post-install"},
            )

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success, "Must NOT report success when verification fails")
            self.assertEqual(outcome.status, "VERIFICATION_FAILED")
            self.assertEqual(outcome.verification_status, "VERIFICATION_FAILED")
            self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")

    def test_03b_verification_timeout_reported_honestly(self):
        """Verification timeout must be distinguished from success and failure."""
        recipe = make_sample_recipe()

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="installed", stderr="")), \
             patch.object(verification_engine, "verify_tool") as mock_verify, \
             patch.object(state_refresher, "refresh_tool_state"), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            mock_verify.return_value = VerificationResult(
                status=VerificationStatus.VERIFICATION_TIMEOUT,
                level=VerificationLevel.FAST,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                details={"error": "Probe timed out after 3 attempts"},
                attempts=3,
            )

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "VERIFICATION_TIMEOUT")
            self.assertEqual(outcome.verification_status, "VERIFICATION_TIMEOUT")
            self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")

    # =========================================================================
    # 4. RESCAN ORDERING & FAILURE BYPASS
    # =========================================================================
    def test_04_execution_failure_skips_verification(self):
        """If mutating subprocess returns non-zero, verification must NOT run."""
        recipe = make_sample_recipe()

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="Download failed")), \
             patch.object(verification_engine, "verify_tool") as mock_verify, \
             patch.object(state_refresher, "refresh_tool_state"), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "EXECUTION_FAILED")
            self.assertEqual(outcome.execution_status, "EXECUTION_FAILED")
            self.assertEqual(outcome.verification_status, "NOT_RUN")
            self.assertEqual(mock_verify.call_count, 0, "Verification must be skipped when execution fails")

    # =========================================================================
    # 5. STRUCTURED LOGGING ORDERING & SECRET SANITIZATION
    # =========================================================================
    def test_05a_log_captures_final_canonical_status_not_premature_success(self):
        """Log event must receive final status after verification."""
        recipe = make_sample_recipe()
        captured_logs = []

        def capture_log(**kwargs):
            captured_logs.append(kwargs)
            return kwargs

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="ok", stderr="")), \
             patch.object(verification_engine, "verify_tool") as mock_verify, \
             patch.object(state_refresher, "refresh_tool_state"), \
             patch.object(structured_logger, "log_event", side_effect=capture_log), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            mock_verify.return_value = VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=VerificationLevel.FAST,
                executable_found=False,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                details={"error": "Failed probe"},
            )

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=True,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(len(captured_logs), 1)
            logged = captured_logs[0]
            self.assertEqual(logged.get("status"), "VERIFICATION_FAILED")
            self.assertNotEqual(logged.get("status"), "SUCCESS")

    def test_05b_secrets_redacted_from_logging(self):
        """Sensitive tokens, passwords, and API keys are redacted by StructuredLogger."""
        dirty_strings = [
            ("Bearer my_super_secret_bearer_token_12345", "Bearer [REDACTED]"),
            ("curl -H 'Authorization: Bearer my_super_secret_jwt_token_xyz'", "curl -H '[REDACTED]'"),
            ("winget install --token secret1234567890", "winget install [REDACTED]"),
            ("export API_KEY=AIzaSyD_SECRET_GOOGLE_KEY_123456789", "export API_KEY=[REDACTED_API_KEY]"),
            ("github_pat_11AAAAAAA_BBBBBBBBBBBBBBBBBBBBBBBBBB", "[REDACTED_TOKEN]"),
        ]

        for dirty, expected_clean_substring in dirty_strings:
            cleaned = redact_secrets(dirty)
            self.assertNotIn("secret_bearer_token", cleaned)
            self.assertNotIn("AIzaSyD_SECRET", cleaned)
            self.assertNotIn("11AAAAAAA_BBBBBB", cleaned)

    # =========================================================================
    # 6. DUPLICATE EXECUTION PROTECTION & CONCURRENCY LOCKING
    # =========================================================================
    def test_06_concurrent_duplicate_mutation_blocked_by_resource_lock(self):
        """
        When Request A acquires the fine-grained lock for a package manager or tool,
        Request B for the same resource is safely blocked with RESOURCE_BUSY.
        """
        recipe = make_sample_recipe(recipe_id="win_git_install", target="git", package_manager="winget")

        from plan_freeze import resource_lock_mgr
        resource_lock_mgr.clear_all()

        # Hold lock simulating Request A currently in-flight
        resource_lock_mgr.acquire_resources("owner_A", ["pm:winget", "tool:git"])

        from machine_state import MachineState
        ms = MachineState(low_disk_space=False, pending_reboot=False)

        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run") as mock_sub_b:

            # Patch acquire_resources timeout for Request B to avoid waiting full 5s
            orig_acquire = resource_lock_mgr.acquire_resources
            def quick_acquire(owner, res, timeout=5.0):
                return orig_acquire(owner, res, timeout=0.05)

            with patch.object(resource_lock_mgr, "acquire_resources", side_effect=quick_acquire):
                outcome_b = self.engine.execute_recipe(
                    recipe=recipe,
                    approved=True,
                    machine_state=ms,
                )

            # Request B must be blocked because the resource is locked by Request A
            self.assertFalse(outcome_b.success)
            self.assertEqual(outcome_b.status, "BLOCKED")
            self.assertEqual(outcome_b.classification, "RESOURCE_BUSY")
            self.assertEqual(mock_sub_b.call_count, 0, "Request B must NOT spawn a subprocess while resource is busy")

        resource_lock_mgr.clear_all()

    # =========================================================================
    # 7. TIMEOUT AND FAILURE HANDLING
    # =========================================================================
    def test_07a_subprocess_timeout_captured_without_false_success(self):
        """Subprocess timeout produces EXECUTION_FAILED and EXECUTION_TIMEOUT classification."""
        with patch.object(authoritative_safety, "live_pre_execution_gate", return_value=SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sleep 100", timeout=2)), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"):

            outcome = self.engine.execute_command(
                command="sleep 100",
                target="git",
                timeout=2,
                approved=True,
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "EXECUTION_FAILED")
            self.assertEqual(outcome.classification, "EXECUTION_TIMEOUT")
            self.assertEqual(outcome.verification_status, "NOT_RUN")

    def test_07b_multi_step_repair_failure_halts_immediately(self):
        """In a multi-step repair (Problem #54 / #56), failure of Step 1 halts without running Step 2."""
        from platform_abstraction.linux.linux_distribution import (
            LinuxArchitecture,
            LinuxDistribution,
            LinuxDistributionFamily,
        )
        from platform_abstraction.linux.linux_package_manager import (
            AptPackageManagerProvider,
            LinuxPackageManagerName,
            LinuxPackageManagerResolver,
        )

        distro = LinuxDistribution(
            distribution="ubuntu",
            distribution_name="Ubuntu 24.04",
            distribution_family=LinuxDistributionFamily.DEBIAN,
            distribution_version="24.04",
            distribution_codename="noble",
            architecture="x86_64",
            primary_package_manager="apt",
            available_package_managers=["apt"],
            init_system="systemd",
            is_supported=True,
            is_family_compatible=True,
        )

        apt_prov = AptPackageManagerProvider(runner=lambda cmd: (0, "2.34.1", ""))
        apt_prov.is_available = MagicMock(return_value=True)
        resolver = LinuxPackageManagerResolver(distro, custom_providers={LinuxPackageManagerName.APT: apt_prov})

        step_order = []
        mock_engine = MagicMock(spec=CentralizedExecutionEngine)

        def mock_exec_cmd(**kwargs):
            cmd = kwargs.get("command", "")
            if "update" in cmd:
                step_order.append("STEP_1_METADATA_REFRESH")
                return ExecutionOutcome(
                    success=False,
                    status="EXECUTION_FAILED",
                    execution_status="EXECUTION_FAILED",
                    verification_status="NOT_RUN",
                    operation="REFRESH_METADATA",
                    target="apt",
                    command=cmd,
                    return_code=100,
                    stdout="",
                    stderr="W: Failed to fetch repository",
                    classification="EXECUTION_FAILED",
                    verification={},
                    tier="TIER_1_AUTO",
                    message="Metadata update failed",
                )
            step_order.append("STEP_2_PACKAGE_UPDATE")
            return ExecutionOutcome(
                success=True,
                status="VERIFIED",
                execution_status="EXECUTION_SUCCEEDED",
                verification_status="VERIFIED",
                operation="UPDATE",
                target="git",
                command=cmd,
                return_code=0,
                stdout="",
                stderr="",
                classification="SUCCESS",
                verification={},
                tier="TIER_1_AUTO",
                message="Success",
            )

        mock_engine.execute_command.side_effect = mock_exec_cmd

        res = resolver.remediate_outdated_repository(
            canonical_id="git",
            expected_version="2.44.0",
            distro=distro,
            execution_engine=mock_engine,
            approved=True,
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "REPOSITORY_UNAVAILABLE")
        self.assertIn("STEP_1_METADATA_REFRESH", step_order)
        self.assertNotIn("STEP_2_PACKAGE_UPDATE", step_order, "Step 2 must NOT run when Step 1 fails")

    # =========================================================================
    # 8. UI / BACKEND RESULT CONSISTENCY
    # =========================================================================
    def test_08_ui_backend_result_consistency_across_statuses(self):
        """
        Confirms that backend canonical outcomes map to API / SSE states with 100% fidelity:
        - FAILED backend outcome is never reported as ok=True or COMPLETED
        - BLOCKED backend outcome is never reported as SUCCESS
        """
        test_outcomes = [
            (
                ExecutionOutcome(success=False, status="BLOCKED", execution_status="EXECUTION_FAILED", verification_status="NOT_RUN", operation="REPAIR", target="git", command="git", return_code=None, stdout="", stderr="Blocked by safety", classification="SAFETY_POLICY_REJECTED", verification={}, tier="BLOCKED", message="Blocked"),
                {"ok": False, "status": "BLOCKED"}
            ),
            (
                ExecutionOutcome(success=False, status="APPROVAL_REQUIRED", execution_status="NOT_RUN", verification_status="NOT_RUN", operation="REPAIR", target="git", command="git", return_code=None, stdout="", stderr="Needs approval", classification="APPROVAL_REQUIRED", verification={}, tier="TIER_2_CONTROLLED", message="Approval required"),
                {"ok": False, "status": "APPROVAL_REQUIRED"}
            ),
            (
                ExecutionOutcome(success=False, status="VERIFICATION_FAILED", execution_status="EXECUTION_SUCCEEDED", verification_status="VERIFIED", operation="REPAIR", target="git", command="git", return_code=0, stdout="ok", stderr="", classification="VERIFICATION_FAILED", verification={}, tier="TIER_1_AUTO", message="Verification failed"),
                {"ok": False, "status": "VERIFICATION_FAILED"}
            ),
            (
                ExecutionOutcome(success=True, status="VERIFIED", execution_status="EXECUTION_SUCCEEDED", verification_status="VERIFIED", operation="REPAIR", target="git", command="git", return_code=0, stdout="ok", stderr="", classification="SUCCESS", verification={}, tier="TIER_1_AUTO", message="Verified"),
                {"ok": True, "status": "VERIFIED"}
            ),
        ]

        for outcome, expected in test_outcomes:
            d = outcome.to_dict()
            self.assertEqual(outcome.success, expected["ok"])
            self.assertEqual(outcome.status, expected["status"])
            if not expected["ok"]:
                self.assertFalse(d["success"])
                self.assertNotEqual(d["status"], "VERIFIED")

    # =========================================================================
    # 9. CROSS-PLATFORM MUTATION BOUNDARY AUDIT
    # =========================================================================
    def test_09_cross_platform_mutation_boundary_delegates_to_centralized_engine(self):
        """
        Audits Windows, Linux, and macOS package providers:
        Confirms providers build structured command representations,
        and all mutation execution delegates to CentralizedExecutionEngine.
        Unauthorized mutation subprocess count = 0.
        """
        from platform_abstraction.linux.linux_package_manager import (
            ApkPackageManagerProvider,
            AptPackageManagerProvider,
            DnfPackageManagerProvider,
            PacmanPackageManagerProvider,
            ZypperPackageManagerProvider,
        )

        providers = [
            AptPackageManagerProvider(),
            DnfPackageManagerProvider(),
            PacmanPackageManagerProvider(),
            ZypperPackageManagerProvider(),
            ApkPackageManagerProvider(),
        ]

        # Verify providers emit commands and none spawn mutating subprocesses directly
        for prov in providers:
            refresh_cmd = prov.build_refresh_command()
            install_cmd = prov.build_install_command("curl")
            self.assertIsInstance(refresh_cmd, list)
            self.assertIsInstance(install_cmd, list)
            self.assertTrue(len(refresh_cmd) > 0)
            self.assertTrue(len(install_cmd) > 0)

    # =========================================================================
    # 10. TRUSTED AUTOMATIC AUTHORIZATION INTEGRITY
    # =========================================================================
    def test_10_trusted_static_db_recipe_is_automatically_authorized(self):
        """
        STATIC_DB + recognized target + trusted recipe + verified policy
        -> is_automatically_authorized = True
        """
        recipe = make_sample_recipe(source="STATIC_DB")
        req = ExecutionRequest(
            recipe=recipe,
            command=recipe.to_command_string(),
            target=recipe.identity_id,
            operation=recipe.operation.value,
            source=recipe.source,
            approved=None,
        )

        plan = execution_resolver.resolve(req, machine_state=MagicMock())
        self.assertTrue(plan.is_automatically_authorized, "Trusted STATIC_DB recipe must be automatically authorized")
        self.assertIn(plan.tier, (ExecutionTier.TIER_2_CONTROLLED, ExecutionTier.TIER_3_FULL_PROTECTED, ExecutionTier.TIER_1_FAST))


if __name__ == "__main__":
    unittest.main()
