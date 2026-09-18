"""
state_refresh.py — Authoritative Post-Mutation Machine State Refresh for PC Doctor.

Enforces:
- After any INSTALL, UPDATE, UNINSTALL, REINSTALL, REPAIR mutation:
  Performs real-world machine state detection rather than mutating in-memory or frontend fake state.
- Refreshes:
  - Installed tool binaries & PATH resolutions.
  - Installed version strings.
  - Package manager installed lists.
  - System health / disk / memory indicators.
"""

from __future__ import annotations

import os
import platform
import shutil
from typing import Any, Dict, List, Optional

from canonical_identity import canonical_store, CanonicalIdentity
from machine_state import MachineState
from platform_abstraction.platform_provider import get_platform_adapter


class StateRefresher:
    """Refreshes real-world machine state post-mutation."""

    def refresh_tool_state(self, identity_or_name: str) -> Dict[str, Any]:
        """Probes real machine state for a specific tool identity."""
        ident = canonical_store.resolve(identity_or_name)
        exec_name = ident.executable if ident else identity_or_name

        path = shutil.which(exec_name)
        if not path and ident:
            for p in ident.installation_paths:
                if os.path.exists(p):
                    path = p
                    break

        version_str = None
        if path and ident and ident.version_command:
            import subprocess
            try:
                r = subprocess.run(
                    ident.version_command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                from verification_engine import _extract_version_string
                version_str = _extract_version_string(r.stdout + "\n" + r.stderr)
            except Exception:
                pass

        return {
            "identity_id": ident.identity_id if ident else identity_or_name,
            "installed": path is not None,
            "executable_path": path,
            "detected_version": version_str,
        }

    def refresh_machine_state(self, target_identity: Optional[str] = None) -> MachineState:
        """Performs full machine state refresh for core tools and system load."""
        tools_status = {}
        for ident in canonical_store.list_all():
            tools_status[ident.identity_id] = self.refresh_tool_state(ident.identity_id)

        signals: Dict[str, Any] = {}
        try:
            adapter = get_platform_adapter()
            signals = adapter.machine_state_provider.collect_machine_signals(target_identity=target_identity)
        except Exception:
            disk_path = os.environ.get("SystemDrive", "C:") + "\\" if platform.system() == "Windows" else "/"
            try:
                total, used, free = shutil.disk_usage(disk_path)
                free_gb = round(free / (1024 ** 3), 2)
                total_gb = round(total / (1024 ** 3), 2)
            except Exception:
                free_gb = None
                total_gb = None

            signals = {
                "os": platform.system(),
                "free_disk_gb": free_gb,
                "total_disk_gb": total_gb,
                "low_disk_space": (free_gb < 5.0) if free_gb is not None else None,
                "pending_reboot": None,
                "dependency_lock": None,
                "service_issue": None,
                "conflicts": False,
                "unusual_state": None,
            }

        signals["tools"] = tools_status
        return MachineState.from_dict(signals)


state_refresher = StateRefresher()

