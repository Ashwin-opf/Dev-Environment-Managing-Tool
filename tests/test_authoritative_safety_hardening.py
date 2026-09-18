"""
test_authoritative_safety_hardening.py — Authoritative Safety Gate Hardening Test Suite (Stage 5).

Verifies:
1. Tier 3 + Safety Allowed: required protection level does not block safe authorized operations.
2. Tier 3 + Safety Blocked: Tier 3 does NOT mean allowed to execute. Prohibited operations are BLOCKED.
3. Hard override invariant: hard overrides to Tier 3 do NOT bypass the safety gate.
4. Natural-language command rejection: 'fix my git', 'please install java', etc. blocked before process spawn.
5. Dangerous command blocking: format, rm -rf, del System32 blocked; process spawn count == 0.
6. Package manager unavailable handled explicitly (PACKAGE_MANAGER_UNAVAILABLE).
7. Dependency/resource conflict handled correctly (RESOURCE_LOCKED).
8. Pending reboot follows explicit policy (queries allowed; conflicting driver/system mutations blocked).
9. OS/platform mismatch blocked (PLATFORM_MISMATCH / UNSUPPORTED_METHOD).
10. Protected internal PC Doctor resource mutation blocked (INTERNAL_RESOURCE_PROTECTION).
11. Safety result preserves canonical blocked reason.
12. Live safety gate executes immediately before mutation (last-mile guarantee).
13. Frozen plan cannot bypass changed live safety state.
14. Safety cache invalidates on critical machine-state changes.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    is_natural_language_command,
)
from execution_engine import CentralizedExecutionEngine, execution_engine
from execution_tier import ExecutionTier, select_execution_tier
from machine_state import MachineState
from plan_freeze import (
    BatchPlan,
    FrozenPlanStep,
    ResourceLockManager,
    create_frozen_batch_plan,
    evaluate_step_live_safety_gate,
    resource_lock_mgr,
)
from recipe_engine import RecipeLifecycle, RecipeOperation, RepairStrategy, StructuredRecipe


def _make_dummy_recipe(
    command: str = "git --version",
    executable: str = "git",
    arguments: list[str] = None,
    operation: RecipeOperation = RecipeOperation.INSTALL,
    target: str = "git",
    source: str = "STATIC_DB",
    os_name: str = "Any",
    package_manager: str = "winget",
) -> StructuredRecipe:
    """Helper to build structured recipes for safety testing."""
    if arguments is None:
        arguments = ["--version"]
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
        risk_base="Low",
        source=source,
        repair_strategy=RepairStrategy.NATIVE,
        validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
    )


# ==============================================================================
# TEST 1: Tier 3 + Safety Allowed
# ==============================================================================
def test_1_tier3_safety_allowed():
    """
    Proves that a command requiring Tier 3 protection (e.g. administrative configuration)
    can pass the Live Safety Gate when it is not destructive.
    Tier 3 specifies protection level, not execution prohibition.
    """
    recipe = _make_dummy_recipe(
        command="bcdedit /set {default} bootstatuspolicy ignoreallfailures",
        executable="bcdedit",
        arguments=["/set", "{default}", "bootstatuspolicy", "ignoreallfailures"],
    )
    # Stage 4 hard override evaluates this to Tier 3
    tier, reason = select_execution_tier(
        recipe,
        trust_score=1.0,
        risk_score=0.1,
        confidence_score=1.0,
        machine_state=MachineState(pending_reboot=False, free_disk_gb=50.0),
    )
    assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
    assert "Hard safety override" in reason

    # Authoritative Live Safety Gate evaluates the command:
    # A non-destructive boot status query/set is permitted through safety
    res = authoritative_safety.live_pre_execution_gate(
        command=recipe.to_command_string(),
        recipe=recipe,
        machine_state=MachineState(pending_reboot=False, free_disk_gb=50.0),
    )
    assert res.allowed is True
    assert "Live pre-execution safety gate passed" in res.message


# ==============================================================================
# TEST 2: Tier 3 + Safety Blocked (Cardinal Invariant)
# ==============================================================================
def test_2_tier3_safety_blocked():
    """
    CRITICAL ARCHITECTURAL INVARIANT:
    Tier 3 != Allowed to Execute.
    A destructive boot modification is assigned Tier 3 by policy, BUT
    the Live Safety Gate must strictly BLOCK it, ensuring subprocess spawn count == 0.
    """
    cmd = "bcdedit /delete {default}"
    recipe = _make_dummy_recipe(
        command=cmd,
        executable="bcdedit",
        arguments=["/delete", "{default}"],
    )

    # 1. Tier selection routes to Tier 3
    tier, _ = select_execution_tier(
        recipe,
        trust_score=1.0,
        risk_score=0.1,
        confidence_score=1.0,
        machine_state=MachineState(pending_reboot=False, free_disk_gb=50.0),
    )
    assert tier == ExecutionTier.TIER_3_FULL_PROTECTED

    # 2. Live Safety Gate MUST BLOCK
    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        res = authoritative_safety.live_pre_execution_gate(
            command=cmd,
            recipe=recipe,
            machine_state=MachineState(pending_reboot=False, free_disk_gb=50.0),
        )
        assert res.allowed is False
        assert res.blocked_reason in (BlockedReason.DESTRUCTIVE_OPERATION, BlockedReason.SAFETY_POLICY_REJECTED)

        # 3. Pipeline execution test: Ensure zero subprocesses are spawned
        outcome = execution_engine.execute_recipe(
            recipe=recipe,
            machine_state=MachineState(pending_reboot=False, free_disk_gb=50.0),
        )
        assert outcome.status == "BLOCKED"
        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0


# ==============================================================================
# TEST 3: Hard Override Does Not Bypass Safety
# ==============================================================================
def test_3_hard_override_does_not_bypass_safety():
    """
    Proves that commands triggering hard tier overrides (e.g. firewall disabling or user deletion)
    are intercepted by the live safety gate before execution.
    """
    prohibited_commands = [
        "netsh advfirewall set allprofiles state off",
        "net user administrator /delete",
        "bcdedit /deletevalue {default} safeboot",
    ]

    for cmd in prohibited_commands:
        recipe = _make_dummy_recipe(command=cmd, executable=cmd.split()[0], arguments=cmd.split()[1:])
        tier, _ = select_execution_tier(recipe, machine_state=MachineState(pending_reboot=False))
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED

        res = authoritative_safety.live_pre_execution_gate(
            command=cmd,
            recipe=recipe,
            machine_state=MachineState(pending_reboot=False),
        )
        assert res.allowed is False
        assert res.blocked_reason in (BlockedReason.DESTRUCTIVE_OPERATION, BlockedReason.SAFETY_POLICY_REJECTED)


# ==============================================================================
# TEST 4: Natural-Language Command Rejection
# ==============================================================================
def test_4_natural_language_command_blocked_before_process_spawn():
    """
    Verifies that conversational or advisory strings cannot spawn a shell process.
    """
    nl_commands = [
        "fix my git",
        "please install java",
        "restart the service for me",
        "configure the path for me",
        "ensure that python is installed.",
    ]

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        for nl in nl_commands:
            assert is_natural_language_command(nl) is True
            res = authoritative_safety.live_pre_execution_gate(command=nl)
            assert res.allowed is False
            assert res.blocked_reason == BlockedReason.SAFETY_POLICY_REJECTED

            # Run through execution engine stream
            events = list(execution_engine.stream_execute_command(command=nl))
            assert any(e.get("status") == "BLOCKED" or "Safety Blocked" in str(e) for e in events)

        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0


# ==============================================================================
# TEST 5: Dangerous Command Blocking
# ==============================================================================
def test_5_dangerous_command_blocked_before_process_spawn():
    """
    Verifies that destructive system operations are blocked by HARD_BLACKLIST
    with zero subprocess spawn count.
    """
    dangerous_commands = [
        "format C:",
        "rm -rf /",
        "rm -rf /*",
        "del C:\\Windows\\System32",
        "rd /s /q C:\\Windows",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
    ]

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        for cmd in dangerous_commands:
            passed, reason, _ = authoritative_safety.evaluate_command_static(cmd)
            assert passed is False
            assert reason == BlockedReason.DESTRUCTIVE_OPERATION

            res = authoritative_safety.live_pre_execution_gate(command=cmd)
            assert res.allowed is False
            assert res.blocked_reason == BlockedReason.DESTRUCTIVE_OPERATION

        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0


# ==============================================================================
# TEST 6: Package Manager Unavailable Handled Explicitly
# ==============================================================================
def test_6_package_manager_unavailable_handled_explicitly():
    """
    When a package manager is absent or marked unavailable, the safety gate
    blocks with PACKAGE_MANAGER_UNAVAILABLE instead of blindly failing at execution.
    """
    # 1. Flagged via MachineState
    m_state = MachineState(package_manager_available=False, pending_reboot=False, free_disk_gb=100.0)
    res = authoritative_safety.live_pre_execution_gate(
        command="winget install Git.Git",
        package_manager="winget",
        machine_state=m_state,
    )
    assert res.allowed is False
    assert res.blocked_reason == BlockedReason.PACKAGE_MANAGER_UNAVAILABLE

    # 2. Package manager executable not found on PATH
    with patch("shutil.which", return_value=None):
        res2 = authoritative_safety.live_pre_execution_gate(
            command="choco install git",
            package_manager="choco",
            machine_state=MachineState(package_manager_available=None, pending_reboot=False, free_disk_gb=100.0),
        )
        assert res2.allowed is False
        assert res2.blocked_reason == BlockedReason.PACKAGE_MANAGER_UNAVAILABLE


# ==============================================================================
# TEST 7: Dependency / Resource Conflict Handled Correctly
# ==============================================================================
def test_7_dependency_and_resource_lock_conflict():
    """
    Verifies that active resource locks (fine-grained) and host dependency locks
    trigger RESOURCE_LOCKED before process spawning.
    """
    # 1. External OS dependency lock
    m_locked = MachineState(dependency_lock=True, pending_reboot=False, free_disk_gb=100.0)
    res_dep = authoritative_safety.live_pre_execution_gate(
        command="git --version",
        machine_state=m_locked,
    )
    assert res_dep.allowed is False
    assert res_dep.blocked_reason == BlockedReason.RESOURCE_LOCKED
    assert res_dep.is_recoverable is True

    # 2. Concurrent internal resource lock
    owner_a = "worker_operation_A"
    owner_b = "worker_operation_B"
    lock_mgr = resource_lock_mgr
    lock_mgr.acquire_resources(owner_id=owner_a, resources=["tool:git"], timeout=1.0)
    try:
        # Operation B tries to mutate git while locked by A
        res_conflict = authoritative_safety.live_pre_execution_gate(
            command="git --version",
            target_resource="git",
            owner_id=owner_b,
            machine_state=MachineState(dependency_lock=False, pending_reboot=False, free_disk_gb=100.0),
        )
        assert res_conflict.allowed is False
        assert res_conflict.blocked_reason == BlockedReason.RESOURCE_LOCKED
        assert "locked by concurrent operation" in res_conflict.message
    finally:
        lock_mgr.release_resources(owner_id=owner_a, resources=["tool:git"])


# ==============================================================================
# TEST 8: Pending Reboot Follows Explicit Policy
# ==============================================================================
def test_8_pending_reboot_explicit_policy():
    """
    Evidence-driven reboot policy:
    - Benign query/check commands (git --version, status) are ALLOWED during pending reboot.
    - Low-level kernel driver / system mutations are BLOCKED with REQUIRES_REBOOT.
    """
    m_reboot = MachineState(pending_reboot=True, low_disk_space=False, free_disk_gb=100.0)

    # 1. Safe query is allowed
    res_safe = authoritative_safety.live_pre_execution_gate(
        command="git --version",
        machine_state=m_reboot,
    )
    assert res_safe.allowed is True

    # 2. Driver / kernel mutation is blocked
    res_driver = authoritative_safety.live_pre_execution_gate(
        command="dism /online /cleanup-image /restorehealth",
        machine_state=m_reboot,
    )
    assert res_driver.allowed is False
    assert res_driver.blocked_reason == BlockedReason.REQUIRES_REBOOT


# ==============================================================================
# TEST 9: OS / Platform Mismatch Blocked
# ==============================================================================
def test_9_os_platform_mismatch_blocked():
    """
    Safety gate rejects commands targeted for a foreign operating system.
    """
    current_os = platform.system()
    foreign_os = "Linux" if current_os == "Windows" else "Windows"

    recipe_mismatch = _make_dummy_recipe(
        command="apt-get install -y git" if current_os == "Windows" else "winget install Git.Git",
        os_name=foreign_os,
    )

    res = authoritative_safety.live_pre_execution_gate(
        command=recipe_mismatch.to_command_string(),
        recipe=recipe_mismatch,
        machine_state=MachineState(pending_reboot=False, free_disk_gb=100.0),
    )
    assert res.allowed is False
    assert res.blocked_reason in (BlockedReason.PLATFORM_MISMATCH, BlockedReason.UNSUPPORTED_METHOD)


# ==============================================================================
# TEST 10: Internal PC Doctor Resource Protection
# ==============================================================================
def test_10_protected_internal_resource_mutation_blocked():
    """
    Proves that attempts to delete or alter PC Doctor's own databases or scripts are blocked.
    """
    internal_attacks = [
        "del backend\\knowledge.db",
        "rm -f backend/authoritative_safety.py",
        "rmdir /s /q backend",
    ]

    for attack in internal_attacks:
        res = authoritative_safety.live_pre_execution_gate(command=attack)
        assert res.allowed is False
        assert res.blocked_reason == BlockedReason.INTERNAL_RESOURCE_PROTECTION


# ==============================================================================
# TEST 11: Safety Result Preserves Canonical Blocked Reason
# ==============================================================================
def test_11_canonical_blocked_reasons():
    """
    Ensures SafetyGateResult returns strongly typed BlockedReason enum values.
    """
    res1 = authoritative_safety.live_pre_execution_gate(command="")
    assert isinstance(res1.blocked_reason, BlockedReason)
    assert res1.blocked_reason == BlockedReason.SAFETY_POLICY_REJECTED

    res2 = authoritative_safety.live_pre_execution_gate(command="format C:")
    assert isinstance(res2.blocked_reason, BlockedReason)
    assert res2.blocked_reason == BlockedReason.DESTRUCTIVE_OPERATION


# ==============================================================================
# TEST 12: Live Safety Gate Executes Immediately Before Mutation
# ==============================================================================
def test_12_last_mile_gate_execution_sequence():
    """
    Verifies that the live safety gate is invoked as the final authorization step
    right before the mutation executes.
    """
    call_order = []
    recipe = _make_dummy_recipe(command="git --version")

    original_gate = authoritative_safety.live_pre_execution_gate

    def spy_gate(*args, **kwargs):
        call_order.append("safety_gate")
        return original_gate(*args, **kwargs)

    def spy_run(*args, **kwargs):
        call_order.append("subprocess_run")
        m = MagicMock()
        m.returncode = 0
        m.stdout = "git version 2.43.0"
        m.stderr = ""
        return m

    with patch.object(authoritative_safety, "live_pre_execution_gate", side_effect=spy_gate):
        with patch("subprocess.run", side_effect=spy_run):
            execution_engine.execute_recipe(
                recipe=recipe,
                machine_state=MachineState(pending_reboot=False, free_disk_gb=100.0),
            )
            assert len(call_order) >= 2
            assert call_order[0] == "safety_gate"
            assert "subprocess_run" in call_order[1:]


# ==============================================================================
# TEST 13: Frozen Plan Cannot Bypass Changed Live Safety State
# ==============================================================================
def test_13_frozen_plan_cannot_bypass_changed_safety_state():
    """
    Batch plan tier is frozen at planning time, but the Live Safety Gate re-evaluates
    dynamically. If disk space drops below threshold, the frozen step is BLOCKED.
    """
    recipe = _make_dummy_recipe(command="git --version")
    plan = create_frozen_batch_plan("test_plan_01", [(recipe, ExecutionTier.TIER_1_FAST, 1.0, 0.1, 1.0)])
    step = plan.steps[0]

    # Initial state: Normal, plenty of disk space
    m_good = MachineState(free_disk_gb=50.0, pending_reboot=False)
    res_good = evaluate_step_live_safety_gate(step, required_disk_gb=2.0, machine_state=m_good)
    assert res_good.allowed is True
    assert step.status == "PENDING"

    # Changed state before mutation: Disk space critically degraded
    m_degraded = MachineState(free_disk_gb=0.4, low_disk_space=True, pending_reboot=False)
    res_degraded = evaluate_step_live_safety_gate(step, required_disk_gb=2.0, machine_state=m_degraded)
    assert res_degraded.allowed is False
    assert res_degraded.blocked_reason == BlockedReason.RISK_ABOVE_HARD_LIMIT
    assert step.status == "BLOCKED"


# ==============================================================================
# TEST 14: Safety Cache Invalidates on Critical Machine-State Changes
# ==============================================================================
def test_14_safety_cache_invalidation():
    """
    Proves that cached safety checks invalidate when machine state signals change
    (e.g. pending reboot or disk threshold).
    """
    cache = authoritative_safety.cache
    cache.clear()

    cmd = "git --version"
    m_clean = MachineState(free_disk_gb=100.0, pending_reboot=False, dependency_lock=False)

    # First evaluation populates cache
    res1 = authoritative_safety.live_pre_execution_gate(command=cmd, machine_state=m_clean)
    assert res1.allowed is True

    # Changed machine state signature (e.g. dependency lock activated)
    m_locked = MachineState(free_disk_gb=100.0, pending_reboot=False, dependency_lock=True)
    res2 = authoritative_safety.live_pre_execution_gate(command=cmd, machine_state=m_locked)
    # The cache must not return the old allowed=True result; it must re-evaluate and block!
    assert res2.allowed is False
    assert res2.blocked_reason == BlockedReason.RESOURCE_LOCKED
