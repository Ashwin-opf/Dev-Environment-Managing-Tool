"""
pkg_discovery.py — Dynamic Package Discovery Engine
=====================================================
Replaces every hardcoded package-ID map in the project.

Supported managers
  Windows  : winget (main source → msstore fallback)
  Linux    : apt-cache + snap + flatpak
  macOS    : brew
  Any OS   : npm (registry.npmjs.org) + PyPI (pypi.org/pypi)

Public API
  search_packages(query, manager="auto")   -> list[PkgResult]
  get_package_details(pkg_id, manager)     -> PkgDetails | None
  build_install_command(pkg_id, manager, classic=False) -> str
  detect_manager()                         -> str
"""
from __future__ import annotations

import asyncio
import json
import platform
import re
import subprocess
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PkgResult:
    id: str
    name: str
    version: str
    source: str        # e.g. "winget", "msstore", "apt", "snap", "brew", "npm", "pypi"
    manager: str       # command used: "winget", "apt", "snap", "brew", "npm", "pip"
    description: str = ""
    publisher: str = ""
    match_score: int = 0   # 0-100, higher = better match


@dataclass
class PkgDetails:
    id: str
    name: str
    description: str
    publisher: str
    version: str
    url: str
    license: str
    manager: str
    source: str
    install_cmd: str
    genre: str = ""         # e.g. "Developer Tool", "IDE", "CLI", "Browser"
    classic: bool = False   # snap --classic flag


# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

def detect_manager() -> str:
    """Return the primary system package manager name."""
    sys = platform.system()
    if sys == "Windows":
        return "winget"
    if sys == "Darwin":
        return "brew"
    # Linux — prefer apt if available
    import shutil
    if shutil.which("apt-get") or shutil.which("apt"):
        return "apt"
    if shutil.which("dnf"):
        return "dnf"
    if shutil.which("pacman"):
        return "pacman"
    return "apt"   # safest default on Linux


# ---------------------------------------------------------------------------
# Command runner helpers
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 20   # seconds per subprocess call


def _run(args: list[str], timeout: int = _DEFAULT_TIMEOUT) -> tuple[str, int]:
    """Run a subprocess and return (stdout+stderr combined, returncode)."""
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return (result.stdout + result.stderr), result.returncode
    except subprocess.TimeoutExpired:
        return "", 1
    except FileNotFoundError:
        return "", 127   # command not found


def _http_get(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch a URL and return body text, or None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PC-Doctor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Score helper
# ---------------------------------------------------------------------------

def _score(query: str, result_id: str, result_name: str, result_publisher: str = "") -> int:
    q = query.lower().strip()
    rid = result_id.lower()
    rname = result_name.lower()
    rpub = result_publisher.lower()
    if rname == q or rid == q:
        return 100
    if rname.startswith(q) or rid.startswith(q):
        return 90
    if q in rname or q in rid:
        return 75
    words = q.split()
    if all(w in rname for w in words) or all(w in rid for w in words):
        return 60
    if any(w in rname for w in words) or any(w in rid for w in words):
        return 40
    if q in rpub:
        return 20
    return 5


# ---------------------------------------------------------------------------
# winget search / show
# ---------------------------------------------------------------------------

def _parse_winget_search(output: str, query: str, source: str) -> list[PkgResult]:
    """Parse `winget search` tabular output into PkgResult list."""
    results: list[PkgResult] = []
    lines = output.splitlines()

    # Find the header line (contains "Name" and "Id")
    header_idx = -1
    for i, line in enumerate(lines):
        if re.search(r"\bName\b.*\bId\b", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx == -1:
        return results

    # Determine column offsets from header
    header = lines[header_idx]
    # Skip separator line
    data_start = header_idx + 1
    if data_start < len(lines) and re.match(r"^[-\s]+$", lines[data_start]):
        data_start += 1

    # Find column positions
    name_start = header.lower().find("name")
    id_start = header.lower().find("id")
    ver_start = header.lower().find("version")
    src_start = header.lower().find("source")
    if id_start == -1:
        return results

    for line in lines[data_start:]:
        if not line.strip() or line.strip().startswith("--"):
            continue
        try:
            name = line[name_start:id_start].strip() if id_start > name_start else ""
            id_end = ver_start if ver_start > id_start else (src_start if src_start > id_start else len(line))
            pkg_id = line[id_start:id_end].strip()
            version = line[ver_start:src_start].strip() if ver_start > 0 and src_start > ver_start else ""
            if not pkg_id:
                continue
            results.append(PkgResult(
                id=pkg_id,
                name=name or pkg_id,
                version=version,
                source=source,
                manager="winget",
                match_score=_score(query, pkg_id, name),
            ))
        except Exception:
            continue

    return results


def _winget_search(query: str, source: str = "") -> list[PkgResult]:
    """Run winget search and return parsed results."""
    args = ["winget", "search", query,
            "--accept-source-agreements",
            "--disable-interactivity"]
    if source:
        args += ["--source", source]

    output, rc = _run(args, timeout=20)
    if rc != 0 and not output.strip():
        return []
    return _parse_winget_search(output, query, source or "winget")


def _winget_show(pkg_id: str, source: str = "") -> Optional[PkgDetails]:
    """Run `winget show --id <id>` and parse details."""
    args = ["winget", "show", "--id", pkg_id, "--exact",
            "--accept-source-agreements",
            "--disable-interactivity"]
    if source:
        args += ["--source", source]

    output, rc = _run(args, timeout=20)
    if not output.strip():
        return None

    def _extract(pattern: str) -> str:
        m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    name        = _extract(r"^Found\s+(.+?)\s*\[")
    if not name:
        name    = _extract(r"^\s*Name\s*:\s+(.+)$")
    publisher   = _extract(r"Publisher\s*:\s+(.+)$")
    version     = _extract(r"Version\s*:\s+(.+)$")
    url         = _extract(r"(?:Homepage|Publisher\s+Url|Url)\s*:\s+(https?://\S+)")
    description = _extract(r"Description\s*:\s+(.+)$")
    license_    = _extract(r"License\s*:\s+(.+)$")

    install_cmd = build_install_command(pkg_id, "winget")

    return PkgDetails(
        id=pkg_id,
        name=name or pkg_id,
        description=description,
        publisher=publisher,
        version=version,
        url=url,
        license=license_,
        manager="winget",
        source=source or "winget",
        install_cmd=install_cmd,
        genre=_guess_genre(pkg_id, name, description),
    )


# ---------------------------------------------------------------------------
# apt search / show
# ---------------------------------------------------------------------------

def _apt_search(query: str) -> list[PkgResult]:
    output, _ = _run(["apt-cache", "search", query], timeout=15)
    results = []
    for line in output.splitlines():
        if " - " not in line:
            continue
        pkg_id, desc = line.split(" - ", 1)
        pkg_id = pkg_id.strip()
        results.append(PkgResult(
            id=pkg_id,
            name=pkg_id,
            version="",
            source="apt",
            manager="apt",
            description=desc.strip(),
            match_score=_score(query, pkg_id, pkg_id),
        ))
    return results[:20]


def _apt_show(pkg_id: str) -> Optional[PkgDetails]:
    output, rc = _run(["apt-cache", "show", pkg_id], timeout=10)
    if rc != 0:
        return None

    def _extract(pattern: str) -> str:
        m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    return PkgDetails(
        id=pkg_id,
        name=_extract(r"^Package:\s+(.+)$") or pkg_id,
        description=_extract(r"^Description(?:-\w+)?:\s+(.+)$"),
        publisher=_extract(r"^Maintainer:\s+(.+)$"),
        version=_extract(r"^Version:\s+(.+)$"),
        url=_extract(r"^Homepage:\s+(.+)$"),
        license=_extract(r"^License:\s+(.+)$"),
        manager="apt",
        source="apt",
        install_cmd=build_install_command(pkg_id, "apt"),
        genre=_guess_genre(pkg_id, pkg_id, ""),
    )


# ---------------------------------------------------------------------------
# snap search / info
# ---------------------------------------------------------------------------

def _snap_search(query: str) -> list[PkgResult]:
    output, _ = _run(["snap", "find", query], timeout=15)
    results = []
    lines = output.splitlines()
    # Header: Name  Version  Publisher  Notes  Summary
    data_start = 1
    for line in lines[data_start:]:
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2:
            continue
        pkg_id = parts[0].strip()
        version = parts[1].strip() if len(parts) > 1 else ""
        desc = parts[-1].strip() if len(parts) > 3 else ""
        results.append(PkgResult(
            id=pkg_id,
            name=pkg_id,
            version=version,
            source="snap",
            manager="snap",
            description=desc,
            match_score=_score(query, pkg_id, pkg_id),
        ))
    return results[:10]


def _snap_info(pkg_id: str) -> Optional[PkgDetails]:
    output, rc = _run(["snap", "info", pkg_id], timeout=10)
    if rc != 0:
        return None

    def _extract(pattern: str) -> str:
        m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    classic = "--classic" in output.lower() or "classic" in _extract(r"confinement:\s*(.+)$").lower()

    return PkgDetails(
        id=pkg_id,
        name=_extract(r"^name:\s+(.+)$") or pkg_id,
        description=_extract(r"^summary:\s+(.+)$"),
        publisher=_extract(r"^publisher:\s+(.+)$"),
        version=_extract(r"^version:\s+(.+)$"),
        url=_extract(r"^store-url:\s+(.+)$"),
        license=_extract(r"^license:\s+(.+)$"),
        manager="snap",
        source="snap",
        install_cmd=build_install_command(pkg_id, "snap", classic=classic),
        genre=_guess_genre(pkg_id, pkg_id, ""),
        classic=classic,
    )


# ---------------------------------------------------------------------------
# flatpak search / info
# ---------------------------------------------------------------------------

def _flatpak_search(query: str) -> list[PkgResult]:
    output, _ = _run(["flatpak", "search", query], timeout=15)
    results = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else ""
        pkg_id = parts[2].strip() if len(parts) > 2 else ""
        version = parts[3].strip() if len(parts) > 3 else ""
        if not pkg_id:
            continue
        results.append(PkgResult(
            id=pkg_id,
            name=name,
            version=version,
            source="flatpak",
            manager="flatpak",
            description=desc,
            match_score=_score(query, pkg_id, name),
        ))
    return results[:10]


def _flatpak_info(pkg_id: str) -> Optional[PkgDetails]:
    output, rc = _run(["flatpak", "info", pkg_id], timeout=10)
    if rc != 0:
        return None

    def _extract(pattern: str) -> str:
        m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    return PkgDetails(
        id=pkg_id,
        name=_extract(r"^\s*Name:\s+(.+)$") or pkg_id,
        description=_extract(r"^\s*Summary:\s+(.+)$"),
        publisher=_extract(r"^\s*Developer:\s+(.+)$"),
        version=_extract(r"^\s*Version:\s+(.+)$"),
        url=_extract(r"^\s*Homepage:\s+(.+)$"),
        license=_extract(r"^\s*License:\s+(.+)$"),
        manager="flatpak",
        source="flatpak",
        install_cmd=build_install_command(pkg_id, "flatpak"),
        genre=_guess_genre(pkg_id, pkg_id, ""),
    )


# ---------------------------------------------------------------------------
# brew search / info
# ---------------------------------------------------------------------------

def _brew_search(query: str) -> list[PkgResult]:
    output, _ = _run(["brew", "search", query], timeout=15)
    results = []
    for line in output.splitlines():
        pkg_id = line.strip()
        if not pkg_id or pkg_id.startswith("==>"):
            continue
        results.append(PkgResult(
            id=pkg_id,
            name=pkg_id,
            version="",
            source="brew",
            manager="brew",
            match_score=_score(query, pkg_id, pkg_id),
        ))
    return results[:15]


def _brew_info(pkg_id: str) -> Optional[PkgDetails]:
    output, rc = _run(["brew", "info", "--json=v2", pkg_id], timeout=15)
    if rc != 0:
        return None
    try:
        data = json.loads(output)
        item = (data.get("formulae") or data.get("casks") or [{}])[0]
        desc = item.get("desc", "")
        homepage = item.get("homepage", "")
        version = (item.get("versions") or {}).get("stable", "")
        name = item.get("full_name") or item.get("token") or pkg_id
        return PkgDetails(
            id=pkg_id,
            name=name,
            description=desc,
            publisher="",
            version=version,
            url=homepage,
            license=item.get("license", ""),
            manager="brew",
            source="brew",
            install_cmd=build_install_command(pkg_id, "brew"),
            genre=_guess_genre(pkg_id, name, desc),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# npm registry (registry.npmjs.org)
# ---------------------------------------------------------------------------

def _npm_search(query: str) -> list[PkgResult]:
    url = f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(query)}&size=8"
    body = _http_get(url, timeout=10)
    if not body:
        return []
    try:
        data = json.loads(body)
        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            pkg_id = pkg.get("name", "")
            if not pkg_id:
                continue
            results.append(PkgResult(
                id=pkg_id,
                name=pkg_id,
                version=pkg.get("version", ""),
                source="npm",
                manager="npm",
                description=pkg.get("description", ""),
                publisher=(pkg.get("publisher") or {}).get("username", ""),
                match_score=_score(query, pkg_id, pkg_id),
            ))
        return results
    except Exception:
        return []


def _npm_details(pkg_id: str) -> Optional[PkgDetails]:
    url = f"https://registry.npmjs.org/{urllib.parse.quote(pkg_id)}"
    body = _http_get(url, timeout=10)
    if not body:
        return None
    try:
        data = json.loads(body)
        latest_ver = data.get("dist-tags", {}).get("latest", "")
        info = data.get("versions", {}).get(latest_ver, {})
        return PkgDetails(
            id=pkg_id,
            name=data.get("name", pkg_id),
            description=data.get("description", ""),
            publisher=(data.get("author") or {}).get("name", ""),
            version=latest_ver,
            url=data.get("homepage", f"https://npmjs.com/package/{pkg_id}"),
            license=info.get("license", ""),
            manager="npm",
            source="npm",
            install_cmd=build_install_command(pkg_id, "npm"),
            genre="Node.js Package",
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# PyPI (pypi.org/pypi/<pkg>/json)
# ---------------------------------------------------------------------------

def _pypi_search(query: str) -> list[PkgResult]:
    """
    PyPI has no free search API — use the Simple JSON index heuristic:
    fetch https://pypi.org/simple/<query>/json and if it 200s, it's a match.
    For general search, use the unofficial search endpoint (limited).
    """
    # Try direct package lookup first (exact or close match)
    results = []
    slug = query.lower().replace(" ", "-")
    url = f"https://pypi.org/pypi/{urllib.parse.quote(slug)}/json"
    body = _http_get(url, timeout=8)
    if body:
        try:
            data = json.loads(body)
            info = data.get("info", {})
            pkg_id = info.get("name", slug)
            results.append(PkgResult(
                id=pkg_id,
                name=pkg_id,
                version=info.get("version", ""),
                source="pypi",
                manager="pip",
                description=info.get("summary", ""),
                publisher=info.get("author", ""),
                match_score=_score(query, pkg_id, pkg_id),
            ))
        except Exception:
            pass

    # Also try the XMLRPC search (deprecated but still works for some queries)
    # Skipped to avoid extra complexity; exact match is sufficient for install flow.
    return results


def _pypi_details(pkg_id: str) -> Optional[PkgDetails]:
    url = f"https://pypi.org/pypi/{urllib.parse.quote(pkg_id)}/json"
    body = _http_get(url, timeout=10)
    if not body:
        return None
    try:
        data = json.loads(body)
        info = data.get("info", {})
        return PkgDetails(
            id=info.get("name", pkg_id),
            name=info.get("name", pkg_id),
            description=info.get("summary", ""),
            publisher=info.get("author", ""),
            version=info.get("version", ""),
            url=info.get("home_page") or info.get("project_url") or f"https://pypi.org/project/{pkg_id}",
            license=info.get("license", ""),
            manager="pip",
            source="pypi",
            install_cmd=build_install_command(pkg_id, "pip"),
            genre="Python Package",
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Genre guesser (no hardcoding — keyword-based heuristic)
# ---------------------------------------------------------------------------

_GENRE_RULES: list[tuple[list[str], str]] = [
    (["studio", "ide", "pycharm", "intellij", "eclipse", "xcode", "code", "editor", "sublime", "atom"], "IDE / Editor"),
    (["browser", "chrome", "firefox", "safari", "edge", "brave", "opera"], "Web Browser"),
    (["docker", "kubernetes", "k8s", "container", "helm", "podman", "compose"], "DevOps / Containers"),
    (["git", "svn", "mercurial", "vcs", "version control", "github"], "Version Control"),
    (["python", "node", "ruby", "java", "go", "rust", "php", "swift", "kotlin", "dart", "scala"], "Programming Language"),
    (["npm", "pip", "cargo", "brew", "pnpm", "yarn", "poetry", "gradle", "maven", "nuget"], "Package Manager"),
    (["database", "postgres", "mysql", "sqlite", "mongo", "redis", "dbeaver", "sql"], "Database Tool"),
    (["postman", "insomnia", "curl", "http", "api", "rest", "graphql", "grpc"], "API / Testing"),
    (["ai", "ollama", "llm", "copilot", "codex", "ml", "model", "neural"], "AI / ML Tool"),
    (["terminal", "shell", "bash", "zsh", "tmux", "htop", "fzf", "jq", "cli", "command"], "CLI / Terminal"),
    (["slack", "discord", "teams", "zoom", "notion", "figma", "linear"], "Productivity"),
    (["snap", "flatpak", "winget", "apt", "choco", "scoop"], "Package Manager"),
]


def _guess_genre(pkg_id: str, name: str, description: str) -> str:
    combined = (pkg_id + " " + name + " " + description).lower()
    for keywords, genre in _GENRE_RULES:
        if any(k in combined for k in keywords):
            return genre
    return "Developer Tool"


# ---------------------------------------------------------------------------
# build_install_command — template engine, zero hardcoding
# ---------------------------------------------------------------------------

def build_install_command(pkg_id: str, manager: str, classic: bool = False) -> str:
    """
    Build the correct install command for the given manager.
    Uses only the pkg_id provided by the caller — no internal ID map.
    """
    m = manager.lower().strip()
    if m == "winget":
        return (
            f"winget install --id {pkg_id} -e "
            "--accept-package-agreements --accept-source-agreements --silent"
        )
    if m == "msstore":
        return (
            f"winget install {pkg_id} --source msstore "
            "--accept-package-agreements --accept-source-agreements --silent"
        )
    if m == "apt":
        return f"sudo apt-get update && sudo apt-get install -y {pkg_id}"
    if m == "snap":
        classic_flag = " --classic" if classic else ""
        return f"sudo snap install {pkg_id}{classic_flag}"
    if m == "flatpak":
        return f"flatpak install flathub {pkg_id} -y"
    if m == "brew":
        return f"brew install {pkg_id}"
    if m == "npm":
        return f"npm install -g {pkg_id}"
    if m == "pip":
        return f"pip install {pkg_id}"
    if m == "cargo":
        return f"cargo install {pkg_id}"
    if m == "dnf":
        return f"sudo dnf install -y {pkg_id}"
    if m == "pacman":
        return f"sudo pacman -S --noconfirm {pkg_id}"
    # Generic fallback
    return f"# Unknown manager '{manager}' — install {pkg_id} manually"


def build_update_command(pkg_id: str, manager: str) -> str:
    """Build a verified, non-interactive upgrade command."""
    m = manager.lower().strip()
    if m == "winget":
        return (
            f"winget upgrade --id {pkg_id} -e "
            "--accept-package-agreements --accept-source-agreements --silent"
        )
    if m == "msstore":
        return (
            f"winget upgrade {pkg_id} --source msstore "
            "--accept-package-agreements --accept-source-agreements --silent"
        )
    if m == "apt":
        return f"sudo apt-get update && sudo apt-get --only-upgrade install -y {pkg_id}"
    if m == "snap":
        return f"sudo snap refresh {pkg_id}"
    if m == "flatpak":
        return f"flatpak update {pkg_id} -y"
    if m == "brew":
        return f"brew upgrade {pkg_id}"
    if m == "npm":
        return f"npm install -g {pkg_id}@latest"
    if m == "pip":
        return f"pip install --upgrade {pkg_id}"
    if m == "choco":
        return f"choco upgrade {pkg_id} -y"
    if m == "scoop":
        return f"scoop update {pkg_id}"
    return build_install_command(pkg_id, manager)



# ---------------------------------------------------------------------------
# Context-aware manager hint
# ---------------------------------------------------------------------------

_NPM_HINTS = {"typescript", "ts-node", "eslint", "prettier", "vite", "webpack",
              "nodemon", "pm2", "nx", "turbo", "create-react-app", "next",
              "express", "jest", "vitest", "rollup", "esbuild"}
_PIP_HINTS = {"ruff", "black", "mypy", "pylint", "flake8", "pytest", "ipython",
              "jupyter", "pandas", "numpy", "fastapi", "flask", "django",
              "uvicorn", "gunicorn", "poetry", "pipx", "httpx", "requests"}


def _context_managers(query: str, primary: str) -> list[str]:
    """
    Return a prioritised list of managers to try for `query`.
    Always includes the OS primary manager; adds npm/pip if query is a known
    ecosystem package.
    """
    q = query.lower().strip()
    managers = [primary]
    # On Windows, also try msstore as fallback
    if primary == "winget" and "msstore" not in managers:
        managers.append("msstore")
    # npm heuristic
    if any(h in q for h in _NPM_HINTS) or q.startswith("@"):
        managers = ["npm"] + managers
    # pip heuristic
    if any(h in q for h in _PIP_HINTS):
        managers = ["pip"] + managers
    return managers


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def search_packages(query: str, manager: str = "auto", include_npm: bool = True,
                    include_pypi: bool = True) -> list[PkgResult]:
    """
    Search all relevant package managers for `query`.

    Parameters
    ----------
    query        : search term (app name, partial name, etc.)
    manager      : "auto" to detect from OS, or explicit manager name
    include_npm  : also search npm registry
    include_pypi : also search PyPI

    Returns
    -------
    List of PkgResult sorted by match_score descending, deduplicated by id.
    """
    if not query.strip():
        return []

    primary = detect_manager() if manager == "auto" else manager.lower()
    results: list[PkgResult] = []

    # --- OS-level search ---
    if primary == "winget":
        # Pass 1: default winget source
        winget_results = _winget_search(query)
        results.extend(winget_results)
        # Pass 2: msstore fallback if pass 1 was empty
        if not winget_results:
            results.extend(_winget_search(query, source="msstore"))

    elif primary == "apt":
        results.extend(_apt_search(query))
        # Also try snap if available
        import shutil
        if shutil.which("snap"):
            results.extend(_snap_search(query))
        if shutil.which("flatpak"):
            results.extend(_flatpak_search(query))

    elif primary == "brew":
        results.extend(_brew_search(query))

    elif primary == "snap":
        results.extend(_snap_search(query))

    elif primary == "flatpak":
        results.extend(_flatpak_search(query))

    elif primary in ("npm",):
        results.extend(_npm_search(query))

    elif primary in ("pip",):
        results.extend(_pypi_search(query))

    # --- Cross-platform ecosystem search ---
    if include_npm and primary != "npm":
        npm_r = _npm_search(query)
        results.extend(npm_r)

    if include_pypi and primary != "pip":
        pypi_r = _pypi_search(query)
        results.extend(pypi_r)

    # De-duplicate by id (keep highest score)
    seen: dict[str, PkgResult] = {}
    for r in results:
        key = r.id.lower()
        if key not in seen or r.match_score > seen[key].match_score:
            seen[key] = r

    sorted_results = sorted(seen.values(), key=lambda r: r.match_score, reverse=True)
    return sorted_results[:12]


def get_package_details(pkg_id: str, manager: str) -> Optional[PkgDetails]:
    """
    Fetch full metadata for a confirmed package ID from its manager.
    """
    m = manager.lower().strip()
    if m == "winget":
        return _winget_show(pkg_id)
    if m == "msstore":
        return _winget_show(pkg_id, source="msstore")
    if m == "apt":
        return _apt_show(pkg_id)
    if m == "snap":
        return _snap_info(pkg_id)
    if m == "flatpak":
        return _flatpak_info(pkg_id)
    if m == "brew":
        return _brew_info(pkg_id)
    if m == "npm":
        return _npm_details(pkg_id)
    if m == "pip":
        return _pypi_details(pkg_id)
    return None


def search_and_auto_pick(app_name: str) -> Optional[tuple[str, str, str]]:
    """
    Convenience wrapper for the repair engine.

    Searches, picks the best result, and returns
    (install_cmd, pkg_id, manager) or None if nothing was found.
    """
    results = search_packages(app_name, include_npm=True, include_pypi=True)
    if not results:
        return None
    top = results[0]
    cmd = build_install_command(top.id, top.manager)
    return cmd, top.id, top.manager
