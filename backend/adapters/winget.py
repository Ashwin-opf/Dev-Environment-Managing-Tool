"""
Winget Package Manager Adapter (Windows)
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


class WingetAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return "winget"

    def is_available(self) -> bool:
        return shutil.which("winget") is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(["winget", "search", "--query", query, "--accept-source-agreements"])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("Name") and not line.startswith("-") and not line.startswith("No package"):
                parts = [p for p in line.split("  ") if p.strip()]
                if len(parts) >= 2:
                    results.append({
                        "name": parts[0].strip(),
                        "id": parts[1].strip(),
                        "version": parts[2].strip() if len(parts) > 2 else "latest",
                        "description": parts[3].strip() if len(parts) > 3 else f"Winget package {parts[0]}",
                    })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        results = self.search(name)
        if results:
            return results[0].get("version", "latest")
        return "latest"

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ""
        if constraints:
            extra = " " + " ".join(constraints)
        return f"winget install --id {name} --exact --accept-source-agreements --accept-package-agreements{extra}"

    def remove(self, name: str) -> str:
        return f"winget uninstall --id {name} --exact"

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(["winget", "show", "--id", name, "--accept-source-agreements"])
        homepage = ""
        desc = f"Winget package {name}"
        deps = []
        for line in out.splitlines():
            if "Publisher Info Url:" in line or "Homepage:" in line or "URL:" in line:
                homepage = line.split(":", 1)[1].strip()
            elif "Description:" in line:
                desc = line.split(":", 1)[1].strip()
            elif "Dependencies:" in line:
                dep_part = line.split(":", 1)[1].strip()
                if dep_part and dep_part != "None":
                    deps = [d.strip() for d in dep_part.split(",") if d.strip()]
        return {
            "name": name,
            "version": self.resolve_latest(name),
            "dependencies": deps,
            "homepage": homepage or f"https://winget.run/pkg/{name}",
            "description": desc,
        }
