"""
APK Package Manager Adapter (Alpine Linux)
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


class ApkAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "apk"

    def is_available(self) -> bool:
        return shutil.which("apk") is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(["apk", "search", query])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line:
                pkg_name = line.split("-")[0] if "-" in line else line
                results.append({
                    "name": pkg_name,
                    "id": line,
                    "version": "latest",
                    "description": f"Alpine package {line}",
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(["apk", "info", "-d", name])
        for line in out.splitlines():
            if line.startswith(f"{name}-"):
                ver_part = line[len(name) + 1:].split()[0]
                return ver_part
        return "latest"

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = " " + " ".join(constraints) if constraints else ""
        return f"sudo apk add --no-cache {name}{extra}"

    def remove(self, name: str) -> str:
        return f"sudo apk del {name}"

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(["apk", "info", "-w", name])
        homepage = out.strip() if out.strip() else ""
        return {
            "name": name,
            "version": self.resolve_latest(name),
            "dependencies": [],
            "homepage": homepage or f"https://pkgs.alpinelinux.org/packages?name={name}",
            "description": f"APK package {name}",
        }
