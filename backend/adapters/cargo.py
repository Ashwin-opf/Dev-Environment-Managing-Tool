"""
Cargo Package Manager Adapter (Rust crates)
"""

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional
from .base import BaseAdapter


def _safe_run(cmd: List[str], timeout: int = 12) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
        return res.stdout or ''
    except Exception:
        return ''


class CargoAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'cargo'

    def is_available(self) -> bool:
        return shutil.which('cargo') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['cargo', 'search', query, '--limit', '10'])
        results = []
        for line in out.splitlines():
            line = line.strip()
            if '=' in line and '#' in line:
                try:
                    name_ver, desc = line.split('#', 1)
                    name, ver = name_ver.split('=', 1)
                    results.append({
                        'name': name.strip(),
                        'id': name.strip(),
                        'version': ver.strip().strip('"'),
                        'description': desc.strip(),
                    })
                except Exception:
                    pass
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        results = self.search(name)
        for r in results:
            if r['name'] == name:
                return r['version']
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        extra = ' ' + ' '.join(constraints) if constraints else ''
        return f'cargo install {name}{extra}'

    def remove(self, name: str) -> str:
        return f'cargo uninstall {name}'

    def info(self, name: str) -> Dict[str, Any]:
        try:
            import urllib.request, json as _json
            url = f'https://crates.io/api/v1/crates/{name}'
            req = urllib.request.Request(url, headers={'User-Agent': 'pc-doctor/1.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            crate = data.get('crate', {})
            return {
                'name': name,
                'version': crate.get('newest_version', 'latest'),
                'dependencies': [],
                'homepage': crate.get('homepage') or crate.get('repository') or f'https://crates.io/crates/{name}',
                'description': (crate.get('description') or f'Rust crate {name}')[:200],
            }
        except Exception:
            return {
                'name': name,
                'version': 'latest',
                'dependencies': [],
                'homepage': f'https://crates.io/crates/{name}',
                'description': f'Rust crate {name}',
            }
