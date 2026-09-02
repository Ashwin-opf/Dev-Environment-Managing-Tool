"""
DNF Package Manager Adapter (Fedora / RHEL / CentOS)
"""

import shutil
import subprocess
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _safe_run(cmd: List[str], timeout: int = 8) -> str:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.stdout or ""
    except Exception:
        return ""


class DnfAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "dnf"

    def is_available(self) -> bool:
        return shutil.which("dnf") is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(["dnf", "search", query, "--quiet"])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line and " : " in line and not line.startswith("="):
                pkg_id, desc = line.split(" : ", 1)
                results.append({
                    "name": pkg_id.strip().split(".")[0],
                    "id": pkg_id.strip(),
                    "version": "latest",
                    "description": desc.strip(),
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(["dnf", "info", name, "--quiet"])
        for line in out.splitlines():
            if line.startswith("Version") and ":" in line:
                return line.split(":", 1)[1].strip()
        return "latest"

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = " " + " ".join(constraints) if constraints else ""
        return f"sudo dnf install -y {name}{extra}"

    def remove(self, name: str) -> str:
        return f"sudo dnf remove -y {name}"

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(["dnf", "info", name])
        deps = []
        homepage = ""
        desc = f"DNF package {name}"
        for line in out.splitlines():
            if line.startswith("Description") and ":" in line:
                desc = line.split(":", 1)[1].strip()
            elif line.startswith("URL") and ":" in line:
                homepage = line.split(":", 1)[1].strip()
        return {
            "name": name,
            "version": self.resolve_latest(name),
            "dependencies": deps,
            "homepage": homepage or f"https://packages.fedoraproject.org/pkgs/{name}/",
            "description": desc,
        }
