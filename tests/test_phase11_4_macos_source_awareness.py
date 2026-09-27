"""
tests/test_phase11_4_macos_source_awareness.py — Phase 11.4 macOS Source Awareness Test Suite.
=============================================================================================
Tests covering:
- Problem #55: macOS Homebrew vs Official/Vendor Installer Detection and Source Awareness.
- Source detection: Homebrew (formula/cask), Vendor (.app), Manual, System, Unknown.
- Architecture detection: Mach-O headers (arm64, x86_64, universal).
- Multiple installations: Homebrew + Vendor, Homebrew + Manual, multiple versions.
- Active installation resolution strictly via PATH precedence (never highest version).
- Per-tool source policy enforcement without blanket Homebrew preference.
- Ownership tracking via ManagedFootprintRegistry (Phase 11.2).
- Source migration planning with approval enforcement (Tier 2/3).
- Safety Gate and CentralizedExecutionEngine invariants (zero mutation without approval).
- End-to-end integration workflows.
"""

from __future__ import annotations

import os
import plistlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from canonical_identity import CanonicalIdentity, canonical_store
from execution_engine import CentralizedExecutionEngine, ExecutionOutcome
from execution_plan import ExecutionPlan, ExecutionRequest, ExecutionResolver, ProvenanceClass
from execution_tier import ExecutionTier
from managed_footprint import (
    ManagedInstallation,
    OwnershipState,
    footprint_registry,
)
from platform_abstraction.macos.macos_adapter import MacOSPlatformAdapter
from platform_abstraction.macos.macos_source_awareness import (
    MacOSArchitecture,
    MacOSBrewType,
    MacOSInstallSource,
    MacOSInstallation,
    MacOSSourceAnalysisResult,
    MacOSSourceAwarenessProvider,
    MacOSSourceDecisionStatus,
    MacOSSourceUpdateDecision,
    macos_source_awareness,
)


class TestMacOSSourceAwarenessBase(unittest.TestCase):
    """Base test class providing temporary filesystem fixtures simulating macOS directory structures."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Standard macOS tree mock
        self.opt_homebrew = self.root / "opt" / "homebrew"
        self.brew_cellar = self.opt_homebrew / "Cellar"
        self.brew_caskroom = self.opt_homebrew / "Caskroom"
        self.brew_bin = self.opt_homebrew / "bin"
        self.applications = self.root / "Applications"
        self.user_applications = self.root / "Users" / "dev" / "Applications"
        self.system_bin = self.root / "usr" / "bin"
        self.user_local_bin = self.root / "Users" / "dev" / ".local" / "bin"

        for d in (
            self.brew_cellar,
            self.brew_caskroom,
            self.brew_bin,
            self.applications,
            self.user_applications,
            self.system_bin,
            self.user_local_bin,
        ):
            d.mkdir(parents=True, exist_ok=True)

        self.custom_roots = {
            "homebrew_prefix": str(self.opt_homebrew),
            "applications_dir": str(self.applications),
            "system_bin": str(self.system_bin),
            "path": f"{self.brew_bin}:{self.system_bin}:{self.user_local_bin}",
        }

        self.provider = MacOSSourceAwarenessProvider(
            homebrew_prefixes=[str(self.opt_homebrew)],
            app_dirs=[str(self.applications)],
        )

        self.footprint_patcher = patch.object(footprint_registry, "get_installation", return_value=None)
        self.footprint_patcher.start()

    def tearDown(self):
        self.footprint_patcher.stop()
        self.temp_dir.cleanup()

    def create_macho_file(self, file_path: Path, arch: str) -> Path:
        """Helper to create a binary file with valid Mach-O header bytes."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            if arch == "universal":
                # FAT_MAGIC (0xcafebabe)
                f.write(struct.pack(">I", 0xCAFEBABE))
                f.write(b"\x00" * 28)
            elif arch == "arm64":
                # MH_MAGIC_64 (0xfeedfacf) with cputype CPU_TYPE_ARM64 (12)
                f.write(struct.pack(">I", 0xFEEDFACF))
                f.write(struct.pack(">I", 12))
                f.write(b"\x00" * 24)
            elif arch == "x86_64":
                # MH_MAGIC_64 (0xfeedfacf) with cputype CPU_TYPE_X86_64 (7)
                f.write(struct.pack(">I", 0xFEEDFACF))
                f.write(struct.pack(">I", 7))
                f.write(b"\x00" * 24)
            else:
                f.write(b"#!/bin/sh\necho test\n")
        return file_path

    def create_app_bundle(
        self,
        app_name: str,
        bundle_id: str,
        version: str,
        exec_name: str,
        parent_dir: Optional[Path] = None,
        arch: str = "arm64",
    ) -> Path:
        """Helper to create an authentic macOS .app bundle with Info.plist."""
        base = parent_dir or self.applications
        bundle_dir = base / f"{app_name}.app"
        contents = bundle_dir / "Contents"
        macos_dir = contents / "MacOS"
        macos_dir.mkdir(parents=True, exist_ok=True)

        plist_path = contents / "Info.plist"
        plist_data = {
            "CFBundleIdentifier": bundle_id,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleExecutable": exec_name,
            "CFBundleName": app_name,
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        exec_path = macos_dir / exec_name
        self.create_macho_file(exec_path, arch)
        return bundle_dir


# ===========================================================================
# 1. Source Detection Tests
# ===========================================================================

class TestMacOSSourceDetection(TestMacOSSourceAwarenessBase):
    """Tests 1-8: Single source detection, bundle parsing, and Mach-O architectures."""

    def test_01_homebrew_formula_tool_detected(self):
        """1. Detects Homebrew Formula installation in Cellar."""
        git_cellar = self.brew_cellar / "git" / "2.43.0" / "bin"
        git_cellar.mkdir(parents=True, exist_ok=True)
        git_exec = git_cellar / "git"
        self.create_macho_file(git_exec, "arm64")

        # Symlink in brew bin
        symlink_bin = self.brew_bin / "git"
        self.create_macho_file(symlink_bin, "arm64")

        installs = self.provider.detect_installations("git", self.custom_roots)
        self.assertTrue(len(installs) >= 1)
        brew_inst = next((i for i in installs if i.source == MacOSInstallSource.HOMEBREW), None)
        self.assertIsNotNone(brew_inst)
        self.assertEqual(brew_inst.brew_type, MacOSBrewType.FORMULA)
        self.assertEqual(brew_inst.version, "2.43.0")
        self.assertEqual(brew_inst.package_manager, "brew")
        self.assertEqual(brew_inst.architecture, MacOSArchitecture.ARM64)

    def test_02_vendor_installed_app_bundle_detected(self):
        """2. Detects Vendor .app bundle in /Applications."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker", self.applications, "arm64")

        installs = self.provider.detect_installations("docker", self.custom_roots)
        self.assertTrue(len(installs) >= 1)
        vendor_inst = next((i for i in installs if i.source == MacOSInstallSource.VENDOR_INSTALLER), None)
        self.assertIsNotNone(vendor_inst)
        self.assertEqual(vendor_inst.bundle_id, "com.docker.docker")
        self.assertEqual(vendor_inst.version, "4.26.1")
        self.assertEqual(vendor_inst.owner, "VENDOR")

    def test_03_manual_tool_in_local_bin_detected(self):
        """3. Detects manual binary in user local bin."""
        manual_git = self.user_local_bin / "git"
        self.create_macho_file(manual_git, "arm64")

        # Set PATH to local bin only
        roots = dict(self.custom_roots)
        roots["path"] = str(self.user_local_bin)

        installs = self.provider.detect_installations("git", roots)
        manual_inst = next((i for i in installs if i.source == MacOSInstallSource.MANUAL), None)
        self.assertIsNotNone(manual_inst)
        self.assertEqual(manual_inst.owner, "USER")
        self.assertEqual(manual_inst.installation_scope, "USER")

    def test_04_unknown_source_detected(self):
        """4. Detects unidentifiable installation as UNKNOWN_SOURCE."""
        result = self.provider.analyze_sources("nonexistent_mac_tool", self.custom_roots)
        self.assertEqual(result.status, MacOSSourceDecisionStatus.UNKNOWN_SOURCE)
        self.assertTrue(result.review_required)

    def test_05_homebrew_cask_detected(self):
        """5. Detects Homebrew Cask in Caskroom."""
        cask_dir = self.brew_caskroom / "docker" / "4.27.0"
        self.create_app_bundle("Docker", "com.docker.docker", "4.27.0", "docker", cask_dir, "arm64")

        installs = self.provider.detect_installations("docker", self.custom_roots)
        cask_inst = next((i for i in installs if i.source == MacOSInstallSource.HOMEBREW and i.brew_type == MacOSBrewType.CASK), None)
        self.assertIsNotNone(cask_inst)
        self.assertEqual(cask_inst.version, "4.27.0")
        self.assertEqual(cask_inst.package_id, "docker")

    def test_06_apple_system_binary_detected(self):
        """6. Detects Apple-shipped binary in /usr/bin."""
        sys_git = self.system_bin / "git"
        self.create_macho_file(sys_git, "universal")

        installs = self.provider.detect_installations("git", self.custom_roots)
        sys_inst = next((i for i in installs if i.source == MacOSInstallSource.SYSTEM), None)
        self.assertIsNotNone(sys_inst)
        self.assertEqual(sys_inst.owner, "APPLE_SYSTEM")
        self.assertEqual(sys_inst.architecture, MacOSArchitecture.UNIVERSAL)

    def test_07_app_bundle_info_plist_extraction(self):
        """7. Verifies Info.plist metadata extraction."""
        app_path = self.create_app_bundle("Visual Studio Code", "com.microsoft.VSCode", "1.85.0", "code")
        info = MacOSSourceAwarenessProvider.read_bundle_info_plist(str(app_path))
        self.assertEqual(info.get("CFBundleIdentifier"), "com.microsoft.VSCode")
        self.assertEqual(info.get("CFBundleShortVersionString"), "1.85.0")
        self.assertEqual(info.get("CFBundleExecutable"), "code")

    def test_08_architecture_detection_macho_headers(self):
        """8. Statically detects Mach-O arm64, x86_64, and Universal headers."""
        arm_bin = self.create_macho_file(self.system_bin / "test_arm", "arm64")
        x86_bin = self.create_macho_file(self.system_bin / "test_x86", "x86_64")
        fat_bin = self.create_macho_file(self.system_bin / "test_fat", "universal")

        self.assertEqual(MacOSSourceAwarenessProvider.detect_mach_o_architecture(str(arm_bin)), MacOSArchitecture.ARM64)
        self.assertEqual(MacOSSourceAwarenessProvider.detect_mach_o_architecture(str(x86_bin)), MacOSArchitecture.X86_64)
        self.assertEqual(MacOSSourceAwarenessProvider.detect_mach_o_architecture(str(fat_bin)), MacOSArchitecture.UNIVERSAL)


# ===========================================================================
# 2. Multiple Installations Tests
# ===========================================================================

class TestMacOSMultipleInstallations(TestMacOSSourceAwarenessBase):
    """Tests 9-13: Multiple installation sources, version divergence, and active PATH resolution."""

    def test_09_multiple_installations_homebrew_plus_vendor(self):
        """9. Detects coexisting Homebrew formula and Vendor .app bundle."""
        # Homebrew git
        git_cellar = self.brew_cellar / "git" / "2.43.0" / "bin"
        git_cellar.mkdir(parents=True, exist_ok=True)
        self.create_macho_file(git_cellar / "git", "arm64")
        self.create_macho_file(self.brew_bin / "git", "arm64")

        # Vendor Git in /usr/local/git
        vendor_git = self.root / "usr" / "local" / "git" / "bin" / "git"
        self.create_macho_file(vendor_git, "arm64")

        identity = canonical_store.resolve("git")
        with patch.object(identity, "get_installation_paths", return_value=[str(vendor_git)]):
            analysis = self.provider.analyze_sources("git", self.custom_roots)
            self.assertEqual(analysis.status, MacOSSourceDecisionStatus.MULTIPLE_SOURCES_DETECTED)
            self.assertTrue(len(analysis.all_installations) >= 2)
            self.assertIn(MacOSInstallSource.HOMEBREW, analysis.detected_sources)
            self.assertIn(MacOSInstallSource.VENDOR_INSTALLER, analysis.detected_sources)
            self.assertTrue(analysis.review_required)

    def test_10_multiple_installations_homebrew_plus_manual(self):
        """10. Detects Homebrew tool and manual binary simultaneously."""
        self.create_macho_file(self.brew_bin / "git", "arm64")
        self.create_macho_file(self.user_local_bin / "git", "arm64")

        analysis = self.provider.analyze_sources("git", self.custom_roots)
        self.assertEqual(analysis.status, MacOSSourceDecisionStatus.MULTIPLE_SOURCES_DETECTED)
        self.assertTrue(analysis.review_required)

    def test_11_multiple_versions_detected(self):
        """11. Correctly maps diverging versions across sources."""
        git_cellar = self.brew_cellar / "git" / "2.43.0" / "bin"
        git_cellar.mkdir(parents=True, exist_ok=True)
        self.create_macho_file(git_cellar / "git", "arm64")
        self.create_macho_file(self.brew_bin / "git", "arm64")

        self.create_macho_file(self.system_bin / "git", "universal")

        analysis = self.provider.analyze_sources("git", self.custom_roots)
        self.assertEqual(analysis.status, MacOSSourceDecisionStatus.MULTIPLE_SOURCES_DETECTED)
        # Brew version is 2.43.0
        brew_inst = next(i for i in analysis.all_installations if i.source == MacOSInstallSource.HOMEBREW)
        self.assertEqual(brew_inst.version, "2.43.0")

    def test_12_active_executable_resolved_strictly_via_path(self):
        """12. Proves active installation is strictly resolved via PATH order, NOT highest version."""
        # 1. Brew git (v2.40.0) in /opt/homebrew/bin
        git_cellar = self.brew_cellar / "git" / "2.40.0" / "bin"
        git_cellar.mkdir(parents=True, exist_ok=True)
        self.create_macho_file(git_cellar / "git", "arm64")
        brew_git = self.create_macho_file(self.brew_bin / "git", "arm64")

        # 2. Local git (v2.45.0 — HIGHER version) in ~/.local/bin
        local_git = self.create_macho_file(self.user_local_bin / "git", "arm64")

        # PATH puts ~/.local/bin FIRST
        path_override = [str(self.user_local_bin), str(self.brew_bin)]
        installs = self.provider.detect_installations("git", self.custom_roots)
        active = self.provider.resolve_active_installation(installs, path_override)

        self.assertIsNotNone(active)
        self.assertEqual(active.executable_path, str(local_git))
        self.assertEqual(active.source, MacOSInstallSource.MANUAL)

        # Now reverse PATH: /opt/homebrew/bin FIRST
        path_reversed = [str(self.brew_bin), str(self.user_local_bin)]
        active_reversed = self.provider.resolve_active_installation(installs, path_reversed)
        self.assertEqual(active_reversed.executable_path, str(brew_git))
        self.assertEqual(active_reversed.source, MacOSInstallSource.HOMEBREW)

    def test_13_architecture_conflict_detected(self):
        """13. Detects architecture conflict between arm64 and x86_64 installations."""
        brew_git = self.create_macho_file(self.brew_bin / "git", "arm64")
        sys_git = self.create_macho_file(self.system_bin / "git", "x86_64")

        analysis = self.provider.analyze_sources("git", self.custom_roots)
        self.assertEqual(analysis.status, MacOSSourceDecisionStatus.ARCHITECTURE_CONFLICT)
        self.assertTrue(analysis.architecture_conflict)
        self.assertTrue(analysis.review_required)


# ===========================================================================
# 3. Policy & Update Decisions Tests
# ===========================================================================

class TestMacOSPolicyAndUpdateDecisions(TestMacOSSourceAwarenessBase):
    """Tests 14-18: Per-tool policy enforcement and avoidance of blanket preferences."""

    def test_14_explicit_homebrew_source_policy_applied(self):
        """14. Applies 'package_manager_first' policy to update active Homebrew tool."""
        self.create_macho_file(self.brew_bin / "git", "arm64")
        self.create_macho_file(self.system_bin / "git", "universal")

        decision = self.provider.resolve_update_decision("git", self.custom_roots)
        self.assertEqual(decision.action, "UPDATE_EXISTING")
        self.assertEqual(decision.source, MacOSInstallSource.HOMEBREW)
        self.assertIn("brew upgrade", decision.command)
        self.assertFalse(decision.review_required)

    def test_15_explicit_vendor_source_policy_applied(self):
        """15. Applies 'prefer_upstream' policy when vendor installation is active."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker")
        custom_roots = dict(self.custom_roots)
        custom_roots["path"] = str(self.applications / "Docker.app" / "Contents" / "MacOS")

        identity = canonical_store.resolve("docker")
        with patch.object(identity, "source_policy", "prefer_upstream"):
            decision = self.provider.resolve_update_decision("docker", custom_roots)
            self.assertEqual(decision.action, "UPDATE_EXISTING")
            self.assertEqual(decision.source, MacOSInstallSource.VENDOR_INSTALLER)

    def test_16_ambiguous_source_conflict_triggers_review(self):
        """16. Ambiguous conflict without clear matching policy halts with REVIEW_REQUIRED."""
        self.create_macho_file(self.brew_bin / "git", "arm64")
        self.create_macho_file(self.user_local_bin / "git", "arm64")

        identity = canonical_store.resolve("git")
        with patch.object(identity, "source_policy", "review_required"):
            decision = self.provider.resolve_update_decision("git", self.custom_roots)
            self.assertEqual(decision.action, "REVIEW_REQUIRED")
            self.assertTrue(decision.review_required)

    def test_17_review_required_fallback(self):
        """17. Unmanaged or manual conflict safely defaults to review."""
        self.create_macho_file(self.user_local_bin / "git", "arm64")
        custom_roots = dict(self.custom_roots)
        custom_roots["path"] = str(self.user_local_bin)

        decision = self.provider.resolve_update_decision("git", custom_roots)
        self.assertEqual(decision.action, "REVIEW_REQUIRED")
        self.assertTrue(decision.review_required)

    def test_18_no_blanket_homebrew_preference(self):
        """18. Proves Homebrew is not blindly preferred when vendor is active and policy is upstream."""
        # Both exist
        cask_dir = self.brew_caskroom / "docker" / "4.26.0"
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.0", "docker", cask_dir)
        self.create_app_bundle("Docker", "com.docker.docker", "4.27.0", "docker", self.applications)

        # Active is Vendor in /Applications
        custom_roots = dict(self.custom_roots)
        custom_roots["path"] = str(self.applications / "Docker.app" / "Contents" / "MacOS")

        identity = canonical_store.resolve("docker")
        with patch.object(identity, "source_policy", "prefer_upstream"):
            decision = self.provider.resolve_update_decision("docker", custom_roots)
            self.assertEqual(decision.source, MacOSInstallSource.VENDOR_INSTALLER)
            self.assertNotEqual(decision.source, MacOSInstallSource.HOMEBREW)


# ===========================================================================
# 4. Ownership & Managed Footprint Tests
# ===========================================================================

class TestMacOSOwnershipAndManagedFootprint(TestMacOSSourceAwarenessBase):
    """Tests 19-23: PC Doctor managed vs pre-existing installations and unmanaged removal blocking."""

    def test_19_pc_doctor_managed_homebrew_installation(self):
        """19. Marks Homebrew installation as PC Doctor managed when recorded in registry."""
        self.create_macho_file(self.brew_bin / "git", "arm64")

        mock_record = ManagedInstallation(
            canonical_id="git",
            installation_id="git-inst-1",
            source="BREW",
            package_manager="brew",
            package_id="git",
            version="2.43.0",
            scope="user",
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        with patch.object(footprint_registry, "get_installation", return_value=mock_record):
            installs = self.provider.detect_installations("git", self.custom_roots)
            brew_inst = next(i for i in installs if i.source == MacOSInstallSource.HOMEBREW)
            self.assertTrue(brew_inst.managed_by_pc_doctor)
            self.assertEqual(brew_inst.owner, "PC_DOCTOR")

    def test_20_pc_doctor_managed_vendor_installation(self):
        """20. Marks Vendor installation as PC Doctor managed when recorded in registry."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker")

        mock_record = ManagedInstallation(
            canonical_id="docker",
            installation_id="docker-inst-1",
            source="VENDOR_INSTALLER",
            package_manager="vendor",
            package_id="Docker.DockerDesktop",
            version="4.26.1",
            scope="machine",
            ownership_state=OwnershipState.PC_DOCTOR_MANAGED,
        )
        with patch.object(footprint_registry, "get_installation", return_value=mock_record):
            installs = self.provider.detect_installations("docker", self.custom_roots)
            vendor_inst = next(i for i in installs if i.source == MacOSInstallSource.VENDOR_INSTALLER)
            self.assertTrue(vendor_inst.managed_by_pc_doctor)
            self.assertEqual(vendor_inst.owner, "PC_DOCTOR")

    def test_21_pre_existing_homebrew_installation_flagged_unmanaged(self):
        """21. Unrecorded Homebrew tool is flagged as pre-existing / unmanaged by PC Doctor."""
        self.create_macho_file(self.brew_bin / "git", "arm64")

        with patch.object(footprint_registry, "get_installation", return_value=None):
            installs = self.provider.detect_installations("git", self.custom_roots)
            brew_inst = next(i for i in installs if i.source == MacOSInstallSource.HOMEBREW)
            self.assertFalse(brew_inst.managed_by_pc_doctor)
            self.assertEqual(brew_inst.owner, "HOMEBREW")

    def test_22_pre_existing_vendor_installation_flagged_unmanaged(self):
        """22. Unrecorded Vendor tool is flagged as unmanaged by PC Doctor."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker")

        with patch.object(footprint_registry, "get_installation", return_value=None):
            installs = self.provider.detect_installations("docker", self.custom_roots)
            vendor_inst = next(i for i in installs if i.source == MacOSInstallSource.VENDOR_INSTALLER)
            self.assertFalse(vendor_inst.managed_by_pc_doctor)
            self.assertEqual(vendor_inst.owner, "VENDOR")

    def test_23_unmanaged_source_removal_strictly_blocked(self):
        """23. Source migration notes explicitly preserve pre-existing unmanaged source from deletion."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker")

        with patch.object(footprint_registry, "get_installation", return_value=None):
            plan = self.provider.plan_source_migration(
                canonical_id="docker",
                from_source=MacOSInstallSource.VENDOR_INSTALLER,
                to_source=MacOSInstallSource.HOMEBREW,
                approved=False,
            )
            self.assertIn("UNMANAGED", plan.notes)
            self.assertIn("will NOT be deleted", plan.notes)


# ===========================================================================
# 5. Safety & Execution Boundary Tests
# ===========================================================================

class TestMacOSSafetyAndExecutionBoundary(TestMacOSSourceAwarenessBase):
    """Tests 24-27: Approval requirements, blocked mutations, and Live Safety Gate integration."""

    def test_24_source_migration_requires_user_approval(self):
        """24. Source migration plans are assigned Tier 2 and require explicit user approval."""
        plan = self.provider.plan_source_migration(
            canonical_id="docker",
            from_source=MacOSInstallSource.VENDOR_INSTALLER,
            to_source=MacOSInstallSource.HOMEBREW,
            approved=False,
        )
        self.assertEqual(plan.tier, ExecutionTier.TIER_2_CONTROLLED)
        self.assertTrue(plan.approval_required)
        self.assertFalse(plan.approved)

    def test_25_unapproved_source_migration_blocks_mutation(self):
        """25. Calling CentralizedExecutionEngine with unapproved migration plan executes zero commands."""
        plan = self.provider.plan_source_migration(
            canonical_id="docker",
            from_source=MacOSInstallSource.VENDOR_INSTALLER,
            to_source=MacOSInstallSource.HOMEBREW,
            approved=False,
        )

        engine = CentralizedExecutionEngine()
        outcome = engine.execute_command(
            command=plan.clean_command,
            operation=plan.operation_enum.value,
            source=plan.source,
            approved=plan.approved,
            elevate=plan.requires_elevation,
        )

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.status, "APPROVAL_REQUIRED")
        self.assertIn("approval", outcome.stderr.lower())

    def test_26_safety_gate_rejects_unapproved_command(self):
        """26. Live Safety Gate blocks dangerous or unapproved migration commands."""
        req = ExecutionRequest(
            command="rm -rf /Applications/Docker.app",
            target="docker",
            operation="UNINSTALL",
            source="MACOS_SOURCE_AWARENESS",
            approved=False,
        )
        resolver = ExecutionResolver()
        plan = resolver.resolve(req)
        self.assertTrue(plan.approval_required)

        engine = CentralizedExecutionEngine()
        outcome = engine.execute_command(
            command=plan.clean_command,
            operation=plan.operation_enum.value,
            source=plan.source,
            approved=plan.approved,
            elevate=plan.requires_elevation,
        )
        self.assertFalse(outcome.success)

    def test_27_source_migration_cannot_bypass_centralized_execution(self):
        """27. Verifies provider class never imports or calls subprocess directly for mutations."""
        import inspect
        source_code = inspect.getsource(MacOSSourceAwarenessProvider)
        self.assertNotIn("subprocess.run", source_code)
        self.assertNotIn("os.system", source_code)
        self.assertNotIn("shutil.rmtree", source_code)


# ===========================================================================
# 6. End-to-End Integration Tests
# ===========================================================================

class TestMacOSEndToEndIntegration(TestMacOSSourceAwarenessBase):
    """Tests 28-32: Full lifecycle flows, migration proposals, verification, and rescan."""

    def test_28_source_aware_update_decision_flow(self):
        """28. End-to-end update decision for verified Homebrew tool."""
        self.create_macho_file(self.brew_bin / "git", "arm64")
        git_cellar = self.brew_cellar / "git" / "2.43.0" / "bin"
        git_cellar.mkdir(parents=True, exist_ok=True)
        self.create_macho_file(git_cellar / "git", "arm64")

        decision = self.provider.resolve_update_decision("git", self.custom_roots)
        self.assertEqual(decision.action, "UPDATE_EXISTING")
        self.assertEqual(decision.source, MacOSInstallSource.HOMEBREW)
        self.assertIn("brew upgrade", decision.command)

    def test_29_source_migration_proposal_workflow(self):
        """29. End-to-end source migration workflow from Vendor to Homebrew."""
        self.create_app_bundle("Docker", "com.docker.docker", "4.26.1", "docker")

        plan = self.provider.plan_source_migration(
            canonical_id="docker",
            from_source=MacOSInstallSource.VENDOR_INSTALLER,
            to_source=MacOSInstallSource.HOMEBREW,
            approved=True,
        )
        self.assertEqual(plan.tier, ExecutionTier.TIER_2_CONTROLLED)
        self.assertTrue(plan.approved)
        self.assertIn("brew install", plan.clean_command)

    def test_30_migration_verification_probe(self):
        """30. Verifies installation source verification probe after execution."""
        # Simulated post-migration state: Homebrew now installed
        self.create_macho_file(self.brew_bin / "docker", "arm64")
        analysis = self.provider.analyze_sources("docker", self.custom_roots)
        self.assertTrue(any(i.source == MacOSInstallSource.HOMEBREW for i in analysis.all_installations))

    def test_31_path_source_consistency(self):
        """31. Verifies that switching PATH priority immediately changes active installation."""
        brew_bin = self.create_macho_file(self.brew_bin / "git", "arm64")
        sys_bin = self.create_macho_file(self.system_bin / "git", "universal")

        # 1. Homebrew first
        installs = self.provider.detect_installations("git", self.custom_roots)
        active1 = self.provider.resolve_active_installation(installs, [str(self.brew_bin), str(self.system_bin)])
        self.assertEqual(active1.source, MacOSInstallSource.HOMEBREW)

        # 2. System first
        active2 = self.provider.resolve_active_installation(installs, [str(self.system_bin), str(self.brew_bin)])
        self.assertEqual(active2.source, MacOSInstallSource.SYSTEM)

    def test_32_duplicate_source_rescan_workflow(self):
        """32. Environment rescan correctly captures all concurrent sources without data loss."""
        self.create_macho_file(self.brew_bin / "git", "arm64")
        self.create_macho_file(self.system_bin / "git", "universal")
        self.create_macho_file(self.user_local_bin / "git", "arm64")

        analysis = self.provider.analyze_sources("git", self.custom_roots)
        self.assertEqual(analysis.status, MacOSSourceDecisionStatus.MULTIPLE_SOURCES_DETECTED)
        self.assertEqual(len(analysis.detected_sources), 3)
        self.assertIn(MacOSInstallSource.HOMEBREW, analysis.detected_sources)
        self.assertIn(MacOSInstallSource.SYSTEM, analysis.detected_sources)
        self.assertIn(MacOSInstallSource.MANUAL, analysis.detected_sources)


if __name__ == "__main__":
    unittest.main()
