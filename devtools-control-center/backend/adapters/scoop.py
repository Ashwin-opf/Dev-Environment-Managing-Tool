"""
Scoop Package Manager Adapter (Windows)
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


class ScoopAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'scoop'

    def is_available(self) -> bool:
        return shutil.which('scoop') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['scoop', 'search', query])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith('Results') and not line.startswith('Name') and not line.startswith('-'):
                parts = [p for p in line.split() if p]
                if len(parts) >= 2:
                    results.append({
                        'name': parts[0].strip(),
                        'id': parts[0].strip(),
                        'version': parts[1].strip() if len(parts) > 1 else 'latest',
                        'description': ' '.join(parts[3:]).strip() if len(parts) > 3 else f'Scoop package {parts[0]}',
                    })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['scoop', 'info', name])
        for line in out.splitlines():
            if 'Version' in line and ':' in line:
                return line.split(':', 1)[1].strip()
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        return f'scoop install {name}'

    def remove(self, name: str) -> str:
        return f'scoop uninstall {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['scoop', 'info', name])
        homepage = ''
        desc = f'Scoop package {name}'
        for line in out.splitlines():
            if 'Homepage' in line and ':' in line:
                homepage = line.split(':', 1)[1].strip()
            elif 'Description' in line and ':' in line:
                desc = line.split(':', 1)[1].strip()
        return {
            'name': name,
            'version': self.resolve_latest(name),
            'dependencies': [],
            'homepage': homepage or f'https://scoop.sh/#/apps?q={name}',
            'description': desc,
        }
