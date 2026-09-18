"""
test_lab/models.py — Data models for the PC Doctor Fault Injection / Test Lab.

Defines schemas for:
- FaultDefinition: What fault is being tested without containing shell commands.
- BaselineRecord: Minimal state captured before injection to guarantee safe restoration.
- TestResult: Comprehensive telemetry across the full PC Doctor pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class FaultRiskClass(str, Enum):
    CONTROLLED = "CONTROLLED"
    SIMULATED = "SIMULATED"
    UNSAFE = "UNSAFE"


class FaultCapability(str, Enum):
    PATH = "PATH"
    SERVICE = "SERVICE"
    PORT = "PORT"
    VERSION_IDENTITY = "VERSION_IDENTITY"
    VERIFICATION = "VERIFICATION"
    DRIVER = "DRIVER"
    DISK = "DISK"
    BOOT = "BOOT"


class InjectionMode(str, Enum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"
    MOCK = "MOCK"


class TestStatus(str, Enum):
    PASS = "PASS"
    PASS_EXPECTED_REVIEW = "PASS_EXPECTED_REVIEW"
    FAILED_DETECTION = "FAILED_DETECTION"
    FAILED_DIAGNOSIS = "FAILED_DIAGNOSIS"
    FAILED_RECIPE = "FAILED_RECIPE"
    BLOCKED_EXPECTED = "BLOCKED_EXPECTED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"
    FAILED_RESTORATION = "FAILED_RESTORATION"
    SKIPPED = "SKIPPED"
    SIMULATION_ONLY = "SIMULATION_ONLY"


@dataclass
class FaultDefinition:
    fault_id: str
    target: str
    capability: FaultCapability
    scope: Optional[str] = "MACHINE"
    platforms: List[str] = field(default_factory=lambda: ["windows"])
    risk_class: FaultRiskClass = FaultRiskClass.CONTROLLED
    reversible: bool = True
    requires_admin: bool = False
    verification: str = ""
    injector: str = "PATH_ENTRY_REMOVAL"
    simulation_mode: InjectionMode = InjectionMode.REAL
    expected_behavior: str = "REPAIR_AND_VERIFY"
    description: str = ""
    target_entry: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["capability"] = self.capability.value
        d["risk_class"] = self.risk_class.value
        d["simulation_mode"] = self.simulation_mode.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FaultDefinition:
        cap = data.get("capability", "PATH")
        if isinstance(cap, str):
            cap = FaultCapability(cap)

        rc = data.get("risk_class", "CONTROLLED")
        if isinstance(rc, str):
            rc = FaultRiskClass(rc)

        sm = data.get("simulation_mode", "REAL")
        if isinstance(sm, str):
            sm = InjectionMode(sm)

        return cls(
            fault_id=data["fault_id"],
            target=data["target"],
            capability=cap,
            scope=data.get("scope"),
            platforms=list(data.get("platforms", ["windows"])),
            risk_class=rc,
            reversible=bool(data.get("reversible", True)),
            requires_admin=bool(data.get("requires_admin", False)),
            verification=data.get("verification", ""),
            injector=data.get("injector", "PATH_ENTRY_REMOVAL"),
            simulation_mode=sm,
            expected_behavior=data.get("expected_behavior", "REPAIR_AND_VERIFY"),
            description=data.get("description", ""),
            target_entry=data.get("target_entry"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class BaselineRecord:
    test_id: str
    timestamp: str
    fault_id: str
    target_identity: str
    platform: str
    affected_resource: str
    original_state: Dict[str, Any] = field(default_factory=dict)
    restoration_strategy: str = "EXACT_OVERWRITE"
    cleanup_status: str = "PENDING"  # PENDING, RESTORED, FAILED_RESTORATION, NOT_NEEDED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BaselineRecord:
        return cls(
            test_id=data["test_id"],
            timestamp=data["timestamp"],
            fault_id=data["fault_id"],
            target_identity=data["target_identity"],
            platform=data["platform"],
            affected_resource=data["affected_resource"],
            original_state=dict(data.get("original_state", {})),
            restoration_strategy=data.get("restoration_strategy", "EXACT_OVERWRITE"),
            cleanup_status=data.get("cleanup_status", "PENDING"),
        )


@dataclass
class TestResult:
    test_id: str
    timestamp: str
    fault_id: str
    target: str
    platform: str
    simulation_mode: str = "REAL"
    baseline_captured: bool = False
    fault_injected: bool = False
    fault_verified: bool = False
    detected: bool = False
    diagnosed: bool = False
    recipe_resolved: bool = False
    safety_passed: bool = False
    tier: Optional[str] = None
    trust_score: Optional[float] = None
    risk_score: Optional[float] = None
    confidence_score: Optional[float] = None
    machine_state: Optional[Dict[str, Any]] = None
    approval_completed: bool = False
    repair_executed: bool = False
    repair_verified: bool = False
    original_problem_resolved: bool = False
    baseline_restored: bool = False
    restoration_verified: bool = False
    verification_levels: Dict[str, bool] = field(default_factory=lambda: {"L1": False, "L2": False, "L3": False, "L5": False})
    result: TestStatus = TestStatus.PASS
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["result"] = self.result.value
        return d
