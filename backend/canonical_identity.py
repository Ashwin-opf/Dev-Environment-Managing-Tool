"""
canonical_identity.py — Authoritative Canonical Identity System for PC Doctor.

Provides a unified identity model for tools and applications, ensuring:
- Executable and arguments are strictly separated.
- Package ID, display name, and executable name are decoupled.
- System vs user scope is explicitly tracked.
- Aliases, installation paths, and official URLs are centrally resolved.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalIdentity:
    identity_id: str                      # Unique key: "git", "nodejs", "vscode"
    display_name: str                     # Human readable: "Git", "Node.js"
    package_id: str                       # Package manager ID: "Git.Git"
    publisher: str                        # "The Git Project"
    executable: str                       # Binary name: "git"
    aliases: list[str] = field(default_factory=list) # ["git-scm", "git-cli"]
    installation_paths: list[str] = field(default_factory=list)
    version_command: list[str] = field(default_factory=list) # ["git", "--version"] - MUST be list
    required_path_dirs: list[str] = field(default_factory=list) # ["C:\\Program Files\\Git\\cmd"]
    service_name: str = ""                # Optional background service: "wuauserv", "docker"
    port: Optional[int] = None            # Optional TCP port: 3306, 5432, 8080
    env_var: str = ""                     # Optional environment variable: "JAVA_HOME", "GOROOT"
    official_url: str = ""
    package_manager: str = "winget"       # Primary default PM
    os: str = "Any"                       # "Windows", "Linux", "Darwin", "Any"
    architecture: str = "Any"             # "x64", "arm64", "x86", "Any"
    install_scope: str = "machine"        # "machine", "user", "portable"
    user_system_scope: str = "system"     # "system", "user"
    expected_executable_path: str = ""    # e.g. "C:\\Program Files\\Git\\cmd\\git.exe"
    functional_probe_command: list[str] = field(default_factory=list) # e.g. ["git", "help"]
    functional_probe_expected_exit_code: int = 0
    platform_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    channel: str = "stable"               # "stable", "lts", "beta", "nightly" — for multi-channel tools
    release_source: str = "static"        # "github", "vendor_api", "static"
    release_api: str = ""                 # e.g. "https://api.github.com/repos/git-for-windows/git/releases/latest"
    trusted_repository: str = ""          # e.g. "git-for-windows/git"
    trusted_download_domains: list[str] = field(default_factory=list) # e.g. ["git-scm.com", "github.com", "objects.githubusercontent.com"]
    source_policy: str = "package_manager_first" # "package_manager_first", "prefer_upstream", "review_required"
    checksum_policy: str = "optional"     # "required", "optional"
    signature_policy: str = "optional"    # "signed_only", "optional"

    @property
    def executable_name(self) -> str:
        return self.executable

    def get_package_id(self, platform_name: Optional[str] = None) -> str:
        plat = (platform_name or platform.system()).lower()
        if platform_name and platform_name.lower() in self.platform_overrides:
            val = self.platform_overrides[platform_name.lower()]
            if isinstance(val, dict):
                return str(val.get("package_id", self.package_id))
            return str(val)
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        return str(overrides.get("package_id", self.package_id))

    def get_package_manager(self, platform_name: Optional[str] = None) -> str:
        plat = (platform_name or platform.system()).lower()
        if platform_name and platform_name.lower() in self.platform_overrides:
            val = self.platform_overrides[platform_name.lower()]
            if isinstance(val, dict) and "package_manager" in val:
                return str(val["package_manager"])
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        if "package_manager" in overrides:
            return str(overrides["package_manager"])
        if key == "darwin" and self.package_manager in ("winget", "apt"):
            return "brew"
        if key == "linux" and self.package_manager in ("winget", "brew"):
            return "apt"
        if key == "windows" and self.package_manager in ("apt", "brew"):
            return "winget"
        return str(self.package_manager)

    def get_installation_paths(self, platform_name: Optional[str] = None) -> list[str]:
        plat = (platform_name or platform.system()).lower()
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        if "installation_paths" in overrides:
            return list(overrides["installation_paths"])
        return list(self.installation_paths)

    def get_required_path_dirs(self, platform_name: Optional[str] = None) -> list[str]:
        plat = (platform_name or platform.system()).lower()
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        if "required_path_dirs" in overrides:
            return list(overrides["required_path_dirs"])
        return list(self.required_path_dirs)

    def get_expected_executable_path(self, platform_name: Optional[str] = None) -> str:
        plat = (platform_name or platform.system()).lower()
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        if "expected_executable_path" in overrides:
            return str(overrides["expected_executable_path"])
        return self.expected_executable_path

    def get_functional_probe_command(self, platform_name: Optional[str] = None) -> list[str]:
        plat = (platform_name or platform.system()).lower()
        key = "darwin" if "darwin" in plat or "mac" in plat else ("windows" if "win" in plat else "linux")
        overrides = self.platform_overrides.get(key, {})
        if "functional_probe_command" in overrides:
            cmd = overrides["functional_probe_command"]
            return list(cmd) if isinstance(cmd, (list, tuple)) else str(cmd).split()
        return list(self.functional_probe_command)

    def matches_expected_executable(self, candidate_path: str, platform_name: Optional[str] = None) -> bool:
        """Checks if candidate_path matches the expected executable or falls under expected install paths."""
        if not candidate_path:
            return False
        expected = self.get_expected_executable_path(platform_name)
        norm_candidate = os.path.normcase(os.path.normpath(candidate_path))
        if expected:
            norm_expected = os.path.normcase(os.path.normpath(expected))
            if norm_candidate == norm_expected:
                return True
        for ipath in self.get_installation_paths(platform_name):
            norm_ip = os.path.normcase(os.path.normpath(ipath))
            if norm_candidate == norm_ip:
                return True
        sep = "\\" if os.name == "nt" else "/"
        for rdir in self.get_required_path_dirs(platform_name):
            norm_rd = os.path.normcase(os.path.normpath(rdir))
            if norm_candidate.startswith(norm_rd.rstrip("\\/") + sep):
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity_id": self.identity_id,
            "display_name": self.display_name,
            "package_id": self.package_id,
            "publisher": self.publisher,
            "executable": self.executable,
            "aliases": list(self.aliases),
            "installation_paths": list(self.installation_paths),
            "version_command": list(self.version_command),
            "required_path_dirs": list(self.required_path_dirs),
            "service_name": self.service_name,
            "port": self.port,
            "env_var": self.env_var,
            "official_url": self.official_url,
            "package_manager": self.package_manager,
            "os": self.os,
            "architecture": self.architecture,
            "install_scope": self.install_scope,
            "user_system_scope": self.user_system_scope,
            "expected_executable_path": self.expected_executable_path,
            "functional_probe_command": list(self.functional_probe_command),
            "functional_probe_expected_exit_code": self.functional_probe_expected_exit_code,
            "platform_overrides": dict(self.platform_overrides),
            "channel": self.channel,
            "release_source": self.release_source,
            "release_api": self.release_api,
            "trusted_repository": self.trusted_repository,
            "trusted_download_domains": list(self.trusted_download_domains),
            "source_policy": self.source_policy,
            "checksum_policy": self.checksum_policy,
            "signature_policy": self.signature_policy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CanonicalIdentity:
        # Guarantee version_command is always a list of strings
        vcmd = data.get("version_command", [])
        if isinstance(vcmd, str):
            vcmd = vcmd.split()
        fcmd = data.get("functional_probe_command", [])
        if isinstance(fcmd, str):
            fcmd = fcmd.split()
        return cls(
            identity_id=data["identity_id"],
            display_name=data["display_name"],
            package_id=data.get("package_id", ""),
            publisher=data.get("publisher", ""),
            executable=data.get("executable", ""),
            aliases=list(data.get("aliases", [])),
            installation_paths=list(data.get("installation_paths", [])),
            version_command=list(vcmd),
            required_path_dirs=list(data.get("required_path_dirs", [])),
            service_name=data.get("service_name", ""),
            port=data.get("port"),
            env_var=data.get("env_var", ""),
            official_url=data.get("official_url", ""),
            package_manager=data.get("package_manager", "winget"),
            os=data.get("os", "Any"),
            architecture=data.get("architecture", "Any"),
            install_scope=data.get("install_scope", "machine"),
            user_system_scope=data.get("user_system_scope", "system"),
            expected_executable_path=data.get("expected_executable_path", ""),
            functional_probe_command=list(fcmd),
            functional_probe_expected_exit_code=data.get("functional_probe_expected_exit_code", 0),
            platform_overrides=dict(data.get("platform_overrides", {})),
            channel=data.get("channel", "stable"),
            release_source=data.get("release_source", "static"),
            release_api=data.get("release_api", ""),
            trusted_repository=data.get("trusted_repository", ""),
            trusted_download_domains=list(data.get("trusted_download_domains", [])),
            source_policy=data.get("source_policy", "package_manager_first"),
            checksum_policy=data.get("checksum_policy", "optional"),
            signature_policy=data.get("signature_policy", "optional"),
        )


class CanonicalIdentityStore:
    """In-memory authoritative registry of canonical identities."""

    def __init__(self) -> None:
        self._identities: dict[str, CanonicalIdentity] = {}
        self._alias_map: dict[str, str] = {}
        self._pkg_id_map: dict[str, str] = {}
        self._exec_map: dict[str, str] = {}
        self._init_defaults()

    def register(self, identity: CanonicalIdentity) -> None:
        key = identity.identity_id.lower()
        self._identities[key] = identity
        self._alias_map[identity.display_name.lower()] = key
        for alias in identity.aliases:
            self._alias_map[alias.lower()] = key
        if identity.package_id:
            self._pkg_id_map[identity.package_id.lower()] = key
        if identity.executable:
            self._exec_map[identity.executable.lower()] = key

    def resolve(self, query: str) -> Optional[CanonicalIdentity]:
        """Resolve a tool identity by identity_id, display name, package_id, executable, or alias."""
        if not query:
            return None
        q = query.strip().lower()

        # 1. Direct key match
        if q in self._identities:
            return self._identities[q]

        # 2. Package ID match
        if q in self._pkg_id_map:
            return self._identities[self._pkg_id_map[q]]

        # 3. Executable match
        if q in self._exec_map:
            return self._identities[self._exec_map[q]]

        # 4. Alias / Display name match
        if q in self._alias_map:
            return self._identities[self._alias_map[q]]

        # 5. Fuzzy match for common prefixes / suffixes
        for alias, ident_id in self._alias_map.items():
            if alias in q or q in alias:
                return self._identities[ident_id]

        return None

    def get(self, query: str) -> Optional[CanonicalIdentity]:
        """Alias for resolve."""
        return self.resolve(query)

    def list_all(self) -> list[CanonicalIdentity]:
        return list(self._identities.values())

    def all_identities(self) -> list[CanonicalIdentity]:
        """Returns all registered canonical identities."""
        return list(self._identities.values())

    def _init_defaults(self) -> None:
        cur_os = platform.system()
        default_pm = "winget" if cur_os == "Windows" else ("brew" if cur_os == "Darwin" else "apt")

        # Git
        self.register(
            CanonicalIdentity(
                identity_id="git",
                display_name="Git",
                package_id="Git.Git",
                publisher="The Git Project",
                executable="git",
                aliases=["git-scm", "git-cli"],
                installation_paths=[
                    r"C:\Program Files\Git\cmd\git.exe",
                    r"C:\Program Files\Git\bin\git.exe",
                    r"C:\Program Files\Git\mingw64\bin\git.exe",
                    r"C:\Program Files (x86)\Git\cmd\git.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
                    "/usr/bin/git",
                    "/usr/local/bin/git",
                    "/opt/homebrew/bin/git",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Git\cmd",
                    r"C:\Program Files\Git\bin",
                    r"C:\Program Files\Git\mingw64\bin",
                    r"C:\Program Files (x86)\Git\cmd",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd"),
                    "/usr/bin",
                    "/usr/local/bin",
                    "/opt/homebrew/bin",
                ],
                version_command=["git", "--version"],
                official_url="https://git-scm.com",
                release_source="github",
                release_api="https://api.github.com/repos/git-for-windows/git/releases/latest",
                trusted_repository="git-for-windows/git",
                trusted_download_domains=["git-scm.com", "github.com", "githubusercontent.com", "objects.githubusercontent.com", "gitforwindows.org"],
                source_policy="package_manager_first",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
                expected_executable_path=r"C:\Program Files\Git\cmd\git.exe" if cur_os == "Windows" else "/usr/bin/git",
                functional_probe_command=["git", "help"],
                platform_overrides={
                    "darwin": {
                        "package_id": "git",
                        "package_manager": "brew",
                        "expected_executable_path": "/usr/bin/git",
                        "installation_paths": ["/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"],
                        "required_path_dirs": ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"],
                    },
                    "linux": {
                        "package_id": "git",
                        "package_manager": "apt",
                        "expected_executable_path": "/usr/bin/git",
                        "installation_paths": ["/usr/bin/git", "/usr/local/bin/git"],
                        "required_path_dirs": ["/usr/bin", "/usr/local/bin"],
                    },
                    "windows": {
                        "package_id": "Git.Git",
                        "package_manager": "winget",
                        "expected_executable_path": r"C:\Program Files\Git\cmd\git.exe",
                        "installation_paths": [
                            r"C:\Program Files\Git\cmd\git.exe",
                            r"C:\Program Files\Git\bin\git.exe",
                            r"C:\Program Files\Git\mingw64\bin\git.exe",
                            r"C:\Program Files (x86)\Git\cmd\git.exe",
                        ],
                        "required_path_dirs": [
                            r"C:\Program Files\Git\cmd",
                            r"C:\Program Files\Git\bin",
                            r"C:\Program Files\Git\mingw64\bin",
                            r"C:\Program Files (x86)\Git\cmd",
                        ],
                    },
                },
            )
        )

        # Node.js
        self.register(
            CanonicalIdentity(
                identity_id="nodejs",
                display_name="Node.js",
                package_id="OpenJS.NodeJS",
                publisher="OpenJS Foundation",
                executable="node",
                aliases=["node", "node.js", "nodejs-lts", "node-lts"],
                installation_paths=[
                    r"C:\Program Files\nodejs\node.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe"),
                    "/usr/bin/node",
                    "/usr/local/bin/node",
                ],
                required_path_dirs=[
                    r"C:\Program Files\nodejs",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs"),
                    "/usr/bin",
                    "/usr/local/bin",
                ],
                version_command=["node", "--version"],
                official_url="https://nodejs.org",
                release_source="vendor_api",
                release_api="https://nodejs.org/dist/index.json",
                trusted_repository="nodejs/node",
                trusted_download_domains=["nodejs.org", "github.com"],
                source_policy="package_manager_first",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
                expected_executable_path=r"C:\Program Files\nodejs\node.exe" if cur_os == "Windows" else "/usr/bin/node",
                functional_probe_command=["node", "-e", "console.log('pc_doctor_ok')"],
            )
        )

        # npm
        self.register(
            CanonicalIdentity(
                identity_id="npm",
                display_name="npm",
                package_id="npm",
                publisher="OpenJS Foundation",
                executable="npm",
                aliases=["npm-cli"],
                installation_paths=[
                    r"C:\Program Files\nodejs\npm.cmd",
                    os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
                    "/usr/bin/npm",
                    "/usr/local/bin/npm",
                ],
                required_path_dirs=[
                    r"C:\Program Files\nodejs",
                    os.path.expandvars(r"%APPDATA%\npm"),
                    "/usr/bin",
                    "/usr/local/bin",
                ],
                version_command=["npm", "--version"],
                official_url="https://www.npmjs.com",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Visual Studio Code
        self.register(
            CanonicalIdentity(
                identity_id="vscode",
                display_name="Visual Studio Code",
                package_id="Microsoft.VisualStudioCode",
                publisher="Microsoft Corporation",
                executable="code",
                aliases=["vs code", "vscode", "code-oss", "visual-studio-code"],
                installation_paths=[
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                    r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
                    r"C:\Program Files\Microsoft VS Code\Code.exe",
                    "/usr/bin/code",
                ],
                required_path_dirs=[
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin"),
                    r"C:\Program Files\Microsoft VS Code\bin",
                    "/usr/bin",
                ],
                version_command=["code", "--version"],
                official_url="https://code.visualstudio.com",
                release_source="vendor_api",
                release_api="https://update.code.visualstudio.com/api/releases/stable",
                trusted_repository="microsoft/vscode",
                trusted_download_domains=["code.visualstudio.com", "visualstudio.com", "update.code.visualstudio.com", "microsoft.com", "github.com"],
                source_policy="package_manager_first",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="user",
                user_system_scope="user",
            )
        )

        # Python
        self.register(
            CanonicalIdentity(
                identity_id="python",
                display_name="Python",
                package_id="Python.Python.3.13",
                publisher="Python Software Foundation",
                executable="python",
                aliases=["python3", "py", "python-3"],
                installation_paths=[
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
                    r"C:\Program Files\Python313\python.exe",
                    r"C:\Program Files\Python312\python.exe",
                    "/usr/bin/python3",
                ],
                required_path_dirs=[
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\Scripts"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\Scripts"),
                    r"C:\Program Files\Python313",
                    "/usr/bin",
                ],
                version_command=["python", "--version"],
                official_url="https://www.python.org",
                release_source="vendor_api",
                release_api="https://www.python.org/api/v2/downloads/release/",
                trusted_repository="python/cpython",
                trusted_download_domains=["python.org", "www.python.org"],
                source_policy="package_manager_first",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="user",
                user_system_scope="user",
                functional_probe_command=["python", "-c", "import sys; print('pc_doctor_ok')"],
            )
        )

        # Java (JDK)
        self.register(
            CanonicalIdentity(
                identity_id="java",
                display_name="Java JDK",
                package_id="Oracle.JDK.21",
                publisher="Oracle Corporation",
                executable="java",
                aliases=["jdk", "openjdk", "temurin", "java-jdk"],
                installation_paths=[
                    r"C:\Program Files\Java\jdk-21\bin\java.exe",
                    r"C:\Program Files\Java\jdk*\bin\java.exe",
                    r"C:\Program Files\Eclipse Adoptium\jdk*\bin\java.exe",
                    "/usr/bin/java",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Java\jdk-21\bin",
                    "/usr/bin",
                ],
                version_command=["java", "-version"],
                env_var="JAVA_HOME",
                official_url="https://www.oracle.com/java/",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Maven
        self.register(
            CanonicalIdentity(
                identity_id="maven",
                display_name="Apache Maven",
                package_id="Apache.Maven",
                publisher="Apache Software Foundation",
                executable="mvn",
                aliases=["mvn"],
                installation_paths=[
                    r"C:\Program Files\apache-maven*\bin\mvn.cmd",
                    r"C:\apache-maven*\bin\mvn.cmd",
                    "/usr/bin/mvn",
                ],
                required_path_dirs=[
                    r"C:\Program Files\apache-maven\bin",
                    "/usr/bin",
                ],
                version_command=["mvn", "-version"],
                env_var="M2_HOME",
                official_url="https://maven.apache.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Gradle
        self.register(
            CanonicalIdentity(
                identity_id="gradle",
                display_name="Gradle",
                package_id="Gradle.Gradle",
                publisher="Gradle Inc.",
                executable="gradle",
                aliases=["gradle-build"],
                installation_paths=[
                    r"C:\Gradle\gradle*\bin\gradle.bat",
                    os.path.expandvars(r"%USERPROFILE%\.gradle\wrapper\dists\*\bin\gradle.bat"),
                    "/usr/bin/gradle",
                ],
                required_path_dirs=[
                    r"C:\Gradle\gradle\bin",
                    "/usr/bin",
                ],
                version_command=["gradle", "-version"],
                official_url="https://gradle.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Docker
        self.register(
            CanonicalIdentity(
                identity_id="docker",
                display_name="Docker",
                package_id="Docker.DockerDesktop",
                publisher="Docker Inc.",
                executable="docker",
                aliases=["docker-cli", "docker-desktop"],
                installation_paths=[
                    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
                    "/usr/bin/docker",
                    "/usr/local/bin/docker",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Docker\Docker\resources\bin",
                    "/usr/bin",
                    "/usr/local/bin",
                ],
                service_name="com.docker.service",
                port=2375,
                version_command=["docker", "--version"],
                official_url="https://www.docker.com",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # GCC
        self.register(
            CanonicalIdentity(
                identity_id="gcc",
                display_name="GCC Compiler",
                package_id="MSYS2.MSYS2",
                publisher="GNU Project",
                executable="gcc",
                aliases=["mingw", "g++", "msys2-gcc"],
                installation_paths=[
                    r"C:\msys64\mingw64\bin\gcc.exe",
                    r"C:\w64devkit\bin\gcc.exe",
                    r"C:\MinGW\bin\gcc.exe",
                    "/usr/bin/gcc",
                ],
                required_path_dirs=[
                    r"C:\msys64\mingw64\bin",
                    r"C:\w64devkit\bin",
                    "/usr/bin",
                ],
                version_command=["gcc", "--version"],
                official_url="https://gcc.gnu.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # CMake
        self.register(
            CanonicalIdentity(
                identity_id="cmake",
                display_name="CMake",
                package_id="Kitware.CMake",
                publisher="Kitware, Inc.",
                executable="cmake",
                aliases=["cmake-gui"],
                installation_paths=[
                    r"C:\Program Files\CMake\bin\cmake.exe",
                    r"C:\Program Files (x86)\CMake\bin\cmake.exe",
                    "/usr/bin/cmake",
                ],
                required_path_dirs=[
                    r"C:\Program Files\CMake\bin",
                    "/usr/bin",
                ],
                version_command=["cmake", "--version"],
                official_url="https://cmake.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Go
        self.register(
            CanonicalIdentity(
                identity_id="go",
                display_name="Go",
                package_id="GoLang.Go",
                publisher="Google LLC",
                executable="go",
                aliases=["golang"],
                installation_paths=[
                    r"C:\Program Files\Go\bin\go.exe",
                    r"C:\Go\bin\go.exe",
                    os.path.expandvars(r"%USERPROFILE%\go\bin\go.exe"),
                    "/usr/local/go/bin/go",
                    "/usr/bin/go",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Go\bin",
                    os.path.expandvars(r"%USERPROFILE%\go\bin"),
                    "/usr/local/go/bin",
                    "/usr/bin",
                ],
                env_var="GOROOT",
                version_command=["go", "version"],
                official_url="https://go.dev",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Rust / Cargo
        self.register(
            CanonicalIdentity(
                identity_id="rust",
                display_name="Rust & Cargo",
                package_id="Rustlang.Rustup",
                publisher="Rust Foundation",
                executable="cargo",
                aliases=["cargo", "rustc", "rustup"],
                installation_paths=[
                    os.path.expandvars(r"%USERPROFILE%\.cargo\bin\cargo.exe"),
                    os.path.expandvars(r"%USERPROFILE%\.cargo\bin\rustc.exe"),
                    os.path.expanduser("~/.cargo/bin/cargo"),
                    os.path.expanduser("~/.cargo/bin/rustc"),
                ],
                required_path_dirs=[
                    os.path.expandvars(r"%USERPROFILE%\.cargo\bin"),
                    os.path.expanduser("~/.cargo/bin"),
                ],
                env_var="CARGO_HOME",
                version_command=["cargo", "--version"],
                official_url="https://www.rust-lang.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="user",
                user_system_scope="user",
            )
        )

        # Jenkins
        self.register(
            CanonicalIdentity(
                identity_id="jenkins",
                display_name="Jenkins",
                package_id="Jenkins.Jenkins",
                publisher="Jenkins Project",
                executable="jenkins",
                aliases=["jenkins-ci"],
                installation_paths=[
                    r"C:\Program Files\Jenkins\jenkins.exe",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Jenkins",
                ],
                service_name="Jenkins",
                port=8080,
                version_command=["jenkins", "--version"],
                official_url="https://www.jenkins.io",
                package_manager="winget",
                os="Windows",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # MySQL
        self.register(
            CanonicalIdentity(
                identity_id="mysql",
                display_name="MySQL Server",
                package_id="Oracle.MySQL",
                publisher="Oracle Corporation",
                executable="mysql",
                aliases=["mysql-server"],
                installation_paths=[
                    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
                    r"C:\Program Files\MySQL\MySQL Server *\bin\mysql.exe",
                    "/usr/bin/mysql",
                ],
                required_path_dirs=[
                    r"C:\Program Files\MySQL\MySQL Server 8.0\bin",
                    "/usr/bin",
                ],
                service_name="MySQL80",
                port=3306,
                version_command=["mysql", "--version"],
                official_url="https://www.mysql.com",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # PostgreSQL
        self.register(
            CanonicalIdentity(
                identity_id="postgresql",
                display_name="PostgreSQL",
                package_id="PostgreSQL.PostgreSQL",
                publisher="PostgreSQL Global Development Group",
                executable="psql",
                aliases=["postgres", "psql"],
                installation_paths=[
                    r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
                    r"C:\Program Files\PostgreSQL\*\bin\psql.exe",
                    "/usr/bin/psql",
                ],
                required_path_dirs=[
                    r"C:\Program Files\PostgreSQL\16\bin",
                    "/usr/bin",
                ],
                service_name="postgresql-x64-16",
                port=5432,
                version_command=["psql", "--version"],
                official_url="https://www.postgresql.org",
                package_manager=default_pm,
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Google Chrome
        self.register(
            CanonicalIdentity(
                identity_id="chrome",
                display_name="Google Chrome",
                package_id="Google.Chrome",
                publisher="Google LLC",
                executable="chrome",
                aliases=["google chrome", "chrome browser", "google-chrome"],
                installation_paths=[
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    "/usr/bin/google-chrome",
                ],
                required_path_dirs=[
                    r"C:\Program Files\Google\Chrome\Application",
                    r"C:\Program Files (x86)\Google\Chrome\Application",
                    "/usr/bin",
                ],
                version_command=["chrome", "--version"],
                official_url="https://www.google.com/chrome",
                package_manager="winget" if cur_os == "Windows" else "apt",
                os="Any",
                architecture="Any",
                install_scope="machine",
                user_system_scope="system",
            )
        )

        # Anaconda3
        self.register(
            CanonicalIdentity(
                identity_id="anaconda3",
                display_name="Anaconda3",
                package_id="Anaconda.Anaconda3",
                publisher="Anaconda, Inc.",
                executable="conda",
                aliases=["anaconda", "miniconda", "conda"],
                installation_paths=[
                    os.path.expandvars(r"%USERPROFILE%\anaconda3\Scripts\conda.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\anaconda3\Scripts\conda.exe"),
                ],
                required_path_dirs=[
                    os.path.expandvars(r"%USERPROFILE%\anaconda3\Scripts"),
                    os.path.expandvars(r"%LOCALAPPDATA%\anaconda3\Scripts"),
                ],
                version_command=["conda", "--version"],
                official_url="https://www.anaconda.com",
                package_manager="winget",
                os="Windows",
                architecture="x64",
                install_scope="user",
                user_system_scope="user",
            )
        )


# Global singleton store
canonical_store = CanonicalIdentityStore()
