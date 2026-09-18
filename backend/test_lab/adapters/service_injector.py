"""
test_lab/adapters/service_injector.py — Generic service fault injector.

Controls non-critical developer services (e.g. MySQL80, Docker) for test injection.
"""

from __future__ import annotations

import platform
import subprocess
from test_lab.adapters.base import FaultInjector
from test_lab.models import BaselineRecord, FaultDefinition
from dev_environment_detector import dev_environment_detector
from platform_abstraction import get_service_manager


class ServiceFaultInjector(FaultInjector):
    """Generic cross-platform service fault injector."""

    # Approved non-critical test services
    APPROVED_TEST_SERVICES = {"MySQL80", "mysql", "docker", "test_svc"}

    def inject(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        service_name = fault_def.metadata.get("service_name", fault_def.target)
        if service_name not in self.APPROVED_TEST_SERVICES and not service_name.lower().startswith("test"):
            return False

        try:
            mgr = get_service_manager()
            mgr.stop(service_name)
            return self.verify_fault_present(fault_def, baseline)
        except Exception:
            return False

    def verify_fault_present(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        service_name = fault_def.metadata.get("service_name", fault_def.target)
        info = dev_environment_detector.check_service(service_name)
        return info.get("status") in ("Stopped", "NotFound")

    def restore(self, baseline: BaselineRecord) -> bool:
        service_name = baseline.original_state.get("service_name")
        orig_status = baseline.original_state.get("original_status")
        if not service_name or orig_status != "Running":
            return True

        try:
            mgr = get_service_manager()
            mgr.start(service_name)
            return True
        except Exception:
            return False

    def verify_restored(self, baseline: BaselineRecord) -> bool:
        service_name = baseline.original_state.get("service_name")
        orig_status = baseline.original_state.get("original_status")
        if not service_name:
            return True
        info = dev_environment_detector.check_service(service_name)
        return info.get("status") == orig_status
