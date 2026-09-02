"""
Npm Package Manager Adapter (Node.js packages)
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


class NpmAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'npm'

    def is_available(self) -> bool:
        return shutil.which('npm') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['npm', 'search', '--json', query])
        try:
            data = json.loads(out)
            return [
                {
                    'name': pkg.get('name', ''),
                    'id': pkg.get('name', ''),
                    'version': pkg.get('version', 'latest'),
                    'description': (pkg.get('description') or '')[:120],
                }
                for pkg in data[:15]
            ]
        except Exception:
            return []

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['npm', 'view', name, 'version'])
        return out.strip() or 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'npm install -g {name}{extra}'

    def remove(self, name: str) -> str:
        return f'npm uninstall -g {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['npm', 'view', name, '--json'])
        try:
            data = json.loads(out)
            raw_deps = list((data.get('dependencies') or {}).keys())
            return {
                'name': name,
                'version': data.get('version', 'latest'),
                'dependencies': raw_deps[:10],
                'homepage': data.get('homepage') or f'https://www.npmjs.com/package/{name}',
                'description': (data.get('description') or f'npm package {name}')[:200],
            }
        except Exception:
            return {
                'name': name,
                'version': 'latest',
                'dependencies': [],
                'homepage': f'https://www.npmjs.com/package/{name}',
                'description': f'npm package {name}',
            }
