"""
platform_abstraction/linux/linux_path.py — Linux Path Manager.

Encapsulates POSIX colon-delimited PATH operations, shell profile management (~/.profile, ~/.bashrc),
and /etc/profile.d/ system PATH management on Linux.
"""

from __future__ import annotations

import os
import posixpath
import re
from typing import List, Optional, Set, Tuple

from platform_abstraction.base import PathManager, PathScope
from platform_abstraction.linux.linux_environment import LinuxEnvironmentProvider


class LinuxPathManager(PathManager):
    """Linux-specific PATH management using POSIX colon delimiters and shell config files."""

    def __init__(self, env_provider: Optional[LinuxEnvironmentProvider] = None) -> None:
        self._env = env_provider or LinuxEnvironmentProvider()

    def normalize_path_entry(self, entry: str) -> str:
        """Normalizes a POSIX path entry (case-sensitive, expands ~ and vars)."""
        if not entry:
            return ""
        cleaned = self._env._clean_and_expand_dir(entry).replace("\\", "/")
        return posixpath.normpath(cleaned).rstrip("/")

    def sync_process_path(self, target_dir: str) -> None:
        """Adds target_dir to the current process's os.environ['PATH'] if not present."""
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
        """Returns raw PATH string from /etc/environment (Machine) or os.environ (User/Effective)."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        if scope_str == "MACHINE":
            etc_env = "/etc/environment"
            if os.path.isfile(etc_env):
                try:
                    with open(etc_env, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            m = re.match(r'^\s*PATH\s*=\s*["\']?(.*?)["\']?\s*$', line)
                            if m:
                                return m.group(1)
                except Exception:
                    pass
        return os.environ.get("PATH", "")

    def get_path_entries(self, scope: PathScope | str = PathScope.MACHINE) -> List[str]:
        """Returns parsed and normalized list of PATH entries for scope."""
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
        """Returns effective PATH entries from process environment."""
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
        """Sets the exact PATH value. Machine scope requires root privileges."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        if scope_str == "MACHINE":
            is_root = os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0
            if not is_root:
                return False, "REQUIRES_ADMIN"
            try:
                # Update /etc/profile.d/pcdoc_path.sh
                profile_dir = "/etc/profile.d"
                os.makedirs(profile_dir, exist_ok=True)
                target_file = os.path.join(profile_dir, "pcdoc_path.sh")
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(f'export PATH="{raw_path}"\n')
                os.chmod(target_file, 0o644)
                return True, f"Updated {target_file} successfully"
            except Exception as e:
                return False, f"Failed to update Machine PATH on Linux: {e}"
        else:
            os.environ["PATH"] = str(raw_path)
            return True, "Updated process PATH"

    def add_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
        elevate_if_needed: bool = False,
    ) -> Tuple[bool, str]:
        """Adds a directory entry to PATH for user or system on Linux."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        target = self._env._clean_and_expand_dir(dir_path).rstrip("/")
        if not target:
            return False, "Empty directory path"

        target_norm = self.normalize_path_entry(target)

        # Check existing entries
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
                profile_dir = "/etc/profile.d"
                os.makedirs(profile_dir, exist_ok=True)
                script_path = os.path.join(profile_dir, "pcdoc_path.sh")
                mode = "a" if os.path.isfile(script_path) else "w"
                with open(script_path, mode, encoding="utf-8") as f:
                    f.write(f'export PATH="$PATH:{target}"\n')
                os.chmod(script_path, 0o644)
                self._sync_process_path(target)
                return True, f"Added '{target}' to /etc/profile.d/pcdoc_path.sh"
            except Exception as e:
                return False, f"Error writing to /etc/profile.d: {e}"
        else:
            # User scope: update user ~/.profile or ~/.bashrc
            user_profile = os.path.expanduser("~/.profile")
            try:
                with open(user_profile, "a", encoding="utf-8") as f:
                    f.write(f'\nexport PATH="$PATH:{target}"\n')
                self._sync_process_path(target)
                return True, f"Added '{target}' to ~/.profile"
            except Exception as e:
                return False, f"Error updating user profile: {e}"

    def remove_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Removes a directory entry from PATH on Linux."""
        target = self._env._clean_and_expand_dir(dir_path).rstrip("/")
        target_norm = self.normalize_path_entry(target)
        current = [p for p in os.environ.get("PATH", "").split(":") if p.strip()]
        filtered = [p for p in current if self.normalize_path_entry(p) != target_norm]
        os.environ["PATH"] = ":".join(filtered)
        return True, f"Removed '{target}' from active Linux PATH"

    def generate_repair_command(
        self,
        exe_parent_dir: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[str, str, List[str]]:
        """Generates POSIX export PATH command string, executable, and arguments."""
        cmd = f'export PATH="$PATH:{exe_parent_dir}"'
        return cmd, "sh", ["-c", cmd]

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
        """Determines if dir_path is in the persistent Linux PATH."""
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
