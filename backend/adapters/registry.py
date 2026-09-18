"""
Adapter Registry
================
Auto-detects which package managers are present on the current machine
and exposes factory functions to get an adapter by name or all active adapters.

Design: new package managers can be added by importing their adapter class
here and adding them to ALL_ADAPTERS. No other code changes needed.
"""

from __future__ import annotations

import platform
from typing import Dict, List, Optional, Type

from .base import BaseAdapter
from .winget import WingetAdapter
from .choco import ChocoAdapter
from .scoop import ScoopAdapter
from .apt import AptAdapter
from .dnf import DnfAdapter
from .pacman import PacmanAdapter
from .brew import BrewAdapter
from .flatpak import FlatpakAdapter
from .snap import SnapAdapter
from .pip import PipAdapter
from .npm import NpmAdapter
from .cargo import CargoAdapter

# All registered adapter classes — add new ones here only.
ALL_ADAPTER_CLASSES: List[Type[BaseAdapter]] = [
    WingetAdapter,
    ChocoAdapter,
    ScoopAdapter,
    AptAdapter,
    DnfAdapter,
    PacmanAdapter,
    BrewAdapter,
    FlatpakAdapter,
    SnapAdapter,
    PipAdapter,
    NpmAdapter,
    CargoAdapter,
]

# Singleton cache — populated lazily on first call.
_active_adapters: Optional[List[BaseAdapter]] = None


def get_all_active_adapters() -> List[BaseAdapter]:
    """
    Return all adapter instances whose package manager is present on this machine.
    Result is cached for the process lifetime (adapters do not appear/disappear at runtime).
    """
    global _active_adapters
    if _active_adapters is None:
        _active_adapters = [
            cls() for cls in ALL_ADAPTER_CLASSES
            if cls().is_available()
        ]
    return _active_adapters


def get_adapter(name: str) -> Optional[BaseAdapter]:
    """
    Return the active adapter by package manager name (e.g. 'apt', 'brew', 'flatpak').
    Returns None if the package manager is not available on this machine.
    """
    for adapter in get_all_active_adapters():
        if adapter.name.lower() == name.lower():
            return adapter
    return None


get_adapter_by_name = get_adapter


def get_active_adapter_names() -> List[str]:
    """Return the names of all available package managers."""
    return [a.name for a in get_all_active_adapters()]


def get_system_adapter() -> Optional[BaseAdapter]:
    """
    Return the primary OS-level adapter (winget on Windows, apt/dnf/pacman on Linux, brew on macOS).
    Preference order per OS matches typical system defaults.
    """
    os_name = platform.system()
    preference = {
        'Windows': ['winget', 'choco', 'scoop'],
        'Darwin':  ['brew'],
        'Linux':   ['apt', 'dnf', 'pacman'],
    }.get(os_name, [])

    for pm_name in preference:
        adapter = get_adapter(pm_name)
        if adapter:
            return adapter
    # Fallback: first available
    active = get_all_active_adapters()
    return active[0] if active else None
