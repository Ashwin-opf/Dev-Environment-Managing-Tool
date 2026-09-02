"""
Dependency Resolver
===================
Builds full dependency graphs for a requested action by querying adapters
recursively. Shared by Search, Install Pipeline, and Repair — one engine,
multiple entry points.

Never stores commands or versions — queries adapters live every time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """A single node in the dependency graph."""
    name: str
    version: str = 'latest'
    adapter_name: str = ''
    install_command: str = ''
    children: List['DependencyNode'] = field(default_factory=list)
    error: Optional[str] = None
    is_cycle: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'version': self.version,
            'adapter': self.adapter_name,
            'install_command': self.install_command,
            'children': [c.to_dict() for c in self.children],
            'error': self.error,
            'is_cycle': self.is_cycle,
        }


@dataclass
class CanonicalAction:
    """Canonical representation of any user request, OS-independent."""
    intent: str            # install | remove | repair | configure
    target: str            # tool name
    constraints: List[str] = field(default_factory=list)  # version pins, flags
    adapter_name: Optional[str] = None  # preferred adapter, or None for auto


class VersionConflict(Exception):
    pass


class DependencyResolver:
    """
    Shared dependency resolver.
    Builds the dependency tree for a CanonicalAction by recursively querying
    adapter.info() calls. Detects cycles and version conflicts.
    """

    MAX_DEPTH = 6

    def __init__(self) -> None:
        # Lazy import to avoid circular import at module level
        from adapters.registry import get_all_active_adapters, get_adapter, get_system_adapter
        self._get_all = get_all_active_adapters
        self._get_adapter = get_adapter
        self._get_system = get_system_adapter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_tree(self, action: CanonicalAction) -> DependencyNode:
        """
        Build the full dependency tree for the given action.
        Returns the root DependencyNode with children populated.
        """
        visited: Set[str] = set()
        version_registry: Dict[str, str] = {}
        return self._resolve_node(
            name=action.target,
            constraints=action.constraints,
            adapter_name=action.adapter_name,
            visited=visited,
            version_registry=version_registry,
            depth=0,
        )

    def resolve_install_order(self, root: DependencyNode) -> List[DependencyNode]:
        """
        Perform a post-order traversal to get installation order
        (dependencies first, then the requested target).
        """
        result: List[DependencyNode] = []
        seen: Set[str] = set()

        def _walk(node: DependencyNode) -> None:
            if node.name in seen or node.is_cycle or node.error:
                return
            seen.add(node.name)
            for child in node.children:
                _walk(child)
            result.append(node)

        _walk(root)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _pick_adapter(self, name: str, preferred: Optional[str] = None):
        if preferred:
            a = self._get_adapter(preferred)
            if a:
                return a
        return self._get_system()

    def _resolve_node(
        self,
        name: str,
        constraints: List[str],
        adapter_name: Optional[str],
        visited: Set[str],
        version_registry: Dict[str, str],
        depth: int,
    ) -> DependencyNode:
        # Cycle detection
        if name in visited:
            return DependencyNode(name=name, is_cycle=True)

        if depth > self.MAX_DEPTH:
            return DependencyNode(name=name, error=f'Max depth {self.MAX_DEPTH} exceeded')

        visited = visited | {name}  # immutable update for this branch

        adapter = self._pick_adapter(name, adapter_name)
        if not adapter:
            return DependencyNode(name=name, error='No suitable adapter found')

        # Resolve latest version live from adapter
        try:
            version = adapter.resolve_latest(name)
        except Exception as exc:
            version = 'latest'
            logger.warning('resolve_latest(%s) failed: %s', name, exc)

        # Version conflict detection
        if name in version_registry and version_registry[name] != version:
            node = DependencyNode(
                name=name,
                version=version,
                adapter_name=adapter.name,
                error=f'Version conflict: {version_registry[name]} vs {version}',
            )
            return node
        version_registry[name] = version

        # Generate install command at resolution time (never stored)
        try:
            install_cmd = adapter.install(name, constraints)
        except Exception:
            install_cmd = ''

        # Query dependencies from adapter
        try:
            info = adapter.info(name)
            dep_names: List[str] = info.get('dependencies', []) or []
        except Exception:
            dep_names = []

        # Recursively resolve children
        children: List[DependencyNode] = []
        for dep in dep_names:
            child = self._resolve_node(
                name=dep,
                constraints=[],
                adapter_name=adapter_name,
                visited=visited,
                version_registry=version_registry,
                depth=depth + 1,
            )
            children.append(child)

        return DependencyNode(
            name=name,
            version=version,
            adapter_name=adapter.name,
            install_command=install_cmd,
            children=children,
        )
