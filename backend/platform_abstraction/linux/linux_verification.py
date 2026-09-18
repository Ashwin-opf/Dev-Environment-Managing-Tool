"""
platform_abstraction/linux/linux_verification.py — Linux Verification Provider.

Implements POSIX executable resolution, version extraction, and functional sanity checks on Linux.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from platform_abstraction.base import VerificationProvider
from platform_abstraction.linux.linux_service import LinuxServiceManager


class LinuxVerificationProvider(VerificationProvider):
    """Linux-specific binary resolution and verification."""

    def __init__(self, service_manager: Optional[LinuxServiceManager] = None) -> None:
        self._service_manager = service_manager or LinuxServiceManager()

    def resolve_binary_path(
        self,
        executable: str,
        known_paths: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Resolves binary on Linux checking executable bits."""
        if not executable:
            return None

        found = shutil.which(executable)
        if found:
            return os.path.normpath(found)

        if known_paths:
            for p in known_paths:
                expanded = os.path.expandvars(os.path.expanduser(p))
                if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                    return os.path.normpath(expanded)

        return None

    def probe_version(
        self,
        executable: str,
        version_command: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str], str]:
        """Executes version check on Linux."""
        cmd = list(version_command) if version_command else [executable, "--version"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            combined = (proc.stdout + "\n" + proc.stderr).strip()

            version_str: Optional[str] = None
            for line in combined.splitlines():
                line_clean = line.strip()
                m = re.search(r"\b(?:v)?(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?)\b", line_clean)
                if m:
                    version_str = line_clean[:100]
                    break

            ok = (proc.returncode == 0 or bool(version_str))
            return ok, version_str, combined
        except Exception as e:
            return False, None, str(e)

    def probe_functional(
        self,
        executable: str,
        test_command: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Executes functional sanity check."""
        cmd = list(test_command) if test_command else [executable, "--help"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
            )
            ok = (proc.returncode == 0)
            msg = proc.stdout if ok else (proc.stderr or f"Exit code {proc.returncode}")
            return ok, msg.strip()[:200]
        except Exception as e:
            return False, str(e)

    def check_service_state(self, service_name: str) -> Dict[str, Any]:
        """Checks the state of an associated service."""
        return self._service_manager.status(service_name)
