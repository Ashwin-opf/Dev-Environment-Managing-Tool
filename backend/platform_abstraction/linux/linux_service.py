"""
platform_abstraction/linux/linux_service.py — Linux Service Manager.

Encapsulates Linux systemd / service management behind the ServiceManager interface.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Tuple

from platform_abstraction.base import ServiceManager, ServiceStatus


class LinuxServiceManager(ServiceManager):
    """Linux-specific service management using systemctl."""

    def detect(self, service_name: str) -> bool:
        """Checks if a systemd unit exists."""
        if not service_name:
            return False
        try:
            proc = subprocess.run(
                ["systemctl", "status", service_name],
                capture_output=True,
                text=True,
                timeout=3,
            )
            # 4 indicates unit not found in systemd
            return proc.returncode != 4
        except Exception:
            return False

    def status(self, service_name: str) -> Dict[str, Any]:
        """Queries live service status using systemctl is-active."""
        if not service_name:
            return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": ""}

        try:
            proc = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=4,
            )
            raw = proc.stdout.strip()
            if proc.returncode == 0 and raw == "active":
                status_str = ServiceStatus.RUNNING.value
            elif raw in ("inactive", "failed"):
                status_str = ServiceStatus.STOPPED.value
            else:
                # Check if unit exists
                exists = self.detect(service_name)
                status_str = ServiceStatus.STOPPED.value if exists else ServiceStatus.NOT_FOUND.value

            return {
                "exists": status_str != ServiceStatus.NOT_FOUND.value,
                "status": status_str,
                "name": service_name,
            }
        except Exception:
            return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": service_name}

    def start(self, service_name: str) -> Tuple[bool, str]:
        """Starts a systemd service."""
        try:
            proc = subprocess.run(
                ["systemctl", "start", service_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return True, f"Service '{service_name}' started successfully"
            return False, proc.stderr.strip() or f"Failed to start '{service_name}'"
        except Exception as e:
            return False, str(e)

    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stops a systemd service."""
        try:
            proc = subprocess.run(
                ["systemctl", "stop", service_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return True, f"Service '{service_name}' stopped successfully"
            return False, proc.stderr.strip() or f"Failed to stop '{service_name}'"
        except Exception as e:
            return False, str(e)

    def restart(self, service_name: str) -> Tuple[bool, str]:
        """Restarts a systemd service."""
        try:
            proc = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode == 0:
                return True, f"Service '{service_name}' restarted successfully"
            return False, proc.stderr.strip() or f"Failed to restart '{service_name}'"
        except Exception as e:
            return False, str(e)

    def verify(self, service_name: str, expected_status: ServiceStatus | str) -> bool:
        """Verifies if the service matches expected_status."""
        exp = expected_status.value if isinstance(expected_status, ServiceStatus) else str(expected_status)
        st = self.status(service_name)
        return st.get("status", "").lower() == exp.lower()

    def generate_service_command(self, service_name: str, action: str = "start") -> Tuple[str, str, List[str]]:
        """Generates systemctl service command for Linux."""
        act = action.lower()
        cmd_str = f"systemctl {act} {service_name}"
        return cmd_str, "systemctl", [act, service_name]
