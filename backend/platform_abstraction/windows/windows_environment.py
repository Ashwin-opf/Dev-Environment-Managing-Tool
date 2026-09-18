"""
platform_abstraction/windows/windows_environment.py — Windows Environment Provider.

Implements Windows-specific environment retrieval, App Paths registry inspection,
standard path expansion, and WM_SETTINGCHANGE environment broadcast.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any, Dict, List, Optional

from platform_abstraction.base import EnvironmentProvider


class WindowsEnvironmentProvider(EnvironmentProvider):
    """Windows-specific environment provider utilizing the Windows Registry and standard locations."""

    ESSENTIAL_SYSTEM_VARS = (
        "SystemRoot",
        "SystemDrive",
        "windir",
        "ComSpec",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "ALLUSERSPROFILE",
        "ProgramData",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "CommonProgramFiles",
        "CommonProgramFiles(x86)",
        "LOCALAPPDATA",
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "PUBLIC",
        "PATHEXT",
    )

    @staticmethod
    def _clean_and_expand_dir(raw_dir: str) -> str:
        if not raw_dir:
            return ""
        expanded = os.path.expandvars(os.path.expanduser(raw_dir.strip().strip('"').strip("'")))
        return os.path.normpath(expanded)

    def _expand_vars_recursively(self, val: str, env_dict: Dict[str, str], max_depth: int = 5) -> str:
        """Recursively expands %VAR% tokens in a string using the provided environment mapping."""
        if not val or "%" not in val:
            return val
        pattern = re.compile(r"%([^%]+)%", re.IGNORECASE)
        current = val
        for _ in range(max_depth):
            def repl(match: re.Match) -> str:
                var_name = match.group(1).upper()
                for k, v in env_dict.items():
                    if k.upper() == var_name:
                        return v
                for k, v in os.environ.items():
                    if k.upper() == var_name:
                        return v
                return match.group(0)

            new_val = pattern.sub(repl, current)
            if new_val == current:
                break
            current = new_val
        return current

    def get_user_environment(self) -> Dict[str, str]:
        """Reads persistent User environment variables from HKCU\\Environment."""
        env: Dict[str, str] = {}
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
                num_values = winreg.QueryInfoKey(key)[1]
                for i in range(num_values):
                    name, val, _ = winreg.EnumValue(key, i)
                    env[name] = str(val)
        except Exception:
            pass
        return env

    def get_machine_environment(self) -> Dict[str, str]:
        """Reads persistent Machine environment variables from HKLM."""
        env: Dict[str, str] = {}
        try:
            import winreg
            subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_READ) as key:
                num_values = winreg.QueryInfoKey(key)[1]
                for i in range(num_values):
                    name, val, _ = winreg.EnumValue(key, i)
                    env[name] = str(val)
        except Exception:
            pass
        return env

    def get_effective_environment(self) -> Dict[str, str]:
        """
        Reconstructs the authoritative Windows effective Machine + User environment.
        - Preserves essential process-level system variables (SystemRoot, ComSpec, etc.)
        - Reads persistent Machine environment from HKLM
        - Reads persistent User environment from HKCU
        - Performs case-insensitive variable merging
        - For PATH: concatenates Machine PATH + User PATH (Machine first, User does NOT clobber)
        - Ensures PATHEXT is present
        - Recursively expands %VAR% references
        """
        env: Dict[str, str] = {}
        key_map: Dict[str, str] = {}  # uppercase name -> exact key in env

        def set_var(k: str, v: str) -> None:
            uk = k.upper()
            if uk in key_map:
                existing_k = key_map[uk]
                env[existing_k] = str(v)
            else:
                key_map[uk] = k
                env[k] = str(v)

        def get_var(k: str) -> Optional[str]:
            uk = k.upper()
            if uk in key_map:
                return env[key_map[uk]]
            return None

        # 1. Seed essential process-level system variables from os.environ
        for var_name in self.ESSENTIAL_SYSTEM_VARS:
            for cur_k, cur_v in os.environ.items():
                if cur_k.upper() == var_name.upper():
                    set_var(var_name, cur_v)
                    break

        if not get_var("PATHEXT"):
            set_var("PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC")

        # 2. Merge persistent Machine environment from HKLM
        machine_env = self.get_machine_environment()
        for k, v in machine_env.items():
            set_var(k, v)

        # 3. Merge persistent User environment from HKCU
        user_env = self.get_user_environment()
        for k, v in user_env.items():
            if k.upper() == "PATH":
                # For PATH, do NOT clobber: Machine PATH comes first, then User PATH
                machine_path = get_var("PATH") or ""
                user_path = str(v)
                parts: List[str] = []
                for p in machine_path.split(";"):
                    p_clean = p.strip().strip('"').strip("'")
                    if p_clean:
                        parts.append(p_clean)
                for p in user_path.split(";"):
                    p_clean = p.strip().strip('"').strip("'")
                    if p_clean:
                        parts.append(p_clean)
                combined_path = ";".join(parts)
                if "PATH" in key_map:
                    env[key_map["PATH"]] = combined_path
                else:
                    set_var("Path", combined_path)
            else:
                set_var(k, v)

        # 4. Fallback PATH if neither machine nor user provided one
        if not get_var("PATH"):
            set_var("Path", os.environ.get("PATH", ""))

        # 5. Recursive expansion of %VAR% references across all environment variables
        expanded_env: Dict[str, str] = {}
        for k, v in env.items():
            expanded_env[k] = self._expand_vars_recursively(v, env)

        return expanded_env

    def refresh_effective_environment(self) -> Dict[str, str]:
        """
        Refreshes the effective environment by re-querying the OS/registry
        and broadcasting WM_SETTINGCHANGE if appropriate.
        """
        self.refresh_environment_state()
        return self.get_effective_environment()

    def resolve_executable(self, name: str) -> Optional[str]:
        """Resolves an executable on Windows, checking common Windows executable extensions."""
        if not name:
            return None
        found = shutil.which(name)
        if found:
            return os.path.normpath(found)

        # Check with Windows extensions if not already present
        exts = [".exe", ".cmd", ".bat", ".ps1"]
        base, ext = os.path.splitext(name)
        if not ext:
            for e in exts:
                c = shutil.which(f"{name}{e}")
                if c:
                    return os.path.normpath(c)
        return None

    def get_standard_search_roots(self) -> List[str]:
        """Returns standard Windows install roots."""
        roots: List[str] = []
        for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            p = os.environ.get(v)
            if p and os.path.exists(p) and p not in roots:
                roots.append(os.path.normpath(p))

        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            prog = os.path.join(local_appdata, "Programs")
            if os.path.exists(prog) and prog not in roots:
                roots.append(os.path.normpath(prog))

        appdata = os.environ.get("APPDATA")
        if appdata and os.path.exists(appdata) and appdata not in roots:
            roots.append(os.path.normpath(appdata))

        system_drive = os.environ.get("SystemDrive", "C:")
        tools_root = os.path.join(system_drive, "\\Tools")
        if os.path.exists(tools_root) and tools_root not in roots:
            roots.append(os.path.normpath(tools_root))

        return roots

    def find_standard_install_dirs(self, identity: Any) -> List[str]:
        """
        Discovers candidate install directories using Windows App Paths registry
        and standard Program Files / LocalAppData scans.
        """
        candidates: List[str] = []
        raw_exec = getattr(identity, "executable", None) or getattr(identity, "executable_name", str(identity))
        clean_exec = raw_exec.replace(".exe", "").replace(".cmd", "").replace(".bat", "")
        win_names = [f"{clean_exec}.exe", f"{clean_exec}.cmd", f"{clean_exec}.bat", clean_exec]

        # 1. Search Windows Registry App Paths
        try:
            import winreg
            for bin_name in win_names:
                app_sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{bin_name}"
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, app_sub) as key:
                            app_path, _ = winreg.QueryValueEx(key, "")
                            if app_path and os.path.exists(app_path):
                                norm = os.path.normpath(app_path)
                                if norm not in candidates:
                                    candidates.append(norm)
                    except Exception:
                        pass
        except Exception:
            pass

        # 2. Search configured installation paths on identity (supporting globs)
        configured_paths = getattr(identity, "installation_paths", [])
        for p in configured_paths:
            expanded = self._clean_and_expand_dir(p)
            if "*" in expanded:
                import glob
                for match in glob.glob(expanded):
                    if os.path.isfile(match) and match not in candidates:
                        candidates.append(os.path.normpath(match))
            elif os.path.isfile(expanded) and expanded not in candidates:
                candidates.append(os.path.normpath(expanded))

        # 3. Standard Program Files and LocalAppData candidate scans
        roots = self.get_standard_search_roots()
        display = getattr(identity, "display_name", "")
        ident_id = getattr(identity, "identity_id", "")
        names_to_try = [display, ident_id, clean_exec]
        for r in roots:
            for n in names_to_try:
                if not n:
                    continue
                candidate_dir = os.path.join(r, n)
                if os.path.isdir(candidate_dir):
                    for sub in ("", "bin", "cmd"):
                        target_folder = os.path.join(candidate_dir, sub) if sub else candidate_dir
                        if os.path.isdir(target_folder):
                            for b_name in win_names:
                                target_file = os.path.join(target_folder, b_name)
                                if os.path.isfile(target_file) and target_file not in candidates:
                                    candidates.append(os.path.normpath(target_file))

        return candidates

    def refresh_environment_state(self) -> None:
        """Broadcasts WM_SETTINGCHANGE to all top-level windows on Windows."""
        try:
            import ctypes
            from ctypes import wintypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = wintypes.DWORD()
            user32 = ctypes.windll.user32
            user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                1000,
                ctypes.byref(result),
            )
        except Exception:
            pass
