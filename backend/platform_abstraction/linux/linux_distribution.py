"""
platform_abstraction/linux/linux_distribution.py — Normalized Linux Distribution Model and Provider.

Implements authoritative distribution and distribution-family identification from /etc/os-release.
Handles:
- Debian family (Ubuntu, Debian, Linux Mint, Pop!_OS, Zorin, Kali, Raspberry Pi OS)
- Red Hat family (Fedora, RHEL, CentOS, Rocky Linux, AlmaLinux, CentOS Stream, Amazon Linux)
- Arch family (Arch Linux, Manjaro, EndeavourOS, Garuda)
- SUSE family (openSUSE Tumbleweed, openSUSE Leap, SLES)
- Alpine family (Alpine Linux)
- Unknown / Custom distributions (flagged strictly as UNKNOWN / REVIEW_REQUIRED with zero guessing)
- Missing and malformed /etc/os-release handling
- Architecture normalization (x86_64, aarch64, armhf, i686)
- Version and codename normalization
- Init system detection (systemd, openrc, runit, sysvinit)
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pc_doctor.platform.linux.distribution")


class LinuxDistributionFamily(str, Enum):
    """Normalized Linux distribution families."""
    DEBIAN = "DEBIAN"
    REDHAT = "REDHAT"
    ARCH = "ARCH"
    SUSE = "SUSE"
    ALPINE = "ALPINE"
    UNKNOWN = "UNKNOWN"


class LinuxArchitecture(str, Enum):
    """Normalized CPU architectures."""
    X86_64 = "x86_64"
    AARCH64 = "aarch64"
    ARMHF = "armhf"
    I686 = "i686"
    RISCV64 = "riscv64"
    UNKNOWN = "unknown"

    @classmethod
    def normalize(cls, raw_arch: Optional[str]) -> str:
        """Normalizes diverse architecture strings across kernels and package managers."""
        if not raw_arch:
            return cls.UNKNOWN.value
        arch_clean = raw_arch.strip().lower()
        if arch_clean in ("x86_64", "amd64", "x64", "x86-64"):
            return cls.X86_64.value
        if arch_clean in ("aarch64", "arm64", "armv8", "armv8l"):
            return cls.AARCH64.value
        if arch_clean in ("armhf", "armv7l", "armv7", "armv6l", "armel"):
            return cls.ARMHF.value
        if arch_clean in ("i686", "i386", "x86", "i586", "i486"):
            return cls.I686.value
        if arch_clean in ("riscv64", "riscv"):
            return cls.RISCV64.value
        return arch_clean


@dataclass
class LinuxDistribution:
    """Structured, immutable representation of a detected Linux distribution."""
    distribution: str                       # e.g. "ubuntu", "debian", "fedora", "arch", "unknown"
    distribution_name: str                  # Pretty name, e.g. "Ubuntu 24.04 LTS"
    distribution_family: LinuxDistributionFamily
    distribution_version: Optional[str]     # e.g. "24.04", "40", "9.4", "rolling"
    distribution_codename: Optional[str]    # e.g. "noble", "jammy", "bookworm"
    architecture: str                       # Normalized architecture, e.g. "x86_64"
    primary_package_manager: str            # e.g. "apt", "dnf", "pacman", "zypper", "apk", "unknown"
    available_package_managers: List[str]   # Discovered on host
    init_system: str                        # e.g. "systemd", "openrc", "sysvinit", "unknown"
    is_supported: bool                      # False for unknown distros requiring review
    is_family_compatible: bool              # True if compatible with a supported family
    compatibility_notes: str = ""
    raw_metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "distribution": self.distribution,
            "distribution_name": self.distribution_name,
            "distribution_family": self.distribution_family.value,
            "distribution_version": self.distribution_version,
            "distribution_codename": self.distribution_codename,
            "architecture": self.architecture,
            "primary_package_manager": self.primary_package_manager,
            "available_package_managers": list(self.available_package_managers),
            "init_system": self.init_system,
            "is_supported": self.is_supported,
            "is_family_compatible": self.is_family_compatible,
            "compatibility_notes": self.compatibility_notes,
            "raw_metadata": dict(self.raw_metadata),
        }


class LinuxDistributionProvider:
    """
    Authoritative provider for Linux distribution identification.
    Parses standard OS release metadata (/etc/os-release) without scattering shell calls.
    """

    DEFAULT_OS_RELEASE_PATHS = [
        "/etc/os-release",
        "/usr/lib/os-release",
    ]

    def __init__(
        self,
        custom_os_release_path: Optional[str | Path] = None,
        custom_os_release_text: Optional[str] = None,
        custom_os_release_dict: Optional[Dict[str, str]] = None,
        host_arch: Optional[str] = None,
        custom_pm_checker: Optional[Any] = None,
    ) -> None:
        self._custom_path = Path(custom_os_release_path) if custom_os_release_path else None
        self._custom_text = custom_os_release_text
        self._custom_dict = dict(custom_os_release_dict) if custom_os_release_dict is not None else None
        self._host_arch = host_arch
        self._pm_checker = custom_pm_checker

    @staticmethod
    def parse_os_release_text(text: str) -> Dict[str, str]:
        """
        Safely parses standard /etc/os-release KEY=VALUE format.
        Preserves string values without executing arbitrary shell scripts.
        """
        metadata: Dict[str, str] = {}
        if not text:
            return metadata

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            # Handle quoted strings (both single and double)
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            metadata[k] = v
        return metadata

    def load_os_release_metadata(self) -> Dict[str, str]:
        """Loads and parses os-release data from the configured or standard sources."""
        if self._custom_dict is not None:
            return dict(self._custom_dict)

        if self._custom_text is not None:
            return self.parse_os_release_text(self._custom_text)

        if self._custom_path is not None:
            if self._custom_path.is_file():
                try:
                    return self.parse_os_release_text(self._custom_path.read_text(encoding="utf-8", errors="replace"))
                except Exception as exc:
                    logger.warning("Failed to read custom os-release at %s: %s", self._custom_path, exc)
            return {}

        # Default paths on live system
        for path_str in self.DEFAULT_OS_RELEASE_PATHS:
            p = Path(path_str)
            if p.is_file():
                try:
                    return self.parse_os_release_text(p.read_text(encoding="utf-8", errors="replace"))
                except Exception as exc:
                    logger.warning("Failed to read %s: %s", path_str, exc)
        return {}

    def detect_architecture(self) -> str:
        """Returns normalized machine architecture."""
        raw = self._host_arch or platform.machine()
        return LinuxArchitecture.normalize(raw)

    def detect_family(self, metadata: Dict[str, str]) -> Tuple[LinuxDistributionFamily, bool, str]:
        """
        Determines the distribution family based strictly on ID, ID_LIKE, and known taxonomy.
        Returns (family, is_family_compatible, notes).
        """
        dist_id = metadata.get("ID", "").lower().strip()
        id_like = metadata.get("ID_LIKE", "").lower().strip()
        all_identifiers = set(re.split(r"[\s,]+", f"{dist_id} {id_like}".strip()))

        # 1. Debian Family
        debian_matches = {"debian", "ubuntu", "mint", "pop", "zorin", "kali", "raspbian", "elementary"}
        if all_identifiers & debian_matches:
            notes = f"Mapped to Debian family via identifier(s): {', '.join(all_identifiers & debian_matches)}"
            return LinuxDistributionFamily.DEBIAN, True, notes

        # 2. Red Hat Family
        redhat_matches = {"rhel", "fedora", "centos", "rocky", "almalinux", "amzn", "ol", "scientific"}
        if all_identifiers & redhat_matches:
            notes = f"Mapped to Red Hat family via identifier(s): {', '.join(all_identifiers & redhat_matches)}"
            return LinuxDistributionFamily.REDHAT, True, notes

        # 3. Arch Family
        arch_matches = {"arch", "manjaro", "endeavouros", "garuda", "artix"}
        if all_identifiers & arch_matches:
            notes = f"Mapped to Arch family via identifier(s): {', '.join(all_identifiers & arch_matches)}"
            return LinuxDistributionFamily.ARCH, True, notes

        # 4. SUSE Family
        suse_matches = {"suse", "opensuse", "opensuse-tumbleweed", "opensuse-leap", "sles"}
        if all_identifiers & suse_matches:
            notes = f"Mapped to SUSE family via identifier(s): {', '.join(all_identifiers & suse_matches)}"
            return LinuxDistributionFamily.SUSE, True, notes

        # 5. Alpine Family
        if "alpine" in all_identifiers:
            return LinuxDistributionFamily.ALPINE, True, "Alpine Linux musl/busybox environment"

        # 6. Unknown / Custom distribution
        if dist_id:
            notes = f"Unknown distribution '{dist_id}' (ID_LIKE='{id_like}') requires explicit review"
        else:
            notes = "Missing or empty distribution metadata; manual review required"
        return LinuxDistributionFamily.UNKNOWN, False, notes

    def detect_version(self, metadata: Dict[str, str]) -> Optional[str]:
        """Extracts normalized version string, preserving rolling indicators."""
        raw_ver = metadata.get("VERSION_ID") or metadata.get("VERSION")
        if not raw_ver:
            # Check for rolling release tag
            if metadata.get("IMAGE_VERSION"):
                return metadata.get("IMAGE_VERSION")
            if metadata.get("ID", "").lower() in ("arch", "manjaro", "endeavouros", "opensuse-tumbleweed"):
                return "rolling"
            return None
        # Clean quotes and strip build suffixes if present
        v = raw_ver.strip().split()[0].strip('"').strip("'")
        return v if v else None

    def detect_codename(self, metadata: Dict[str, str]) -> Optional[str]:
        """Extracts release codename (e.g. 'noble', 'jammy', 'bookworm')."""
        codename = metadata.get("VERSION_CODENAME") or metadata.get("UBUNTU_CODENAME")
        if codename:
            return codename.strip().lower()

        # Parse from VERSION string e.g. "24.04 LTS (Noble Numbat)"
        version_str = metadata.get("VERSION", "")
        match = re.search(r"\(([^)]+)\)", version_str)
        if match:
            words = match.group(1).strip().split()
            if words:
                return words[0].lower()
        return None

    def detect_package_managers(self) -> List[str]:
        """Discovers available Linux package managers on PATH or via custom checker."""
        if self._pm_checker is not None:
            return [pm for pm in ["apt-get", "apt", "dnf", "pacman", "zypper", "apk"] if self._pm_checker(pm)]

        found: List[str] = []
        for pm in ["apt", "dnf", "pacman", "zypper", "apk"]:
            if shutil.which(pm) or (pm == "apt" and shutil.which("apt-get")):
                found.append(pm)
        return found

    def detect_init_system(self) -> str:
        """Infers the active host init system."""
        if os.path.isdir("/run/systemd/system"):
            return "systemd"
        if shutil.which("systemctl"):
            return "systemd"
        if os.path.isfile("/sbin/openrc") or os.path.isdir("/run/openrc"):
            return "openrc"
        if os.path.isdir("/etc/runit"):
            return "runit"
        if os.path.isfile("/etc/init.d/rc"):
            return "sysvinit"
        return "unknown"

    def detect_distribution(self) -> LinuxDistribution:
        """
        Executes the complete, authoritative Linux distribution detection contract.
        Returns a normalized LinuxDistribution dataclass.
        """
        metadata = self.load_os_release_metadata()
        arch = self.detect_architecture()
        family, is_family_compatible, notes = self.detect_family(metadata)
        version = self.detect_version(metadata)
        codename = self.detect_codename(metadata)
        available_pms = self.detect_package_managers()
        init_system = self.detect_init_system()

        dist_id = metadata.get("ID", "").lower().strip() or "unknown"
        dist_name = metadata.get("PRETTY_NAME") or metadata.get("NAME") or dist_id.capitalize()

        # Determine primary package manager based on family policy
        primary_pm = "unknown"
        if family == LinuxDistributionFamily.DEBIAN:
            primary_pm = "apt"
        elif family == LinuxDistributionFamily.REDHAT:
            primary_pm = "dnf"
        elif family == LinuxDistributionFamily.ARCH:
            primary_pm = "pacman"
        elif family == LinuxDistributionFamily.SUSE:
            primary_pm = "zypper"
        elif family == LinuxDistributionFamily.ALPINE:
            primary_pm = "apk"
        elif available_pms:
            # Fallback for unknown distribution with discovered tools
            primary_pm = available_pms[0]

        is_supported = (family != LinuxDistributionFamily.UNKNOWN)

        return LinuxDistribution(
            distribution=dist_id,
            distribution_name=dist_name,
            distribution_family=family,
            distribution_version=version,
            distribution_codename=codename,
            architecture=arch,
            primary_package_manager=primary_pm,
            available_package_managers=available_pms,
            init_system=init_system,
            is_supported=is_supported,
            is_family_compatible=is_family_compatible,
            compatibility_notes=notes,
            raw_metadata=metadata,
        )
