"""
test_lab/catalog.py — Authoritative Fault Catalog for PC Doctor Test Lab.

Provides a matrix of structured, parameterized fault definitions across PATH,
Service, Port, Version, and Simulation capabilities without hardcoded test scripts.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional
from test_lab.models import (
    FaultCapability,
    FaultDefinition,
    FaultRiskClass,
    InjectionMode,
)


class FaultCatalog:
    """Catalog of registered testable faults across supported capabilities."""

    def __init__(self) -> None:
        self._definitions: Dict[str, FaultDefinition] = {}
        self._init_catalog()

    def _init_catalog(self) -> None:
        # 1. Git Machine PATH Entry Missing (Real Machine Mutation - Controlled)
        self.register(
            FaultDefinition(
                fault_id="GIT_MACHINE_PATH_MISSING",
                target="Git",
                capability=FaultCapability.PATH,
                scope="MACHINE",
                platforms=["windows"],
                risk_class=FaultRiskClass.CONTROLLED,
                reversible=True,
                requires_admin=True,
                target_entry=r"C:\Program Files\Git\cmd",
                injector="PATH_ENTRY_REMOVAL",
                simulation_mode=InjectionMode.REAL,
                expected_behavior="REPAIR_AND_VERIFY",
                verification="L1_L2_L3_L5",
                description="Removes Git command directory from Windows Machine PATH to test detection, privilege elevation, and repair.",
            )
        )

        # 2. User-Scope PATH Entry Missing (Real Machine Mutation - Controlled)
        test_user_dir = os.path.normpath(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\TestLab"))
        self.register(
            FaultDefinition(
                fault_id="USER_PATH_MISSING",
                target="PythonTestEnv",
                capability=FaultCapability.PATH,
                scope="USER",
                platforms=["windows"],
                risk_class=FaultRiskClass.CONTROLLED,
                reversible=True,
                requires_admin=False,
                target_entry=test_user_dir,
                injector="PATH_ENTRY_REMOVAL",
                simulation_mode=InjectionMode.REAL,
                expected_behavior="REPAIR_AND_VERIFY",
                verification="L1",
                description="Removes a safe test directory from User-scope PATH to test non-elevated repair.",
            )
        )

        # 3. Stopped Developer Service (Real Machine Mutation - Controlled)
        self.register(
            FaultDefinition(
                fault_id="DEVELOPER_SERVICE_STOPPED",
                target="MySQL Server",
                capability=FaultCapability.SERVICE,
                scope="MACHINE",
                platforms=["windows"],
                risk_class=FaultRiskClass.CONTROLLED,
                reversible=True,
                requires_admin=False,
                injector="SERVICE_STOP",
                simulation_mode=InjectionMode.REAL,
                expected_behavior="REPAIR_AND_VERIFY",
                verification="L1",
                metadata={"service_name": "MySQL80"},
                description="Stops approved non-critical developer service (MySQL80) to verify service health diagnosis.",
            )
        )

        # 4. Controlled Port Conflict (Real Machine - Ephemeral)
        self.register(
            FaultDefinition(
                fault_id="CONTROLLED_PORT_CONFLICT",
                target="TestPort",
                capability=FaultCapability.PORT,
                scope="PROCESS",
                platforms=["windows", "linux", "darwin"],
                risk_class=FaultRiskClass.CONTROLLED,
                reversible=True,
                requires_admin=False,
                injector="PORT_BIND",
                simulation_mode=InjectionMode.REAL,
                expected_behavior="REPAIR_AND_VERIFY",
                verification="L1",
                metadata={"port": 18765},
                description="Binds temporary socket on non-critical port 18765 to test port conflict detection.",
            )
        )

        # 5. Python Multiple Versions (Simulation / Review-Only Scenario)
        self.register(
            FaultDefinition(
                fault_id="PYTHON_MULTIPLE_VERSIONS_REVIEW",
                target="Python",
                capability=FaultCapability.VERSION_IDENTITY,
                scope="MACHINE",
                platforms=["windows", "linux", "darwin"],
                risk_class=FaultRiskClass.CONTROLLED,
                reversible=True,
                requires_admin=False,
                injector="VERSION_FIXTURE",
                simulation_mode=InjectionMode.MOCK,
                expected_behavior="REVIEW_REQUIRED",
                verification="REVIEW_REQUIRED",
                metadata={"versions": ["Python 3.12 (C:\\Python312)", "Python 3.13 (C:\\Python313)"]},
                description="Injects harmless multiple-version scenario. Verifies PC Doctor marks REVIEW_REQUIRED and avoids destructive repair.",
            )
        )

        # 6. Driver Package Corruption (Simulation-Only Safety Scenario)
        self.register(
            FaultDefinition(
                fault_id="DRIVER_CORRUPTION_SIMULATED",
                target="GraphicsDriver",
                capability=FaultCapability.DRIVER,
                scope="MACHINE",
                platforms=["windows", "linux"],
                risk_class=FaultRiskClass.UNSAFE,
                reversible=False,
                requires_admin=True,
                injector="SIMULATED_DRIVER_FAULT",
                simulation_mode=InjectionMode.SIMULATED,
                expected_behavior="BLOCKED",
                verification="BLOCKED",
                description="Dangerous condition: non-reversible driver corruption. Enforces SIMULATION_ONLY and safety gate blocks real injection.",
            )
        )

        # 7. Low Disk Space Condition (Simulation-Only Safety Scenario)
        self.register(
            FaultDefinition(
                fault_id="LOW_DISK_SPACE_SIMULATED",
                target="SystemDrive",
                capability=FaultCapability.DISK,
                scope="MACHINE",
                platforms=["windows", "linux", "darwin"],
                risk_class=FaultRiskClass.UNSAFE,
                reversible=False,
                requires_admin=False,
                injector="SIMULATED_DISK_FAULT",
                simulation_mode=InjectionMode.SIMULATED,
                expected_behavior="BLOCKED",
                verification="BLOCKED",
                description="Dangerous condition: low disk space simulation. Real machine mutation is strictly prevented.",
            )
        )

    def register(self, definition: FaultDefinition) -> None:
        self._definitions[definition.fault_id] = definition

    def get(self, fault_id: str) -> Optional[FaultDefinition]:
        return self._definitions.get(fault_id)

    def list_all(
        self,
        platform: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> List[FaultDefinition]:
        results = list(self._definitions.values())
        if platform:
            p_lower = platform.lower()
            results = [r for r in results if any(p.lower() == p_lower for p in r.platforms)]
        if capability:
            results = [r for r in results if r.capability.value == capability or r.capability == capability]
        return results


    def filter(
        self,
        capability: Optional[FaultCapability] = None,
        platform_name: Optional[str] = None,
        mode: Optional[InjectionMode] = None,
    ) -> List[FaultDefinition]:
        results = list(self._definitions.values())
        if capability:
            results = [r for r in results if r.capability == capability]
        if platform_name:
            results = [r for r in results if platform_name.lower() in [p.lower() for p in r.platforms]]
        if mode:
            results = [r for r in results if r.simulation_mode == mode]
        return results


fault_catalog = FaultCatalog()
