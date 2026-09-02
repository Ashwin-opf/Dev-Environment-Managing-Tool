"""
Snap Package Manager Adapter (Linux - Ubuntu Snap Store)
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


class SnapAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'snap'

    def is_available(self) -> bool:
        return shutil.which('snap') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['snap', 'find', query])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('Name') or line.startswith('-'):
                continue
            parts = [p for p in line.split('  ') if p.strip()]
            if len(parts) >= 1:
                results.append({
                    'name': parts[0].strip(),
                    'id': parts[0].strip(),
                    'version': parts[1].strip() if len(parts) > 1 else 'latest',
                    'description': parts[3].strip() if len(parts) > 3 else f'Snap package {parts[0]}',
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['snap', 'info', name])
        for line in out.splitlines():
            if line.strip().startswith('latest/stable:'):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'sudo snap install {name}{extra}'

    def remove(self, name: str) -> str:
        return f'sudo snap remove {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['snap', 'info', name])
        desc = f'Snap package {name}'
        homepage = ''
        for line in out.splitlines():
            if line.startswith('summary:'):
                desc = line.split(':', 1)[1].strip()
            elif line.startswith('contact:') or line.startswith('website:'):
                homepage = line.split(':', 1)[1].strip()
        return {
            'name': name,
            'version': self.resolve_latest(name),
            'dependencies': [],
            'homepage': homepage or f'https://snapcraft.io/{name}',
            'description': desc,
        }
