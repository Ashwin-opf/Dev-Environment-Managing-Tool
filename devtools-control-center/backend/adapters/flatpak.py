"""
Flatpak Package Manager Adapter (Linux cross-distro)
"""

import shutil
import subprocess
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _safe_run(cmd: List[str], timeout: int = 10) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
        return res.stdout or ''
    except Exception:
        return ''


class FlatpakAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'flatpak'

    def is_available(self) -> bool:
        return shutil.which('flatpak') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['flatpak', 'search', query, '--columns=name,application,version,description'])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('Name'):
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                results.append({
                    'name': parts[0].strip(),
                    'id': parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                    'version': parts[2].strip() if len(parts) > 2 else 'latest',
                    'description': parts[3].strip() if len(parts) > 3 else f'Flatpak app {parts[0].strip()}',
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        results = self.search(name)
        if results:
            return results[0].get('version', 'latest')
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        return f'flatpak install -y flathub {name}'

    def remove(self, name: str) -> str:
        return f'flatpak uninstall -y {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['flatpak', 'info', name])
        desc = f'Flatpak application {name}'
        homepage = ''
        for line in out.splitlines():
            if line.strip().startswith('Description:'):
                desc = line.split(':', 1)[1].strip()
            elif line.strip().startswith('Url:') or line.strip().startswith('URL:'):
                homepage = line.split(':', 1)[1].strip()
        return {
            'name': name,
            'version': self.resolve_latest(name),
            'dependencies': [],
            'homepage': homepage or f'https://flathub.org/apps/{name}',
            'description': desc,
        }
