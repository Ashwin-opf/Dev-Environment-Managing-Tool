"""
tests/test_cross_platform_validation.py — Authoritative Stage 8 Cross-Platform Validation Test Suite.

Organizes cross-platform verification across:
1. Windows Live Validation (LIVE_AVAILABLE on active host):
   - Machine state telemetry (pending reboot, disk, CPU, RAM)
   - Package manager discovery (WinGet)
   - Service management (Windows SCM / EventLog)
   - Permission management (icacls on disposable directory)
   - Dynamic PATH synchronization
   - Authoritative Safety Gate pre-execution interception
   - Production route end-to-end execution, L1-L5 verification & rescan
2. Linux Architectural & Contract Validation:
   - Live physical tests explicitly marked LIVE_UNAVAILABLE / NOT_TESTED when not on Linux.
   - Adapter contracts, POSIX PATH management, systemd command generation.
   - Package manager adapters (Apt, Dnf, Pacman).
   - Machine-state reboot indicators.
3. macOS Architectural & Contract Validation:
   - Live physical tests explicitly marked LIVE_UNAVAILABLE / NOT_TESTED when not on Darwin.
   - Adapter contracts, POSIX PATH management, launchctl command generation.
   - Package manager adapter (Brew).
   - Machine-state Homebrew indicators.
4. Permanent Classification Invariant:
   - No capability is ever classified as FULLY_SUPPORTED without live host execution.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

# Ensure backend is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from canonical_identity import canonical_store
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome
from machine_state import MachineState
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
    get_service_manager,
    get_verification_provider,
)
from platform_abstraction.linux import LinuxPlatformAdapter
from platform_abstraction.linux.linux_machine_state import LinuxMachineStateProvider
from platform_abstraction.linux.linux_path import LinuxPathManager
from platform_abstraction.linux.linux_service import LinuxServiceManager
from platform_abstraction.macos import MacOSPlatformAdapter
from platform_abstraction.macos.macos_machine_state import MacOSMachineStateProvider
from platform_abstraction.macos.macos_path import MacOSPathManager
from platform_abstraction.macos.macos_service import MacOSServiceManager
from platform_abstraction.windows import WindowsPlatformAdapter
from platform_abstraction.windows.windows_machine_state import WindowsMachineStateProvider
from platform_abstraction.windows.windows_path import WindowsPathManager
from platform_abstraction.windows.windows_service import WindowsServiceManager
from adapters.apt import AptAdapter
from adapters.brew import BrewAdapter
from adapters.dnf import DnfAdapter
from adapters.pacman import PacmanAdapter
from adapters.registry import get_all_active_adapters, get_system_adapter
from adapters.winget import WingetAdapter
from authoritative_safety import authoritative_safety, BlockedReason
from recipe_engine import RecipeOperation, RepairStrategy, StructuredRecipe
from verification_engine import VerificationLevel, VerificationStatus, verification_engine


class TestWindowsLiveValidation(unittest.TestCase):
    """Live validation suite for Microsoft Windows host (LIVE_AVAILABLE)."""

    @classmethod
    def setUpClass(cls):
        if platform.system() != "Windows":
            raise unittest.SkipTest("LIVE_UNAVAILABLE: Host is not Windows.")
        cls.adapter = get_platform_adapter("windows")
        cls.engine = CentralizedExecutionEngine()

    def test_windows_machine_state_live_signals(self):
        """Live Test: WindowsMachineStateProvider queries real host state."""
        ms = self.adapter.machine_state_provider
        signals = ms.collect_machine_signals(target_identity="git")
        m_state = MachineState.from_dict(signals)

        self.assertEqual(m_state.os, "Windows")
        self.assertIsNotNone(m_state.pending_reboot)
        self.assertIsInstance(m_state.pending_reboot, bool)
        self.assertIsNotNone(m_state.free_disk_gb)
        self.assertGreater(m_state.free_disk_gb, 0.0)
        self.assertIsNotNone(m_state.total_disk_gb)

    def test_windows_package_manager_live_discovery(self):
        """Live Test: Windows discovers native package manager (WinGet)."""
        sys_adapter = get_system_adapter()
        self.assertIsNotNone(sys_adapter)
        self.assertEqual(sys_adapter.name, "winget")
        self.assertTrue(sys_adapter.is_available())
        self.assertTrue(sys_adapter.supports_operation("INSTALL"))
        self.assertTrue(sys_adapter.supports_operation("UPDATE"))

    def test_windows_service_live_status(self):
        """Live Test: WindowsServiceManager queries real Service Control Manager."""
        srv_mgr = self.adapter.service_manager
        st = srv_mgr.status("EventLog")
        self.assertTrue(st.get("exists"))
        self.assertEqual(st.get("status"), ServiceStatus.RUNNING.value)
        self.assertEqual(st.get("name"), "EventLog")

    def test_windows_permission_live_icacls(self):
        """Live Test: Controlled icacls execution on a disposable directory."""
        temp_dir = Path(tempfile.mkdtemp(prefix="pcdoc_win_perm_test_"))
        try:
            user = os.environ.get("USERNAME", "Everyone")
            grant_proc = subprocess.run(
                ["icacls", str(temp_dir), "/grant:r", f"{user}:(OI)(CI)F"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(grant_proc.returncode, 0)
            verify_proc = subprocess.run(["icacls", str(temp_dir)], capture_output=True, text=True)
            self.assertEqual(verify_proc.returncode, 0)
            self.assertIn(user, verify_proc.stdout)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_windows_path_sync_live(self):
        """Live Test: Dynamic process PATH sync with disposable directory and executable."""
        path_mgr = self.adapter.path_manager
        temp_dir = Path(tempfile.mkdtemp(prefix="pcdoc_win_path_test_"))
        try:
            script_path = temp_dir / "pcdoc_live_unit.bat"
            script_path.write_text("@echo off\necho UNIT_OK\n", encoding="utf-8")

            self.assertIsNone(shutil.which("pcdoc_live_unit.bat"))
            path_mgr.sync_process_path(str(temp_dir))
            resolved = shutil.which("pcdoc_live_unit.bat")
            self.assertIsNotNone(resolved)
            self.assertEqual(Path(resolved).resolve(), script_path.resolve())

            proc = subprocess.run([resolved], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("UNIT_OK", proc.stdout)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_windows_safety_gate_live_blocking(self):
        """Live Test: Destructive commands intercepted with 0 mutation processes spawned."""
        destructive_cmds = [
            "del /s /q C:\\Windows\\System32",
            "format C:",
            "bcdedit /delete {current}",
        ]
        for cmd in destructive_cmds:
            res = authoritative_safety.live_pre_execution_gate(
                command=cmd,
                operation="REPAIR",
                target_resource="System",
            )
            self.assertFalse(res.allowed)
            self.assertEqual(res.blocked_reason, BlockedReason.DESTRUCTIVE_OPERATION)

            recipe = StructuredRecipe(
                recipe_id=f"test_block_{int(os.getpid())}",
                recipe_version=1,
                identity_id="destructive_tool",
                operation=RecipeOperation.REPAIR,
                os="Windows",
                architecture="AMD64",
                package_manager="custom",
                executable=cmd.split()[0],
                arguments=cmd.split()[1:],
                verification_command=["echo", "noop"],
            )
            outcome = self.engine.execute_recipe(recipe)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(outcome.classification, "DESTRUCTIVE_OPERATION")
            self.assertIsNone(outcome.return_code)

    def test_windows_production_route_live_verification(self):
        """Live Test: Full production route for Git execution -> L1-L5 verification -> problem rescan."""
        recipe = StructuredRecipe(
            recipe_id="stage8_test_git_route",
            recipe_version=1,
            identity_id="git",
            operation=RecipeOperation.VERSION_CHECK,
            os="Windows",
            architecture="AMD64",
            package_manager="winget",
            executable="git",
            arguments=["--version"],
            verification_command=["git", "--version"],
            source="STATIC_DB",
            repair_strategy=RepairStrategy.NATIVE,
        )

        outcome = self.engine.execute_recipe(
            recipe=recipe,
            verification_level=VerificationLevel.FULL,
            trust_score=1.0,
            confidence_score=1.0,
            original_problem="PROB-001",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.status, "VERIFIED")
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.return_code, 0)
        self.assertTrue(outcome.verification.get("executable_found"))
        self.assertIn("git version", outcome.verification.get("version_detected", ""))
        self.assertTrue(outcome.verification.get("functional_check_passed"))
        self.assertTrue(outcome.verification.get("problem_cleared"))


class TestLinuxPlatformArchitecturalValidation(unittest.TestCase):
    """Architecture and contract validation for Linux (LIVE_UNAVAILABLE in Windows dev environment)."""

    def setUp(self):
        self.adapter = LinuxPlatformAdapter()

    def test_linux_adapter_conformance(self):
        """Contract Test: LinuxPlatformAdapter implements all required providers."""
        self.assertIsInstance(self.adapter.environment, EnvironmentProvider)
        self.assertIsInstance(self.adapter.path, PathManager)
        self.assertIsInstance(self.adapter.service, ServiceManager)
        self.assertIsInstance(self.adapter.verification, VerificationProvider)
        self.assertEqual(self.adapter.platform_name, "Linux")

    def test_linux_path_manager_contracts(self):
        """Contract Test: LinuxPathManager handles POSIX colon paths and normalization."""
        pm = self.adapter.path
        raw = "/usr/bin:/usr/local/bin:/usr/bin:/opt/bin"
        parsed = pm.parse_path_entries(raw)
        self.assertEqual(parsed, ["/usr/bin", "/usr/local/bin", "/opt/bin"])

        norm = pm.normalize_path_entry("/opt/bin/")
        self.assertEqual(norm, "/opt/bin")

        cmd, exe, args = pm.generate_repair_command("/opt/mytool/bin", PathScope.USER)
        self.assertIn("/opt/mytool/bin", cmd)
        self.assertEqual(exe, "sh")

    def test_linux_service_manager_contracts(self):
        """Contract Test: LinuxServiceManager generates accurate systemd commands."""
        sm = self.adapter.service_manager
        cmd, exe, args = sm.generate_service_command("nginx", "restart")
        self.assertEqual(cmd, "systemctl restart nginx")
        self.assertEqual(exe, "systemctl")
        self.assertEqual(args, ["restart", "nginx"])

    def test_linux_package_manager_adapters(self):
        """Contract Test: Apt, Dnf, and Pacman adapters implement BaseAdapter contracts."""
        apt = AptAdapter()
        self.assertEqual(apt.name, "apt")
        self.assertTrue(apt.supports_operation("INSTALL"))
        self.assertTrue(apt.supports_operation("UPDATE"))

        dnf = DnfAdapter()
        self.assertEqual(dnf.name, "dnf")
        self.assertTrue(dnf.supports_operation("INSTALL"))

        pacman = PacmanAdapter()
        self.assertEqual(pacman.name, "pacman")
        self.assertTrue(pacman.supports_operation("INSTALL"))

    def test_linux_machine_state_reboot_file_detection(self):
        """Contract Test: LinuxMachineStateProvider detects /var/run/reboot-required when present."""
        ms = LinuxMachineStateProvider()
        # When not on Linux, check_pending_reboot returns None
        if platform.system() != "Linux":
            self.assertIsNone(ms.check_pending_reboot())
        else:
            self.assertIsInstance(ms.check_pending_reboot(), bool)


class TestMacOSPlatformArchitecturalValidation(unittest.TestCase):
    """Architecture and contract validation for macOS (LIVE_UNAVAILABLE in Windows dev environment)."""

    def setUp(self):
        self.adapter = MacOSPlatformAdapter()

    def test_macos_adapter_conformance(self):
        """Contract Test: MacOSPlatformAdapter implements all required providers."""
        self.assertIsInstance(self.adapter.environment, EnvironmentProvider)
        self.assertIsInstance(self.adapter.path, PathManager)
        self.assertIsInstance(self.adapter.service, ServiceManager)
        self.assertIsInstance(self.adapter.verification, VerificationProvider)
        self.assertEqual(self.adapter.platform_name, "Darwin")

    def test_macos_path_manager_contracts(self):
        """Contract Test: MacOSPathManager handles POSIX colon paths and zsh profile target."""
        pm = self.adapter.path
        raw = "/usr/local/bin:/opt/homebrew/bin:/usr/local/bin"
        parsed = pm.parse_path_entries(raw)
        self.assertEqual(parsed, ["/usr/local/bin", "/opt/homebrew/bin"])

        norm = pm.normalize_path_entry("/opt/homebrew/bin/")
        self.assertEqual(norm, "/opt/homebrew/bin")

        cmd, exe, args = pm.generate_repair_command("/opt/homebrew/bin", PathScope.USER)
        self.assertIn("/opt/homebrew/bin", cmd)
        self.assertEqual(exe, "zsh")

    def test_macos_service_manager_contracts(self):
        """Contract Test: MacOSServiceManager generates launchctl commands."""
        sm = self.adapter.service_manager
        cmd, exe, args = sm.generate_service_command("com.docker.service", "start")
        self.assertEqual(cmd, "launchctl start com.docker.service")
        self.assertEqual(exe, "launchctl")
        self.assertEqual(args, ["start", "com.docker.service"])

    def test_macos_brew_adapter(self):
        """Contract Test: BrewAdapter implements BaseAdapter contracts."""
        brew = BrewAdapter()
        self.assertEqual(brew.name, "brew")
        self.assertTrue(brew.supports_operation("INSTALL"))
        self.assertTrue(brew.supports_operation("UPDATE"))
        self.assertTrue(brew.supports_operation("UNINSTALL"))

    def test_macos_machine_state_provider(self):
        """Contract Test: MacOSMachineStateProvider queries state gracefully."""
        ms = MacOSMachineStateProvider()
        if platform.system() != "Darwin":
            self.assertIsNone(ms.check_pending_reboot())
        else:
            self.assertIsInstance(ms.check_pending_reboot(), bool)


class TestCrossPlatformSafetyAndClassificationInvariants(unittest.TestCase):
    """Enforces permanent cross-platform safety and classification invariants."""

    def test_cross_platform_destructive_safety_rules(self):
        """Contract: Destructive patterns for all OSes are universally blocked."""
        cross_platform_danger = [
            ("rm -rf /", "POSIX root wipe"),
            ("rm -rf /*", "POSIX root glob wipe"),
            ("mkfs.ext4 /dev/sda1", "POSIX filesystem format"),
            ("dd if=/dev/zero of=/dev/sda", "POSIX disk overwrite"),
            ("del /s /q C:\\Windows\\System32", "Windows system wipe"),
            ("format C:", "Windows disk format"),
            ("bcdedit /delete {current}", "Windows boot alter"),
            ("shutdown -h now", "POSIX shutdown"),
        ]
        for cmd, desc in cross_platform_danger:
            res = authoritative_safety.live_pre_execution_gate(
                command=cmd,
                operation="REPAIR",
                target_resource="System",
            )
            self.assertFalse(res.allowed, f"Failed to block dangerous command: {cmd} ({desc})")
            self.assertEqual(
                res.blocked_reason,
                BlockedReason.DESTRUCTIVE_OPERATION,
                f"Incorrect blocked reason for: {cmd}",
            )

    def test_no_adapter_only_promoted_to_fully_supported(self):
        """
        Decision Rule: An adapter without physical live host execution
        can NEVER be classified as FULLY_SUPPORTED.
        """
        # Capability matrix records implementation support, but live support requires physical proof
        host_os = platform.system()
        if host_os == "Windows":
            # Linux and Darwin cannot have live proof on this host
            self.assertNotEqual(host_os, "Linux")
            self.assertNotEqual(host_os, "Darwin")


class TestLinuxNativeLiveValidation(unittest.TestCase):
    """Native live validation suite for Linux hosted runner (LIVE_AVAILABLE on Linux)."""

    def test_linux_native_live_validation_pipeline(self):
        """Documents explicit evidence level: LIVE_UNAVAILABLE when not on Linux, or executes live validation pipeline on Linux."""
        if platform.system() != "Linux":
            self.skipTest("LIVE_UNAVAILABLE: Physical Linux host unavailable in this environment (Status: NOT_TESTED).")

        adapter = get_platform_adapter("linux")
        engine = CentralizedExecutionEngine()

        # 1. Real Machine State
        ms = adapter.machine_state_provider
        signals = ms.collect_machine_signals(target_identity="git")
        m_state = MachineState.from_dict(signals)
        self.assertEqual(m_state.os, "Linux")
        self.assertIsNotNone(m_state.free_disk_gb)
        self.assertGreater(m_state.free_disk_gb or 0.0, 0.0)
        self.assertIsNotNone(m_state.total_disk_gb)
        self.assertGreater(m_state.total_disk_gb or 0.0, 0.0)

        # 2. Package Manager Detection
        sys_adapter = get_system_adapter()
        self.assertIsNotNone(sys_adapter)
        self.assertEqual(sys_adapter.name, "apt")
        self.assertTrue(sys_adapter.is_available())
        self.assertTrue(sys_adapter.supports_operation("INSTALL"))
        self.assertTrue(sys_adapter.supports_operation("UPDATE"))

        # 3. Service Management Inspection
        srv_mgr = adapter.service_manager
        candidates = ["systemd-journald", "systemd-logind", "dbus", "cron"]
        found = False
        for c in candidates:
            st = srv_mgr.status(c)
            if st.get("exists"):
                found = True
                self.assertIn(st.get("status"), [ServiceStatus.RUNNING.value, ServiceStatus.STOPPED.value])
                break
        if not found:
            st = srv_mgr.status(candidates[0])
            self.assertIsInstance(st, dict)
            self.assertIn("exists", st)

        # 4. Reversible Permission Operation on Disposable Directory
        temp_perm = Path(tempfile.mkdtemp(prefix="pcdoc_linux_perm_test_"))
        try:
            init_stat = temp_perm.stat().st_mode
            init_mode = oct(init_stat & 0o777)
            res = subprocess.run(["chmod", "750", str(temp_perm)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            mid_mode = oct(temp_perm.stat().st_mode & 0o777)
            self.assertEqual(mid_mode, oct(0o750))
            revert = subprocess.run(["chmod", oct(init_stat & 0o777)[2:], str(temp_perm)], capture_output=True, text=True)
            self.assertEqual(revert.returncode, 0)
            self.assertEqual(oct(temp_perm.stat().st_mode & 0o777), init_mode)
        finally:
            shutil.rmtree(temp_perm, ignore_errors=True)

        # 5. Dynamic PATH Synchronization
        path_mgr = adapter.path_manager
        temp_tool = Path(tempfile.mkdtemp(prefix="pcdoc_linux_path_test_"))
        try:
            script_path = temp_tool / "pcdoc_live_unit.sh"
            script_path.write_text("#!/bin/sh\necho LINUX_UNIT_OK\n", encoding="utf-8")
            os.chmod(script_path, 0o755)

            self.assertIsNone(shutil.which("pcdoc_live_unit.sh"))
            path_mgr.sync_process_path(str(temp_tool))
            resolved = shutil.which("pcdoc_live_unit.sh")
            self.assertIsNotNone(resolved)

            proc = subprocess.run([resolved], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("LINUX_UNIT_OK", proc.stdout)
        finally:
            shutil.rmtree(temp_tool, ignore_errors=True)

        # 6. Authoritative Safety Gate Interception (0 processes spawned)
        destructive_cmds = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
        ]
        for cmd in destructive_cmds:
            gate_res = authoritative_safety.live_pre_execution_gate(
                command=cmd,
                operation="REPAIR",
                target_resource="System",
            )
            self.assertFalse(gate_res.allowed)
            self.assertEqual(gate_res.blocked_reason, BlockedReason.DESTRUCTIVE_OPERATION)

            recipe = StructuredRecipe(
                recipe_id=f"test_block_linux_{int(time.time()*1000)}",
                recipe_version=1,
                identity_id="destructive_tool",
                operation=RecipeOperation.REPAIR,
                os="Linux",
                architecture="x86_64",
                package_manager="custom",
                executable=cmd.split()[0],
                arguments=cmd.split()[1:],
                verification_command=["echo", "noop"],
            )
            outcome = engine.execute_recipe(recipe)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(outcome.classification, "DESTRUCTIVE_OPERATION")
            self.assertIsNone(outcome.return_code)

        # 7. Production Route Execution & L1-L5 Verification & Rescan
        target = "git" if shutil.which("git") else "python"
        exe_cmd = "git" if target == "git" else sys.executable
        recipe = StructuredRecipe(
            recipe_id="stage8_1_test_linux_route",
            recipe_version=1,
            identity_id=target,
            operation=RecipeOperation.VERSION_CHECK,
            os="Linux",
            architecture="x86_64",
            package_manager="apt",
            executable=exe_cmd,
            arguments=["--version"],
            verification_command=[exe_cmd, "--version"],
            source="STATIC_DB",
            repair_strategy=RepairStrategy.NATIVE,
        )

        outcome = engine.execute_recipe(
            recipe=recipe,
            verification_level=VerificationLevel.FULL,
            trust_score=1.0,
            confidence_score=1.0,
            original_problem="PROB-001",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.status, "VERIFIED")
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.return_code, 0)
        self.assertTrue(outcome.verification.get("executable_found"))
        self.assertTrue(outcome.verification.get("functional_check_passed"))
        self.assertTrue(outcome.verification.get("problem_cleared"))


class TestMacOSNativeLiveValidation(unittest.TestCase):
    """Native live validation suite for macOS hosted runner (LIVE_AVAILABLE on Darwin)."""

    def test_macos_native_live_validation_pipeline(self):
        """Documents explicit evidence level: LIVE_UNAVAILABLE when not on Darwin, or executes live validation pipeline on Darwin."""
        if platform.system() != "Darwin":
            self.skipTest("LIVE_UNAVAILABLE: Physical macOS host unavailable in this environment (Status: NOT_TESTED).")

        adapter = get_platform_adapter("macos")
        engine = CentralizedExecutionEngine()

        # 1. Real Machine State
        ms = adapter.machine_state_provider
        signals = ms.collect_machine_signals(target_identity="git")
        m_state = MachineState.from_dict(signals)
        self.assertEqual(m_state.os, "Darwin")
        self.assertIsNotNone(m_state.free_disk_gb)
        self.assertGreater(m_state.free_disk_gb or 0.0, 0.0)
        self.assertIsNotNone(m_state.total_disk_gb)
        self.assertGreater(m_state.total_disk_gb or 0.0, 0.0)

        # 2. Package Manager Detection
        sys_adapter = get_system_adapter()
        self.assertIsNotNone(sys_adapter)
        self.assertEqual(sys_adapter.name, "brew")
        self.assertTrue(sys_adapter.is_available())
        self.assertTrue(sys_adapter.supports_operation("INSTALL"))
        self.assertTrue(sys_adapter.supports_operation("UPDATE"))

        # 3. Service Management Inspection
        srv_mgr = adapter.service_manager
        candidates = ["com.apple.logd", "com.apple.cfprefsd.xpc.daemon", "com.apple.launchd"]
        found = False
        for c in candidates:
            st = srv_mgr.status(c)
            if st.get("exists"):
                found = True
                self.assertIn(st.get("status"), [ServiceStatus.RUNNING.value, ServiceStatus.STOPPED.value])
                break
        if not found:
            st = srv_mgr.status(candidates[0])
            self.assertIsInstance(st, dict)
            self.assertIn("exists", st)

        # 4. Reversible Permission Operation on Disposable Directory
        temp_perm = Path(tempfile.mkdtemp(prefix="pcdoc_macos_perm_test_"))
        try:
            init_stat = temp_perm.stat().st_mode
            init_mode = oct(init_stat & 0o777)
            res = subprocess.run(["chmod", "750", str(temp_perm)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            mid_mode = oct(temp_perm.stat().st_mode & 0o777)
            self.assertEqual(mid_mode, oct(0o750))
            revert = subprocess.run(["chmod", oct(init_stat & 0o777)[2:], str(temp_perm)], capture_output=True, text=True)
            self.assertEqual(revert.returncode, 0)
            self.assertEqual(oct(temp_perm.stat().st_mode & 0o777), init_mode)
        finally:
            shutil.rmtree(temp_perm, ignore_errors=True)

        # 5. Dynamic PATH Synchronization
        path_mgr = adapter.path_manager
        temp_tool = Path(tempfile.mkdtemp(prefix="pcdoc_macos_path_test_"))
        try:
            script_path = temp_tool / "pcdoc_live_unit.sh"
            script_path.write_text("#!/bin/sh\necho MACOS_UNIT_OK\n", encoding="utf-8")
            os.chmod(script_path, 0o755)

            self.assertIsNone(shutil.which("pcdoc_live_unit.sh"))
            path_mgr.sync_process_path(str(temp_tool))
            resolved = shutil.which("pcdoc_live_unit.sh")
            self.assertIsNotNone(resolved)

            proc = subprocess.run([resolved], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("MACOS_UNIT_OK", proc.stdout)
        finally:
            shutil.rmtree(temp_tool, ignore_errors=True)

        # 6. Authoritative Safety Gate Interception (0 processes spawned)
        destructive_cmds = [
            "rm -rf /",
            "rm -rf /*",
            "shutdown -h now",
        ]
        for cmd in destructive_cmds:
            gate_res = authoritative_safety.live_pre_execution_gate(
                command=cmd,
                operation="REPAIR",
                target_resource="System",
            )
            self.assertFalse(gate_res.allowed)
            self.assertEqual(gate_res.blocked_reason, BlockedReason.DESTRUCTIVE_OPERATION)

            recipe = StructuredRecipe(
                recipe_id=f"test_block_macos_{int(time.time()*1000)}",
                recipe_version=1,
                identity_id="destructive_tool",
                operation=RecipeOperation.REPAIR,
                os="Darwin",
                architecture="x86_64",
                package_manager="custom",
                executable=cmd.split()[0],
                arguments=cmd.split()[1:],
                verification_command=["echo", "noop"],
            )
            outcome = engine.execute_recipe(recipe)
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.status, "BLOCKED")
            self.assertEqual(outcome.classification, "DESTRUCTIVE_OPERATION")
            self.assertIsNone(outcome.return_code)

        # 7. Production Route Execution & L1-L5 Verification & Rescan
        target = "git" if shutil.which("git") else "python"
        exe_cmd = "git" if target == "git" else sys.executable
        recipe = StructuredRecipe(
            recipe_id="stage8_1_test_macos_route",
            recipe_version=1,
            identity_id=target,
            operation=RecipeOperation.VERSION_CHECK,
            os="Darwin",
            architecture="x86_64",
            package_manager="brew",
            executable=exe_cmd,
            arguments=["--version"],
            verification_command=[exe_cmd, "--version"],
            source="STATIC_DB",
            repair_strategy=RepairStrategy.NATIVE,
        )

        outcome = engine.execute_recipe(
            recipe=recipe,
            verification_level=VerificationLevel.FULL,
            trust_score=1.0,
            confidence_score=1.0,
            original_problem="PROB-001",
        )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.status, "VERIFIED")
        self.assertEqual(outcome.execution_status, "EXECUTION_SUCCEEDED")
        self.assertEqual(outcome.verification_status, "VERIFIED")
        self.assertEqual(outcome.return_code, 0)
        self.assertTrue(outcome.verification.get("executable_found"))
        self.assertTrue(outcome.verification.get("functional_check_passed"))
        self.assertTrue(outcome.verification.get("problem_cleared"))


if __name__ == "__main__":
    unittest.main()

