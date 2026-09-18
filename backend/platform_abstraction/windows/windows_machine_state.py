"""
windows_machine_state.py — Windows Host Machine State Assessment.

Queries Windows host subsystem for machine-state signals:
- Pending reboot detection via Component Based Servicing (CBS), WindowsUpdate, and PendingFileRenameOperations.
- Installer and resource concurrency locks (Windows Installer InProgress, resource_lock_mgr).
- Package manager availability (winget, choco).
- CPU/RAM metrics and drive utilization.
- Service status and executable conflicts.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from typing import Any, Dict, Optional

from platform_abstraction.base import MachineStateProvider

logger = logging.getLogger("pc_doctor.platform.windows.machine_state")

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class WindowsMachineStateProvider(MachineStateProvider):
    """Windows-specific machine state provider querying registry and host telemetry."""

    def check_pending_reboot(self) -> Optional[bool]:
        """
        Checks if Windows requires a system restart.
        Inspects:
        1. HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending
        2. HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired
        3. HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager -> PendingFileRenameOperations
        """
        if not _HAS_WINREG or platform.system() != "Windows":
            return None

        try:
            # 1. Component Based Servicing RebootPending
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                    0,
                    winreg.KEY_READ,
                ):
                    return True
            except FileNotFoundError:
                pass

            # 2. Windows Update RebootRequired
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                    0,
                    winreg.KEY_READ,
                ):
                    return True
            except FileNotFoundError:
                pass

            # 3. Session Manager PendingFileRenameOperations
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager",
                    0,
                    winreg.KEY_READ,
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "PendingFileRenameOperations")
                    if val:
                        return True
            except FileNotFoundError:
                pass

            return False
        except Exception as exc:
            logger.warning("Failed to query Windows pending reboot state: %s", exc)
            return None

    def check_resource_lock(self, resource_name: Optional[str] = None) -> Optional[bool]:
        """
        Checks if Windows Installer is busy or fine-grained resource locks exist.
        """
        # Check fine-grained lock manager if available
        try:
            from plan_freeze import resource_lock_mgr
            if resource_name and resource_lock_mgr.is_locked(resource_name):
                return True
        except Exception:
            pass

        if not _HAS_WINREG or platform.system() != "Windows":
            return None

        try:
            # Windows Installer InProgress key
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\InProgress",
                    0,
                    winreg.KEY_READ,
                ):
                    return True
            except FileNotFoundError:
                return False
        except Exception as exc:
            logger.warning("Failed to query Windows installer lock state: %s", exc)
            return None

    def check_package_manager_available(self, package_manager: str) -> Optional[bool]:
        """Checks if a Windows package manager (winget, choco, etc.) exists on PATH."""
        if not package_manager or package_manager.lower() in ("native", "custom"):
            return True
        binary = shutil.which(package_manager)
        return binary is not None

    def collect_machine_signals(self, target_identity: Optional[str] = None) -> Dict[str, Any]:
        """Collects complete Windows host telemetry into a normalized dictionary."""
        # 1. Reboot state
        pending_reboot = self.check_pending_reboot()

        # 2. Resource & package manager locks
        dep_lock = self.check_resource_lock(resource_name=target_identity)
        winget_avail = self.check_package_manager_available("winget")

        # 3. Disk telemetry
        free_disk_gb: Optional[float] = None
        total_disk_gb: Optional[float] = None
        low_disk_space: Optional[bool] = None

        try:
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            total, used, free = shutil.disk_usage(drive)
            free_disk_gb = round(free / (1024 ** 3), 2)
            total_disk_gb = round(total / (1024 ** 3), 2)
            low_disk_space = (free_disk_gb < 5.0)
        except Exception as exc:
            logger.warning("Failed to query Windows disk usage: %s", exc)

        # 4. CPU & RAM telemetry
        cpu_percent: Optional[float] = None
        ram_percent: Optional[float] = None
        if _HAS_PSUTIL:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.05)
                ram_percent = psutil.virtual_memory().percent
            except Exception as exc:
                logger.warning("Failed to query CPU/RAM telemetry: %s", exc)

        # 5. Service state for target if applicable
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

        # 6. Conflicts & unusual state
        conflicts: Optional[bool] = False
        unusual_state: Optional[bool] = False

        if pending_reboot is True or low_disk_space is True or dep_lock is True or service_issue is True:
            unusual_state = True
        elif pending_reboot is None or low_disk_space is None:
            # If critical state could not be determined, unusual_state is UNKNOWN
            unusual_state = None

        return {
            "os": "Windows",
            "pending_reboot": pending_reboot,
            "low_disk_space": low_disk_space,
            "service_issue": service_issue,
            "dependency_lock": dep_lock,
            "package_manager_available": winget_avail,
            "installation_state_changed": False,
            "previous_failure": False,
            "environment_drift": False,
            "conflicts": conflicts,
            "unusual_state": unusual_state,
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "free_disk_gb": free_disk_gb,
            "total_disk_gb": total_disk_gb,
        }
