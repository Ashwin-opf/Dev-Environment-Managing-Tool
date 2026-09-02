"""
Snapshot & Rollback Engine
==========================
Auto-snapshots system state before any medium/high-risk action.
Provides revert capability. Stores snapshots in a JSON manifest.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent
SNAPSHOT_DIR = BASE_DIR / "snapshots"
MANIFEST_FILE = SNAPSHOT_DIR / "manifest.json"
MAX_SNAPSHOTS = 20

SNAPSHOT_DIR.mkdir(exist_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_manifest() -> List[Dict[str, Any]]:
    if not MANIFEST_FILE.exists():
        return []
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_manifest(entries: List[Dict[str, Any]]) -> None:
    MANIFEST_FILE.write_text(
        json.dumps(entries[-MAX_SNAPSHOTS:], indent=2), encoding="utf-8"
    )


def _safe_run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except Exception:
        import subprocess as sp
        return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr="timeout or error")


def _capture_installed_packages() -> Dict[str, List[str]]:
    """Capture currently installed package lists per available package manager."""
    result: Dict[str, List[str]] = {}
    os_name = platform.system()

    if os_name == "Windows":
        out = _safe_run(["winget", "list", "--accept-source-agreements"])
        if out.returncode == 0:
            result["winget"] = [l.strip() for l in out.stdout.splitlines() if l.strip()][2:]
    elif os_name == "Linux":
        out = _safe_run(["dpkg", "--get-selections"])
        if out.returncode == 0:
            result["apt"] = [l.split()[0] for l in out.stdout.splitlines() if "install" in l]
        out2 = _safe_run(["flatpak", "list", "--app", "--columns=application"])
        if out2.returncode == 0:
            result["flatpak"] = [l.strip() for l in out2.stdout.splitlines() if l.strip()]
        out3 = _safe_run(["snap", "list"])
        if out3.returncode == 0:
            result["snap"] = [l.split()[0] for l in out3.stdout.splitlines()[1:] if l.strip()]
    elif os_name == "Darwin":
        out = _safe_run(["brew", "list", "--formula"])
        if out.returncode == 0:
            result["brew"] = [l.strip() for l in out.stdout.splitlines() if l.strip()]

    return result


def _capture_env_vars() -> Dict[str, str]:
    """Capture PATH and other key environment variables."""
    keys = ["PATH", "PYTHONPATH", "NODE_PATH", "JAVA_HOME", "GOPATH", "CARGO_HOME"]
    return {k: os.environ.get(k, "") for k in keys}


# ─── Public API ────────────────────────────────────────────────────────────────

def create(label: str = "", action: str = "") -> Dict[str, Any]:
    """
    Create a system snapshot.
    Returns the snapshot record including its unique ID.
    """
    snapshot_id = str(uuid.uuid4())[:8]
    snap_path = SNAPSHOT_DIR / snapshot_id
    snap_path.mkdir(exist_ok=True)

    installed = _capture_installed_packages()
    env = _capture_env_vars()

    record = {
        "id": snapshot_id,
        "created_at": _utc_now(),
        "label": label or f"Before: {action}",
        "action": action,
        "os": platform.system(),
        "installed_packages": installed,
        "env_vars": env,
        "path": str(snap_path),
    }

    (snap_path / "snapshot.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )

    manifest = _load_manifest()
    manifest.append(record)
    _save_manifest(manifest)

    return record


def revert(snapshot_id: str) -> Dict[str, Any]:
    """
    Attempt to revert the system to the given snapshot.
    Currently restores environment variable hints; full package revert
    surfaces the diff to the user as a batch plan for approval.
    Returns a result dict with success flag and diff.
    """
    manifest = _load_manifest()
    snap = next((s for s in manifest if s["id"] == snapshot_id), None)
    if not snap:
        return {"success": False, "error": f"Snapshot {snapshot_id} not found"}

    snap_path = Path(snap.get("path", ""))
    snap_file = snap_path / "snapshot.json"
    if not snap_file.exists():
        return {"success": False, "error": "Snapshot data missing"}

    try:
        saved_data = json.loads(snap_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    current_installed = _capture_installed_packages()
    saved_installed = saved_data.get("installed_packages", {})

    # Compute diff: what needs to be removed/added to revert
    to_remove: List[str] = []
    to_reinstall: List[str] = []

    for pm, saved_pkgs in saved_installed.items():
        current_pkgs = set(current_installed.get(pm, []))
        saved_set = set(saved_pkgs)
        to_remove.extend(f"{pm}:{p}" for p in (current_pkgs - saved_set))
        to_reinstall.extend(f"{pm}:{p}" for p in (saved_set - current_pkgs))

    return {
        "success": True,
        "snapshot_id": snapshot_id,
        "snapshot_label": snap.get("label", ""),
        "revert_plan": {
            "packages_to_remove": to_remove[:30],
            "packages_to_reinstall": to_reinstall[:30],
        },
        "note": "Review and approve the revert plan before execution.",
    }


def list_snapshots() -> List[Dict[str, Any]]:
    """List all stored snapshots, newest first."""
    return list(reversed(_load_manifest()))


def delete(snapshot_id: str) -> bool:
    """Delete a snapshot record and its files."""
    manifest = _load_manifest()
    snap = next((s for s in manifest if s["id"] == snapshot_id), None)
    if not snap:
        return False
    snap_path = Path(snap.get("path", ""))
    if snap_path.exists():
        shutil.rmtree(snap_path, ignore_errors=True)
    updated = [s for s in manifest if s["id"] != snapshot_id]
    _save_manifest(updated)
    return True
