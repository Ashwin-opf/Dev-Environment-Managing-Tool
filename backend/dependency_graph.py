"""
dependency_graph.py -- Topological Dependency Resolver for PC Doctor (SC-6)

Provides:
  - DependencyNode: a single tool node with its direct dependency list.
  - DependencyGraph: an acyclic dependency DAG with Kahn's topological sort.
  - topological_install_order(): returns an ordered list of tool identity_ids
    that satisfies all dependency constraints (dependencies installed first).

Design constraints:
  - SAT-free: only handles direct acyclic chains (no circular dependencies).
  - OS-agnostic: works on any platform.
  - Mandatory pipeline: callers feed the result into recipe_resolver and
    CentralizedExecutionEngine; this module does NOT execute anything.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DependencyNode:
    """Represents a single tool and its direct runtime prerequisites."""
    identity_id: str
    display_name: str = ""
    dependencies: List[str] = field(default_factory=list)
    version_constraint: Optional[str] = None
    optional: bool = False

    def __hash__(self) -> int:
        return hash(self.identity_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DependencyNode):
            return self.identity_id == other.identity_id
        return NotImplemented


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class DependencyGraph:
    """
    Directed Acyclic Graph (DAG) of tool dependencies.

    Usage:
        graph = DependencyGraph()
        graph.add_node(DependencyNode("maven", dependencies=["java"]))
        graph.add_node(DependencyNode("java"))
        order = graph.topological_install_order()
        # ["java", "maven"]
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, DependencyNode] = {}

    def add_node(self, node: DependencyNode) -> None:
        self._nodes[node.identity_id] = node

    def add_nodes(self, nodes: List[DependencyNode]) -> None:
        for n in nodes:
            self.add_node(n)

    def get_node(self, identity_id: str) -> Optional[DependencyNode]:
        return self._nodes.get(identity_id)

    def all_nodes(self) -> List[DependencyNode]:
        return list(self._nodes.values())

    def has_cycle(self) -> bool:
        try:
            self.topological_install_order()
            return False
        except ValueError:
            return True

    def find_missing_dependencies(self) -> Dict[str, List[str]]:
        missing: Dict[str, List[str]] = {}
        for node in self._nodes.values():
            absent = [dep for dep in node.dependencies if dep not in self._nodes]
            if absent:
                missing[node.identity_id] = absent
        return missing

    def topological_install_order(
        self,
        roots: Optional[List[str]] = None,
        include_optional: bool = False,
    ) -> List[str]:
        """
        Returns a topologically sorted list of identity_ids such that every
        dependency appears before the tools that depend on it.

        Raises ValueError if a circular dependency is detected.
        """
        if roots is not None:
            included = self._reachable_from(roots, include_optional)
        else:
            included = set(self._nodes.keys())

        in_degree: Dict[str, int] = {nid: 0 for nid in included}
        dependents: Dict[str, List[str]] = {nid: [] for nid in included}

        for nid in included:
            node = self._nodes[nid]
            for dep in node.dependencies:
                if not include_optional and self._nodes.get(dep, DependencyNode(dep)).optional:
                    continue
                if dep not in included:
                    continue
                dependents[dep].append(nid)
                in_degree[nid] += 1

        queue: deque[str] = deque(nid for nid in included if in_degree[nid] == 0)
        result: List[str] = []

        while queue:
            nid = queue.popleft()
            result.append(nid)
            for dependent in dependents.get(nid, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(included):
            cycle_members = sorted(nid for nid in included if nid not in result)
            raise ValueError(
                f"Circular dependency detected among: {cycle_members}. "
                "Cannot produce a safe topological install order."
            )

        return result

    def missing_dependency_repair_plan(
        self,
        target: str,
        installed: Optional[Set[str]] = None,
    ) -> List[str]:
        """
        Returns the ordered list of identity_ids that must be installed to
        satisfy all transitive dependencies of target.
        """
        installed = installed or set()
        if target not in self._nodes:
            return [target]
        full_order = self.topological_install_order(roots=[target])
        return [nid for nid in full_order if nid not in installed or nid == target]

    def _reachable_from(self, roots: List[str], include_optional: bool) -> Set[str]:
        visited: Set[str] = set()
        queue: deque[str] = deque(r for r in roots if r in self._nodes)
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = self._nodes.get(nid)
            if node:
                for dep in node.dependencies:
                    if not include_optional and self._nodes.get(dep, DependencyNode(dep)).optional:
                        continue
                    if dep in self._nodes and dep not in visited:
                        queue.append(dep)
        return visited


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_graph_from_canonical_store() -> DependencyGraph:
    """
    Constructs a DependencyGraph by reading every CanonicalIdentity from the
    global canonical_store. Import is deferred to avoid circular imports.
    """
    from canonical_identity import canonical_store  # deferred import

    graph = DependencyGraph()

    well_known: Dict[str, List[str]] = {
        "maven":         ["java"],
        "gradle":        ["java"],
        "kotlin":        ["java"],
        "android-studio": ["java"],
        "npm":           ["nodejs"],
        "yarn":          ["nodejs"],
        "pnpm":          ["nodejs"],
        "pip":           ["python"],
        "pipenv":        ["python", "pip"],
        "poetry":        ["python", "pip"],
        "conda":         ["python"],
        "jupyter":       ["python", "pip"],
        "tox":           ["python", "pip"],
        "pytest":        ["python", "pip"],
        "mypy":          ["python", "pip"],
        "black":         ["python", "pip"],
        "ruff":          ["python", "pip"],
    }

    for identity in canonical_store.list_all():
        deps: List[str] = []
        overrides = getattr(identity, "platform_overrides", {})
        if "dependencies" in overrides.get("all", {}):
            deps = list(overrides["all"]["dependencies"])
        if not deps and identity.identity_id in well_known:
            deps = well_known[identity.identity_id]

        graph.add_node(DependencyNode(
            identity_id=identity.identity_id,
            display_name=identity.display_name,
            dependencies=deps,
        ))
    return graph
