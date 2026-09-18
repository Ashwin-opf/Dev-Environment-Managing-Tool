"""macOS platform abstraction package."""

from platform_abstraction.macos.macos_adapter import MacOSPlatformAdapter
from platform_abstraction.macos.macos_environment import MacOSEnvironmentProvider
from platform_abstraction.macos.macos_path import MacOSPathManager
from platform_abstraction.macos.macos_service import MacOSServiceManager
from platform_abstraction.macos.macos_verification import MacOSVerificationProvider

__all__ = [
    "MacOSPlatformAdapter",
    "MacOSEnvironmentProvider",
    "MacOSPathManager",
    "MacOSServiceManager",
    "MacOSVerificationProvider",
]
