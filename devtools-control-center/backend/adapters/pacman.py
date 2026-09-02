"""
Pacman Package Manager Adapter (Arch Linux / Manjaro)
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


class PacmanAdapter(BaseAdapter):
    @property
    def name(self) -> str:
        return 'pacman'

    def is_available(self) -> bool:
        return shutil.which('pacman') is not None

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not query:
            return []
        out = _safe_run(['pacman', '-Ss', query])
        results = []
        lines = out.splitlines()
        i = 0
        while i < len(lines) - 1:
            header = lines[i].strip()
            desc_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if '/' in header and ' ' in header:
                parts = header.split(' ')
                pkg_full = parts[0]
                version = parts[1] if len(parts) > 1 else 'latest'
                pkg_name = pkg_full.split('/')[1] if '/' in pkg_full else pkg_full
                results.append({
                    'name': pkg_name,
                    'id': pkg_full,
                    'version': version,
                    'description': desc_line,
                })
                i += 2
            else:
                i += 1
        return results[:15]

    def resolve_latest(self, name: str) -> str:
        out = _safe_run(['pacman', '-Si', name])
        for line in out.splitlines():
            if line.startswith('Version') and ':' in line:
                return line.split(':', 1)[1].strip()
        return 'latest'

    def install(self, name: str, constraints: Optional[List[str]] = None) -> str:
        return f'sudo pacman -S --noconfirm {name}'

    def remove(self, name: str) -> str:
        return f'sudo pacman -Rns --noconfirm {name}'

    def info(self, name: str) -> Dict[str, Any]:
        out = _safe_run(['pacman', '-Si', name])
        deps = []
        homepage = ''
        desc = f'Pacman package {name}'
        for line in out.splitlines():
            if line.startswith('Description') and ':' in line:
                desc = line.split(':', 1)[1].strip()
            elif line.startswith('URL') and ':' in line:
                homepage = line.split(':', 1)[1].strip()
            elif line.startswith('Depends On') and ':' in line:
                raw = line.split(':', 1)[1].strip()
                deps = [d.strip() for d in raw.split() if d.strip() and d != 'None']
        return {
            'name': name,
            'version': self.resolve_latest(name),
            'dependencies': deps[:10],
            'homepage': homepage or f'https://archlinux.org/packages/?q={name}',
            'description': desc,
        }
