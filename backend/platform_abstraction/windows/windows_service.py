"""
platform_abstraction/windows/windows_service.py — Windows Service Manager.

Encapsulates Windows service inspection, querying, and lifecycle control
using PowerShell Get-Service / Start-Service / Stop-Service behind a stable interface.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Tuple

from platform_abstraction.base import ServiceManager, ServiceStatus


class WindowsServiceManager(ServiceManager):
    """Windows-specific service management."""

    def detect(self, service_name: str) -> bool:
        """Returns True if the Windows service exists."""
        if not service_name:
            return False
        st = self.status(service_name)
        return bool(st.get("exists", False))

    def status(self, service_name: str) -> Dict[str, Any]:
        """Queries live service status via PowerShell Get-Service."""
        if not service_name:
            return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": ""}

        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue | Select-Object -Property Name, Status, StartType | ConvertTo-Json",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                if isinstance(data, list) and data:
                    data = data[0]

                st_val = data.get("Status")
                if st_val in (4, "Running"):
                    status_str = ServiceStatus.RUNNING.value
                elif st_val in (1, "Stopped"):
                    status_str = ServiceStatus.STOPPED.value
                else:
                    status_str = str(st_val)

                return {
                    "exists": True,
                    "status": status_str,
                    "start_type": str(data.get("StartType", "")),
                    "name": data.get("Name", service_name),
                }
        except Exception:
            pass

        return {"exists": False, "status": ServiceStatus.NOT_FOUND.value, "name": service_name}

    def start(self, service_name: str) -> Tuple[bool, str]:
        """Starts a Windows service using Start-Service."""
        if not service_name:
            return False, "No service name provided"
        try:
            cmd = ["powershell", "-NoProfile", "-Command", f"Start-Service -Name '{service_name}' -ErrorAction Stop"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                return True, f"Service '{service_name}' started successfully"
            return False, proc.stderr.strip() or f"Failed to start '{service_name}'"
        except subprocess.TimeoutExpired:
            return False, f"Starting service '{service_name}' timed out"
        except Exception as e:
            return False, str(e)

    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stops a Windows service using Stop-Service."""
        if not service_name:
            return False, "No service name provided"
        try:
            cmd = ["powershell", "-NoProfile", "-Command", f"Stop-Service -Name '{service_name}' -Force -ErrorAction Stop"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                return True, f"Service '{service_name}' stopped successfully"
            return False, proc.stderr.strip() or f"Failed to stop '{service_name}'"
        except subprocess.TimeoutExpired:
            return False, f"Stopping service '{service_name}' timed out"
        except Exception as e:
            return False, str(e)

    def restart(self, service_name: str) -> Tuple[bool, str]:
        """Restarts a Windows service using Restart-Service."""
        if not service_name:
            return False, "No service name provided"
        try:
            cmd = ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{service_name}' -Force -ErrorAction Stop"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return True, f"Service '{service_name}' restarted successfully"
            return False, proc.stderr.strip() or f"Failed to restart '{service_name}'"
        except subprocess.TimeoutExpired:
            return False, f"Restarting service '{service_name}' timed out"
        except Exception as e:
            return False, str(e)

    def verify(self, service_name: str, expected_status: ServiceStatus | str) -> bool:
        """Verifies if the service matches expected_status."""
        exp = expected_status.value if isinstance(expected_status, ServiceStatus) else str(expected_status)
        st = self.status(service_name)
        return st.get("status", "").lower() == exp.lower()

    def generate_service_command(self, service_name: str, action: str = "start") -> Tuple[str, str, List[str]]:
        """Generates PowerShell service command for Windows."""
        verb = "Start-Service" if action.lower() == "start" else "Stop-Service" if action.lower() == "stop" else "Restart-Service"
        ps_cmd = f"{verb} -Name '{service_name}'"
        full_str = f'powershell -NoProfile -Command "{ps_cmd}"'
        return full_str, "powershell", ["-NoProfile", "-Command", ps_cmd]
