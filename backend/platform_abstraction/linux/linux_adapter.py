"""
platform_abstraction/linux/linux_adapter.py — Unified Linux Platform Adapter.

Aggregates Linux environment, path, service, privilege, and verification providers.
"""

from __future__ import annotations

from typing import Any

from platform_abstraction.base import PlatformAdapter
from platform_abstraction.linux.linux_distribution import LinuxDistribution, LinuxDistributionProvider
from platform_abstraction.linux.linux_environment import LinuxEnvironmentProvider
from platform_abstraction.linux.linux_machine_state import LinuxMachineStateProvider
from platform_abstraction.linux.linux_package_manager import (
    LinuxPackageManagerProvider,
    LinuxPackageManagerResolver,
)
from platform_abstraction.linux.linux_path import LinuxPathManager
from platform_abstraction.linux.linux_service import LinuxServiceManager
from platform_abstraction.linux.linux_verification import LinuxVerificationProvider
from privilege_manager import PrivilegeManager


class LinuxPlatformAdapter(PlatformAdapter):
    """Authoritative platform adapter for Linux distributions."""

    def __init__(self) -> None:
        self._environment = LinuxEnvironmentProvider()
        self._path_manager = LinuxPathManager(self._environment)
        self._service_manager = LinuxServiceManager()
        self._verification_provider = LinuxVerificationProvider(self._service_manager)
        self._machine_state_provider = LinuxMachineStateProvider()
        self._distribution_provider = LinuxDistributionProvider()
        self._distribution = self._distribution_provider.detect_distribution()
        self._package_manager_resolver = LinuxPackageManagerResolver(self._distribution)
        resolved_pm, _, _ = self._package_manager_resolver.resolve_provider_for_distribution(self._distribution)
        self._package_manager_provider = resolved_pm

    @property
    def platform_name(self) -> str:
        return "Linux"

    @property
    def environment(self) -> LinuxEnvironmentProvider:
        return self._environment

    @property
    def path_manager(self) -> LinuxPathManager:
        return self._path_manager

    @property
    def service_manager(self) -> LinuxServiceManager:
        return self._service_manager

    @property
    def privilege_adapter(self) -> Any:
        return PrivilegeManager.get_adapter("linux")

    @property
    def verification_provider(self) -> LinuxVerificationProvider:
        return self._verification_provider

    @property
    def machine_state_provider(self) -> LinuxMachineStateProvider:
        return self._machine_state_provider

    @property
    def distribution_provider(self) -> LinuxDistributionProvider:
        return self._distribution_provider

    @property
    def distribution(self) -> LinuxDistribution:
        return self._distribution

    @property
    def package_manager_provider(self) -> Optional[LinuxPackageManagerProvider]:
        return self._package_manager_provider

    @property
    def package_manager_resolver(self) -> LinuxPackageManagerResolver:
        return self._package_manager_resolver

