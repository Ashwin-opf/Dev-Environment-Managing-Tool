"""
Full unit-test suite for DevToolsManager.

Tests cover:
- install_tool()         -> creates a record with all generated commands
- get_management_commands() -> retrieves update/uninstall commands
- list_managed_apps()    -> returns full list
- remove_managed_app()   -> removes entry, returns True/False
- get_managed_app()      -> single-record lookup
- Command generation for all 8 package managers
- Legacy list-format migration
- Package name extraction from various tool_info shapes
"""
import sys
import json
import tempfile
import unittest
from pathlib import Path

# Add backend directory to Python path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from devtools_manager import DevToolsManager


class TestDevToolsManagerCore(unittest.TestCase):
    """Core CRUD operations on the DevToolsManager."""

    def setUp(self):
        """Each test gets its own isolated store in a temp directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "test_managed_apps.json"
        self.mgr = DevToolsManager(store_path=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    # --- install_tool ---

    def test_install_tool_creates_record(self):
        info = {
            "name": "Git",
            "install_command": "apt-get install -y git",
            "category": "Developer Tools",
            "description": "Distributed version control",
        }
        rec = self.mgr.install_tool(info)
        self.assertEqual(rec["name"], "Git")
        self.assertIn("app_id", rec)
        self.assertIn("update_command", rec)
        self.assertIn("uninstall_command", rec)
        self.assertTrue(len(rec["update_command"]) > 0)
        self.assertTrue(len(rec["uninstall_command"]) > 0)

    def test_install_tool_persists_to_disk(self):
        self.mgr.install_tool({"name": "Node.js", "install_command": "apt-get install -y nodejs"})
        # Re-load from disk
        mgr2 = DevToolsManager(store_path=self.store)
        apps = mgr2.list_managed_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["name"], "Node.js")

    def test_install_tool_uses_explicit_app_id(self):
        rec = self.mgr.install_tool({"name": "Python", "app_id": "python3", "install_command": "apt-get install -y python3"})
        self.assertEqual(rec["app_id"], "python3")

    def test_install_tool_idempotent_on_same_app_id(self):
        self.mgr.install_tool({"name": "Docker", "app_id": "docker", "install_command": "apt-get install -y docker"})
        self.mgr.install_tool({"name": "Docker Updated", "app_id": "docker", "install_command": "apt-get install -y docker-ce"})
        apps = self.mgr.list_managed_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["name"], "Docker Updated")

    # --- list_managed_apps ---

    def test_list_managed_apps_empty_initially(self):
        self.assertEqual(self.mgr.list_managed_apps(), [])

    def test_list_managed_apps_returns_all(self):
        self.mgr.install_tool({"name": "Git", "install_command": "apt install git"})
        self.mgr.install_tool({"name": "Vim", "install_command": "apt install vim"})
        self.assertEqual(len(self.mgr.list_managed_apps()), 2)

    # --- get_managed_app ---

    def test_get_managed_app_existing(self):
        self.mgr.install_tool({"name": "Rust", "app_id": "rust", "install_command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"})
        app = self.mgr.get_managed_app("rust")
        self.assertIsNotNone(app)
        self.assertEqual(app["name"], "Rust")

    def test_get_managed_app_missing_returns_none(self):
        result = self.mgr.get_managed_app("does-not-exist")
        self.assertIsNone(result)

    # --- get_management_commands ---

    def test_get_management_commands_existing(self):
        self.mgr.install_tool({"name": "Go", "app_id": "go", "install_command": "apt install golang"})
        cmds = self.mgr.get_management_commands("go")
        self.assertIn("update_command", cmds)
        self.assertIn("uninstall_command", cmds)
        self.assertIsInstance(cmds["update_command"], str)
        self.assertIsInstance(cmds["uninstall_command"], str)

    def test_get_management_commands_missing_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.mgr.get_management_commands("nonexistent-app")

    # --- remove_managed_app ---

    def test_remove_managed_app_existing_returns_true(self):
        self.mgr.install_tool({"name": "Jq", "app_id": "jq", "install_command": "apt install jq"})
        result = self.mgr.remove_managed_app("jq")
        self.assertTrue(result)
        self.assertIsNone(self.mgr.get_managed_app("jq"))

    def test_remove_managed_app_missing_returns_false(self):
        result = self.mgr.remove_managed_app("never-installed")
        self.assertFalse(result)

    def test_remove_managed_app_persists_deletion(self):
        self.mgr.install_tool({"name": "Htop", "app_id": "htop", "install_command": "apt install htop"})
        self.mgr.remove_managed_app("htop")
        mgr2 = DevToolsManager(store_path=self.store)
        self.assertIsNone(mgr2.get_managed_app("htop"))


class TestCommandGeneration(unittest.TestCase):
    """Verify correct update/uninstall commands for each package manager."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "test_store.json"
        self.mgr = DevToolsManager(store_path=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _install_with_pm(self, name, pm, pkg=None):
        info = {
            "name": name,
            "package_manager": pm,
            "install_command": f"{pm} install {pkg or name.lower()}",
        }
        if pkg:
            info["package_name"] = pkg
        return self.mgr.install_tool(info)

    def test_apt_commands(self):
        rec = self._install_with_pm("Nginx", "apt", "nginx")
        self.assertIn("apt-get", rec["update_command"])
        self.assertIn("nginx", rec["update_command"])
        self.assertIn("apt-get remove", rec["uninstall_command"])
        self.assertIn("nginx", rec["uninstall_command"])

    def test_snap_commands(self):
        rec = self._install_with_pm("VLC", "snap", "vlc")
        self.assertIn("snap refresh", rec["update_command"])
        self.assertIn("vlc", rec["update_command"])
        self.assertIn("snap remove", rec["uninstall_command"])

    def test_flatpak_commands(self):
        rec = self._install_with_pm("GIMP", "flatpak", "org.gimp.GIMP")
        self.assertIn("flatpak update", rec["update_command"])
        self.assertIn("flatpak uninstall", rec["uninstall_command"])

    def test_brew_commands(self):
        rec = self._install_with_pm("Fish", "brew", "fish")
        self.assertIn("brew upgrade", rec["update_command"])
        self.assertIn("brew uninstall", rec["uninstall_command"])

    def test_winget_commands(self):
        rec = self._install_with_pm("7zip", "winget", "7zip.7zip")
        self.assertIn("winget upgrade", rec["update_command"])
        self.assertIn("winget uninstall", rec["uninstall_command"])
        self.assertIn("--exact", rec["update_command"])

    def test_npm_commands(self):
        rec = self._install_with_pm("TypeScript", "npm", "typescript")
        self.assertIn("npm install -g", rec["update_command"])
        self.assertIn("typescript@latest", rec["update_command"])
        self.assertIn("npm uninstall -g", rec["uninstall_command"])

    def test_pip_commands(self):
        rec = self._install_with_pm("Requests", "pip", "requests")
        self.assertIn("pip install --upgrade", rec["update_command"])
        self.assertIn("requests", rec["update_command"])
        self.assertIn("pip uninstall -y", rec["uninstall_command"])

    def test_cargo_commands(self):
        rec = self._install_with_pm("Ripgrep", "cargo", "ripgrep")
        self.assertIn("cargo install", rec["update_command"])
        self.assertIn("cargo uninstall", rec["uninstall_command"])

    def test_unknown_pm_falls_back_gracefully(self):
        rec = self.mgr.install_tool({
            "name": "MyTool",
            "package_manager": "unknown-pm",
            "install_command": "custom_installer install mytool",
        })
        # Should not raise; should produce some command
        self.assertIsInstance(rec["update_command"], str)
        self.assertIsInstance(rec["uninstall_command"], str)


class TestPackageNameExtraction(unittest.TestCase):
    """Verify _extract_package_name logic for various tool_info shapes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "test_store.json"
        self.mgr = DevToolsManager(store_path=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_package_name_used_first(self):
        rec = self.mgr.install_tool({
            "name": "Visual Studio Code",
            "package_name": "code",
            "package_manager": "apt",
            "install_command": "apt install code",
        })
        self.assertIn("code", rec["update_command"])

    def test_name_used_as_fallback(self):
        rec = self.mgr.install_tool({
            "name": "Neovim",
            "package_manager": "apt",
            "install_command": "apt install neovim",
        })
        self.assertIn("neovim", rec["update_command"])

    def test_spaces_in_name_become_dashes(self):
        rec = self.mgr.install_tool({
            "name": "Google Chrome",
            "package_manager": "apt",
            "install_command": "apt install google-chrome",
        })
        # The package name should have dashes not spaces
        self.assertTrue(rec["update_command"].endswith("google-chrome"))


class TestLegacyListFormatMigration(unittest.TestCase):
    """Test that stores saved in old list format are loaded correctly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "legacy_store.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_list_format_migrated(self):
        # Simulate the old list-of-dicts format
        legacy_data = [
            {"app_id": "git", "name": "Git", "update_command": "apt update", "uninstall_command": "apt remove git"},
            {"app_id": "curl", "name": "Curl", "update_command": "apt update", "uninstall_command": "apt remove curl"},
        ]
        self.store.write_text(json.dumps(legacy_data), encoding="utf-8")

        mgr = DevToolsManager(store_path=self.store)
        apps = mgr.list_managed_apps()
        self.assertEqual(len(apps), 2)
        ids = {a["app_id"] for a in apps}
        self.assertIn("git", ids)
        self.assertIn("curl", ids)

    def test_invalid_store_starts_fresh(self):
        self.store.write_text("THIS IS NOT VALID JSON!!!!", encoding="utf-8")
        mgr = DevToolsManager(store_path=self.store)
        self.assertEqual(mgr.list_managed_apps(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
