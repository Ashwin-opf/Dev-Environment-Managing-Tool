"""
execution_tier.py — Dynamic Live Risk Assessment & Execution Tier Selection.

Implements:
- 5 Execution Tiers:
  - TIER 0: READ_ONLY (no mutation, observation only)
  - TIER 1: FAST (trusted, low risk, high confidence, non-conflicting, confirmed normal machine state, automated)
  - TIER 2: CONTROLLED (medium risk, trusted, requires user review/confirmation)
  - TIER 3: FULL_PROTECTED (high risk or hard safety overrides, requires snapshot & explicit authorization)
  - BLOCKED (violates safety policy or insurmountable risk)
- Dynamic Live Risk calculation factoring:
  - Base recipe risk
  - Normalized live machine state (CPU/RAM/Disk/Locks/Drift/Failures)
  - Execution permissions / admin requirement
  - Data / environment impact
  - Rollback difficulty
  - Operation context
- TierPolicyConfig:
  - Configurable, typed, validated policy thresholds.
- Pure Policy Selection:
  - No OS/subprocess/winreg side-effects.
- Hard Safety Overrides:
  - Evaluated before normal tier scoring for protected system configurations.
- Controlled Tier Trust Requirement:
  - Enforces both risk <= controlled_max_risk AND trust >= controlled_min_trust.
- Unknown State Safety:
  - Unknown machine signals are treated conservatively, never silently converted to safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from machine_state import MachineState
from recipe_engine import RecipeOperation, StructuredRecipe

logger = logging.getLogger("pc_doctor.execution_tier")


class ExecutionTier(str, Enum):
    TIER_0_READ_ONLY = "TIER_0_READ_ONLY"
    TIER_1_FAST = "TIER_1_FAST"
    TIER_2_CONTROLLED = "TIER_2_CONTROLLED"
    TIER_3_FULL_PROTECTED = "TIER_3_FULL_PROTECTED"
    TIER_3_ELEVATED_ADMIN = "TIER_3_FULL_PROTECTED"
    BLOCKED = "BLOCKED"

    @property
    def requires_approval(self) -> bool:
        """Indicates whether execution requires explicit user authorization."""
        return self in (
            ExecutionTier.TIER_2_CONTROLLED,
            ExecutionTier.TIER_3_FULL_PROTECTED,
            ExecutionTier.TIER_3_ELEVATED_ADMIN,
        )


@dataclass
class TierPolicyConfig:
    """Configurable, typed, validated policy thresholds for execution tiers."""
    fast_path_trust_min: float = 0.85
    fast_path_risk_max: float = 0.30
    fast_path_confidence_min: float = 0.80

    controlled_trust_min: float = 0.60
    controlled_risk_max: float = 0.70

    full_protected_risk_max: float = 0.90

    min_disk_free_gb: float = 5.0
    warn_cpu_percent: float = 80.0
    warn_ram_percent: float = 85.0

    allow_unknown_as_safe: bool = False

    def validate(self) -> None:
        """Ensures all thresholds satisfy architectural ordering and domain bounds."""
        if not (0.0 <= self.fast_path_risk_max < self.controlled_risk_max <= self.full_protected_risk_max <= 1.0):
            raise ValueError(
                f"Invalid risk thresholds: must satisfy 0.0 <= fast_path_risk_max ({self.fast_path_risk_max}) "
                f"< controlled_risk_max ({self.controlled_risk_max}) <= full_protected_risk_max ({self.full_protected_risk_max}) <= 1.0"
            )
        if not (0.0 <= self.controlled_trust_min <= self.fast_path_trust_min <= 1.0):
            raise ValueError(
                f"Invalid trust thresholds: must satisfy 0.0 <= controlled_trust_min ({self.controlled_trust_min}) "
                f"<= fast_path_trust_min ({self.fast_path_trust_min}) <= 1.0"
            )
        if not (0.0 <= self.fast_path_confidence_min <= 1.0):
            raise ValueError(f"Confidence threshold must be between 0.0 and 1.0: {self.fast_path_confidence_min}")
        if self.min_disk_free_gb < 0.0:
            raise ValueError("min_disk_free_gb must be non-negative")


# Global active policy
_ACTIVE_POLICY = TierPolicyConfig()


def get_tier_policy() -> TierPolicyConfig:
    """Returns the current active tier policy configuration."""
    return _ACTIVE_POLICY


def set_tier_policy(policy: TierPolicyConfig) -> None:
    """Sets and validates the active tier policy configuration."""
    policy.validate()
    global _ACTIVE_POLICY
    _ACTIVE_POLICY = policy


def reset_tier_policy() -> None:
    """Resets the tier policy configuration to default values."""
    global _ACTIVE_POLICY
    _ACTIVE_POLICY = TierPolicyConfig()


# Backward-compatible module-level threshold references
FAST_PATH_TRUST_MIN = 0.85
FAST_PATH_RISK_MAX = 0.30
FAST_PATH_CONFIDENCE_MIN = 0.80
CONTROLLED_RISK_MAX = 0.70
CONTROLLED_TRUST_MIN = 0.60


# Hard override regex patterns for protected system configurations
HARD_OVERRIDE_PATTERNS = [
    # Boot configuration
    r"\b(bcdedit|bootcfg|update-grub|grub-install|grub2-install|bootctl)\b",
    # System firewall / network configuration
    r"\b(netsh\s+advfirewall|netsh\s+firewall|iptables|ufw|firewall-cmd|nftables)\b",
    # Core system registry manipulation
    r"\b(reg\s+(?:add|delete|import|restore)\s+.*HKLM\\(?:SYSTEM|SAM|SECURITY))\b",
    # Kernel modules / core drivers
    r"\b(modprobe|insmod|rmmod|kextload|kextunload)\b",
    # Credential & user database manipulation
    r"\b(net\s+user|passwd|chpasswd|useradd|userdel|usermod|groupadd|groupdel)\b",
]

HARD_OVERRIDE_REGEXES = [re.compile(p, re.IGNORECASE) for p in HARD_OVERRIDE_PATTERNS]


def check_hard_safety_override(command_str: str) -> Optional[Tuple[ExecutionTier, str]]:
    """
    Evaluates whether an operation touches protected system configurations,
    requiring a hard safety override to Full Protected Path regardless of
    ordinary risk/trust scores.
    """
    if not command_str:
        return None

    cmd = command_str.strip()
    for reg in HARD_OVERRIDE_REGEXES:
        if reg.search(cmd):
            return (
                ExecutionTier.TIER_3_FULL_PROTECTED,
                f"Hard safety override: Protected system configuration detected ({reg.pattern}) "
                f"requires Full Protected Path (pre-execution snapshot and explicit user authorization)."
            )

    return None


def compute_live_risk(
    recipe: Optional[StructuredRecipe] = None,
    machine_state: Optional[Any] = None,
    requires_elevation: bool = False,
    data_impact: str = "LOW",          # "NONE", "LOW", "MEDIUM", "HIGH"
    rollback_difficulty: str = "EASY", # "TRIVIAL", "EASY", "MEDIUM", "HARD"
    policy: Optional[TierPolicyConfig] = None,
    command: Optional[str] = None,
    operation: Optional[RecipeOperation] = None,
    risk_base: Optional[str] = None,
) -> float:
    """
    Computes dynamic risk score [0.0 - 1.0].
    Combines base risk + machine state signals + permissions + data impact + rollback difficulty.
    Supports structured recipes or raw commands with explicit operation.
    """
    pol = policy or get_tier_policy()

    # 1. Base recipe risk
    base_map = {"Low": 0.15, "Medium": 0.45, "High": 0.75}
    effective_op = operation
    if recipe is not None:
        risk = base_map.get(recipe.risk_base, 0.40)
        effective_op = recipe.operation
    else:
        # For raw/unknown command without a recipe:
        # Default to Medium (0.45) or use risk_base if supplied
        r_base = risk_base or "Medium"
        if command:
            c_low = command.strip().lower()
            if c_low.startswith("echo ") or c_low.endswith("--version") or c_low.endswith("-v") or c_low == "echo" or c_low.startswith("git config"):
                r_base = "Low"
                if c_low.startswith("git config"):
                    data_impact = "NONE"
                    rollback_difficulty = "TRIVIAL"
        risk = base_map.get(r_base, 0.45)

    # 2. Operation type weighting
    if effective_op in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
        return 0.05
    elif effective_op == RecipeOperation.INSTALL:
        risk += 0.05
    elif effective_op in (RecipeOperation.UPDATE, RecipeOperation.REPAIR):
        risk += 0.10
    elif effective_op in (RecipeOperation.UNINSTALL, RecipeOperation.REINSTALL, RecipeOperation.CLEANUP):
        risk += 0.20

    # 3. Elevation requirement
    if requires_elevation:
        risk += 0.15

    # 4. Data impact
    data_weights = {"NONE": 0.0, "LOW": 0.05, "MEDIUM": 0.15, "HIGH": 0.25}
    risk += data_weights.get(data_impact.upper(), 0.05)

    # 5. Rollback difficulty
    rollback_weights = {"TRIVIAL": 0.0, "EASY": 0.05, "MEDIUM": 0.10, "HARD": 0.20}
    risk += rollback_weights.get(rollback_difficulty.upper(), 0.05)

    # 6. Machine state impact
    if machine_state:
        # Normalize to MachineState if dict
        m_state = machine_state if isinstance(machine_state, MachineState) else MachineState.from_dict(machine_state)

        # CPU/RAM high load
        if m_state.cpu_percent is not None and m_state.cpu_percent > pol.warn_cpu_percent:
            risk += 0.15
        elif m_state.ram_percent is not None and m_state.ram_percent > pol.warn_ram_percent:
            risk += 0.15

        # Disk low
        if m_state.low_disk_space is True or (m_state.free_disk_gb is not None and m_state.free_disk_gb < pol.min_disk_free_gb):
            risk += 0.20
        elif m_state.low_disk_space is None and m_state.free_disk_gb is None and not pol.allow_unknown_as_safe:
            risk += 0.10

        # Conflict or previous failure
        if m_state.conflicts is True:
            risk += 0.15
        if m_state.previous_failure is True:
            risk += 0.15
        if m_state.pending_reboot is True:
            risk += 0.10
        if m_state.dependency_lock is True:
            risk += 0.15
        if m_state.environment_drift is True:
            risk += 0.10

    return min(1.0, max(0.0, round(risk, 2)))


def select_execution_tier(
    recipe: Optional[StructuredRecipe] = None,
    trust_score: float = 0.9,       # 0.0 to 1.0 (Static DB recipes have 1.0, dynamic start at 0.5)
    risk_score: float = 0.2,        # 0.0 to 1.0
    confidence_score: float = 1.0,  # 0.0 to 1.0
    machine_state: Optional[Any] = None,
    policy: Optional[TierPolicyConfig] = None,
    command: Optional[str] = None,
    operation: Optional[RecipeOperation] = None,
) -> Tuple[ExecutionTier, str]:
    """
    Selects authoritative execution tier as a pure policy function of its inputs:
    - Tier 0: Read-only operations.
    - Hard Safety Overrides: Protected system configurations force Tier 3 Full Protected.
    - Tier 1 (Fast Path):
      trust >= fast_path_trust_min AND risk <= fast_path_risk_max AND
      confidence >= fast_path_confidence_min AND confirmed normal machine state (no conflicts, no pending reboot, etc.).
    - Tier 2 (Controlled Path):
      risk <= controlled_risk_max AND trust >= controlled_min_trust.
      (Confidence does not block Controlled path, allowing trusted first-time Static recipes to take Controlled path).
    - Tier 3 (Full Protected):
      High risk (risk <= full_protected_risk_max) OR insufficient trust for Controlled tier.
    - Blocked:
      Insurmountable risk (risk > full_protected_risk_max) or safety policy violations.
    """
    pol = policy or get_tier_policy()

    # 1. Check for read-only operations
    effective_op = recipe.operation if recipe else operation
    if effective_op in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
        return ExecutionTier.TIER_0_READ_ONLY, "Read-only inspection operation."

    # 2. Hard Safety Overrides (Evaluated BEFORE normal scoring)
    cmd_str = recipe.to_command_string() if recipe else (command or "")
    override = check_hard_safety_override(cmd_str)
    if override is not None:
        return override

    # 3. Machine State Assessment
    m_state = machine_state if isinstance(machine_state, MachineState) else (MachineState.from_dict(machine_state) if machine_state else MachineState())
    is_normal, abnormal_reasons = m_state.is_normal_state(allow_unknown_as_safe=pol.allow_unknown_as_safe)

    # 4. Fast Path Evaluation (Section 15)
    if (
        trust_score >= pol.fast_path_trust_min
        and risk_score <= pol.fast_path_risk_max
        and confidence_score >= pol.fast_path_confidence_min
        and is_normal
    ):
        return ExecutionTier.TIER_1_FAST, "Eligible for Fast Path automated execution."

    # If Fast Path was disqualified due to machine state, capture why
    fast_path_disqualified_reason = ""
    if not is_normal:
        fast_path_disqualified_reason = f"Machine state abnormal/unknown: {'; '.join(abnormal_reasons)}"

    # 5. Controlled Path Evaluation (Section 15)
    # Controlled routing enforces BOTH risk <= controlled_risk_max AND trust >= controlled_min_trust
    if risk_score <= pol.controlled_risk_max:
        if trust_score >= pol.controlled_trust_min:
            msg = "Routed to Controlled Path (requires standard user review/confirmation)."
            if fast_path_disqualified_reason:
                msg += f" [{fast_path_disqualified_reason}]"
            return ExecutionTier.TIER_2_CONTROLLED, msg
        else:
            # Trust is insufficient for Controlled Path! Escalate appropriately
            if risk_score <= pol.full_protected_risk_max:
                return (
                    ExecutionTier.TIER_3_FULL_PROTECTED,
                    f"Insufficient trust ({trust_score:.2f} < {pol.controlled_trust_min:.2f}) for Controlled Path; "
                    f"escalated to Full Protected Path (requires pre-execution snapshot and explicit approval)."
                )
            else:
                return (
                    ExecutionTier.BLOCKED,
                    f"Insufficient trust ({trust_score:.2f}) and unacceptable risk ({risk_score:.2f}) (Blocked)."
                )

    # 6. High risk -> Full Protected Path
    if risk_score <= pol.full_protected_risk_max:
        return (
            ExecutionTier.TIER_3_FULL_PROTECTED,
            f"Routed to Full Protected Path (risk {risk_score:.2f} requires pre-execution snapshot and explicit approval)."
        )

    # 7. Blocked: Insurmountable risk
    return ExecutionTier.BLOCKED, f"Risk {risk_score:.2f} exceeds acceptable limits (Blocked)."
