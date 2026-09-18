"""
platform_abstraction/macos/macos_path.py — macOS Path Manager.

Encapsulates macOS PATH reading, /etc/paths and /etc/paths.d/ management,
and user zsh profile configuration on macOS.
"""

from __future__ import annotations

import glob
import os
import posixpath
import re
from typing import List, Optional, Set, Tuple

from platform_abstraction.base import PathManager, PathScope
from platform_abstraction.macos.macos_environment import MacOSEnvironmentProvider


class MacOSPathManager(PathManager):
    """macOS-specific PATH management using POSIX colon delimiters and /etc/paths.d."""

    def __init__(self, env_provider: Optional[MacOSEnvironmentProvider] = None) -> None:
        self._env = env_provider or MacOSEnvironmentProvider()

    def normalize_path_entry(self, entry: str) -> str:
        """Normalizes a POSIX path entry on macOS."""
        if not entry:
            return ""
        cleaned = self._env._clean_and_expand_dir(entry).replace("\\", "/")
        return posixpath.normpath(cleaned).rstrip("/")

    def sync_process_path(self, target_dir: str) -> None:
        """Adds target_dir to current process's os.environ['PATH'] if not present."""
        clean_target = self.normalize_path_entry(target_dir)
        if not clean_target:
            return
        current = [p for p in os.environ.get("PATH", "").split(":") if p.strip()]
        for p in current:
            if self.normalize_path_entry(p) == clean_target:
                return
        os.environ["PATH"] = f"{clean_target}:" + os.environ.get("PATH", "")

    # Retain private alias for backward compatibility
    _sync_process_path = sync_process_path

    def get_raw_path(self, scope: PathScope | str = PathScope.MACHINE) -> str:
        """Reads system PATH from /etc/paths and /etc/paths.d/* or os.environ."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        if scope_str == "MACHINE":
            paths: List[str] = []
            if os.path.isfile("/etc/paths"):
                try:
                    with open("/etc/paths", "r", encoding="utf-8", errors="ignore") as f:
                        paths.extend([line.strip() for line in f if line.strip()])
                except Exception:
                    pass
            if os.path.isdir("/etc/paths.d"):
                for p_file in glob.glob("/etc/paths.d/*"):
                    try:
                        with open(p_file, "r", encoding="utf-8", errors="ignore") as f:
                            paths.extend([line.strip() for line in f if line.strip()])
                    except Exception:
                        pass
            if paths:
                return ":".join(paths)
        return os.environ.get("PATH", "")

    def get_path_entries(self, scope: PathScope | str = PathScope.MACHINE) -> List[str]:
        """Returns parsed and deduplicated list of PATH entries for scope."""
        raw = self.get_raw_path(scope)
        if not raw:
            return []
        dirs = [self._env._clean_and_expand_dir(p) for p in raw.split(":") if p.strip()]
        seen: Set[str] = set()
        result: List[str] = []
        for d in dirs:
            key = self.normalize_path_entry(d)
            if key and key not in seen:
                seen.add(key)
                result.append(d)
        return result

    def get_effective_path(self) -> List[str]:
        """Returns effective PATH entries on macOS."""
        raw = os.environ.get("PATH", "")
        dirs = [self._env._clean_and_expand_dir(p) for p in raw.split(":") if p.strip()]
        seen: Set[str] = set()
        result: List[str] = []
        for d in dirs:
            key = self.normalize_path_entry(d)
            if key and key not in seen:
                seen.add(key)
                result.append(d)
        return result

    def get_process_path(self) -> List[str]:
        """Returns active PATH of the running process."""
        raw = os.environ.get("PATH", "")
        return [self._env._clean_and_expand_dir(p) for p in raw.split(":") if p.strip()]

    def set_exact_path(
        self,
        raw_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Sets exact PATH value on macOS. Machine scope updates /etc/paths.d/pcdoc."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        if scope_str == "MACHINE":
            is_root = os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0
            if not is_root:
                return False, "REQUIRES_ADMIN"
            try:
                os.makedirs("/etc/paths.d", exist_ok=True)
                with open("/etc/paths.d/pcdoc", "w", encoding="utf-8") as f:
                    for entry in raw_path.split(":"):
                        if entry.strip():
                            f.write(f"{entry.strip()}\n")
                return True, "Updated /etc/paths.d/pcdoc"
            except Exception as e:
                return False, f"Failed to set machine PATH on macOS: {e}"
        else:
            os.environ["PATH"] = str(raw_path)
            return True, "Updated process PATH"

    def add_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
        elevate_if_needed: bool = False,
    ) -> Tuple[bool, str]:
        """Adds a directory entry to PATH on macOS."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        target = self._env._clean_and_expand_dir(dir_path).rstrip("/")
        if not target:
            return False, "Empty directory path"

        target_norm = self.normalize_path_entry(target)

        # Check existing
        existing = self.get_path_entries(scope)
        for p in existing:
            if self.normalize_path_entry(p) == target_norm:
                self._sync_process_path(target)
                return True, f"Directory already in {scope_str.capitalize()} PATH"

        if scope_str == "MACHINE":
            is_root = os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0
            if not is_root:
                return False, "REQUIRES_ADMIN"
            try:
                os.makedirs("/etc/paths.d", exist_ok=True)
                with open("/etc/paths.d/pcdoc", "a", encoding="utf-8") as f:
                    f.write(f"{target}\n")
                self._sync_process_path(target)
                return True, f"Added '{target}' to /etc/paths.d/pcdoc"
            except Exception as e:
                return False, f"Error writing to /etc/paths.d: {e}"
        else:
            # User scope: update ~/.zprofile or ~/.zshrc
            zprofile = os.path.expanduser("~/.zprofile")
            try:
                with open(zprofile, "a", encoding="utf-8") as f:
                    f.write(f'\nexport PATH="$PATH:{target}"\n')
                self._sync_process_path(target)
                return True, f"Added '{target}' to ~/.zprofile"
            except Exception as e:
                return False, f"Error updating ~/.zprofile: {e}"

    def remove_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Removes a directory entry from active PATH on macOS."""
        target = self._env._clean_and_expand_dir(dir_path).rstrip("/")
        target_norm = self.normalize_path_entry(target)
        current = [p for p in os.environ.get("PATH", "").split(":") if p.strip()]
        filtered = [p for p in current if self.normalize_path_entry(p) != target_norm]
        os.environ["PATH"] = ":".join(filtered)
        return True, f"Removed '{target}' from active macOS PATH"

    def generate_repair_command(
        self,
        exe_parent_dir: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[str, str, List[str]]:
        """Generates macOS zsh export PATH command string, executable, and arguments."""
        cmd = f'export PATH="$PATH:{exe_parent_dir}"'
        return cmd, "zsh", ["-c", cmd]

    def parse_path_entries(self, raw_path_str: str) -> List[str]:
        """Safely parses a colon-delimited PATH string preserving entry order and removing duplicates."""
        if not raw_path_str:
            return []
        entries: List[str] = []
        seen: Set[str] = set()
        for p in raw_path_str.split(":"):
            clean = p.strip().strip('"').strip("'")
            if not clean:
                continue
            norm = self.normalize_path_entry(clean)
            if norm and norm not in seen:
                seen.add(norm)
                entries.append(clean)
        return entries

    def is_dir_in_persistent_path(self, dir_path: str) -> bool:
        """Determines if dir_path is in the persistent macOS PATH."""
        target = self._env._clean_and_expand_dir(dir_path)
        if not target:
            return False
        norm = self.normalize_path_entry(target)
        persistent = self.get_effective_path()
        return any(self.normalize_path_entry(p) == norm for p in persistent)

    def is_dir_in_process_path(self, dir_path: str) -> bool:
        """Determines if dir_path is in the current process PATH."""
        target = self._env._clean_and_expand_dir(dir_path)
        if not target:
            return False
        norm = self.normalize_path_entry(target)
        proc = self.get_process_path()
        return any(self.normalize_path_entry(p) == norm for p in proc)
