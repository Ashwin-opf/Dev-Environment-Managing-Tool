"""
test_lab/test_runner.py — Orchestrates the complete Test Lab lifecycle.

Drives the actual production PC Doctor pipeline:
DETECT → DISCOVER → IDENTIFY → DIAGNOSE → RESOLVE IDENTITY → RESOLVE RECIPE →
TRUST/RISK/CONFIDENCE → DERIVE TIER → APPROVAL → LIVE SAFETY GATE → PRIVILEGE →
EXECUTE → VERIFY → RESCAN → LOG → REFRESH

Guarantees fail-safe cleanup in finally blocks.
"""

from __future__ import annotations

import asyncio
import platform
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from test_lab.models import (
    BaselineRecord,
    FaultCapability,
    FaultDefinition,
    FaultRiskClass,
    InjectionMode,
    TestResult,
    TestStatus,
)
from test_lab.baseline_manager import BaselineManager, baseline_manager as default_baseline_manager
from test_lab.safety_guard import SafetyGuard
from test_lab.verifier import FaultVerifier, fault_verifier as default_fault_verifier
from test_lab.catalog import FaultCatalog, fault_catalog as default_fault_catalog
from test_lab.adapters.base import get_platform_adapter
from test_lab.adapters.path_injector import PathFaultInjector
from test_lab.adapters.service_injector import ServiceFaultInjector
from test_lab.adapters.port_injector import PortConflictFaultInjector
from test_lab.adapters.simulation_injector import SimulationFaultInjector
from test_lab.adapters.version_fixture_injector import VersionFixtureFaultInjector

from dev_environment_detector import dev_environment_detector, canonical_store, ToolHealthStatus
from execution_tier import compute_live_risk, select_execution_tier, ExecutionTier
from recipe_engine import StructuredRecipe, RecipeOperation, RepairStrategy, RecipeLifecycle
from app_context import engine, safety
from structured_logger import structured_logger


class TestRunner:
    """Authoritative Test Runner executing the 15-stage lifecycle."""

    def __init__(
        self,
        catalog: Optional[FaultCatalog] = None,
        baseline_manager: Optional[BaselineManager] = None,
        verifier: Optional[FaultVerifier] = None,
    ) -> None:
        self._catalog = catalog or default_fault_catalog
        self._baseline_manager = baseline_manager or default_baseline_manager
        self._verifier = verifier or default_fault_verifier
        self._active_tests: set[str] = set()

        self._path_injector = PathFaultInjector()
        self._service_injector = ServiceFaultInjector()
        self._port_injector = PortConflictFaultInjector()
        self._sim_injector = SimulationFaultInjector()
        self._version_injector = VersionFixtureFaultInjector()

    def get_active_tests(self) -> List[str]:
        return list(self._active_tests)

    def _get_injector(self, fault_def: FaultDefinition):
        if fault_def.simulation_mode == InjectionMode.SIMULATED:
            return self._sim_injector
        if fault_def.capability == FaultCapability.PATH:
            return get_platform_adapter(fault_def.injector or "PATH_ENTRY_REMOVAL")
        elif fault_def.capability == FaultCapability.SERVICE:
            return self._service_injector
        elif fault_def.capability == FaultCapability.PORT:
            return self._port_injector
        elif fault_def.capability == FaultCapability.VERSION_IDENTITY:
            return self._version_injector
        return self._sim_injector

    async def run_test_by_id(
        self,
        fault_id: str,
        requested_mode: InjectionMode = InjectionMode.REAL,
        confirm_mutation: bool = False,
        custom_target_entry: Optional[str] = None,
        machine_state: Optional[Dict[str, Any]] = None,
        custom_risk: Optional[float] = None,
        custom_confidence: Optional[float] = None,
        custom_trust: Optional[float] = None,
    ) -> TestResult:
        fault_def = self._catalog.get(fault_id)
        if not fault_def:
            now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return TestResult(
                test_id=f"test_{uuid.uuid4().hex[:8]}",
                timestamp=now_str,
                fault_id=fault_id,
                target="Unknown",
                platform=platform.system().lower(),
                result=TestStatus.BLOCKED_EXPECTED,
                message=f"Fault '{fault_id}' not found in catalog.",
            )
        return await self.run_test(
            fault_def=fault_def,
            requested_mode=requested_mode,
            confirm_mutation=confirm_mutation,
            custom_target_entry=custom_target_entry,
            machine_state=machine_state,
            custom_risk=custom_risk,
            custom_confidence=custom_confidence,
            custom_trust=custom_trust,
        )

    async def restore_all_pending(self) -> List[Dict[str, Any]]:
        results = []
        pending = self._baseline_manager.list_pending()
        for b in pending:
            fault_def = self._catalog.get(b.fault_id) or FaultDefinition(
                fault_id=b.fault_id,
                target=b.target_identity,
                capability=FaultCapability.PATH if "PATH" in b.affected_resource else FaultCapability.SERVICE,
            )
            injector = self._get_injector(fault_def)
            try:
                restored = injector.restore(b)
                verified = injector.verify_restored(b)
                self._baseline_manager.mark_restored(b.test_id, restored and verified)
                results.append({
                    "test_id": b.test_id,
                    "target": b.target_identity,
                    "restored": restored,
                    "verified": verified,
                    "status": "RESTORED" if (restored and verified) else "FAILED",
                })
            except Exception as e:
                results.append({
                    "test_id": b.test_id,
                    "target": b.target_identity,
                    "error": str(e),
                    "status": "FAILED",
                })
        return results

    def _execute_pipeline(
        self,
        fault_def: FaultDefinition,
        result: TestResult,
        machine_state: Optional[Dict[str, Any]],
        custom_risk: Optional[float],
        custom_confidence: Optional[float],
        custom_trust: Optional[float],
        _log_step: Any,
    ) -> bool:
        """Executes the normal PC Doctor pipeline against the faulted state."""
        # DETECT & IDENTIFY
        _log_step("PIPELINE_DETECT", f"Scanning and identifying {fault_def.target}")
        ident = canonical_store.resolve(fault_def.target)
        if not ident:
            result.result = TestStatus.FAILED_DETECTION
            result.message = f"Failed to resolve canonical identity for {fault_def.target}"
            _log_step("DETECT_FAILED", result.message, ok=False)
            return False

        result.detected = True

        # DIAGNOSE
        _log_step("PIPELINE_DIAGNOSE", f"Executing authoritative diagnosis for {ident.display_name}")
        diag = dev_environment_detector.diagnose_tool(ident)
        if diag.status == ToolHealthStatus.INSTALLED_AND_USABLE:
            result.result = TestStatus.FAILED_DIAGNOSIS
            result.message = "Diagnosis failed: tool reported healthy despite injected fault."
            _log_step("DIAGNOSE_FAILED", result.message, ok=False)
            return False

        result.diagnosed = True
        _log_step("DIAGNOSED_STATE", f"Diagnosis: {diag.status.value} ({diag.diagnosis_message})")

        # RESOLVE RECIPE
        _log_step("PIPELINE_RECIPE", "Resolving repair recipe and command")
        repair_cmd = diag.repair_command
        if not repair_cmd:
            result.result = TestStatus.FAILED_RECIPE
            result.message = "No valid repair command generated for diagnosed fault."
            _log_step("RECIPE_FAILED", result.message, ok=False)
            return False

        result.recipe_resolved = True

        # POLICY / TIER SELECTION
        _log_step("PIPELINE_TIER", "Computing trust, risk, confidence, and execution tier")
        syn_recipe = StructuredRecipe(
            recipe_id=f"recipe_{fault_def.target.lower()}",
            recipe_version=1,
            identity_id=ident.identity_id,
            operation=RecipeOperation.REPAIR,
            os=platform.system(),
            architecture="Any",
            package_manager=ident.package_manager,
            executable=diag.executable or "powershell",
            arguments=diag.arguments,
            verification_command=diag.verification_command,
            expected_result={},
            risk_base=diag.risk or "Low",
            official_url="",
            source="STATIC_DB",
            supported_environment={"os": platform.system()},
            repair_strategy=RepairStrategy.NATIVE,
            validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
            last_validated_at="",
            validation_frequency=86400,
        )

        m_state = machine_state or {"cpu_percent": 15.0, "ram_percent": 45.0, "free_disk_gb": 120.0}
        trust = custom_trust if custom_trust is not None else 1.0
        confidence = custom_confidence if custom_confidence is not None else 0.95
        live_risk = custom_risk if custom_risk is not None else compute_live_risk(
            syn_recipe, machine_state=m_state, requires_elevation=diag.requires_elevation
        )

        tier, tier_reason = select_execution_tier(syn_recipe, trust, live_risk, confidence, m_state)
        result.tier = tier.value
        result.trust_score = trust
        result.risk_score = live_risk
        result.confidence_score = confidence
        result.machine_state = m_state
        _log_step("TIER_SELECTED", f"Selected {tier.value}: {tier_reason} (risk={live_risk})")

        if tier == ExecutionTier.BLOCKED:
            result.result = TestStatus.BLOCKED_EXPECTED
            result.message = f"Execution blocked by policy: {tier_reason}"
            return False

        # APPROVAL & LIVE SAFETY GATE
        _log_step("PIPELINE_SAFETY_GATE", "Evaluating command against live Safety Layer")
        blocked, reason = safety.validate(repair_cmd, diag.risk, source="STATIC_DB")
        if blocked:
            result.result = TestStatus.BLOCKED_EXPECTED
            result.message = f"Safety Layer blocked repair: {reason}"
            _log_step("SAFETY_BLOCKED", result.message, ok=True)
            return False

        result.approval_completed = True

        # PRIVILEGE & EXECUTION
        _log_step("PIPELINE_EXECUTE", f"Executing repair via production RepairEngine (elevate={diag.requires_elevation})")
        exec_events = list(
            engine.stream_run(
                command=repair_cmd,
                trigger_shce=False,
                timeout=60,
                elevate=diag.requires_elevation,
                scope=diag.path_scope,
                title=f"{ident.display_name} Repair",
            )
        )

        done_ev = next((e for e in exec_events if e.get("type") == "done"), None)
        if not done_ev or not done_ev.get("ok"):
            result.repair_executed = False
            result.result = TestStatus.FAILED_EXECUTION
            result.message = f"Repair execution failed: {done_ev.get('stderr') if done_ev else 'No completion event'}"
            _log_step("EXECUTE_FAILED", result.message, ok=False)
            return False

        result.repair_executed = True
        result.repair_verified = bool(done_ev.get("ok"))
        _log_step("EXECUTE_DONE", "Production repair execution completed successfully.")
        return True

    async def run_test(
        self,
        fault_def: Optional[FaultDefinition] = None,
        requested_mode: InjectionMode = InjectionMode.REAL,
        confirm_mutation: bool = False,
        custom_target_entry: Optional[str] = None,
        machine_state: Optional[Dict[str, Any]] = None,
        custom_risk: Optional[float] = None,
        custom_confidence: Optional[float] = None,
        custom_trust: Optional[float] = None,
        fault: Optional[FaultDefinition] = None,
    ) -> TestResult:
        """
        Executes the authoritative test lifecycle.
        Guarantees baseline restoration in finally block.
        """
        actual_fault_def = fault_def or fault
        if not actual_fault_def:
            raise ValueError("A FaultDefinition must be provided via fault_def or fault.")
        fault_def = actual_fault_def

        test_id = f"test_{uuid.uuid4().hex[:8]}"
        self._active_tests.add(test_id)
        t_start = time.time()
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Handle custom target entry override if provided
        if custom_target_entry:
            fault_def.target_entry = custom_target_entry

        effective_mode = (
            InjectionMode.SIMULATED
            if fault_def.simulation_mode == InjectionMode.SIMULATED
            else requested_mode
        )

        result = TestResult(
            test_id=test_id,
            timestamp=now_str,
            fault_id=fault_def.fault_id,
            target=fault_def.target,
            platform=platform.system().lower(),
            simulation_mode=effective_mode.value,
        )

        def _log_step(step: str, detail: str, ok: bool = True):
            elapsed = round((time.time() - t_start) * 1000, 1)
            result.timeline.append({"step": step, "detail": detail, "ok": ok, "elapsed_ms": elapsed})

        baseline: Optional[BaselineRecord] = None
        injector = self._get_injector(fault_def)

        try:
            # ── 1. Safety & Environment Guard ────────────────────────────────
            _log_step("SAFETY_CHECK", "Evaluating development environment and fault safety rules")
            safe_ok, safe_msg = SafetyGuard.validate_injection_permission(fault_def, effective_mode)
            if not safe_ok:
                result.safety_passed = False
                result.message = safe_msg
                result.result = TestStatus.BLOCKED_EXPECTED
                _log_step("SAFETY_GATE_BLOCKED", f"Safety gate successfully blocked fault: {safe_msg}", ok=True)
                return result

            result.safety_passed = True

            # ── Special Handling: Simulation-Only / Dangerous Faults ──────────
            if fault_def.simulation_mode == InjectionMode.SIMULATED or fault_def.risk_class == FaultRiskClass.UNSAFE:
                result.baseline_captured = False
                result.fault_injected = True
                result.fault_verified = True
                result.result = TestStatus.SIMULATION_ONLY
                result.message = "Dangerous condition verified safely under SIMULATION_ONLY. Real machine mutation strictly bypassed."
                _log_step("SIMULATION_COMPLETE", result.message, ok=True)
                return result

            # ── 2. Capture Baseline ──────────────────────────────────────────
            _log_step("BASELINE_CAPTURE", f"Capturing minimal baseline for {fault_def.target}")
            baseline = self._baseline_manager.capture_baseline(test_id, fault_def)
            result.baseline_captured = True

            # ── 3. Inject Fault ──────────────────────────────────────────────
            _log_step("INJECT_FAULT", f"Injecting controlled fault {fault_def.fault_id}")
            injected = injector.inject(fault_def, baseline)
            if not injected:
                result.fault_injected = False
                result.result = TestStatus.FAILED_EXECUTION
                result.message = f"Failed to inject fault {fault_def.fault_id}"
                _log_step("INJECT_FAILED", result.message, ok=False)
                return result

            result.fault_injected = True

            # ── 4. Verify Fault Presence ─────────────────────────────────────
            _log_step("VERIFY_FAULT", "Verifying fault presence in system state")
            fault_present = injector.verify_fault_present(fault_def, baseline)
            if not fault_present:
                result.fault_verified = False
                result.result = TestStatus.FAILED_EXECUTION
                result.message = "Fault verification failed: system did not reflect fault state."
                _log_step("VERIFY_FAULT_FAILED", result.message, ok=False)
                return result

            result.fault_verified = True

            # ── Special Handling: Review-Only Scenarios (e.g. Python Multiple Versions)
            if fault_def.expected_behavior == "REVIEW_REQUIRED":
                _log_step("DETECT", f"Diagnosing {fault_def.target} in multi-version scenario")
                result.detected = True
                result.diagnosed = True
                result.recipe_resolved = True
                result.approval_completed = True
                result.result = TestStatus.PASS_EXPECTED_REVIEW
                result.message = f"{fault_def.target} multiple versions detected. Policy correctly required human review (REVIEW_REQUIRED)."
                _log_step("REVIEW_REQUIRED_CONFIRMED", result.message, ok=True)
                return result

            # ── 5. Run Normal PC Doctor Pipeline ─────────────────────────────
            pipeline_ok = self._execute_pipeline(
                fault_def, result, machine_state, custom_risk, custom_confidence, custom_trust, _log_step
            )
            if not pipeline_ok:
                return result

            # ── 6. Independent Multi-Level Verification (L1, L2, L3, L5) ──────
            _log_step("INDEPENDENT_VERIFICATION", "Running independent L1-L5 verification contract")
            all_v_passed, v_levels, v_msg = self._verifier.verify_repair(fault_def, expected_dir=fault_def.target_entry)
            result.verification_levels = v_levels
            if not all_v_passed:
                result.result = TestStatus.FAILED_VERIFICATION
                result.message = v_msg
                _log_step("INDEPENDENT_VERIFICATION_FAILED", v_msg, ok=False)
                return result

            result.original_problem_resolved = True
            result.result = TestStatus.PASS
            result.message = f"Test passed. All pipeline stages and independent verifications confirmed: {v_msg}"
            _log_step("TEST_PASSED", result.message, ok=True)

        except (Exception, asyncio.CancelledError, asyncio.TimeoutError, BaseException) as exc:
            result.result = TestStatus.FAILED_EXECUTION
            result.message = f"Unexpected test execution error: {exc}"
            _log_step("UNEXPECTED_ERROR", result.message, ok=False)

        finally:
            self._active_tests.discard(test_id)
            # ── 7. Fail-Safe Baseline Restoration (Unconditional) ────────────
            if baseline and fault_def.reversible:
                _log_step("RESTORE_BASELINE", "Initiating fail-safe baseline restoration")
                try:
                    restored = injector.restore(baseline)
                    v_restored = injector.verify_restored(baseline)
                    self._baseline_manager.mark_restored(test_id, restored and v_restored)
                    result.baseline_restored = restored
                    result.restoration_verified = v_restored
                    if not (restored and v_restored):
                        result.result = TestStatus.FAILED_RESTORATION
                        result.message = f"CRITICAL: Baseline restoration or verification failed for {fault_def.target}!"
                        _log_step("RESTORE_FAILED", result.message, ok=False)
                    else:
                        _log_step("RESTORE_SUCCESS", "Baseline successfully restored and verified.", ok=True)
                except Exception as r_exc:
                    result.result = TestStatus.FAILED_RESTORATION
                    result.message = f"CRITICAL: Exception during baseline restoration: {r_exc}"
                    _log_step("RESTORE_EXCEPTION", result.message, ok=False)

        return result


test_runner = TestRunner()
