"""
BaseAdapter Interface
====================
Thin adapter interface exposing uniform methods for search, resolve_latest,
install, update, uninstall, reinstall, verify, and capability checks across
all package managers. No tool-specific logic lives here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the package manager (e.g. winget, apt, brew, choco)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the package manager binary is available on PATH."""
        pass

    def detect(self) -> bool:
        """Alias for is_available() conforming to frozen architecture."""
        return self.is_available()

    @abstractmethod
    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for available packages matching query.
        Returns a list of dicts: [{'name': str, 'id': str, 'version': str, 'description': str}]
        """
        pass

    @abstractmethod
    def resolve_latest(self, name: str) -> str:
        """
        Query the package manager live to resolve the latest available version string.
        """
        pass

    @abstractmethod
    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        """
        Generate the shell command string to install the requested tool/version at runtime.
        """
        pass

    def update(self, name: str) -> str:
        """
        Generate the shell command string to update the requested tool at runtime.
        """
        return f"{self.name} upgrade {name}"

    @abstractmethod
    def remove(self, name: str) -> str:
        """
        Generate the shell command string to remove/uninstall the requested tool at runtime.
        """
        pass

    def uninstall(self, name: str) -> str:
        """Conforming alias for remove()."""
        return self.remove(name)

    def reinstall(self, name: str) -> str:
        """
        Generate the shell command string to reinstall/repair the tool via package manager.
        """
        return f"{self.install(name)} --force"

    def list_installed(self) -> List[Dict[str, Any]]:
        """List packages installed by this package manager."""
        return []

    def verify(self, name: str) -> Dict[str, Any]:
        """Verify package state via package manager query."""
        return {"installed": False, "version": None}

    def supports_operation(self, operation: str, name_or_id: Optional[str] = None) -> bool:
        """Check if this adapter supports a given operation for a package."""
        op = operation.upper()
        if op in ("INSTALL", "SEARCH", "INFO", "LIST_INSTALLED"):
            return True
        if op in ("UPDATE", "UNINSTALL", "REINSTALL"):
            return True
        return False

    def supports_dry_run(self) -> bool:
        """Whether this package manager supports a simulated dry run."""
        return False

    @abstractmethod
    def info(self, name: str) -> Dict[str, Any]:
        """
        Query package information including dependencies, home page, and license.
        Returns dict: {'name': str, 'version': str, 'dependencies': list[str], 'homepage': str, 'description': str}
        """
        pass
