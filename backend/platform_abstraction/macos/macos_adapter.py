"""
platform_abstraction/macos/macos_adapter.py — Unified macOS Platform Adapter.

Aggregates macOS environment, path, service, privilege, and verification providers.
"""

from __future__ import annotations

from typing import Any

from platform_abstraction.base import PlatformAdapter
from platform_abstraction.macos.macos_environment import MacOSEnvironmentProvider
from platform_abstraction.macos.macos_machine_state import MacOSMachineStateProvider
from platform_abstraction.macos.macos_path import MacOSPathManager
from platform_abstraction.macos.macos_service import MacOSServiceManager
from platform_abstraction.macos.macos_source_awareness import (
    MacOSSourceAwarenessProvider,
    macos_source_awareness,
)
from platform_abstraction.macos.macos_verification import MacOSVerificationProvider
from privilege_manager import PrivilegeManager


class MacOSPlatformAdapter(PlatformAdapter):
    """Authoritative platform adapter for Apple macOS."""

    def __init__(self) -> None:
        self._environment = MacOSEnvironmentProvider()
        self._path_manager = MacOSPathManager(self._environment)
        self._service_manager = MacOSServiceManager()
        self._verification_provider = MacOSVerificationProvider(self._service_manager)
        self._machine_state_provider = MacOSMachineStateProvider()
        self._source_awareness_provider = MacOSSourceAwarenessProvider(
            env_provider=self._environment,
            path_manager=self._path_manager,
        )

    @property
    def platform_name(self) -> str:
        return "Darwin"

    @property
    def environment(self) -> MacOSEnvironmentProvider:
        return self._environment

    @property
    def path_manager(self) -> MacOSPathManager:
        return self._path_manager

    @property
    def service_manager(self) -> MacOSServiceManager:
        return self._service_manager

    @property
    def privilege_adapter(self) -> Any:
        return PrivilegeManager.get_adapter("darwin")

    @property
    def verification_provider(self) -> MacOSVerificationProvider:
        return self._verification_provider

    @property
    def machine_state_provider(self) -> MacOSMachineStateProvider:
        return self._machine_state_provider

    @property
    def source_awareness_provider(self) -> MacOSSourceAwarenessProvider:
        return self._source_awareness_provider

    @property
    def source_awareness(self) -> MacOSSourceAwarenessProvider:
        return self._source_awareness_provider

