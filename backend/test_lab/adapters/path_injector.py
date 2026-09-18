"""
test_lab/adapters/path_injector.py — Generic, cross-platform PATH fault injector.

Operations:
- REMOVE_ENTRY: Removes only the target normalized entry from the chosen scope.
- RESTORE_ENTRY: Restores the exact original baseline state.
Preserves all unrelated PATH entries, avoids duplicates, and supports both User and Machine scopes.
"""

from __future__ import annotations

import os
import platform
from typing import Any, Dict, List, Optional, Tuple
from test_lab.adapters.base import FaultInjector
from test_lab.models import BaselineRecord, FaultDefinition
from dev_environment_detector import EffectivePath, PathScope
from privilege_manager import PrivilegeManager


class PathFaultInjector(FaultInjector):
    """Generic cross-platform PATH fault injector."""

    def __init__(self) -> None:
        self.os_type = platform.system().lower()

    def _normalize_path(self, raw_path_str: str) -> List[str]:
        """Normalizes and deduplicates a PATH string preserving order."""
        if not raw_path_str:
            return []
        parts = [p.strip() for p in raw_path_str.split(";") if p.strip()]
        seen = set()
        result = []
        for p in parts:
            norm = EffectivePath.normalize_path_entry(p)
            if norm not in seen:
                seen.add(norm)
                result.append(p)
        return result

    def _get_raw_path(self, scope: str = "MACHINE") -> str:
        """Retrieves raw persistent PATH string for scope."""
        scope_upper = scope.upper()
        entries = EffectivePath.get_machine_path() if scope_upper == "MACHINE" else EffectivePath.get_user_path()
        return ";".join(entries)

    def _set_raw_path(self, raw_path: str, scope: str = "MACHINE") -> bool:
        """Sets raw persistent PATH string for scope."""
        scope_enum = PathScope.MACHINE if scope.upper() == "MACHINE" else PathScope.USER
        ok, msg = EffectivePath.set_exact_persistent_path(raw_path, scope=scope_enum)
        if not ok and scope.upper() == "MACHINE":
            return self._execute_elevated_op({
                "operation": "RESTORE_PATH",
                "path": raw_path,
                "scope": "MACHINE",
                "application": "Test Lab",
            })
        return ok

    def _execute_elevated_op(self, payload: dict) -> bool:
        adapter = PrivilegeManager.get_adapter()
        gen = adapter.execute_elevated(payload, timeout_sec=45)
        try:
            while True:
                next(gen)
        except StopIteration as si:
            res = si.value or {}
            return bool(res.get("ok"))
        except Exception:
            return False

    def inject(
        self,
        fault_def: Optional[FaultDefinition] = None,
        baseline: Optional[BaselineRecord] = None,
        *,
        target_entry: Optional[str] = None,
        scope: str = "MACHINE",
    ) -> Any:
        """Removes the target directory from the specified PATH scope."""
        target_dir = (
            target_entry
            or (fault_def.target_entry if fault_def else None)
            or (baseline.original_state.get("target_entry") if baseline else None)
        )
        if not target_dir:
            return ("FAILED", "No target entry specified") if target_entry else False

        sc = (
            scope
            or (fault_def.scope if fault_def else None)
            or (baseline.original_state.get("scope") if baseline else None)
            or "MACHINE"
        ).upper()
        clean_target = os.path.normpath(target_dir).rstrip("\\/")
        target_norm = EffectivePath.normalize_path_entry(clean_target)

        raw = self._get_raw_path(sc)
        entries = self._normalize_path(raw)

        # Filter out target entry while strictly preserving all other entries
        remaining = [e for e in entries if EffectivePath.normalize_path_entry(e) != target_norm]
        new_raw = ";".join(remaining)
        ok = self._set_raw_path(new_raw, sc)

        if not ok and sc == "MACHINE":
            ok = self._execute_elevated_op({
                "operation": "REMOVE_PATH",
                "directory": clean_target,
                "scope": "MACHINE",
                "application": "Test Lab",
            })

        if target_entry:
            return ("INJECTED", f"Successfully removed '{clean_target}' from {sc} PATH") if ok else ("FAILED", f"Could not modify {sc} PATH")
        return ok

    def verify_fault_present(
        self,
        fault_def: Optional[FaultDefinition] = None,
        baseline: Optional[BaselineRecord] = None,
        *,
        target_entry: Optional[str] = None,
        scope: str = "MACHINE",
    ) -> bool:
        """Verifies that the target directory is absent from the persistent PATH."""
        target_dir = (
            target_entry
            or (fault_def.target_entry if fault_def else None)
            or (baseline.original_state.get("target_entry") if baseline else None)
        )
        if not target_dir:
            return False

        sc = (
            scope
            or (fault_def.scope if fault_def else None)
            or (baseline.original_state.get("scope") if baseline else None)
            or "MACHINE"
        ).upper()
        clean_target = os.path.normpath(target_dir).rstrip("\\/")
        target_norm = EffectivePath.normalize_path_entry(clean_target)

        raw = self._get_raw_path(sc)
        entries = self._normalize_path(raw)

        # Must NOT be in the targeted scope
        return not any(EffectivePath.normalize_path_entry(e) == target_norm for e in entries)

    def restore(self, baseline: BaselineRecord) -> Any:
        """Restores the exact original persistent PATH from the baseline."""
        scope = (baseline.original_state.get("scope") or "MACHINE").upper()
        original_path = baseline.original_state.get("path") or baseline.original_state.get("original_path")
        target_entry = baseline.original_state.get("target_entry")

        if original_path is not None:
            ok = self._set_raw_path(str(original_path), scope)
            return ("RESTORED", f"Restored exact {scope} PATH baseline") if ok else ("FAILED", "Restoration failed")
        elif target_entry:
            raw = self._get_raw_path(scope)
            entries = self._normalize_path(raw)
            target_norm = EffectivePath.normalize_path_entry(target_entry)
            if not any(EffectivePath.normalize_path_entry(e) == target_norm for e in entries):
                entries.append(target_entry)
            ok = self._set_raw_path(";".join(entries), scope)
            return ("RESTORED", f"Restored {target_entry} to {scope} PATH") if ok else ("FAILED", "Restoration failed")
        return False

    def verify_restored(self, baseline: BaselineRecord) -> bool:
        """Verifies that the target directory or exact path has been restored."""
        scope = (baseline.original_state.get("scope") or "MACHINE").upper()
        original_path = baseline.original_state.get("path") or baseline.original_state.get("original_path")
        target_entry = baseline.original_state.get("target_entry")

        raw = self._get_raw_path(scope)
        if original_path is not None:
            curr_entries = [EffectivePath.normalize_path_entry(e) for e in self._normalize_path(raw)]
            orig_entries = [EffectivePath.normalize_path_entry(e) for e in self._normalize_path(str(original_path))]
            return curr_entries == orig_entries

        if target_entry:
            entries = self._normalize_path(raw)
            target_norm = EffectivePath.normalize_path_entry(target_entry)
            return any(EffectivePath.normalize_path_entry(e) == target_norm for e in entries)

        return True


class WindowsPathFaultInjector(PathFaultInjector):
    """Windows-specific PATH fault injector utilizing registry APIs and elevated worker."""

    def __init__(self) -> None:
        super().__init__()
        self.os_type = "windows"


class LinuxPathFaultInjector(PathFaultInjector):
    """Linux-specific PATH fault injector manipulating environment profiles."""

    def __init__(self) -> None:
        super().__init__()
        self.os_type = "linux"


class MacOSPathFaultInjector(PathFaultInjector):
    """macOS-specific PATH fault injector manipulating paths.d or user profiles."""

    def __init__(self) -> None:
        super().__init__()
        self.os_type = "darwin"
