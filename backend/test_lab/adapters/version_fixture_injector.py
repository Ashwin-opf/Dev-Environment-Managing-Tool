"""
test_lab/adapters/version_fixture_injector.py — Controlled multi-version fixture injector.

Injects a harmless fixture state representing multiple active tool versions (e.g. Python)
to test PC Doctor's policy that refuses automatic mutation and flags REVIEW_REQUIRED.
"""

from __future__ import annotations

from typing import Dict, Any
from test_lab.adapters.base import FaultInjector
from test_lab.models import BaselineRecord, FaultDefinition


class VersionFixtureFaultInjector(FaultInjector):
    """Fixture injector for multi-version review scenarios."""

    def __init__(self) -> None:
        self._active_fixtures: Dict[str, Dict[str, Any]] = {}

    def inject(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        self._active_fixtures[fault_def.fault_id] = {
            "target": fault_def.target,
            "simulated_versions": fault_def.metadata.get(
                "versions", ["Python 3.12 (C:\\Python312)", "Python 3.13 (C:\\Python313)"]
            ),
        }
        return True

    def verify_fault_present(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        return fault_def.fault_id in self._active_fixtures

    def restore(self, baseline: BaselineRecord) -> bool:
        self._active_fixtures.pop(baseline.fault_id, None)
        return True

    def verify_restored(self, baseline: BaselineRecord) -> bool:
        return baseline.fault_id not in self._active_fixtures
