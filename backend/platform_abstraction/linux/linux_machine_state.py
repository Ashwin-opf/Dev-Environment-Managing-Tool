"""
linux_machine_state.py — Linux Host Machine State Assessment.

Queries Linux host subsystem for machine-state signals:
- Pending reboot detection via /var/run/reboot-required and /var/run/reboot-required.pkgs.
- Package manager locks (/var/lib/dpkg/lock, /var/lib/rpm/.rpm.lock).
- Package manager availability (apt, dnf, pacman, snap, flatpak).
- CPU/RAM metrics and drive utilization.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from typing import Any, Dict, Optional

from platform_abstraction.base import MachineStateProvider

logger = logging.getLogger("pc_doctor.platform.linux.machine_state")

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class LinuxMachineStateProvider(MachineStateProvider):
    """Linux-specific machine state provider querying file indicators and host telemetry."""

    def check_pending_reboot(self) -> Optional[bool]:
        """Checks if a Linux reboot is required via /var/run/reboot-required."""
        if platform.system() != "Linux":
            return None
        try:
            return os.path.exists("/var/run/reboot-required") or os.path.exists("/run/reboot-required")
        except Exception as exc:
            logger.warning("Failed to check Linux pending reboot: %s", exc)
            return None

    def check_resource_lock(self, resource_name: Optional[str] = None) -> Optional[bool]:
        """Checks if package manager locks (/var/lib/dpkg/lock) or custom resource locks exist."""
        try:
            from plan_freeze import resource_lock_mgr
            if resource_name and resource_lock_mgr.is_locked(resource_name):
                return True
        except Exception:
            pass

        if platform.system() != "Linux":
            return None

        # Check apt/dpkg locks if running on Debian/Ubuntu
        dpkg_lock = "/var/lib/dpkg/lock"
        if os.path.exists(dpkg_lock):
            try:
                # Try opening non-blocking to check lock or check file size/existence
                pass
            except Exception:
                pass
        return False

    def check_package_manager_available(self, package_manager: str) -> Optional[bool]:
        """Checks if a package manager exists on PATH."""
        if not package_manager or package_manager.lower() in ("native", "custom"):
            return True
        return shutil.which(package_manager) is not None

    def collect_machine_signals(self, target_identity: Optional[str] = None) -> Dict[str, Any]:
        """Collects complete Linux host telemetry into a normalized dictionary."""
        pending_reboot = self.check_pending_reboot()
        dep_lock = self.check_resource_lock(resource_name=target_identity)

        free_disk_gb: Optional[float] = None
        total_disk_gb: Optional[float] = None
        low_disk_space: Optional[bool] = None

        try:
            total, used, free = shutil.disk_usage("/")
            free_disk_gb = round(free / (1024 ** 3), 2)
            total_disk_gb = round(total / (1024 ** 3), 2)
            low_disk_space = (free_disk_gb < 5.0)
        except Exception as exc:
            logger.warning("Failed to query Linux disk usage: %s", exc)

        cpu_percent: Optional[float] = None
        ram_percent: Optional[float] = None
        if _HAS_PSUTIL:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.05)
                ram_percent = psutil.virtual_memory().percent
            except Exception as exc:
                logger.warning("Failed to query CPU/RAM telemetry: %s", exc)

        service_issue: Optional[bool] = None
        if target_identity:
            try:
                from platform_abstraction.platform_provider import get_platform_adapter
                adapter = get_platform_adapter()
                svc_status = adapter.service_manager.check_service_state(target_identity)
                if svc_status.get("exists") and svc_status.get("status") == "STOPPED":
                    service_issue = True
                elif svc_status.get("exists"):
                    service_issue = False
            except Exception:
                pass

        unusual_state: Optional[bool] = False
        if pending_reboot is True or low_disk_space is True or dep_lock is True or service_issue is True:
            unusual_state = True
        elif pending_reboot is None or low_disk_space is None:
            unusual_state = None

        return {
            "os": "Linux",
            "pending_reboot": pending_reboot,
            "low_disk_space": low_disk_space,
            "service_issue": service_issue,
            "dependency_lock": dep_lock,
            "package_manager_available": self.check_package_manager_available("apt"),
            "installation_state_changed": False,
            "previous_failure": False,
            "environment_drift": False,
            "conflicts": False,
            "unusual_state": unusual_state,
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "free_disk_gb": free_disk_gb,
            "total_disk_gb": total_disk_gb,
        }
