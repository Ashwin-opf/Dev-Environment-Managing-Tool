"""
platform_abstraction — PC Doctor Cross-Platform Abstraction Layer.

Exposes abstract interfaces and dynamic platform factories:
- EnvironmentProvider, PathManager, ServiceManager, VerificationProvider, PlatformAdapter
- get_platform_adapter, get_environment_provider, get_path_manager, get_service_manager, get_verification_provider
- CAPABILITY_MATRIX, get_capability_status
"""

from platform_abstraction.base import (
    EnvironmentProvider,
    PathManager,
    PathScope,
    PlatformAdapter,
    ServiceManager,
    ServiceStatus,
    VerificationProvider,
)
from platform_abstraction.capability_matrix import (
    CAPABILITY_MATRIX,
    CapabilityStatus,
    PlatformCapability,
    get_capability_matrix,
    get_capability_status,
    get_platform_capabilities,
    is_capability_supported,
    to_matrix_dict,
)
from platform_abstraction.platform_provider import (
    get_environment_provider,
    get_path_manager,
    get_platform_adapter,
    get_service_manager,
    get_verification_provider,
)

__all__ = [
    "PathScope",
    "ServiceStatus",
    "EnvironmentProvider",
    "PathManager",
    "ServiceManager",
    "VerificationProvider",
    "PlatformAdapter",
    "CAPABILITY_MATRIX",
    "CapabilityStatus",
    "PlatformCapability",
    "get_capability_status",
    "get_capability_matrix",
    "is_capability_supported",
    "get_platform_capabilities",
    "to_matrix_dict",
    "get_platform_adapter",
    "get_environment_provider",
    "get_path_manager",
    "get_service_manager",
    "get_verification_provider",
]
