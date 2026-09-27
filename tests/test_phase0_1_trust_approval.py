"""
Tests for Phase 0.1 — Trust, Approval, and Execution-Plan Hardening.
Implements the mandatory negative tests (Tests 1 through 7) specified in Section 9:
1. Unknown command: Unresolved/low-trust provenance, NOT max trust, NOT max confidence, NOT Fast Path, no unauthorized mutation.
2. AI-generated command: Dynamic/untrusted provenance, never automatically promoted to static recipe.
3. RAG-generated candidate: Untrusted dynamic candidate, normal safety and approval rules apply.
4. Controlled tier without approval: approved=False -> NO MUTATION, APPROVAL_REQUIRED.
5. Controlled tier with approval: approved=True -> Safety Gate -> execution -> verification.
6. Dangerous request: Even with approved=True, trust=high -> rejected by Safety Gate, 0 subprocesses.
7. Safe machine-scope repair: Execution Plan -> machine scope -> privilege resolution -> elevation -> Safety Gate -> mutation -> verification -> rescan.
"""

import os
import sys
import platform
import subprocess
import unittest
from unittest.mock import patch, MagicMock

# Ensure backend is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from execution_plan import (
    ProvenanceClass,
    ExecutionRequest,
    ExecutionPlan,
    execution_resolver,
)
from execution_tier import (
    ExecutionTier,
    select_execution_tier,
    compute_live_risk,
)
from execution_engine import execution_engine, ExecutionOutcome
from authoritative_safety import authoritative_safety
from verification_engine import (
    verification_engine,
    VerificationResult,
    VerificationStatus,
    VerificationLevel,
)
from machine_state import MachineState
from state_refresh import state_refresher
from privilege_manager import privilege_manager


class TestPhase01TrustApproval(unittest.TestCase):
    """Authoritative test suite for Phase 0.1 Trust & Approval Hardening."""

    # =========================================================================
    # TEST 1 — Unknown Command: Low Trust, Not Fast Path, No Unauthorized Mutation
    # =========================================================================
    def test_01_unknown_command_not_trusted_not_fast_path(self):
        """
        Test 1:
        Input: Command with no matching Static recipe.
        Expected:
        - Unresolved / low-trust provenance (UNRESOLVED_RAW).
        - NOT maximum trust (trust <= 0.40).
        - NOT maximum confidence (confidence <= 0.50).
        - NOT Fast Path by default (tier is Controlled, Protected, or Blocked).
        - No unauthorized mutation (0 subprocesses spawned without approved=True).
        """
        raw_cmd = "mystery_tool_xyz --force-repair-everything"
        req = ExecutionRequest(
            command=raw_cmd,
            target="mystery_tool_xyz",
            operation="REPAIR",
        )
        m_state = MachineState(free_disk_gb=50.0)
        plan = execution_resolver.resolve(req, machine_state=m_state)

        # 1. Provenance must be UNRESOLVED_RAW, never fabricated into a STATIC_RECIPE
        self.assertEqual(plan.provenance_class, ProvenanceClass.UNRESOLVED_RAW)
        self.assertIsNone(plan.recipe)

        # 2. Must NOT receive maximum trust or maximum confidence
        self.assertLessEqual(plan.trust_score, 0.40)
        self.assertLessEqual(plan.confidence_score, 0.50)
        self.assertNotEqual(plan.trust_score, 1.0)
        self.assertNotEqual(plan.confidence_score, 1.0)

        # 3. Must NOT silently enter Fast Path
        self.assertNotEqual(plan.tier, ExecutionTier.TIER_1_FAST)
        self.assertIn(
            plan.tier,
            (
                ExecutionTier.TIER_2_CONTROLLED,
                ExecutionTier.TIER_3_FULL_PROTECTED,
                ExecutionTier.BLOCKED,
            ),
        )

        # 4. No unauthorized mutation: executing without explicit approved=True must NOT spawn processes
        with patch("subprocess.run") as mock_subproc, patch("subprocess.Popen") as mock_popen:
            outcome = execution_engine.execute_command(
                command=raw_cmd,
                target="mystery_tool_xyz",
                operation="REPAIR",
            )
            self.assertEqual(mock_subproc.call_count, 0)
            self.assertEqual(mock_popen.call_count, 0)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertEqual(outcome.execution_status, "NOT_RUN")

    # =========================================================================
    # TEST 2 — AI-Generated Command: Untrusted Provenance, Never Promoted
    # =========================================================================
    def test_02_ai_generated_command_untrusted_dynamic_provenance(self):
        """
        Test 2:
        Simulate an AI-produced command.
        Expected:
        - Dynamic/untrusted provenance (AI_RAG_CANDIDATE).
        - Must NOT be treated like a trusted Static recipe.
        - Trust and confidence strictly bounded.
        """
        ai_cmd = "pip install hypothetical-ai-fix-pkg"
        req = ExecutionRequest(
            command=ai_cmd,
            target="pip",
            source="AI",
        )
        plan = execution_resolver.resolve(req)

        # Provenance must be AI_RAG_CANDIDATE
        self.assertEqual(plan.provenance_class, ProvenanceClass.AI_RAG_CANDIDATE)
        self.assertNotEqual(plan.provenance_class, ProvenanceClass.STATIC_RECIPE)
        self.assertIsNone(plan.recipe)

        # Strict bounds
        self.assertLessEqual(plan.trust_score, 0.40)
        self.assertLessEqual(plan.confidence_score, 0.40)
        self.assertNotEqual(plan.tier, ExecutionTier.TIER_1_FAST)

        # Without approval, no execution occurs
        with patch("subprocess.run") as mock_subproc:
            outcome = execution_engine.execute_command(
                command=ai_cmd,
                target="pip",
                source="AI",
            )
            self.assertEqual(mock_subproc.call_count, 0)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")

    # =========================================================================
    # TEST 3 — RAG-Generated Candidate: Subject to Normal Safety & Approval
    # =========================================================================
    def test_03_rag_generated_candidate_subject_to_safety_and_approval(self):
        """
        Test 3:
        Simulate a RAG-derived repair candidate.
        Expected:
        - Untrusted dynamic candidate provenance.
        - Normal safety and approval rules apply.
        - Even if marked approved, a dangerous RAG recommendation is blocked.
        """
        rag_cmd = "rm -rf / --no-preserve-root"
        req = ExecutionRequest(
            command=rag_cmd,
            target="system",
            source="RAG",
            approved=True,
        )
        plan = execution_resolver.resolve(req)

        self.assertEqual(plan.provenance_class, ProvenanceClass.AI_RAG_CANDIDATE)
        self.assertLessEqual(plan.trust_score, 0.40)

        # Even with approved=True, authoritative safety gate MUST reject it with 0 subprocesses
        with patch("subprocess.run") as mock_subproc, patch("subprocess.Popen") as mock_popen:
            outcome = execution_engine.execute_command(
                command=rag_cmd,
                source="RAG",
                approved=True,
            )
            self.assertEqual(mock_subproc.call_count, 0)
            self.assertEqual(mock_popen.call_count, 0)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertIn(outcome.classification, ("SAFETY_POLICY_REJECTED", "RISK_ABOVE_HARD_LIMIT", "BLOCKED"))

    # =========================================================================
    # TEST 4 — Controlled Tier Without Approval: No Mutation
    # =========================================================================
    def test_04_controlled_tier_without_approval_blocks_mutation(self):
        """
        Test 4:
        Force a valid Tier-2 / controlled request.
        Set: approved = false
        Expected:
        - NO MUTATION (call_count == 0).
        - Result clearly identifies approval required.
        """
        cmd = "pip install certifi"
        with patch("subprocess.run") as mock_subproc, patch("subprocess.Popen") as mock_popen:
            outcome = execution_engine.execute_command(
                command=cmd,
                target="pip",
                operation="REPAIR",
                approved=False,
            )
            self.assertEqual(mock_subproc.call_count, 0)
            self.assertEqual(mock_popen.call_count, 0)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
            self.assertEqual(outcome.execution_status, "NOT_RUN")
            self.assertIn("approval", outcome.message.lower())
            self.assertTrue(outcome.details.get("requires_approval"))

    # =========================================================================
    # TEST 5 — Controlled Tier With Approval: Executes and Verifies
    # =========================================================================
    def test_05_controlled_tier_with_approval_executes_and_verifies(self):
        """
        Test 5:
        Same request as Test 4:
        Set: approved = true
        Expected:
        - Tier requirements satisfied.
        - Proceeds to Safety Gate.
        - Execution occurs.
        - Verification occurs.
        """
        cmd = "pip install certifi"
        fake_proc = subprocess.CompletedProcess(
            args=["pip", "install", "certifi"],
            returncode=0,
            stdout="Successfully installed certifi-2024.2.2",
            stderr="",
        )

        with patch("subprocess.run", return_value=fake_proc) as mock_subproc, \
             patch.object(verification_engine, "verify_tool") as mock_verif, \
             patch.object(state_refresher, "refresh_tool_state") as mock_rescan, \
             patch.object(state_refresher, "refresh_machine_state", return_value=MagicMock(
                 pending_reboot=False, low_disk_space=False, dependency_lock=False,
                 conflicts=False, unusual_state=False, service_issue=False,
                 package_manager_available=True, free_disk_gb=50.0,
                 cpu_percent=20.0, ram_percent=30.0, is_normal_state=lambda **kw: (True, []),
             )):

            mock_verif.return_value = VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.CONTROLLED,
                executable_found=True,
                version_detected="2024.2.2",
                functional_check_passed=True,
                problem_cleared=True,
                attempts=1,
            )

            outcome = execution_engine.execute_command(
                command=cmd,
                target="pip",
                operation="REPAIR",
                approved=True,
            )

            # Subprocess executed
            self.assertGreaterEqual(mock_subproc.call_count, 1)
            # Verification executed
            self.assertEqual(mock_verif.call_count, 1)
            # State refresh executed
            self.assertEqual(mock_rescan.call_count, 1)
            # Final state verified
            self.assertTrue(outcome.success)
            self.assertEqual(outcome.status, "VERIFIED")
            self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")


    # =========================================================================
    # TEST 6 — Dangerous Request: Rejected Even With High Trust and Approval
    # =========================================================================
    def test_06_dangerous_request_rejected_even_with_high_trust_and_approval(self):
        """
        Test 6:
        Even with:
        - approved = true
        - trust = high (1.0)
        - confidence = high (1.0)
        the existing authoritative Safety Gate must still reject the operation.
        No subprocess may be spawned.
        """
        destructive_cmd = "del /f /q C:\\Windows\\System32\\hal.dll"
        with patch("subprocess.run") as mock_subproc, patch("subprocess.Popen") as mock_popen:
            outcome = execution_engine.execute_command(
                command=destructive_cmd,
                target="system",
                source="STATIC_DB",
                approved=True,
            )
            self.assertEqual(mock_subproc.call_count, 0)
            self.assertEqual(mock_popen.call_count, 0)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertIn(outcome.classification, ("SAFETY_POLICY_REJECTED", "DESTRUCTIVE_OPERATION"))

    # =========================================================================
    # TEST 7 — Machine-Scope Repair: Full Authoritative Lifecycle
    # =========================================================================
    def test_07_safe_machine_scope_repair_lifecycle(self):
        """
        Test 7:
        Safe machine-scope repair scenario.
        Verify full pipeline:
        Execution Plan -> machine scope -> privilege resolution -> elevation -> Safety Gate -> mutation -> verification -> rescan.
        """
        cur_os = platform.system()
        git_path_cmd = 'export PATH="$PATH:/usr/bin"' if cur_os != "Windows" else 'setx PATH "%PATH%;C:\\Program Files\\Git\\cmd" /M'

        with patch.object(privilege_manager, "run_with_elevation", return_value=("PATH updated successfully", "", 0)) as mock_elev, \
             patch.object(authoritative_safety, "live_pre_execution_gate", wraps=authoritative_safety.live_pre_execution_gate) as mock_safety, \
             patch.object(verification_engine, "verify_tool") as mock_verif, \
             patch.object(state_refresher, "refresh_tool_state") as mock_rescan:

            mock_verif.return_value = VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=VerificationLevel.CONTROLLED,
                executable_found=True,
                version_detected="2.43.0",
                functional_check_passed=True,
                problem_cleared=True,
                attempts=1,
            )

            outcome = execution_engine.execute_command(
                command=git_path_cmd,
                elevate=True,
                scope="machine",
                target="git",
                operation="REPAIR_PATH",
                approved=True,
            )

            # 1. Safety Gate ran and authorized
            self.assertTrue(mock_safety.called)
            # 2. Elevated operation ran via privilege manager
            self.assertTrue(mock_elev.called)
            # 3. Post-execution verification ran
            self.assertTrue(mock_verif.called)
            # 4. State rescan ran
            self.assertTrue(mock_rescan.called)
            # 5. Final outcome is VERIFIED
            self.assertTrue(outcome.success)
            self.assertEqual(outcome.status, "VERIFIED")
            self.assertEqual(outcome.return_code, 0)


if __name__ == "__main__":
    unittest.main()
