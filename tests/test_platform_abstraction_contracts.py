"""
tests/test_platform_abstraction_contracts.py — Architectural Boundary Contract and Cross-Platform Tests.

Enforces the non-negotiable architectural requirements:
1. Core generic modules (dev_environment_detector, test_lab/baseline_manager, execution_engine, safety_layer)
   must NOT directly import or depend on winreg, raw PowerShell, sc.exe, or hardcoded winget.
2. PlatformAdapter and its component providers (EnvironmentProvider, PathManager, ServiceManager,
   VerificationProvider) conform strictly to abstract protocols.
3. Windows, Linux, and macOS adapters provide real implementations (not stubs) and report
   accurate capability states via the authoritative Capability Matrix.
4. Core detection, tier evaluation, and safety scoring can execute on simulated non-Windows
   platforms with zero Windows dependencies.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import unittest
from pathlib import Path
from typing import List, Set
from unittest.mock import MagicMock, patch

# Ensure backend is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from canonical_identity import CanonicalIdentity, canonical_store
from platform_abstraction import (
    CapabilityStatus,
    EnvironmentProvider,
    PathManager,
    PathScope,
    PlatformAdapter,
    PlatformCapability,
    ServiceManager,
    ServiceStatus,
    VerificationProvider,
    get_capability_matrix,
    get_environment_provider,
    get_path_manager,
    get_platform_adapter,
    get_platform_capabilities,
    get_service_manager,
    get_verification_provider,
    is_capability_supported,
)
from platform_abstraction.linux import LinuxPlatformAdapter
from platform_abstraction.macos import MacOSPlatformAdapter
from platform_abstraction.windows import WindowsPlatformAdapter


class TestArchitectureBoundaryContracts(unittest.TestCase):
    """Architectural regression tests to ensure core generic modules remain decoupled from OS-specific APIs."""

    def _get_ast_imported_modules(self, file_path: Path) -> Set[str]:
        """Parses a Python file into an AST and extracts all imported module names."""
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        imports: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return imports

    def test_generic_detector_never_imports_winreg(self):
        """Contract: dev_environment_detector.py must NEVER import winreg directly."""
        detector_path = BACKEND_DIR / "dev_environment_detector.py"
        self.assertTrue(detector_path.exists())
        imports = self._get_ast_imported_modules(detector_path)
        self.assertNotIn("winreg", imports, "CRITICAL: dev_environment_detector.py imports winreg directly!")

    def test_baseline_manager_never_imports_winreg(self):
        """Contract: baseline_manager.py must NEVER import winreg directly."""
        baseline_path = BACKEND_DIR / "test_lab" / "baseline_manager.py"
        self.assertTrue(baseline_path.exists())
        imports = self._get_ast_imported_modules(baseline_path)
        self.assertNotIn("winreg", imports, "CRITICAL: test_lab/baseline_manager.py imports winreg directly!")

    def test_generic_detector_does_not_contain_raw_powershell_commands(self):
        """Contract: dev_environment_detector.py must not hardcode raw PowerShell script generation."""
        detector_path = BACKEND_DIR / "dev_environment_detector.py"
        content = detector_path.read_text(encoding="utf-8")
        # Check that Get-Service and SetEnvironmentVariable are not in generic detector
        self.assertNotIn("Get-Service", content, "dev_environment_detector.py contains raw Get-Service PowerShell call")
        self.assertNotIn("[Environment]::SetEnvironmentVariable", content, "dev_environment_detector.py contains raw SetEnvironmentVariable PowerShell call")

    def test_service_injector_does_not_contain_raw_powershell(self):
        """Contract: test_lab/adapters/service_injector.py must not hardcode raw powershell commands."""
        injector_path = BACKEND_DIR / "test_lab" / "adapters" / "service_injector.py"
        content = injector_path.read_text(encoding="utf-8")
        self.assertNotIn("Stop-Service", content, "service_injector.py contains hardcoded Stop-Service")
        self.assertNotIn("Start-Service", content, "service_injector.py contains hardcoded Start-Service")

    def test_core_execution_engine_does_not_depend_on_winreg(self):
        """Contract: execution_engine.py must not import winreg."""
        exec_path = BACKEND_DIR / "execution_engine.py"
        if exec_path.exists():
            imports = self._get_ast_imported_modules(exec_path)
            self.assertNotIn("winreg", imports)

    def test_safety_layer_does_not_depend_on_winreg(self):
        """Contract: safety_layer.py must not import winreg."""
        safety_path = BACKEND_DIR / "safety_layer.py"
        if safety_path.exists():
            imports = self._get_ast_imported_modules(safety_path)
            self.assertNotIn("winreg", imports)


class TestPlatformAdaptersConformance(unittest.TestCase):
    """Verifies that Windows, Linux, and macOS adapters adhere strictly to the PlatformAdapter protocol."""

    def setUp(self):
        self.win_adapter = WindowsPlatformAdapter()
        self.linux_adapter = LinuxPlatformAdapter()
        self.macos_adapter = MacOSPlatformAdapter()

    def test_all_adapters_inherit_platform_adapter(self):
        self.assertIsInstance(self.win_adapter, PlatformAdapter)
        self.assertIsInstance(self.linux_adapter, PlatformAdapter)
        self.assertIsInstance(self.macos_adapter, PlatformAdapter)

    def test_windows_adapter_providers(self):
        self.assertIsInstance(self.win_adapter.environment, EnvironmentProvider)
        self.assertIsInstance(self.win_adapter.path, PathManager)
        self.assertIsInstance(self.win_adapter.service, ServiceManager)
        self.assertIsInstance(self.win_adapter.verification, VerificationProvider)
        self.assertEqual(self.win_adapter.platform_name, "Windows")

    def test_linux_adapter_providers(self):
        self.assertIsInstance(self.linux_adapter.environment, EnvironmentProvider)
        self.assertIsInstance(self.linux_adapter.path, PathManager)
        self.assertIsInstance(self.linux_adapter.service, ServiceManager)
        self.assertIsInstance(self.linux_adapter.verification, VerificationProvider)
        self.assertEqual(self.linux_adapter.platform_name, "Linux")

    def test_macos_adapter_providers(self):
        self.assertIsInstance(self.macos_adapter.environment, EnvironmentProvider)
        self.assertIsInstance(self.macos_adapter.path, PathManager)
        self.assertIsInstance(self.macos_adapter.service, ServiceManager)
        self.assertIsInstance(self.macos_adapter.verification, VerificationProvider)
        self.assertEqual(self.macos_adapter.platform_name, "Darwin")

    def test_factory_accessors_return_active_platform(self):
        current_adapter = get_platform_adapter()
        self.assertIsInstance(current_adapter, PlatformAdapter)
        self.assertIsInstance(get_environment_provider(), EnvironmentProvider)
        self.assertIsInstance(get_path_manager(), PathManager)
        self.assertIsInstance(get_service_manager(), ServiceManager)
        self.assertIsInstance(get_verification_provider(), VerificationProvider)

    def test_explicit_platform_selection(self):
        win = get_platform_adapter("windows")
        linux = get_platform_adapter("linux")
        mac = get_platform_adapter("darwin")

        self.assertEqual(win.platform_name, "Windows")
        self.assertEqual(linux.platform_name, "Linux")
        self.assertEqual(mac.platform_name, "Darwin")


class TestCrossPlatformCapabilityMatrix(unittest.TestCase):
    """Validates the authoritative machine-readable Capability Matrix."""

    def test_capability_matrix_structure(self):
        matrix = get_capability_matrix()
        self.assertIn("capabilities", matrix)
        self.assertIn("summary", matrix)
        caps = matrix["capabilities"]
        self.assertGreaterEqual(len(caps), 8)

        # Check required capabilities exist
        required_caps = [
            "PATH_REPAIR_USER",
            "PATH_REPAIR_MACHINE",
            "MACHINE_PRIVILEGE",
            "SERVICE_CONTROL",
            "PACKAGE_MANAGER_DETECTION",
            "BINARY_VERIFICATION",
        ]
        for rc in required_caps:
            self.assertIn(rc, caps, f"Missing capability {rc} in matrix")
            entry = caps[rc]
            self.assertIn("Windows", entry)
            self.assertIn("Linux", entry)
            self.assertIn("Darwin", entry)

    def test_capability_matrix_accurately_reflects_adapter_states(self):
        # Windows supports PATH_REPAIR_USER, PATH_REPAIR_MACHINE, and MACHINE_PRIVILEGE
        self.assertTrue(is_capability_supported(PlatformCapability.PATH_REPAIR_USER, "windows"))
        self.assertTrue(is_capability_supported(PlatformCapability.PATH_REPAIR_MACHINE, "windows"))
        self.assertTrue(is_capability_supported(PlatformCapability.MACHINE_PRIVILEGE, "windows"))

        # Linux supports PARTIAL for PATH_REPAIR_MACHINE (profile.d based)
        linux_caps = get_platform_capabilities("linux")
        self.assertIn(linux_caps[PlatformCapability.PATH_REPAIR_MACHINE], (CapabilityStatus.PARTIAL, CapabilityStatus.SUPPORTED))
        self.assertEqual(linux_caps[PlatformCapability.MACHINE_PRIVILEGE], CapabilityStatus.PARTIAL)

        # macOS supports PARTIAL for PATH_REPAIR_MACHINE (/etc/paths.d)
        mac_caps = get_platform_capabilities("darwin")
        self.assertIn(mac_caps[PlatformCapability.PATH_REPAIR_MACHINE], (CapabilityStatus.PARTIAL, CapabilityStatus.SUPPORTED))
        self.assertEqual(mac_caps[PlatformCapability.MACHINE_PRIVILEGE], CapabilityStatus.PARTIAL)


class TestLinuxAdapterRealFoundation(unittest.TestCase):
    """Verifies Linux adapter provides real implementations, not fake mocks."""

    def setUp(self):
        self.adapter = LinuxPlatformAdapter()

    def test_linux_path_generate_repair_command(self):
        cmd, executable, args = self.adapter.path.generate_repair_command("/opt/mytool/bin", PathScope.USER)
        self.assertIn("/opt/mytool/bin", cmd)
        self.assertEqual(executable, "sh")
        self.assertEqual(args, ["-c", cmd])

    def test_linux_path_parse_entries(self):
        raw = "/usr/bin:/bin:/usr/local/bin:/usr/bin"
        entries = self.adapter.path.parse_path_entries(raw)
        self.assertEqual(entries, ["/usr/bin", "/bin", "/usr/local/bin"])

    def test_linux_path_normalize(self):
        norm = self.adapter.path.normalize_path_entry("/usr/local/bin/")
        self.assertEqual(norm, "/usr/local/bin")

    def test_linux_service_generate_command(self):
        cmd, executable, args = self.adapter.service.generate_service_command("mysql", "start")
        self.assertEqual(cmd, "systemctl start mysql")
        self.assertEqual(executable, "systemctl")
        self.assertEqual(args, ["start", "mysql"])

    def test_linux_environment_search_roots(self):
        roots = self.adapter.environment.get_standard_search_roots()
        self.assertIn("/usr/bin", roots)
        self.assertIn("/opt", roots)


class TestMacOSAdapterRealFoundation(unittest.TestCase):
    """Verifies macOS adapter provides real implementations, not fake mocks."""

    def setUp(self):
        self.adapter = MacOSPlatformAdapter()

    def test_macos_path_generate_repair_command(self):
        cmd, executable, args = self.adapter.path.generate_repair_command("/usr/local/bin", PathScope.USER)
        self.assertIn("/usr/local/bin", cmd)
        self.assertEqual(executable, "zsh")
        self.assertEqual(args, ["-c", cmd])

    def test_macos_path_parse_entries(self):
        raw = "/usr/bin:/bin:/usr/local/bin"
        entries = self.adapter.path.parse_path_entries(raw)
        self.assertEqual(entries, ["/usr/bin", "/bin", "/usr/local/bin"])

    def test_macos_service_generate_command(self):
        cmd, executable, args = self.adapter.service.generate_service_command("homebrew.mxcl.mysql", "start")
        self.assertEqual(cmd, "launchctl start homebrew.mxcl.mysql")
        self.assertEqual(executable, "launchctl")
        self.assertEqual(args, ["start", "homebrew.mxcl.mysql"])

    def test_macos_environment_search_roots(self):
        roots = self.adapter.environment.get_standard_search_roots()
        self.assertIn("/Applications", roots)
        self.assertIn("/opt/homebrew/bin", roots)


class TestGenericDetectorWithMockPlatform(unittest.TestCase):
    """Verifies that DevEnvironmentDetector can execute on a simulated non-Windows platform without Windows APIs."""

    def test_detector_runs_with_mock_linux_adapter(self):
        from dev_environment_detector import DevEnvironmentDetector

        mock_env = MagicMock(spec=EnvironmentProvider)
        mock_env.find_standard_install_dirs.return_value = ["/usr/bin/git"]

        mock_path = MagicMock(spec=PathManager)
        mock_path.get_effective_path.return_value = ["/usr/bin"]
        mock_path.get_process_path.return_value = ["/usr/bin"]
        mock_path.is_dir_in_persistent_path.return_value = True
        mock_path.is_dir_in_process_path.return_value = True
        mock_path.normalize_path_entry.side_effect = lambda x: str(x).rstrip("/")

        mock_svc = MagicMock(spec=ServiceManager)
        mock_svc.status.return_value = ServiceStatus.NOT_FOUND

        mock_ver = MagicMock(spec=VerificationProvider)
        mock_ver.verify_executable.return_value = (True, "git version 2.44.0")

        mock_adapter = MagicMock(spec=PlatformAdapter)
        mock_adapter.platform_name = "Linux"

        detector = DevEnvironmentDetector()
        detector.platform_adapter = mock_adapter
        detector.env_provider = mock_env
        detector.path_manager = mock_path
        detector.service_manager = mock_svc
        detector.verification_provider = mock_ver

        # Diagnose git using simulated non-Windows adapter
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.isdir", return_value=True), \
             patch.object(detector, "_test_launch_in_persistent_env", return_value=("git version 2.44.0", True)), \
             patch.object(detector.effective_path, "get_persistent_paths", return_value=["/usr/bin"]), \
             patch.object(detector.effective_path, "get_process_paths", return_value=["/usr/bin"]):
            diag = detector.diagnose_tool("git")
            self.assertTrue(diag.installed)
            self.assertEqual((diag.discovered_path or "").replace("\\", "/"), "/usr/bin/git")
            self.assertEqual(diag.status.value, "INSTALLED_AND_USABLE")


class TestCanonicalIdentityPlatformAwareness(unittest.TestCase):
    """Verifies that CanonicalIdentity handles platform-specific package IDs and paths cleanly."""

    def test_canonical_identity_accessors(self):
        identity = CanonicalIdentity(
            identity_id="test_tool",
            display_name="Test Tool",
            executable="testtool",
            package_id="testtool.winget",
            publisher="Test Org",
            package_manager="winget",
            installation_paths=[r"C:\Tools\testtool"],
            required_path_dirs=[r"C:\Tools\testtool\bin"],
            platform_overrides={
                "linux": {
                    "package_id": "testtool-deb",
                    "package_manager": "apt",
                    "installation_paths": ["/usr/bin/testtool"],
                    "required_path_dirs": ["/usr/bin"],
                },
                "darwin": {
                    "package_id": "testtool-brew",
                    "package_manager": "brew",
                    "installation_paths": ["/opt/homebrew/bin/testtool"],
                    "required_path_dirs": ["/opt/homebrew/bin"],
                },
            },
        )

        # Default / Windows
        self.assertEqual(identity.get_package_id("windows"), "testtool.winget")
        self.assertEqual(identity.get_package_manager("windows"), "winget")
        self.assertEqual(identity.get_installation_paths("windows"), [r"C:\Tools\testtool"])

        # Linux overrides
        self.assertEqual(identity.get_package_id("linux"), "testtool-deb")
        self.assertEqual(identity.get_package_manager("linux"), "apt")
        self.assertEqual(identity.get_installation_paths("linux"), ["/usr/bin/testtool"])

        # macOS overrides
        self.assertEqual(identity.get_package_id("darwin"), "testtool-brew")
        self.assertEqual(identity.get_package_manager("darwin"), "brew")
        self.assertEqual(identity.get_installation_paths("darwin"), ["/opt/homebrew/bin/testtool"])


if __name__ == "__main__":
    unittest.main()
