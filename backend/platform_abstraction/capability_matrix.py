"""
platform_abstraction/capability_matrix.py — Authoritative Cross-Platform Capability Matrix.

Records real implementation capabilities across Windows, Linux, and macOS.
Status values:
- "SUPPORTED": Fully implemented and authoritatively verified on the platform.
- "PARTIAL": Real adapter boundary and initial implementation exists; not all edge cases verified.
- "UNSUPPORTED": Not yet implemented on this platform (explicitly rejects rather than faking success).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


class PlatformCapability(str, Enum):
    PATH_INSPECTION = "PATH_INSPECTION"
    PATH_REPAIR_USER = "PATH_REPAIR_USER"
    PATH_REPAIR_MACHINE = "PATH_REPAIR_MACHINE"
    PRIVILEGE_ELEVATION = "PRIVILEGE_ELEVATION"
    MACHINE_PRIVILEGE = "PRIVILEGE_ELEVATION"
    SERVICE_INSPECTION = "SERVICE_INSPECTION"
    SERVICE_CONTROL = "SERVICE_CONTROL"
    PACKAGE_MANAGEMENT = "PACKAGE_MANAGEMENT"
    PACKAGE_MANAGER_DETECTION = "PACKAGE_MANAGEMENT"
    TOOL_VERIFICATION = "TOOL_VERIFICATION"
    BINARY_VERIFICATION = "TOOL_VERIFICATION"
    PORT_INSPECTION = "PORT_INSPECTION"
    PROCESS_INSPECTION = "PROCESS_INSPECTION"


CAPABILITY_MATRIX: Dict[str, Dict[str, CapabilityStatus]] = {
    "PATH_INSPECTION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
    "PATH_REPAIR_USER": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
    "PATH_REPAIR_MACHINE": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.PARTIAL,
        "Darwin": CapabilityStatus.PARTIAL,
    },
    "PRIVILEGE_ELEVATION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.PARTIAL,
        "Darwin": CapabilityStatus.PARTIAL,
    },
    "SERVICE_INSPECTION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.PARTIAL,
    },
    "SERVICE_CONTROL": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.PARTIAL,
        "Darwin": CapabilityStatus.PARTIAL,
    },
    "PACKAGE_MANAGEMENT": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
    "TOOL_VERIFICATION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
    "PORT_INSPECTION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
    "PROCESS_INSPECTION": {
        "Windows": CapabilityStatus.SUPPORTED,
        "Linux": CapabilityStatus.SUPPORTED,
        "Darwin": CapabilityStatus.SUPPORTED,
    },
}


ALIASES: Dict[str, str] = {
    "MACHINE_PRIVILEGE": "PRIVILEGE_ELEVATION",
    "PACKAGE_MANAGER_DETECTION": "PACKAGE_MANAGEMENT",
    "BINARY_VERIFICATION": "TOOL_VERIFICATION",
}


def get_capability_status(capability: Any, platform_name: str) -> CapabilityStatus:
    """Returns the capability status for a given capability name and platform."""
    cap = str(getattr(capability, "value", capability)).upper()
    cap = ALIASES.get(cap, cap)
    plat = platform_name.capitalize()
    if plat == "Macos":
        plat = "Darwin"
    if cap not in CAPABILITY_MATRIX:
        return CapabilityStatus.UNSUPPORTED
    return CAPABILITY_MATRIX[cap].get(plat, CapabilityStatus.UNSUPPORTED)


def is_capability_supported(capability: Any, platform_name: str) -> bool:
    """Returns True if the capability is fully SUPPORTED on the given platform."""
    return get_capability_status(capability, platform_name) == CapabilityStatus.SUPPORTED


def get_platform_capabilities(platform_name: str) -> Dict[str, CapabilityStatus]:
    """Returns all capability statuses for a platform as a dictionary of CapabilityStatus."""
    plat = platform_name.capitalize()
    if plat == "Macos":
        plat = "Darwin"
    result: Dict[str, CapabilityStatus] = {
        cap: statuses.get(plat, CapabilityStatus.UNSUPPORTED)
        for cap, statuses in CAPABILITY_MATRIX.items()
    }
    # Include aliases
    for alias, target in ALIASES.items():
        if target in result:
            result[alias] = result[target]
    return result


def to_matrix_dict() -> Dict[str, Dict[str, str]]:
    """Exports the entire matrix as a JSON-serializable dictionary."""
    base: Dict[str, Dict[str, str]] = {
        cap: {plat: status.value for plat, status in platforms.items()}
        for cap, platforms in CAPABILITY_MATRIX.items()
    }
    for alias, target in ALIASES.items():
        if target in base:
            base[alias] = dict(base[target])
    return base


def get_capability_matrix() -> Dict[str, Any]:
    """Returns the full capability matrix structure with capabilities and summary."""
    caps = to_matrix_dict()
    summary = {
        "Windows": {
            "supported": sum(1 for v in caps.values() if v.get("Windows") == CapabilityStatus.SUPPORTED.value),
            "partial": sum(1 for v in caps.values() if v.get("Windows") == CapabilityStatus.PARTIAL.value),
            "unsupported": sum(1 for v in caps.values() if v.get("Windows") == CapabilityStatus.UNSUPPORTED.value),
        },
        "Linux": {
            "supported": sum(1 for v in caps.values() if v.get("Linux") == CapabilityStatus.SUPPORTED.value),
            "partial": sum(1 for v in caps.values() if v.get("Linux") == CapabilityStatus.PARTIAL.value),
            "unsupported": sum(1 for v in caps.values() if v.get("Linux") == CapabilityStatus.UNSUPPORTED.value),
        },
        "Darwin": {
            "supported": sum(1 for v in caps.values() if v.get("Darwin") == CapabilityStatus.SUPPORTED.value),
            "partial": sum(1 for v in caps.values() if v.get("Darwin") == CapabilityStatus.PARTIAL.value),
            "unsupported": sum(1 for v in caps.values() if v.get("Darwin") == CapabilityStatus.UNSUPPORTED.value),
        },
    }
    return {
        "capabilities": caps,
        "summary": summary,
    }

