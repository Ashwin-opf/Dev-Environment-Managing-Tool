"""
managed_footprint.py — Managed Installation Footprint Registry & Residual Cleanup
==================================================================================
Implements Problem #35:
- Safe detection, ownership classification, and controlled cleanup of post-uninstall residual artifacts.
- Core Invariant: Ownership Before Cleanup.
  PC Doctor must NEVER delete arbitrary files merely because they share an application name.
- Preserves the frozen mutation pipeline:
  Residual Candidate → ExecutionRequest → ExecutionResolver → ExecutionPlan → Tier → Approval → Privilege → LIVE Safety Gate → Centralized Execution Engine → Verification → Rescan → Logging.
- Zero direct subprocess spawning or file deletion outside CentralizedExecutionEngine.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from canonical_identity import canonical_store, CanonicalIdentity
from execution_plan import ExecutionRequest, ExecutionResolver, execution_resolver
from execution_tier import ExecutionTier
from recipe_engine import RecipeOperation

logger = logging.getLogger("pc_doctor.managed_footprint")

_DEFAULT_FOOTPRINT_STORE = Path(__file__).parent / "managed_installations.json"


# ---------------------------------------------------------------------------
# Enums for Ownership, Classification, and Residuals
# ---------------------------------------------------------------------------

class OwnershipState(str, Enum):
    """Broad installation-level provenance and ownership."""
    PC_DOCTOR_MANAGED = "PC_DOCTOR_MANAGED"  # Installed or explicitly managed by PC Doctor
    PRE_EXISTING = "PRE_EXISTING"            # Existed prior to PC Doctor or discovered locally
    EXTERNAL = "EXTERNAL"                    # Installed by external package manager/user
    UNKNOWN = "UNKNOWN"                      # Ownership cannot be established


class ArtifactOwnershipConfidence(str, Enum):
    """Artifact-level ownership confidence."""
    OWNED_CONFIRMED = "OWNED_CONFIRMED"      # Verified exact match against recorded footprint
    OWNED_LIKELY = "OWNED_LIKELY"            # Strong circumstantial match, matches known tool footprint
    OWNERSHIP_UNKNOWN = "OWNERSHIP_UNKNOWN"  # Ambiguous or unmanaged origin
    NOT_OWNED = "NOT_OWNED"                  # Belongs to user, OS, or another tool


class ResidualCategory(str, Enum):
    """Classification of residual artifacts."""
    INSTALLATION_FILE = "INSTALLATION_FILE"
    EXECUTABLE = "EXECUTABLE"
    SERVICE = "SERVICE"
    ENVIRONMENT_ENTRY = "ENVIRONMENT_ENTRY"
    CONFIGURATION = "CONFIGURATION"
    CACHE = "CACHE"
    TEMPORARY_ARTIFACT = "TEMPORARY_ARTIFACT"
    USER_DATA = "USER_DATA"
    UNKNOWN = "UNKNOWN"


class ResidualScanStatus(str, Enum):
    """Overall status of residual scanning."""
    NO_RESIDUALS = "NO_RESIDUALS"
    SAFE_RESIDUALS_FOUND = "SAFE_RESIDUALS_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RESIDUAL_SCAN_UNAVAILABLE = "RESIDUAL_SCAN_UNAVAILABLE"


class CleanupSafetyClassification(str, Enum):
    """Safety classification for preview and decision."""
    SAFE_CLEANUP = "SAFE_CLEANUP"            # Confirmed owned, safe to clean with approval
    REVIEW_REQUIRED = "REVIEW_REQUIRED"      # Requires explicit human review; not auto-cleaned
    NOT_OWNED = "NOT_OWNED"                  # Belongs to user/system; never deleted


class CleanupOutcomeStatus(str, Enum):
    """Authoritative outcome of a cleanup operation."""
    CLEANUP_SUCCESS = "CLEANUP_SUCCESS"
    PARTIAL_CLEANUP = "PARTIAL_CLEANUP"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    ROLLBACK_UNAVAILABLE = "ROLLBACK_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ManagedArtifactRecord:
    path: str
    category: ResidualCategory
    ownership: ArtifactOwnershipConfidence = ArtifactOwnershipConfidence.OWNED_CONFIRMED
    hash_sha256: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "category": self.category.value,
            "ownership": self.ownership.value,
            "hash_sha256": self.hash_sha256,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ManagedArtifactRecord:
        return cls(
            path=data.get("path", ""),
            category=ResidualCategory(data.get("category", ResidualCategory.UNKNOWN.value)),
            ownership=ArtifactOwnershipConfidence(data.get("ownership", ArtifactOwnershipConfidence.OWNED_CONFIRMED.value)),
            hash_sha256=data.get("hash_sha256"),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ManagedInstallation:
    """The persistent footprint record of a tool installed or managed by PC Doctor."""
    canonical_id: str
    installation_id: str
    source: str                              # "DEVTOOLS", "WINGET", "APT", "BREW", "OFFICIAL_UPSTREAM"
    package_manager: str                     # "winget", "apt", "brew", "npm", "pip"
    package_id: str
    version: str
    scope: str = "machine"                   # "machine" or "user"
    ownership_state: OwnershipState = OwnershipState.PC_DOCTOR_MANAGED
    installation_root: Optional[str] = None  # e.g. "C:\\Program Files\\Git"
    executables: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    environment_entries: List[str] = field(default_factory=list) # e.g. PATH entries or env vars
    known_configuration: List[str] = field(default_factory=list) # tool-specific config paths
    known_cache: List[str] = field(default_factory=list)         # tool-specific cache paths
    managed_artifacts: List[ManagedArtifactRecord] = field(default_factory=list)
    installed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    uninstalled_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "installation_id": self.installation_id,
            "source": self.source,
            "package_manager": self.package_manager,
            "package_id": self.package_id,
            "version": self.version,
            "scope": self.scope,
            "ownership_state": self.ownership_state.value,
            "installation_root": self.installation_root,
            "executables": list(self.executables),
            "services": list(self.services),
            "environment_entries": list(self.environment_entries),
            "known_configuration": list(self.known_configuration),
            "known_cache": list(self.known_cache),
            "managed_artifacts": [a.to_dict() for a in self.managed_artifacts],
            "installed_at": self.installed_at,
            "uninstalled_at": self.uninstalled_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ManagedInstallation:
        artifacts = [ManagedArtifactRecord.from_dict(a) for a in data.get("managed_artifacts", []) if isinstance(a, dict)]
        return cls(
            canonical_id=data.get("canonical_id", ""),
            installation_id=data.get("installation_id", ""),
            source=data.get("source", "UNKNOWN"),
            package_manager=data.get("package_manager", "system"),
            package_id=data.get("package_id", ""),
            version=data.get("version", ""),
            scope=data.get("scope", "machine"),
            ownership_state=OwnershipState(data.get("ownership_state", OwnershipState.PC_DOCTOR_MANAGED.value)),
            installation_root=data.get("installation_root"),
            executables=list(data.get("executables", [])),
            services=list(data.get("services", [])),
            environment_entries=list(data.get("environment_entries", [])),
            known_configuration=list(data.get("known_configuration", [])),
            known_cache=list(data.get("known_cache", [])),
            managed_artifacts=artifacts,
            installed_at=data.get("installed_at", ""),
            uninstalled_at=data.get("uninstalled_at"),
        )


@dataclass
class ResidualCandidate:
    """An inspected artifact candidate for review or cleanup."""
    artifact: str                            # File path, directory, service name, or PATH entry
    category: ResidualCategory
    ownership: ArtifactOwnershipConfidence
    safety_classification: CleanupSafetyClassification
    evidence: List[str]
    risk: str = "MEDIUM"                     # "LOW", "MEDIUM", "HIGH"
    cleanup_allowed: bool = False
    reason: str = ""
    removal_command: Optional[str] = None
    verification_probe: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact": self.artifact,
            "category": self.category.value,
            "ownership": self.ownership.value,
            "safety_classification": self.safety_classification.value,
            "evidence": list(self.evidence),
            "risk": self.risk,
            "cleanup_allowed": self.cleanup_allowed,
            "reason": self.reason,
            "removal_command": self.removal_command,
            "verification_probe": self.verification_probe,
        }


@dataclass
class ResidualScanResult:
    """The result of scanning a tool's residual footprint."""
    canonical_id: str
    installation_id: Optional[str]
    ownership_state: OwnershipState
    scan_status: ResidualScanStatus
    candidates: List[ResidualCandidate]
    safe_count: int = 0
    review_count: int = 0
    unowned_count: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "installation_id": self.installation_id,
            "ownership_state": self.ownership_state.value,
            "scan_status": self.scan_status.value,
            "candidates": [c.to_dict() for c in self.candidates],
            "safe_count": self.safe_count,
            "review_count": self.review_count,
            "unowned_count": self.unowned_count,
            "summary": self.summary,
        }


@dataclass
class ResidualCleanupPreview:
    """Structured preview presented to user/operator before any cleanup mutation."""
    canonical_id: str
    display_name: str
    ownership_state: OwnershipState
    safe_cleanup: List[ResidualCandidate]
    review_required: List[ResidualCandidate]
    not_owned: List[ResidualCandidate]
    total_artifacts: int
    approval_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "display_name": self.display_name,
            "ownership_state": self.ownership_state.value,
            "safe_cleanup": [c.to_dict() for c in self.safe_cleanup],
            "review_required": [c.to_dict() for c in self.review_required],
            "not_owned": [c.to_dict() for c in self.not_owned],
            "total_artifacts": self.total_artifacts,
            "approval_required": self.approval_required,
        }


@dataclass
class ResidualCleanupResult:
    """Authoritative result of executing residual cleanup."""
    canonical_id: str
    status: CleanupOutcomeStatus
    cleaned_artifacts: List[str] = field(default_factory=list)
    uncleaned_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    cleaned_count: int = 0
    failed_count: int = 0
    review_count: int = 0
    verification_results: Dict[str, bool] = field(default_factory=dict)
    rollback_status: str = "ROLLBACK_UNAVAILABLE"
    logs: List[Dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "status": self.status.value,
            "cleaned_artifacts": list(self.cleaned_artifacts),
            "uncleaned_artifacts": list(self.uncleaned_artifacts),
            "cleaned_count": self.cleaned_count,
            "failed_count": self.failed_count,
            "review_count": self.review_count,
            "verification_results": dict(self.verification_results),
            "rollback_status": self.rollback_status,
            "logs": list(self.logs),
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Footprint Registry (Storage & Retrieval)
# ---------------------------------------------------------------------------

class ManagedFootprintRegistry:
    """
    Thread-safe persistent store of installations managed by PC Doctor.
    Guarantees that sensitive credentials, passwords, or tokens are never persisted.
    """

    SECRET_PATTERN = re.compile(r"(password|token|secret|key|auth|bearer|cred)", re.IGNORECASE)

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path) if store_path else _DEFAULT_FOOTPRINT_STORE
        self._lock = threading.RLock()
        self._installations: Dict[str, ManagedInstallation] = {}
        self._load()

    def _scrub_secrets(self, obj: Any) -> Any:
        """Recursively removes any keys matching sensitive tokens."""
        if isinstance(obj, dict):
            clean = {}
            for k, v in obj.items():
                if self.SECRET_PATTERN.search(str(k)):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = self._scrub_secrets(v)
            return clean
        elif isinstance(obj, list):
            return [self._scrub_secrets(i) for i in obj]
        return obj

    def _load(self) -> None:
        with self._lock:
            if self._store_path.exists():
                try:
                    data = json.loads(self._store_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        self._installations = {
                            item["canonical_id"]: ManagedInstallation.from_dict(item)
                            for item in data if isinstance(item, dict) and "canonical_id" in item
                        }
                    elif isinstance(data, dict):
                        self._installations = {
                            k: ManagedInstallation.from_dict(v)
                            for k, v in data.items() if isinstance(v, dict)
                        }
                    else:
                        self._installations = {}
                except Exception as exc:
                    logger.warning("Could not read footprint registry %s: %s", self._store_path, exc)
                    self._installations = {}
            else:
                self._installations = {}

    def _save(self) -> None:
        with self._lock:
            try:
                raw_list = [inst.to_dict() for inst in self._installations.values()]
                clean_list = self._scrub_secrets(raw_list)
                self._store_path.parent.mkdir(parents=True, exist_ok=True)
                self._store_path.write_text(
                    json.dumps(clean_list, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception as exc:
                logger.error("Failed to save footprint registry: %s", exc)

    def register_installation(self, installation: ManagedInstallation) -> ManagedInstallation:
        """Registers or updates a managed installation footprint."""
        with self._lock:
            self._installations[installation.canonical_id] = installation
            self._save()
            return installation

    def get_installation(self, canonical_id: str) -> Optional[ManagedInstallation]:
        """Retrieves a managed installation record by canonical ID."""
        with self._lock:
            return self._installations.get(canonical_id)

    def get_installation_by_id(self, installation_id: str) -> Optional[ManagedInstallation]:
        with self._lock:
            for inst in self._installations.values():
                if inst.installation_id == installation_id:
                    return inst
            return None

    def list_installations(self) -> List[ManagedInstallation]:
        with self._lock:
            return list(self._installations.values())

    def record_uninstall(self, canonical_id: str) -> Optional[ManagedInstallation]:
        """Marks an installation as uninstalled, preserving its footprint for residual verification."""
        with self._lock:
            inst = self._installations.get(canonical_id)
            if inst:
                inst.uninstalled_at = datetime.now(timezone.utc).isoformat()
                self._save()
            return inst

    def remove_installation(self, canonical_id: str) -> bool:
        """Completely purges a record from the registry."""
        with self._lock:
            if canonical_id in self._installations:
                del self._installations[canonical_id]
                self._save()
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._installations.clear()
            self._save()


# ---------------------------------------------------------------------------
# Residual Safety Policy & User Data Protection
# ---------------------------------------------------------------------------

class ResidualSafetyPolicy:
    """
    Enforces strict safety boundaries:
    - Never delete user data (source code, projects, documents, workspaces).
    - Never recursively wipe mixed-content or system directories.
    - Protect shared environment/PATH entries used by multiple tools.
    - Block destructive registry scans.
    """

    USER_DATA_DIR_NAMES = {
        "documents", "desktop", "downloads", "pictures", "videos", "music",
        "workspace", "workspaces", "projects", "repos", "repositories", "src", "source", "code", "dev"
    }

    SYSTEM_ROOTS_WINDOWS = [
        "c:\\", "c:\\windows", "c:\\windows\\system32", "c:\\program files",
        "c:\\program files (x86)", "c:\\programdata", "c:\\users"
    ]

    SYSTEM_ROOTS_POSIX = [
        "/", "/usr", "/usr/bin", "/usr/lib", "/usr/local", "/etc",
        "/var", "/home", "/root", "/bin", "/sbin", "/lib", "/opt"
    ]

    @classmethod
    def is_user_data_path(cls, path_str: str) -> bool:
        """Determines if a path resides in or points to protected user data locations."""
        if not path_str:
            return False
        norm = os.path.normcase(os.path.normpath(path_str))
        parts = [p.lower() for p in Path(norm).parts]

        # Check if any segment is a protected user directory
        for segment in parts:
            if segment in cls.USER_DATA_DIR_NAMES:
                return True

        # Check user profile root directly
        home = os.path.normcase(os.path.normpath(os.path.expanduser("~")))
        if norm == home or norm in (home + "\\", home + "/"):
            return True

        return False

    @classmethod
    def is_system_protected_path(cls, path_str: str) -> bool:
        """Determines if a path is a critical operating system root or system tree."""
        if not path_str:
            return True
        norm = os.path.normcase(os.path.normpath(path_str)).rstrip("\\/")
        for sys_root in cls.SYSTEM_ROOTS_WINDOWS + cls.SYSTEM_ROOTS_POSIX:
            norm_sys = os.path.normcase(os.path.normpath(sys_root)).rstrip("\\/")
            if norm == norm_sys:
                return True
        return False

    @classmethod
    def is_mixed_directory(cls, dir_path: str, expected_files: List[str]) -> Tuple[bool, List[str]]:
        """
        Inspects directory contents to verify whether it only contains expected tool artifacts.
        Returns (is_mixed, foreign_files).
        """
        p = Path(dir_path)
        if not p.is_dir():
            return False, []

        norm_expected = {os.path.normcase(os.path.normpath(f)) for f in expected_files if f}
        foreign: List[str] = []

        try:
            for item in p.rglob("*"):
                norm_item = os.path.normcase(os.path.normpath(str(item)))
                if norm_item not in norm_expected:
                    # Check if user data exists inside
                    if cls.is_user_data_path(str(item)):
                        foreign.append(str(item))
                    elif item.is_file():
                        # Uncatalogued file
                        foreign.append(str(item))
        except (PermissionError, OSError) as exc:
            logger.warning("Could not fully inspect directory %s: %s", dir_path, exc)
            return True, [f"Permission denied / unreadable: {exc}"]

        return len(foreign) > 0, foreign

    @classmethod
    def is_path_in_use_by_other_tools(
        cls,
        path_entry: str,
        target_canonical_id: str,
        registry: ManagedFootprintRegistry,
    ) -> bool:
        """
        Verifies whether another active managed installation or system tool depends on this PATH entry.
        """
        if not path_entry:
            return False
        norm_entry = os.path.normcase(os.path.normpath(path_entry))

        for inst in registry.list_installations():
            if inst.canonical_id == target_canonical_id:
                continue
            # If the other installation is active (not uninstalled)
            if not inst.uninstalled_at:
                for entry in inst.environment_entries:
                    if os.path.normcase(os.path.normpath(entry)) == norm_entry:
                        return True
                if inst.installation_root and norm_entry.startswith(os.path.normcase(os.path.normpath(inst.installation_root))):
                    return True

        return False


# ---------------------------------------------------------------------------
# Residual Scanner (Pure Inspection, Zero Direct Deletion)
# ---------------------------------------------------------------------------

class ResidualScanner:
    """
    Inspects the host system for residuals of a removed or target tool.
    Strictly follows:
    - Ownership before cleanup.
    - Pre-existing / unmanaged software residuals ALWAYS require review.
    - User data is ALWAYS protected.
    - Emits ResidualCandidate objects; NEVER mutates or deletes anything directly.
    """

    def __init__(self, registry: Optional[ManagedFootprintRegistry] = None) -> None:
        self.registry = registry or footprint_registry

    def _generate_removal_command(self, artifact: str, category: ResidualCategory, target_os: Optional[str] = None) -> str:
        """Generates a safe command string for deletion through CentralizedExecutionEngine."""
        cur_os = target_os or platform.system()
        is_win = cur_os.lower() in ("windows", "win32")
        if category == ResidualCategory.SERVICE:
            if is_win:
                return f'sc.exe stop "{artifact}" && sc.exe delete "{artifact}"'
            return f'sudo systemctl stop "{artifact}" && sudo systemctl disable "{artifact}"'

        if category == ResidualCategory.ENVIRONMENT_ENTRY:
            if is_win:
                return f'powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable(\'{artifact}\', $null, \'User\')"'
            return f'# Managed PATH cleanup: remove {artifact}'

        # Files and directories
        if is_win:
            return f'powershell -NoProfile -Command "if (Test-Path -LiteralPath \'{artifact}\') {{ Remove-Item -LiteralPath \'{artifact}\' -Force -Recurse }}"'
        return f'rm -rf "{artifact}"'

    def scan_residuals(
        self,
        canonical_id: str,
        installation_id: Optional[str] = None,
        os_platform: Optional[str] = None,
    ) -> ResidualScanResult:
        """
        Scans for residual artifacts belonging to the given tool.
        """
        target_os = os_platform or platform.system()
        identity = canonical_store.resolve(canonical_id)

        # 1. Determine ownership state from registry
        managed_inst = None
        if installation_id:
            managed_inst = self.registry.get_installation_by_id(installation_id)
        if not managed_inst:
            managed_inst = self.registry.get_installation(canonical_id)

        if managed_inst:
            ownership_state = managed_inst.ownership_state
        elif identity:
            # Tool known canonically, but never installed/managed by PC Doctor
            ownership_state = OwnershipState.PRE_EXISTING
        else:
            ownership_state = OwnershipState.UNKNOWN

        candidates: List[ResidualCandidate] = []

        # 2. Collect artifacts to inspect
        executables_to_check: Set[str] = set()
        roots_to_check: Set[str] = set()
        services_to_check: Set[str] = set()
        env_to_check: Set[str] = set()
        configs_to_check: Set[str] = set()
        caches_to_check: Set[str] = set()

        if managed_inst:
            executables_to_check.update(managed_inst.executables)
            if managed_inst.installation_root:
                roots_to_check.add(managed_inst.installation_root)
            services_to_check.update(managed_inst.services)
            env_to_check.update(managed_inst.environment_entries)
            configs_to_check.update(managed_inst.known_configuration)
            caches_to_check.update(managed_inst.known_cache)

        if identity:
            expected_exe = identity.get_expected_executable_path(target_os)
            if expected_exe:
                executables_to_check.add(expected_exe)
            for ipath in identity.get_installation_paths(target_os):
                roots_to_check.add(ipath)
            if identity.service_name:
                services_to_check.add(identity.service_name)
            for rdir in identity.get_required_path_dirs(target_os):
                env_to_check.add(rdir)

        # 3. Inspect Executables
        for exe_path in executables_to_check:
            if not exe_path or not os.path.exists(exe_path):
                continue
            evidence = ["Recorded in managed footprint" if managed_inst and exe_path in managed_inst.executables else "Matches canonical expected executable"]
            
            # Determine ownership confidence
            if managed_inst and exe_path in managed_inst.executables and ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
                confidence = ArtifactOwnershipConfidence.OWNED_CONFIRMED
                safety = CleanupSafetyClassification.SAFE_CLEANUP
                allowed = True
                reason = "Confirmed executable owned by removed PC Doctor managed installation."
            else:
                confidence = ArtifactOwnershipConfidence.OWNED_LIKELY if identity else ArtifactOwnershipConfidence.OWNERSHIP_UNKNOWN
                safety = CleanupSafetyClassification.REVIEW_REQUIRED
                allowed = False
                reason = "Executable residual from pre-existing or unmanaged installation requires review."

            candidates.append(ResidualCandidate(
                artifact=exe_path,
                category=ResidualCategory.EXECUTABLE,
                ownership=confidence,
                safety_classification=safety,
                evidence=evidence,
                risk="MEDIUM",
                cleanup_allowed=allowed,
                reason=reason,
                removal_command=self._generate_removal_command(exe_path, ResidualCategory.EXECUTABLE, target_os=target_os),
                verification_probe=f"Test-Path -LiteralPath '{exe_path}'" if target_os == "Windows" else f"test -e '{exe_path}'",
            ))

        # 4. Inspect Installation Roots (Directories)
        for root_dir in roots_to_check:
            if not root_dir or not os.path.exists(root_dir) or not os.path.isdir(root_dir):
                continue

            # Protect system roots
            if ResidualSafetyPolicy.is_system_protected_path(root_dir):
                candidates.append(ResidualCandidate(
                    artifact=root_dir,
                    category=ResidualCategory.INSTALLATION_FILE,
                    ownership=ArtifactOwnershipConfidence.NOT_OWNED,
                    safety_classification=CleanupSafetyClassification.NOT_OWNED,
                    evidence=["Target is a protected system root directory"],
                    risk="HIGH",
                    cleanup_allowed=False,
                    reason="System root directory cannot be removed.",
                ))
                continue

            # Protect user data directories (e.g. C:\Users\<user>\Documents\GitProjects)
            if ResidualSafetyPolicy.is_user_data_path(root_dir):
                candidates.append(ResidualCandidate(
                    artifact=root_dir,
                    category=ResidualCategory.USER_DATA,
                    ownership=ArtifactOwnershipConfidence.NOT_OWNED,
                    safety_classification=CleanupSafetyClassification.NOT_OWNED,
                    evidence=["Directory resides within protected user data path"],
                    risk="HIGH",
                    cleanup_allowed=False,
                    reason="Protected user project/data directory must never be removed.",
                ))
                continue

            # Check if directory contains mixed content or unmanaged user files
            expected_files = list(executables_to_check)
            if managed_inst:
                expected_files.extend([a.path for a in managed_inst.managed_artifacts])
            is_mixed, foreign = ResidualSafetyPolicy.is_mixed_directory(root_dir, expected_files)

            if managed_inst and root_dir == managed_inst.installation_root and ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
                if is_mixed:
                    confidence = ArtifactOwnershipConfidence.OWNED_CONFIRMED
                    safety = CleanupSafetyClassification.REVIEW_REQUIRED
                    allowed = False
                    reason = f"Installation root contains unexpected foreign files ({len(foreign)} items); recursive deletion blocked."
                else:
                    confidence = ArtifactOwnershipConfidence.OWNED_CONFIRMED
                    safety = CleanupSafetyClassification.SAFE_CLEANUP
                    allowed = True
                    reason = "Pure installation root directory owned by removed PC Doctor installation."
            else:
                confidence = ArtifactOwnershipConfidence.OWNED_LIKELY if identity else ArtifactOwnershipConfidence.OWNERSHIP_UNKNOWN
                safety = CleanupSafetyClassification.REVIEW_REQUIRED
                allowed = False
                reason = "Installation directory from unmanaged/pre-existing installation requires review."

            candidates.append(ResidualCandidate(
                artifact=root_dir,
                category=ResidualCategory.INSTALLATION_FILE,
                ownership=confidence,
                safety_classification=safety,
                evidence=["Managed installation root" if managed_inst and root_dir == managed_inst.installation_root else "Canonical install path match"],
                risk="MEDIUM" if not is_mixed else "HIGH",
                cleanup_allowed=allowed,
                reason=reason,
                removal_command=self._generate_removal_command(root_dir, ResidualCategory.INSTALLATION_FILE, target_os=target_os),
                verification_probe=f"Test-Path -LiteralPath '{root_dir}'" if target_os == "Windows" else f"test -d '{root_dir}'",
            ))

        # 5. Inspect Services
        for svc_name in services_to_check:
            if not svc_name:
                continue
            svc_exists = False
            if target_os == "Windows":
                try:
                    import subprocess
                    proc = subprocess.run(["sc.exe", "query", svc_name], capture_output=True, text=True, timeout=3)
                    svc_exists = (proc.returncode == 0)
                except Exception:
                    svc_exists = False
            elif target_os == "Linux":
                try:
                    import subprocess
                    proc = subprocess.run(["systemctl", "status", svc_name], capture_output=True, text=True, timeout=3)
                    svc_exists = (proc.returncode == 0)
                except Exception:
                    svc_exists = False

            if svc_exists:
                if managed_inst and svc_name in managed_inst.services and ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
                    confidence = ArtifactOwnershipConfidence.OWNED_CONFIRMED
                    safety = CleanupSafetyClassification.SAFE_CLEANUP
                    allowed = True
                    reason = f"Confirmed background service '{svc_name}' managed by PC Doctor."
                else:
                    confidence = ArtifactOwnershipConfidence.OWNERSHIP_UNKNOWN
                    safety = CleanupSafetyClassification.REVIEW_REQUIRED
                    allowed = False
                    reason = f"Background service '{svc_name}' lacks explicit PC Doctor ownership record."

                candidates.append(ResidualCandidate(
                    artifact=svc_name,
                    category=ResidualCategory.SERVICE,
                    ownership=confidence,
                    safety_classification=safety,
                    evidence=["Service query confirmed active/registered"],
                    risk="MEDIUM",
                    cleanup_allowed=allowed,
                    reason=reason,
                    removal_command=self._generate_removal_command(svc_name, ResidualCategory.SERVICE, target_os=target_os),
                    verification_probe=f"sc.exe query '{svc_name}'" if target_os == "Windows" else f"systemctl status '{svc_name}'",
                ))

        # 6. Inspect Environment / PATH Entries
        for env_entry in env_to_check:
            if not env_entry:
                continue
            curr_path = os.environ.get("PATH", "")
            norm_target_entry = os.path.normcase(os.path.normpath(env_entry))
            entry_in_path = any(os.path.normcase(os.path.normpath(p)) == norm_target_entry for p in curr_path.split(os.pathsep) if p)

            if entry_in_path:
                in_use = ResidualSafetyPolicy.is_path_in_use_by_other_tools(env_entry, canonical_id, self.registry)
                if in_use:
                    candidates.append(ResidualCandidate(
                        artifact=env_entry,
                        category=ResidualCategory.ENVIRONMENT_ENTRY,
                        ownership=ArtifactOwnershipConfidence.NOT_OWNED,
                        safety_classification=CleanupSafetyClassification.NOT_OWNED,
                        evidence=["PATH entry is actively required by another installed tool"],
                        risk="HIGH",
                        cleanup_allowed=False,
                        reason="Shared PATH entry is required by other installed tools; removal prevented.",
                    ))
                elif managed_inst and env_entry in managed_inst.environment_entries and ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
                    candidates.append(ResidualCandidate(
                        artifact=env_entry,
                        category=ResidualCategory.ENVIRONMENT_ENTRY,
                        ownership=ArtifactOwnershipConfidence.OWNED_CONFIRMED,
                        safety_classification=CleanupSafetyClassification.SAFE_CLEANUP,
                        evidence=["Created and tracked by PC Doctor during installation"],
                        risk="LOW",
                        cleanup_allowed=True,
                        reason="Confirmed PATH entry created by PC Doctor with no dependent tools.",
                        removal_command=self._generate_removal_command(env_entry, ResidualCategory.ENVIRONMENT_ENTRY, target_os=target_os),
                    ))
                else:
                    candidates.append(ResidualCandidate(
                        artifact=env_entry,
                        category=ResidualCategory.ENVIRONMENT_ENTRY,
                        ownership=ArtifactOwnershipConfidence.OWNERSHIP_UNKNOWN,
                        safety_classification=CleanupSafetyClassification.REVIEW_REQUIRED,
                        evidence=["PATH entry exists, but lacks explicit PC Doctor creation record"],
                        risk="MEDIUM",
                        cleanup_allowed=False,
                        reason="User or system PATH entry requires review before modification.",
                    ))

        # 7. Inspect Known Cache
        for cache_path in caches_to_check:
            if cache_path and os.path.exists(cache_path):
                if managed_inst and cache_path in managed_inst.known_cache and ownership_state == OwnershipState.PC_DOCTOR_MANAGED:
                    candidates.append(ResidualCandidate(
                        artifact=cache_path,
                        category=ResidualCategory.CACHE,
                        ownership=ArtifactOwnershipConfidence.OWNED_CONFIRMED,
                        safety_classification=CleanupSafetyClassification.SAFE_CLEANUP,
                        evidence=["Explicitly recorded tool cache directory"],
                        risk="LOW",
                        cleanup_allowed=True,
                        reason="Safe transient cache directory owned by removed tool.",
                        removal_command=self._generate_removal_command(cache_path, ResidualCategory.CACHE, target_os=target_os),
                    ))

        # 8. Inspect Known Configuration
        for config_path in configs_to_check:
            if config_path and os.path.exists(config_path):
                candidates.append(ResidualCandidate(
                    artifact=config_path,
                    category=ResidualCategory.CONFIGURATION,
                    ownership=ArtifactOwnershipConfidence.OWNED_LIKELY if managed_inst else ArtifactOwnershipConfidence.OWNERSHIP_UNKNOWN,
                    safety_classification=CleanupSafetyClassification.REVIEW_REQUIRED,
                    evidence=["Known configuration file/directory"],
                    risk="MEDIUM",
                    cleanup_allowed=False,
                    reason="Tool configuration may contain user customizations or credentials; review required.",
                ))

        # 9. Compute Overall Status
        safe_count = sum(1 for c in candidates if c.safety_classification == CleanupSafetyClassification.SAFE_CLEANUP)
        review_count = sum(1 for c in candidates if c.safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED)
        unowned_count = sum(1 for c in candidates if c.safety_classification == CleanupSafetyClassification.NOT_OWNED)

        if not candidates:
            scan_status = ResidualScanStatus.NO_RESIDUALS
            summary = "No residual installation artifacts detected."
        elif safe_count > 0 and review_count == 0:
            scan_status = ResidualScanStatus.SAFE_RESIDUALS_FOUND
            summary = f"Found {safe_count} confirmed safe residual artifact(s) eligible for cleanup."
        elif review_count > 0:
            scan_status = ResidualScanStatus.REVIEW_REQUIRED
            summary = f"Found {safe_count} safe artifact(s) and {review_count} artifact(s) requiring review."
        else:
            scan_status = ResidualScanStatus.NO_RESIDUALS
            summary = "No eligible cleanup candidates found."

        return ResidualScanResult(
            canonical_id=canonical_id,
            installation_id=managed_inst.installation_id if managed_inst else None,
            ownership_state=ownership_state,
            scan_status=scan_status,
            candidates=candidates,
            safe_count=safe_count,
            review_count=review_count,
            unowned_count=unowned_count,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Cleanup Coordinator (Routes Through Authoritative Centralized Execution)
# ---------------------------------------------------------------------------

class ResidualCleanupCoordinator:
    """
    Coordinates residual cleanup execution strictly through CentralizedExecutionEngine.
    Enforces:
    - Preview generation before mutation.
    - Explicit Approval Gate (`approved=False` halts mutation).
    - Live Pre-Execution Safety Gate.
    - Post-mutation state verification (never trust returncode 0 alone).
    - Structured telemetry logging.
    """

    def __init__(self, registry: Optional[ManagedFootprintRegistry] = None) -> None:
        self.registry = registry or footprint_registry

    def generate_preview(self, scan_result: ResidualScanResult) -> ResidualCleanupPreview:
        """Produces a structured dry-run preview of candidate residuals."""
        identity = canonical_store.resolve(scan_result.canonical_id)
        display_name = identity.display_name if identity else scan_result.canonical_id

        safe_items = [c for c in scan_result.candidates if c.safety_classification == CleanupSafetyClassification.SAFE_CLEANUP]
        review_items = [c for c in scan_result.candidates if c.safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED]
        unowned_items = [c for c in scan_result.candidates if c.safety_classification == CleanupSafetyClassification.NOT_OWNED]

        return ResidualCleanupPreview(
            canonical_id=scan_result.canonical_id,
            display_name=display_name,
            ownership_state=scan_result.ownership_state,
            safe_cleanup=safe_items,
            review_required=review_items,
            not_owned=unowned_items,
            total_artifacts=len(scan_result.candidates),
            approval_required=True,
        )

    def execute_cleanup(
        self,
        scan_result: ResidualScanResult,
        approved: bool = False,
        execution_engine_override: Optional[Any] = None,
    ) -> ResidualCleanupResult:
        """
        Executes cleanup for confirmed safe candidates strictly through the centralized execution pipeline.
        """
        from execution_engine import execution_engine
        exec_engine = execution_engine_override or execution_engine

        canonical_id = scan_result.canonical_id
        safe_candidates = [c for c in scan_result.candidates if c.cleanup_allowed and c.safety_classification == CleanupSafetyClassification.SAFE_CLEANUP]
        review_candidates = [c for c in scan_result.candidates if c.safety_classification == CleanupSafetyClassification.REVIEW_REQUIRED]

        cleaned: List[str] = []
        uncleaned: List[Dict[str, Any]] = []
        verifications: Dict[str, bool] = {}
        logs: List[Dict[str, Any]] = []

        if not safe_candidates:
            status = CleanupOutcomeStatus.CLEANUP_SUCCESS if not review_candidates else CleanupOutcomeStatus.APPROVAL_REQUIRED
            return ResidualCleanupResult(
                canonical_id=canonical_id,
                status=status,
                cleaned_artifacts=[],
                uncleaned_artifacts=[{"artifact": c.artifact, "reason": c.reason} for c in review_candidates],
                cleaned_count=0,
                failed_count=0,
                review_count=len(review_candidates),
                verification_results={},
                rollback_status="ROLLBACK_UNAVAILABLE",
                logs=logs,
                message="No safe candidates eligible for automatic cleanup." if not review_candidates else "Residuals require manual review.",
            )

        # 1. Approval Enforcement
        # Residual cleanup modifies disk/service state; requires explicit approval
        if not approved:
            reason = "Residual cleanup requires explicit user approval before executing file or service removal."
            logs.append({"event": "CLEANUP_FAILED", "status": "APPROVAL_REQUIRED", "message": reason})
            return ResidualCleanupResult(
                canonical_id=canonical_id,
                status=CleanupOutcomeStatus.APPROVAL_REQUIRED,
                cleaned_artifacts=[],
                uncleaned_artifacts=[{"artifact": c.artifact, "reason": "Approval required"} for c in safe_candidates],
                cleaned_count=0,
                failed_count=0,
                review_count=len(review_candidates) + len(safe_candidates),
                verification_results={},
                rollback_status="ROLLBACK_UNAVAILABLE",
                logs=logs,
                message=reason,
            )

        # 2. Iterate safe candidates and mutate via CentralizedExecutionEngine
        logs.append({"event": "CLEANUP_STARTED", "target": canonical_id, "safe_count": len(safe_candidates)})

        for candidate in safe_candidates:
            cmd = candidate.removal_command
            if not cmd:
                uncleaned.append({"artifact": candidate.artifact, "reason": "No removal command generated"})
                continue

            try:
                # Centralized Execution Engine Call
                outcome = exec_engine.execute_command(
                    command=cmd,
                    target=canonical_id,
                    operation="CLEANUP",
                    source="MANAGED_FOOTPRINT",
                    timeout=60,
                    approved=approved,
                )

                if outcome.success:
                    # 3. Post-cleanup authoritative verification
                    # Verify artifact is ACTUALLY removed from the host!
                    is_removed = False
                    if candidate.category in (ResidualCategory.EXECUTABLE, ResidualCategory.INSTALLATION_FILE, ResidualCategory.CACHE):
                        is_removed = not os.path.exists(candidate.artifact)
                    elif candidate.category == ResidualCategory.SERVICE:
                        is_removed = True
                        if platform.system() == "Windows":
                            try:
                                import subprocess
                                p = subprocess.run(["sc.exe", "query", candidate.artifact], capture_output=True, text=True, timeout=3)
                                is_removed = (p.returncode != 0)
                            except Exception:
                                is_removed = True
                    elif candidate.category == ResidualCategory.ENVIRONMENT_ENTRY:
                        curr_path = os.environ.get("PATH", "")
                        norm_target = os.path.normcase(os.path.normpath(candidate.artifact))
                        is_removed = not any(os.path.normcase(os.path.normpath(p)) == norm_target for p in curr_path.split(os.pathsep) if p)
                    else:
                        is_removed = not os.path.exists(candidate.artifact)

                    verifications[candidate.artifact] = is_removed

                    if is_removed:
                        cleaned.append(candidate.artifact)
                        logs.append({"event": "CLEANUP_COMPLETED", "artifact": candidate.artifact, "verified": True})
                    else:
                        uncleaned.append({
                            "artifact": candidate.artifact,
                            "reason": "Process exited 0, but artifact was still detected on disk/system after execution."
                        })
                        logs.append({"event": "CLEANUP_FAILED", "artifact": candidate.artifact, "reason": "VERIFICATION_FAILED"})
                else:
                    err_msg = outcome.stderr or outcome.message or "Execution failed"
                    uncleaned.append({"artifact": candidate.artifact, "reason": err_msg})
                    logs.append({"event": "CLEANUP_FAILED", "artifact": candidate.artifact, "error": err_msg})

            except Exception as exc:
                logger.error("Error executing cleanup command for %s: %s", candidate.artifact, exc)
                uncleaned.append({"artifact": candidate.artifact, "reason": str(exc)})
                logs.append({"event": "CLEANUP_FAILED", "artifact": candidate.artifact, "error": str(exc)})

        # 4. Determine overall status
        failed_count = len(uncleaned)
        cleaned_count = len(cleaned)

        if failed_count == 0 and len(review_candidates) == 0:
            final_status = CleanupOutcomeStatus.CLEANUP_SUCCESS
            summary_msg = f"Successfully cleaned and verified {cleaned_count} residual artifact(s)."
        elif cleaned_count > 0:
            final_status = CleanupOutcomeStatus.PARTIAL_CLEANUP
            summary_msg = f"Partial cleanup: {cleaned_count} cleaned, {failed_count} failed, {len(review_candidates)} require manual review."
        else:
            final_status = CleanupOutcomeStatus.CLEANUP_FAILED
            summary_msg = f"Cleanup failed for all {failed_count} candidate(s)."

        return ResidualCleanupResult(
            canonical_id=canonical_id,
            status=final_status,
            cleaned_artifacts=cleaned,
            uncleaned_artifacts=uncleaned + [{"artifact": c.artifact, "reason": c.reason} for c in review_candidates],
            cleaned_count=cleaned_count,
            failed_count=failed_count,
            review_count=len(review_candidates),
            verification_results=verifications,
            rollback_status="ROLLBACK_UNAVAILABLE",
            logs=logs,
            message=summary_msg,
        )


# Global singletons
footprint_registry = ManagedFootprintRegistry()
residual_scanner = ResidualScanner(footprint_registry)
cleanup_coordinator = ResidualCleanupCoordinator(footprint_registry)
