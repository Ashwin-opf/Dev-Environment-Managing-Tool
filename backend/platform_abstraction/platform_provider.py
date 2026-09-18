"""
platform_abstraction/platform_provider.py — Authoritative Platform Provider Factory.

Dynamically instantiates and caches the active PlatformAdapter (Windows, Linux, macOS).
Provides clean dependency-injected facades so core modules never need to inspect platform.system().
"""

from __future__ import annotations

import platform
from typing import Dict, Optional

from platform_abstraction.base import (
    EnvironmentProvider,
    PathManager,
    PlatformAdapter,
    ServiceManager,
    VerificationProvider,
)
from platform_abstraction.linux.linux_adapter import LinuxPlatformAdapter
from platform_abstraction.macos.macos_adapter import MacOSPlatformAdapter
from platform_abstraction.windows.windows_adapter import WindowsPlatformAdapter


class PlatformProviderRegistry:
    """Singleton cache of platform adapters."""

    _adapters: Dict[str, PlatformAdapter] = {}

    @classmethod
    def get_platform_adapter(cls, sys_platform: Optional[str] = None) -> PlatformAdapter:
        """Resolves the PlatformAdapter for the specified OS (or current host OS)."""
        plat = (sys_platform or platform.system()).lower()
        if "windows" in plat or "win32" in plat:
            key = "windows"
            if key not in cls._adapters:
                cls._adapters[key] = WindowsPlatformAdapter()
            return cls._adapters[key]
        elif "darwin" in plat or "mac" in plat or "osx" in plat:
            key = "darwin"
            if key not in cls._adapters:
                cls._adapters[key] = MacOSPlatformAdapter()
            return cls._adapters[key]
        else:
            key = "linux"
            if key not in cls._adapters:
                cls._adapters[key] = LinuxPlatformAdapter()
            return cls._adapters[key]

    @classmethod
    def reset(cls) -> None:
        """Clears cached adapter singletons (useful for test isolation)."""
        cls._adapters.clear()


def get_platform_adapter(sys_platform: Optional[str] = None) -> PlatformAdapter:
    """Returns the unified PlatformAdapter for the current or specified platform."""
    return PlatformProviderRegistry.get_platform_adapter(sys_platform)


def get_environment_provider(sys_platform: Optional[str] = None) -> EnvironmentProvider:
    """Returns the EnvironmentProvider for the current or specified platform."""
    return get_platform_adapter(sys_platform).environment


def get_path_manager(sys_platform: Optional[str] = None) -> PathManager:
    """Returns the PathManager for the current or specified platform."""
    return get_platform_adapter(sys_platform).path_manager


def get_service_manager(sys_platform: Optional[str] = None) -> ServiceManager:
    """Returns the ServiceManager for the current or specified platform."""
    return get_platform_adapter(sys_platform).service_manager


def get_verification_provider(sys_platform: Optional[str] = None) -> VerificationProvider:
    """Returns the VerificationProvider for the current or specified platform."""
    return get_platform_adapter(sys_platform).verification_provider
