"""
platform_abstraction/macos/macos_service.py — macOS Service Manager.

Encapsulates macOS launchd / Homebrew services management.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Tuple

from platform_abstraction.base import ServiceManager, ServiceStatus


class MacOSServiceManager(ServiceManager):
    """macOS-specific service management using launchctl and brew services."""

    def detect(self, service_name: str) -> bool:
        """Checks if a service is registered in launchd or brew services."""
        if not service_name:
            return False
        try:
            proc = subprocess.run(
                ["launchctl", "list", service_name],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def status(self, service_name: str) -> Dict[str, Any]:
        """Queries status of a macOS service."""
        if not service_name:
            return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": ""}

        try:
            proc = subprocess.run(
                ["launchctl", "list", service_name],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if proc.returncode == 0:
                # PID is reported if running
                lines = proc.stdout.strip().splitlines()
                is_running = any('"PID"' in l for l in lines)
                status_str = ServiceStatus.RUNNING.value if is_running else ServiceStatus.STOPPED.value
                return {
                    "exists": True,
                    "status": status_str,
                    "name": service_name,
                }
        except Exception:
            pass

        return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": service_name}

    def start(self, service_name: str) -> Tuple[bool, str]:
        """Starts a service on macOS via launchctl or brew services."""
        try:
            # Try launchctl start
            proc = subprocess.run(
                ["launchctl", "start", service_name],
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
        """Stops a service on macOS via launchctl."""
        try:
            proc = subprocess.run(
                ["launchctl", "stop", service_name],
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
        """Restarts a service on macOS."""
        self.stop(service_name)
        return self.start(service_name)

    def verify(self, service_name: str, expected_status: ServiceStatus | str) -> bool:
        """Verifies service status."""
        exp = expected_status.value if isinstance(expected_status, ServiceStatus) else str(expected_status)
        st = self.status(service_name)
        return st.get("status", "").lower() == exp.lower()

    def generate_service_command(self, service_name: str, action: str = "start") -> Tuple[str, str, List[str]]:
        """Generates launchctl/brew service command for macOS."""
        sub = "start" if action.lower() == "start" else "stop"
        cmd_str = f"launchctl {sub} {service_name}"
        return cmd_str, "launchctl", [sub, service_name]
