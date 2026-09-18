"""
platform_abstraction/windows/windows_verification.py — Windows Verification Provider.

Implements Windows binary resolution, Windows executable extension detection (.exe, .cmd, .bat),
version parsing, and functional sanity probing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from platform_abstraction.base import VerificationProvider
from platform_abstraction.windows.windows_service import WindowsServiceManager


class WindowsVerificationProvider(VerificationProvider):
    """Windows-specific binary resolution and verification."""

    def __init__(self, service_manager: Optional[WindowsServiceManager] = None) -> None:
        self._service_manager = service_manager or WindowsServiceManager()

    def resolve_binary_path(
        self,
        executable: str,
        known_paths: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Resolves full executable path on Windows."""
        if not executable:
            return None

        # 1. PATH lookup with shutil.which
        found = shutil.which(executable)
        if found:
            return os.path.normpath(found)

        # Try with common Windows extensions
        base, ext = os.path.splitext(executable)
        if not ext:
            for e in (".exe", ".cmd", ".bat"):
                cand = shutil.which(f"{executable}{e}")
                if cand:
                    return os.path.normpath(cand)

        # 2. Known paths check
        if known_paths:
            for p in known_paths:
                expanded = os.path.expandvars(os.path.expanduser(p))
                if os.path.isfile(expanded):
                    return os.path.normpath(expanded)

        return None

    def probe_version(
        self,
        executable: str,
        version_command: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str], str]:
        """Runs the version command and extracts semantic version output."""
        cmd = list(version_command) if version_command else [executable, "--version"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                shell=False,
            )
            combined = (proc.stdout + "\n" + proc.stderr).strip()

            # Extract semantic version token
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
        """Executes a functional sanity probe."""
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
