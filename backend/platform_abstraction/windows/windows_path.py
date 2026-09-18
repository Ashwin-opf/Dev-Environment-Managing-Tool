"""
platform_abstraction/windows/windows_path.py — Windows Path Manager.

Encapsulates all Windows registry PATH reading, modification, deduplication,
elevation handling, and safe PowerShell repair script generation.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Set, Tuple

from platform_abstraction.base import PathManager, PathScope
from platform_abstraction.windows.windows_environment import WindowsEnvironmentProvider


class WindowsPathManager(PathManager):
    """Windows-specific PATH management via the Windows Registry (HKCU & HKLM)."""

    def __init__(self, env_provider: Optional[WindowsEnvironmentProvider] = None) -> None:
        self._env = env_provider or WindowsEnvironmentProvider()

    def normalize_path_entry(self, entry: str) -> str:
        """Normalizes a path entry for Windows comparison (case-insensitive, expanded)."""
        if not entry:
            return ""
        cleaned = self._env._clean_and_expand_dir(entry)
        return os.path.normcase(os.path.normpath(cleaned)).rstrip("\\/")

    def sync_process_path(self, target_dir: str) -> None:
        """Dynamically ensures target_dir is present in the current process's os.environ['PATH']."""
        clean_target = os.path.normpath(self._env._clean_and_expand_dir(target_dir)).rstrip("\\/")
        if not clean_target:
            return
        target_norm = self.normalize_path_entry(clean_target)
        current = [p for p in os.environ.get("PATH", "").split(";") if p.strip()]
        for p in current:
            if self.normalize_path_entry(p) == target_norm:
                return
        os.environ["PATH"] = f"{clean_target};" + os.environ.get("PATH", "")

    # Retain private alias for backward compatibility
    _sync_process_path = sync_process_path

    def get_raw_path(self, scope: PathScope | str = PathScope.MACHINE) -> str:
        """Reads raw Path string from registry for scope."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        try:
            import winreg
            if scope_str == "USER":
                hive = winreg.HKEY_CURRENT_USER
                subkey = r"Environment"
            else:
                hive = winreg.HKEY_LOCAL_MACHINE
                subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
                return str(val)
        except Exception:
            return ""

    def get_path_entries(self, scope: PathScope | str = PathScope.MACHINE) -> List[str]:
        """Returns parsed, expanded, and ordered PATH entries for scope."""
        raw = self.get_raw_path(scope)
        if not raw:
            return []
        dirs = [self._env._clean_and_expand_dir(p) for p in raw.split(";") if p.strip()]
        seen: Set[str] = set()
        result: List[str] = []
        for d in dirs:
            if not d:
                continue
            key = self.normalize_path_entry(d)
            if key not in seen:
                seen.add(key)
                result.append(d)
        return result

    def get_effective_path(self) -> List[str]:
        """Combines persistent Machine + User PATH, preserving order and deduplicating."""
        machine = self.get_path_entries(PathScope.MACHINE)
        user = self.get_path_entries(PathScope.USER)
        seen: Set[str] = set()
        result: List[str] = []
        for d in machine + user:
            key = self.normalize_path_entry(d)
            if key not in seen:
                seen.add(key)
                result.append(d)
        return result

    def get_process_path(self) -> List[str]:
        """Returns the current process's active PATH."""
        raw = os.environ.get("PATH", "")
        return [self._env._clean_and_expand_dir(p) for p in raw.split(";") if p.strip()]

    def set_exact_path(
        self,
        raw_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Sets the exact persistent PATH value in the Windows registry."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        try:
            import winreg
            if scope_str == "USER":
                hive = winreg.HKEY_CURRENT_USER
                subkey = r"Environment"
            else:
                hive = winreg.HKEY_LOCAL_MACHINE
                subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, str(raw_path))
            self._env.refresh_environment_state()
            return True, f"Updated {scope_str.capitalize()} PATH successfully"
        except PermissionError:
            return False, "REQUIRES_ADMIN"
        except Exception as e:
            return False, f"Registry error: {e}"

    def add_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
        elevate_if_needed: bool = False,
    ) -> Tuple[bool, str]:
        """
        Adds dir_path to persistent Windows PATH (User or Machine) and syncs process PATH.
        Preserves all existing entries, normalizes paths, prevents duplicates,
        and enforces elevation boundaries.
        """
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        if scope_str not in ("USER", "MACHINE"):
            scope_str = "USER" if "user" in str(scope).lower() else "MACHINE"

        target = self._env._clean_and_expand_dir(dir_path).rstrip("\\/")
        if not target:
            return False, "Empty directory path"

        target_norm = self.normalize_path_entry(target)

        # Check existing persistent PATH for the specific scope
        existing_list = self.get_path_entries(PathScope.USER if scope_str == "USER" else PathScope.MACHINE)
        for p in existing_list:
            if self.normalize_path_entry(p) == target_norm:
                self._sync_process_path(target)
                return True, f"Directory already in {scope_str.capitalize()} PATH"

        # Check if elevation is required for Machine scope
        if scope_str == "MACHINE":
            try:
                import ctypes
                is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_admin = False

            if not is_admin:
                if not elevate_if_needed:
                    return False, "REQUIRES_ADMIN"
                # If elevation requested, run via elevated worker or elevated PowerShell RunAs
                safe_ps_script = (
                    f"$target = '{target}'; "
                    f"$curr = [Environment]::GetEnvironmentVariable('Path', 'Machine'); "
                    f"$entries = $curr -split ';' | Where-Object {{ $_.Trim().Length -gt 0 }}; "
                    f"if ($entries -notcontains $target) {{ "
                    f"[Environment]::SetEnvironmentVariable('Path', ($entries + $target) -join ';', 'Machine') }}"
                )
                elevated_cmd = (
                    f"powershell -NoProfile -ExecutionPolicy Bypass -Command "
                    f"\"$p = Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', '{safe_ps_script}' "
                    f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode\""
                )
                res = subprocess.run(elevated_cmd, capture_output=True, text=True, shell=True)
                if res.returncode == 0:
                    self._env.refresh_environment_state()
                    self._sync_process_path(target)
                    return True, f"Successfully elevated and added '{target}' to Machine PATH"
                return False, f"Elevation cancelled or failed with exit code {res.returncode}"

        # Write directly to registry for User scope or when running as Admin for Machine scope
        try:
            import winreg
            if scope_str == "USER":
                hive = winreg.HKEY_CURRENT_USER
                subkey = r"Environment"
            else:
                hive = winreg.HKEY_LOCAL_MACHINE
                subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
                    current, val_type = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    current, val_type = "", winreg.REG_EXPAND_SZ

                current_entries = [p for p in current.split(";") if p.strip()]
                for p in current_entries:
                    if self.normalize_path_entry(p) == target_norm:
                        self._sync_process_path(target)
                        return True, f"Directory already in {scope_str.capitalize()} PATH"

                new_val = (";".join(current_entries) + f";{target}").strip(";")
                winreg.SetValueEx(key, "Path", 0, val_type, new_val)

            self._env.refresh_environment_state()
            self._sync_process_path(target)
            return True, f"Added '{target}' to {scope_str.capitalize()} PATH successfully"
        except PermissionError:
            return False, "REQUIRES_ADMIN"
        except Exception as e:
            return False, f"Registry error: {e}"

    def remove_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Removes a directory entry from the specified Windows registry PATH scope."""
        scope_str = scope.value if isinstance(scope, PathScope) else str(scope).upper()
        target = self._env._clean_and_expand_dir(dir_path).rstrip("\\/")
        if not target:
            return False, "Empty directory path"
        target_norm = self.normalize_path_entry(target)

        try:
            import winreg
            if scope_str == "USER":
                hive = winreg.HKEY_CURRENT_USER
                subkey = r"Environment"
            else:
                hive = winreg.HKEY_LOCAL_MACHINE
                subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
                    current, val_type = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    return True, "Path variable empty; entry not present"

                current_entries = [p for p in current.split(";") if p.strip()]
                filtered = [p for p in current_entries if self.normalize_path_entry(p) != target_norm]

                if len(filtered) == len(current_entries):
                    return True, f"Entry '{target}' was not present in {scope_str.capitalize()} PATH"

                new_val = ";".join(filtered)
                winreg.SetValueEx(key, "Path", 0, val_type, new_val)

            self._env.refresh_environment_state()
            return True, f"Removed '{target}' from {scope_str.capitalize()} PATH successfully"
        except PermissionError:
            return False, "REQUIRES_ADMIN"
        except Exception as e:
            return False, f"Registry error: {e}"

    def generate_repair_command(
        self,
        exe_parent_dir: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[str, str, List[str]]:
        """Generates a safe PowerShell PATH repair command, executable, and arguments for Windows."""
        raw_scope = getattr(scope, "value", str(scope))
        scope_str = str(raw_scope).upper()
        scope_cap = "User" if "USER" in scope_str else "Machine"

        fix_script = (
            f"$target = '{exe_parent_dir}'; "
            f"$current = [Environment]::GetEnvironmentVariable('Path', '{scope_cap}'); "
            f"$entries = $current -split ';' | Where-Object {{ $_.Trim().Length -gt 0 }}; "
            f"if ($entries -notcontains $target) {{ "
            f"[Environment]::SetEnvironmentVariable('Path', ($entries + $target) -join ';', '{scope_cap}') }}"
        )
        fix_cmd = f'powershell -NoProfile -Command "{fix_script}"'
        return fix_cmd, "powershell", ["-NoProfile", "-Command", fix_script]

    def parse_path_entries(self, raw_path_str: str) -> List[str]:
        """Safely parses a semicolon-delimited PATH string preserving entry order and removing duplicates."""
        if not raw_path_str:
            return []
        entries: List[str] = []
        seen: Set[str] = set()
        for p in raw_path_str.split(";"):
            clean = p.strip().strip('"').strip("'")
            if not clean:
                continue
            norm = self.normalize_path_entry(clean)
            if norm and norm not in seen:
                seen.add(norm)
                entries.append(clean)
        return entries

    def is_dir_in_persistent_path(self, dir_path: str) -> bool:
        """Determines if dir_path is present in persistent Machine or User PATH."""
        target = self._env._clean_and_expand_dir(dir_path)
        if not target:
            return False
        target_norm = self.normalize_path_entry(target)
        persistent = self.get_effective_path()
        return any(self.normalize_path_entry(p) == target_norm for p in persistent)

    def is_dir_in_process_path(self, dir_path: str) -> bool:
        """Determines if dir_path is present in current process PATH."""
        target = self._env._clean_and_expand_dir(dir_path)
        if not target:
            return False
        target_norm = self.normalize_path_entry(target)
        proc = self.get_process_path()
        return any(self.normalize_path_entry(p) == target_norm for p in proc)
