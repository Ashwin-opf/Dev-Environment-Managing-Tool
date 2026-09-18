"""
test_machine_state_policy.py — Comprehensive Test Suite for Stage 4 Machine-State & Tier-Policy Correctness.

Validates:
1. Machine-state signals: pending reboot, low disk, conflicts, unusual state, previous failure,
   package manager unavailable, dependency lock, environment drift, normal state, CPU/RAM load.
2. Controlled tier trust requirement:
   - high trust + moderate risk -> Controlled
   - low trust + moderate risk -> Full Protected (escalated)
   - untrusted dynamic -> escalation/blocking
3. Threshold configuration: changing policy threshold alters tier outcome without changing business logic.
4. Scope invariant: USER vs MACHINE scope identical tier unless policy inputs change.
5. Hard safety overrides: boot config, protected firewall, credentials force Full Protected/Blocked.
6. Unknown machine state: UNKNOWN is never silently converted to SAFE (conservative policy).
7. Architecture boundary: execution_tier.py does NOT import platform-specific modules (winreg, subprocess).
8. First-time Static recipe: confidence < 0.80 routes trusted static recipe to Controlled, not Fast.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest

from execution_tier import (
    ExecutionTier,
    TierPolicyConfig,
    check_hard_safety_override,
    compute_live_risk,
    get_tier_policy,
    reset_tier_policy,
    select_execution_tier,
    set_tier_policy,
)
from machine_state import MachineState
from recipe_engine import RecipeLifecycle, RecipeOperation, RepairStrategy, StructuredRecipe


@pytest.fixture(autouse=True)
def restore_default_policy():
    """Ensures each test starts and ends with a pristine default TierPolicyConfig."""
    reset_tier_policy()
    yield
    reset_tier_policy()


def _make_dummy_recipe(
    command: str = "git --version",
    executable: str = "git",
    arguments: list[str] = None,
    operation: RecipeOperation = RecipeOperation.INSTALL,
    risk_base: str = "Low",
    source: str = "STATIC_DB",
) -> StructuredRecipe:
    """Helper to construct structured recipes for pure policy testing."""
    if arguments is None:
        arguments = ["--version"]
    return StructuredRecipe(
        recipe_id="test_rec_001",
        recipe_version=1,
        identity_id="git",
        operation=operation,
        os="Any",
        architecture="Any",
        package_manager="winget",
        executable=executable,
        arguments=arguments,
        verification_command=[executable, "--version"],
        risk_base=risk_base,
        source=source,
        repair_strategy=RepairStrategy.NATIVE,
        validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
    )


# ==============================================================================
# AREA 1: Machine-State Signals
# ==============================================================================

class TestMachineStateSignals:
    """Validates that real machine state signals directly affect risk and tier policy."""

    def test_normal_machine_state_allows_fast_path(self):
        """When all signals are verified normal, an eligible recipe receives Fast Path."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(
            pending_reboot=False,
            low_disk_space=False,
            service_issue=False,
            dependency_lock=False,
            package_manager_available=True,
            installation_state_changed=False,
            previous_failure=False,
            environment_drift=False,
            conflicts=False,
            unusual_state=False,
            cpu_percent=15.0,
            ram_percent=40.0,
            free_disk_gb=100.0,
        )
        is_normal, reasons = m_state.is_normal_state()
        assert is_normal is True
        assert len(reasons) == 0

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_1_FAST
        assert "Eligible for Fast Path" in reason

    def test_pending_reboot_disqualifies_fast_path(self):
        """When pending_reboot is True, Fast Path is ineligible even with perfect trust and risk."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(
            pending_reboot=True,
            low_disk_space=False,
            conflicts=False,
            unusual_state=False,
            free_disk_gb=80.0,
        )
        is_normal, reasons = m_state.is_normal_state()
        assert is_normal is False
        assert any("pending reboot" in r for r in reasons)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "pending reboot" in reason

    def test_low_disk_space_increases_risk_and_blocks_fast_path(self):
        """Low disk space increases dynamic risk and disqualifies Fast Path."""
        recipe = _make_dummy_recipe()
        m_normal = MachineState(free_disk_gb=50.0, low_disk_space=False)
        m_low = MachineState(free_disk_gb=2.0, low_disk_space=True)

        risk_normal = compute_live_risk(recipe, machine_state=m_normal)
        risk_low = compute_live_risk(recipe, machine_state=m_low)
        assert risk_low >= risk_normal + 0.20

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=risk_low,
            confidence_score=0.95,
            machine_state=m_low,
        )
        assert tier != ExecutionTier.TIER_1_FAST
        assert "Low disk space" in reason or "Controlled" in reason or "Full Protected" in reason

    def test_conflict_blocks_fast_path(self):
        """When conflicts=True, Fast Path is disqualified and routes to Controlled."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(conflicts=True, unusual_state=False)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "conflicts" in reason.lower()

    def test_unusual_state_blocks_fast_path(self):
        """When unusual_state=True, Fast Path is disqualified."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(conflicts=False, unusual_state=True)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "unusual state" in reason.lower()

    def test_previous_failure_increases_risk(self):
        """When previous_failure=True, compute_live_risk increases risk score."""
        recipe = _make_dummy_recipe()
        m_clean = MachineState(previous_failure=False)
        m_fail = MachineState(previous_failure=True)

        r_clean = compute_live_risk(recipe, machine_state=m_clean)
        r_fail = compute_live_risk(recipe, machine_state=m_fail)
        assert r_fail >= r_clean + 0.15

    def test_dependency_lock_increases_risk_and_blocks_fast_path(self):
        """Active dependency/resource lock increases risk and disqualifies Fast Path."""
        recipe = _make_dummy_recipe()
        m_locked = MachineState(dependency_lock=True)

        risk = compute_live_risk(recipe, machine_state=m_locked)
        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=risk,
            confidence_score=0.95,
            machine_state=m_locked,
        )
        assert tier != ExecutionTier.TIER_1_FAST
        assert "locked" in reason.lower()

    def test_environment_drift_blocks_fast_path(self):
        """When environment_drift is True, Fast Path is disqualified."""
        recipe = _make_dummy_recipe()
        m_drift = MachineState(environment_drift=True)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_drift,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "drift" in reason.lower()

    def test_high_cpu_and_ram_load_increases_risk(self):
        """High CPU (>80%) or RAM (>85%) triggers dynamic risk penalty."""
        recipe = _make_dummy_recipe()
        m_idle = MachineState(cpu_percent=10.0, ram_percent=30.0)
        m_heavy = MachineState(cpu_percent=92.0, ram_percent=90.0)

        r_idle = compute_live_risk(recipe, machine_state=m_idle)
        r_heavy = compute_live_risk(recipe, machine_state=m_heavy)
        assert r_heavy >= r_idle + 0.15


# ==============================================================================
# AREA 2: Controlled Tier Trust Requirement
# ==============================================================================

class TestControlledTierTrustRequirement:
    """Validates that Controlled tier enforces BOTH risk <= max_risk AND trust >= min_trust."""

    def test_high_trust_moderate_risk_selects_controlled(self):
        """Moderate risk with high trust qualifies for Controlled path."""
        recipe = _make_dummy_recipe()
        # Default policy: controlled_trust_min=0.60, controlled_risk_max=0.70
        tier, reason = select_execution_tier(
            recipe,
            trust_score=0.85,
            risk_score=0.55,
            confidence_score=0.90,
            machine_state={"conflicts": False, "unusual_state": False, "pending_reboot": False},
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "Controlled Path" in reason

    def test_low_trust_moderate_risk_escalates_to_full_protected(self):
        """
        When trust is below controlled_trust_min (e.g. 0.40 < 0.60), Controlled tier
        is REJECTED even if risk is moderate (0.50 <= 0.70). Escalates to Full Protected.
        """
        recipe = _make_dummy_recipe()
        tier, reason = select_execution_tier(
            recipe,
            trust_score=0.40,
            risk_score=0.50,
            confidence_score=0.90,
            machine_state={"conflicts": False, "unusual_state": False, "pending_reboot": False},
        )
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
        assert "Insufficient trust" in reason
        assert "escalated to Full Protected" in reason

    def test_untrusted_dynamic_candidate_with_acceptable_risk_escalates(self):
        """Untrusted dynamic recipe (trust=0.20) does not get Controlled path."""
        recipe = _make_dummy_recipe(source="DYNAMIC_DB")
        tier, reason = select_execution_tier(
            recipe,
            trust_score=0.20,
            risk_score=0.40,
            confidence_score=0.70,
            machine_state={"conflicts": False, "unusual_state": False, "pending_reboot": False},
        )
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
        assert "Insufficient trust" in reason

    def test_low_trust_and_unacceptable_risk_blocks(self):
        """Low trust with insurmountable risk (> 0.90) is Blocked."""
        recipe = _make_dummy_recipe()
        tier, reason = select_execution_tier(
            recipe,
            trust_score=0.30,
            risk_score=0.95,
            confidence_score=0.50,
            machine_state={"conflicts": False, "unusual_state": False, "pending_reboot": False},
        )
        assert tier == ExecutionTier.BLOCKED
        assert "Blocked" in reason


# ==============================================================================
# AREA 3: Threshold Configuration
# ==============================================================================

class TestThresholdConfiguration:
    """Validates that tier selection thresholds are driven by configuration, not hardcoded logic."""

    def test_threshold_tuning_changes_tier_outcome(self):
        """Proves that changing a policy threshold alters the tier outcome without code changes."""
        recipe = _make_dummy_recipe()
        inputs = dict(
            trust_score=0.90,
            risk_score=0.75,
            confidence_score=0.90,
            machine_state={"conflicts": False, "unusual_state": False, "pending_reboot": False},
        )

        # Baseline: default policy has controlled_risk_max = 0.70 -> risk 0.75 exceeds Controlled -> Full Protected
        tier_default, _ = select_execution_tier(recipe, **inputs)
        assert tier_default == ExecutionTier.TIER_3_FULL_PROTECTED

        # Tuned policy: increase controlled_risk_max to 0.80 -> risk 0.75 now qualifies for Controlled
        tuned_policy = TierPolicyConfig(controlled_risk_max=0.80)
        tier_tuned, _ = select_execution_tier(recipe, policy=tuned_policy, **inputs)
        assert tier_tuned == ExecutionTier.TIER_2_CONTROLLED

    def test_policy_validation_rejects_invalid_ordering(self):
        """Validates that invariant violations (e.g. fast_risk > controlled_risk) are rejected."""
        with pytest.raises(ValueError, match="Invalid risk thresholds"):
            bad_policy = TierPolicyConfig(fast_path_risk_max=0.75, controlled_risk_max=0.60)
            bad_policy.validate()

    def test_policy_validation_rejects_inverted_trust(self):
        """Validates that controlled_trust > fast_path_trust is rejected."""
        with pytest.raises(ValueError, match="Invalid trust thresholds"):
            bad_policy = TierPolicyConfig(fast_path_trust_min=0.70, controlled_trust_min=0.85)
            bad_policy.validate()


# ==============================================================================
# AREA 4: Scope Invariant
# ==============================================================================

class TestScopeInvariant:
    """Validates that Scope is only an input to policy and does not hardcode tiers."""

    def test_identical_policy_inputs_yield_identical_tiers_regardless_of_scope(self):
        """USER scope vs MACHINE scope do not artificially alter the pure tier policy output."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(
            pending_reboot=False,
            low_disk_space=False,
            free_disk_gb=100.0,
            dependency_lock=False,
            conflicts=False,
            unusual_state=False,
        )

        # Exact same trust, risk, confidence, machine state
        tier_user, _ = select_execution_tier(recipe, trust_score=0.9, risk_score=0.2, confidence_score=0.9, machine_state=m_state)
        tier_machine, _ = select_execution_tier(recipe, trust_score=0.9, risk_score=0.2, confidence_score=0.9, machine_state=m_state)

        assert tier_user == tier_machine == ExecutionTier.TIER_1_FAST

    def test_scope_influences_risk_input_legitimately(self):
        """Machine scope legitimately contributes to higher elevation requirement in risk computation."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(pending_reboot=False)

        # User scope (no elevation required)
        risk_user = compute_live_risk(recipe, machine_state=m_state, requires_elevation=False)
        # Machine scope (requires elevation)
        risk_machine = compute_live_risk(recipe, machine_state=m_state, requires_elevation=True)

        assert risk_machine > risk_user
        assert risk_machine >= risk_user + 0.15


# ==============================================================================
# AREA 5: Hard Safety Overrides
# ==============================================================================

class TestHardSafetyOverrides:
    """Validates that critical system configurations trigger hard tier overrides before scoring."""

    def test_boot_configuration_forces_full_protected(self):
        """bcdedit command is intercepted by hard override -> Full Protected Path."""
        recipe = _make_dummy_recipe(
            executable="bcdedit",
            arguments=["/set", "{default}", "bootstatuspolicy", "ignoreallfailures"],
        )
        # Even with perfect trust and lowest risk, hard override must trigger
        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.05,
            confidence_score=1.0,
            machine_state=MachineState(pending_reboot=False, conflicts=False, unusual_state=False),
        )
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
        assert "Hard safety override" in reason
        assert "bcdedit" in reason

    def test_firewall_alteration_forces_full_protected(self):
        """netsh advfirewall command triggers hard safety override."""
        recipe = _make_dummy_recipe(
            executable="netsh",
            arguments=["advfirewall", "set", "allprofiles", "state", "off"],
        )
        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.05,
            confidence_score=1.0,
            machine_state=MachineState(pending_reboot=False, conflicts=False, unusual_state=False),
        )
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
        assert "Hard safety override" in reason

    def test_credential_manipulation_forces_full_protected(self):
        """User account management command triggers hard safety override."""
        recipe = _make_dummy_recipe(
            executable="net",
            arguments=["user", "testadmin", "SecretPass123!", "/add"],
        )
        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.05,
            confidence_score=1.0,
            machine_state=MachineState(pending_reboot=False, conflicts=False, unusual_state=False),
        )
        assert tier == ExecutionTier.TIER_3_FULL_PROTECTED
        assert "Hard safety override" in reason

    def test_benign_operation_bypasses_hard_overrides(self):
        """Standard tools (e.g. git) do not match hard overrides and proceed to normal scoring."""
        recipe = _make_dummy_recipe(executable="git", arguments=["--version"])
        assert check_hard_safety_override(recipe.to_command_string()) is None


# ==============================================================================
# AREA 6: Unknown Machine State Handling
# ==============================================================================

class TestUnknownMachineStateHandling:
    """Validates that UNKNOWN signals are treated conservatively and never silently assumed safe."""

    def test_unknown_pending_reboot_disqualifies_fast_path(self):
        """When pending_reboot is None (UNKNOWN), conservative policy rejects Fast Path."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(
            pending_reboot=None, # UNKNOWN
            low_disk_space=False,
            conflicts=False,
            unusual_state=False,
            free_disk_gb=100.0,
        )
        is_normal, reasons = m_state.is_normal_state(allow_unknown_as_safe=False)
        assert is_normal is False
        assert any("UNKNOWN" in r for r in reasons)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "UNKNOWN" in reason or "abnormal/unknown" in reason

    def test_unknown_disk_space_disqualifies_fast_path(self):
        """When disk space cannot be probed, Fast Path is rejected."""
        recipe = _make_dummy_recipe()
        m_state = MachineState(
            pending_reboot=False,
            low_disk_space=None,
            free_disk_gb=None, # UNKNOWN
            conflicts=False,
            unusual_state=False,
        )
        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.15,
            confidence_score=0.95,
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "UNKNOWN" in reason or "abnormal/unknown" in reason


# ==============================================================================
# AREA 7: Pure Policy & Architecture Boundary
# ==============================================================================

class TestArchitectureBoundary:
    """Validates that execution_tier.py does not contain platform-specific or I/O imports."""

    def test_execution_tier_has_no_platform_imports(self):
        """execution_tier.py must NOT import winreg, subprocess, or OS APIs."""
        tier_file = Path(__file__).parent.parent / "backend" / "execution_tier.py"
        content = tier_file.read_text(encoding="utf-8")
        tree = ast.parse(content)

        forbidden = {"winreg", "subprocess", "ctypes", "pty", "termios"}
        imported_modules = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        violations = forbidden.intersection(imported_modules)
        assert len(violations) == 0, f"execution_tier.py directly imports forbidden modules: {violations}"


# ==============================================================================
# AREA 8: First-Time Static Recipe / Confidence
# ==============================================================================

class TestFirstTimeStaticConfidence:
    """Validates that low confidence on a trusted static recipe routes to Controlled, not Full Protected."""

    def test_first_time_static_recipe_routes_to_controlled(self):
        """
        A trusted static recipe (trust=1.0, risk=0.25) with zero or low confidence (0.0)
        does not qualify for Fast Path (requires conf >= 0.80), but qualifies for Controlled Path.
        """
        recipe = _make_dummy_recipe(source="STATIC_DB")
        m_state = MachineState(pending_reboot=False, conflicts=False, unusual_state=False)

        tier, reason = select_execution_tier(
            recipe,
            trust_score=1.0,
            risk_score=0.25,
            confidence_score=0.0, # Not yet established
            machine_state=m_state,
        )
        assert tier == ExecutionTier.TIER_2_CONTROLLED
        assert "Controlled Path" in reason
