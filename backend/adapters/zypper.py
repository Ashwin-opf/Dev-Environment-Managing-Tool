"""
Zypper Package Manager Adapter (openSUSE / SLES)
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


class ZypperAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "zypper"

    def is_available(self) -> bool:
        return shutil.which("zypper") is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(["zypper", "--non-interactive", "search", query])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("i ") or line.startswith("v ") or line.startswith("  "):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    pkg_name = parts[1]
                    summary = parts[2]
                    results.append({
                        "name": pkg_name,
                        "id": pkg_name,
                        "version": "latest",
                        "description": summary,
                    })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(["zypper", "--non-interactive", "info", name])
        for line in out.splitlines():
            if line.startswith("Version") and ":" in line:
                return line.split(":", 1)[1].strip()
        return "latest"

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = " " + " ".join(constraints) if constraints else ""
        return f"sudo zypper --non-interactive install -y {name}{extra}"

    def remove(self, name: str) -> str:
        return f"sudo zypper --non-interactive remove -y {name}"

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(["zypper", "--non-interactive", "info", name])
        deps: List[str] = []
        homepage = ""
        desc = f"Zypper package {name}"
        for line in out.splitlines():
            if line.startswith("Summary") and ":" in line:
                desc = line.split(":", 1)[1].strip()
            elif line.startswith("URL") and ":" in line:
                homepage = line.split(":", 1)[1].strip()
        return {
            "name": name,
            "version": self.resolve_latest(name),
            "dependencies": deps,
            "homepage": homepage or f"https://software.opensuse.org/package/{name}",
            "description": desc,
        }
