"""
PC Doctor – Fault Injection / Test Lab Package
==============================================
Development-only test harness for controlled, reversible fault injection
and authoritative measurement of the PC Doctor detection → diagnosis →
recipe resolution → policy/tier → execution → verification pipeline.
"""

from test_lab.models import (
    FaultCapability,
    FaultDefinition,
    FaultRiskClass,
    InjectionMode,
    TestResult,
    TestStatus,
    BaselineRecord,
)
from test_lab.baseline_manager import BaselineManager, baseline_manager
from test_lab.safety_guard import SafetyGuard, is_fault_injection_enabled
from test_lab.catalog import FaultCatalog, fault_catalog
from test_lab.verifier import FaultVerifier, fault_verifier
from test_lab.test_runner import TestRunner, test_runner
from test_lab.solvability_report import SolvabilityReporter, solvability_reporter

__all__ = [
    "FaultCapability",
    "FaultDefinition",
    "FaultRiskClass",
    "InjectionMode",
    "TestResult",
    "TestStatus",
    "BaselineRecord",
    "BaselineManager",
    "baseline_manager",
    "SafetyGuard",
    "is_fault_injection_enabled",
    "FaultCatalog",
    "fault_catalog",
    "FaultVerifier",
    "fault_verifier",
    "TestRunner",
    "test_runner",
    "SolvabilityReporter",
    "solvability_reporter",
]
