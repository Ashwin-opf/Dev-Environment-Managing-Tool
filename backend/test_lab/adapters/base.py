"""
test_lab/adapters/base.py — Abstract interface for platform and capability fault injectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from test_lab.models import BaselineRecord, FaultDefinition


class FaultInjector(ABC):
    """Abstract interface that all capability/platform fault injectors must implement."""

    @abstractmethod
    def inject(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        """Injects the controlled fault onto the machine or simulation environment."""
        pass

    @abstractmethod
    def verify_fault_present(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        """Independently verifies that the fault is actually present."""
        pass

    @abstractmethod
    def restore(self, baseline: BaselineRecord) -> bool:
        """Restores the original baseline state captured before injection."""
        pass

    @abstractmethod
    def verify_restored(self, baseline: BaselineRecord) -> bool:
        """Independently verifies that the system has been returned to its baseline state."""
        pass


def get_platform_adapter(injector_type: str, platform_name: Optional[str] = None) -> FaultInjector:
    """
    Factory resolving platform-specific fault adapters for a given injector type.
    """
    import platform
    target_platform = (platform_name or platform.system()).lower()

    if injector_type in ("PATH_ENTRY_REMOVAL", "USER_PATH_ENTRY_REMOVAL", "PATH"):
        from test_lab.adapters.path_injector import (
            WindowsPathFaultInjector,
            LinuxPathFaultInjector,
            MacOSPathFaultInjector,
        )
        if target_platform == "windows":
            return WindowsPathFaultInjector()
        elif target_platform == "darwin":
            return MacOSPathFaultInjector()
        else:
            return LinuxPathFaultInjector()

    elif injector_type in ("SERVICE_STOP", "SERVICE"):
        from test_lab.adapters.service_injector import ServiceFaultInjector
        return ServiceFaultInjector()

    elif injector_type in ("PORT_CONFLICT", "PORT"):
        from test_lab.adapters.port_injector import PortConflictFaultInjector
        return PortConflictFaultInjector()

    elif injector_type in ("VERSION_FIXTURE", "VERSION_IDENTITY"):
        from test_lab.adapters.version_fixture_injector import VersionFixtureFaultInjector
        return VersionFixtureFaultInjector()

    else:
        from test_lab.adapters.simulation_injector import SimulationFaultInjector
        return SimulationFaultInjector()

