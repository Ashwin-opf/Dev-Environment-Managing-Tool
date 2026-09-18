"""
platform_abstraction/macos/macos_environment.py — macOS Environment Provider.

Implements macOS-specific environment inspection, /etc/paths.d/ parsing,
Homebrew root inspection (/opt/homebrew), and /Applications bundle resolution.
"""

from __future__ import annotations

import glob
import os
import shutil
from typing import Any, Dict, List, Optional

from platform_abstraction.base import EnvironmentProvider


class MacOSEnvironmentProvider(EnvironmentProvider):
    """macOS-specific environment provider."""

    @staticmethod
    def _clean_and_expand_dir(raw_dir: str) -> str:
        if not raw_dir:
            return ""
        expanded = os.path.expandvars(os.path.expanduser(raw_dir.strip().strip('"').strip("'")))
        return os.path.normpath(expanded)

    def get_user_environment(self) -> Dict[str, str]:
        """Returns user environment on macOS."""
        return dict(os.environ)

    def get_machine_environment(self) -> Dict[str, str]:
        """Reads system-level environment from /etc/environment if present."""
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
        """Returns the merged environment for the current process."""
        return dict(os.environ)

    def refresh_effective_environment(self) -> Dict[str, str]:
        """Refreshes and returns the effective environment on macOS."""
        self.refresh_environment_state()
        return self.get_effective_environment()

    def resolve_executable(self, name: str) -> Optional[str]:
        """Resolves executable on macOS (Homebrew, /usr/local/bin, /usr/bin)."""
        if not name:
            return None
        found = shutil.which(name)
        return os.path.normpath(found) if found else None

    def get_standard_search_roots(self) -> List[str]:
        """Returns standard binary search locations on macOS."""
        return [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            os.path.expanduser("~/.local/bin"),
            "/Applications",
            os.path.expanduser("~/Applications"),
        ]

    def find_standard_install_dirs(self, identity: Any) -> List[str]:
        """Finds candidate install paths for a tool on macOS."""
        candidates: List[str] = []
        exec_name = getattr(identity, "executable", None) or getattr(identity, "executable_name", str(identity))

        # Check which
        found = shutil.which(exec_name)
        if found and os.path.isfile(found):
            candidates.append(os.path.normpath(found))

        # Check configured paths
        configured_paths = getattr(identity, "installation_paths", [])
        for p in configured_paths:
            expanded = self._clean_and_expand_dir(p)
            if os.path.isfile(expanded) and expanded not in candidates:
                candidates.append(os.path.normpath(expanded))

        # Check Homebrew and standard roots
        for root in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
            target = os.path.join(root, exec_name)
            if os.path.isfile(target) and target not in candidates:
                candidates.append(os.path.normpath(target))

        # Check macOS .app bundles
        display = getattr(identity, "display_name", "")
        if display:
            app_pattern = f"/Applications/{display}.app/Contents/MacOS/{exec_name}"
            matches = glob.glob(app_pattern)
            for m in matches:
                if os.path.isfile(m) and m not in candidates:
                    candidates.append(os.path.normpath(m))

        return candidates

    def refresh_environment_state(self) -> None:
        """Environment refresh on macOS."""
        pass
