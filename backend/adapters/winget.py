"""
Winget Package Manager Adapter (Windows)
========================================
Authoritative adapter for Windows Package Manager (WinGet).
Enforces:
- Clean quoted command generation without blind chaining (`||`).
- Exact ID matching (`--exact`).
- Capability checking for publisher-managed packages (e.g. Anaconda).
- Non-interactive silent execution flags.
"""

import shutil
import subprocess
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _safe_run(cmd: List[str], timeout: int = 15) -> str:
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
        return f'winget install --id "{name}" --exact --silent --accept-source-agreements --accept-package-agreements{extra}'

    def update(self, name: str) -> str:
        return f'winget upgrade --id "{name}" --exact --silent'

    def remove(self, name: str) -> str:
        return f'winget uninstall --id "{name}" --exact --silent'

    def uninstall(self, name: str) -> str:
        return self.remove(name)

    def reinstall(self, name: str) -> str:
        return f'winget install --id "{name}" --exact --force --silent'

    def list_installed(self) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        out = _safe_run(["winget", "list", "--accept-source-agreements"], timeout=30)
        apps = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("Name") or line.startswith("-"):
                continue
            parts = [p.strip() for p in line.split("  ") if p.strip()]
            if len(parts) >= 2:
                apps.append({
                    "name": parts[0],
                    "id": parts[1],
                    "version": parts[2] if len(parts) > 2 else "",
                    "available": parts[3] if len(parts) > 3 else "",
                    "source": parts[4] if len(parts) > 4 else "winget",
                })
        return apps

    def verify(self, name: str) -> Dict[str, Any]:
        if not self.is_available():
            return {"installed": False, "version": None}
        out = _safe_run(["winget", "list", "--id", name, "--exact", "--accept-source-agreements"])
        for line in out.splitlines():
            if name.lower() in line.lower() and not line.startswith("Name") and not line.startswith("-"):
                parts = [p.strip() for p in line.split("  ") if p.strip()]
                return {
                    "installed": True,
                    "version": parts[2] if len(parts) > 2 else None,
                    "raw": line,
                }
        return {"installed": False, "version": None}

    def supports_operation(self, operation: str, name_or_id: Optional[str] = None) -> bool:
        op = operation.upper()
        if op == "UPDATE" and name_or_id:
            # Check for known publisher-managed packages that cannot be upgraded via WinGet
            nid = name_or_id.lower()
            if "anaconda" in nid:
                return False
        return super().supports_operation(op, name_or_id)

    def supports_dry_run(self) -> bool:
        return False

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
