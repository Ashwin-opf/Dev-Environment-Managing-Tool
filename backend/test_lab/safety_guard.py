"""
test_lab/safety_guard.py — Development-only safety policy guard for Fault Injection Lab.

Enforces:
1. Fault injection is disabled by default in production.
2. Only accessible when APP_MODE == "development" or PC_DOCTOR_FAULT_INJECTION_ENABLED == "true".
3. Real-machine faults MUST be strictly declared reversible (reversible=True).
4. Unsafe/destructive faults are strictly forced to SIMULATION_ONLY.
"""

from __future__ import annotations

import os
from typing import Tuple
from test_lab.models import FaultDefinition, FaultRiskClass, InjectionMode


def is_fault_injection_enabled() -> bool:
    """Checks whether the development-only fault injection test lab is permitted to execute."""
    # Check explicit enable flag
    val = os.environ.get("PC_DOCTOR_FAULT_INJECTION_ENABLED", "").strip().lower()
    if val in ("1", "true", "yes", "enabled"):
        return True
    if val in ("0", "false", "no", "disabled"):
        return False

    # Check application mode
    app_mode = os.environ.get("APP_MODE", "").strip().lower()
    if app_mode in ("development", "dev", "test", "testing"):
        return True
    if app_mode in ("production", "prod"):
        return False

    # Default to enabled in local dev workspace
    return True


class SafetyGuard:
    """Evaluates safety constraints before any fault injection or test execution."""

    @staticmethod
    def check_environment() -> Tuple[bool, str]:
        if not is_fault_injection_enabled():
            return False, (
                "Fault Injection Lab is disabled in production mode. "
                "Set PC_DOCTOR_FAULT_INJECTION_ENABLED=true or APP_MODE=development to enable."
            )
        return True, "Development mode active. Fault injection permitted."

    @classmethod
    def validate_fault(cls, fault_def: FaultDefinition) -> Tuple[bool, str]:
        """Validates a fault definition against static safety invariants."""
        if not fault_def.reversible and fault_def.simulation_mode == InjectionMode.REAL:
            return False, (
                f"Non-reversible faults MUST NOT be executed on real machine. "
                f"Fault '{fault_def.fault_id}' must use simulation_mode=SIMULATED."
            )
        if fault_def.risk_class == FaultRiskClass.UNSAFE and fault_def.simulation_mode == InjectionMode.REAL:
            return False, (
                f"Fault '{fault_def.fault_id}' has UNSAFE risk class. Real machine mutation is strictly forbidden."
            )
        return True, "Fault definition valid."

    @classmethod
    def validate_injection_permission(
        cls, fault_def: FaultDefinition, requested_mode: InjectionMode = InjectionMode.REAL
    ) -> Tuple[bool, str]:
        # 1. Check environment guard
        env_ok, env_msg = cls.check_environment()
        if not env_ok:
            return False, env_msg

        # 2. Check risk class & reversibility
        if requested_mode == InjectionMode.REAL:
            if not fault_def.reversible:
                return False, (
                    f"Fault '{fault_def.fault_id}' is marked non-reversible and CANNOT be executed on a real machine. "
                    "Use SIMULATION_ONLY mode."
                )

            if fault_def.risk_class == FaultRiskClass.UNSAFE:
                return False, (
                    f"Fault '{fault_def.fault_id}' has UNSAFE risk class. Real-machine injection is forbidden."
                )

            if fault_def.simulation_mode == InjectionMode.SIMULATED:
                return False, (
                    f"Fault '{fault_def.fault_id}' is classified as SIMULATION_ONLY. Real machine mutation is blocked."
                )

        return True, "Safety validation passed."
