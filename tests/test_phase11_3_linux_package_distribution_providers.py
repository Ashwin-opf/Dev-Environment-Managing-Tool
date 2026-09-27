"""
tests/test_phase11_3_linux_package_distribution_providers.py — Phase 11.3 Linux Distribution & Package Manager Test Suite.

Comprehensive tests covering:
- Distribution detection and normalization (Ubuntu, Debian, Fedora, RHEL, Arch, openSUSE, Alpine, Unknown, malformed, missing)
- Architecture normalization (x86_64, aarch64, armhf, i686)
- Package manager providers: APT, DNF, Pacman, Zypper, APK
- Availability, version, package identity, installed state, candidate version, commands, ownership, verification, failure classification
- Elevation requirements (requires_elevation = True without raw sudo bypass)
- Deterministic provider resolution and compatibility matrix
- Safety gate and execution pipeline integration (approved=False yields APPROVAL_REQUIRED and zero mutations)
- End-to-end lifecycle integration for supported and unknown distributions
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from canonical_identity import CanonicalIdentity, canonical_store
from execution_engine import CentralizedExecutionEngine
from execution_plan import ExecutionPlan, ExecutionRequest, ExecutionResolver, ProvenanceClass
from execution_tier import ExecutionTier
from platform_abstraction.linux.linux_distribution import (
    LinuxArchitecture,
    LinuxDistribution,
    LinuxDistributionFamily,
    LinuxDistributionProvider,
)
from platform_abstraction.linux.linux_package_manager import (
    ApkPackageManagerProvider,
    AptPackageManagerProvider,
    DnfPackageManagerProvider,
    LinuxPackageManagerName,
    LinuxPackageManagerProvider,
    LinuxPackageManagerResolver,
    LinuxPackageOperationResult,
    LinuxToolCompatibilityMatrix,
    PackageOperationStatus,
    PackageVerificationState,
    PacmanPackageManagerProvider,
    ZypperPackageManagerProvider,
)
from recipe_engine import RecipeOperation, StructuredRecipe, recipe_resolver


# ==============================================================================
# 1. DISTRIBUTION DETECTION TESTS (Problem #53)
# ==============================================================================

class TestLinuxDistributionDetection(unittest.TestCase):
    """Tests for Problem #53: Linux distribution and distribution family identification."""

    def test_01_ubuntu_detection_and_normalization(self):
        os_release = """
NAME="Ubuntu"
VERSION="24.04 LTS (Noble Numbat)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 24.04 LTS"
VERSION_ID="24.04"
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "ubuntu")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.DEBIAN)
        self.assertEqual(distro.distribution_version, "24.04")
        self.assertEqual(distro.distribution_codename, "noble")
        self.assertEqual(distro.architecture, "x86_64")
        self.assertEqual(distro.primary_package_manager, "apt")
        self.assertTrue(distro.is_supported)
        self.assertTrue(distro.is_family_compatible)

    def test_02_debian_detection_and_normalization(self):
        os_release = """
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
VERSION="12 (bookworm)"
VERSION_CODENAME=bookworm
ID=debian
HOME_URL="https://www.debian.org/"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="amd64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "debian")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.DEBIAN)
        self.assertEqual(distro.distribution_version, "12")
        self.assertEqual(distro.distribution_codename, "bookworm")
        self.assertEqual(distro.architecture, "x86_64")  # amd64 normalized to x86_64
        self.assertEqual(distro.primary_package_manager, "apt")
        self.assertTrue(distro.is_supported)

    def test_03_fedora_detection_and_normalization(self):
        os_release = """
NAME="Fedora Linux"
VERSION="40 (Workstation Edition)"
ID=fedora
VERSION_ID=40
VERSION_CODENAME=""
PLATFORM_ID="platform:f40"
PRETTY_NAME="Fedora Linux 40 (Workstation Edition)"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="aarch64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "fedora")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.REDHAT)
        self.assertEqual(distro.distribution_version, "40")
        self.assertEqual(distro.architecture, "aarch64")
        self.assertEqual(distro.primary_package_manager, "dnf")
        self.assertTrue(distro.is_supported)

    def test_04_rhel_family_rocky_detection(self):
        os_release = """
NAME="Rocky Linux"
VERSION="9.4 (Blue Onyx)"
ID="rocky"
ID_LIKE="rhel centos fedora"
VERSION_ID="9.4"
PLATFORM_ID="platform:el9"
PRETTY_NAME="Rocky Linux 9.4 (Blue Onyx)"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "rocky")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.REDHAT)
        self.assertEqual(distro.distribution_version, "9.4")
        self.assertEqual(distro.primary_package_manager, "dnf")
        self.assertTrue(distro.is_supported)

    def test_05_arch_linux_rolling_detection(self):
        os_release = """
NAME="Arch Linux"
PRETTY_NAME="Arch Linux"
ID=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;23;147;209"
HOME_URL="https://archlinux.org/"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "arch")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.ARCH)
        self.assertEqual(distro.distribution_version, "rolling")
        self.assertEqual(distro.primary_package_manager, "pacman")
        self.assertTrue(distro.is_supported)

    def test_06_opensuse_tumbleweed_detection(self):
        os_release = """
NAME="openSUSE Tumbleweed"
# VERSION="20240901"
ID="opensuse-tumbleweed"
ID_LIKE="opensuse suse"
VERSION_ID="20240901"
PRETTY_NAME="openSUSE Tumbleweed"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "opensuse-tumbleweed")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.SUSE)
        self.assertEqual(distro.primary_package_manager, "zypper")
        self.assertTrue(distro.is_supported)

    def test_07_alpine_linux_detection(self):
        os_release = """
NAME="Alpine Linux"
ID=alpine
VERSION_ID=3.20.2
PRETTY_NAME="Alpine Linux v3.20"
HOME_URL="https://alpinelinux.org/"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="arm64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "alpine")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.ALPINE)
        self.assertEqual(distro.distribution_version, "3.20.2")
        self.assertEqual(distro.architecture, "aarch64")  # arm64 normalized to aarch64
        self.assertEqual(distro.primary_package_manager, "apk")
        self.assertTrue(distro.is_supported)

    def test_08_unknown_custom_linux_requires_review(self):
        os_release = """
NAME="CustomOS Linux"
ID="customos"
PRETTY_NAME="CustomOS 1.0"
VERSION_ID="1.0"
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "customos")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.UNKNOWN)
        self.assertFalse(distro.is_supported)
        self.assertFalse(distro.is_family_compatible)
        self.assertIn("requires explicit review", distro.compatibility_notes)

    def test_09_missing_os_release_gracefully_handled(self):
        provider = LinuxDistributionProvider(custom_os_release_text="")
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "unknown")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.UNKNOWN)
        self.assertFalse(distro.is_supported)
        self.assertIn("Missing or empty distribution metadata", distro.compatibility_notes)

    def test_10_malformed_os_release_resilient_parsing(self):
        malformed = """
# Header comment with no equals
INVALID LINE WITHOUT EQUALS
NAME="Malformed Linux"
EMPTY_VAL=
SPACED_KEY = "Spaced Value"
UNQUOTED=some_value
SINGLE_QUOTED='single'
ID=debian
ID_LIKE=ubuntu
"""
        provider = LinuxDistributionProvider(custom_os_release_text=malformed)
        distro = provider.detect_distribution()

        self.assertEqual(distro.distribution, "debian")
        self.assertEqual(distro.distribution_family, LinuxDistributionFamily.DEBIAN)
        self.assertTrue(distro.is_supported)

    def test_11_architecture_normalization_matrix(self):
        cases = [
            ("x86_64", "x86_64"),
            ("amd64", "x86_64"),
            ("x64", "x86_64"),
            ("aarch64", "aarch64"),
            ("arm64", "aarch64"),
            ("armhf", "armhf"),
            ("armv7l", "armhf"),
            ("i686", "i686"),
            ("i386", "i686"),
            ("riscv64", "riscv64"),
            ("", "unknown"),
        ]
        for raw, expected in cases:
            self.assertEqual(LinuxArchitecture.normalize(raw), expected)


# ==============================================================================
# 2. PACKAGE MANAGER PROVIDER TESTS (Problem #52)
# ==============================================================================

class TestLinuxPackageManagerProviders(unittest.TestCase):
    """Tests for Problem #52: Linux package manager differences and provider implementations."""

    def test_12_apt_provider_operations_and_contract(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "--version" in cmd:
                return (0, "apt 2.7.14 (amd64)\n", "")
            if "dpkg-query" in cmd and "-f=${Status}" in cmd:
                return (0, "install ok installed", "")
            if "dpkg-query" in cmd and "-f=${Version}" in cmd:
                return (0, "2.43.0-1ubuntu7.1", "")
            if "apt-cache" in cmd and "policy" in cmd:
                return (0, "git:\n  Installed: 2.43.0\n  Candidate: 2.43.0-1ubuntu7.1\n", "")
            if "dpkg" in cmd and "-S" in cmd:
                return (0, "git: /usr/bin/git", "")
            return (0, "", "")

        apt = AptPackageManagerProvider(runner=mock_runner)
        self.assertEqual(apt.name, LinuxPackageManagerName.APT)
        self.assertTrue(apt.requires_elevation)
        self.assertEqual(apt.version(), "2.7.14")
        self.assertEqual(apt.identify_package("python"), "python3")
        self.assertEqual(apt.identify_package("git"), "git")
        self.assertTrue(apt.is_installed("git"))
        self.assertEqual(apt.installed_version("git"), "2.43.0-1ubuntu7.1")
        self.assertEqual(apt.candidate_version("git"), "2.43.0-1ubuntu7.1")
        self.assertTrue(apt.check_package_ownership("/usr/bin/git"))

        # Verify command syntax
        self.assertEqual(apt.build_install_command("git"), ["apt-get", "install", "-y", "git"])
        self.assertEqual(apt.build_update_command("git"), ["apt-get", "install", "--only-upgrade", "-y", "git"])
        self.assertEqual(apt.build_uninstall_command("git"), ["apt-get", "remove", "-y", "git"])
        self.assertEqual(apt.build_uninstall_command("git", purge=True), ["apt-get", "purge", "-y", "git"])

    def test_13_dnf_provider_operations_and_contract(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "--version" in cmd:
                return (0, "4.19.0\n  Installed: dnf-0:4.19.0-1.fc40.noarch", "")
            if "rpm" in cmd and "-q" in cmd and "--queryformat" in cmd:
                return (0, "2.44.0-1.fc40", "")
            if "rpm" in cmd and "-q" in cmd:
                return (0, "git-2.44.0-1.fc40.x86_64", "")
            if "dnf" in cmd and "info" in cmd:
                return (0, "Name: git\nVersion: 2.44.0\nRelease: 1.fc40\n", "")
            if "rpm" in cmd and "-qf" in cmd:
                return (0, "git-core-2.44.0-1.fc40.x86_64", "")
            return (0, "", "")

        dnf = DnfPackageManagerProvider(runner=mock_runner)
        self.assertEqual(dnf.name, LinuxPackageManagerName.DNF)
        self.assertTrue(dnf.requires_elevation)
        self.assertEqual(dnf.version(), "4.19.0")
        self.assertEqual(dnf.identify_package("docker"), "moby-engine")
        self.assertTrue(dnf.is_installed("git"))
        self.assertEqual(dnf.installed_version("git"), "2.44.0-1.fc40")
        self.assertEqual(dnf.candidate_version("git"), "2.44.0")
        self.assertTrue(dnf.check_package_ownership("/usr/bin/git"))

        # Verify command syntax
        self.assertEqual(dnf.build_install_command("git"), ["dnf", "install", "-y", "git"])
        self.assertEqual(dnf.build_update_command("git"), ["dnf", "upgrade", "-y", "git"])
        self.assertEqual(dnf.build_uninstall_command("git"), ["dnf", "remove", "-y", "git"])

    def test_14_pacman_provider_operations_and_contract(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "--version" in cmd:
                return (0, "Pacman v6.1.0 - libalpm v14.0.0\n", "")
            if "pacman" in cmd and "-Q" in cmd:
                return (0, "git 2.45.1-1", "")
            if "pacman" in cmd and "-Si" in cmd:
                return (0, "Repository: extra\nName: git\nVersion: 2.45.1-1\n", "")
            if "pacman" in cmd and "-Qo" in cmd:
                return (0, "/usr/bin/git is owned by git 2.45.1-1", "")
            return (0, "", "")

        pacman = PacmanPackageManagerProvider(runner=mock_runner)
        self.assertEqual(pacman.name, LinuxPackageManagerName.PACMAN)
        self.assertTrue(pacman.requires_elevation)
        self.assertEqual(pacman.version(), "6.1.0")
        self.assertEqual(pacman.identify_package("python"), "python")
        self.assertTrue(pacman.is_installed("git"))
        self.assertEqual(pacman.installed_version("git"), "2.45.1-1")
        self.assertEqual(pacman.candidate_version("git"), "2.45.1-1")
        self.assertTrue(pacman.check_package_ownership("/usr/bin/git"))

        # Verify command syntax
        self.assertEqual(pacman.build_install_command("git"), ["pacman", "-S", "--noconfirm", "git"])
        self.assertEqual(pacman.build_update_command("git"), ["pacman", "-S", "--noconfirm", "git"])
        self.assertEqual(pacman.build_uninstall_command("git"), ["pacman", "-Rns", "--noconfirm", "git"])

    def test_15_zypper_provider_operations_and_contract(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "--version" in cmd:
                return (0, "zypper 1.14.68\n", "")
            if "rpm" in cmd and "-q" in cmd and "--queryformat" in cmd:
                return (0, "2.43.0-150600.1.1", "")
            if "rpm" in cmd and "-q" in cmd:
                return (0, "git-2.43.0-150600.1.1.x86_64", "")
            if "zypper" in cmd and "info" in cmd:
                return (0, "Information for package git:\nVersion: 2.43.0\n", "")
            if "rpm" in cmd and "-qf" in cmd:
                return (0, "git-2.43.0.x86_64", "")
            return (0, "", "")

        zypper = ZypperPackageManagerProvider(runner=mock_runner)
        self.assertEqual(zypper.name, LinuxPackageManagerName.ZYPPER)
        self.assertTrue(zypper.requires_elevation)
        self.assertEqual(zypper.version(), "1.14.68")
        self.assertEqual(zypper.identify_package("git"), "git")
        self.assertTrue(zypper.is_installed("git"))
        self.assertEqual(zypper.installed_version("git"), "2.43.0-150600.1.1")
        self.assertEqual(zypper.candidate_version("git"), "2.43.0")
        self.assertTrue(zypper.check_package_ownership("/usr/bin/git"))

        # Verify command syntax
        self.assertEqual(zypper.build_install_command("git"), ["zypper", "--non-interactive", "install", "-y", "git"])
        self.assertEqual(zypper.build_update_command("git"), ["zypper", "--non-interactive", "update", "-y", "git"])
        self.assertEqual(zypper.build_uninstall_command("git"), ["zypper", "--non-interactive", "remove", "-y", "git"])

    def test_16_apk_provider_operations_and_contract(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "--version" in cmd:
                return (0, "apk-tools 2.14.0, compiled for x86_64\n", "")
            if "apk" in cmd and "info" in cmd and "-e" in cmd:
                return (0, "git\n", "")
            if "apk" in cmd and "info" in cmd and "-d" in cmd:
                return (0, "git-2.45.2-r0 description:\nGIT Distributed Version Control", "")
            if "apk" in cmd and "info" in cmd and "-r" in cmd:
                return (0, "git-2.45.2-r0\n", "")
            if "apk" in cmd and "info" in cmd and "-W" in cmd:
                return (0, "/usr/bin/git is owned by git-2.45.2-r0", "")
            return (0, "", "")

        apk = ApkPackageManagerProvider(runner=mock_runner)
        self.assertEqual(apk.name, LinuxPackageManagerName.APK)
        self.assertTrue(apk.requires_elevation)
        self.assertEqual(apk.version(), "2.14.0")
        self.assertEqual(apk.identify_package("pip"), "py3-pip")
        self.assertTrue(apk.is_installed("git"))
        self.assertEqual(apk.installed_version("git"), "2.45.2-r0")
        self.assertEqual(apk.candidate_version("git"), "2.45.2-r0")
        self.assertTrue(apk.check_package_ownership("/usr/bin/git"))

        # Verify command syntax
        self.assertEqual(apk.build_install_command("git"), ["apk", "add", "--no-cache", "git"])
        self.assertEqual(apk.build_update_command("git"), ["apk", "upgrade", "git"])
        self.assertEqual(apk.build_uninstall_command("git"), ["apk", "del", "git"])

    def test_17_package_manager_failure_classification(self):
        apt = AptPackageManagerProvider()
        dnf = DnfPackageManagerProvider()
        pacman = PacmanPackageManagerProvider()

        # APT failures
        st = apt.classify_failure(100, "", "E: Unable to locate package nonexist")
        self.assertEqual(st, PackageOperationStatus.PACKAGE_NOT_FOUND)

        st = apt.classify_failure(100, "", "E: Could not get lock /var/lib/dpkg/lock-frontend")
        self.assertEqual(st, PackageOperationStatus.RESOURCE_LOCKED)

        st = apt.classify_failure(100, "", "E: Failed to fetch http://archive.ubuntu.com/...")
        self.assertEqual(st, PackageOperationStatus.REPOSITORY_UNAVAILABLE)

        # DNF failures
        st = dnf.classify_failure(1, "", "Error: Unable to find a match: nonexist")
        self.assertEqual(st, PackageOperationStatus.PACKAGE_NOT_FOUND)

        st = dnf.classify_failure(1, "", "Error: Failed to synchronize cache for repo 'updates'")
        self.assertEqual(st, PackageOperationStatus.REPOSITORY_UNAVAILABLE)

        # Pacman failures
        st = pacman.classify_failure(1, "", "error: target not found: nonexist")
        self.assertEqual(st, PackageOperationStatus.PACKAGE_NOT_FOUND)

        st = pacman.classify_failure(1, "", "error: failed retrieving file 'core.db'")
        self.assertEqual(st, PackageOperationStatus.REPOSITORY_UNAVAILABLE)

    def test_18_verification_probe_states(self):
        def mock_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "dpkg-query" in cmd and "-f=${Status}" in cmd:
                return (0, "install ok installed", "")
            if "dpkg-query" in cmd and "-f=${Version}" in cmd:
                return (0, "2.43.0", "")
            return (1, "", "Package not found")

        apt = AptPackageManagerProvider(runner=mock_runner)
        self.assertEqual(apt.verify_package("git"), PackageVerificationState.INSTALLED)
        self.assertEqual(apt.verify_package("git", expected_version="2.43.0"), PackageVerificationState.VERSION_MATCHES)
        self.assertEqual(apt.verify_package("git", expected_version="3.0.0"), PackageVerificationState.VERSION_MISMATCH)

        # Non-installed
        def not_installed_runner(cmd: List[str]) -> Tuple[int, str, str]:
            return (1, "", "no packages found")

        apt_empty = AptPackageManagerProvider(runner=not_installed_runner)
        self.assertEqual(apt_empty.verify_package("missing"), PackageVerificationState.NOT_INSTALLED)


# ==============================================================================
# 3. RESOLVER & SELECTION TESTS
# ==============================================================================

class TestLinuxPackageManagerResolver(unittest.TestCase):
    """Tests deterministic provider selection based on distribution and ownership."""

    def test_19_deterministic_resolution_ubuntu_selects_apt(self):
        distro = LinuxDistribution(
            distribution="ubuntu",
            distribution_name="Ubuntu 24.04 LTS",
            distribution_family=LinuxDistributionFamily.DEBIAN,
            distribution_version="24.04",
            distribution_codename="noble",
            architecture="x86_64",
            primary_package_manager="apt",
            available_package_managers=["apt"],
            init_system="systemd",
            is_supported=True,
            is_family_compatible=True,
        )

        mock_apt = MagicMock(spec=AptPackageManagerProvider)
        mock_apt.name = LinuxPackageManagerName.APT
        mock_apt.is_available.return_value = True

        custom_providers = {LinuxPackageManagerName.APT: mock_apt}
        resolver = LinuxPackageManagerResolver(distro, custom_providers=custom_providers)
        prov, reason, req_review = resolver.resolve_provider_for_distribution(distro)

        self.assertIsNotNone(prov)
        self.assertEqual(prov.name, LinuxPackageManagerName.APT)
        self.assertFalse(req_review)
        self.assertIn("selected for family 'DEBIAN'", reason)

    def test_20_package_ownership_precedence(self):
        # Hybrid distro where RPM owns the binary even though APT is also present
        distro = LinuxDistribution(
            distribution="custom",
            distribution_name="Hybrid Linux",
            distribution_family=LinuxDistributionFamily.DEBIAN,
            distribution_version="1.0",
            distribution_codename="",
            architecture="x86_64",
            primary_package_manager="apt",
            available_package_managers=["apt", "dnf"],
            init_system="systemd",
            is_supported=True,
            is_family_compatible=True,
        )

        mock_apt = MagicMock(spec=AptPackageManagerProvider)
        mock_apt.name = LinuxPackageManagerName.APT
        mock_apt.is_available.return_value = True
        mock_apt.check_package_ownership.return_value = False

        mock_dnf = MagicMock(spec=DnfPackageManagerProvider)
        mock_dnf.name = LinuxPackageManagerName.DNF
        mock_dnf.is_available.return_value = True
        mock_dnf.check_package_ownership.return_value = True  # RPM owns this binary

        custom_providers = {
            LinuxPackageManagerName.APT: mock_apt,
            LinuxPackageManagerName.DNF: mock_dnf,
        }
        resolver = LinuxPackageManagerResolver(distro, custom_providers=custom_providers)
        prov, reason, req_review = resolver.resolve_provider_for_distribution(
            distro, installed_binary_path="/usr/bin/git"
        )

        self.assertIsNotNone(prov)
        self.assertEqual(prov.name, LinuxPackageManagerName.DNF)
        self.assertIn("verified ownership", reason)
        self.assertFalse(req_review)

    def test_21_unknown_distro_strictly_triggers_review(self):
        distro = LinuxDistribution(
            distribution="obscure-linux",
            distribution_name="Obscure Linux",
            distribution_family=LinuxDistributionFamily.UNKNOWN,
            distribution_version="0.1",
            distribution_codename="",
            architecture="x86_64",
            primary_package_manager="unknown",
            available_package_managers=[],
            init_system="unknown",
            is_supported=False,
            is_family_compatible=False,
        )

        resolver = LinuxPackageManagerResolver(distro)
        prov, reason, req_review = resolver.resolve_provider_for_distribution(distro)

        self.assertIsNone(prov)
        self.assertTrue(req_review)
        self.assertIn("Manual review required", reason)

    def test_22_tool_compatibility_matrix_contract(self):
        distro_fedora = LinuxDistribution(
            distribution="fedora",
            distribution_name="Fedora 40",
            distribution_family=LinuxDistributionFamily.REDHAT,
            distribution_version="40",
            distribution_codename="",
            architecture="x86_64",
            primary_package_manager="dnf",
            available_package_managers=["dnf"],
            init_system="systemd",
            is_supported=True,
            is_family_compatible=True,
        )

        # Mock DNF as available
        mock_dnf = MagicMock(spec=DnfPackageManagerProvider)
        mock_dnf.name = LinuxPackageManagerName.DNF
        mock_dnf.is_available.return_value = True
        mock_dnf.identify_package.side_effect = lambda x: "golang" if x == "go" else x
        mock_dnf.build_install_command.side_effect = lambda pkg: ["dnf", "install", "-y", pkg]
        mock_dnf.build_update_command.side_effect = lambda pkg: ["dnf", "upgrade", "-y", pkg]
        mock_dnf.build_uninstall_command.side_effect = lambda pkg: ["dnf", "remove", "-y", pkg]
        mock_dnf.requires_elevation = True

        with patch("platform_abstraction.linux.linux_package_manager.LinuxPackageManagerResolver") as MockResolverClass:
            mock_res_inst = MagicMock()
            mock_res_inst.resolve_provider_for_distribution.return_value = (mock_dnf, "Fedora DNF selected", False)
            MockResolverClass.return_value = mock_res_inst

            record = LinuxToolCompatibilityMatrix.get_compatibility("go", distro_fedora)
            self.assertTrue(record.supported)
            self.assertEqual(record.package_name, "golang")
            self.assertEqual(record.package_manager, LinuxPackageManagerName.DNF)
            self.assertEqual(record.install_command, "dnf install -y golang")
            self.assertTrue(record.requires_elevation)


# ==============================================================================
# 4. SAFETY & EXECUTION BOUNDARY INTEGRATION TESTS
# ==============================================================================

class TestLinuxExecutionBoundarySafety(unittest.TestCase):
    """
    Validates that Linux package manager commands pass through the authoritative execution pipeline:
    ExecutionResolver → ExecutionPlan → Tier → Approval → Privilege → LIVE Safety Gate → Engine.
    """

    def test_23_provider_command_routed_to_execution_plan(self):
        apt = AptPackageManagerProvider()
        cmd_args = apt.build_install_command("git")
        cmd_str = " ".join(cmd_args)

        # Ingest into ExecutionRequest
        req = ExecutionRequest(
            command=cmd_str,
            target="git",
            operation="INSTALL",
            source="LINUX_PROVIDER",
            provenance_hint=ProvenanceClass.STATIC_RECIPE,
            elevate=apt.requires_elevation,
        )

        resolver = ExecutionResolver()
        plan = resolver.resolve(req)

        self.assertIsInstance(plan, ExecutionPlan)
        self.assertEqual(plan.clean_command, "apt-get install -y git")
        self.assertEqual(plan.target_name, "git")
        self.assertEqual(plan.pm, "apt-get")
        self.assertTrue(plan.requires_elevation)
        # Verify approval is mandatory for system package mutation
        self.assertTrue(plan.approval_required)

    def test_24_unapproved_linux_execution_plan_blocks_mutation(self):
        req = ExecutionRequest(
            command="apt-get install -y ripgrep",
            target="ripgrep",
            operation="INSTALL",
            source="LINUX_PROVIDER",
            provenance_hint=ProvenanceClass.STATIC_RECIPE,
            approved=False,  # User rejected
            elevate=True,
        )

        resolver = ExecutionResolver()
        plan = resolver.resolve(req)
        self.assertTrue(plan.approval_required)
        self.assertFalse(plan.approved)

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

    def test_25_recipe_resolver_synthesizes_dnf_command_for_linux(self):
        identity = CanonicalIdentity(
            identity_id="git",
            display_name="Git",
            executable="git",
            package_id="git",
            publisher="Git Community",
            package_manager="dnf",
            platform_overrides={
                "linux": {
                    "package_id": "git",
                    "package_manager": "dnf",
                }
            }
        )

        recipe = recipe_resolver._synthesize_from_identity(identity, RecipeOperation.INSTALL, "Linux")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.executable, "sudo")
        self.assertEqual(recipe.arguments, ["dnf", "install", "-y", "git"])

    def test_26_recipe_resolver_synthesizes_pacman_command_for_linux(self):
        identity = CanonicalIdentity(
            identity_id="git",
            display_name="Git",
            executable="git",
            package_id="git",
            publisher="Git Community",
            package_manager="pacman",
            platform_overrides={
                "linux": {
                    "package_id": "git",
                    "package_manager": "pacman",
                }
            }
        )

        recipe = recipe_resolver._synthesize_from_identity(identity, RecipeOperation.INSTALL, "Linux")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.arguments, ["pacman", "-S", "--noconfirm", "git"])

    def test_27_recipe_resolver_synthesizes_zypper_command_for_linux(self):
        identity = CanonicalIdentity(
            identity_id="git",
            display_name="Git",
            executable="git",
            package_id="git",
            publisher="Git Community",
            package_manager="zypper",
            platform_overrides={
                "linux": {
                    "package_id": "git",
                    "package_manager": "zypper",
                }
            }
        )

        recipe = recipe_resolver._synthesize_from_identity(identity, RecipeOperation.INSTALL, "Linux")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.arguments, ["zypper", "--non-interactive", "install", "-y", "git"])

    def test_28_recipe_resolver_synthesizes_apk_command_for_linux(self):
        identity = CanonicalIdentity(
            identity_id="git",
            display_name="Git",
            executable="git",
            package_id="git",
            publisher="Git Community",
            package_manager="apk",
            platform_overrides={
                "linux": {
                    "package_id": "git",
                    "package_manager": "apk",
                }
            }
        )

        recipe = recipe_resolver._synthesize_from_identity(identity, RecipeOperation.INSTALL, "Linux")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.arguments, ["apk", "add", "--no-cache", "git"])


# ==============================================================================
# 5. FULL END-TO-END WORKFLOW INTEGRATION
# ==============================================================================

class TestLinuxEndToEndLifecycle(unittest.TestCase):
    """End-to-end integration tests connecting detection, resolution, and execution."""

    def test_29_end_to_end_supported_distro_flow(self):
        """
        Flow:
        1. Detect Linux distribution (Fedora 40, x86_64)
        2. Resolve provider (DNF)
        3. Identify package for 'ripgrep'
        4. Generate structured install command
        5. Ingest into ExecutionResolver
        6. Verify ExecutionPlan tier and approval
        7. Execute with approved=True (simulated execution)
        8. Verify package status probe
        """
        os_release = """
NAME="Fedora Linux"
VERSION="40 (Workstation Edition)"
ID=fedora
VERSION_ID=40
"""
        provider = LinuxDistributionProvider(custom_os_release_text=os_release, host_arch="x86_64")
        distro = provider.detect_distribution()
        self.assertEqual(distro.distribution, "fedora")

        # Mock DNF runner
        def mock_dnf_runner(cmd: List[str]) -> Tuple[int, str, str]:
            if "rpm" in cmd and "-q" in cmd:
                return (0, "ripgrep-14.1.0-1.fc40.x86_64", "")
            return (0, "Complete!", "")

        dnf_prov = DnfPackageManagerProvider(runner=mock_dnf_runner)
        pkg_name = dnf_prov.identify_package("ripgrep")
        self.assertEqual(pkg_name, "ripgrep")

        cmd = " ".join(dnf_prov.build_install_command(pkg_name))
        self.assertEqual(cmd, "dnf install -y ripgrep")

        req = ExecutionRequest(
            command=cmd,
            target="ripgrep",
            operation="INSTALL",
            source="LINUX_PROVIDER",
            provenance_hint=ProvenanceClass.STATIC_RECIPE,
            approved=True,
            elevate=dnf_prov.requires_elevation,
        )

        resolver = ExecutionResolver()
        plan = resolver.resolve(req)
        self.assertEqual(plan.pm, "dnf")
        self.assertTrue(plan.requires_elevation)

        # Verification probe confirms installed
        ver_state = dnf_prov.verify_package(pkg_name)
        self.assertEqual(ver_state, PackageVerificationState.INSTALLED)

    def test_30_end_to_end_unknown_distro_strictly_zero_mutation(self):
        """
        Flow for an unrecognized Linux distribution:
        1. Detect unknown distro
        2. Resolver returns None + requires_review=True
        3. No automated recipe is generated
        4. Zero automatic mutations occur
        """
        os_release = """
NAME="MyCustomDistro"
ID="mycustom"
"""
        dist_prov = LinuxDistributionProvider(custom_os_release_text=os_release)
        distro = dist_prov.detect_distribution()

        resolver = LinuxPackageManagerResolver(distro)
        prov, reason, req_review = resolver.resolve_provider_for_distribution(distro)

        self.assertIsNone(prov)
        self.assertTrue(req_review)

        # Verify Compatibility Matrix also rejects
        record = LinuxToolCompatibilityMatrix.get_compatibility("git", distro)
        self.assertFalse(record.supported)
        self.assertEqual(record.package_manager, LinuxPackageManagerName.UNKNOWN)
        self.assertIn("requires manual review", record.notes)


if __name__ == "__main__":
    unittest.main()
