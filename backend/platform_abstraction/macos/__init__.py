"""macOS platform abstraction package."""

from platform_abstraction.macos.macos_adapter import MacOSPlatformAdapter
from platform_abstraction.macos.macos_environment import MacOSEnvironmentProvider
from platform_abstraction.macos.macos_path import MacOSPathManager
from platform_abstraction.macos.macos_service import MacOSServiceManager
from platform_abstraction.macos.macos_source_awareness import (
    MacOSArchitecture,
    MacOSBrewType,
    MacOSInstallSource,
    MacOSInstallation,
    MacOSSourceAnalysisResult,
    MacOSSourceAwarenessProvider,
    MacOSSourceDecisionStatus,
    MacOSSourceUpdateDecision,
    macos_source_awareness,
)
from platform_abstraction.macos.macos_verification import MacOSVerificationProvider

__all__ = [
    "MacOSPlatformAdapter",
    "MacOSEnvironmentProvider",
    "MacOSPathManager",
    "MacOSServiceManager",
    "MacOSVerificationProvider",
    "MacOSInstallSource",
    "MacOSBrewType",
    "MacOSArchitecture",
    "MacOSSourceDecisionStatus",
    "MacOSInstallation",
    "MacOSSourceAnalysisResult",
    "MacOSSourceUpdateDecision",
    "MacOSSourceAwarenessProvider",
    "macos_source_awareness",
]
