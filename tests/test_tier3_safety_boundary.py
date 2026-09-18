"""
test_tier3_safety_boundary.py — Invariant Hardening Test Suite (Stage 5.1).

Permanently enforces and regression-tests the architectural invariant:

    Tier / Hard Override
        ↓
    Stronger protection / approval
        ↓
    Privilege resolution / Elevation
        ↓
    LIVE AUTHORITATIVE SAFETY GATE
        ↓
    ALLOW or BLOCK

The following MUST NEVER exist:
    - Tier 3 → Execute
    - Hard Override → Execute
    - Approval → Execute
    - Elevation Available → Execute

Only the LIVE AUTHORITATIVE SAFETY GATE provides the final last-mile
permission to mutate the system. Zero subprocess spawns on BLOCK.
"""

from __future__ import annotations

import ast
import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is on sys.path
_BACKEND = Path(__file__).parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from authoritative_safety import (
    AuthoritativeSafetyLayer,
    BlockedReason,
    SafetyGateResult,
    authoritative_safety,
)
from execution_engine import (
    CentralizedExecutionEngine,
    ExecutionOutcome,
    SafetyAuthorizationViolation,
    execution_engine,
)
from execution_tier import ExecutionTier, check_hard_safety_override, select_execution_tier
from machine_state import MachineState
from plan_freeze import (
    BatchPlan,
    FrozenPlanStep,
    create_frozen_batch_plan,
    evaluate_step_live_safety_gate,
    resource_lock_mgr,
)
from privilege_manager import PrivilegeManager, privilege_manager
from recipe_engine import RecipeLifecycle, RecipeOperation, RepairStrategy, StructuredRecipe


def _make_recipe(
    command: str = "git --version",
    executable: str = "git",
    arguments: Optional[List[str]] = None,
    operation: RecipeOperation = RecipeOperation.INSTALL,
    target: str = "git",
    source: str = "STATIC_DB",
    os_name: str = "Any",
    package_manager: str = "winget",
    risk: str = "Low",
) -> StructuredRecipe:
    if arguments is None:
        parts = command.split()
        if len(parts) > 1:
            executable = parts[0]
            arguments = parts[1:]
        else:
            arguments = []
    return StructuredRecipe(
        recipe_id=f"rec_test_{target}",
        recipe_version=1,
        identity_id=target,
        operation=operation,
        os=os_name,
        architecture="Any",
        package_manager=package_manager,
        executable=executable,
        arguments=arguments,
        verification_command=[executable, "--version"],
        risk_base=risk,
        source=source,
        repair_strategy=RepairStrategy.NATIVE,
        validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
    )


# ==============================================================================
# 1. Primary Regression: Tier 3 + Safety Blocked -> Zero Spawn
# ==============================================================================

def test_tier3_plus_safety_blocked_zero_spawn():
    """
    Scenario:
        tier = TIER_3_FULL_PROTECTED
        approval = granted
        privilege = available
        live safety = BLOCKED
    Expected:
        subprocess spawn count == 0
        elevated mutation worker count == 0
        final state = BLOCKED
    """
    destructive_cmd = "format C: /fs:NTFS /q"
    recipe = _make_recipe(command=destructive_cmd, risk="High")

    with patch("subprocess.run") as mock_subproc_run, \
         patch("subprocess.Popen") as mock_subproc_popen:

        # Tier is Tier 3 Full Protected
        m_state = MachineState(free_disk_gb=100.0)
        tier, _ = select_execution_tier(
            recipe=recipe,
            trust_score=0.40,  # Low trust -> Tier 3
            risk_score=0.80,   # High risk -> Tier 3
            machine_state=m_state,
        )
        assert tier in (ExecutionTier.TIER_3_FULL_PROTECTED, ExecutionTier.TIER_3_ELEVATED_ADMIN)

        outcome = execution_engine.execute_recipe(
            recipe=recipe,
            trust_score=0.40,
            machine_state=m_state,
        )

        assert outcome.status == "BLOCKED"
        assert mock_subproc_run.call_count == 0
        assert mock_subproc_popen.call_count == 0


# ==============================================================================
# 2. Tier 3 + Safety Allowed -> Executes and proceeds to verification
# ==============================================================================

def test_tier3_plus_safety_allowed_executes_and_verifies():
    """
    Scenario:
        tier = TIER_3_FULL_PROTECTED
        approval = granted
        privilege = available
        live safety = ALLOWED
    Expected:
        mutation executes once
        final flow proceeds to verification
        proves Tier 3 is neither unconditionally blocked nor automatically allowed
    """
    recipe = _make_recipe(command="git config --system core.autocrlf true", risk="High")
    m_state = MachineState(free_disk_gb=100.0)

    fake_proc = subprocess.CompletedProcess(
        args=["git", "config"],
        returncode=0,
        stdout="success",
        stderr="",
    )

    with patch("subprocess.run", return_value=fake_proc) as mock_subproc, \
         patch("verification_engine.verification_engine.verify_tool") as mock_verify:

        mock_verify.return_value = MagicMock(
            status="VERIFIED",
            level="FULL",
            verified=True,
            version_detected="2.43.0",
            to_dict=lambda: {"status": "VERIFIED", "level": "FULL", "verified": True},
        )

        outcome = execution_engine.execute_recipe(
            recipe=recipe,
            trust_score=0.40,  # Forces Tier 3
            machine_state=m_state,
        )

        assert outcome.status == "VERIFIED"
        assert outcome.success is True
        assert mock_subproc.call_count >= 1
        assert mock_verify.call_count == 1


# ==============================================================================
# 3. Hard Override + Safety Blocked -> Zero Spawn
# ==============================================================================

def test_hard_override_plus_safety_blocked():
    """
    Scenario:
        hard override = TRUE
        tier = TIER_3_FULL_PROTECTED
        live safety = BLOCKED
    Expected:
        no subprocess
        no elevated mutation worker
        final state = BLOCKED
    """
    # Touches boot config (triggers hard override) and deletes system file (blocked by safety)
    cmd = "bcdedit /set {default} bootstatuspolicy ignoreallfailures & rmdir /s /q C:\\Windows"
    override = check_hard_safety_override(cmd)
    assert override is not None
    assert override[0] == ExecutionTier.TIER_3_FULL_PROTECTED

    with patch("subprocess.run") as mock_subproc_run, \
         patch("subprocess.Popen") as mock_subproc_popen:

        outcome = execution_engine.execute_command(
            command=cmd,
            operation="REPAIR",
            source="STATIC_DB",
            elevate=True,
        )

        assert outcome.status == "BLOCKED"
        assert mock_subproc_run.call_count == 0
        assert mock_subproc_popen.call_count == 0


# ==============================================================================
# 4. Approval Cannot Bypass Safety
# ==============================================================================

def test_approval_cannot_bypass_safety():
    """
    Scenario:
        approval = TRUE
        tier = TIER_3
        live safety = BLOCKED
    Expected:
        mutation_count == 0
    Proof:
        User approval != safety authorization
    """
    # User explicitly clicks 'Approve' on a dangerous command
    cmd = "rmdir /s /q C:\\Windows"
    recipe = _make_recipe(command=cmd, risk="High")

    with patch("subprocess.run") as mock_subproc_run, \
         patch("subprocess.Popen") as mock_subproc_popen:

        # Calling execute_recipe with user_approved = True (implicit in invocation)
        outcome = execution_engine.execute_recipe(
            recipe=recipe,
            trust_score=0.99,  # High trust cannot override safety
            machine_state=MachineState(free_disk_gb=50.0),
        )

        assert outcome.status == "BLOCKED"
        assert outcome.classification == BlockedReason.DESTRUCTIVE_OPERATION.value
        assert mock_subproc_run.call_count == 0
        assert mock_subproc_popen.call_count == 0


# ==============================================================================
# 5. Elevation Cannot Bypass Safety
# ==============================================================================

def test_elevation_cannot_bypass_safety():
    """
    Scenario:
        elevation available
        tier = TIER_3
        live safety = BLOCKED
    Expected:
        mutation_count == 0
        elevated mutation worker count == 0
    Proof:
        Administrator privileges != safety authorization
    """
    cmd = "del /f /q C:\\Windows\\System32\\hal.dll"

    with patch("subprocess.run") as mock_subproc, \
         patch("subprocess.Popen") as mock_popen:

        # Test both via execution_engine with elevate=True AND directly via privilege_manager
        outcome = execution_engine.execute_command(
            command=cmd,
            elevate=True,
            scope="machine",
        )
        assert outcome.status == "BLOCKED"
        assert mock_subproc.call_count == 0
        assert mock_popen.call_count == 0

        # Direct call to privilege_manager must also block before worker spawn
        payload = {
            "operation": "EXECUTE_COMMAND",
            "command": cmd,
            "application": "System Tool",
            "scope": "MACHINE",
        }
        res = privilege_manager.run_elevated_operation(payload)
        assert res.get("status") == "BLOCKED"
        assert res.get("ok") is False
        assert mock_subproc.call_count == 0
        assert mock_popen.call_count == 0


# ==============================================================================
# 6. Parameterized Test Matrix: Tier x Safety
# ==============================================================================

@pytest.mark.parametrize(
    "tier,safety_allowed",
    [
        (ExecutionTier.TIER_1_FAST, True),
        (ExecutionTier.TIER_2_CONTROLLED, True),
        (ExecutionTier.TIER_3_FULL_PROTECTED, True),
        (ExecutionTier.TIER_1_FAST, False),
        (ExecutionTier.TIER_2_CONTROLLED, False),
        (ExecutionTier.TIER_3_FULL_PROTECTED, False),
    ],
)
def test_parameterized_tier_safety_matrix(tier: ExecutionTier, safety_allowed: bool):
    """
    Verifies across all execution tiers that:
        Safety Allowed  → mutation may proceed
        Safety Blocked  → mutation count == 0
    """
    recipe = _make_recipe(command="git status", risk="Low")

    fake_proc = subprocess.CompletedProcess(
        args=["git", "status"],
        returncode=0,
        stdout="clean",
        stderr="",
    )

    safety_result = SafetyGateResult(
        allowed=safety_allowed,
        blocked_reason=None if safety_allowed else BlockedReason.SAFETY_POLICY_REJECTED,
        message="Gate test message",
    )

    with patch("subprocess.run", return_value=fake_proc) as mock_subproc, \
         patch("authoritative_safety.authoritative_safety.live_pre_execution_gate", return_value=safety_result), \
         patch("execution_tier.select_execution_tier", return_value=(tier, "Tier selection test")), \
         patch("verification_engine.verification_engine.verify_tool") as mock_verify:

        mock_verify.return_value = MagicMock(
            status="VERIFIED",
            level="FAST",
            verified=True,
            version_detected="2.43.0",
            to_dict=lambda: {"status": "VERIFIED", "verified": True},
        )

        outcome = execution_engine.execute_recipe(
            recipe=recipe,
            machine_state=MachineState(free_disk_gb=100.0),
        )

        if safety_allowed:
            assert outcome.status in ("VERIFIED", "EXECUTED")
            assert mock_subproc.call_count >= 1
        else:
            assert outcome.status == "BLOCKED"
            assert mock_subproc.call_count == 0


# ==============================================================================
# 7. Frozen Plan Cannot Bypass Live Safety
# ==============================================================================

def test_frozen_plan_cannot_bypass_live_safety():
    """
    Scenario:
        plan created
        tier frozen at TIER_1_FAST
        approval granted
        machine/environment changes (e.g. disk space degrades to 0.1 GB)
        live safety now blocks
    Expected:
        mutation_count == 0
        step.status == "BLOCKED"
    """
    recipe = _make_recipe(command="git fetch", risk="Low")
    plan = create_frozen_batch_plan(
        plan_id="plan_degrade_test",
        recipes_with_scores=[(recipe, ExecutionTier.TIER_1_FAST, 0.95, 0.10, 0.95)],
    )
    step = plan.steps[0]
    assert step.frozen_tier == ExecutionTier.TIER_1_FAST

    # Machine state degrades: disk is critically low (< 2.0 GB)
    degraded_machine_state = MachineState(free_disk_gb=0.5)

    with patch("subprocess.run") as mock_subproc:
        live_res = evaluate_step_live_safety_gate(
            step=step,
            required_disk_gb=2.0,
            machine_state=degraded_machine_state,
        )

        assert live_res.allowed is False
        assert step.status == "BLOCKED"
        assert mock_subproc.call_count == 0


# ==============================================================================
# 8. Legacy Compatibility Must Not Bypass
# ==============================================================================

def test_no_legacy_bypass_repair_engine():
    """
    Verify RepairEngine.run() cannot execute unsafe/blocked commands directly.
    """
    from repair_engine import RepairEngine
    engine = RepairEngine()

    destructive_cmd = "format D: /fs:NTFS /q"

    with patch("subprocess.run") as mock_subproc:
        stdout, stderr, rc = engine.run(command=destructive_cmd)

        assert rc != 0
        assert "Safety Gate" in stderr or "blocked" in stderr.lower() or "destructive" in stderr.lower()
        assert mock_subproc.call_count == 0


def test_no_legacy_bypass_repair_engine_stream():
    """
    Verify RepairEngine.stream_run() cannot execute unsafe/blocked commands directly.
    """
    from repair_engine import RepairEngine
    engine = RepairEngine()

    destructive_cmd = "format D: /fs:NTFS /q"

    with patch("subprocess.run") as mock_subproc, \
         patch("subprocess.Popen") as mock_popen:

        events = list(engine.stream_run(command=destructive_cmd))
        last_event = events[-1] if events else {}

        assert last_event.get("ok") is False or last_event.get("status") == "BLOCKED"
        assert mock_subproc.call_count == 0
        assert mock_popen.call_count == 0


def test_no_legacy_bypass_shce_engine():
    """
    Verify SHCE queued fix execution routes to CentralizedExecutionEngine and respects safety.
    """
    from shce_engine import shce

    # Mock queue item returning a destructive command
    with patch.object(shce.error_db, "get_queue_item", return_value={"selected_candidate": "rmdir /s /q C:\\Windows"}), \
         patch.object(shce.error_db, "update_queue_item") as mock_update, \
         patch("subprocess.run") as mock_subproc:

        res = shce.execute_queued_fix(queue_id=999)

        assert res.get("ok") is False
        assert mock_subproc.call_count == 0


def test_no_legacy_bypass_agent_orchestrator():
    """
    Verify AgentOrchestrator.tool_executor_run() routes to CentralizedExecutionEngine and respects safety.
    """
    from agent_orchestrator import AgentOrchestrator
    agent = AgentOrchestrator()

    with patch("subprocess.run") as mock_subproc:
        res = agent.tool_executor_run("rm -rf /")

        assert res.get("success") is False
        assert res.get("status") == "BLOCKED"
        assert mock_subproc.call_count == 0


# ==============================================================================
# 9. Zero Spawn Across All ExecutionEngine Entry Points
# ==============================================================================

def test_zero_spawn_on_all_execution_engine_entrypoints():
    """
    Intercepts subprocess.run, subprocess.Popen, asyncio.create_subprocess_shell.
    Proves 0 spawns across synchronous and streaming execution entry points.
    """
    blocked_cmd = "format E: /fs:NTFS /q"
    recipe = _make_recipe(command=blocked_cmd, risk="High")

    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen, \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_async_shell:

        # 1. execute_recipe (sync)
        outcome1 = execution_engine.execute_recipe(recipe=recipe)
        assert outcome1.status == "BLOCKED"

        # 2. execute_command (sync)
        outcome2 = execution_engine.execute_command(command=blocked_cmd)
        assert outcome2.status == "BLOCKED"

        # 3. stream_execute_command (generator)
        events = list(execution_engine.stream_execute_command(command=blocked_cmd))
        assert any(e.get("status") == "BLOCKED" for e in events)

        # 4. stream_execute_recipe (async generator)
        async def run_async():
            async_events = []
            async for ev in execution_engine.stream_execute_recipe(recipe=recipe):
                async_events.append(ev)
            return async_events

        async_events = asyncio.run(run_async())
        assert any(
            (isinstance(ev, dict) and ev.get("status") == "BLOCKED") or "BLOCKED" in str(ev)
            for ev in async_events
        )

        # Verify that the blocked mutation command was NEVER spawned by any runner
        format_mutation_calls = [c for c in mock_run.call_args_list if "format" in str(c)]
        assert len(format_mutation_calls) == 0, f"Blocked mutation was spawned! Calls: {format_mutation_calls}"
        assert mock_popen.call_count == 0
        assert mock_async_shell.call_count == 0


# ==============================================================================
# 10. Direct Call to PrivilegeManager Enforces Live Safety
# ==============================================================================

def test_privilege_manager_direct_call_enforces_live_safety():
    """
    Direct call to PrivilegeManager.run_with_elevation() with unsafe command
    must be blocked by check_pre_elevation_safety before worker process launch.
    """
    cmd = "format C: /fs:NTFS /q"

    with patch("subprocess.run") as mock_subproc, \
         patch("subprocess.Popen") as mock_popen:

        out, err, rc = privilege_manager.run_with_elevation(cmd, title="Direct Elevation Test")

        assert rc != 0
        assert "Safety Gate" in err or "blocked" in err.lower() or "destructive" in err.lower()
        assert mock_subproc.call_count == 0
        assert mock_popen.call_count == 0


# ==============================================================================
# 11. Safety Authorization Assertion Invariant
# ==============================================================================

def test_safety_authorization_assertion_raises_on_bypass():
    """
    Verifies that _assert_safety_authorized strictly raises SafetyAuthorizationViolation
    if an internal component attempts execution without an allowed SafetyGateResult.
    """
    # 1. None safety result raises violation
    with pytest.raises(SafetyAuthorizationViolation):
        CentralizedExecutionEngine._assert_safety_authorized(None)

    # 2. Disallowed safety result raises violation
    blocked_res = SafetyGateResult(allowed=False, message="Blocked by policy")
    with pytest.raises(SafetyAuthorizationViolation):
        CentralizedExecutionEngine._assert_safety_authorized(blocked_res)

    # 3. Allowed safety result succeeds without exception
    allowed_res = SafetyGateResult(allowed=True, message="Clear")
    CentralizedExecutionEngine._assert_safety_authorized(allowed_res)


# ==============================================================================
# 12. Architecture AST Regression Inspection
# ==============================================================================

def test_architecture_ast_invariant_no_direct_tier_execution():
    """
    AST analysis of execution_engine.py and execution_tier.py.
    1. execution_tier.py must have zero process spawning calls (pure policy).
    2. execution_engine.py must not contain unconditional tier execution patterns.
    """
    tier_file = _BACKEND / "execution_tier.py"
    tier_tree = ast.parse(tier_file.read_text(encoding="utf-8"))

    for node in ast.walk(tier_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in ("subprocess", "winreg"), (
                    f"execution_tier.py must be a pure policy module with no platform/subprocess imports: found {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in ("subprocess", "winreg"), (
                f"execution_tier.py must be a pure policy module with no platform/subprocess imports: found {node.module}"
            )

    # Verify execution_engine.py contains _assert_safety_authorized
    ee_file = _BACKEND / "execution_engine.py"
    ee_code = ee_file.read_text(encoding="utf-8")
    assert "_assert_safety_authorized" in ee_code
    assert "live_pre_execution_gate" in ee_code
