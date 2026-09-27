"""
platform_abstraction/macos/macos_source_awareness.py — macOS Installation Source Intelligence.
=================================================================================================
Implements Problem #55:
- macOS Homebrew vs Official/Vendor Installer Detection and Source Awareness.
- Invariants:
  1. Pure inspection, comparison, and plan resolution layer — NEVER directly executes
     mutations, shell commands, or uninstalls outside CentralizedExecutionEngine.
  2. Distinguishes Homebrew (formula/cask), Vendor Installers (.app/frameworks),
     Apple System binaries, Manual binaries, and Unknown sources.
  3. Detects duplicate installations across multiple sources without blanket preferences.
  4. Resolves active installation strictly via PATH order, never by highest version number.
  5. Distinguishes normal source updates from cross-source migrations.
  6. Reuses ManagedFootprintRegistry (Phase 11.2) to block deletion of unmanaged installations.
  7. Reuses TrustedSourceIntelligence (Phase 11.1) for authentic vendor source validation.
"""

from __future__ import annotations

import glob
import os
import plistlib
import posixpath
import re
import shutil
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from canonical_identity import CanonicalIdentity, canonical_store
from execution_plan import ExecutionPlan, ExecutionRequest, ExecutionResolver, ProvenanceClass
from execution_tier import ExecutionTier
from managed_footprint import OwnershipState, footprint_registry
from platform_abstraction.macos.macos_environment import MacOSEnvironmentProvider
from platform_abstraction.macos.macos_path import MacOSPathManager
from structured_logger import structured_logger
from trusted_source_intelligence import trusted_source_engine


# ===========================================================================
# 1. Enums and Classifications
# ===========================================================================

class MacOSInstallSource(str, Enum):
    """Authoritative classification of macOS installation provenance."""
    HOMEBREW = "HOMEBREW"
    VENDOR_INSTALLER = "VENDOR_INSTALLER"
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"
    OTHER_TRUSTED = "OTHER_TRUSTED"
    UNKNOWN = "UNKNOWN"


class MacOSBrewType(str, Enum):
    """Homebrew packaging classification."""
    FORMULA = "FORMULA"
    CASK = "CASK"
    NONE = "NONE"


class MacOSArchitecture(str, Enum):
    """Normalized macOS binary/bundle architecture."""
    X86_64 = "x86_64"
    ARM64 = "arm64"
    UNIVERSAL = "universal"
    UNKNOWN = "unknown"


class MacOSSourceDecisionStatus(str, Enum):
    """Status outcomes for macOS source awareness decisions."""
    SOURCE_CONFIRMED = "SOURCE_CONFIRMED"
    MULTIPLE_SOURCES_DETECTED = "MULTIPLE_SOURCES_DETECTED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    SOURCE_POLICY_REQUIRES_REVIEW = "SOURCE_POLICY_REQUIRES_REVIEW"
    ARCHITECTURE_CONFLICT = "ARCHITECTURE_CONFLICT"


# ===========================================================================
# 2. Data Models
# ===========================================================================

@dataclass
class MacOSInstallation:
    """Detailed record of a single detected installation on macOS."""
    canonical_id: str
    display_name: str
    version: Optional[str] = None
    source: MacOSInstallSource = MacOSInstallSource.UNKNOWN
    package_manager: Optional[str] = None
    package_id: Optional[str] = None
    executable_path: Optional[str] = None
    application_bundle_path: Optional[str] = None
    installation_scope: str = "SYSTEM"  # "USER" or "SYSTEM"
    architecture: MacOSArchitecture = MacOSArchitecture.UNKNOWN
    owner: str = "UNKNOWN"              # "HOMEBREW", "VENDOR", "APPLE_SYSTEM", "PC_DOCTOR", "USER"
    brew_type: MacOSBrewType = MacOSBrewType.NONE
    is_active: bool = False
    bundle_id: Optional[str] = None
    bundle_version: Optional[str] = None
    managed_by_pc_doctor: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "display_name": self.display_name,
            "version": self.version,
            "source": self.source.value,
            "package_manager": self.package_manager,
            "package_id": self.package_id,
            "executable_path": self.executable_path,
            "application_bundle_path": self.application_bundle_path,
            "installation_scope": self.installation_scope,
            "architecture": self.architecture.value,
            "owner": self.owner,
            "brew_type": self.brew_type.value,
            "is_active": self.is_active,
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "managed_by_pc_doctor": self.managed_by_pc_doctor,
            "notes": self.notes,
        }


@dataclass
class MacOSSourceAnalysisResult:
    """Comprehensive analysis result across all detected installations of a tool."""
    canonical_id: str
    status: MacOSSourceDecisionStatus
    active_installation: Optional[MacOSInstallation] = None
    all_installations: List[MacOSInstallation] = field(default_factory=list)
    detected_sources: List[MacOSInstallSource] = field(default_factory=list)
    installed_versions: Dict[str, str] = field(default_factory=dict)
    executable_paths: List[str] = field(default_factory=list)
    selected_source: Optional[MacOSInstallSource] = None
    reason: str = ""
    review_required: bool = False
    architecture_conflict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "status": self.status.value,
            "active_installation": self.active_installation.to_dict() if self.active_installation else None,
            "all_installations": [inst.to_dict() for inst in self.all_installations],
            "detected_sources": [s.value for s in self.detected_sources],
            "installed_versions": dict(self.installed_versions),
            "executable_paths": list(self.executable_paths),
            "selected_source": self.selected_source.value if self.selected_source else None,
            "reason": self.reason,
            "review_required": self.review_required,
            "architecture_conflict": self.architecture_conflict,
        }


@dataclass
class MacOSSourceUpdateDecision:
    """Decision recommendation for updating or migrating a macOS installation."""
    canonical_id: str
    source: MacOSInstallSource
    action: str  # "UPDATE_EXISTING", "MIGRATE_SOURCE", "REVIEW_REQUIRED", "NO_ACTION"
    target_source: Optional[MacOSInstallSource] = None
    command: Optional[str] = None
    tier: ExecutionTier = ExecutionTier.TIER_2_CONTROLLED
    approval_required: bool = True
    requires_elevation: bool = False
    reason: str = ""
    review_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "source": self.source.value,
            "action": self.action,
            "target_source": self.target_source.value if self.target_source else None,
            "command": self.command,
            "tier": self.tier.value,
            "approval_required": self.approval_required,
            "requires_elevation": self.requires_elevation,
            "reason": self.reason,
            "review_required": self.review_required,
        }


# ===========================================================================
# 3. macOS Source Awareness Provider
# ===========================================================================

class MacOSSourceAwarenessProvider:
    """
    Authoritative macOS Source Intelligence Provider.
    Inspects Homebrew, vendor application bundles, system tools, and PATH entries.
    """

    def __init__(
        self,
        env_provider: Optional[MacOSEnvironmentProvider] = None,
        path_manager: Optional[MacOSPathManager] = None,
        homebrew_prefixes: Optional[List[str]] = None,
        app_dirs: Optional[List[str]] = None,
    ) -> None:
        self._env = env_provider or MacOSEnvironmentProvider()
        self._path_mgr = path_manager or MacOSPathManager(self._env)
        self._homebrew_prefixes = homebrew_prefixes or ["/opt/homebrew", "/usr/local"]
        self._app_dirs = app_dirs or ["/Applications", os.path.expanduser("~/Applications")]

    # -----------------------------------------------------------------------
    # Binary & Bundle Inspection Probes
    # -----------------------------------------------------------------------

    @staticmethod
    def detect_mach_o_architecture(file_path: str) -> MacOSArchitecture:
        """
        Statically inspects Mach-O header magic bytes without spawning child processes.
        """
        if not file_path or not os.path.isfile(file_path):
            return MacOSArchitecture.UNKNOWN

        try:
            with open(file_path, "rb") as f:
                header = f.read(8)
                if len(header) < 4:
                    return MacOSArchitecture.UNKNOWN

                magic = struct.unpack(">I", header[:4])[0]
                # Fat / Universal Binary
                if magic in (0xCAFEBABE, 0xBEBAFECA):
                    return MacOSArchitecture.UNIVERSAL

                # 64-bit Mach-O
                if magic in (0xFEEDFACF, 0xCFFAEDFE):
                    if len(header) >= 8:
                        # Inspect cputype
                        cputype = struct.unpack("<I", header[4:8])[0] if magic == 0xCFFAEDFE else struct.unpack(">I", header[4:8])[0]
                        # 0x01000007 = CPU_TYPE_X86_64, 0x0100000C = CPU_TYPE_ARM64
                        if cputype in (0x01000007, 7):
                            return MacOSArchitecture.X86_64
                        if cputype in (0x0100000C, 12):
                            return MacOSArchitecture.ARM64

                # 32-bit Mach-O fallback
                if magic in (0xFEEDFACE, 0xCEFAEDFE):
                    return MacOSArchitecture.X86_64

        except Exception:
            pass

        return MacOSArchitecture.UNKNOWN

    @staticmethod
    def read_bundle_info_plist(bundle_path: str) -> Dict[str, Any]:
        """Reads Info.plist from an .app bundle safely using plistlib."""
        if not bundle_path:
            return {}
        plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
        if not os.path.isfile(plist_path):
            return {}
        try:
            with open(plist_path, "rb") as f:
                return plistlib.load(f)
        except Exception:
            return {}

    # -----------------------------------------------------------------------
    # Multi-Source Detection
    # -----------------------------------------------------------------------

    def detect_installations(
        self,
        canonical_id: str,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> List[MacOSInstallation]:
        """
        Gathers all detected installations of the target canonical tool across:
        1. Homebrew (Cellar + Caskroom)
        2. Official Vendor .app bundles & frameworks
        3. Apple System binaries (/usr/bin)
        4. Manual / PATH binaries
        """
        identity = canonical_store.resolve(canonical_id)
        if not identity:
            structured_logger.log_event(
                operation="SOURCE_SCAN",
                application=canonical_id,
                identity=canonical_id,
                status="NOT_FOUND",
                message=f"Canonical identity '{canonical_id}' not found in registry",
            )
            return []

        structured_logger.log_event(
            operation="SOURCE_SCAN",
            application=canonical_id,
            identity=canonical_id,
            status="STARTED",
            message=f"Beginning multi-source scan for tool '{identity.display_name}'",
        )

        detected: List[MacOSInstallation] = []
        seen_executables: Set[str] = set()

        # 1. Detect Homebrew Installations (Formula & Cask)
        brew_installs = self._detect_homebrew(identity, custom_roots)
        for inst in brew_installs:
            detected.append(inst)
            if inst.executable_path:
                seen_executables.add(os.path.normpath(inst.executable_path))

        # 2. Detect Vendor .app Bundles & Vendor Frameworks
        vendor_installs = self._detect_vendor(identity, custom_roots)
        for inst in vendor_installs:
            # Avoid duplicate if cask already mapped this .app bundle
            already_mapped = any(
                d.application_bundle_path and inst.application_bundle_path and
                os.path.normpath(d.application_bundle_path) == os.path.normpath(inst.application_bundle_path)
                for d in detected
            )
            if not already_mapped:
                detected.append(inst)
                if inst.executable_path:
                    seen_executables.add(os.path.normpath(inst.executable_path))

        # 3. Detect Apple System Binaries (/usr/bin, /bin)
        sys_installs = self._detect_system(identity, custom_roots)
        for inst in sys_installs:
            if inst.executable_path and os.path.normpath(inst.executable_path) not in seen_executables:
                detected.append(inst)
                seen_executables.add(os.path.normpath(inst.executable_path))

        # 4. Detect Manual / Custom PATH Binaries
        path_installs = self._detect_path(identity, seen_executables, custom_roots)
        for inst in path_installs:
            if inst.executable_path and os.path.normpath(inst.executable_path) not in seen_executables:
                detected.append(inst)
                seen_executables.add(os.path.normpath(inst.executable_path))

        # 5. Check PC Doctor Managed Ownership for each installation
        footprint = footprint_registry.get_installation(canonical_id)
        if footprint and footprint.ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
            # Mark matching installation
            for inst in detected:
                    if footprint.package_manager == "brew" and inst.source == MacOSInstallSource.HOMEBREW:
                        inst.managed_by_pc_doctor = True
                        inst.owner = "PC_DOCTOR"
                    elif footprint.package_manager != "brew" and inst.source == MacOSInstallSource.VENDOR_INSTALLER:
                        inst.managed_by_pc_doctor = True
                        inst.owner = "PC_DOCTOR"

        # 6. Resolve Active Installation via PATH order
        effective_path = self._split_path_string(custom_roots["path"]) if (custom_roots and "path" in custom_roots) else None
        self.resolve_active_installation(detected, effective_path=effective_path)

        for inst in detected:
            structured_logger.log_event(
                operation="SOURCE_DETECTED",
                application=canonical_id,
                identity=canonical_id,
                status=inst.source.value,
                message=f"Found {inst.source.value} installation at '{inst.executable_path or inst.application_bundle_path}' (active={inst.is_active})",
            )

        return detected

    def _detect_homebrew(
        self,
        identity: CanonicalIdentity,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> List[MacOSInstallation]:
        """Detects Homebrew Formula or Cask installations."""
        installs: List[MacOSInstallation] = []
        pkg_id = identity.get_package_id("darwin") or identity.identity_id
        prefixes = [custom_roots["homebrew_prefix"]] if (custom_roots and "homebrew_prefix" in custom_roots) else self._homebrew_prefixes

        candidate_names = {
            identity.identity_id.lower(),
            identity.executable.lower(),
            pkg_id.lower(),
            pkg_id,
        }
        for alias in identity.aliases:
            candidate_names.add(alias.lower())

        for prefix in prefixes:
            if not os.path.isdir(prefix):
                continue

            # A. Check Cellar (Formula)
            for c_name in candidate_names:
                cellar_pkg_dir = os.path.join(prefix, "Cellar", c_name)
                if os.path.isdir(cellar_pkg_dir):
                    versions = [v for v in os.listdir(cellar_pkg_dir) if not v.startswith(".")]
                    if versions:
                        latest_ver = sorted(versions)[-1]
                        bin_dir = os.path.join(cellar_pkg_dir, latest_ver, "bin")
                        exec_path = os.path.join(bin_dir, identity.executable)
                        symlink_bin = os.path.join(prefix, "bin", identity.executable)
                        final_exec = symlink_bin if os.path.exists(symlink_bin) else (exec_path if os.path.exists(exec_path) else None)
                        arch = self.detect_mach_o_architecture(final_exec) if final_exec else (
                            MacOSArchitecture.ARM64 if "/opt/homebrew" in prefix.replace("\\", "/") else MacOSArchitecture.X86_64
                        )
                        installs.append(
                            MacOSInstallation(
                                canonical_id=identity.identity_id,
                                display_name=identity.display_name,
                                version=latest_ver,
                                source=MacOSInstallSource.HOMEBREW,
                                package_manager="brew",
                                package_id=c_name,
                                executable_path=final_exec,
                                architecture=arch,
                                owner="HOMEBREW",
                                brew_type=MacOSBrewType.FORMULA,
                                installation_scope="USER" if "/home/" in prefix.replace("\\", "/") else "SYSTEM",
                                notes=f"Homebrew formula installed in {cellar_pkg_dir}",
                            )
                        )
                        break

            # B. Check Caskroom (Cask)
            for c_name in candidate_names:
                cask_pkg_dir = os.path.join(prefix, "Caskroom", c_name)
                if os.path.isdir(cask_pkg_dir):
                    cask_versions = [v for v in os.listdir(cask_pkg_dir) if not v.startswith(".")]
                    if cask_versions:
                        latest_cask_ver = sorted(cask_versions)[-1]
                        cask_ver_dir = os.path.join(cask_pkg_dir, latest_cask_ver)
                        # Find .app inside cask directory
                        app_matches = glob.glob(os.path.join(cask_ver_dir, "*.app"))
                        bundle_path = app_matches[0] if app_matches else None
                        bundle_info = self.read_bundle_info_plist(bundle_path) if bundle_path else {}
                        exec_name = bundle_info.get("CFBundleExecutable", identity.executable)
                        exec_path = os.path.join(bundle_path, "Contents", "MacOS", exec_name) if bundle_path else None
                        if not exec_path or not os.path.exists(exec_path):
                            symlink_bin = os.path.join(prefix, "bin", identity.executable)
                            if os.path.exists(symlink_bin):
                                exec_path = symlink_bin

                        arch = self.detect_mach_o_architecture(exec_path) if exec_path else (
                            MacOSArchitecture.ARM64 if "/opt/homebrew" in prefix.replace("\\", "/") else MacOSArchitecture.X86_64
                        )
                        installs.append(
                            MacOSInstallation(
                                canonical_id=identity.identity_id,
                                display_name=identity.display_name,
                                version=latest_cask_ver,
                                source=MacOSInstallSource.HOMEBREW,
                                package_manager="brew",
                                package_id=c_name,
                                executable_path=exec_path,
                                application_bundle_path=bundle_path,
                                architecture=arch,
                                owner="HOMEBREW",
                                brew_type=MacOSBrewType.CASK,
                                bundle_id=bundle_info.get("CFBundleIdentifier"),
                                bundle_version=bundle_info.get("CFBundleShortVersionString") or bundle_info.get("CFBundleVersion"),
                                installation_scope="SYSTEM",
                                notes=f"Homebrew cask installed in {cask_pkg_dir}",
                            )
                        )
                        break

            # C. Check prefix/bin directly if not already registered
            if not any(i.source == MacOSInstallSource.HOMEBREW for i in installs):
                bin_candidates = [
                    os.path.join(prefix, "bin", identity.executable),
                    os.path.join(prefix, "bin", identity.identity_id),
                ]
                for bc in bin_candidates:
                    if os.path.exists(bc):
                        arch = self.detect_mach_o_architecture(bc)
                        installs.append(
                            MacOSInstallation(
                                canonical_id=identity.identity_id,
                                display_name=identity.display_name,
                                version="unknown",
                                source=MacOSInstallSource.HOMEBREW,
                                package_manager="brew",
                                package_id=pkg_id,
                                executable_path=bc,
                                architecture=arch,
                                owner="HOMEBREW",
                                brew_type=MacOSBrewType.FORMULA,
                                installation_scope="SYSTEM",
                                notes=f"Homebrew binary at {bc}",
                            )
                        )
                        break

        return installs

    def _detect_vendor(
        self,
        identity: CanonicalIdentity,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> List[MacOSInstallation]:
        """Detects Official Vendor .app bundles and vendor framework installations."""
        installs: List[MacOSInstallation] = []
        app_dirs = [custom_roots["applications_dir"]] if (custom_roots and "applications_dir" in custom_roots) else self._app_dirs

        candidate_bundle_names = [
            f"{identity.display_name}.app",
            f"{identity.identity_id}.app",
            f"{identity.identity_id.capitalize()}.app",
            f"{identity.executable.capitalize()}.app",
            f"{identity.executable}.app",
        ]
        for alias in identity.aliases:
            candidate_bundle_names.append(f"{alias}.app")
            candidate_bundle_names.append(f"{alias.capitalize()}.app")

        for app_dir in app_dirs:
            if not os.path.isdir(app_dir):
                continue

            app_dir_lower = app_dir.replace("\\", "/").lower()
            scope = "USER" if ("/users/" in app_dir_lower or "/home/" in app_dir_lower) else "SYSTEM"

            for b_name in candidate_bundle_names:
                bundle_path = os.path.join(app_dir, b_name)
                if not os.path.isdir(bundle_path):
                    continue

                info = self.read_bundle_info_plist(bundle_path)
                bundle_id = info.get("CFBundleIdentifier", "")
                version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")

                exec_name = info.get("CFBundleExecutable", identity.executable)
                exec_path = os.path.join(bundle_path, "Contents", "MacOS", exec_name)
                if not os.path.exists(exec_path):
                    # Check resources or helper bin
                    alt_exec = os.path.join(bundle_path, "Contents", "Resources", "bin", identity.executable)
                    if os.path.exists(alt_exec):
                        exec_path = alt_exec
                    else:
                        exec_path = None

                arch = self.detect_mach_o_architecture(exec_path) if exec_path else MacOSArchitecture.UNKNOWN

                # Verify provenance: is this Homebrew Cask or Authentic Vendor?
                is_brew_cask = False
                for prefix in self._homebrew_prefixes:
                    if os.path.realpath(bundle_path).startswith(os.path.join(prefix, "Caskroom")):
                        is_brew_cask = True
                        break

                source = MacOSInstallSource.HOMEBREW if is_brew_cask else MacOSInstallSource.VENDOR_INSTALLER

                installs.append(
                    MacOSInstallation(
                        canonical_id=identity.identity_id,
                        display_name=identity.display_name,
                        version=version,
                        source=source,
                        executable_path=exec_path,
                        application_bundle_path=bundle_path,
                        installation_scope=scope,
                        architecture=arch,
                        owner="HOMEBREW" if is_brew_cask else "VENDOR",
                        brew_type=MacOSBrewType.CASK if is_brew_cask else MacOSBrewType.NONE,
                        bundle_id=bundle_id,
                        bundle_version=version,
                        notes=f"Application bundle in {bundle_path}",
                    )
                )

        # Also check configured vendor installation paths (e.g. /usr/local/go/bin/go, /Library/Frameworks/Python.framework)
        for configured_path in identity.get_installation_paths("darwin"):
            norm_path = os.path.normpath(configured_path)
            norm_lower = norm_path.replace("\\", "/").lower()
            if os.path.isfile(norm_path) and not any(i.executable_path and os.path.normpath(i.executable_path) == norm_path for i in installs):
                if not norm_lower.startswith("/usr/bin") and not norm_lower.startswith("/bin") and "/cellar/" not in norm_lower:
                    arch = self.detect_mach_o_architecture(norm_path)
                    scope = "USER" if ("/users/" in norm_lower or "/home/" in norm_lower) else "SYSTEM"
                    installs.append(
                        MacOSInstallation(
                            canonical_id=identity.identity_id,
                            display_name=identity.display_name,
                            source=MacOSInstallSource.VENDOR_INSTALLER,
                            executable_path=norm_path,
                            architecture=arch,
                            owner="VENDOR",
                            installation_scope=scope,
                            notes=f"Vendor installation path: {norm_path}",
                        )
                    )

        return installs

    def _detect_system(
        self,
        identity: CanonicalIdentity,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> List[MacOSInstallation]:
        """Detects Apple-shipped system tools in /usr/bin or /bin."""
        installs: List[MacOSInstallation] = []
        sys_roots = [custom_roots["system_bin"]] if (custom_roots and "system_bin" in custom_roots) else ["/usr/bin", "/bin"]

        for s_root in sys_roots:
            target = os.path.join(s_root, identity.executable)
            if os.path.isfile(target):
                arch = self.detect_mach_o_architecture(target)
                installs.append(
                    MacOSInstallation(
                        canonical_id=identity.identity_id,
                        display_name=identity.display_name,
                        source=MacOSInstallSource.SYSTEM,
                        executable_path=target,
                        architecture=arch,
                        owner="APPLE_SYSTEM",
                        installation_scope="SYSTEM",
                        notes=f"Apple system binary in {s_root}",
                    )
                )

        return installs

    def _split_path_string(self, raw_path: str) -> List[str]:
        r"""
        Splits a PATH string into directory components.
        Supports both semicolon and colon delimiters, correctly preserving
        Windows drive letters (e.g. 'C:\dir') without corrupting path tokens.
        """
        if not raw_path:
            return []
        if ";" in raw_path:
            return [p.strip() for p in raw_path.split(";") if p.strip()]

        raw_tokens = raw_path.split(":")
        parts: List[str] = []
        i = 0
        while i < len(raw_tokens):
            tok = raw_tokens[i]
            if len(tok) == 1 and tok.isalpha() and i + 1 < len(raw_tokens):
                parts.append(f"{tok}:{raw_tokens[i+1]}".strip())
                i += 2
            else:
                if tok.strip():
                    parts.append(tok.strip())
                i += 1
        return parts

    def _detect_path(
        self,
        identity: CanonicalIdentity,
        already_seen: Set[str],
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> List[MacOSInstallation]:
        """Detects manual binaries discoverable on PATH."""
        installs: List[MacOSInstallation] = []
        raw_path = os.environ.get("PATH", "")
        if custom_roots and "path" in custom_roots:
            raw_path = custom_roots["path"]

        path_dirs = self._split_path_string(raw_path)

        for p_dir in path_dirs:
            candidate = os.path.join(p_dir, identity.executable)
            norm_cand = os.path.normpath(candidate)
            if os.path.isfile(candidate) and norm_cand not in already_seen:
                cand_lower = candidate.replace("\\", "/").lower()

                brew_match = False
                if custom_roots and "homebrew_prefix" in custom_roots:
                    hb_root = custom_roots["homebrew_prefix"].replace("\\", "/").lower()
                    if hb_root in cand_lower:
                        brew_match = True
                if "opt/homebrew" in cand_lower or "/cellar/" in cand_lower:
                    brew_match = True

                sys_match = False
                if custom_roots and "system_bin" in custom_roots:
                    sb_root = custom_roots["system_bin"].replace("\\", "/").lower()
                    if sb_root in cand_lower:
                        sys_match = True
                if cand_lower.startswith("/usr/bin") or cand_lower.startswith("/bin") or "/usr/bin" in cand_lower:
                    sys_match = True

                if brew_match:
                    source = MacOSInstallSource.HOMEBREW
                    owner = "HOMEBREW"
                    b_type = MacOSBrewType.FORMULA
                elif sys_match:
                    source = MacOSInstallSource.SYSTEM
                    owner = "APPLE_SYSTEM"
                    b_type = MacOSBrewType.NONE
                else:
                    source = MacOSInstallSource.MANUAL
                    owner = "USER"
                    b_type = MacOSBrewType.NONE

                arch = self.detect_mach_o_architecture(candidate)
                scope = "USER" if ("/users/" in cand_lower or "/home/" in cand_lower) else "SYSTEM"
                installs.append(
                    MacOSInstallation(
                        canonical_id=identity.identity_id,
                        display_name=identity.display_name,
                        source=source,
                        executable_path=candidate,
                        architecture=arch,
                        owner=owner,
                        brew_type=b_type,
                        installation_scope=scope,
                        notes=f"Discovered on PATH: {candidate}",
                    )
                )

        return installs

    # -----------------------------------------------------------------------
    # Active Installation & Analysis Resolution
    # -----------------------------------------------------------------------

    def resolve_active_installation(
        self,
        installations: List[MacOSInstallation],
        effective_path: Optional[List[str]] = None,
    ) -> Optional[MacOSInstallation]:
        """
        Determines the active installation by checking which executable is resolved by PATH order.
        Strict invariant: NEVER blindly chooses the highest version number.
        """
        if not installations:
            return None

        if effective_path is not None:
            path_dirs = effective_path
        else:
            raw_path = os.environ.get("PATH", "")
            path_dirs = self._split_path_string(raw_path)

        # Reset active status
        for inst in installations:
            inst.is_active = False

        # Scan PATH directories in order
        for p_dir in path_dirs:
            norm_p_dir = os.path.normpath(p_dir).lower().rstrip(r"\/")
            for inst in installations:
                if inst.executable_path:
                    inst_dir = os.path.normpath(os.path.dirname(inst.executable_path)).lower().rstrip(r"\/")
                    if inst_dir == norm_p_dir:
                        inst.is_active = True
                        return inst

        # Fallback if none explicitly matches PATH: pick the first one with an executable
        for inst in installations:
            if inst.executable_path:
                inst.is_active = True
                return inst

        # Final fallback
        installations[0].is_active = True
        return installations[0]

    def analyze_sources(
        self,
        canonical_id: str,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> MacOSSourceAnalysisResult:
        """
        Performs holistic analysis across all detected sources for a tool.
        Identifies:
        - Confirmed single source
        - Multiple sources detected (duplicate installations)
        - Conflicting versions or architectures
        - Policy-required human review
        """
        installs = self.detect_installations(canonical_id, custom_roots)
        if not installs:
            return MacOSSourceAnalysisResult(
                canonical_id=canonical_id,
                status=MacOSSourceDecisionStatus.UNKNOWN_SOURCE,
                reason=f"No installation of '{canonical_id}' detected on macOS host",
                review_required=True,
            )

        active = next((i for i in installs if i.is_active), installs[0])
        sources = list({i.source for i in installs})
        versions = {f"{i.source.value}:{i.executable_path or i.application_bundle_path}": (i.version or "unknown") for i in installs}
        exec_paths = [i.executable_path for i in installs if i.executable_path]

        # Check for architecture conflict
        archs = {i.architecture for i in installs if i.architecture != MacOSArchitecture.UNKNOWN}
        arch_conflict = len(archs) > 1 and MacOSArchitecture.UNIVERSAL not in archs

        # Case 1: Multiple sources detected
        if len(sources) > 1 or len(installs) > 1:
            structured_logger.log_event(
                operation="MULTIPLE_SOURCES_DETECTED",
                application=canonical_id,
                identity=canonical_id,
                status="CONFLICT",
                message=f"Detected multiple installation sources for '{canonical_id}': {[s.value for s in sources]}",
            )

            status = MacOSSourceDecisionStatus.ARCHITECTURE_CONFLICT if arch_conflict else (
                MacOSSourceDecisionStatus.MULTIPLE_SOURCES_DETECTED
            )

            return MacOSSourceAnalysisResult(
                canonical_id=canonical_id,
                status=status,
                active_installation=active,
                all_installations=installs,
                detected_sources=sources,
                installed_versions=versions,
                executable_paths=exec_paths,
                selected_source=active.source,
                reason=f"Multiple installations detected: active={active.source.value} ({active.version}), total={len(installs)}",
                review_required=True,  # Disambiguation required
                architecture_conflict=arch_conflict,
            )

        # Case 2: Exactly 1 installation source
        single_source = sources[0]
        if single_source == MacOSInstallSource.UNKNOWN:
            return MacOSSourceAnalysisResult(
                canonical_id=canonical_id,
                status=MacOSSourceDecisionStatus.UNKNOWN_SOURCE,
                active_installation=active,
                all_installations=installs,
                detected_sources=sources,
                installed_versions=versions,
                executable_paths=exec_paths,
                selected_source=single_source,
                reason="Single installation detected but provenance/source is unknown",
                review_required=True,
            )

        return MacOSSourceAnalysisResult(
            canonical_id=canonical_id,
            status=MacOSSourceDecisionStatus.SOURCE_CONFIRMED,
            active_installation=active,
            all_installations=installs,
            detected_sources=sources,
            installed_versions=versions,
            executable_paths=exec_paths,
            selected_source=single_source,
            reason=f"Single verified installation source: {single_source.value} ({active.version or 'active'})",
            review_required=False,
        )

    # -----------------------------------------------------------------------
    # Source-Aware Decision & Migration Planning
    # -----------------------------------------------------------------------

    def resolve_update_decision(
        self,
        canonical_id: str,
        custom_roots: Optional[Dict[str, str]] = None,
    ) -> MacOSSourceUpdateDecision:
        """
        Determines the appropriate update or review action for a tool:
        - If single source: updates that specific source.
        - If multiple sources: consults canonical identity policy (no blanket preferences).
        - If policy is ambiguous or conflict exists: halts with REVIEW_REQUIRED.
        """
        analysis = self.analyze_sources(canonical_id, custom_roots)
        identity = canonical_store.resolve(canonical_id)
        policy = identity.source_policy if identity else "package_manager_first"

        # 1. Unknown or No Installations
        if analysis.status == MacOSSourceDecisionStatus.UNKNOWN_SOURCE or not analysis.all_installations:
            return MacOSSourceUpdateDecision(
                canonical_id=canonical_id,
                source=MacOSInstallSource.UNKNOWN,
                action="REVIEW_REQUIRED",
                reason=analysis.reason,
                review_required=True,
            )

        active = analysis.active_installation or analysis.all_installations[0]

        # 2. Confirmed Single Installation Source
        if analysis.status == MacOSSourceDecisionStatus.SOURCE_CONFIRMED:
            pkg_id = identity.get_package_id("darwin") if identity else canonical_id
            if active.source == MacOSInstallSource.HOMEBREW:
                cmd = f"brew upgrade {pkg_id}"
                return MacOSSourceUpdateDecision(
                    canonical_id=canonical_id,
                    source=MacOSInstallSource.HOMEBREW,
                    action="UPDATE_EXISTING",
                    command=cmd,
                    tier=ExecutionTier.TIER_2_CONTROLLED,
                    approval_required=True,
                    reason=f"Updating existing Homebrew installation for '{canonical_id}'",
                )
            elif active.source == MacOSInstallSource.VENDOR_INSTALLER:
                return MacOSSourceUpdateDecision(
                    canonical_id=canonical_id,
                    source=MacOSInstallSource.VENDOR_INSTALLER,
                    action="UPDATE_EXISTING",
                    command=None,
                    tier=ExecutionTier.TIER_2_CONTROLLED,
                    approval_required=True,
                    reason=f"Vendor update required for '{canonical_id}' via trusted upstream",
                    review_required=False,
                )
            elif active.source == MacOSInstallSource.SYSTEM:
                return MacOSSourceUpdateDecision(
                    canonical_id=canonical_id,
                    source=MacOSInstallSource.SYSTEM,
                    action="REVIEW_REQUIRED",
                    reason=f"Tool '{canonical_id}' is an Apple system binary; cannot be updated independently",
                    review_required=True,
                )

        # 3. Multiple Sources Detected
        # Check tool-specific policy
        has_brew = any(i.source == MacOSInstallSource.HOMEBREW for i in analysis.all_installations)
        has_vendor = any(i.source == MacOSInstallSource.VENDOR_INSTALLER for i in analysis.all_installations)

        structured_logger.log_event(
            operation="SOURCE_POLICY_REVIEW",
            application=canonical_id,
            identity=canonical_id,
            status="EVALUATING",
            message=f"Evaluating policy '{policy}' for conflicting sources: {[s.value for s in analysis.detected_sources]}",
        )

        if policy == "package_manager_first" and has_brew and active.source == MacOSInstallSource.HOMEBREW:
            pkg_id = identity.get_package_id("darwin") if identity else canonical_id
            return MacOSSourceUpdateDecision(
                canonical_id=canonical_id,
                source=MacOSInstallSource.HOMEBREW,
                action="UPDATE_EXISTING",
                command=f"brew upgrade {pkg_id}",
                tier=ExecutionTier.TIER_2_CONTROLLED,
                approval_required=True,
                reason=f"Policy 'package_manager_first' matched active Homebrew installation",
                review_required=False,
            )

        if policy == "prefer_upstream" and has_vendor and active.source == MacOSInstallSource.VENDOR_INSTALLER:
            return MacOSSourceUpdateDecision(
                canonical_id=canonical_id,
                source=MacOSInstallSource.VENDOR_INSTALLER,
                action="UPDATE_EXISTING",
                command=None,
                tier=ExecutionTier.TIER_2_CONTROLLED,
                approval_required=True,
                reason=f"Policy 'prefer_upstream' matched active Vendor installation",
                review_required=False,
            )

        # Ambiguous conflict: require human review
        return MacOSSourceUpdateDecision(
            canonical_id=canonical_id,
            source=active.source,
            action="REVIEW_REQUIRED",
            reason=f"Multiple conflicting installation sources detected ({[s.value for s in analysis.detected_sources]}); explicit review required",
            review_required=True,
        )

    def plan_source_migration(
        self,
        canonical_id: str,
        from_source: MacOSInstallSource,
        to_source: MacOSInstallSource,
        approved: bool = False,
    ) -> ExecutionPlan:
        """
        Creates an authoritative ExecutionPlan for migrating a tool across sources.
        Invariants:
        1. Migration is NEVER treated as a normal update.
        2. Requires explicit user approval (`tier = Tier 2/3`, `approval_required = True`).
        3. Never automatically uninstalls the old source before verification.
        4. Reuses ManagedFootprintRegistry: unmanaged pre-existing sources cannot be auto-deleted.
        """
        identity = canonical_store.resolve(canonical_id)
        pkg_id = identity.get_package_id("darwin") if identity else canonical_id

        structured_logger.log_event(
            operation="SOURCE_MIGRATION_PROPOSED",
            application=canonical_id,
            identity=canonical_id,
            status="PROPOSED",
            message=f"Proposing source migration for '{canonical_id}' from {from_source.value} to {to_source.value}",
        )

        # Synthesize target installation command
        if to_source == MacOSInstallSource.HOMEBREW:
            cmd = f"brew install {pkg_id}"
            elevate = False
            tier = ExecutionTier.TIER_2_CONTROLLED
        elif to_source == MacOSInstallSource.VENDOR_INSTALLER:
            official_url = identity.official_url if identity else "https://vendor.com"
            cmd = f"# Vendor installer from {official_url}"
            elevate = True
            tier = ExecutionTier.TIER_2_CONTROLLED
        else:
            cmd = f"# Migration to {to_source.value}"
            elevate = False
            tier = ExecutionTier.TIER_2_CONTROLLED

        # Route through ExecutionResolver
        req = ExecutionRequest(
            command=cmd,
            target=canonical_id,
            operation="INSTALL",
            source="MACOS_SOURCE_AWARENESS",
            provenance_hint=ProvenanceClass.SOURCE_MIGRATION,
            approved=approved,
            elevate=elevate,
        )

        resolver = ExecutionResolver()
        plan = resolver.resolve(req)

        # Check if old source is unmanaged
        footprint = footprint_registry.get_installation(canonical_id)
        is_pc_doctor_managed = footprint and footprint.ownership_state == OwnershipState.PC_DOCTOR_MANAGED

        if not is_pc_doctor_managed:
            plan.notes = (
                f"Source migration from {from_source.value} to {to_source.value}. "
                f"Existing {from_source.value} installation is PRE-EXISTING / UNMANAGED and will NOT be deleted."
            )
        else:
            plan.notes = f"Source migration from {from_source.value} to {to_source.value}."

        return plan


# Global singleton instance
macos_source_awareness = MacOSSourceAwarenessProvider()
