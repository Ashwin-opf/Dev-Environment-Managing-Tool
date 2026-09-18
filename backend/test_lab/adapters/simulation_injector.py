"""
test_lab/adapters/simulation_injector.py — Simulation-only fault injector.

Used for dangerous, destructive, or hardware/OS-level conditions (e.g. low disk space,
driver corruption, boot problems) that must NEVER be injected into the real machine.
"""

from __future__ import annotations

from typing import Dict, Any
from test_lab.adapters.base import FaultInjector
from test_lab.models import BaselineRecord, FaultDefinition


class SimulationFaultInjector(FaultInjector):
    """Simulation-only injector that prevents real-machine mutation."""

    def __init__(self) -> None:
        self._simulated_states: Dict[str, Dict[str, Any]] = {}

    def inject(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        # Strictly in-memory simulation — zero mutation on the real machine
        self._simulated_states[fault_def.fault_id] = {
            "fault_id": fault_def.fault_id,
            "target": fault_def.target,
            "simulated": True,
            "details": fault_def.metadata,
        }
        return True

    def verify_fault_present(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        return fault_def.fault_id in self._simulated_states

    def restore(self, baseline: BaselineRecord) -> bool:
        self._simulated_states.pop(baseline.fault_id, None)
        return True

    def verify_restored(self, baseline: BaselineRecord) -> bool:
        return baseline.fault_id not in self._simulated_states
