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
# DevToolsManager
# ---------------------------------------------------------------------------

class DevToolsManager:
    """
    Manages the lifecycle of tools installed through the Dev Tools interface.

    Persistence: a JSON file (``devtools_managed_apps.json``) stored in the
    backend directory.  Each entry conforms to the ``ManagedApplication`` data
    model defined in design.md.
    """

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path) if store_path else _DEFAULT_STORE
        self._apps: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load managed apps from the JSON store (creates it if absent)."""
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    # Legacy list format – convert to dict keyed by app_id
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
            # Non-fatal — log and continue
            print(f"[DevToolsManager] Warning: could not save store: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install_tool(self, tool_info: dict) -> dict:
        """
        Record a tool installation and automatically add it to the managed apps list.

        ``tool_info`` should contain at minimum ``name`` (or ``app``) and
        optionally ``install_command``, ``package_manager``, ``app_id``, and
        ``category``.

        Returns the newly created or updated managed-app record.
        """
        name = (
            tool_info.get("name")
            or tool_info.get("app")
            or tool_info.get("title")
            or "Unknown Tool"
        ).strip()

        # Derive a stable app_id from the name if not provided
        app_id = (
            tool_info.get("app_id")
            or name.lower().replace(" ", "-").replace("/", "-").replace(".", "-")
        )

        install_command = tool_info.get("install_command", "")
        package_manager = (
            tool_info.get("package_manager", "")
            or _infer_package_manager(install_command)
        )

        # Derive a canonical package name for update/uninstall commands
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
        """
        Return the update and uninstall commands for a managed app.

        Returns ``{"update_command": "...", "uninstall_command": "..."}`` or
        raises ``KeyError`` if the app is not tracked.
        """
        record = self._apps.get(app_id)
        if record is None:
            raise KeyError(f"App '{app_id}' is not in the managed apps list.")
        return {
            "update_command": record.get("update_command", ""),
            "uninstall_command": record.get("uninstall_command", ""),
        }

    def list_managed_apps(self) -> list:
        """Return all tracked managed apps as a list."""
        return list(self._apps.values())

    def remove_managed_app(self, app_id: str) -> bool:
        """Remove an app from the managed list. Returns True if found and removed."""
        if app_id in self._apps:
            del self._apps[app_id]
            self._save()
            return True
        return False

    def get_managed_app(self, app_id: str) -> Optional[dict]:
        """Return a single managed app record, or None if not found."""
        return self._apps.get(app_id)


# ---------------------------------------------------------------------------
# Module-level singleton (imported by routes)
# ---------------------------------------------------------------------------

devtools_manager = DevToolsManager()
