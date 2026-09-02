"""
APT Package Manager Adapter (Debian / Ubuntu)
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


class AptAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "apt"

    def is_available(self) -> bool:
        return shutil.which("apt-get") is not None or shutil.which("apt") is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(["apt-cache", "search", query])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line and " - " in line:
                pkg_id, desc = line.split(" - ", 1)
                results.append({
                    "name": pkg_id.strip(),
                    "id": pkg_id.strip(),
                    "version": "latest",
                    "description": desc.strip(),
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(["apt-cache", "policy", name])
        for line in out.splitlines():
            if "Candidate:" in line:
                return line.split("Candidate:", 1)[1].strip()
        return "latest"

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ""
        if constraints:
            extra = " " + " ".join(constraints)
        return f"sudo apt-get install -y {name}{extra}"

    def remove(self, name: str) -> str:
        return f"sudo apt-get remove -y {name}"

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(["apt-cache", "show", name])
        deps = []
        homepage = ""
        desc = f"APT package {name}"
        for line in out.splitlines():
            if line.startswith("Depends:"):
                raw_deps = line.split("Depends:", 1)[1].strip()
                deps = [d.split("(")[0].strip() for d in raw_deps.split(",") if d.strip()]
            elif line.startswith("Homepage:"):
                homepage = line.split("Homepage:", 1)[1].strip()
            elif line.startswith("Description-en:") or line.startswith("Description:"):
                desc = line.split(":", 1)[1].strip()
        return {
            "name": name,
            "version": self.resolve_latest(name),
            "dependencies": deps[:10],
            "homepage": homepage or f"https://packages.ubuntu.com/search?keywords={name}",
            "description": desc,
        }
