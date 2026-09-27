"""
platform_abstraction/base.py — Core Platform Abstraction Interfaces for PC Doctor.

Defines abstract base interfaces for OS-agnostic operations:
- EnvironmentProvider: Reading and refreshing user/machine environment variables.
- PathManager: Inspecting, normalizing, and modifying persistent PATH scopes.
- ServiceManager: Inspecting and managing OS-level services.
- VerificationProvider: Platform-aware binary and health verification.
- PlatformAdapter: Unified aggregator for all platform providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class PathScope(str, Enum):
    """Scope for environment PATH configuration."""
    USER = "USER"
    MACHINE = "MACHINE"
    EFFECTIVE = "EFFECTIVE"


class ServiceStatus(str, Enum):
    """Normalized service lifecycle state."""
    RUNNING = "Running"
    STOPPED = "Stopped"
    NOT_FOUND = "NotFound"
    ERROR = "Error"


class EnvironmentProvider(ABC):
    """Interface for querying and refreshing system environment state."""

    @abstractmethod
    def get_user_environment(self) -> Dict[str, str]:
        """Returns the persistent User-scoped environment variables."""
        pass

    @abstractmethod
    def get_machine_environment(self) -> Dict[str, str]:
        """Returns the persistent Machine/System-scoped environment variables."""
        pass

    @abstractmethod
    def get_effective_environment(self) -> Dict[str, str]:
        """Returns the merged effective environment variables."""
        pass

    @abstractmethod
    def resolve_executable(self, name: str) -> Optional[str]:
        """Resolves the full path to an executable using the platform's lookup logic."""
        pass

    @abstractmethod
    def get_standard_search_roots(self) -> List[str]:
        """Returns standard disk root paths where developer tools are typically installed."""
        pass

    @abstractmethod
    def find_standard_install_dirs(self, identity: Any) -> List[str]:
        """Finds candidate install directories for a given canonical tool identity."""
        pass

    @abstractmethod
    def refresh_environment_state(self) -> None:
        """Broadcasts or refreshes OS environment changes across the system."""
        pass

    @abstractmethod
    def refresh_effective_environment(self) -> Dict[str, str]:
        """Re-queries the OS for persistent environment state, returning the fresh effective environment dictionary."""
        pass


class PathManager(ABC):
    """Interface for managing persistent and runtime PATH configurations."""

    @abstractmethod
    def get_raw_path(self, scope: PathScope | str = PathScope.MACHINE) -> str:
        """Returns the raw unparsed PATH string for the specified scope."""
        pass

    @abstractmethod
    def get_path_entries(self, scope: PathScope | str = PathScope.MACHINE) -> List[str]:
        """Returns ordered, deduplicated directory entries from the specified persistent scope."""
        pass

    @abstractmethod
    def get_effective_path(self) -> List[str]:
        """Returns the combined persistent effective PATH (Machine + User)."""
        pass

    @abstractmethod
    def get_process_path(self) -> List[str]:
        """Returns the active PATH of the current running process."""
        pass

    @abstractmethod
    def add_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
        elevate_if_needed: bool = False,
    ) -> Tuple[bool, str]:
        """Adds a directory entry to the specified PATH scope, avoiding duplicates."""
        pass

    @abstractmethod
    def remove_path_entry(
        self,
        dir_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Removes a directory entry from the specified PATH scope."""
        pass

    @abstractmethod
    def set_exact_path(
        self,
        raw_path: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[bool, str]:
        """Sets the exact persistent PATH value for the specified scope."""
        pass

    @abstractmethod
    def generate_repair_command(
        self,
        exe_parent_dir: str,
        scope: PathScope | str = PathScope.MACHINE,
    ) -> Tuple[str, str, List[str]]:
        """
        Generates the platform-native repair command string, executable, and arguments
        for adding exe_parent_dir to the specified PATH scope.
        """
        pass

    @abstractmethod
    def normalize_path_entry(self, entry: str) -> str:
        """Normalizes a single PATH directory entry for reliable duplicate comparison."""
        pass

    @abstractmethod
    def parse_path_entries(self, raw_path_str: str) -> List[str]:
        """Safely parses a platform PATH string preserving entry order and removing duplicates."""
        pass

    @abstractmethod
    def is_dir_in_persistent_path(self, dir_path: str) -> bool:
        """Determines if dir_path is in the persistent Machine or User PATH."""
        pass

    @abstractmethod
    def is_dir_in_process_path(self, dir_path: str) -> bool:
        """Determines if dir_path is in the current process PATH."""
        pass

    @abstractmethod
    def sync_process_path(self, dir_path: str) -> None:
        """Dynamically ensures dir_path is present in the current process's os.environ['PATH']."""
        pass


class ServiceManager(ABC):
    """Interface for inspecting and controlling system background services."""

    @abstractmethod
    def detect(self, service_name: str) -> bool:
        """Returns True if the service is registered on the system."""
        pass

    @abstractmethod
    def status(self, service_name: str) -> Dict[str, Any]:
        """
        Queries live service status.
        Returns a dictionary with:
        {'exists': bool, 'status': 'Running'|'Stopped'|'NotFound'|'Error', 'name': str, ...}
        """
        pass

    @abstractmethod
    def start(self, service_name: str) -> Tuple[bool, str]:
        """Starts a service. Returns (success, message)."""
        pass

    @abstractmethod
    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stops a service. Returns (success, message)."""
        pass

    @abstractmethod
    def restart(self, service_name: str) -> Tuple[bool, str]:
        """Restarts a service. Returns (success, message)."""
        pass

    @abstractmethod
    def verify(self, service_name: str, expected_status: ServiceStatus | str) -> bool:
        """Verifies if the service matches the expected status."""
        pass

    @abstractmethod
    def generate_service_command(self, service_name: str, action: str = "start") -> Tuple[str, str, List[str]]:
        """Generates platform-specific service command string, executable, and arguments."""
        pass


class VerificationProvider(ABC):
    """Interface for platform-specific binary resolution and functional validation."""

    @abstractmethod
    def resolve_binary_path(
        self,
        executable: str,
        known_paths: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Finds the full path to a binary across PATH and known platform install locations."""
        pass

    @abstractmethod
    def probe_version(
        self,
        executable: str,
        version_command: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str], str]:
        """Executes the tool's version command. Returns (success, version_str, raw_output)."""
        pass

    @abstractmethod
    def probe_functional(
        self,
        executable: str,
        test_command: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Executes a functional probe for the tool. Returns (success, message)."""
        pass

    @abstractmethod
    def check_service_state(self, service_name: str) -> Dict[str, Any]:
        """Verifies the state of an associated service."""
        pass

    def verify_executable(self, executable: str) -> Tuple[bool, str]:
        """Verifies if an executable runs and returns version or status output."""
        success, ver, raw = self.probe_version(executable)
        return (success, ver or raw)


class MachineStateProvider(ABC):
    """Abstract interface for platform-specific machine state assessment."""

    @abstractmethod
    def check_pending_reboot(self) -> Optional[bool]:
        """Returns True if reboot is pending, False if clean, None if UNKNOWN."""
        pass

    @abstractmethod
    def check_resource_lock(self, resource_name: Optional[str] = None) -> Optional[bool]:
        """Returns True if package manager or system installer is locked, None if UNKNOWN."""
        pass

    @abstractmethod
    def check_package_manager_available(self, package_manager: str) -> Optional[bool]:
        """Checks if package manager (winget, apt, brew, etc.) is functional on host."""
        pass

    @abstractmethod
    def collect_machine_signals(self, target_identity: Optional[str] = None) -> Dict[str, Any]:
        """Collects platform-specific signals and returns normalized machine state dictionary."""
        pass


class PlatformAdapter(ABC):
    """Aggregates all platform-specific services under a unified facade."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """The canonical platform name ('Windows', 'Linux', 'Darwin')."""
        pass

    @property
    @abstractmethod
    def environment(self) -> EnvironmentProvider:
        """The environment provider for this platform."""
        pass

    @property
    @abstractmethod
    def path_manager(self) -> PathManager:
        """The PATH manager for this platform."""
        pass

    @property
    def path(self) -> PathManager:
        """Alias for path_manager."""
        return self.path_manager

    @property
    @abstractmethod
    def service_manager(self) -> ServiceManager:
        """The service manager for this platform."""
        pass

    @property
    def service(self) -> ServiceManager:
        """Alias for service_manager."""
        return self.service_manager

    @property
    @abstractmethod
    def privilege_adapter(self) -> Any:
        """The privilege manager adapter for this platform."""
        pass

    @property
    @abstractmethod
    def verification_provider(self) -> VerificationProvider:
        """The verification provider for this platform."""
        pass

    @property
    def verification(self) -> VerificationProvider:
        """Alias for verification_provider."""
        return self.verification_provider

    @property
    @abstractmethod
    def machine_state_provider(self) -> MachineStateProvider:
        """The machine state provider for this platform."""
        pass

    @property
    def machine_state(self) -> MachineStateProvider:
        """Alias for machine_state_provider."""
        return self.machine_state_provider

    def refresh_effective_environment(self) -> Dict[str, str]:
        """Refreshes and returns the effective environment via the environment provider."""
        return self.environment.refresh_effective_environment()

    @property
    def distribution_provider(self) -> Optional[Any]:
        """The distribution provider for this platform (if applicable)."""
        return None

    @property
    def distribution(self) -> Optional[Any]:
        """The detected OS distribution (if applicable)."""
        return None

    @property
    def package_manager_provider(self) -> Optional[Any]:
        """The package manager provider for this platform (if applicable)."""
        return None

    @property
    def package_manager_resolver(self) -> Optional[Any]:
        """The package manager resolver for this platform (if applicable)."""
        return None

    @property
    def source_awareness_provider(self) -> Optional[Any]:
        """The installation source awareness provider for this platform (if applicable)."""
        return None

    @property
    def source_awareness(self) -> Optional[Any]:
        """Alias for source_awareness_provider."""
        return self.source_awareness_provider


