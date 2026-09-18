"""
test_lab/baseline_manager.py — Captures and manages minimal restoration state before fault injection.

Design goals:
- Minimal state capture: Captures ONLY the affected resource (PATH string, service status, etc.).
- Never snapshots the entire PC unnecessarily.
- Keeps track of all pending baselines in memory and persisted to JSON.
- Provides emergency cleanup / restore for all pending baselines.
"""

from __future__ import annotations

import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from test_lab.models import BaselineRecord, FaultCapability, FaultDefinition
from platform_abstraction import get_path_manager

BASE_DIR = Path(__file__).parent.parent
BASELINES_FILE = BASE_DIR / "test_lab_baselines.json"


class BaselineManager:
    """Manages baseline snapshots for controlled fault injection."""

    def __init__(self, persistence_file: Optional[Path] = None, storage_path: Optional[Path] = None) -> None:
        self.persistence_file = storage_path or persistence_file or BASELINES_FILE
        self._baselines: Dict[str, BaselineRecord] = {}
        self._load_persisted()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _load_persisted(self) -> None:
        if self.persistence_file.exists():
            try:
                data = json.loads(self.persistence_file.read_text(encoding="utf-8"))
                for item in data:
                    rec = BaselineRecord.from_dict(item)
                    self._baselines[rec.test_id] = rec
            except Exception:
                pass

    def _save_persisted(self) -> None:
        try:
            items = [b.to_dict() for b in self._baselines.values() if b.cleanup_status == "PENDING"]
            self.persistence_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except Exception:
            pass

    def list_pending(self) -> List[BaselineRecord]:
        """Returns all baselines awaiting restoration."""
        return [b for b in self._baselines.values() if b.cleanup_status == "PENDING"]

    def capture_baseline(
        self,
        test_id: Optional[str] = None,
        fault_def: Optional[FaultDefinition] = None,
        *,
        fault_id: Optional[str] = None,
        target_identity: Optional[str] = None,
        platform_name: Optional[str] = None,
        affected_resource: Optional[str] = None,
        original_state: Optional[Dict[str, Any]] = None,
        restoration_strategy: str = "EXACT_RESTORE",
    ) -> BaselineRecord:
        """Captures minimal required state based on fault capability or explicit params."""
        import uuid

        if fault_def is None and fault_id:
            tid = test_id or f"test_{uuid.uuid4().hex[:8]}"
            record = BaselineRecord(
                test_id=tid,
                timestamp=self._utc_now(),
                fault_id=fault_id,
                target_identity=target_identity or "Unknown",
                platform=platform_name or platform.system().lower(),
                affected_resource=affected_resource or "UNKNOWN",
                original_state=original_state or {},
                restoration_strategy=restoration_strategy,
                cleanup_status="PENDING",
            )
            self._baselines[tid] = record
            self._save_persisted()
            return record

        assert test_id is not None and fault_def is not None, "Either (test_id, fault_def) or explicit keyword params must be provided"
        original_state = {}
        affected_res = fault_def.target
        strat = "EXACT_RESTORE"

        # 1. PATH Capability
        if fault_def.capability == FaultCapability.PATH:
            scope = (fault_def.scope or "MACHINE").upper()
            affected_res = f"{scope}_PATH"
            target_entry = fault_def.target_entry or ""

            path_mgr = get_path_manager()
            raw_path = path_mgr.get_raw_path(scope=scope)

            original_state = {
                "scope": scope,
                "original_path": raw_path,
                "target_entry": target_entry,
            }
            if platform.system() == "Windows":
                sub = (
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
                    if scope == "MACHINE"
                    else r"Environment"
                )
                original_state["hive"] = "HKLM" if scope == "MACHINE" else "HKCU"
                original_state["subkey"] = sub

        # 2. SERVICE Capability
        elif fault_def.capability == FaultCapability.SERVICE:
            service_name = fault_def.metadata.get("service_name", fault_def.target)
            affected_res = f"SERVICE_{service_name}"
            from dev_environment_detector import dev_environment_detector
            svc_info = dev_environment_detector.check_service(service_name)
            original_state = {
                "service_name": service_name,
                "original_status": svc_info.get("status", "Stopped"),
                "exists": svc_info.get("exists", False),
            }

        # 3. PORT Capability
        elif fault_def.capability == FaultCapability.PORT:
            port = fault_def.metadata.get("port", 18765)
            affected_res = f"PORT_{port}"
            original_state = {
                "port": port,
                "original_bound": False,
            }

        # 4. SIMULATION / FIXTURE Capability
        else:
            affected_res = f"SIMULATED_{fault_def.target}"
            strat = "SIMULATION_NOOP"
            original_state = {
                "simulation": True,
                "target": fault_def.target,
            }

        record = BaselineRecord(
            test_id=test_id,
            timestamp=self._utc_now(),
            fault_id=fault_def.fault_id,
            target_identity=fault_def.target,
            platform=platform.system().lower(),
            affected_resource=affected_res,
            original_state=original_state,
            restoration_strategy=strat,
            cleanup_status="PENDING",
        )

        self._baselines[test_id] = record
        self._save_persisted()
        return record

    def get_baseline(self, test_id: str) -> Optional[BaselineRecord]:
        return self._baselines.get(test_id)

    def mark_restored(self, test_id: str, success: bool) -> None:
        rec = self._baselines.get(test_id)
        if rec:
            rec.cleanup_status = "RESTORED" if success else "FAILED_RESTORATION"
            self._save_persisted()

    def list_active_baselines(self) -> List[BaselineRecord]:
        return [b for b in self._baselines.values() if b.cleanup_status == "PENDING"]


# Global singleton instance
baseline_manager = BaselineManager()
