"""
test_dependency_graph.py -- Stage 7 SC-6: Dependency Graph tests.

Tests DependencyNode, DependencyGraph, topological sort, cycle detection,
missing dependency analysis, and the mandatory pipeline routing contract.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dependency_graph import DependencyGraph, DependencyNode, build_graph_from_canonical_store


# ---------------------------------------------------------------------------
# DependencyNode basics
# ---------------------------------------------------------------------------

class TestDependencyNode:
    def test_hash_equality_by_id(self):
        a = DependencyNode("java", display_name="Java JDK")
        b = DependencyNode("java", display_name="Different Name")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_ids_not_equal(self):
        a = DependencyNode("java")
        b = DependencyNode("python")
        assert a != b

    def test_default_not_optional(self):
        node = DependencyNode("git")
        assert node.optional is False

    def test_optional_flag(self):
        node = DependencyNode("junit", optional=True)
        assert node.optional is True

    def test_version_constraint_none_by_default(self):
        node = DependencyNode("maven")
        assert node.version_constraint is None

    def test_version_constraint_stored(self):
        node = DependencyNode("maven", version_constraint=">=3.8")
        assert node.version_constraint == ">=3.8"


# ---------------------------------------------------------------------------
# Topological sort — basic cases
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def _make_graph(self, edges: dict) -> DependencyGraph:
        """edges: {id: [dep1, dep2]} — all nodes auto-registered."""
        graph = DependencyGraph()
        all_ids = set(edges.keys())
        for deps in edges.values():
            all_ids.update(deps)
        for nid in all_ids:
            if nid not in edges:
                graph.add_node(DependencyNode(nid, dependencies=[]))
        for nid, deps in edges.items():
            graph.add_node(DependencyNode(nid, dependencies=deps))
        return graph

    def test_single_node_no_deps(self):
        g = self._make_graph({"git": []})
        order = g.topological_install_order()
        assert order == ["git"]

    def test_linear_chain(self):
        """pip depends on python; python has no deps."""
        g = self._make_graph({"pip": ["python"], "python": []})
        order = g.topological_install_order()
        assert order.index("python") < order.index("pip")

    def test_three_level_chain(self):
        """poetry -> pip -> python"""
        g = self._make_graph({
            "poetry": ["pip"],
            "pip":    ["python"],
            "python": [],
        })
        order = g.topological_install_order()
        assert order.index("python") < order.index("pip")
        assert order.index("pip") < order.index("poetry")

    def test_diamond_dependency(self):
        """black -> python, ruff -> python; both must follow python."""
        g = self._make_graph({
            "black":  ["python"],
            "ruff":   ["python"],
            "python": [],
        })
        order = g.topological_install_order()
        assert order.index("python") < order.index("black")
        assert order.index("python") < order.index("ruff")

    def test_java_maven_gradle(self):
        """maven and gradle both depend on java."""
        g = self._make_graph({
            "java":   [],
            "maven":  ["java"],
            "gradle": ["java"],
        })
        order = g.topological_install_order()
        assert order.index("java") < order.index("maven")
        assert order.index("java") < order.index("gradle")

    def test_node_npm_yarn(self):
        """npm and yarn depend on nodejs."""
        g = self._make_graph({
            "nodejs": [],
            "npm":    ["nodejs"],
            "yarn":   ["nodejs"],
        })
        order = g.topological_install_order()
        assert order.index("nodejs") < order.index("npm")
        assert order.index("nodejs") < order.index("yarn")

    def test_all_nodes_included(self):
        """Every registered node must appear in the output exactly once."""
        g = self._make_graph({
            "java":   [],
            "maven":  ["java"],
            "python": [],
            "pip":    ["python"],
        })
        order = g.topological_install_order()
        assert sorted(order) == sorted(["java", "maven", "python", "pip"])
        assert len(order) == len(set(order))  # no duplicates


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def _cycle_graph(self, *cycle_ids) -> DependencyGraph:
        """Creates a simple circular chain: a->b->c->a."""
        ids = list(cycle_ids)
        g = DependencyGraph()
        for i, nid in enumerate(ids):
            dep = ids[(i + 1) % len(ids)]
            g.add_node(DependencyNode(nid, dependencies=[dep]))
        return g

    def test_simple_cycle_raises(self):
        g = self._cycle_graph("a", "b")
        with pytest.raises(ValueError, match="Circular dependency"):
            g.topological_install_order()

    def test_three_way_cycle_raises(self):
        g = self._cycle_graph("x", "y", "z")
        with pytest.raises(ValueError, match="Circular dependency"):
            g.topological_install_order()

    def test_has_cycle_returns_true(self):
        g = self._cycle_graph("foo", "bar")
        assert g.has_cycle() is True

    def test_has_cycle_returns_false_for_dag(self):
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        assert g.has_cycle() is False

    def test_cycle_error_names_members(self):
        g = self._cycle_graph("alpha", "beta")
        with pytest.raises(ValueError) as exc_info:
            g.topological_install_order()
        msg = str(exc_info.value)
        assert "alpha" in msg or "beta" in msg


# ---------------------------------------------------------------------------
# Roots-based scoping
# ---------------------------------------------------------------------------

class TestRootScoping:
    def _full_graph(self) -> DependencyGraph:
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        g.add_node(DependencyNode("python"))
        g.add_node(DependencyNode("pip", dependencies=["python"]))
        g.add_node(DependencyNode("poetry", dependencies=["pip"]))
        return g

    def test_roots_limits_output(self):
        g = self._full_graph()
        order = g.topological_install_order(roots=["maven"])
        assert "maven" in order
        assert "java" in order
        # unrelated tools must not appear
        assert "python" not in order
        assert "pip" not in order

    def test_roots_single_no_deps(self):
        g = self._full_graph()
        order = g.topological_install_order(roots=["python"])
        assert order == ["python"]

    def test_roots_transitive_closure(self):
        g = self._full_graph()
        order = g.topological_install_order(roots=["poetry"])
        assert "python" in order
        assert "pip" in order
        assert "poetry" in order
        assert order.index("python") < order.index("pip")
        assert order.index("pip") < order.index("poetry")

    def test_unknown_root_ignored(self):
        g = self._full_graph()
        order = g.topological_install_order(roots=["nonexistent"])
        assert order == []


# ---------------------------------------------------------------------------
# Missing dependency repair plan
# ---------------------------------------------------------------------------

class TestMissingDependencyRepairPlan:
    def _graph(self) -> DependencyGraph:
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        g.add_node(DependencyNode("python"))
        g.add_node(DependencyNode("pip", dependencies=["python"]))
        g.add_node(DependencyNode("poetry", dependencies=["pip"]))
        return g

    def test_full_plan_when_nothing_installed(self):
        g = self._graph()
        plan = g.missing_dependency_repair_plan("poetry")
        assert plan.index("python") < plan.index("pip")
        assert plan.index("pip") < plan.index("poetry")

    def test_plan_skips_already_installed(self):
        g = self._graph()
        plan = g.missing_dependency_repair_plan("poetry", installed={"python"})
        assert "python" not in plan
        assert "pip" in plan
        assert "poetry" in plan

    def test_plan_always_includes_target(self):
        g = self._graph()
        plan = g.missing_dependency_repair_plan("maven", installed={"java", "maven"})
        assert "maven" in plan  # target always present even if installed

    def test_unknown_target_returns_just_target(self):
        g = self._graph()
        plan = g.missing_dependency_repair_plan("unknown_tool")
        assert plan == ["unknown_tool"]

    def test_target_no_deps_returns_target_only(self):
        g = self._graph()
        plan = g.missing_dependency_repair_plan("java")
        assert plan == ["java"]


# ---------------------------------------------------------------------------
# find_missing_dependencies
# ---------------------------------------------------------------------------

class TestFindMissingDependencies:
    def test_detects_unregistered_dep(self):
        g = DependencyGraph()
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        # java not registered
        missing = g.find_missing_dependencies()
        assert "maven" in missing
        assert "java" in missing["maven"]

    def test_no_missing_when_all_registered(self):
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        assert g.find_missing_dependencies() == {}

    def test_empty_graph_no_missing(self):
        g = DependencyGraph()
        assert g.find_missing_dependencies() == {}


# ---------------------------------------------------------------------------
# build_graph_from_canonical_store integration
# ---------------------------------------------------------------------------

class TestBuildGraphFromCanonicalStore:
    def test_returns_dependency_graph_instance(self):
        graph = build_graph_from_canonical_store()
        assert isinstance(graph, DependencyGraph)

    def test_graph_has_nodes(self):
        graph = build_graph_from_canonical_store()
        assert len(graph.all_nodes()) > 0

    def test_graph_has_no_cycle(self):
        """The canonical store must never produce a circular dependency."""
        graph = build_graph_from_canonical_store()
        assert graph.has_cycle() is False

    def test_well_known_deps_wired(self):
        """pip must depend on python; maven must depend on java (if both registered)."""
        graph = build_graph_from_canonical_store()
        nodes_by_id = {n.identity_id: n for n in graph.all_nodes()}
        if "pip" in nodes_by_id and "python" in nodes_by_id:
            assert "python" in nodes_by_id["pip"].dependencies
        if "maven" in nodes_by_id and "java" in nodes_by_id:
            assert "java" in nodes_by_id["maven"].dependencies

    def test_topological_order_valid_for_whole_store(self):
        """Full store topological sort must not raise."""
        graph = build_graph_from_canonical_store()
        order = graph.topological_install_order()
        assert isinstance(order, list)
        assert len(order) == len(set(order))  # no duplicates


# ---------------------------------------------------------------------------
# Pipeline contract: dependency graph is READ-ONLY; never executes
# ---------------------------------------------------------------------------

class TestPipelineContract:
    def test_graph_has_no_subprocess_calls(self):
        """DependencyGraph must never import subprocess or os.system."""
        import dependency_graph
        import inspect
        src = inspect.getsource(dependency_graph)
        assert "subprocess" not in src
        assert "os.system" not in src
        assert "shell=True" not in src

    def test_graph_output_is_pure_id_list(self):
        """Output is a plain list of strings — no commands, no side effects."""
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        result = g.topological_install_order()
        assert all(isinstance(x, str) for x in result)

    def test_repair_plan_output_is_pure_id_list(self):
        g = DependencyGraph()
        g.add_node(DependencyNode("java"))
        g.add_node(DependencyNode("maven", dependencies=["java"]))
        plan = g.missing_dependency_repair_plan("maven")
        assert all(isinstance(x, str) for x in plan)
