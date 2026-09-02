"""
pkg_resolution.py — Robust Package Resolution Pipeline
=======================================================
Wraps and enhances the existing pkg_discovery search/show/install calls.

Features
--------
  1. Fuzzy match + ranking via MatchScorer (difflib + token overlap + variant bonus)
  2. Confidence gate: auto-select only if top score ≥ CONFIDENCE_THRESHOLD
  3. ProvenanceStore: SQLite-backed cache of verified resolutions
  4. Multi-source fallback: adapters run in priority order, short-circuits on confidence
  5. PublisherVerifier: domain cross-check from pkg_catalog.json
  6. Variant disambiguation: CLI vs desktop, community vs professional, etc.

All ranking, caching, and provenance logic is OS/PM-agnostic.
Only the concrete Adapter subclasses call pkg_discovery (OS-specific).
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import sqlite3
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_CATALOG_PATH  = _HERE / "pkg_catalog.json"
_CACHE_DB_PATH = _HERE / "resolution_cache.db"

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ResolutionCandidate:
    pkg_id:       str
    name:         str
    version:      str
    manager:      str           # "winget", "choco", "scoop", "apt", "brew", "npm", "pip"
    source:       str           # "winget", "msstore", "choco", "scoop", "apt", "snap" …
    publisher:    str  = ""
    homepage:     str  = ""
    description:  str  = ""
    fuzzy_score:  float = 0.0   # 0–100: name/id similarity
    trust_score:  float = 50.0  # 0–100: publisher trust signal
    total_score:  float = 0.0   # weighted: 0.7*fuzzy + 0.3*trust
    variant_tags: list  = field(default_factory=list)   # e.g. ["cli"], ["desktop"]
    verified:     Optional[bool] = None   # True/False/None


@dataclass
class ResolutionResult:
    status:      str            # "auto_selected" | "needs_disambiguation" | "not_found"
    selected:    Optional[ResolutionCandidate]
    candidates:  list[ResolutionCandidate]
    confidence:  float
    from_cache:  bool
    source_used: str
    install_cmd: str


@dataclass
class ProvenanceRecord:
    query_name:      str
    variant:         str
    resolved_id:     str
    manager:         str
    source:          str
    publisher:       str
    homepage:        str
    verified:        Optional[bool]
    verified_at:     str        # ISO-8601
    install_success: bool
    last_used:       str        # ISO-8601


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------

class _Catalog:
    """Loads pkg_catalog.json once and provides lookup helpers."""

    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                self._data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[pkg_resolution] Warning: could not load pkg_catalog.json: {e}")
                self._data = {"confidence_threshold": 80.0, "tools": [], "adapter_priority": {}}
            self._loaded = True

    @property
    def confidence_threshold(self) -> float:
        self._ensure_loaded()
        return float(self._data.get("confidence_threshold", 80.0))

    @property
    def adapter_priority(self) -> dict:
        self._ensure_loaded()
        return self._data.get("adapter_priority", {})

    def find_tool(self, query: str) -> Optional[dict]:
        """Return catalog entry whose 'names' list matches query (case-insensitive)."""
        self._ensure_loaded()
        q = query.lower().strip()
        for tool in self._data.get("tools", []):
            if q in [n.lower() for n in tool.get("names", [])]:
                return tool
            # Partial match: query is contained in any name
            for n in tool.get("names", []):
                if q in n.lower() or n.lower() in q:
                    return tool
        return None

    def known_domains(self, query: str) -> list[str]:
        t = self.find_tool(query)
        if not t:
            return []
        raw = t.get("known_domain", [])
        if isinstance(raw, list):
            return [str(d) for d in raw]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []

    def default_variant(self, query: str) -> str:
        t = self.find_tool(query)
        return (t or {}).get("default_variant", "")

    def variant_config(self, query: str, variant: str) -> dict:
        t = self.find_tool(query)
        if not t:
            return {}
        return t.get("variants", {}).get(variant, {})


CATALOG = _Catalog()


# ---------------------------------------------------------------------------
# MatchScorer
# ---------------------------------------------------------------------------

class MatchScorer:
    """
    Ranks candidates by name/id similarity + variant bonus.
    Uses only stdlib (difflib.SequenceMatcher) — no third-party deps.
    """

    CONFIDENCE_THRESHOLD: float = 80.0  # override via CATALOG.confidence_threshold

    @staticmethod
    def _seq_ratio(a: str, b: str) -> float:
        """0.0–1.0 similarity ratio between two strings."""
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

    @staticmethod
    def _token_coverage(query: str, text: str) -> float:
        """Fraction of query tokens present in text (0.0–1.0)."""
        tokens = query.lower().split()
        if not tokens:
            return 0.0
        text_l = text.lower()
        return sum(1 for t in tokens if t in text_l) / len(tokens)

    def score_candidate(
        self,
        query: str,
        c: ResolutionCandidate,
        variant_hint: str = "",
    ) -> ResolutionCandidate:
        """Compute and attach fuzzy_score + total_score to the candidate in-place."""
        q = query.lower().strip()
        c_name = c.name.lower().strip()
        c_id = c.pkg_id.lower().strip()

        # --- Name similarity (40%) ---
        if c_name == q:
            name_sim = 100.0
        elif c_name.startswith(q + " ") or c_name.endswith(" " + q) or f" {q} " in f" {c_name} ":
            name_sim = 95.0
        else:
            name_sim = self._seq_ratio(q, c.name) * 100

        # --- ID similarity (25%) ---
        # Use only the last segment of the ID (e.g. "Git.Git" → "git")
        id_tail = c_id.split(".")[-1].replace("-", " ").strip()
        if c_id == q or id_tail == q or c_id == f"{q}.{q}":
            id_sim = 100.0
        elif c_id.startswith(q + ".") or c_id.endswith("." + q):
            id_sim = 90.0
        else:
            id_sim = max(
                self._seq_ratio(q, c.pkg_id) * 100,
                self._seq_ratio(q, id_tail)  * 100,
            )

        # --- Token coverage (20%) ---
        token_cov = max(
            self._token_coverage(q, c.name),
            self._token_coverage(q, c.pkg_id),
        ) * 100

        # --- Variant bonus (15%) ---
        variant_bonus = 50.0
        if variant_hint and c.variant_tags:
            if variant_hint.lower() in [v.lower() for v in c.variant_tags]:
                variant_bonus = 100.0
            else:
                variant_bonus = 10.0   # some tags but wrong variant
        elif not variant_hint:
            variant_bonus = 80.0       # neutral-high if no variant disambiguation needed
        elif variant_hint and not c.variant_tags:
            variant_bonus = 50.0

        fuzzy = 0.40 * name_sim + 0.25 * id_sim + 0.20 * token_cov + 0.15 * variant_bonus

        # Exact overall match boost
        if (c_name == q or id_tail == q or c_id == q or c_id == f"{q}.{q}"):
            fuzzy = max(fuzzy, 92.0)

        # Clamp
        fuzzy = min(100.0, max(0.0, fuzzy))

        c.fuzzy_score = round(fuzzy, 1)
        c.total_score = round(0.70 * c.fuzzy_score + 0.30 * c.trust_score, 1)
        return c

    def rank(
        self,
        query: str,
        candidates: list[ResolutionCandidate],
        variant_hint: str = "",
    ) -> list[ResolutionCandidate]:
        """Score all candidates and return sorted list (best first)."""
        for c in candidates:
            self.score_candidate(query, c, variant_hint)
        return sorted(candidates, key=lambda c: c.total_score, reverse=True)

    def is_confident(self, candidate: ResolutionCandidate) -> bool:
        threshold = CATALOG.confidence_threshold or self.CONFIDENCE_THRESHOLD
        return candidate.total_score >= threshold


SCORER = MatchScorer()


# ---------------------------------------------------------------------------
# PublisherVerifier
# ---------------------------------------------------------------------------

class PublisherVerifier:
    """
    Cross-checks candidate.homepage against known official domains.
    Pure string matching — no network requests.
    """

    def _extract_domain(self, url: str) -> str:
        """Return the registered domain (e.g. 'github.com') from a URL."""
        if not url:
            return ""
        url = url.strip().lower()
        if not url.startswith("http"):
            url = "https://" + url
        try:
            host = urllib.parse.urlparse(url).netloc
            # Strip www. prefix
            return host.removeprefix("www.")
        except Exception:
            return url

    def verify(
        self,
        candidate: ResolutionCandidate,
        known_domains: list[str] | str = "",
    ) -> Optional[bool]:
        """
        Returns:
          True   — homepage matches one of the known_domains (or is a subdomain)
          False  — homepage present but DOES NOT match known_domains
          None   — no known_domain, cannot verify
        """
        if isinstance(known_domains, str):
            domains = [known_domains] if known_domains.strip() else []
        else:
            domains = [d for d in known_domains if d.strip()]

        if not domains:
            return None

        hp = self._extract_domain(candidate.homepage)
        if not hp:
            return None  # no homepage in package metadata

        for kd_raw in domains:
            kd = self._extract_domain(kd_raw)
            if not kd:
                continue

            # Match if homepage domain ends with known_domain (handles subdomains)
            if hp == kd or hp.endswith("." + kd) or kd.endswith("." + hp):
                return True

            # Some packages use github.com/publisher/repo — tolerate that
            if "github.com" in hp:
                try:
                    path = urllib.parse.urlparse("https://" + hp).path
                    org = path.strip("/").split("/")[0].lower()
                    if org and (org in kd or kd in org):
                        return True
                except Exception:
                    pass

        return False

    def apply(
        self,
        candidate: ResolutionCandidate,
        query: str,
    ) -> ResolutionCandidate:
        """
        Verify the candidate against the catalog's known_domains for this query,
        attach the result to candidate.verified, and adjust trust_score.
        """
        known = CATALOG.known_domains(query)
        result = self.verify(candidate, known)
        candidate.verified = result

        # Adjust trust_score
        if result is True:
            candidate.trust_score = 100.0
        elif result is False:
            candidate.trust_score = 10.0   # big penalty for domain mismatch
        else:
            candidate.trust_score = 50.0   # neutral unknown

        # Recompute total_score with new trust_score
        candidate.total_score = round(
            0.70 * candidate.fuzzy_score + 0.30 * candidate.trust_score, 1
        )
        return candidate


VERIFIER = PublisherVerifier()


# ---------------------------------------------------------------------------
# ProvenanceStore
# ---------------------------------------------------------------------------

class ProvenanceStore:
    """SQLite-backed cache of verified package resolutions."""

    _DDL = """
    CREATE TABLE IF NOT EXISTS provenance (
        query_name      TEXT NOT NULL,
        variant         TEXT NOT NULL DEFAULT '',
        resolved_id     TEXT NOT NULL,
        manager         TEXT NOT NULL,
        source          TEXT NOT NULL DEFAULT '',
        publisher       TEXT NOT NULL DEFAULT '',
        homepage        TEXT NOT NULL DEFAULT '',
        verified        INTEGER,          -- 1=true, 0=false, NULL=unknown
        verified_at     TEXT NOT NULL DEFAULT '',
        install_success INTEGER NOT NULL DEFAULT 0,
        last_used       TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (query_name, variant)
    );
    """

    def __init__(self, db_path: Path = _CACHE_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(self._DDL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def lookup(self, query_name: str, variant: str = "") -> Optional[ProvenanceRecord]:
        """Return cached record only if install_success=True, else None."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM provenance WHERE query_name=? AND variant=?",
                    (query_name.lower().strip(), variant.lower().strip()),
                ).fetchone()
        if not row:
            return None
        if not row["install_success"]:
            return None   # previous install failed — force live re-resolution
        return ProvenanceRecord(
            query_name=row["query_name"],
            variant=row["variant"],
            resolved_id=row["resolved_id"],
            manager=row["manager"],
            source=row["source"],
            publisher=row["publisher"],
            homepage=row["homepage"],
            verified={1: True, 0: False}.get(row["verified"]),
            verified_at=row["verified_at"],
            install_success=bool(row["install_success"]),
            last_used=row["last_used"],
        )

    def record(
        self,
        query: str,
        candidate: ResolutionCandidate,
        install_success: bool,
        variant: str = "",
    ) -> None:
        """Upsert a provenance record after an install attempt."""
        now = datetime.now(timezone.utc).isoformat()
        verified_int = {True: 1, False: 0, None: None}[candidate.verified]
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO provenance
                        (query_name, variant, resolved_id, manager, source,
                         publisher, homepage, verified, verified_at,
                         install_success, last_used)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(query_name, variant) DO UPDATE SET
                        resolved_id=excluded.resolved_id,
                        manager=excluded.manager,
                        source=excluded.source,
                        publisher=excluded.publisher,
                        homepage=excluded.homepage,
                        verified=excluded.verified,
                        verified_at=excluded.verified_at,
                        install_success=excluded.install_success,
                        last_used=excluded.last_used
                """, (
                    query.lower().strip(),
                    variant.lower().strip(),
                    candidate.pkg_id,
                    candidate.manager,
                    candidate.source,
                    candidate.publisher,
                    candidate.homepage,
                    verified_int,
                    now,
                    1 if install_success else 0,
                    now,
                ))

    def invalidate(self, query_name: str, variant: str = "") -> None:
        """Mark a record's install_success=0 to force re-resolution next time."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE provenance SET install_success=0 WHERE query_name=? AND variant=?",
                    (query_name.lower().strip(), variant.lower().strip()),
                )

    def get_record(self, query_name: str, variant: str = "") -> Optional[ProvenanceRecord]:
        """Return any record regardless of install_success (for UI display)."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM provenance WHERE query_name=? AND variant=?",
                    (query_name.lower().strip(), variant.lower().strip()),
                ).fetchone()
        if not row:
            return None
        return ProvenanceRecord(
            query_name=row["query_name"],
            variant=row["variant"],
            resolved_id=row["resolved_id"],
            manager=row["manager"],
            source=row["source"],
            publisher=row["publisher"],
            homepage=row["homepage"],
            verified={1: True, 0: False}.get(row["verified"]),
            verified_at=row["verified_at"],
            install_success=bool(row["install_success"]),
            last_used=row["last_used"],
        )

    def delete(self, query_name: str, variant: str = "") -> None:
        """Hard-delete a provenance record."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM provenance WHERE query_name=? AND variant=?",
                    (query_name.lower().strip(), variant.lower().strip()),
                )


PROVENANCE = ProvenanceStore()


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

class BaseAdapter:
    """Abstract base for all package manager adapters."""
    name: str = "base"

    def available(self) -> bool:
        return bool(shutil.which(self.name))

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        raise NotImplementedError

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        raise NotImplementedError


class WingetAdapter(BaseAdapter):
    """Delegates to pkg_discovery._winget_search / _winget_show."""
    name = "winget"

    def available(self) -> bool:
        return bool(shutil.which("winget"))

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _winget_search, _winget_show
        results: list[ResolutionCandidate] = []

        # Pass 1: default source
        raw = _winget_search(query)
        for r in raw:
            # Fetch homepage via winget show for top candidates only (to save time)
            homepage = ""
            publisher = r.publisher
            c = ResolutionCandidate(
                pkg_id=r.id,
                name=r.name,
                version=r.version,
                manager="winget",
                source=r.source or "winget",
                publisher=publisher,
                homepage=homepage,
                description=r.description,
                trust_score=50.0,
            )
            # Tag variant from catalog
            c.variant_tags = self._infer_variant_tags(query, r.id)
            results.append(c)

        # Pass 2: msstore fallback if no main-source results
        if not results:
            raw2 = _winget_search(query, source="msstore")
            for r in raw2:
                c = ResolutionCandidate(
                    pkg_id=r.id,
                    name=r.name,
                    version=r.version,
                    manager="winget",
                    source="msstore",
                    publisher=r.publisher,
                    homepage="",
                    description=r.description,
                    trust_score=50.0,
                )
                c.variant_tags = self._infer_variant_tags(query, r.id)
                results.append(c)

        return results

    def get_details(self, pkg_id: str, source: str = "winget") -> Optional[ResolutionCandidate]:
        from pkg_discovery import _winget_show
        det = _winget_show(pkg_id, source=source if source == "msstore" else None)
        if not det:
            return None
        return ResolutionCandidate(
            pkg_id=det.id,
            name=det.name,
            version=det.version,
            manager="winget",
            source=source,
            publisher=det.publisher,
            homepage=det.url,
            description=det.description,
            trust_score=50.0,
        )

    @staticmethod
    def _infer_variant_tags(query: str, pkg_id: str) -> list[str]:
        """Use catalog variant config to tag a package ID with variant labels."""
        tool = CATALOG.find_tool(query)
        if not tool:
            return []
        tags = []
        for variant_name, vcfg in tool.get("variants", {}).items():
            id_contains = vcfg.get("id_contains", [])
            if any(frag.lower() in pkg_id.lower() for frag in id_contains):
                tags.append(variant_name)
        return tags


class MsStoreAdapter(BaseAdapter):
    """Winget pointing at msstore source only."""
    name = "msstore"

    def available(self) -> bool:
        return bool(shutil.which("winget"))

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _winget_search
        raw = _winget_search(query, source="msstore")
        return [
            ResolutionCandidate(
                pkg_id=r.id, name=r.name, version=r.version,
                manager="winget", source="msstore",
                publisher=r.publisher, homepage="",
                description=r.description, trust_score=50.0,
                variant_tags=WingetAdapter._infer_variant_tags(query, r.id),
            )
            for r in raw
        ]

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        return WingetAdapter().get_details(pkg_id, source="msstore")


class ChocoAdapter(BaseAdapter):
    """Chocolatey search adapter."""
    name = "choco"

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _run
        out, code = _run(["choco", "search", query, "--limit-output", "--no-progress"])
        if code != 0 or not out.strip():
            return []
        results = []
        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) < 2:
                continue
            pkg_id, version = parts[0].strip(), parts[1].strip()
            results.append(ResolutionCandidate(
                pkg_id=pkg_id,
                name=pkg_id,
                version=version,
                manager="choco",
                source="choco",
                trust_score=50.0,
            ))
        return results

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _run
        out, code = _run(["choco", "info", pkg_id, "--limit-output"])
        if code != 0:
            return None
        title = pkg_id
        desc = ""
        homepage = ""
        for line in out.splitlines():
            l = line.strip()
            if l.lower().startswith("title:"):
                title = l.split(":", 1)[1].strip()
            elif l.lower().startswith("description:"):
                desc = l.split(":", 1)[1].strip()
            elif l.lower().startswith("projecturl:"):
                homepage = l.split(":", 1)[1].strip()
        return ResolutionCandidate(
            pkg_id=pkg_id, name=title, version="",
            manager="choco", source="choco",
            homepage=homepage, description=desc,
            trust_score=50.0,
        )


class ScoopAdapter(BaseAdapter):
    """Scoop search adapter."""
    name = "scoop"

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _run
        out, code = _run(["scoop", "search", query])
        if code != 0 or not out.strip():
            return []
        results = []
        # Scoop search output: "  name (bucket) (version)"
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("Results") or line.startswith("---"):
                continue
            m = re.match(r"^(\S+)\s+\(([^)]+)\)\s+\(([^)]+)\)", line)
            if m:
                pkg_id, bucket, version = m.group(1), m.group(2), m.group(3)
            else:
                parts = line.split()
                if not parts:
                    continue
                pkg_id, version, bucket = parts[0], (parts[1] if len(parts) > 1 else ""), ""
            results.append(ResolutionCandidate(
                pkg_id=pkg_id,
                name=pkg_id,
                version=version,
                manager="scoop",
                source=f"scoop/{bucket}" if bucket else "scoop",
                trust_score=50.0,
            ))
        return results

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _run
        out, code = _run(["scoop", "info", pkg_id])
        if code != 0:
            return None
        homepage = ""
        desc = ""
        version = ""
        for line in out.splitlines():
            l = line.strip()
            if l.lower().startswith("homepage:"):
                homepage = l.split(":", 1)[1].strip()
            elif l.lower().startswith("description:"):
                desc = l.split(":", 1)[1].strip()
            elif l.lower().startswith("version:"):
                version = l.split(":", 1)[1].strip()
        return ResolutionCandidate(
            pkg_id=pkg_id, name=pkg_id, version=version,
            manager="scoop", source="scoop",
            homepage=homepage, description=desc,
            trust_score=50.0,
        )


class AptAdapter(BaseAdapter):
    """apt-cache / apt search adapter (Linux)."""
    name = "apt"

    def available(self) -> bool:
        return bool(shutil.which("apt-cache") or shutil.which("apt"))

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _apt_search
        raw = _apt_search(query)
        return [
            ResolutionCandidate(
                pkg_id=r.id, name=r.name, version=r.version,
                manager="apt", source="apt",
                description=r.description, trust_score=60.0,
            )
            for r in raw
        ]

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _apt_show
        det = _apt_show(pkg_id)
        if not det:
            return None
        return ResolutionCandidate(
            pkg_id=det.id, name=det.name, version=det.version,
            manager="apt", source="apt",
            publisher=det.publisher, homepage=det.url,
            description=det.description, trust_score=60.0,
        )


class BrewAdapter(BaseAdapter):
    """Homebrew search adapter (macOS / Linux)."""
    name = "brew"

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _brew_search
        raw = _brew_search(query)
        return [
            ResolutionCandidate(
                pkg_id=r.id, name=r.name, version=r.version,
                manager="brew", source="brew",
                description=r.description, trust_score=60.0,
            )
            for r in raw
        ]

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _brew_info
        det = _brew_info(pkg_id)
        if not det:
            return None
        return ResolutionCandidate(
            pkg_id=det.id, name=det.name, version=det.version,
            manager="brew", source="brew",
            publisher=det.publisher, homepage=det.url,
            description=det.description, trust_score=60.0,
        )


class NpmAdapter(BaseAdapter):
    """npm registry search adapter (cross-platform)."""
    name = "npm"

    def available(self) -> bool:
        return True   # HTTP-only, always available

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _npm_search
        raw = _npm_search(query)
        return [
            ResolutionCandidate(
                pkg_id=r.id, name=r.name, version=r.version,
                manager="npm", source="npm",
                publisher=r.publisher, homepage="",
                description=r.description, trust_score=50.0,
            )
            for r in raw
        ]

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _npm_details
        det = _npm_details(pkg_id)
        if not det:
            return None
        return ResolutionCandidate(
            pkg_id=det.id, name=det.name, version=det.version,
            manager="npm", source="npm",
            publisher=det.publisher, homepage=det.url,
            description=det.description, trust_score=50.0,
        )


class PipAdapter(BaseAdapter):
    """PyPI search adapter (cross-platform)."""
    name = "pip"

    def available(self) -> bool:
        return True   # HTTP-only, always available

    def search(self, query: str, variant_hint: str = "") -> list[ResolutionCandidate]:
        from pkg_discovery import _pypi_search
        raw = _pypi_search(query)
        return [
            ResolutionCandidate(
                pkg_id=r.id, name=r.name, version=r.version,
                manager="pip", source="pypi",
                publisher=r.publisher, homepage="",
                description=r.description, trust_score=50.0,
            )
            for r in raw
        ]

    def get_details(self, pkg_id: str) -> Optional[ResolutionCandidate]:
        from pkg_discovery import _pypi_details
        det = _pypi_details(pkg_id)
        if not det:
            return None
        return ResolutionCandidate(
            pkg_id=det.id, name=det.name, version=det.version,
            manager="pip", source="pypi",
            publisher=det.publisher, homepage=det.url,
            description=det.description, trust_score=50.0,
        )


# ---------------------------------------------------------------------------
# AdapterRegistry
# ---------------------------------------------------------------------------

_ALL_ADAPTERS: dict[str, BaseAdapter] = {
    "winget":  WingetAdapter(),
    "msstore": MsStoreAdapter(),
    "choco":   ChocoAdapter(),
    "scoop":   ScoopAdapter(),
    "apt":     AptAdapter(),
    "brew":    BrewAdapter(),
    "npm":     NpmAdapter(),
    "pip":     PipAdapter(),
}


class AdapterRegistry:
    """Returns available adapters in the correct OS priority order."""

    def get_adapters(self, os_override: str = "") -> list[BaseAdapter]:
        import platform
        os_name = os_override or platform.system()
        priority = CATALOG.adapter_priority
        order = (
            priority.get("Windows", ["winget", "msstore", "choco", "scoop", "npm", "pip"])
            if os_name == "Windows" else
            priority.get("Darwin",  ["brew", "npm", "pip"])
            if os_name == "Darwin" else
            priority.get("Linux",   ["apt", "snap", "flatpak", "npm", "pip"])
        )
        adapters = []
        for name in order:
            adapter = _ALL_ADAPTERS.get(name)
            if adapter and adapter.available():
                adapters.append(adapter)
        return adapters

    def search_all(
        self,
        query: str,
        variant_hint: str = "",
        stop_on_confident: bool = True,
    ) -> list[ResolutionCandidate]:
        """
        Run adapters in priority order.
        Stops as soon as one adapter produces a confident result
        (if stop_on_confident=True).
        """
        all_candidates: list[ResolutionCandidate] = []
        for adapter in self.get_adapters():
            try:
                batch = adapter.search(query, variant_hint)
            except Exception as e:
                print(f"[AdapterRegistry] {adapter.name} search error: {e}")
                continue

            # Score this batch inline
            for c in batch:
                SCORER.score_candidate(query, c, variant_hint)

            all_candidates.extend(batch)

            if stop_on_confident and batch:
                ranked = sorted(batch, key=lambda c: c.total_score, reverse=True)
                if ranked and SCORER.is_confident(ranked[0]):
                    break   # Good enough — don't bother with lower-priority adapters

        # Final global sort
        all_candidates.sort(key=lambda c: c.total_score, reverse=True)
        # De-duplicate by pkg_id (case-insensitive)
        seen: dict[str, ResolutionCandidate] = {}
        for c in all_candidates:
            key = c.pkg_id.lower()
            if key not in seen or c.total_score > seen[key].total_score:
                seen[key] = c
        return sorted(seen.values(), key=lambda c: c.total_score, reverse=True)[:15]


REGISTRY = AdapterRegistry()


# ---------------------------------------------------------------------------
# ResolutionPipeline
# ---------------------------------------------------------------------------

class ResolutionPipeline:
    """
    Orchestrates the full resolution flow:
      cache lookup → multi-source search → rank → gate → verify → return
    """

    def resolve(
        self,
        query: str,
        variant_hint: str = "",
        force_refresh: bool = False,
    ) -> ResolutionResult:
        q = query.strip()
        v = variant_hint.strip()

        # If no explicit variant, use catalog default
        if not v:
            v = CATALOG.default_variant(q)

        # 1. Provenance cache lookup
        if not force_refresh:
            cached = PROVENANCE.lookup(q, v)
            if cached:
                install_cmd = self._build_cmd(cached.resolved_id, cached.manager)
                cand = ResolutionCandidate(
                    pkg_id=cached.resolved_id,
                    name=cached.resolved_id,
                    version="",
                    manager=cached.manager,
                    source=cached.source,
                    publisher=cached.publisher,
                    homepage=cached.homepage,
                    verified=cached.verified,
                    total_score=100.0,
                    fuzzy_score=100.0,
                    trust_score=100.0,
                )
                return ResolutionResult(
                    status="auto_selected",
                    selected=cand,
                    candidates=[cand],
                    confidence=100.0,
                    from_cache=True,
                    source_used=cached.manager,
                    install_cmd=install_cmd,
                )

        # 2. Multi-source search + ranking
        candidates = REGISTRY.search_all(q, v, stop_on_confident=True)

        if not candidates:
            return ResolutionResult(
                status="not_found",
                selected=None,
                candidates=[],
                confidence=0.0,
                from_cache=False,
                source_used="",
                install_cmd="",
            )

        # 3. Enrich top-N candidates with details + publisher verification
        # Only fetch full details for the top few to avoid timeouts
        enriched = self._enrich_top(q, candidates, variant_hint=v, top_n=5)

        # 4. Re-sort after enrichment (trust_score may have changed)
        enriched.sort(key=lambda c: c.total_score, reverse=True)
        top = enriched[0]

        # 5. Confidence gate
        if SCORER.is_confident(top):
            install_cmd = self._build_cmd(top.pkg_id, top.manager, top.source)
            top.variant_tags = top.variant_tags or ([v] if v else [])
            return ResolutionResult(
                status="auto_selected",
                selected=top,
                candidates=enriched,
                confidence=top.total_score,
                from_cache=False,
                source_used=top.manager,
                install_cmd=install_cmd,
            )
        else:
            return ResolutionResult(
                status="needs_disambiguation",
                selected=None,
                candidates=enriched,
                confidence=top.total_score,
                from_cache=False,
                source_used="",
                install_cmd="",
            )

    def _enrich_top(
        self,
        query: str,
        candidates: list[ResolutionCandidate],
        variant_hint: str = "",
        top_n: int = 5,
    ) -> list[ResolutionCandidate]:
        """
        For the top-N candidates, fetch full details (homepage/publisher) from
        their respective adapters, then run PublisherVerifier.
        Remaining candidates pass through with current data.
        """
        enriched_ids: set[str] = set()
        result: list[ResolutionCandidate] = []

        for i, c in enumerate(candidates):
            if i < top_n and c.pkg_id.lower() not in enriched_ids:
                adapter = _ALL_ADAPTERS.get(c.manager)
                if adapter:
                    try:
                        details = adapter.get_details(c.pkg_id)
                        if details:
                            # Merge: keep existing scores, update provenance fields
                            c.publisher = details.publisher or c.publisher
                            c.homepage  = details.homepage  or c.homepage
                            c.description = details.description or c.description
                    except Exception:
                        pass
                # Apply publisher verification
                VERIFIER.apply(c, query)
                # Re-score with updated trust_score
                SCORER.score_candidate(query, c, variant_hint)
                enriched_ids.add(c.pkg_id.lower())
            result.append(c)

        return result

    @staticmethod
    def _build_cmd(pkg_id: str, manager: str, source: str = "") -> str:
        """Build install command — delegates to pkg_discovery template engine."""
        from pkg_discovery import build_install_command
        effective_manager = "msstore" if source == "msstore" else manager
        return build_install_command(pkg_id, effective_manager)

    def record_install(
        self,
        query: str,
        candidate: ResolutionCandidate,
        success: bool,
        variant: str = "",
    ) -> None:
        """Called after install stream completes. Updates provenance cache."""
        PROVENANCE.record(query, candidate, success, variant)


# Singleton pipeline
PIPELINE = ResolutionPipeline()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(
    query: str,
    variant_hint: str = "",
    force_refresh: bool = False,
) -> ResolutionResult:
    """
    Full resolution pipeline.
    Returns ResolutionResult with status in:
      "auto_selected"        — confident pick, install_cmd ready
      "needs_disambiguation" — candidates returned, caller must ask user
      "not_found"            — nothing matched
    """
    return PIPELINE.resolve(query, variant_hint, force_refresh)


def record_install(
    query: str,
    pkg_id: str,
    manager: str,
    source: str = "",
    publisher: str = "",
    homepage: str = "",
    verified: Optional[bool] = None,
    variant: str = "",
    success: bool = True,
) -> None:
    """Persist install outcome to the provenance cache."""
    c = ResolutionCandidate(
        pkg_id=pkg_id,
        name=pkg_id,
        version="",
        manager=manager,
        source=source or manager,
        publisher=publisher,
        homepage=homepage,
        verified=verified,
    )
    PIPELINE.record_install(query, c, success, variant)


def get_provenance(query: str, variant: str = "") -> Optional[ProvenanceRecord]:
    """Return the provenance record for a query (any install_success value)."""
    return PROVENANCE.get_record(query, variant)


def delete_provenance(query: str, variant: str = "") -> None:
    """Hard-delete a provenance record to force fresh resolution next time."""
    PROVENANCE.delete(query, variant)
