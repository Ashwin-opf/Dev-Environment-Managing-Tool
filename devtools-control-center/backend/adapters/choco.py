"""
Chocolatey Package Manager Adapter (Windows)
"""

import shutil
import subprocess
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _safe_run(cmd: List[str], timeout: int = 8) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
        return res.stdout or ''
    except Exception:
        return ''


class ChocoAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'choco'

    def is_available(self) -> bool:
        return shutil.which('choco') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['choco', 'search', query, '--limit-output'])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    results.append({
                        'name': parts[0].strip(),
                        'id': parts[0].strip(),
                        'version': parts[1].strip(),
                        'description': f'Chocolatey package {parts[0].strip()}',
                    })
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['choco', 'info', name, '--limit-output'])
        for line in out.splitlines():
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    return parts[1].strip()
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'choco install {name} -y{extra}'

    def remove(self, name: str) -> str:
        return f'choco uninstall {name} -y'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['choco', 'info', name])
        homepage = ''
        desc = f'Chocolatey package {name}'
        for line in out.splitlines():
            if 'Project Url' in line and ':' in line:
                homepage = line.split(':', 1)[1].strip()
            elif 'Summary' in line and ':' in line:
                desc = line.split(':', 1)[1].strip()
        return {
            'name': name,
            'version': self.resolve_latest(name),
            'dependencies': [],
            'homepage': homepage or f'https://community.chocolatey.org/packages/{name}',
            'description': desc,
        }
