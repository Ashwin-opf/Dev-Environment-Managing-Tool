"""
BaseAdapter Interface
====================
Thin adapter interface exposing uniform methods for search, resolve_latest,
install, remove, and info across all package managers. No tool-specific logic lives here.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the package manager (e.g. winget, apt, brew, flatpak)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the package manager binary is available on PATH."""
        pass

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

    @abstractmethod
    def remove(self, name: str) -> str:
        """
        Generate the shell command string to remove/uninstall the requested tool at runtime.
        """
        pass

    @abstractmethod
    def info(self, name: str) -> Dict[str, Any]:
        """
        Query package information including dependencies, home page, and license.
        Returns dict: {'name': str, 'version': str, 'dependencies': list[str], 'homepage': str, 'description': str}
        """
        pass
