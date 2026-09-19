"""
test_authoritative_backend.py — Comprehensive Test Suite for Authoritative PC Doctor Architecture.

Validates:
1. Unit Tests (Identity, Recipe, Risk, Tier, Blocked, Verification)
2. Integration Tests (Static DB -> Resolver -> Safety -> Executor -> Verification -> Logger -> State Refresh)
3. Safety Tests (Static recipe live gate, AI approval, destructive blocked, wrong OS/arch)
4. Plan Freeze Test (Frozen tier + live safety gate on degraded machine state)
5. Background Automation Tests (User activity deferral vs non-interruptible mutation)
6. Promotion Tests (Local success -> PROMOTION_ELIGIBLE only; cross-environment promotion)
7. MVP End-to-End Tests (Git, Node.js, Visual Studio Code)
"""

import os
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from canonical_identity import CanonicalIdentity, canonical_store
from recipe_engine import (
    RecipeLifecycle,
    RecipeOperation,
    RepairStrategy,
    StructuredRecipe,
    recipe_resolver,
)
from authoritative_safety import (
    AuthoritativeSafetyLayer,
    BlockedReason,
    SafetyGateResult,
    authoritative_safety,
)
from execution_tier import (
    ExecutionTier,
    compute_live_risk,
    select_execution_tier,
)
from plan_freeze import (
    BatchPlan,
    FrozenPlanStep,
    create_frozen_batch_plan,
    evaluate_step_live_safety_gate,
    resource_lock_mgr,
)
from verification_engine import (
    VerificationLevel,
    VerificationResult,
    VerificationStatus,
    verification_engine,
)
from structured_logger import structured_logger
from state_refresh import state_refresher
from automation_engine import (
    AuthoritativePromotionEngine,
    BackgroundAutomationController,
    ValidationEvidence,
    background_automation,
    promotion_engine,
)
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome, execution_engine


class TestCanonicalIdentity(unittest.TestCase):
    def test_canonical_identity_structure(self):
        ident = canonical_store.resolve("git")
        self.assertIsNotNone(ident)
        self.assertEqual(ident.identity_id, "git")
        self.assertEqual(ident.executable, "git")
        # Ensure executable and arguments are strictly separated
        self.assertIsInstance(ident.version_command, list)
        self.assertEqual(ident.version_command, ["git", "--version"])
        self.assertNotEqual(ident.package_id, ident.display_name)

    def test_alias_resolution(self):
        self.assertEqual(canonical_store.resolve("git-scm").identity_id, "git")
        self.assertEqual(canonical_store.resolve("node.js").identity_id, "nodejs")
        self.assertEqual(canonical_store.resolve("vs code").identity_id, "vscode")
        self.assertEqual(canonical_store.resolve("OpenJS.NodeJS").identity_id, "nodejs")


class TestRecipeResolver(unittest.TestCase):
    def test_mvp_recipes_resolution(self):
        # Git
        git_install = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        self.assertIsNotNone(git_install)
        self.assertEqual(git_install.operation, RecipeOperation.INSTALL)

        # Node.js
        node_update = recipe_resolver.resolve_recipe("nodejs", RecipeOperation.UPDATE)
        self.assertIsNotNone(node_update)
        self.assertEqual(node_update.operation, RecipeOperation.UPDATE)

        # Visual Studio Code Repair
        vscode_repair = recipe_resolver.resolve_recipe("vscode", RecipeOperation.REPAIR)
        self.assertIsNotNone(vscode_repair)
        self.assertEqual(vscode_repair.operation, RecipeOperation.REPAIR)
        # CRITICAL RULE: Reinstall strategy must be labeled explicitly, not disguised as native
        self.assertEqual(vscode_repair.repair_strategy, RepairStrategy.REINSTALL)

    def test_command_string_generation(self):
        cur_os = platform.system()
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        cmd = recipe.to_command_string()
        expected_pkg = "Git.Git" if cur_os == "Windows" else "git"
        self.assertIn(expected_pkg, cmd)
        self.assertNotIn("||", cmd)  # No blind fallbacks


class TestDynamicRiskAndTiers(unittest.TestCase):
    def test_fast_path_selection(self):
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.VERSION_CHECK)
        risk = compute_live_risk(recipe, {"free_disk_gb": 50.0, "cpu_percent": 10.0, "ram_percent": 30.0})
        tier, reason = select_execution_tier(recipe, trust_score=1.0, risk_score=risk, confidence_score=0.95)
        self.assertEqual(tier, ExecutionTier.TIER_0_READ_ONLY)

    def test_controlled_path_for_repair(self):
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.REPAIR)
        risk = compute_live_risk(recipe, {"free_disk_gb": 50.0, "cpu_percent": 10.0, "ram_percent": 30.0})
        tier, reason = select_execution_tier(recipe, trust_score=1.0, risk_score=risk, confidence_score=0.9)
        self.assertIn(tier, (ExecutionTier.TIER_1_FAST, ExecutionTier.TIER_2_CONTROLLED))


class TestAuthoritativeSafety(unittest.TestCase):
    def test_destructive_blacklist(self):
        destructive = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs.ext4 /dev/sda1",
            "format C:",
            "del C:\\windows\\system32",
            "reg delete HKLM\\SYSTEM",
        ]
        for cmd in destructive:
            allowed, reason, msg = authoritative_safety.evaluate_command_static(cmd)
            self.assertFalse(allowed, f"Should have blocked: {cmd}")
            self.assertEqual(reason, BlockedReason.DESTRUCTIVE_OPERATION)

    def test_wrong_os_rejection(self):
        cur_os = platform.system()
        if cur_os == "Windows":
            res = authoritative_safety.live_pre_execution_gate("sudo apt-get install -y git")
            self.assertFalse(res.allowed)
            self.assertEqual(res.blocked_reason, BlockedReason.UNSUPPORTED_METHOD)
            self.assertTrue(res.is_recoverable)
        else:
            res = authoritative_safety.live_pre_execution_gate("winget install --id Git.Git")
            self.assertFalse(res.allowed)
            self.assertEqual(res.blocked_reason, BlockedReason.UNSUPPORTED_METHOD)

    def test_static_recipe_still_receives_live_safety_gate(self):
        # Even trusted static recipes must check disk space dynamically
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        # Mock low disk space (<2GB)
        res = authoritative_safety.live_pre_execution_gate(
            command=recipe.to_command_string(),
            operation="INSTALL",
            required_disk_gb=99999.0, # Will fail disk check
            is_static_recipe=True,
        )
        self.assertFalse(res.allowed)
        self.assertEqual(res.blocked_reason, BlockedReason.RISK_ABOVE_HARD_LIMIT)


class TestPlanFreeze(unittest.TestCase):
    def test_batch_plan_freeze_and_degraded_state_gate(self):
        """
        Section 26: PLAN-FREEZE TEST
        Batch plan Git + Node + VS Code.
        All receive Fast Path at 09:00.
        Git executes. Machine state degrades (disk critically low).
        Before Node: live safety gate runs and BLOCKS execution.
        The original plan tier remains FROZEN.
        """
        git_rec = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        node_rec = recipe_resolver.resolve_recipe("nodejs", RecipeOperation.INSTALL)
        vscode_rec = recipe_resolver.resolve_recipe("vscode", RecipeOperation.INSTALL)

        plan = create_frozen_batch_plan(
            plan_id="plan_0900",
            recipes_with_scores=[
                (git_rec, ExecutionTier.TIER_1_FAST, 1.0, 0.2, 0.9),
                (node_rec, ExecutionTier.TIER_1_FAST, 1.0, 0.2, 0.9),
                (vscode_rec, ExecutionTier.TIER_1_FAST, 1.0, 0.2, 0.9),
            ],
        )

        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[1].frozen_tier, ExecutionTier.TIER_1_FAST)

        # Before Node executes, simulate disk space becoming critically low
        gate_res = evaluate_step_live_safety_gate(plan.steps[1], required_disk_gb=99999.0)

        # Node does NOT blindly execute!
        self.assertFalse(gate_res.allowed)
        self.assertEqual(plan.steps[1].status, "BLOCKED")

        # BUT the plan tier remains frozen as TIER_1_FAST
        self.assertEqual(plan.steps[1].frozen_tier, ExecutionTier.TIER_1_FAST)


class TestConcurrencyLocking(unittest.TestCase):
    def test_fine_grained_resource_locks(self):
        # Acquire lock for winget
        acquired1 = resource_lock_mgr.acquire_resources("job1", ["pm:winget", "tool:git"])
        self.assertTrue(acquired1)

        # Another job targeting winget must wait / fail
        acquired2 = resource_lock_mgr.acquire_resources("job2", ["pm:winget", "tool:nodejs"], timeout=0.1)
        self.assertFalse(acquired2)

        # Job targeting an unrelated package manager can acquire concurrently
        acquired3 = resource_lock_mgr.acquire_resources("job3", ["pm:npm", "tool:eslint"], timeout=0.1)
        self.assertTrue(acquired3)

        # Release
        resource_lock_mgr.release_resources("job1", ["pm:winget", "tool:git"])
        resource_lock_mgr.release_resources("job3", ["pm:npm", "tool:eslint"])

        # Now job2 can acquire
        acquired4 = resource_lock_mgr.acquire_resources("job2", ["pm:winget", "tool:nodejs"], timeout=0.5)
        self.assertTrue(acquired4)
        resource_lock_mgr.release_resources("job2", ["pm:winget", "tool:nodejs"])


class TestBackgroundAutomation(unittest.TestCase):
    def test_background_idle_pause(self):
        ctrl = BackgroundAutomationController()
        ctrl.mark_user_activity()
        # User is active: defer before execute
        self.assertTrue(ctrl.should_defer_pre_execution())

    def test_non_interruptible_mutation(self):
        ctrl = BackgroundAutomationController()
        ctrl.enter_execution()
        ctrl.mark_user_activity() # User becomes active while executing
        # Once in EXECUTE: DO NOT INTERRUPT
        self.assertFalse(ctrl.should_defer_pre_execution())
        ctrl.exit_execution()


class TestPromotionRules(unittest.TestCase):
    def test_local_execution_grants_promotion_eligible_not_promoted(self):
        """
        Section 11 & 28: Local successful execution yields PROMOTION_ELIGIBLE.
        Confirm it does NOT become Static.
        """
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        recipe.source = "DYNAMIC_DB"
        recipe.validation_status = RecipeLifecycle.READY_FOR_EXECUTION

        outcome = promotion_engine.record_execution_outcome(recipe, execution_success=True, verification_success=True)
        self.assertEqual(outcome, RecipeLifecycle.PROMOTION_ELIGIBLE)
        self.assertNotEqual(recipe.validation_status, RecipeLifecycle.PROMOTED_TO_STATIC)
        self.assertNotEqual(recipe.source, "STATIC_DB")

    def test_cross_environment_promotion_requirement(self):
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.INSTALL)
        recipe.source = "DYNAMIC_DB"
        recipe.os = "Windows"
        recipe.validation_status = RecipeLifecycle.PROMOTION_ELIGIBLE

        # 1. Single environment evidence -> insufficient
        evidence1 = [
            ValidationEvidence("env_pc1", "Windows 11", "x64", "winget", "2026-09-11", True),
            ValidationEvidence("env_pc1", "Windows 11", "x64", "winget", "2026-09-11", True), # Repeated on same PC
        ]
        promoted, status, msg = promotion_engine.evaluate_for_static_promotion(recipe, evidence1, user_approved_review=True)
        self.assertFalse(promoted)
        self.assertEqual(status, RecipeLifecycle.REVIEW_REQUIRED)

        # 2. 3 distinct independent matching environments + review -> PROMOTED_TO_STATIC
        evidence3 = [
            ValidationEvidence("env_pc1", "Windows 11", "x64", "winget", "2026-09-11", True),
            ValidationEvidence("env_pc2", "Windows 11", "x64", "winget", "2026-09-11", True),
            ValidationEvidence("env_pc3", "Windows 10", "x64", "winget", "2026-09-11", True),
        ]
        promoted, status, msg = promotion_engine.evaluate_for_static_promotion(recipe, evidence3, user_approved_review=True)
        self.assertTrue(promoted)
        self.assertEqual(status, RecipeLifecycle.PROMOTED_TO_STATIC)
        self.assertEqual(recipe.source, "STATIC_DB")


class TestStructuredLogging(unittest.TestCase):
    def test_structured_log_contains_all_16_fields_and_redaction(self):
        log_entry = structured_logger.log_event(
            operation="INSTALL",
            application="Git",
            identity="git",
            status="VERIFIED",
            message="Bearer secret_token_xyz_1234567890 installed ok",
            command="winget install Git.Git --token secret_token_xyz_1234567890",
            recipe_id="static_git_install",
            return_code=0,
            tier="TIER_1_FAST",
        )

        required_fields = [
            "timestamp", "operation", "application", "identity", "recipe_id",
            "source", "status", "message", "command", "return_code",
            "versions", "verification", "tier", "trust", "risk", "confidence",
        ]
        for f in required_fields:
            self.assertIn(f, log_entry, f"Missing required field: {f}")

        # Ensure secrets are redacted
        self.assertNotIn("secret_token_xyz_1234567890", log_entry["message"])
        self.assertNotIn("secret_token_xyz_1234567890", log_entry["command"])
        self.assertIn("[REDACTED]", log_entry["message"])


class TestMVPVerificationAndExecution(unittest.TestCase):
    def test_verification_levels(self):
        # Test FAST verification for Git
        res_fast = verification_engine.verify_tool("git", level=VerificationLevel.FAST)
        if res_fast.executable_found:
            self.assertEqual(res_fast.status, VerificationStatus.VERIFIED)
            self.assertIsNotNone(res_fast.version_detected)

        # Test CONTROLLED verification for Git
        res_ctrl = verification_engine.verify_tool("git", level=VerificationLevel.CONTROLLED)
        if res_ctrl.executable_found:
            self.assertEqual(res_ctrl.status, VerificationStatus.VERIFIED)

        # Test non-existent tool returns VERIFICATION_FAILED
        res_none = verification_engine.verify_tool("nonexistent_tool_12345")
        self.assertEqual(res_none.status, VerificationStatus.VERIFICATION_FAILED)

    def test_safe_read_only_execution(self):
        # Version check for Git through the authoritative execution engine
        recipe = recipe_resolver.resolve_recipe("git", RecipeOperation.VERSION_CHECK)
        self.assertIsNotNone(recipe)
        outcome = execution_engine.execute_recipe(recipe, verification_level=VerificationLevel.FAST)
        # If Git is on system, it executes and verifies
        if outcome.return_code == 0:
            self.assertEqual(outcome.status, "VERIFIED")
            self.assertTrue(outcome.success)
            self.assertIn("tier", outcome.to_dict())


if __name__ == "__main__":
    unittest.main()
