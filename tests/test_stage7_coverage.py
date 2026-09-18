"""
test_stage7_coverage.py -- Stage 7 coverage expansion tests.

Verifies all 7 shared capabilities (SC-1 through SC-7):
  SC-1: Service repair recipes present and correctly classified
  SC-2: Permission (icacls) repair recipes present
  SC-3: Windows feature enablement recipes present with reboot tags
  SC-4: Package manager self-update recipes present
  SC-5: Residual data cleanup recipes present with CACHE_CLEAR strategy
  SC-6: Dependency graph wiring (see test_dependency_graph.py)
  SC-7: Channel field on CanonicalIdentity + multi-channel recipe variants

All tests are unit/integration tests against the static recipe DB and the
CanonicalIdentity model. No live execution or subprocess calls are made here.
"""
import os
import sys
import sqlite3
import platform
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent / "backend"
STATIC_DB = BACKEND_DIR / "knowledge_static.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_recipes(where_clause: str, params: tuple = ()) -> list:
    if not STATIC_DB.exists():
        return []
    conn = sqlite3.connect(STATIC_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM static_recipes WHERE {where_clause}", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_recipes() -> list:
    if not STATIC_DB.exists():
        return []
    conn = sqlite3.connect(STATIC_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM static_recipes").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# SC-1: Service Repair Recipes (Problems 16, 49)
# ---------------------------------------------------------------------------

class TestSC1ServiceRepairRecipes:
    """Verify that service-start REPAIR recipes exist in the static DB."""

    def test_mysql_service_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%mysql%", "Windows")
        )
        assert len(rows) >= 1, "MySQL service repair recipe missing"

    def test_postgresql_service_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%postgresql%", "Windows")
        )
        assert len(rows) >= 1, "PostgreSQL service repair recipe missing"

    def test_docker_service_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%docker%", "Windows")
        )
        assert len(rows) >= 1, "Docker service repair recipe missing"

    def test_mongodb_service_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%mongodb%", "Windows")
        )
        assert len(rows) >= 1, "MongoDB service repair recipe missing"

    def test_redis_service_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%redis%", "Windows")
        )
        assert len(rows) >= 1, "Redis service repair recipe missing"

    def test_service_recipes_have_repair_operation(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? AND os = ?",
            ("%service,repair%", "Windows")
        )
        for r in rows:
            assert r["operation"] == "REPAIR", (
                f"Service recipe '{r['issue']}' must have operation=REPAIR"
            )

    def test_service_recipes_have_verification_command(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? AND os = ? AND LOWER(tags) LIKE ?",
            ("%service%", "Windows", "%repair%")
        )
        # Only check Stage 7 recipes (those with a sc query / net start verification pattern)
        stage7_rows = [r for r in rows if r.get("verification_command", "").startswith("sc query") or
                       r.get("verification_command", "").startswith("docker")]
        assert len(stage7_rows) >= 5, (
            f"Expected >=5 Stage 7 service recipes with verification_command, got {len(stage7_rows)}"
        )
        for r in stage7_rows:
            assert r.get("verification_command", ""), (
                f"Stage 7 service repair recipe '{r['issue']}' missing verification_command"
            )

    def test_linux_service_recipe_exists(self):
        rows = _query_recipes("LOWER(issue) LIKE ? AND os = ?", ("%service%", "Linux"))
        assert len(rows) >= 1, "Linux service repair recipe missing"

    def test_macos_service_recipe_exists(self):
        rows = _query_recipes("LOWER(issue) LIKE ? AND os = ?", ("%service%", "Darwin"))
        assert len(rows) >= 1, "macOS service repair recipe missing"


# ---------------------------------------------------------------------------
# SC-2: Permission Repair Recipes (Problems 31, 73)
# ---------------------------------------------------------------------------

class TestSC2PermissionRepairRecipes:
    """Verify icacls permission repair recipes exist in the static DB."""

    def test_permission_denied_recipe_windows(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%permission%", "Windows")
        )
        assert len(rows) >= 1, "Windows permission repair recipe missing"

    def test_permission_recipe_uses_icacls_or_acl(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%permission%", "Windows")
        )
        for r in rows:
            cmd = r.get("command", "").lower()
            assert "icacls" in cmd or "acl" in cmd or "grant" in cmd, (
                f"Permission recipe '{r['issue']}' command should use icacls/ACL"
            )

    def test_uninstall_changes_permissions_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%uninstall%permission%", "Windows")
        )
        assert len(rows) >= 1, (
            "Recipe for 'uninstall changes permissions' (Problem 73) missing"
        )

    def test_permission_recipes_have_repair_strategy(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? AND os = ?",
            ("%permissions%", "Windows")
        )
        for r in rows:
            assert r.get("repair_strategy") in ("NATIVE_REPAIR", "REINSTALL", "NONE"), (
                f"Permission recipe '{r['issue']}' has unexpected repair_strategy"
            )

    def test_linux_permission_recipe_exists(self):
        rows = _query_recipes("LOWER(issue) LIKE ? AND os = ?", ("%permission%", "Linux"))
        assert len(rows) >= 1

    def test_darwin_permission_recipe_exists(self):
        rows = _query_recipes("LOWER(issue) LIKE ? AND os = ?", ("%permission%", "Darwin"))
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# SC-3: Windows Feature Enablement Recipes (Problems 50, 51)
# ---------------------------------------------------------------------------

class TestSC3WindowsFeatureRecipes:
    """Verify WSL, Hyper-V, and Containers feature enablement recipes."""

    def test_wsl_enablement_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%wsl%", "Windows")
        )
        assert len(rows) >= 1, "WSL enablement recipe missing"

    def test_hyperv_enablement_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%hyper%", "Windows")
        )
        assert len(rows) >= 1, "Hyper-V enablement recipe missing"

    def test_containers_feature_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%containers%", "Windows")
        )
        assert len(rows) >= 1, "Containers feature recipe missing"

    def test_hypervisor_platform_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%hypervisorplatform%", "Windows")
        )
        assert len(rows) >= 1, "HypervisorPlatform enablement recipe missing"

    def test_bounded_windows_feature_whitelist(self):
        """Decision 1: Verify all 5 whitelisted developer features exist with reboot-required tag."""
        whitelisted_features = [
            "Microsoft-Windows-Subsystem-Linux",
            "VirtualMachinePlatform",
            "HypervisorPlatform",
            "Microsoft-Hyper-V",
            "Containers"
        ]
        rows = _query_recipes("category = ? AND os = ?", ("WindowsFeatures", "Windows"))
        commands = " ".join(r.get("command", "") for r in rows)
        for feat in whitelisted_features:
            assert feat.lower() in commands.lower(), f"Whitelisted feature {feat} not in static recipes"
        reboot_rows = [r for r in rows if "reboot-required" in r.get("tags", "")]
        assert len(reboot_rows) >= 5, f"Expected all 5 whitelisted features to be tagged reboot-required, got {len(reboot_rows)}"

    def test_wsl_recipe_uses_enable_windows_optional_feature(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%wsl%enabled%", "Windows")
        )
        wsl_rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%wsl%", "Windows")
        )
        for r in wsl_rows:
            cmd = r.get("command", "").lower()
            if "enable" in cmd:
                assert "enable-windowsoptionalfeature" in cmd or "dism" in cmd, (
                    f"WSL recipe must use Enable-WindowsOptionalFeature, got: {r['command']}"
                )

    def test_feature_recipes_tagged_reboot_required(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? AND os = ?",
            ("%reboot-required%", "Windows")
        )
        assert len(rows) >= 3, (
            "Expected at least 3 reboot-required feature recipes (WSL, VirtualMachinePlatform, Hyper-V)"
        )

    def test_feature_recipes_have_high_risk(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? AND os = ?",
            ("%reboot-required%", "Windows")
        )
        for r in rows:
            assert r.get("risk") == "High", (
                f"Feature recipe '{r['issue']}' must have risk=High (triggers reboot)"
            )

    def test_wsl_kernel_update_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%wsl kernel%", "Windows")
        )
        assert len(rows) >= 1, "WSL kernel update recipe missing"

    def test_wsl_kernel_update_is_low_risk(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%wsl kernel%", "Windows")
        )
        if rows:
            assert rows[0]["risk"] == "Low"


# ---------------------------------------------------------------------------
# SC-4: Package Manager Self-Update Recipes (Problem 25)
# ---------------------------------------------------------------------------

class TestSC4PackageManagerSelfUpdate:
    """Verify PM self-update recipes exist in the static DB."""

    def test_winget_self_update_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%winget%", "Windows")
        )
        update_rows = [r for r in rows if r.get("operation") == "UPDATE"]
        assert len(update_rows) >= 1, "WinGet self-update recipe missing"

    def test_chocolatey_self_update_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%chocolatey%", "Windows")
        )
        update_rows = [r for r in rows if r.get("operation") == "UPDATE"]
        assert len(update_rows) >= 1, "Chocolatey self-update recipe missing"

    def test_apt_self_update_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%apt%", "Linux")
        )
        update_rows = [r for r in rows if r.get("operation") == "UPDATE"]
        assert len(update_rows) >= 1, "apt self-update recipe missing"

    def test_brew_self_update_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%brew%", "Darwin")
        )
        update_rows = [r for r in rows if r.get("operation") == "UPDATE"]
        assert len(update_rows) >= 1, "brew self-update recipe missing"

    def test_pm_update_recipes_have_verification_command(self):
        rows = _query_recipes(
            "LOWER(tags) LIKE ? ",
            ("%self-update%",)
        )
        for r in rows:
            assert r.get("verification_command", ""), (
                f"PM self-update recipe '{r['issue']}' missing verification_command"
            )

    def test_pm_update_recipes_are_low_risk(self):
        rows = _query_recipes("LOWER(tags) LIKE ?", ("%self-update%",))
        for r in rows:
            assert r.get("risk") in ("Low", "Medium"), (
                f"PM self-update recipe should be Low/Medium risk, got: {r.get('risk')}"
            )


# ---------------------------------------------------------------------------
# SC-5: Residual Data Cleanup Recipes (Problem 35)
# ---------------------------------------------------------------------------

class TestSC5ResidualCleanupRecipes:
    """Verify residual data cleanup recipes use CACHE_CLEAR strategy."""

    def test_residual_cleanup_recipe_windows(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%residual%", "Windows")
        )
        assert len(rows) >= 1, "Windows residual cleanup recipe missing"

    def test_residual_cleanup_recipe_linux(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%residual%", "Linux")
        )
        assert len(rows) >= 1, "Linux residual cleanup recipe missing"

    def test_residual_cleanup_recipe_darwin(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%residual%", "Darwin")
        )
        assert len(rows) >= 1, "macOS residual cleanup recipe missing"

    def test_residual_recipes_use_cache_clear_strategy(self):
        rows = _query_recipes("LOWER(issue) LIKE ?", ("%residual%",))
        for r in rows:
            assert r.get("repair_strategy") == "CACHE_CLEAR", (
                f"Residual cleanup recipe '{r['issue']}' must use CACHE_CLEAR strategy"
            )

    def test_residual_recipes_are_high_risk(self):
        rows = _query_recipes("LOWER(issue) LIKE ?", ("%residual%",))
        for r in rows:
            assert r.get("risk") == "High", (
                f"Residual data deletion recipe must be risk=High, got: {r.get('risk')}"
            )

    def test_residual_recipes_have_tier3_tag(self):
        rows = _query_recipes("LOWER(issue) LIKE ?", ("%residual%",))
        for r in rows:
            tags = r.get("tags", "")
            assert "tier3" in tags.lower() or "cleanup" in tags.lower(), (
                f"Residual cleanup recipe '{r['issue']}' must have tier3 tag"
            )


# ---------------------------------------------------------------------------
# SC-7: Channel Field on CanonicalIdentity (Problem 40)
# ---------------------------------------------------------------------------

class TestSC7ChannelFieldOnCanonicalIdentity:
    """Verify the new channel field on CanonicalIdentity."""

    def test_channel_field_exists_on_dataclass(self):
        from canonical_identity import CanonicalIdentity
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(CanonicalIdentity)]
        assert "channel" in field_names, "CanonicalIdentity must have a 'channel' field"

    def test_channel_defaults_to_stable(self):
        from canonical_identity import CanonicalIdentity
        ci = CanonicalIdentity(
            identity_id="test",
            display_name="Test",
            package_id="test.test",
            publisher="Test Publisher",
            executable="test",
        )
        assert ci.channel == "stable"

    def test_channel_can_be_set_to_lts(self):
        from canonical_identity import CanonicalIdentity
        ci = CanonicalIdentity(
            identity_id="nodejs-lts",
            display_name="Node.js LTS",
            package_id="OpenJS.NodeJS.LTS",
            publisher="OpenJS Foundation",
            executable="node",
            channel="lts",
        )
        assert ci.channel == "lts"

    def test_channel_can_be_set_to_beta(self):
        from canonical_identity import CanonicalIdentity
        ci = CanonicalIdentity(
            identity_id="vscode-insiders",
            display_name="VS Code Insiders",
            package_id="Microsoft.VisualStudioCode.Insiders",
            publisher="Microsoft",
            executable="code-insiders",
            channel="beta",
        )
        assert ci.channel == "beta"

    def test_channel_serializes_to_dict(self):
        from canonical_identity import CanonicalIdentity
        ci = CanonicalIdentity(
            identity_id="nodejs-lts",
            display_name="Node.js LTS",
            package_id="OpenJS.NodeJS.LTS",
            publisher="OpenJS Foundation",
            executable="node",
            channel="lts",
        )
        d = ci.to_dict()
        assert "channel" in d
        assert d["channel"] == "lts"

    def test_channel_deserializes_from_dict(self):
        from canonical_identity import CanonicalIdentity
        data = {
            "identity_id": "python-lts",
            "display_name": "Python LTS",
            "package_id": "Python.Python.3.12",
            "publisher": "Python Software Foundation",
            "executable": "python",
            "channel": "lts",
        }
        ci = CanonicalIdentity.from_dict(data)
        assert ci.channel == "lts"

    def test_channel_defaults_stable_when_missing_from_dict(self):
        from canonical_identity import CanonicalIdentity
        data = {
            "identity_id": "git",
            "display_name": "Git",
            "package_id": "Git.Git",
            "publisher": "The Git Project",
            "executable": "git",
            # no channel key
        }
        ci = CanonicalIdentity.from_dict(data)
        assert ci.channel == "stable"

    def test_channel_roundtrip(self):
        from canonical_identity import CanonicalIdentity
        ci = CanonicalIdentity(
            identity_id="node-nightly",
            display_name="Node.js Nightly",
            package_id="OpenJS.NodeJS",
            publisher="OpenJS Foundation",
            executable="node",
            channel="nightly",
        )
        ci2 = CanonicalIdentity.from_dict(ci.to_dict())
        assert ci2.channel == "nightly"


class TestSC7MultiChannelRecipesInDB:
    """Verify multi-channel recipe variants exist in the static DB."""

    def test_nodejs_lts_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%node%lts%", "Windows")
        )
        assert len(rows) >= 1, "Node.js LTS channel install recipe missing"

    def test_nodejs_current_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%node%current%", "Windows")
        )
        assert len(rows) >= 1, "Node.js current channel install recipe missing"

    def test_vscode_insiders_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%insiders%", "Windows")
        )
        assert len(rows) >= 1, "VS Code Insiders channel recipe missing"

    def test_python_lts_recipe_exists(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%python lts%", "Windows")
        )
        assert len(rows) >= 1, "Python LTS channel recipe missing"

    def test_nodejs_lts_uses_correct_package_id(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%node%lts%", "Windows")
        )
        if rows:
            cmd = rows[0].get("command", "")
            assert "OpenJS.NodeJS.LTS" in cmd, (
                f"LTS recipe should reference OpenJS.NodeJS.LTS, got: {cmd}"
            )

    def test_nodejs_current_is_medium_risk(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%node%current%", "Windows")
        )
        if rows:
            assert rows[0].get("risk") == "Medium", (
                "Current/latest channel should be Medium risk (may have breaking changes)"
            )

    def test_lts_channel_is_low_risk(self):
        rows = _query_recipes(
            "LOWER(issue) LIKE ? AND os = ?",
            ("%node%lts%", "Windows")
        )
        if rows:
            assert rows[0].get("risk") == "Low"


# ---------------------------------------------------------------------------
# Static DB integrity after Stage 7 additions
# ---------------------------------------------------------------------------

class TestStage7StaticDBIntegrity:
    """Cross-cutting integrity checks after all Stage 7 recipes are added."""

    def test_static_db_exists(self):
        assert STATIC_DB.exists(), "knowledge_static.db must exist"

    def test_recipe_count_increased(self):
        """After Stage 7 additions there should be significantly more recipes."""
        rows = _all_recipes()
        assert len(rows) >= 50, (
            f"Expected >=50 recipes after Stage 7, got {len(rows)}"
        )

    def test_all_recipes_have_issue(self):
        rows = _all_recipes()
        for r in rows:
            assert r.get("issue", "").strip(), f"Recipe id={r.get('id')} has empty issue"

    def test_all_recipes_have_command(self):
        rows = _all_recipes()
        for r in rows:
            assert r.get("command", "").strip(), f"Recipe id={r.get('id')} has empty command"

    def test_all_recipes_have_valid_risk(self):
        rows = _all_recipes()
        valid_risks = {"Low", "Medium", "High", "Critical"}
        for r in rows:
            assert r.get("risk") in valid_risks, (
                f"Recipe '{r.get('issue')}' has invalid risk='{r.get('risk')}'"
            )

    def test_all_recipes_have_valid_operation(self):
        rows = _all_recipes()
        valid_ops = {"INSTALL", "REINSTALL", "REPAIR", "UPDATE", "UNINSTALL", "VERIFY"}
        for r in rows:
            op = r.get("operation", "REPAIR")
            assert op in valid_ops, (
                f"Recipe '{r.get('issue')}' has invalid operation='{op}'"
            )

    def test_new_categories_exist(self):
        if not STATIC_DB.exists():
            pytest.skip("Static DB not present")
        conn = sqlite3.connect(STATIC_DB)
        categories = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT category FROM static_recipes"
            ).fetchall()
        }
        conn.close()
        assert "Services" in categories, "Services category missing after SC-1"
        assert "Permissions" in categories, "Permissions category missing after SC-2"
        assert "WindowsFeatures" in categories, "WindowsFeatures category missing after SC-3"
        assert "PackageManagers" in categories, "PackageManagers category missing after SC-4"
        assert "Cleanup" in categories, "Cleanup category missing after SC-5"
