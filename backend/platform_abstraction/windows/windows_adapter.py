"""
platform_abstraction/windows/windows_adapter.py — Unified Windows Platform Adapter.

Aggregates Windows environment, path, service, privilege, and verification providers.
"""

from __future__ import annotations

from typing import Any

from platform_abstraction.base import PlatformAdapter
from platform_abstraction.windows.windows_environment import WindowsEnvironmentProvider
from platform_abstraction.windows.windows_machine_state import WindowsMachineStateProvider
from platform_abstraction.windows.windows_path import WindowsPathManager
from platform_abstraction.windows.windows_service import WindowsServiceManager
from platform_abstraction.windows.windows_verification import WindowsVerificationProvider
from privilege_manager import PrivilegeManager


class WindowsPlatformAdapter(PlatformAdapter):
    """Authoritative platform adapter for Microsoft Windows."""

    def __init__(self) -> None:
        self._environment = WindowsEnvironmentProvider()
        self._path_manager = WindowsPathManager(self._environment)
        self._service_manager = WindowsServiceManager()
        self._verification_provider = WindowsVerificationProvider(self._service_manager)
        self._machine_state_provider = WindowsMachineStateProvider()

    @property
    def platform_name(self) -> str:
        return "Windows"

    @property
    def environment(self) -> WindowsEnvironmentProvider:
        return self._environment

    @property
    def path_manager(self) -> WindowsPathManager:
        return self._path_manager

    @property
    def service_manager(self) -> WindowsServiceManager:
        return self._service_manager

    @property
    def privilege_adapter(self) -> Any:
        return PrivilegeManager.get_adapter("windows")

    @property
    def verification_provider(self) -> WindowsVerificationProvider:
        return self._verification_provider

    @property
    def machine_state_provider(self) -> WindowsMachineStateProvider:
        return self._machine_state_provider

