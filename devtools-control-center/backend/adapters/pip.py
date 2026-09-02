"""
Pip Package Manager Adapter (Python packages)
"""

import json
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _pip_bin() -> str:
    return sys.executable + ' -m pip'


def _safe_run(cmd: List[str], timeout: int = 10) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
        return res.stdout or ''
    except Exception:
        return ''


class PipAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'pip'

    def is_available(self) -> bool:
        return shutil.which('pip') is not None or shutil.which('pip3') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        # pip search was deprecated; use PyPI JSON API via pypi.org
        try:
            import urllib.request, json as _json
            url = f'https://pypi.org/pypi/{query}/json'
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            info = data.get('info', {})
            return [{
                'name': info.get('name', query),
                'id': info.get('name', query),
                'version': info.get('version', 'latest'),
                'description': (info.get('summary') or '')[:120],
            }]
        except Exception:
            return []

    def resolve_latest(self, name: str) -> str:
        try:
            import urllib.request, json as _json
            url = f'https://pypi.org/pypi/{name}/json'
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            return data.get('info', {}).get('version', 'latest')
        except Exception:
            return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'{sys.executable} -m pip install {name}{extra}'

    def remove(self, name: str) -> str:
        return f'{sys.executable} -m pip uninstall -y {name}'

    def info(self, name: str) -> Dict[str, Any]:
        try:
            import urllib.request, json as _json
            url = f'https://pypi.org/pypi/{name}/json'
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            info = data.get('info', {})
            deps = [r.split(' ')[0].split(';')[0].strip() for r in (info.get('requires_dist') or [])]
            return {
                'name': name,
                'version': info.get('version', 'latest'),
                'dependencies': deps[:10],
                'homepage': info.get('home_page') or info.get('project_url') or f'https://pypi.org/project/{name}/',
                'description': (info.get('summary') or f'PyPI package {name}')[:200],
            }
        except Exception:
            return {
                'name': name,
                'version': 'latest',
                'dependencies': [],
                'homepage': f'https://pypi.org/project/{name}/',
                'description': f'PyPI package {name}',
            }
