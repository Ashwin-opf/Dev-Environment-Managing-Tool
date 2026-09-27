"""
backend/multi_source_manager.py — Cross-Platform Multiple Installation Source Manager.

Implements Problem #56:
- Cross-platform detection of multiple installation sources (Windows, macOS, Linux)
- Active PATH resolution (distinguishing active binary from shadowed/redundant binaries)
- Managed footprint ownership verification via ManagedFootprintRegistry
- Safe migration sequence:
  1. Target source verified BEFORE old redundant source removal
  2. Redundant source removal permitted ONLY when verified as PC_DOCTOR_MANAGED
  3. Unmanaged/user/ambiguous sources strictly routed to REVIEW_REQUIRED
  4. All mutations pass strictly through CentralizedExecutionEngine
  5. Post-migration verification and state rescan
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from execution_engine import CentralizedExecutionEngine, ExecutionOutcome, execution_engine as default_engine
from managed_footprint import ManagedFootprintRegistry, ManagedInstallation, OwnershipState
from state_refresh import state_refresher
from structured_logger import structured_logger

logger = logging.getLogger("pc_doctor.multi_source_manager")


class InstallationSourceType(str, Enum):
    """Normalized source classifications across platforms."""
    WINGET = "winget"
    CHOCOLATEY = "choco"
    SCOOP = "scoop"
    HOMEBREW = "brew"
    MACOS_APP = "macos_app"
    APT = "apt"
    DNF = "dnf"
    PACMAN = "pacman"
    ZYPPER = "zypper"
    APK = "apk"
    SNAP = "snap"
    FLATPAK = "flatpak"
    STANDALONE_PATH = "standalone_path"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class MultiSourceStatus(str, Enum):
    """Taxonomy of multi-source detection and remediation outcomes."""
    NO_CONFLICT = "NO_CONFLICT"
    MULTIPLE_SOURCES_DETECTED = "MULTIPLE_SOURCES_DETECTED"
    MIGRATION_SUCCESS = "MIGRATION_SUCCESS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    TARGET_VERIFICATION_FAILED = "TARGET_VERIFICATION_FAILED"
    REDUNDANT_REMOVAL_FAILED = "REDUNDANT_REMOVAL_FAILED"
    FINAL_VERIFICATION_FAILED = "FINAL_VERIFICATION_FAILED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"


@dataclass
class DetectedInstallation:
    """An identified installation instance of a canonical tool on the host."""
    canonical_id: str
    source_type: InstallationSourceType
    executable_path: Optional[str] = None
    installation_root: Optional[str] = None
    version: Optional[str] = None
    is_active: bool = False
    ownership_state: OwnershipState = OwnershipState.UNKNOWN
    package_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "source_type": self.source_type.value,
            "executable_path": self.executable_path,
            "installation_root": self.installation_root,
            "version": self.version,
            "is_active": self.is_active,
            "ownership_state": self.ownership_state.value,
            "package_id": self.package_id,
            "details": self.details,
        }


@dataclass
class MultiSourceAnalysisResult:
    """Detailed diagnostic analysis of a tool's multi-source state."""
    canonical_id: str
    status: MultiSourceStatus
    active_installation: Optional[DetectedInstallation] = None
    installations: List[DetectedInstallation] = field(default_factory=list)
    has_conflict: bool = False
    requires_review: bool = False
    review_reason: str = ""
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "status": self.status.value,
            "active_installation": self.active_installation.to_dict() if self.active_installation else None,
            "installations": [i.to_dict() for i in self.installations],
            "has_conflict": self.has_conflict,
            "requires_review": self.requires_review,
            "review_reason": self.review_reason,
            "message": self.message,
        }


class MultiSourceDetector:
    """
    Discovers multiple installation sources for tools across platforms.
    Resolves active vs shadowed binaries via PATH precedence.
    Correlates installations with ManagedFootprintRegistry.
    """

    def __init__(
        self,
        footprint_registry: Optional[ManagedFootprintRegistry] = None,
        path_resolver: Optional[Callable[[str], List[str]]] = None,
        version_prober: Optional[Callable[[str], Optional[str]]] = None,
        host_os: Optional[str] = None,
    ) -> None:
        self.footprint_registry = footprint_registry or ManagedFootprintRegistry()
        self._path_resolver = path_resolver or self._default_find_all_on_path
        self._version_prober = version_prober or self._default_probe_version
        self.host_os = host_os or platform.system()

    @staticmethod
    def _default_find_all_on_path(executable: str) -> List[str]:
        """Discovers all occurrences of an executable across PATH directories."""
        pathext = os.environ.get("PATHEXT", "").split(os.pathsep) if os.name == "nt" else [""]
        paths = os.environ.get("PATH", "").split(os.pathsep)
        found: List[str] = []
        seen: Set[str] = set()

        for p in paths:
            if not p:
                continue
            for ext in pathext:
                full = os.path.join(p, f"{executable}{ext}" if ext and not executable.endswith(ext) else executable)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    normalized = os.path.normcase(os.path.normpath(full))
                    if normalized not in seen:
                        seen.add(normalized)
                        found.append(full)
        return found

    @staticmethod
    def _default_probe_version(path: str) -> Optional[str]:
        """Probes an executable directly for its version."""
        try:
            import subprocess
            res = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if res.returncode == 0 and res.stdout:
                import re
                match = re.search(r"(\d+\.\d+(?:\.\d+)?)", res.stdout)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None

    def detect_installations(
        self,
        canonical_id: str,
        custom_installations: Optional[List[DetectedInstallation]] = None,
    ) -> MultiSourceAnalysisResult:
        """
        Detects all installation sources for a given canonical ID.
        If custom_installations are provided (e.g. for testing), they are used directly.
        """
        if custom_installations is not None:
            installs = list(custom_installations)
        else:
            installs = self._discover_host_installations(canonical_id)

        # Correlate with footprint registry
        managed_inst = self.footprint_registry.get_installation(canonical_id)
        for inst in installs:
            if managed_inst:
                # Check if this installation matches the managed record
                is_match = False
                if managed_inst.package_id and inst.package_id and managed_inst.package_id == inst.package_id:
                    is_match = True
                elif managed_inst.installation_root and inst.installation_root:
                    if os.path.normcase(os.path.normpath(managed_inst.installation_root)) == os.path.normcase(os.path.normpath(inst.installation_root)):
                        is_match = True
                elif managed_inst.executables and inst.executable_path:
                    for ex in managed_inst.executables:
                        if os.path.normcase(os.path.normpath(ex)) == os.path.normcase(os.path.normpath(inst.executable_path)):
                            is_match = True
                            break
                elif managed_inst.package_manager == inst.source_type.value:
                    is_match = True

                if is_match:
                    inst.ownership_state = managed_inst.ownership_state
            if inst.ownership_state == OwnershipState.UNKNOWN:
                # If not registered in footprint, check default ownership
                inst.ownership_state = OwnershipState.EXTERNAL

        # Identify active installation (first by PATH precedence)
        active_inst: Optional[DetectedInstallation] = None
        for inst in installs:
            if inst.is_active:
                active_inst = inst
                break
        if not active_inst and installs:
            # First one is default active if on PATH
            installs[0].is_active = True
            active_inst = installs[0]

        has_conflict = len(installs) > 1
        requires_review = False
        review_reason = ""

        if has_conflict:
            # Check if any non-active installation has unmanaged / ambiguous ownership
            unmanaged_redundants = [
                i for i in installs
                if i != active_inst and i.ownership_state != OwnershipState.PC_DOCTOR_MANAGED
            ]
            if unmanaged_redundants:
                requires_review = True
                sources_str = ", ".join([f"{i.source_type.value} ({i.ownership_state.value})" for i in unmanaged_redundants])
                review_reason = f"Multiple installation sources detected. Redundant installation(s) [{sources_str}] are not managed by PC Doctor and require human review."
            else:
                review_reason = f"Multiple installation sources detected for '{canonical_id}'. Redundant installations are verified PC_DOCTOR_MANAGED."

            status = MultiSourceStatus.REVIEW_REQUIRED if requires_review else MultiSourceStatus.MULTIPLE_SOURCES_DETECTED
            msg = f"Found {len(installs)} installation sources for '{canonical_id}'."
        else:
            status = MultiSourceStatus.NO_CONFLICT
            msg = f"Single installation source detected for '{canonical_id}'."

        return MultiSourceAnalysisResult(
            canonical_id=canonical_id,
            status=status,
            active_installation=active_inst,
            installations=installs,
            has_conflict=has_conflict,
            requires_review=requires_review,
            review_reason=review_reason,
            message=msg,
        )

    def _discover_host_installations(self, canonical_id: str) -> List[DetectedInstallation]:
        """Performs host binary and package manager discovery across PATH."""
        discovered: List[DetectedInstallation] = []
        executables_on_path = self._path_resolver(canonical_id)

        for idx, exec_path in enumerate(executables_on_path):
            norm_path = os.path.normpath(exec_path).lower()
            source = InstallationSourceType.STANDALONE_PATH

            # Determine source heuristics from path
            if "winget" in norm_path or "localcache" in norm_path:
                source = InstallationSourceType.WINGET
            elif "chocolatey" in norm_path or "choco" in norm_path:
                source = InstallationSourceType.CHOCOLATEY
            elif "scoop" in norm_path:
                source = InstallationSourceType.SCOOP
            elif "homebrew" in norm_path or "cellar" in norm_path or "/usr/local/bin" in norm_path:
                source = InstallationSourceType.HOMEBREW
            elif "/snap/" in norm_path:
                source = InstallationSourceType.SNAP
            elif "/var/lib/flatpak" in norm_path or ".local/share/flatpak" in norm_path:
                source = InstallationSourceType.FLATPAK
            elif "/usr/bin" in norm_path or "/bin" in norm_path:
                source = InstallationSourceType.SYSTEM

            ver = self._version_prober(exec_path)
            discovered.append(
                DetectedInstallation(
                    canonical_id=canonical_id,
                    source_type=source,
                    executable_path=exec_path,
                    installation_root=os.path.dirname(exec_path),
                    version=ver,
                    is_active=(idx == 0),
                    ownership_state=OwnershipState.UNKNOWN,
                    package_id=canonical_id,
                )
            )

        return discovered


class MultiSourceRemediator:
    """
    Authoritative remediation manager for Problem #56.
    Enforces safe multi-source migration:
    1. Target source is prepared/installed and verified BEFORE old source is removed.
    2. Old redundant source is removed ONLY if verified as PC_DOCTOR_MANAGED.
    3. Unmanaged/user sources route strictly to REVIEW_REQUIRED (no unconfirmed deletions).
    4. All mutations execute strictly through CentralizedExecutionEngine.
    5. Post-migration verification and state rescan.
    """

    def __init__(
        self,
        execution_engine: Optional[CentralizedExecutionEngine] = None,
        detector: Optional[MultiSourceDetector] = None,
        footprint_registry: Optional[ManagedFootprintRegistry] = None,
    ) -> None:
        self.engine = execution_engine or default_engine
        self.footprint_registry = footprint_registry or ManagedFootprintRegistry()
        self.detector = detector or MultiSourceDetector(footprint_registry=self.footprint_registry)

    def remediate_multiple_sources(
        self,
        canonical_id: str,
        target_source: InstallationSourceType,
        custom_analysis: Optional[MultiSourceAnalysisResult] = None,
        approved: Optional[bool] = None,
        target_install_command: Optional[str] = None,
        target_verify_fn: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Executes safe migration/consolidation of multiple installation sources.
        """
        analysis = custom_analysis or self.detector.detect_installations(canonical_id)

        if not analysis.has_conflict:
            return {
                "success": True,
                "status": MultiSourceStatus.NO_CONFLICT.value,
                "canonical_id": canonical_id,
                "message": f"No multi-source conflict for '{canonical_id}'. Single installation present.",
                "analysis": analysis.to_dict(),
            }

        # Identify target installation instance and redundant installations
        target_inst = next((i for i in analysis.installations if i.source_type == target_source), None)
        redundant_installs = [i for i in analysis.installations if i.source_type != target_source]

        # STEP 1: Strict Ownership Boundary Check
        # Check if any redundant installation is NOT managed by PC Doctor
        unmanaged_redundants = [
            i for i in redundant_installs
            if i.ownership_state != OwnershipState.PC_DOCTOR_MANAGED
        ]

        if unmanaged_redundants:
            unmanaged_summary = ", ".join([f"{i.source_type.value} at {i.executable_path or i.installation_root or 'unknown'}" for i in unmanaged_redundants])
            reason = (
                f"Cannot automatically remove redundant installation(s) for '{canonical_id}': "
                f"[{unmanaged_summary}] are not managed by PC Doctor (Ownership: {[i.ownership_state.value for i in unmanaged_redundants]}). "
                "Automated deletion of user-installed or unmanaged binaries is forbidden. Manual review required."
            )
            structured_logger.log_event(
                operation="MULTI_SOURCE_REMEDIATION",
                application=canonical_id,
                identity=canonical_id,
                status=MultiSourceStatus.REVIEW_REQUIRED.value,
                message=reason,
                command="",
                details={"requires_review": True, "unmanaged_redundants": [i.to_dict() for i in unmanaged_redundants]},
            )
            return {
                "success": False,
                "status": MultiSourceStatus.REVIEW_REQUIRED.value,
                "canonical_id": canonical_id,
                "requires_review": True,
                "reason": reason,
                "message": reason,
                "analysis": analysis.to_dict(),
            }

        # STEP 2: Target Source Preparation & Verification
        # The target source MUST be verified before we touch or remove any old redundant source!
        target_ready = False
        if target_inst and target_inst.executable_path and (not target_verify_fn or target_verify_fn()):
            target_ready = True
        elif target_install_command:
            # Install target source via CentralizedExecutionEngine
            install_outcome = self.engine.execute_command(
                command=target_install_command,
                target=canonical_id,
                operation="INSTALL",
                source=target_source.value,
                approved=approved,
            )
            if not install_outcome.success:
                msg = f"Failed to prepare target installation source '{target_source.value}' for '{canonical_id}': {install_outcome.stderr or install_outcome.message}"
                structured_logger.log_event(
                    operation="MULTI_SOURCE_REMEDIATION",
                    application=canonical_id,
                    identity=canonical_id,
                    status=MultiSourceStatus.TARGET_VERIFICATION_FAILED.value,
                    message=msg,
                    command=target_install_command,
                )
                return {
                    "success": False,
                    "status": MultiSourceStatus.TARGET_VERIFICATION_FAILED.value,
                    "canonical_id": canonical_id,
                    "message": msg,
                    "details": {"install_outcome": install_outcome.to_dict()},
                }
            # Verify target after install
            if target_verify_fn and not target_verify_fn():
                msg = f"Target installation source '{target_source.value}' executed, but target functional verification failed."
                return {
                    "success": False,
                    "status": MultiSourceStatus.TARGET_VERIFICATION_FAILED.value,
                    "canonical_id": canonical_id,
                    "message": msg,
                }
            target_ready = True
        elif target_verify_fn and target_verify_fn():
            target_ready = True

        if not target_ready:
            msg = f"Target source '{target_source.value}' for '{canonical_id}' is not verified. Aborting redundant source removal to prevent loss of working tool."
            return {
                "success": False,
                "status": MultiSourceStatus.TARGET_VERIFICATION_FAILED.value,
                "canonical_id": canonical_id,
                "message": msg,
            }

        # STEP 3: Safe Removal of Verified PC_DOCTOR_MANAGED Redundant Sources
        removal_outcomes: List[ExecutionOutcome] = []
        for red in redundant_installs:
            # Generate uninstallation command based on source
            uninst_cmd = self._build_uninstall_command(red)
            if uninst_cmd:
                rem_outcome = self.engine.execute_command(
                    command=uninst_cmd,
                    target=canonical_id,
                    operation="UNINSTALL",
                    source=red.source_type.value,
                    approved=approved,
                )
                removal_outcomes.append(rem_outcome)
                if not rem_outcome.success:
                    msg = f"Failed to remove managed redundant source '{red.source_type.value}' for '{canonical_id}': {rem_outcome.stderr or rem_outcome.message}"
                    return {
                        "success": False,
                        "status": MultiSourceStatus.REDUNDANT_REMOVAL_FAILED.value,
                        "canonical_id": canonical_id,
                        "message": msg,
                        "details": {"removal_outcomes": [r.to_dict() for r in removal_outcomes]},
                    }
            # Update footprint registry
            self.footprint_registry.record_uninstall(canonical_id)

        # STEP 4: Final Verification Probe
        final_check = self.detector.detect_installations(canonical_id)
        if final_check.has_conflict:
            msg = f"Multi-source remediation executed, but secondary sources are still detected for '{canonical_id}'."
            return {
                "success": False,
                "status": MultiSourceStatus.FINAL_VERIFICATION_FAILED.value,
                "canonical_id": canonical_id,
                "message": msg,
                "analysis": final_check.to_dict(),
            }

        # STEP 5: Rescan
        state_refresher.refresh_tool_state(canonical_id)

        # STEP 6: Structured Logging
        msg = f"Successfully consolidated '{canonical_id}' to primary source '{target_source.value}'. Removed {len(redundant_installs)} managed redundant source(s)."
        structured_logger.log_event(
            operation="MULTI_SOURCE_REMEDIATION",
            application=canonical_id,
            identity=canonical_id,
            status=MultiSourceStatus.MIGRATION_SUCCESS.value,
            message=msg,
            details={
                "target_source": target_source.value,
                "removed_sources": [r.source_type.value for r in redundant_installs],
            },
        )

        return {
            "success": True,
            "status": MultiSourceStatus.MIGRATION_SUCCESS.value,
            "canonical_id": canonical_id,
            "target_source": target_source.value,
            "removed_sources": [r.source_type.value for r in redundant_installs],
            "message": msg,
            "final_analysis": final_check.to_dict(),
        }

    def _build_uninstall_command(self, inst: DetectedInstallation) -> Optional[str]:
        """Builds structured package manager uninstallation command."""
        st = inst.source_type
        pkg_id = inst.package_id or inst.canonical_id

        if st == InstallationSourceType.WINGET:
            return f"winget uninstall --id {pkg_id} --exact --silent"
        elif st == InstallationSourceType.CHOCOLATEY:
            return f"choco uninstall {pkg_id} -y"
        elif st == InstallationSourceType.SCOOP:
            return f"scoop uninstall {pkg_id}"
        elif st == InstallationSourceType.HOMEBREW:
            return f"brew uninstall {pkg_id}"
        elif st == InstallationSourceType.APT:
            return f"apt-get remove -y {pkg_id}"
        elif st == InstallationSourceType.DNF:
            return f"dnf remove -y {pkg_id}"
        elif st == InstallationSourceType.PACMAN:
            return f"pacman -Rns --noconfirm {pkg_id}"
        elif st == InstallationSourceType.ZYPPER:
            return f"zypper --non-interactive remove -y {pkg_id}"
        elif st == InstallationSourceType.APK:
            return f"apk del {pkg_id}"
        elif st == InstallationSourceType.SNAP:
            return f"snap remove {pkg_id}"
        elif st == InstallationSourceType.FLATPAK:
            return f"flatpak uninstall -y {pkg_id}"
        elif st == InstallationSourceType.STANDALONE_PATH and inst.executable_path:
            return f"rm -f {inst.executable_path}"
        return None


# Global singleton instances
multi_source_detector = MultiSourceDetector()
multi_source_remediator = MultiSourceRemediator()
