"""
platform_abstraction/linux/linux_environment.py — Linux Environment Provider.

Implements POSIX/Linux environment inspection, /etc/environment reading,
XDG base directory resolution, and standard Linux install root inspection.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional

from platform_abstraction.base import EnvironmentProvider


class LinuxEnvironmentProvider(EnvironmentProvider):
    """Linux-specific environment provider utilizing /etc/environment and user shell files."""

    @staticmethod
    def _clean_and_expand_dir(raw_dir: str) -> str:
        if not raw_dir:
            return ""
        expanded = os.path.expandvars(os.path.expanduser(raw_dir.strip().strip('"').strip("'")))
        return os.path.normpath(expanded)

    def get_user_environment(self) -> Dict[str, str]:
        """Reads persistent user environment from user config files where available."""
        env: Dict[str, str] = {}
        # Parse ~/.pam_environment or standard user environment export if present
        pam_env = os.path.expanduser("~/.pam_environment")
        if os.path.isfile(pam_env):
            try:
                with open(pam_env, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass
        return env

    def get_machine_environment(self) -> Dict[str, str]:
        """Reads machine-level environment variables from /etc/environment."""
        env: Dict[str, str] = {}
        etc_env = "/etc/environment"
        if os.path.isfile(etc_env):
            try:
                with open(etc_env, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass
        return env

    def get_effective_environment(self) -> Dict[str, str]:
        """Returns the current process's environment as effective."""
        merged = dict(self.get_machine_environment())
        merged.update(self.get_user_environment())
        merged.update(dict(os.environ))
        return merged

    def refresh_effective_environment(self) -> Dict[str, str]:
        """Refreshes and returns the effective environment on Linux."""
        self.refresh_environment_state()
        return self.get_effective_environment()

    def resolve_executable(self, name: str) -> Optional[str]:
        """Resolves full executable path on Linux using standard PATH resolution."""
        if not name:
            return None
        found = shutil.which(name)
        return os.path.normpath(found) if found else None

    def get_standard_search_roots(self) -> List[str]:
        """Returns standard Linux binary directories."""
        return [
            "/usr/bin",
            "/usr/local/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            os.path.expanduser("~/.local/bin"),
            "/snap/bin",
            "/var/lib/flatpak/exports/bin",
            os.path.expanduser("~/.local/share/flatpak/exports/bin"),
            "/opt",
        ]

    def find_standard_install_dirs(self, identity: Any) -> List[str]:
        """Finds candidate install paths for a tool on Linux."""
        candidates: List[str] = []
        exec_name = getattr(identity, "executable", None) or getattr(identity, "executable_name", str(identity))

        # Check which
        found = shutil.which(exec_name)
        if found and os.path.isfile(found):
            candidates.append(os.path.normpath(found))

        # Check configured installation paths
        configured_paths = getattr(identity, "installation_paths", [])
        for p in configured_paths:
            expanded = self._clean_and_expand_dir(p)
            if os.path.isfile(expanded) and expanded not in candidates:
                candidates.append(os.path.normpath(expanded))

        # Check standard roots
        for root in self.get_standard_search_roots():
            target = os.path.join(root, exec_name)
            if os.path.isfile(target) and target not in candidates:
                candidates.append(os.path.normpath(target))

        return candidates

    def refresh_environment_state(self) -> None:
        """On Linux, environment changes take effect in new shells."""
        pass
