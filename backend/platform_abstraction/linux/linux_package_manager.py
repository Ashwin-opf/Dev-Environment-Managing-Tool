"""
platform_abstraction/linux/linux_package_manager.py — Linux Package Manager Providers and Resolver.

Implements authoritative package manager abstractions for:
- APT (Debian, Ubuntu, Mint, Pop!_OS)
- DNF (Fedora, RHEL, CentOS, Rocky, Alma)
- Pacman (Arch Linux, Manjaro)
- Zypper (openSUSE, SLES)
- APK (Alpine Linux)

Key Guarantees:
1. Pure abstraction layer: NEVER spawns mutations via direct subprocess calls.
2. Generates structured commands for ingestion by ExecutionResolver / ExecutionPlan.
3. Communicates `requires_elevation = True` without injecting raw sudo/pkexec.
4. Distinguishes Canonical Identity from Distribution Package Identity.
5. Deterministic provider selection anchored to LinuxDistribution and package ownership.
6. Structured failure classification: PACKAGE_MANAGER_UNAVAILABLE, PACKAGE_NOT_FOUND,
   REPOSITORY_UNAVAILABLE, PERMISSION_DENIED, PACKAGE_OPERATION_FAILED, VERSION_PARSE_FAILED.
7. Explicit tool compatibility model with strict review boundaries.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from platform_abstraction.linux.linux_distribution import (
    LinuxArchitecture,
    LinuxDistribution,
    LinuxDistributionFamily,
)

logger = logging.getLogger("pc_doctor.platform.linux.package_manager")


class LinuxPackageManagerName(str, Enum):
    """Supported Linux package manager identifiers."""
    APT = "apt"
    DNF = "dnf"
    PACMAN = "pacman"
    ZYPPER = "zypper"
    APK = "apk"
    UNKNOWN = "unknown"


class PackageOperationStatus(str, Enum):
    """Normalized package manager operation and error classifications."""
    SUCCESS = "SUCCESS"
    PACKAGE_MANAGER_UNAVAILABLE = "PACKAGE_MANAGER_UNAVAILABLE"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    REPOSITORY_UNAVAILABLE = "REPOSITORY_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    PACKAGE_OPERATION_FAILED = "PACKAGE_OPERATION_FAILED"
    VERSION_PARSE_FAILED = "VERSION_PARSE_FAILED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"


class PackageVerificationState(str, Enum):
    """Normalized verification probe states."""
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    VERSION_MATCHES = "VERSION_MATCHES"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    NOT_INSTALLED = "NOT_INSTALLED"
    VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"


@dataclass
class LinuxPackageOperationResult:
    """Structured result from a package manager probe or operation evaluation."""
    status: PackageOperationStatus
    command: List[str]
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    installed_version: Optional[str] = None
    candidate_version: Optional[str] = None
    message: str = ""
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.status == PackageOperationStatus.SUCCESS


class LinuxPackageManagerProvider(ABC):
    """
    Abstract contract for Linux package manager providers.
    Generates structured operations and interprets output without mutating the host directly.
    """

    def __init__(self, runner: Optional[Callable[[List[str]], Tuple[int, str, str]]] = None) -> None:
        self._runner = runner or self._default_read_runner

    @staticmethod
    def _default_read_runner(cmd: List[str]) -> Tuple[int, str, str]:
        """Read-only subprocess executor for queries and probes (never for mutations)."""
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            return (res.returncode, res.stdout or "", res.stderr or "")
        except FileNotFoundError:
            return (127, "", f"Executable not found: {cmd[0] if cmd else ''}")
        except Exception as exc:
            return (1, "", str(exc))

    @property
    @abstractmethod
    def name(self) -> LinuxPackageManagerName:
        """The package manager identifier."""
        pass

    @property
    def requires_elevation(self) -> bool:
        """Indicates whether install/update/uninstall operations require elevated privileges."""
        return True

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the package manager binary exists on the system."""
        pass

    @abstractmethod
    def version(self) -> Optional[str]:
        """Detects the installed package manager version."""
        pass

    @abstractmethod
    def identify_package(self, canonical_id: str) -> str:
        """Maps canonical tool identity to distribution package name."""
        pass

    @abstractmethod
    def is_installed(self, package_name: str) -> bool:
        """Queries whether the package is currently installed."""
        pass

    @abstractmethod
    def installed_version(self, package_name: str) -> Optional[str]:
        """Returns the version currently installed on the host."""
        pass

    @abstractmethod
    def candidate_version(self, package_name: str) -> Optional[str]:
        """Returns the latest candidate version available from upstream repositories."""
        pass

    @abstractmethod
    def check_package_ownership(self, path_or_name: str) -> bool:
        """Determines whether a file or package is owned by this package manager database."""
        pass

    @abstractmethod
    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        """Builds native installation command arguments."""
        pass

    @abstractmethod
    def build_update_command(self, package_name: str) -> List[str]:
        """Builds native upgrade/update command arguments."""
        pass

    @abstractmethod
    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        """Builds native uninstallation command arguments."""
        pass

    @abstractmethod
    def build_refresh_command(self) -> List[str]:
        """Builds native repository metadata refresh command arguments."""
        pass

    @abstractmethod
    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        """Verifies package installation status and version compliance."""
        pass

    @abstractmethod
    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        """Translates raw process output into structured failure taxonomy."""
        pass


class AptPackageManagerProvider(LinuxPackageManagerProvider):
    """Authoritative provider for Debian/Ubuntu APT (apt-get, dpkg, apt-cache)."""

    PACKAGE_MAPPINGS: Dict[str, str] = {
        "git": "git",
        "python": "python3",
        "python3": "python3",
        "pip": "python3-pip",
        "node": "nodejs",
        "nodejs": "nodejs",
        "npm": "npm",
        "docker": "docker.io",
        "ripgrep": "ripgrep",
        "curl": "curl",
        "neovim": "neovim",
        "golang": "golang-go",
        "go": "golang-go",
        "rust": "rustc",
        "rustc": "rustc",
        "cargo": "cargo",
        "build-essential": "build-essential",
    }

    @property
    def name(self) -> LinuxPackageManagerName:
        return LinuxPackageManagerName.APT

    def is_available(self) -> bool:
        return shutil.which("apt-get") is not None or shutil.which("apt") is not None

    def version(self) -> Optional[str]:
        code, out, _ = self._runner(["apt-get", "--version"])
        if code == 0 and out:
            # First line: "apt 2.7.14 (amd64)"
            first_line = out.splitlines()[0]
            tokens = first_line.split()
            if len(tokens) >= 2:
                return tokens[1]
        return None

    def identify_package(self, canonical_id: str) -> str:
        clean = canonical_id.lower().strip()
        return self.PACKAGE_MAPPINGS.get(clean, clean)

    def is_installed(self, package_name: str) -> bool:
        code, out, _ = self._runner(["dpkg-query", "-W", "-f=${Status}", package_name])
        return (code == 0 and "install ok installed" in out.lower())

    def installed_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["dpkg-query", "-W", "-f=${Version}", package_name])
        if code == 0 and out.strip():
            return out.strip()
        return None

    def candidate_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["apt-cache", "policy", package_name])
        if code == 0 and out:
            for line in out.splitlines():
                if "Candidate:" in line:
                    cand = line.split("Candidate:", 1)[1].strip()
                    if cand and cand != "(none)":
                        return cand
        return None

    def check_package_ownership(self, path_or_name: str) -> bool:
        if os.path.exists(path_or_name) or path_or_name.startswith("/"):
            code, out, _ = self._runner(["dpkg", "-S", path_or_name])
            return (code == 0 and ":" in out)
        return self.is_installed(path_or_name)

    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        target = f"{package_name}={version}" if version else package_name
        return ["apt-get", "install", "-y", target]

    def build_update_command(self, package_name: str) -> List[str]:
        return ["apt-get", "install", "--only-upgrade", "-y", package_name]

    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        action = "purge" if purge else "remove"
        return ["apt-get", action, "-y", package_name]

    def build_refresh_command(self) -> List[str]:
        return ["apt-get", "update"]

    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        if not self.is_installed(package_name):
            return PackageVerificationState.NOT_INSTALLED
        if expected_version:
            curr = self.installed_version(package_name)
            if curr == expected_version or (curr and curr.startswith(expected_version)):
                return PackageVerificationState.VERSION_MATCHES
            return PackageVerificationState.VERSION_MISMATCH
        return PackageVerificationState.INSTALLED

    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        merged = f"{stdout}\n{stderr}".lower()
        if "unable to locate package" in merged or "no package found" in merged:
            return PackageOperationStatus.PACKAGE_NOT_FOUND
        if "could not get lock" in merged or "unable to acquire the dpkg frontend lock" in merged:
            return PackageOperationStatus.RESOURCE_LOCKED
        if "permission denied" in merged or "are you root" in merged or exit_code == 100 and "lock" in merged:
            return PackageOperationStatus.PERMISSION_DENIED
        if "failed to fetch" in merged or "temporary failure resolving" in merged:
            return PackageOperationStatus.REPOSITORY_UNAVAILABLE
        if exit_code == 0:
            return PackageOperationStatus.SUCCESS
        return PackageOperationStatus.PACKAGE_OPERATION_FAILED


class DnfPackageManagerProvider(LinuxPackageManagerProvider):
    """Authoritative provider for Fedora/RHEL/CentOS DNF and RPM."""

    PACKAGE_MAPPINGS: Dict[str, str] = {
        "git": "git",
        "python": "python3",
        "python3": "python3",
        "pip": "python3-pip",
        "node": "nodejs",
        "nodejs": "nodejs",
        "npm": "npm",
        "docker": "moby-engine",
        "ripgrep": "ripgrep",
        "curl": "curl",
        "neovim": "neovim",
        "golang": "golang",
        "go": "golang",
        "rust": "rust",
        "rustc": "rust",
        "cargo": "cargo",
    }

    @property
    def name(self) -> LinuxPackageManagerName:
        return LinuxPackageManagerName.DNF

    def is_available(self) -> bool:
        return shutil.which("dnf") is not None

    def version(self) -> Optional[str]:
        code, out, _ = self._runner(["dnf", "--version"])
        if code == 0 and out:
            # Line 1: version number
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if lines:
                return lines[0].split()[0]
        return None

    def identify_package(self, canonical_id: str) -> str:
        clean = canonical_id.lower().strip()
        return self.PACKAGE_MAPPINGS.get(clean, clean)

    def is_installed(self, package_name: str) -> bool:
        code, _, _ = self._runner(["rpm", "-q", package_name])
        return (code == 0)

    def installed_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", package_name])
        if code == 0 and out.strip():
            return out.strip()
        return None

    def candidate_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["dnf", "info", package_name, "--quiet"])
        if code == 0 and out:
            for line in out.splitlines():
                if line.startswith("Version") and ":" in line:
                    return line.split(":", 1)[1].strip()
        return None

    def check_package_ownership(self, path_or_name: str) -> bool:
        if os.path.exists(path_or_name) or path_or_name.startswith("/"):
            code, _, _ = self._runner(["rpm", "-qf", path_or_name])
            return (code == 0)
        return self.is_installed(path_or_name)

    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        target = f"{package_name}-{version}" if version else package_name
        return ["dnf", "install", "-y", target]

    def build_update_command(self, package_name: str) -> List[str]:
        return ["dnf", "upgrade", "-y", package_name]

    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        return ["dnf", "remove", "-y", package_name]

    def build_refresh_command(self) -> List[str]:
        return ["dnf", "makecache"]

    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        if not self.is_installed(package_name):
            return PackageVerificationState.NOT_INSTALLED
        if expected_version:
            curr = self.installed_version(package_name)
            if curr and expected_version in curr:
                return PackageVerificationState.VERSION_MATCHES
            return PackageVerificationState.VERSION_MISMATCH
        return PackageVerificationState.INSTALLED

    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        merged = f"{stdout}\n{stderr}".lower()
        if "no match for argument" in merged or "unable to find a match" in merged:
            return PackageOperationStatus.PACKAGE_NOT_FOUND
        if "cannot download repomd.xml" in merged or "failed to synchronize cache" in merged:
            return PackageOperationStatus.REPOSITORY_UNAVAILABLE
        if "you must be root" in merged or "permission denied" in merged:
            return PackageOperationStatus.PERMISSION_DENIED
        if "waiting for process" in merged or "another app is currently holding the rpm lock" in merged:
            return PackageOperationStatus.RESOURCE_LOCKED
        if exit_code == 0:
            return PackageOperationStatus.SUCCESS
        return PackageOperationStatus.PACKAGE_OPERATION_FAILED


class PacmanPackageManagerProvider(LinuxPackageManagerProvider):
    """Authoritative provider for Arch Linux / Manjaro Pacman."""

    PACKAGE_MAPPINGS: Dict[str, str] = {
        "git": "git",
        "python": "python",
        "python3": "python",
        "pip": "python-pip",
        "node": "nodejs",
        "nodejs": "nodejs",
        "npm": "npm",
        "docker": "docker",
        "ripgrep": "ripgrep",
        "curl": "curl",
        "neovim": "neovim",
        "golang": "go",
        "go": "go",
        "rust": "rust",
        "rustc": "rust",
        "cargo": "rust",
    }

    @property
    def name(self) -> LinuxPackageManagerName:
        return LinuxPackageManagerName.PACMAN

    def is_available(self) -> bool:
        return shutil.which("pacman") is not None

    def version(self) -> Optional[str]:
        code, out, _ = self._runner(["pacman", "--version"])
        if code == 0 and out:
            # Line: "Pacman v6.1.0 - libalpm v14.0.0"
            match = re.search(r"Pacman\s+v?([0-9\.]+)", out, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def identify_package(self, canonical_id: str) -> str:
        clean = canonical_id.lower().strip()
        return self.PACKAGE_MAPPINGS.get(clean, clean)

    def is_installed(self, package_name: str) -> bool:
        code, _, _ = self._runner(["pacman", "-Q", package_name])
        return (code == 0)

    def installed_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["pacman", "-Q", package_name])
        if code == 0 and out:
            tokens = out.strip().split()
            if len(tokens) >= 2:
                return tokens[1]
        return None

    def candidate_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["pacman", "-Si", package_name])
        if code == 0 and out:
            for line in out.splitlines():
                if line.startswith("Version") and ":" in line:
                    return line.split(":", 1)[1].strip()
        return None

    def check_package_ownership(self, path_or_name: str) -> bool:
        if os.path.exists(path_or_name) or path_or_name.startswith("/"):
            code, _, _ = self._runner(["pacman", "-Qo", path_or_name])
            return (code == 0)
        return self.is_installed(path_or_name)

    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        return ["pacman", "-S", "--noconfirm", package_name]

    def build_update_command(self, package_name: str) -> List[str]:
        return ["pacman", "-S", "--noconfirm", package_name]

    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        return ["pacman", "-Rns", "--noconfirm", package_name]

    def build_refresh_command(self) -> List[str]:
        return ["pacman", "-Sy"]

    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        if not self.is_installed(package_name):
            return PackageVerificationState.NOT_INSTALLED
        if expected_version:
            curr = self.installed_version(package_name)
            if curr and expected_version in curr:
                return PackageVerificationState.VERSION_MATCHES
            return PackageVerificationState.VERSION_MISMATCH
        return PackageVerificationState.INSTALLED

    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        merged = f"{stdout}\n{stderr}".lower()
        if "target not found" in merged:
            return PackageOperationStatus.PACKAGE_NOT_FOUND
        if "failed retrieving file" in merged or "could not resolve host" in merged:
            return PackageOperationStatus.REPOSITORY_UNAVAILABLE
        if "you cannot perform this operation unless you are root" in merged or "permission denied" in merged:
            return PackageOperationStatus.PERMISSION_DENIED
        if "db.lck" in merged:
            return PackageOperationStatus.RESOURCE_LOCKED
        if exit_code == 0:
            return PackageOperationStatus.SUCCESS
        return PackageOperationStatus.PACKAGE_OPERATION_FAILED


class ZypperPackageManagerProvider(LinuxPackageManagerProvider):
    """Authoritative provider for openSUSE/SLES Zypper."""

    PACKAGE_MAPPINGS: Dict[str, str] = {
        "git": "git",
        "python": "python3",
        "python3": "python3",
        "pip": "python3-pip",
        "node": "nodejs",
        "nodejs": "nodejs",
        "npm": "npm",
        "docker": "docker",
        "ripgrep": "ripgrep",
        "curl": "curl",
        "neovim": "neovim",
        "golang": "go",
        "go": "go",
        "rust": "rust",
        "rustc": "rust",
    }

    @property
    def name(self) -> LinuxPackageManagerName:
        return LinuxPackageManagerName.ZYPPER

    def is_available(self) -> bool:
        return shutil.which("zypper") is not None

    def version(self) -> Optional[str]:
        code, out, _ = self._runner(["zypper", "--version"])
        if code == 0 and out:
            # "zypper 1.14.68"
            tokens = out.strip().split()
            if len(tokens) >= 2:
                return tokens[1]
        return None

    def identify_package(self, canonical_id: str) -> str:
        clean = canonical_id.lower().strip()
        return self.PACKAGE_MAPPINGS.get(clean, clean)

    def is_installed(self, package_name: str) -> bool:
        code, _, _ = self._runner(["rpm", "-q", package_name])
        return (code == 0)

    def installed_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", package_name])
        if code == 0 and out.strip():
            return out.strip()
        return None

    def candidate_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["zypper", "--non-interactive", "info", package_name])
        if code == 0 and out:
            for line in out.splitlines():
                if line.startswith("Version") and ":" in line:
                    return line.split(":", 1)[1].strip()
        return None

    def check_package_ownership(self, path_or_name: str) -> bool:
        if os.path.exists(path_or_name) or path_or_name.startswith("/"):
            code, _, _ = self._runner(["rpm", "-qf", path_or_name])
            return (code == 0)
        return self.is_installed(path_or_name)

    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        return ["zypper", "--non-interactive", "install", "-y", package_name]

    def build_update_command(self, package_name: str) -> List[str]:
        return ["zypper", "--non-interactive", "update", "-y", package_name]

    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        return ["zypper", "--non-interactive", "remove", "-y", package_name]

    def build_refresh_command(self) -> List[str]:
        return ["zypper", "--non-interactive", "refresh"]

    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        if not self.is_installed(package_name):
            return PackageVerificationState.NOT_INSTALLED
        if expected_version:
            curr = self.installed_version(package_name)
            if curr and expected_version in curr:
                return PackageVerificationState.VERSION_MATCHES
            return PackageVerificationState.VERSION_MISMATCH
        return PackageVerificationState.INSTALLED

    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        merged = f"{stdout}\n{stderr}".lower()
        if "package not found" in merged or "not found in package names" in merged:
            return PackageOperationStatus.PACKAGE_NOT_FOUND
        if "retrieval of the repository" in merged or "cannot access" in merged:
            return PackageOperationStatus.REPOSITORY_UNAVAILABLE
        if "root privileges are required" in merged or "permission denied" in merged:
            return PackageOperationStatus.PERMISSION_DENIED
        if "zypp is locked" in merged:
            return PackageOperationStatus.RESOURCE_LOCKED
        if exit_code == 0:
            return PackageOperationStatus.SUCCESS
        return PackageOperationStatus.PACKAGE_OPERATION_FAILED


class ApkPackageManagerProvider(LinuxPackageManagerProvider):
    """Authoritative provider for Alpine Linux APK."""

    PACKAGE_MAPPINGS: Dict[str, str] = {
        "git": "git",
        "python": "python3",
        "python3": "python3",
        "pip": "py3-pip",
        "node": "nodejs",
        "nodejs": "nodejs",
        "npm": "npm",
        "docker": "docker",
        "ripgrep": "ripgrep",
        "curl": "curl",
        "neovim": "neovim",
        "golang": "go",
        "go": "go",
        "rust": "rust",
        "rustc": "rust",
        "cargo": "cargo",
    }

    @property
    def name(self) -> LinuxPackageManagerName:
        return LinuxPackageManagerName.APK

    def is_available(self) -> bool:
        return shutil.which("apk") is not None

    def version(self) -> Optional[str]:
        code, out, _ = self._runner(["apk", "--version"])
        if code == 0 and out:
            # "apk-tools 2.14.0, compiled for x86_64"
            match = re.search(r"apk-tools\s+([0-9\.]+)", out)
            if match:
                return match.group(1)
        return None

    def identify_package(self, canonical_id: str) -> str:
        clean = canonical_id.lower().strip()
        return self.PACKAGE_MAPPINGS.get(clean, clean)

    def is_installed(self, package_name: str) -> bool:
        code, out, _ = self._runner(["apk", "info", "-e", package_name])
        return (code == 0 and package_name in out)

    def installed_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["apk", "info", "-d", package_name])
        if code == 0 and out:
            # First line: "git-2.43.0-r0 description:"
            first = out.splitlines()[0] if out.splitlines() else ""
            if "-" in first:
                prefix = f"{package_name}-"
                if first.startswith(prefix):
                    ver_part = first[len(prefix):].split()[0]
                    return ver_part
        return None

    def candidate_version(self, package_name: str) -> Optional[str]:
        code, out, _ = self._runner(["apk", "info", "-r", package_name])
        if code == 0 and out:
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if lines:
                return lines[0].replace(f"{package_name}-", "")
        return None

    def check_package_ownership(self, path_or_name: str) -> bool:
        if os.path.exists(path_or_name) or path_or_name.startswith("/"):
            code, out, _ = self._runner(["apk", "info", "-W", path_or_name])
            return (code == 0 and "is owned by" in out)
        return self.is_installed(path_or_name)

    def build_install_command(self, package_name: str, version: Optional[str] = None) -> List[str]:
        return ["apk", "add", "--no-cache", package_name]

    def build_update_command(self, package_name: str) -> List[str]:
        return ["apk", "upgrade", package_name]

    def build_uninstall_command(self, package_name: str, purge: bool = False) -> List[str]:
        return ["apk", "del", package_name]

    def build_refresh_command(self) -> List[str]:
        return ["apk", "update"]

    def verify_package(self, package_name: str, expected_version: Optional[str] = None) -> PackageVerificationState:
        if not self.is_installed(package_name):
            return PackageVerificationState.NOT_INSTALLED
        if expected_version:
            curr = self.installed_version(package_name)
            if curr and expected_version in curr:
                return PackageVerificationState.VERSION_MATCHES
            return PackageVerificationState.VERSION_MISMATCH
        return PackageVerificationState.INSTALLED

    def classify_failure(self, exit_code: int, stdout: str, stderr: str) -> PackageOperationStatus:
        merged = f"{stdout}\n{stderr}".lower()
        if "unsatisfiable" in merged or "no such package" in merged:
            return PackageOperationStatus.PACKAGE_NOT_FOUND
        if "network is unreachable" in merged or "temporary error" in merged:
            return PackageOperationStatus.REPOSITORY_UNAVAILABLE
        if "permission denied" in merged:
            return PackageOperationStatus.PERMISSION_DENIED
        if exit_code == 0:
            return PackageOperationStatus.SUCCESS
        return PackageOperationStatus.PACKAGE_OPERATION_FAILED


class LinuxPackageManagerResolver:
    """
    Deterministic provider resolution for Linux environments.
    Selects the authoritative package manager provider using distribution identity,
    family compatibility, package ownership, and tool availability.
    """

    def __init__(
        self,
        distribution: Optional[LinuxDistribution] = None,
        custom_providers: Optional[Dict[LinuxPackageManagerName, LinuxPackageManagerProvider]] = None,
    ) -> None:
        self.distribution = distribution
        self.providers: Dict[LinuxPackageManagerName, LinuxPackageManagerProvider] = custom_providers or {
            LinuxPackageManagerName.APT: AptPackageManagerProvider(),
            LinuxPackageManagerName.DNF: DnfPackageManagerProvider(),
            LinuxPackageManagerName.PACMAN: PacmanPackageManagerProvider(),
            LinuxPackageManagerName.ZYPPER: ZypperPackageManagerProvider(),
            LinuxPackageManagerName.APK: ApkPackageManagerProvider(),
        }

    def resolve_provider_for_distribution(
        self,
        distro: Optional[LinuxDistribution] = None,
        installed_binary_path: Optional[str] = None,
    ) -> Tuple[Optional[LinuxPackageManagerProvider], str, bool]:
        """
        Deterministically resolves the preferred package manager.
        Returns: (provider, selection_reason, requires_review).
        """
        d = distro or self.distribution

        # 1. Unknown distribution check
        if not d or d.distribution_family == LinuxDistributionFamily.UNKNOWN or not d.is_supported:
            return (
                None,
                f"Unknown or unsupported Linux distribution '{d.distribution if d else 'unknown'}'. Manual review required.",
                True,
            )

        # 2. Package ownership override: if an installed binary is proven owned by a specific PM
        if installed_binary_path:
            for pm_name, prov in self.providers.items():
                if prov.is_available() and prov.check_package_ownership(installed_binary_path):
                    reason = f"Provider '{pm_name.value}' selected based on verified ownership of '{installed_binary_path}'."
                    return (prov, reason, False)

        # 3. Family policy preference
        family_map = {
            LinuxDistributionFamily.DEBIAN: LinuxPackageManagerName.APT,
            LinuxDistributionFamily.REDHAT: LinuxPackageManagerName.DNF,
            LinuxDistributionFamily.ARCH: LinuxPackageManagerName.PACMAN,
            LinuxDistributionFamily.SUSE: LinuxPackageManagerName.ZYPPER,
            LinuxDistributionFamily.ALPINE: LinuxPackageManagerName.APK,
        }

        preferred_pm = family_map.get(d.distribution_family)
        if preferred_pm and preferred_pm in self.providers:
            prov = self.providers[preferred_pm]
            # Verify host binary availability if live
            if prov.is_available():
                reason = f"Provider '{preferred_pm.value}' selected for family '{d.distribution_family.value}' (distribution '{d.distribution}')."
                return (prov, reason, False)
            else:
                # Primary family tool unavailable
                reason = f"Primary package manager '{preferred_pm.value}' for family '{d.distribution_family.value}' is not available on PATH."
                return (None, reason, True)

        return (None, f"No supported provider found for distribution '{d.distribution}'.", True)

    def remediate_outdated_repository(
        self,
        canonical_id: str,
        expected_version: Optional[str] = None,
        distro: Optional[LinuxDistribution] = None,
        execution_engine: Optional[Any] = None,
        approved: Optional[bool] = None,
        auto_refresh: bool = True,
    ) -> Dict[str, Any]:
        """
        Remediates Problem #54: Linux repository package outdated.
        Executes a multi-step remediation strictly through CentralizedExecutionEngine:
        1. Distribution and provider verification (rejects unknown distros -> REVIEW_REQUIRED)
        2. Official repository metadata refresh (apt-get update, dnf makecache, etc.)
        3. Native package upgrade/install
        4. Functional version verification probe
        5. Machine & tool state rescan
        6. Structured audit logging
        """
        from execution_engine import execution_engine as default_engine
        from state_refresh import state_refresher
        from structured_logger import structured_logger

        engine = execution_engine or default_engine
        d = distro or self.distribution
        prov, reason, req_review = self.resolve_provider_for_distribution(d)

        if not prov or req_review:
            msg = f"Remediation blocked for '{canonical_id}': {reason}"
            structured_logger.log_event(
                operation="LINUX_REPOSITORY_REMEDIATION",
                application=canonical_id,
                identity=canonical_id,
                status="REVIEW_REQUIRED",
                message=msg,
                command="",
                details={"requires_review": True, "reason": reason},
            )
            return {
                "success": False,
                "status": "REVIEW_REQUIRED",
                "canonical_id": canonical_id,
                "distribution": d.distribution if d else "unknown",
                "package_manager": None,
                "message": msg,
                "details": {"requires_review": True, "reason": reason},
            }

        pkg_name = prov.identify_package(canonical_id)
        initial_version = prov.installed_version(pkg_name)
        refresh_outcome = None

        # Step 1: Metadata Refresh
        if auto_refresh:
            refresh_cmd = " ".join(prov.build_refresh_command())
            refresh_outcome = engine.execute_command(
                command=refresh_cmd,
                target=canonical_id,
                operation="REFRESH_METADATA",
                source="LINUX_PROVIDER",
                approved=approved,
                elevate=prov.requires_elevation,
            )
            if not refresh_outcome.success:
                msg = f"Repository metadata refresh failed for '{canonical_id}' via {prov.name.value}: {refresh_outcome.stderr or refresh_outcome.message}"
                structured_logger.log_event(
                    operation="LINUX_REPOSITORY_REMEDIATION",
                    application=canonical_id,
                    identity=canonical_id,
                    status="REPOSITORY_UNAVAILABLE",
                    message=msg,
                    command=refresh_cmd,
                    return_code=refresh_outcome.return_code,
                )
                return {
                    "success": False,
                    "status": "REPOSITORY_UNAVAILABLE",
                    "canonical_id": canonical_id,
                    "distribution": d.distribution if d else "unknown",
                    "package_manager": prov.name.value,
                    "package_name": pkg_name,
                    "refresh_outcome": refresh_outcome,
                    "message": msg,
                }

        # Step 2: Native Package Update/Upgrade
        update_cmd = " ".join(prov.build_update_command(pkg_name))
        update_outcome = engine.execute_command(
            command=update_cmd,
            target=canonical_id,
            operation="UPDATE",
            source="LINUX_PROVIDER",
            approved=approved,
            elevate=prov.requires_elevation,
        )

        if not update_outcome.success:
            msg = f"Package update failed for '{canonical_id}' via {prov.name.value}: {update_outcome.stderr or update_outcome.message}"
            return {
                "success": False,
                "status": update_outcome.status,
                "canonical_id": canonical_id,
                "distribution": d.distribution if d else "unknown",
                "package_manager": prov.name.value,
                "package_name": pkg_name,
                "refresh_outcome": refresh_outcome,
                "update_outcome": update_outcome,
                "initial_version": initial_version,
                "message": msg,
            }

        # Step 3: Functional Verification Probe (Level 2)
        final_version = prov.installed_version(pkg_name)
        if expected_version:
            if final_version and (final_version == expected_version or final_version.startswith(expected_version)):
                success = True
                status = "SUCCESS"
                msg = f"Successfully updated '{canonical_id}' to expected version {final_version} via {prov.name.value}."
            else:
                success = False
                status = "VERIFICATION_FAILED"
                msg = f"Package update executed, but version verification failed: expected '{expected_version}', got '{final_version}'."
        else:
            if initial_version and final_version and initial_version == final_version:
                success = False
                status = "VERIFICATION_FAILED"
                msg = f"Package update executed, but version did not change ({final_version}). Upstream repository may have no newer version."
            elif final_version:
                success = True
                status = "SUCCESS"
                msg = f"Successfully updated '{canonical_id}' from {initial_version or 'unknown'} to {final_version} via {prov.name.value}."
            else:
                success = False
                status = "VERIFICATION_FAILED"
                msg = f"Package update executed, but tool '{canonical_id}' is not installed after update."

        # Step 4: Rescan
        state_refresher.refresh_tool_state(canonical_id)

        # Step 5: Structured Logging
        structured_logger.log_event(
            operation="LINUX_REPOSITORY_REMEDIATION",
            application=canonical_id,
            identity=canonical_id,
            status=status,
            message=msg,
            command=update_cmd,
            return_code=update_outcome.return_code if update_outcome else 0,
            versions={"initial": initial_version, "final": final_version, "expected": expected_version},
            details={
                "distribution": d.distribution if d else "unknown",
                "package_manager": prov.name.value,
                "package_name": pkg_name,
            },
        )

        return {
            "success": success,
            "status": status,
            "canonical_id": canonical_id,
            "distribution": d.distribution if d else "unknown",
            "package_manager": prov.name.value,
            "package_name": pkg_name,
            "refresh_outcome": refresh_outcome,
            "update_outcome": update_outcome,
            "initial_version": initial_version,
            "final_version": final_version,
            "message": msg,
        }


@dataclass
class ToolCompatibilityRecord:
    """Explicit cross-distribution tool compatibility mapping."""
    canonical_id: str
    distribution_family: LinuxDistributionFamily
    package_name: str
    package_manager: LinuxPackageManagerName
    supported: bool
    requires_elevation: bool = True
    install_command: str = ""
    update_command: str = ""
    uninstall_command: str = ""
    verification_probe: str = ""
    notes: str = ""


class LinuxToolCompatibilityMatrix:
    """Authoritative tool-distribution-package manager compatibility definitions."""

    @staticmethod
    def get_compatibility(
        canonical_id: str,
        distro: LinuxDistribution,
    ) -> ToolCompatibilityRecord:
        """Retrieves verified compatibility record for a canonical tool on a Linux distribution."""
        fam = distro.distribution_family
        clean_id = canonical_id.lower().strip()

        if fam == LinuxDistributionFamily.UNKNOWN or not distro.is_supported:
            return ToolCompatibilityRecord(
                canonical_id=clean_id,
                distribution_family=fam,
                package_name=clean_id,
                package_manager=LinuxPackageManagerName.UNKNOWN,
                supported=False,
                notes=f"Distribution '{distro.distribution}' requires manual review.",
            )

        # Resolve provider
        resolver = LinuxPackageManagerResolver(distro)
        prov, reason, req_review = resolver.resolve_provider_for_distribution(distro)

        if not prov or req_review:
            return ToolCompatibilityRecord(
                canonical_id=clean_id,
                distribution_family=fam,
                package_name=clean_id,
                package_manager=LinuxPackageManagerName.UNKNOWN,
                supported=False,
                notes=reason,
            )

        pkg_name = prov.identify_package(clean_id)
        inst_cmd = " ".join(prov.build_install_command(pkg_name))
        upd_cmd = " ".join(prov.build_update_command(pkg_name))
        uninst_cmd = " ".join(prov.build_uninstall_command(pkg_name))

        return ToolCompatibilityRecord(
            canonical_id=clean_id,
            distribution_family=fam,
            package_name=pkg_name,
            package_manager=prov.name,
            supported=True,
            requires_elevation=prov.requires_elevation,
            install_command=inst_cmd,
            update_command=upd_cmd,
            uninstall_command=uninst_cmd,
            verification_probe=f"{prov.name.value} query for {pkg_name}",
            notes=f"Verified compatible on {distro.distribution_name} ({distro.architecture}) via {prov.name.value}",
        )
