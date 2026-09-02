"""
DevToolsManager – Application Lifecycle Management for Dev Tools
================================================================
Tracks tools installed through the Dev Tools search interface, stores
them in a persistent JSON file, and generates update / uninstall
commands based on the detected package manager.

Requirements: 4.1, 4.4
"""
from __future__ import annotations

import json
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Persistent store lives alongside this file (in the backend directory).
_DEFAULT_STORE = Path(__file__).parent / "devtools_managed_apps.json"


# ---------------------------------------------------------------------------
# Package-manager command tables
# ---------------------------------------------------------------------------

_APT_UPDATE = "sudo apt-get update && sudo apt-get install --only-upgrade -y {pkg}"
_APT_UNINSTALL = "sudo apt-get remove -y {pkg}"

_SNAP_UPDATE = "sudo snap refresh {pkg}"
_SNAP_UNINSTALL = "sudo snap remove {pkg}"

_FLATPAK_UPDATE = "flatpak update {pkg} -y"
_FLATPAK_UNINSTALL = "flatpak uninstall {pkg} -y"

_BREW_UPDATE = "brew upgrade {pkg}"
_BREW_UNINSTALL = "brew uninstall {pkg}"

_WINGET_UPDATE = "winget upgrade --id {pkg} --exact --silent"
_WINGET_UNINSTALL = "winget uninstall --id {pkg} --exact --silent"

_NPM_UPDATE = "npm install -g {pkg}@latest"
_NPM_UNINSTALL = "npm uninstall -g {pkg}"

_PIP_UPDATE = "pip install --upgrade {pkg}"
_PIP_UNINSTALL = "pip uninstall -y {pkg}"

_CARGO_UPDATE = "cargo install {pkg}"
_CARGO_UNINSTALL = "cargo uninstall {pkg}"

_GENERIC_LINUX = "sudo apt-get update && sudo apt-get install --only-upgrade -y {pkg}"
_GENERIC_UNINSTALL_LINUX = "sudo apt-get remove -y {pkg}"

_GENERIC_WINDOWS = "winget upgrade --id {pkg}"
_GENERIC_UNINSTALL_WINDOWS = "winget uninstall --id {pkg}"


def _generate_update_command(pkg: str, package_manager: str) -> str:
    pm = (package_manager or "").lower().strip()
    if pm == "apt":
        return _APT_UPDATE.format(pkg=pkg)
    if pm == "snap":
        return _SNAP_UPDATE.format(pkg=pkg)
    if pm == "flatpak":
        return _FLATPAK_UPDATE.format(pkg=pkg)
    if pm == "brew":
        return _BREW_UPDATE.format(pkg=pkg)
    if pm == "winget":
        return _WINGET_UPDATE.format(pkg=pkg)
    if pm == "npm":
        return _NPM_UPDATE.format(pkg=pkg)
    if pm == "pip":
        return _PIP_UPDATE.format(pkg=pkg)
    if pm == "cargo":
        return _CARGO_UPDATE.format(pkg=pkg)
    # Fallback: infer from OS
    if platform.system() == "Windows":
        return _GENERIC_WINDOWS.format(pkg=pkg)
    return _GENERIC_LINUX.format(pkg=pkg)


def _generate_uninstall_command(pkg: str, package_manager: str) -> str:
    pm = (package_manager or "").lower().strip()
    if pm == "apt":
        return _APT_UNINSTALL.format(pkg=pkg)
    if pm == "snap":
        return _SNAP_UNINSTALL.format(pkg=pkg)
    if pm == "flatpak":
        return _FLATPAK_UNINSTALL.format(pkg=pkg)
    if pm == "brew":
        return _BREW_UNINSTALL.format(pkg=pkg)
    if pm == "winget":
        return _WINGET_UNINSTALL.format(pkg=pkg)
    if pm == "npm":
        return _NPM_UNINSTALL.format(pkg=pkg)
    if pm == "pip":
        return _PIP_UNINSTALL.format(pkg=pkg)
    if pm == "cargo":
        return _CARGO_UNINSTALL.format(pkg=pkg)
    if platform.system() == "Windows":
        return _GENERIC_UNINSTALL_WINDOWS.format(pkg=pkg)
    return _GENERIC_UNINSTALL_LINUX.format(pkg=pkg)


def _infer_package_manager(install_command: str) -> str:
    """Infer the package manager from an install command string."""
    cmd = (install_command or "").lower()
    if "flatpak" in cmd:
        return "flatpak"
    if "snap" in cmd:
        return "snap"
    if "brew" in cmd:
        return "brew"
    if "winget" in cmd:
        return "winget"
    if "npm install" in cmd:
        return "npm"
    if "pip install" in cmd:
        return "pip"
    if "cargo install" in cmd:
        return "cargo"
    if "apt" in cmd or "apt-get" in cmd:
        return "apt"
    if platform.system() == "Windows":
        return "winget"
    return "apt"


def _extract_package_name(tool_info: dict) -> str:
    """Try to extract a clean package name from tool_info for command generation."""
    # Prefer explicit package_name field, then fall back to app/name
    for key in ("package_name", "pkg", "app", "name", "title"):
        val = tool_info.get(key, "")
        if val:
            return str(val).strip().lower().replace(" ", "-")
    return "unknown-package"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Predefined developer tools and runtimes for host system detection
# ---------------------------------------------------------------------------
_KNOWN_SYSTEM_TOOLS = [
    {
        "app_id": "python",
        "name": "Python",
        "category": "Languages & Runtimes",
        "description": "High-level general-purpose programming language and runtime.",
        "binaries": ["python", "python3", "py"],
        "package_manager": "winget",
        "pkg_name": "Python.Python.3.12",
    },
    {
        "app_id": "git",
        "name": "Git",
        "category": "Version Control",
        "description": "Distributed version control system to track changes in source code.",
        "binaries": ["git"],
        "detector": "git_installed",
        "package_manager": "winget",
        "pkg_name": "Git.Git",
    },
    {
        "app_id": "node",
        "name": "Node.js",
        "category": "JavaScript Runtime",
        "description": "JavaScript runtime built on Chrome's V8 engine.",
        "binaries": ["node", "nodejs"],
        "package_manager": "winget",
        "pkg_name": "OpenJS.NodeJS",
    },
    {
        "app_id": "npm",
        "name": "npm",
        "category": "Package Manager",
        "description": "Package manager for JavaScript and Node.js dependencies.",
        "binaries": ["npm"],
        "package_manager": "npm",
        "pkg_name": "npm",
    },
    {
        "app_id": "vscode",
        "name": "VS Code",
        "category": "Code Editors",
        "description": "Extensible code editor developed by Microsoft.",
        "binaries": ["code"],
        "detector": "vscode_installed",
        "package_manager": "winget",
        "pkg_name": "Microsoft.VisualStudioCode",
    },
    {
        "app_id": "docker",
        "name": "Docker",
        "category": "DevOps & Containers",
        "description": "Platform for containerizing and running applications.",
        "binaries": ["docker"],
        "detector": "docker_installed",
        "package_manager": "winget",
        "pkg_name": "Docker.DockerDesktop",
    },
    {
        "app_id": "rust",
        "name": "Rust & Cargo",
        "category": "Languages & Runtimes",
        "description": "Systems programming language and Cargo package manager.",
        "binaries": ["cargo", "rustc"],
        "package_manager": "winget",
        "pkg_name": "Rustlang.Rustup",
    },
    {
        "app_id": "java",
        "name": "Java JDK",
        "category": "Languages & Runtimes",
        "description": "Java SE Development Kit and runtime environment.",
        "binaries": ["java", "javac"],
        "detector": "java_installed",
        "package_manager": "winget",
        "pkg_name": "Oracle.JDK.21",
    },
    {
        "app_id": "go",
        "name": "Go",
        "category": "Languages & Runtimes",
        "description": "Compiled programming language designed for scalable services.",
        "binaries": ["go"],
        "package_manager": "winget",
        "pkg_name": "GoLang.Go",
    },
    {
        "app_id": "ollama",
        "name": "Ollama",
        "category": "AI & Local LLMs",
        "description": "Local large language model runner and management service.",
        "binaries": ["ollama"],
        "detector": "ollama_installed",
        "package_manager": "winget",
        "pkg_name": "Ollama.Ollama",
    },
    {
        "app_id": "gh",
        "name": "GitHub CLI",
        "category": "CLI Utilities",
        "description": "Official CLI to manage GitHub repos, issues, and PRs.",
        "binaries": ["gh"],
        "package_manager": "winget",
        "pkg_name": "GitHub.cli",
    },
    {
        "app_id": "neovim",
        "name": "Neovim",
        "category": "Code Editors",
        "description": "Hyperextensible Vim-based terminal text editor.",
        "binaries": ["nvim"],
        "package_manager": "winget",
        "pkg_name": "Neovim.Neovim",
    },
]


class DevToolsManager:
    """
    Manages the lifecycle of tools installed through the Dev Tools interface
    and auto-discovers local host developer tools.
    """

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path) if store_path else _DEFAULT_STORE
        self._apps: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load managed apps from the JSON store (creates it if absent)."""
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._apps = {item["app_id"]: item for item in raw if isinstance(item, dict) and "app_id" in item}
                elif isinstance(raw, dict):
                    self._apps = raw
                else:
                    self._apps = {}
            except (json.JSONDecodeError, KeyError, TypeError):
                self._apps = {}
        else:
            self._apps = {}

    def _save(self) -> None:
        """Persist the current managed apps to disk."""
        try:
            self._store_path.write_text(
                json.dumps(list(self._apps.values()), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[DevToolsManager] Warning: could not save store: {exc}")

    def _discover_system_installed_apps(self) -> list[dict]:
        """Scan the local operating system for installed developer tools and runtimes."""
        discovered = []
        is_win = platform.system() == "Windows"
        is_mac = platform.system() == "Darwin"

        def _is_tool_present(t_def: dict) -> bool:
            detector_name = t_def.get("detector")
            if detector_name:
                try:
                    import tool_detector
                    func = getattr(tool_detector, detector_name, None)
                    if func and func():
                        return True
                except Exception:
                    pass
            for bin_name in t_def.get("binaries", []):
                if shutil.which(bin_name) or (is_win and shutil.which(f"{bin_name}.exe")):
                    return True
            return False

        for t in _KNOWN_SYSTEM_TOOLS:
            app_id = t["app_id"]
            if _is_tool_present(t):
                pm = "winget" if is_win else ("brew" if is_mac else t.get("package_manager", "apt"))
                pkg = t.get("pkg_name", app_id)
                discovered.append({
                    "app_id": app_id,
                    "name": t["name"],
                    "category": t["category"],
                    "description": t["description"],
                    "package_manager": pm,
                    "install_command": f"{pm} install {pkg}",
                    "update_command": _generate_update_command(pkg, pm),
                    "uninstall_command": _generate_uninstall_command(pkg, pm),
                    "installation_date": datetime.now(timezone.utc).isoformat(),
                    "auto_managed": True,
                })
        return discovered

    def install_tool(self, tool_info: dict) -> dict:
        """Record a tool installation and automatically add it to the managed apps list."""
        name = (
            tool_info.get("name")
            or tool_info.get("app")
            or tool_info.get("title")
            or "Unknown Tool"
        ).strip()

        app_id = (
            tool_info.get("app_id")
            or name.lower().replace(" ", "-").replace("/", "-").replace(".", "-")
        )

        install_command = tool_info.get("install_command", "")
        package_manager = (
            tool_info.get("package_manager", "")
            or _infer_package_manager(install_command)
        )

        pkg = _extract_package_name(tool_info)

        update_command = (
            tool_info.get("update_command")
            or _generate_update_command(pkg, package_manager)
        )
        uninstall_command = (
            tool_info.get("uninstall_command")
            or _generate_uninstall_command(pkg, package_manager)
        )

        now = datetime.now(timezone.utc).isoformat()

        record = {
            "app_id": app_id,
            "name": name,
            "install_command": install_command,
            "update_command": update_command,
            "uninstall_command": uninstall_command,
            "package_manager": package_manager,
            "category": tool_info.get("category", ""),
            "description": tool_info.get("description", ""),
            "installation_date": tool_info.get("installation_date") or now,
            "auto_managed": tool_info.get("auto_managed", True),
        }

        self._apps[app_id] = record
        self._save()
        return record

    def get_management_commands(self, app_id: str) -> dict:
        """Return the update and uninstall commands for a managed app."""
        record = self._apps.get(app_id)
        if record is None:
            # Check system apps
            for sys_app in self._discover_system_installed_apps():
                if sys_app["app_id"] == app_id:
                    record = sys_app
                    break
        if record is None:
            raise KeyError(f"App '{app_id}' is not in the managed apps list.")
        return {
            "update_command": record.get("update_command", ""),
            "uninstall_command": record.get("uninstall_command", ""),
        }

    def list_managed_apps(self) -> list:
        """Return all tracked managed apps merged with auto-discovered local host apps."""
        combined = {}
        # 1. First add real detected system apps on the host machine
        for app in self._discover_system_installed_apps():
            combined[app["app_id"]] = app
        # 2. Layer any custom or modified user records from store
        for app_id, app in self._apps.items():
            combined[app_id] = app
        return list(combined.values())

    def remove_managed_app(self, app_id: str) -> bool:
        """Remove an app from the managed list. Returns True if found and removed."""
        if app_id in self._apps:
            del self._apps[app_id]
            self._save()
            return True
        return False

    def get_managed_app(self, app_id: str) -> Optional[dict]:
        """Return a single managed app record, or None if not found."""
        for app in self.list_managed_apps():
            if app.get("app_id") == app_id:
                return app
        return None


# ---------------------------------------------------------------------------
# Module-level singleton (imported by routes)
# ---------------------------------------------------------------------------

devtools_manager = DevToolsManager()
