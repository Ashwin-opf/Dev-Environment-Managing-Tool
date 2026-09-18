"""
tests/test_fault_injection_lab.py — Automated Test Suite for Fault Injection / Test Lab.

Validates all 23 core architectural guarantees:
1. Fault definition validation
2. Unsupported fault rejected
3. Non-reversible real fault rejected
4. Baseline capture
5. Git PATH removal
6. Git fault verification
7. Git restoration
8. Restoration verification
9. User PATH fault
10. Review-only Python scenario
11. Simulation-only dangerous fault
12. Normal PC Doctor pipeline invoked after injection
13. Independent verification (L1-L5)
14. Duplicate PATH entries are not created
15. Unrelated PATH entries remain unchanged
16. Fault cleanup occurs on success
17. Fault cleanup occurs after repair failure
18. Fault cleanup occurs after verification failure
19. Fault cleanup occurs after cancellation
20. Test timeout produces cleanup
21. Tier mutation tests
22. Cross-platform adapter selection
23. Production mode rejects fault injection
"""

import asyncio
import os
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend directory is in path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from test_lab.models import (
    BaselineRecord,
    FaultCapability,
    FaultDefinition,
    FaultRiskClass,
    InjectionMode,
    TestResult,
    TestStatus,
)
from test_lab.safety_guard import SafetyGuard
from test_lab.baseline_manager import BaselineManager
from test_lab.catalog import FaultCatalog
from test_lab.verifier import FaultVerifier
from test_lab.test_runner import TestRunner
from test_lab.solvability_report import SolvabilityReporter
from test_lab.adapters.path_injector import PathFaultInjector
from test_lab.adapters.base import get_platform_adapter
from execution_tier import ExecutionTier, select_execution_tier


class TestFaultInjectionLab(unittest.TestCase):
    def setUp(self):
        # Enable development mode for tests
        os.environ["APP_MODE"] = "DEVELOPMENT"
        os.environ["PC_DOCTOR_FAULT_INJECTION_ENABLED"] = "true"
        self.catalog = FaultCatalog()
        self.baseline_file = Path(__file__).parent / "test_baselines_temp.json"
        self.baseline_manager = BaselineManager(storage_path=self.baseline_file)
        self.verifier = FaultVerifier()
        self.runner = TestRunner(
            catalog=self.catalog,
            baseline_manager=self.baseline_manager,
            verifier=self.verifier,
        )

    def tearDown(self):
        if self.baseline_file.exists():
            try:
                self.baseline_file.unlink()
            except Exception:
                pass

    # 1. Fault definition validation
    def test_01_fault_definition_validation(self):
        defn = FaultDefinition(
            fault_id="TEST_FAULT",
            target="Git",
            capability=FaultCapability.PATH,
            scope="MACHINE",
            platforms=["windows", "linux"],
            risk_class=FaultRiskClass.CONTROLLED,
            reversible=True,
            requires_admin=True,
            verification="where.exe git",
            injector="PATH_ENTRY_REMOVAL",
        )
        d = defn.to_dict()
        self.assertEqual(d["fault_id"], "TEST_FAULT")
        self.assertEqual(d["capability"], "PATH")
        self.assertEqual(d["risk_class"], "CONTROLLED")

        reconstructed = FaultDefinition.from_dict(d)
        self.assertEqual(reconstructed.fault_id, "TEST_FAULT")
        self.assertEqual(reconstructed.capability, FaultCapability.PATH)

    # 2. Unsupported fault rejected
    def test_02_unsupported_fault_rejected(self):
        res = asyncio.run(self.runner.run_test_by_id("NON_EXISTENT_FAULT_XYZ"))
        self.assertEqual(res.result, TestStatus.BLOCKED_EXPECTED)
        self.assertIn("not found in catalog", res.message)

    # 3. Non-reversible real fault rejected
    def test_03_non_reversible_real_fault_rejected(self):
        unsafe_fault = FaultDefinition(
            fault_id="UNSAFE_REAL_CORRUPTION",
            target="Kernel",
            capability=FaultCapability.DRIVER,
            risk_class=FaultRiskClass.UNSAFE,
            reversible=False,
            simulation_mode=InjectionMode.REAL,
        )
        allowed, reason = SafetyGuard.validate_fault(unsafe_fault)
        self.assertFalse(allowed)
        self.assertIn("Non-reversible faults MUST NOT be executed on real machine", reason)

        res = asyncio.run(self.runner.run_test(unsafe_fault, confirm_mutation=True))
        self.assertEqual(res.result, TestStatus.BLOCKED_EXPECTED)

    # 4. Baseline capture
    def test_04_baseline_capture(self):
        record = self.baseline_manager.capture_baseline(
            fault_id="TEST_GIT_PATH",
            target_identity="Git",
            platform_name="windows",
            affected_resource="MACHINE_PATH",
            original_state={"path": "C:\\Windows\\system32;C:\\Program Files\\Git\\cmd"},
            restoration_strategy="EXACT_OVERWRITE",
        )
        self.assertIsNotNone(record.test_id)
        self.assertEqual(record.cleanup_status, "PENDING")
        self.assertIn(record, self.baseline_manager.list_pending())

    # 5. Git PATH removal
    def test_05_git_path_removal(self):
        injector = PathFaultInjector()
        with patch.object(injector, "_get_raw_path", return_value="C:\\Windows\\system32;C:\\Program Files\\Git\\cmd;C:\\Program Files\\nodejs"):
            with patch.object(injector, "_set_raw_path") as mock_set:
                with patch.object(injector, "verify_fault_present", return_value=True):
                    status, msg = injector.inject(
                        target_entry="C:\\Program Files\\Git\\cmd",
                        scope="MACHINE",
                    )
                    self.assertEqual(status, "INJECTED")
                    mock_set.assert_called_once()
                    args, _ = mock_set.call_args
                    self.assertNotIn("C:\\Program Files\\Git\\cmd", args[0])
                    self.assertIn("C:\\Windows\\system32", args[0])
                    self.assertIn("C:\\Program Files\\nodejs", args[0])

    # 6. Git fault verification
    def test_06_git_fault_verification(self):
        injector = PathFaultInjector()
        with patch.object(injector, "_get_raw_path", return_value="C:\\Windows\\system32;C:\\Program Files\\nodejs"):
            present = injector.verify_fault_present(
                target_entry="C:\\Program Files\\Git\\cmd",
                scope="MACHINE",
            )
            self.assertTrue(present)

    # 7. Git restoration
    def test_07_git_restoration(self):
        injector = PathFaultInjector()
        baseline = BaselineRecord(
            test_id="test-123",
            timestamp="2026-09-12T00:00:00Z",
            fault_id="GIT_MACHINE_PATH_MISSING",
            target_identity="Git",
            platform="windows",
            affected_resource="MACHINE_PATH",
            original_state={"path": "C:\\Windows\\system32;C:\\Program Files\\Git\\cmd", "scope": "MACHINE"},
        )
        with patch.object(injector, "_set_raw_path") as mock_set:
            with patch.object(injector, "verify_restored", return_value=True):
                status, msg = injector.restore(baseline)
                self.assertEqual(status, "RESTORED")
                mock_set.assert_called_once_with("C:\\Windows\\system32;C:\\Program Files\\Git\\cmd", "MACHINE")

    # 8. Restoration verification
    def test_08_restoration_verification(self):
        injector = PathFaultInjector()
        baseline = BaselineRecord(
            test_id="test-123",
            timestamp="2026-09-12T00:00:00Z",
            fault_id="GIT_MACHINE_PATH_MISSING",
            target_identity="Git",
            platform="windows",
            affected_resource="MACHINE_PATH",
            original_state={"path": "C:\\Windows\\system32;C:\\Program Files\\Git\\cmd", "scope": "MACHINE"},
        )
        with patch.object(injector, "_get_raw_path", return_value="C:\\Windows\\system32;C:\\Program Files\\Git\\cmd"):
            verified = injector.verify_restored(baseline)
            self.assertTrue(verified)

    # 9. User PATH fault
    def test_09_user_path_fault(self):
        fault = self.catalog.get("USER_PATH_MISSING")
        self.assertIsNotNone(fault)
        self.assertEqual(fault.scope, "USER")
        self.assertFalse(fault.requires_admin)

    # 10. Review-only Python scenario
    def test_10_review_only_python_scenario(self):
        fault = self.catalog.get("PYTHON_MULTIPLE_VERSIONS_REVIEW")
        self.assertIsNotNone(fault)
        self.assertEqual(fault.expected_behavior, "REVIEW_REQUIRED")
        res = asyncio.run(self.runner.run_test(fault, confirm_mutation=False))
        self.assertEqual(res.result, TestStatus.PASS_EXPECTED_REVIEW)
        self.assertIn("REVIEW_REQUIRED", res.message)

    # 11. Simulation-only dangerous fault
    def test_11_simulation_only_dangerous_fault(self):
        fault = self.catalog.get("DRIVER_CORRUPTION_SIMULATED")
        self.assertIsNotNone(fault)
        self.assertEqual(fault.simulation_mode, InjectionMode.SIMULATED)
        res = asyncio.run(self.runner.run_test(fault, confirm_mutation=False))
        self.assertEqual(res.result, TestStatus.SIMULATION_ONLY)
        self.assertFalse(res.baseline_captured)

    # 12. Normal PC Doctor pipeline invoked after injection
    def test_12_normal_pc_doctor_pipeline_invoked(self):
        from dev_environment_detector import ToolDiagnosis, ToolHealthStatus, dev_environment_detector
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        mock_diag = ToolDiagnosis(
            tool_id="git",
            display_name="Git",
            status=ToolHealthStatus.INSTALLED_BUT_PATH_MISSING,
            installed=True,
            discovered_path="C:\\Program Files\\Git\\cmd\\git.exe",
            required_path_dir="C:\\Program Files\\Git\\cmd",
            diagnosis_message="Git binary found but missing from Machine PATH",
            repair_command="powershell -Command Add-Path",
            risk="Low",
            requires_elevation=False,
            path_scope="MACHINE",
            executable="git",
            arguments=[],
            verification_command=["git", "--version"],
        )
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Fault injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.verifier, "verify_repair", return_value=(True, {"L1": True, "L2": True, "L3": True, "L5": True}, "Verified")):
                with patch.object(dev_environment_detector, "diagnose_tool", return_value=mock_diag):
                    with patch("test_lab.test_runner.engine.stream_run", return_value=[{"type": "done", "ok": True}]):
                        res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                        self.assertTrue(res.detected)
                        self.assertTrue(res.diagnosed)
                        self.assertTrue(res.recipe_resolved)
                        self.assertTrue(res.safety_passed)
                        self.assertIsNotNone(res.tier)

    # 13. Independent verification (L1-L5)
    def test_13_independent_verification(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="git version 2.45.0\n")
            levels = self.verifier.verify_l1_l5(
                target_identity="Git",
                capability=FaultCapability.PATH,
                expected_entry="C:\\Program Files\\Git\\cmd",
                scope="MACHINE",
                mock_mode=True,
            )
            self.assertTrue(levels["L1"])
            self.assertTrue(levels["L2"])
            self.assertTrue(levels["L3"])
            self.assertTrue(levels["L5"])

    # 14. Duplicate PATH entries are not created
    def test_14_duplicate_path_entries_not_created(self):
        injector = PathFaultInjector()
        raw = "C:\\Windows\\system32;C:\\Program Files\\Git\\cmd;C:\\Program Files\\Git\\cmd"
        normalized = injector._normalize_path(raw)
        self.assertEqual(len([p for p in normalized if p.lower() == "c:\\program files\\git\\cmd"]), 1)

    # 15. Unrelated PATH entries remain unchanged
    def test_15_unrelated_path_entries_remain_unchanged(self):
        injector = PathFaultInjector()
        raw = "C:\\Windows\\system32;C:\\Program Files\\Git\\cmd;C:\\Tools\\custom"
        with patch.object(injector, "_get_raw_path", return_value=raw):
            with patch.object(injector, "_set_raw_path") as mock_set:
                with patch.object(injector, "verify_fault_present", return_value=True):
                    injector.inject(target_entry="C:\\Program Files\\Git\\cmd", scope="MACHINE")
                    saved_path = mock_set.call_args[0][0]
                    self.assertIn("C:\\Windows\\system32", saved_path)
                    self.assertIn("C:\\Tools\\custom", saved_path)
                    self.assertNotIn("C:\\Program Files\\Git\\cmd", saved_path)

    # 16. Fault cleanup occurs on success
    def test_16_fault_cleanup_occurs_on_success(self):
        from dev_environment_detector import ToolDiagnosis, ToolHealthStatus, dev_environment_detector
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        mock_diag = ToolDiagnosis(
            tool_id="git",
            display_name="Git",
            status=ToolHealthStatus.INSTALLED_BUT_PATH_MISSING,
            installed=True,
            discovered_path="C:\\Program Files\\Git\\cmd\\git.exe",
            required_path_dir="C:\\Program Files\\Git\\cmd",
            diagnosis_message="Git binary found but missing from Machine PATH",
            repair_command="powershell -Command Add-Path",
            risk="Low",
            requires_elevation=False,
            path_scope="MACHINE",
            executable="git",
            arguments=[],
            verification_command=["git", "--version"],
        )
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.verifier, "verify_repair", return_value=(True, {"L1": True, "L2": True, "L3": True, "L5": True}, "Verified")):
                with patch.object(dev_environment_detector, "diagnose_tool", return_value=mock_diag):
                    with patch("test_lab.test_runner.engine.stream_run", return_value=[{"type": "done", "ok": True}]):
                        res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                        self.assertEqual(res.result, TestStatus.PASS)
                        self.assertTrue(res.baseline_restored)
                        self.assertTrue(res.restoration_verified)
                        self.assertEqual(len(self.baseline_manager.list_pending()), 0)

    # 17. Fault cleanup occurs after repair failure
    def test_17_fault_cleanup_occurs_after_repair_failure(self):
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.runner, "_execute_pipeline", side_effect=RuntimeError("Repair step failed")):
                res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                self.assertEqual(res.result, TestStatus.FAILED_EXECUTION)
                # Fail-safe cleanup MUST still have run
                self.assertTrue(res.baseline_restored)
                self.assertTrue(res.restoration_verified)
                mock_adapter.restore.assert_called_once()

    # 18. Fault cleanup occurs after verification failure
    def test_18_fault_cleanup_occurs_after_verification_failure(self):
        from dev_environment_detector import ToolDiagnosis, ToolHealthStatus, dev_environment_detector
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        mock_diag = ToolDiagnosis(
            tool_id="git",
            display_name="Git",
            status=ToolHealthStatus.INSTALLED_BUT_PATH_MISSING,
            installed=True,
            discovered_path="C:\\Program Files\\Git\\cmd\\git.exe",
            required_path_dir="C:\\Program Files\\Git\\cmd",
            diagnosis_message="Git binary found but missing from Machine PATH",
            repair_command="powershell -Command Add-Path",
            risk="Low",
            requires_elevation=False,
            path_scope="MACHINE",
            executable="git",
            arguments=[],
            verification_command=["git", "--version"],
        )
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.verifier, "verify_repair", return_value=(False, {"L1": True, "L2": False, "L3": False, "L5": False}, "L2 failed")):
                with patch.object(dev_environment_detector, "diagnose_tool", return_value=mock_diag):
                    with patch("test_lab.test_runner.engine.stream_run", return_value=[{"type": "done", "ok": True}]):
                        res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                        self.assertEqual(res.result, TestStatus.FAILED_VERIFICATION)
                        self.assertTrue(res.baseline_restored)
                        mock_adapter.restore.assert_called_once()


    # 19. Fault cleanup occurs after cancellation
    def test_19_fault_cleanup_occurs_after_cancellation(self):
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.runner, "_execute_pipeline", side_effect=asyncio.CancelledError()):
                res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                self.assertTrue(res.baseline_restored)
                mock_adapter.restore.assert_called_once()

    # 20. Test timeout produces cleanup
    def test_20_test_timeout_produces_cleanup(self):
        fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
        with patch("test_lab.test_runner.get_platform_adapter") as mock_adapter_factory:
            mock_adapter = MagicMock()
            mock_adapter.inject.return_value = ("INJECTED", "Injected")
            mock_adapter.verify_fault_present.return_value = True
            mock_adapter.restore.return_value = ("RESTORED", "Restored")
            mock_adapter.verify_restored.return_value = True
            mock_adapter_factory.return_value = mock_adapter

            with patch.object(self.runner, "_execute_pipeline", side_effect=asyncio.TimeoutError()):
                res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True, custom_target_entry="C:\\Program Files\\Git\\cmd"))
                self.assertTrue(res.baseline_restored)
                mock_adapter.restore.assert_called_once()

    # 21. Tier mutation tests
    def test_21_tier_mutation_tests(self):
        from recipe_engine import StructuredRecipe, RecipeOperation, RepairStrategy, RecipeLifecycle
        recipe = StructuredRecipe(
            recipe_id="test_recipe_tier",
            recipe_version=1,
            identity_id="git",
            operation=RecipeOperation.REPAIR,
            os="Windows",
            architecture="Any",
            package_manager="native",
            executable="git",
            arguments=[],
            verification_command="git --version",
            expected_result={},
            risk_base="Low",
            official_url="",
            source="STATIC_DB",
            supported_environment={},
            repair_strategy=RepairStrategy.NATIVE,
            validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
            last_validated_at="",
            validation_frequency=86400,
        )

        # Nominal case: High trust, low risk, high confidence -> TIER_1_FAST
        tier1, _ = select_execution_tier(recipe, trust_score=1.0, risk_score=0.1, confidence_score=0.95, machine_state={"conflicts": False, "unusual_state": False})
        self.assertEqual(tier1, ExecutionTier.TIER_1_FAST)

        # Risk increased -> TIER_2_CONTROLLED
        tier2, _ = select_execution_tier(recipe, trust_score=0.9, risk_score=0.6, confidence_score=0.8, machine_state={"conflicts": False, "unusual_state": False})
        self.assertEqual(tier2, ExecutionTier.TIER_2_CONTROLLED)

        # High risk -> TIER_3_FULL_PROTECTED
        tier3, _ = select_execution_tier(recipe, trust_score=0.8, risk_score=0.85, confidence_score=0.4, machine_state={"conflicts": False, "unusual_state": False})
        self.assertEqual(tier3, ExecutionTier.TIER_3_FULL_PROTECTED)

        # Risk exceeds acceptable limits -> BLOCKED
        tier4, _ = select_execution_tier(recipe, trust_score=1.0, risk_score=0.95, confidence_score=0.9, machine_state={"conflicts": False, "unusual_state": False})
        self.assertEqual(tier4, ExecutionTier.BLOCKED)


    # 22. Cross-platform adapter selection
    def test_22_cross_platform_adapter_selection(self):
        adapter_win = get_platform_adapter("PATH_ENTRY_REMOVAL", "windows")
        self.assertIsInstance(adapter_win, PathFaultInjector)

        adapter_linux = get_platform_adapter("PATH_ENTRY_REMOVAL", "linux")
        self.assertIsNotNone(adapter_linux)

        adapter_darwin = get_platform_adapter("PATH_ENTRY_REMOVAL", "darwin")
        self.assertIsNotNone(adapter_darwin)

    # 23. Production mode rejects fault injection
    def test_23_production_mode_rejects_fault_injection(self):
        try:
            os.environ["APP_MODE"] = "PRODUCTION"
            os.environ["PC_DOCTOR_FAULT_INJECTION_ENABLED"] = "false"
            allowed, reason = SafetyGuard.check_environment()
            self.assertFalse(allowed)
            self.assertIn("disabled in production", reason)

            fault = self.catalog.get("GIT_MACHINE_PATH_MISSING")
            res = asyncio.run(self.runner.run_test(fault, confirm_mutation=True))
            self.assertEqual(res.result, TestStatus.BLOCKED_EXPECTED)
            self.assertIn("disabled in production", res.message.lower())
        finally:
            # Revert to dev mode
            os.environ["APP_MODE"] = "DEVELOPMENT"
            os.environ["PC_DOCTOR_FAULT_INJECTION_ENABLED"] = "true"


if __name__ == "__main__":
    unittest.main()
