"""
Homebrew Package Manager Adapter (macOS + Linux)
"""

import json
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


class BrewAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'brew'

    def is_available(self) -> bool:
        return shutil.which('brew') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['brew', 'search', '--formula', query])
        results = []
        for line in out.splitlines():
            pkg = line.strip()
            if pkg and not pkg.startswith('=='):
                results.append({
                    'name': pkg,
                    'id': pkg,
                    'version': self.resolve_latest(pkg),
                    'description': f'Homebrew formula {pkg}',
                })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['brew', 'info', '--json=v2', name])
        try:
            data = json.loads(out)
            formulae = data.get('formulae', [])
            if formulae:
                return formulae[0].get('versions', {}).get('stable', 'latest')
        except Exception:
            pass
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'brew install {name}{extra}'

    def remove(self, name: str) -> str:
        return f'brew uninstall {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['brew', 'info', '--json=v2', name])
        try:
            data = json.loads(out)
            formulae = data.get('formulae', [])
            if formulae:
                f = formulae[0]
                deps = f.get('dependencies', [])
                return {
                    'name': name,
                    'version': f.get('versions', {}).get('stable', 'latest'),
                    'dependencies': deps[:10],
                    'homepage': f.get('homepage', f'https://formulae.brew.sh/formula/{name}'),
                    'description': f.get('desc', f'Homebrew formula {name}'),
                }
        except Exception:
            pass
        return {
            'name': name,
            'version': 'latest',
            'dependencies': [],
            'homepage': f'https://formulae.brew.sh/formula/{name}',
            'description': f'Homebrew formula {name}',
        }
