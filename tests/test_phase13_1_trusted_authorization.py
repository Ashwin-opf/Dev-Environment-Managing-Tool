"""
tests/test_phase13_1_trusted_authorization.py — Phase 13.1 Centralized Automatic Authorization Test Suite.

Verifies:
1. Trusted STATIC_DB golden recipes are automatically authorized without requiring manual approval button clicks.
2. Separation of concepts: Trust, Risk, Approval, Authorization, and Safety Gate are distinct.
3. High risk scores in trusted recipes (Tier 2/3) do not prevent automatic authorization of golden recipes.
4. LIVE Safety Gate remains the absolute final blocker: dangerous/blacklisted commands, low disk space, or invalid states block execution regardless of authorization.
5. Untrusted, AI/RAG generated, and raw unresolved commands are NEVER automatically authorized (require explicit human approval).
6. Explicit user rejection (approved=False) takes absolute precedence and stops execution before any mutation or subprocess.
7. Both batch (execute_recipe, execute_command) and streaming execution engines respect automatic authorization.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from authoritative_safety import BlockedReason, AuthoritativeSafetyLayer
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome, execution_engine
from execution_plan import ExecutionPlan, ExecutionRequest, ExecutionResolver, ProvenanceClass
from execution_tier import ExecutionTier
from recipe_engine import RecipeOperation, StructuredRecipe
from verification_engine import VerificationStatus


def make_test_recipe(recipe_id: str = "win_git_install", source: str = "STATIC_DB") -> StructuredRecipe:
    return StructuredRecipe(
        recipe_id=recipe_id,
        recipe_version=1,
        identity_id="git",
        operation=RecipeOperation.INSTALL,
        os="Windows",
        architecture="x64",
        package_manager="winget",
        executable="winget",
        arguments=["install", "--id", "Git.Git", "--exact", "--silent"],
        verification_command=["git", "--version"],
        source=source,
    )


class TestPhase13_1TrustedAuthorization(unittest.TestCase):
    """Authoritative tests for centralized automatic authorization of trusted golden recipes."""

    def setUp(self):
        self.resolver = ExecutionResolver()
        self.engine = CentralizedExecutionEngine()

    def test_01_trusted_static_recipe_is_automatically_authorized(self):
        """A verified STATIC_DB golden recipe is automatically authorized even in Controlled tier."""
        req = ExecutionRequest(
            command="winget install --id Git.Git --exact --silent",
            target="git",
            operation="INSTALL",
            source="STATIC_DB",
            provenance_hint=ProvenanceClass.STATIC_RECIPE,
            approved=None,  # No manual approval button clicked yet
        )

        plan = self.resolver.resolve(req)

        self.assertTrue(plan.is_automatically_authorized)
        self.assertIn("authorized", plan.authorization_reason.lower())
        # Approval requirement on plan is satisfied by automatic authorization
        self.assertTrue(plan.approved)

    def test_02_trusted_recipe_executes_without_manual_approval_clicks(self):
        """Trusted golden recipe executes through execution_engine without requiring approved=True."""
        recipe = make_test_recipe()

        # Mock safety gate and subprocess
        mock_safety = MagicMock()
        mock_safety.allowed = True
        mock_safety.blocked_reason = None
        mock_safety.message = "Allowed"

        mock_ms = MagicMock()

        mock_verify_res = MagicMock()
        mock_verify_res.status = VerificationStatus.VERIFIED
        mock_verify_res.passed = True
        mock_verify_res.duration_ms = 100.0
        mock_verify_res.version_detected = "2.44.0"
        mock_verify_res.details = {}
        mock_verify_res.to_dict.return_value = {"status": "VERIFIED"}

        with patch("execution_engine.authoritative_safety.live_pre_execution_gate", return_value=mock_safety), \
             patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
             patch("execution_engine.resource_lock_mgr.release_resources"), \
             patch("subprocess.run") as mock_run, \
             patch("verification_engine.verification_engine.verify_tool", return_value=mock_verify_res):

            mock_run.return_value = MagicMock(returncode=0, stdout="Successfully installed", stderr="")

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=None,  # Not approved manually
                machine_state=mock_ms,
            )

            # Invariant: Must execute and succeed automatically
            self.assertTrue(outcome.success)
            self.assertTrue(any("winget install" in str(c) for c in mock_run.call_args_list))

    def test_03_high_risk_does_not_block_trusted_golden_recipe_authorization(self):
        """
        Separation of Trust and Risk:
        A golden recipe with higher risk retains automatic authorization
        if its provenance is STATIC_RECIPE and trust score is high.
        """
        is_auto, reason = self.resolver.evaluate_authorization(
            provenance_class=ProvenanceClass.STATIC_RECIPE,
            recipe=make_test_recipe(),
            target_name="git",
            trust_score=0.95,
            tier=ExecutionTier.TIER_2_CONTROLLED,
            source="STATIC_DB",
            request_approved=None,
        )

        self.assertTrue(is_auto)
        self.assertIn("authorized", reason.lower())

    def test_04_live_safety_gate_remains_absolute_final_blocker(self):
        """
        Even when a command has automatic authorization, the LIVE Safety Gate
        will unconditionally BLOCK execution if safety checks fail (e.g. policy rejected, low disk).
        """
        recipe = make_test_recipe()
        mock_ms = MagicMock()

        mock_safety = MagicMock()
        mock_safety.allowed = False
        mock_safety.blocked_reason = BlockedReason.SAFETY_POLICY_REJECTED
        mock_safety.message = "Disk space below safe threshold (500MB remaining, 1024MB required)."

        with patch("execution_engine.authoritative_safety.live_pre_execution_gate", return_value=mock_safety), \
             patch("subprocess.run") as mock_run:

            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=None,
                machine_state=mock_ms,
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertIn("Disk space", outcome.message)
            # Must NOT spawn subprocess!
            mock_run.assert_not_called()

    def test_05_untrusted_source_strictly_requires_approval(self):
        """Commands from untrusted or unvetted sources require manual human approval."""
        req = ExecutionRequest(
            command="npm install -g some-custom-tool",
            target="custom_tool",
            operation="INSTALL",
            source="RAG_EXTRACTION",
            provenance_hint=ProvenanceClass.AI_RAG_CANDIDATE,
            approved=None,
        )

        plan = self.resolver.resolve(req)

        self.assertFalse(plan.is_automatically_authorized)
        self.assertTrue(plan.approval_required)
        self.assertFalse(plan.approved)

    def test_06_untrusted_source_blocked_at_approval_gate_in_execution_engine(self):
        """An unapproved untrusted command is halted at the approval gate with zero mutations."""
        with patch("subprocess.run") as mock_run:
            outcome = self.engine.execute_command(
                command="npm install -g some-custom-tool",
                target="custom_tool",
                operation="INSTALL",
                source="RAG_EXTRACTION",
                approved=None,
                machine_state=MagicMock(),
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertEqual(outcome.execution_status, "NOT_RUN")
            mock_run.assert_not_called()

    def test_07_explicit_user_rejection_overrides_trusted_authorization(self):
        """If user explicitly rejected (approved=False), execution is strictly stopped."""
        recipe = make_test_recipe()
        mock_ms = MagicMock()

        with patch("subprocess.run") as mock_run:
            outcome = self.engine.execute_recipe(
                recipe=recipe,
                approved=False,  # Explicit user refusal
                machine_state=mock_ms,
            )

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertEqual(outcome.execution_status, "NOT_RUN")
            mock_run.assert_not_called()

    def test_08_stream_execution_supports_automatic_authorization(self):
        """Streaming execution emits AUTHORIZING event and completes automatically for trusted recipes."""
        recipe = make_test_recipe()

        mock_safety = MagicMock()
        mock_safety.allowed = True
        mock_safety.blocked_reason = None
        mock_safety.message = "Allowed"

        mock_verify_res = MagicMock()
        mock_verify_res.status = VerificationStatus.VERIFIED
        mock_verify_res.passed = True
        mock_verify_res.version_detected = "2.44.0"
        mock_verify_res.duration_ms = 50.0
        mock_verify_res.details = {}
        mock_verify_res.to_dict.return_value = {"status": "VERIFIED"}

        async def run_test():
            events = []
            with patch("execution_engine.authoritative_safety.live_pre_execution_gate", return_value=mock_safety), \
                 patch("execution_engine.resource_lock_mgr.acquire_resources", return_value=True), \
                 patch("execution_engine.resource_lock_mgr.release_resources"), \
                 patch("asyncio.create_subprocess_shell") as mock_proc, \
                 patch("verification_engine.verification_engine.verify_tool", return_value=mock_verify_res):

                proc_instance = MagicMock()
                proc_instance.returncode = 0
                proc_instance.communicate = MagicMock(return_value=asyncio.sleep(0.001, (b"Done", b"")))
                proc_instance.stdout.readline = MagicMock(return_value=asyncio.sleep(0.001, b""))
                proc_instance.stderr.readline = MagicMock(return_value=asyncio.sleep(0.001, b""))
                mock_proc.return_value = proc_instance

                async for sse in self.engine.stream_execute_recipe(recipe=recipe, approved=None):
                    events.append(sse)

            return events

        events = asyncio.run(run_test())
        # Must contain AUTHORIZING stage event
        authorizing_events = [e for e in events if "AUTHORIZING" in e]
        self.assertTrue(len(authorizing_events) > 0)
        # Must contain DONE event with VERIFIED / success
        done_events = [e for e in events if '"status": "VERIFIED"' in e or '"success": true' in e]
        self.assertTrue(len(done_events) > 0)

    def test_09_critical_mutation_path_trace(self):
        """
        Validates the authoritative critical mutation path runtime trace order:
        CENTRALIZED_ENGINE -> AUTHORIZATION -> LIVE_SAFETY_GATE -> EXECUTION -> VERIFICATION -> RESCAN -> LOGGING
        """
        import subprocess
        from execution_plan import execution_resolver
        from authoritative_safety import authoritative_safety, SafetyGateResult
        from verification_engine import verification_engine, VerificationResult, VerificationLevel
        from state_refresh import state_refresher
        from structured_logger import structured_logger

        trace = []

        orig_auth = execution_resolver.evaluate_authorization
        def trace_auth(*args, **kwargs):
            trace.append("AUTHORIZATION")
            return orig_auth(*args, **kwargs)

        orig_safety = authoritative_safety.live_pre_execution_gate
        def trace_safety(*args, **kwargs):
            trace.append("LIVE_SAFETY_GATE")
            return SafetyGateResult(allowed=True, blocked_reason=None, message="Allowed")

        orig_sub = subprocess.run
        def trace_sub(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", "")
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            if "winget install" in str(cmd) or "git" in str(cmd):
                trace.append("MUTATING_SUBPROCESS")
            return MagicMock(returncode=0, stdout="success", stderr="")

        orig_verify = verification_engine.verify_tool
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

        orig_rescan = state_refresher.refresh_tool_state
        def trace_rescan(*args, **kwargs):
            trace.append("RESCAN")
            return {}

        orig_log = structured_logger.log_event
        def trace_log(*args, **kwargs):
            trace.append("LOGGING")
            return orig_log(*args, **kwargs)

        recipe = make_test_recipe()

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
        self.assertIn("CENTRALIZED_ENGINE_ENTRY", trace)
        self.assertIn("AUTHORIZATION", trace)
        self.assertIn("LIVE_SAFETY_GATE", trace)
        self.assertIn("MUTATING_SUBPROCESS", trace)
        self.assertIn("VERIFICATION", trace)
        self.assertIn("RESCAN", trace)
        self.assertIn("LOGGING", trace)

        engine_idx = trace.index("CENTRALIZED_ENGINE_ENTRY")
        auth_idx = trace.index("AUTHORIZATION")
        safety_idx = trace.index("LIVE_SAFETY_GATE")
        exec_idx = trace.index("MUTATING_SUBPROCESS")
        verif_idx = trace.index("VERIFICATION")
        rescan_idx = trace.index("RESCAN")
        log_idx = trace.index("LOGGING")

        self.assertTrue(engine_idx < auth_idx, "Centralized Engine invocation must precede Authorization")
        self.assertTrue(auth_idx < safety_idx, "Authorization must precede LIVE Safety Gate")
        self.assertTrue(safety_idx < exec_idx, "LIVE Safety Gate must precede Mutating Subprocess")
        self.assertTrue(exec_idx < verif_idx, "Mutating Subprocess must precede Verification")
        self.assertTrue(verif_idx <= rescan_idx, "Verification must precede Rescan")
        self.assertTrue(rescan_idx < log_idx, "Rescan must precede Logging")


if __name__ == "__main__":
    unittest.main()

