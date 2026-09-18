"""
machine_state.py — Normalized Machine State Model for PC Doctor.

Provides a typed, normalized representation of real host machine state facts
for consumption by execution tier policy, live risk computation, and safety gates.
Platform-specific probes populate this model; tier policy evaluates it as a pure input.

Guarantees:
- Tri-state representation: True, False, or None (representing UNKNOWN).
- Conservative evaluation: UNKNOWN is never silently converted to SAFE unless
  explicitly configured.
- Dict-like interface for backward compatibility with existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SignalStatus(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


def _normalize_tristate(val: Any) -> Optional[bool]:
    """Converts a value to True, False, or None (UNKNOWN)."""
    if val is None or val == "UNKNOWN" or val == SignalStatus.UNKNOWN:
        return None
    if isinstance(val, str):
        v_lower = val.strip().lower()
        if v_lower in ("true", "1", "yes"):
            return True
        if v_lower in ("false", "0", "no"):
            return False
        return None
    return bool(val)


@dataclass
class MachineState:
    """
    Normalized machine state signals collected from platform providers.
    All safety/health signals support Tri-state: True, False, or None (UNKNOWN).
    """
    pending_reboot: Optional[bool] = None
    low_disk_space: Optional[bool] = None
    service_issue: Optional[bool] = None
    dependency_lock: Optional[bool] = None
    package_manager_available: Optional[bool] = None
    installation_state_changed: Optional[bool] = None
    previous_failure: Optional[bool] = None
    environment_drift: Optional[bool] = None
    conflicts: Optional[bool] = None
    unusual_state: Optional[bool] = None

    # Quantitative metrics
    cpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    free_disk_gb: Optional[float] = None
    total_disk_gb: Optional[float] = None

    # Contextual metadata
    tools: Dict[str, Any] = field(default_factory=dict)
    os: str = "Unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes machine state to a standard dictionary."""
        d = asdict(self)
        # Ensure aliases are present for backward compatibility
        d["relevant_service_unexpected_state"] = self.service_issue
        d["dependency_or_resource_lock"] = self.dependency_lock
        d["package_manager_unavailable"] = (not self.package_manager_available) if self.package_manager_available is not None else None
        d["previous_execution_failure"] = self.previous_failure
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MachineState:
        """Constructs MachineState from an existing dictionary."""
        if not data:
            return cls()

        # Legacy fallback: If the dictionary explicitly asserts unusual_state is False
        # and omits newly introduced Stage 4 signals, default those omitted signals to False.
        # However, if any signal is explicitly present in the dict (even as None or "UNKNOWN"),
        # preserve that exact value so explicit UNKNOWN handling remains strictly conservative.
        legacy_clean = (data.get("unusual_state") is False)

        def _get_signal(key: str, default: Optional[bool] = None) -> Optional[bool]:
            if key in data:
                return _normalize_tristate(data[key])
            return False if legacy_clean else default

        # Handle aliases
        service = data.get("service_issue")
        if service is None and "relevant_service_unexpected_state" in data:
            service = data.get("relevant_service_unexpected_state")

        dep_lock = data.get("dependency_lock")
        if dep_lock is None and "dependency_or_resource_lock" in data:
            dep_lock = data.get("dependency_or_resource_lock")

        pkg_avail = data.get("package_manager_available")
        if pkg_avail is None and "package_manager_unavailable" in data:
            unavail = data.get("package_manager_unavailable")
            pkg_avail = (not unavail) if unavail is not None else None

        prev_fail = data.get("previous_failure")
        if prev_fail is None and "previous_execution_failure" in data:
            prev_fail = data.get("previous_execution_failure")

        cpu = data.get("cpu_percent")
        if cpu is not None and str(cpu).upper() != "UNKNOWN":
            try:
                cpu = float(cpu)
            except (ValueError, TypeError):
                cpu = None
        else:
            cpu = None

        ram = data.get("ram_percent")
        if ram is not None and str(ram).upper() != "UNKNOWN":
            try:
                ram = float(ram)
            except (ValueError, TypeError):
                ram = None
        else:
            ram = None

        free_d = data.get("free_disk_gb")
        if free_d is not None and str(free_d).upper() != "UNKNOWN":
            try:
                free_d = float(free_d)
            except (ValueError, TypeError):
                free_d = None
        else:
            free_d = None

        total_d = data.get("total_disk_gb")
        if total_d is not None and str(total_d).upper() != "UNKNOWN":
            try:
                total_d = float(total_d)
            except (ValueError, TypeError):
                total_d = None
        else:
            total_d = None

        # Determine low_disk_space if not explicitly set
        if "low_disk_space" in data:
            low_disk = _normalize_tristate(data["low_disk_space"])
        elif free_d is not None:
            low_disk = (free_d < 5.0)
        elif legacy_clean:
            low_disk = False
        else:
            low_disk = None

        return cls(
            pending_reboot=_get_signal("pending_reboot"),
            low_disk_space=low_disk,
            service_issue=_normalize_tristate(service) if service is not None or ("service_issue" in data or "relevant_service_unexpected_state" in data) else (False if legacy_clean else None),
            dependency_lock=_normalize_tristate(dep_lock) if dep_lock is not None or ("dependency_lock" in data or "dependency_or_resource_lock" in data) else (False if legacy_clean else None),
            package_manager_available=_normalize_tristate(pkg_avail) if pkg_avail is not None or ("package_manager_available" in data or "package_manager_unavailable" in data) else (True if legacy_clean else None),
            installation_state_changed=_get_signal("installation_state_changed"),
            previous_failure=_normalize_tristate(prev_fail) if prev_fail is not None or ("previous_failure" in data or "previous_execution_failure" in data) else (False if legacy_clean else None),
            environment_drift=_get_signal("environment_drift"),
            conflicts=_get_signal("conflicts"),
            unusual_state=_get_signal("unusual_state"),
            cpu_percent=cpu,
            ram_percent=ram,
            free_disk_gb=free_d,
            total_disk_gb=total_d,
            tools=data.get("tools", {}),
            os=data.get("os", "Unknown"),
            metadata=data.get("metadata", {}),
        )

    # Dict-like emulation for seamless backward compatibility
    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        return d[key]

    def get(self, key: str, default: Any = None) -> Any:
        d = self.to_dict()
        val = d.get(key, default)
        return val if val is not None else default

    def is_normal_state(self, allow_unknown_as_safe: bool = False) -> Tuple[bool, List[str]]:
        """
        Evaluates whether the machine state represents a confirmed normal, healthy baseline.
        Returns (is_normal, reasons_if_not_normal).
        """
        reasons: List[str] = []

        # 1. Pending reboot
        if self.pending_reboot is True:
            reasons.append("System has a pending reboot requirement.")
        elif self.pending_reboot is None and not allow_unknown_as_safe:
            reasons.append("Pending reboot status is UNKNOWN.")

        # 2. Low disk space
        if self.low_disk_space is True or (self.free_disk_gb is not None and self.free_disk_gb < 5.0):
            reasons.append(f"Low disk space detected ({self.free_disk_gb} GB free).")
        elif self.low_disk_space is None and self.free_disk_gb is None and not allow_unknown_as_safe:
            reasons.append("Available disk space is UNKNOWN.")

        # 3. Conflicts
        if self.conflicts is True:
            reasons.append("Active resource or executable conflicts detected.")
        elif self.conflicts is None and not allow_unknown_as_safe:
            reasons.append("Conflict state is UNKNOWN.")

        # 4. Dependency or resource lock
        if self.dependency_lock is True:
            reasons.append("Package manager or critical resource is currently locked.")
        elif self.dependency_lock is None and not allow_unknown_as_safe:
            reasons.append("Resource lock state is UNKNOWN.")

        # 5. Service issue
        if self.service_issue is True:
            reasons.append("Relevant system service is in an unexpected/abnormal state.")

        # 6. Package manager availability
        if self.package_manager_available is False:
            reasons.append("Required package manager is unavailable or non-functional.")

        # 7. Environment drift
        if self.environment_drift is True:
            reasons.append("Environment drift detected between process and system.")

        # 8. Unusual state flag
        if self.unusual_state is True:
            reasons.append("Machine flagged with general unusual state.")
        elif self.unusual_state is None and not allow_unknown_as_safe:
            reasons.append("General unusual state assessment is UNKNOWN.")

        # 9. High resource load
        if self.cpu_percent is not None and self.cpu_percent > 80.0:
            reasons.append(f"High CPU utilization ({self.cpu_percent}% > 80%).")
        if self.ram_percent is not None and self.ram_percent > 85.0:
            reasons.append(f"High RAM utilization ({self.ram_percent}% > 85%).")

        return (len(reasons) == 0, reasons)
