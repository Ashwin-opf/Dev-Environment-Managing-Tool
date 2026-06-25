# Design Document: SHCE Package Verification and Self-Healing Engine

## Overview

The SHCE Package Verification subsystem adds a safety gate to PC Doctor's Self-Healing Core Engine
that prevents the generation of invalid `apt install` (or equivalent) commands for unrecognised
packages. Before any installation command is produced, a five-source verification pipeline runs
against the requested package name and assigns a confidence score (0–100). Only requests that clear
a score of 70 or above result in a generated command; everything below causes a structured refusal.
A parallel self-healing loop captures run-time "unable to locate package" errors and uses the same
pipeline to produce corrected alternatives, which are queued for user approval exactly as existing
SHCE repairs are.

Key integration points:
- **`shce_engine.py`** — new `PackageVerifier` class lives alongside `CommandMutationEngine`;
  `SHCEOrchestrator` gains an `intent_detect_and_verify` method that routes installation requests
  through `PackageVerifier` before delegating to `CommandMutationEngine`.
- **`knowledge.db`** — a new `package_knowledge` table (the Package Knowledge Store, PKS) is
  added beside the existing `adaptive_knowledge_base` and `error_intelligence` tables.
- **`routes_shce.py`** — three new FastAPI endpoints are registered: `POST /api/shce/verify-package`,
  `GET /api/shce/package-knowledge`, and `POST /api/shce/package-knowledge`.
- **`vector_search.py`** — the existing `VectorSearch` class is reused for Local RAG queries;
  a thin adapter method is added to search by package name rather than error description.

---

## Architecture

### High-Level Flow

```
User query / repair_engine error
          │
          ▼
  ┌─────────────────────┐
  │   IntentDetector    │  ← extract package name, normalise to lowercase
  └─────────┬───────────┘
            │  installation_request?
            ▼ yes
  ┌─────────────────────────────────────────────────────────────┐
  │                   PackageVerifier                            │
  │  Pipeline (in order, stop at first VERIFIED result):        │
  │  1. apt-cache show   → confidence 100 (VERIFIED)           │
  │  2. apt-cache search → confidence 80  (VERIFIED)           │
  │  3. Package Knowledge Store (PKS) → confidence 80 (VERIFIED)│
  │  4. Local RAG (VectorSearch)      → confidence 60 (VERIFIED)│
  │  5. Web RAG (DuckDuckGo, online-only) → confidence 60      │
  │  Fuzzy fallback → confidence 40                             │
  │  None found → confidence 0 (UNVERIFIED)                    │
  └────────────┬────────────────────────────────────────────────┘
               │ VerificationResult
               ▼
  ┌─────────────────────────┐
  │  CommandGenerationGate  │
  │  confidence >= 70 ?     │
  └────┬────────────────────┘
       │ yes                 │ no
       ▼                     ▼
  generate command      return refusal + suggestion (if fuzzy)
       │
       ▼
  existing SHCE queue / API response
```

### Self-Healing Loop Integration

```
Terminal error "unable to locate package X"
          │
          ▼
  SHCEOrchestrator.handle_failure()  ← existing entry point
          │
          │  error_type == "installation_failure"?
          ▼ yes
  Self_Healing_Loop (inside PackageVerifier)
    1. Query PKS for alternative install methods
    2. Query Local RAG
    3. Query Web RAG if online
    4. Generate corrected candidates
    5. Rank by confidence, enqueue best via existing error_intelligence_db.enqueue()
```

---

## Components and Interfaces

### 1. IntentDetector

Responsible for classifying a free-form query as an installation request and extracting the
package name. Lives inside `shce_engine.py` as a static-method class.

```python
class IntentDetector:
    TRIGGER_WORDS = frozenset(["install", "get", "add", "setup"])

    @staticmethod
    def classify(query: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_installation_request, package_name_or_None).
        package_name is normalised to lowercase.
        """

    @staticmethod
    def _extract_package(query: str) -> Optional[str]:
        """Regex extraction after a trigger word; returns lowercase token."""
```

### 2. PackageVerifier

The core verification engine. Lives in `shce_engine.py` alongside existing classes.

```python
@dataclass
class VerificationResult:
    package: str
    verified: bool
    confidence: int          # 0–100
    source: str              # "apt-cache" | "package_knowledge_store" | "local_rag"
                             # "web_rag" | "fuzzy_match" | "none"
    command: Optional[str]   # present when confidence >= 70
    reason: Optional[str]    # present when confidence < 70
    suggestion: Optional[str]  # closest fuzzy match name (when 40 <= confidence < 70)

class PackageVerifier:
    def __init__(self, db_path: str = DB_PATH): ...

    def verify(self, package_name: str, online: bool) -> VerificationResult:
        """Run the full 5-source pipeline and return a VerificationResult."""

    def heal_installation_failure(
        self, failed_package: str, online: bool
    ) -> List[Dict[str, Any]]:
        """Self-healing: return ranked corrected candidates for a failed install."""

    # ── Private pipeline sources ──────────────────────────────────────────
    def _apt_cache_show(self, pkg: str) -> Optional[int]:  ...
    def _apt_cache_search(self, pkg: str) -> Optional[int]: ...
    def _query_pks(self, pkg: str) -> Optional[int]: ...
    def _query_local_rag(self, pkg: str) -> Optional[int]: ...
    def _query_web_rag(self, pkg: str) -> Optional[int]: ...
    def _fuzzy_match(self, pkg: str) -> Tuple[int, Optional[str]]: ...
    def _build_command(self, pkg: str, install_method: str) -> str: ...
```

### 3. PackageKnowledgeStore (PKS)

A thin SQLite DAO class that wraps the `package_knowledge` table in `knowledge.db`.
Lives in `shce_engine.py`.

```python
class PackageKnowledgeStore:
    def __init__(self, db_path: str = DB_PATH): ...
    def ensure_table(self) -> None: ...
    def seed(self) -> None: ...  # idempotent seed of 20+ packages
    def get(self, package_name: str) -> Optional[Dict]: ...
    def upsert(self, package_name: str, **fields) -> None: ...
    def list_all(self, limit: int = 100, offset: int = 0) -> List[Dict]: ...
    def count(self) -> int: ...
```

### 4. SHCEOrchestrator (extended)

`handle_failure` gains an early branch for `installation_failure` errors:

```python
def handle_failure(self, command, error, source, auto_queue) -> Dict:
    # NEW: detect installation_failure
    if re.search(r"unable to locate package\s+(\S+)", error, re.I):
        return self._handle_installation_failure(command, error, source, auto_queue)
    # existing path unchanged …

def _handle_installation_failure(self, command, error, source, auto_queue) -> Dict:
    ...
```

### 5. New API Routes (routes_shce.py)

Three new endpoints are appended to `routes_shce.py`:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/shce/verify-package` | Run full verification pipeline for a package name |
| `GET`  | `/api/shce/package-knowledge` | Paginated PKS listing |
| `POST` | `/api/shce/package-knowledge` | Manually add/update a PKS record |

Pydantic request models:

```python
class VerifyPackageRequest(BaseModel):
    package_name: str

class PackageKnowledgeRecord(BaseModel):
    package_name: str
    install_method: str = "apt"
    repository_required: Optional[str] = None
    verification_status: str = "verified"
    fallback_methods: Optional[str] = None
```

---

## Data Models

### SQLite Table: `package_knowledge`

Added to `knowledge.db` via `PackageKnowledgeStore.ensure_table()`, which is called from
`ErrorIntelligenceDB._ensure_tables()` during startup (so no changes to `main.py` are needed).

```sql
CREATE TABLE IF NOT EXISTS package_knowledge (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name        TEXT    NOT NULL UNIQUE,        -- normalised lowercase
    install_method      TEXT    NOT NULL DEFAULT 'apt', -- apt | snap | flatpak | external_repo
    repository_required TEXT,                           -- e.g. ppa:foo/bar (nullable)
    verification_status TEXT    NOT NULL DEFAULT 'unknown', -- verified | unknown
    last_verified       TEXT,                           -- ISO-8601 UTC timestamp
    fallback_methods    TEXT                            -- JSON array of strings
);
```

Seed records (20 guaranteed at startup):
`git`, `docker.io`, `nodejs`, `python3`, `curl`, `wget`, `vim`, `htop`, `tmux`,
`build-essential`, `net-tools`, `ffmpeg`, `vlc`, `gimp`, `libreoffice`, `openssh-server`,
`ufw`, `fail2ban`, `nginx`, `postgresql`

All seeds have `install_method = 'apt'`, `verification_status = 'verified'`.

### VerificationResult (in-memory / serialised)

```python
@dataclass
class VerificationResult:
    package:             str
    verified:            bool
    confidence:          int             # 0–100
    source:              str             # enum string (see above)
    command:             Optional[str]   # present when confidence >= 70
    reason:              Optional[str]   # present when confidence < 70
    suggestion:          Optional[str]   # present when 40 <= confidence < 70
    verification_source: str             # same as source, explicit field for API contract

    def to_dict(self) -> Dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationResult": ...
```

### API Response Shapes

**Verified (confidence ≥ 70):**
```json
{
  "package": "git",
  "verified": true,
  "confidence": 100,
  "source": "apt-cache",
  "verification_source": "apt-cache",
  "command": "sudo apt install -y git"
}
```

**Unverified (confidence < 70):**
```json
{
  "package": "binance",
  "verified": false,
  "confidence": 0,
  "source": "none",
  "verification_source": "none",
  "reason": "Package could not be verified locally. No installation command generated.",
  "command": null
}
```

**Fuzzy match (40 ≤ confidence < 70):**
```json
{
  "package": "ngnx",
  "verified": false,
  "confidence": 40,
  "source": "fuzzy_match",
  "verification_source": "fuzzy_match",
  "reason": "Package could not be verified locally. No installation command generated.",
  "command": null,
  "suggestion": "nginx"
}
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The following properties were derived from the acceptance criteria prework. Several criteria in
Requirements 6 (Confidence Scoring Model) are structurally identical to criteria in Requirement 2
and were consolidated to avoid redundancy. Criteria that describe infrastructure setup (smoke),
specific one-off examples, or non-computable UI goals are excluded from this section.

---

### Property 1: Intent detection is trigger-word sensitive

*For any* string that contains one of the trigger words ("install", "get", "add", "setup") followed
by at least one non-whitespace token, `IntentDetector.classify()` SHALL return
`is_installation_request = True`; for any string that contains none of those trigger words,
it SHALL return `False`.

**Validates: Requirements 1.1**

---

### Property 2: Extracted package name is always lowercase

*For any* query string that `IntentDetector` classifies as an installation request, the extracted
`package_name` SHALL be the lowercase form of the token that immediately follows the trigger word,
regardless of the casing used in the original query.

**Validates: Requirements 1.2, 1.4**

---

### Property 3: Verification result always contains required fields

*For any* package name string passed to `PackageVerifier.verify()`, the returned
`VerificationResult` SHALL contain all of the following fields with the correct types:
`package` (str), `verified` (bool), `confidence` (int, 0–100), `source` (str),
`verification_source` (str), and at least one of `command` (str) or `reason` (str).

**Validates: Requirements 2.10, 6.8, 7.4**

---

### Property 4: Command generation gate — generate when confidence ≥ 70

*For any* verification result where `confidence >= 70`, the `command` field SHALL be a non-empty
string and `verified` SHALL be `True`.

**Validates: Requirements 3.1, 7.1**

---

### Property 5: Command generation gate — refuse when confidence < 70

*For any* verification result where `confidence < 70`, the `command` field SHALL be `None` (null)
and `verified` SHALL be `False`.

**Validates: Requirements 3.2, 6.7, 7.2**

---

### Property 6: PKS install method is used when available

*For any* package that exists in the PKS with a non-null `install_method`, the command produced
by `PackageVerifier._build_command()` SHALL use that `install_method` (e.g. `snap install` for
`install_method = 'snap'`) rather than defaulting to `apt install`.

**Validates: Requirements 3.5**

---

### Property 7: Verified packages are written to PKS

*For any* package name that passes `apt-cache show` and is not already in the PKS,
after `PackageVerifier.verify()` returns, the PKS SHALL contain a record for that package
with `verification_status = 'verified'` and a non-null `last_verified` timestamp.

**Validates: Requirements 4.4**

---

### Property 8: Unknown packages are written to PKS

*For any* package name that fails all five verification sources, after `PackageVerifier.verify()`
returns, the PKS SHALL contain a record for that package with `verification_status = 'unknown'`.

**Validates: Requirements 4.5**

---

### Property 9: PKS lookup is case-insensitive

*For any* package name stored in the PKS, querying the PKS with any casing variant of that name
(uppercase, mixed-case, or lowercase) SHALL return the same record as a lowercase query.

**Validates: Requirements 4.6**

---

### Property 10: Offline mode never queries Web RAG

*For any* package name, when `PackageVerifier.verify()` is called with `online = False`, the
`_query_web_rag` source SHALL never be invoked and the `verification_source` in the returned
result SHALL NOT be `"web_rag"`.

**Validates: Requirements 2.7, 8.1, 8.2**

---

### Property 11: Installation failure error classification

*For any* error string that matches the pattern `"unable to locate package <name>"`,
`SHCEOrchestrator.handle_failure()` SHALL classify the error as `installation_failure` and
extract the package name equal to `<name>`.

**Validates: Requirements 5.1**

---

### Property 12: Self-healing candidates are ranked by confidence

*For any* non-empty list of corrected candidates returned by
`PackageVerifier.heal_installation_failure()`, the candidates SHALL be ordered by descending
confidence score (highest confidence first).

**Validates: Requirements 5.3**

---

### Property 13: Highest-ranked candidate is enqueued

*For any* non-empty ranked candidate list produced by the self-healing loop, the item inserted
into `shce_queue` via `error_intelligence_db.enqueue()` SHALL be the candidate with the
highest confidence score.

**Validates: Requirements 5.5**

---

### Property 14: Serialisation round-trip

*For any* valid `VerificationResult` object, serialising it to a JSON-compatible dictionary via
`to_dict()` and then deserialising it back via `from_dict()` SHALL produce an object that is
equal to the original (`from_dict(result.to_dict()) == result`).

**Validates: Requirements 7.5**

---

## Error Handling

### Subprocess failures (apt-cache)

`apt-cache show` and `apt-cache search` are executed via `subprocess.run` with a 5-second timeout.
Any non-zero exit code, `FileNotFoundError` (apt not installed), or `subprocess.TimeoutExpired`
are caught silently; the pipeline moves to the next source. This is consistent with the pattern
used by `CommandMutationEngine._from_doc_db`.

### Network timeout (Web RAG)

`_query_web_rag` uses `urllib.request.urlopen` with `timeout=WEB_RAG_TIMEOUT` (4 s, same constant
already defined in `shce_engine.py`). Any `URLError`, `socket.timeout`, or `json.JSONDecodeError`
cause the source to return `None` and the pipeline to continue. The source is never called when
`online = False`.

### PKS database errors

All `sqlite3` calls inside `PackageKnowledgeStore` are wrapped in try/except. A failure to read
from PKS is treated as a cache miss (pipeline continues); a failure to write is logged via the
module-level `logger` but does not raise — verification results are still returned.

### Empty / invalid package name

`PackageVerifier.verify()` raises `ValueError` for empty or whitespace-only package names.
The API layer converts this to HTTP 400 via FastAPI's `HTTPException`.

### Missing apt-cache (non-Debian systems)

If `shutil.which("apt-cache")` returns `None`, sources 1 and 2 are skipped entirely and the
pipeline starts at the PKS. This ensures correct behaviour on Fedora, Arch, and macOS hosts
where `apt-cache` is unavailable.

### Offline + external_repo

When `online = False` and the PKS record has `install_method = 'external_repo'`, the verifier
sets `confidence = 0`, `verified = False`, and prefixes the `reason` field with:
*"Package requires an external repository that cannot be added while offline."*

### Self-healing — no candidates found

If `heal_installation_failure` exhausts all sources with zero candidates, it returns an empty
list. `SHCEOrchestrator._handle_installation_failure` detects the empty list, writes a
`verification_status = 'unknown'` PKS record, and returns a structured failure dict with
`ok = False` and the appropriate message from Requirement 5.7.

---

## Testing Strategy

### Unit Tests

Unit tests are written with pytest and cover:

- `IntentDetector.classify` — positive and negative classification cases, case-insensitivity.
- `IntentDetector._extract_package` — various query shapes including multi-word package names.
- `PackageVerifier._build_command` — install method selection from PKS records.
- `PackageVerifier.verify` with all sources mocked — scoring table, field completeness,
  offline guard, empty name validation.
- `PackageKnowledgeStore` — ensure_table idempotency, seed idempotency, get/upsert round-trips,
  case-insensitive lookup.
- `VerificationResult.to_dict` / `from_dict` — round-trip equality.
- Confidence score thresholds (20, 40, 60, 80, 100) as concrete example-based tests.
- API route handlers — HTTP 400 on empty name, 200 with correct schema on valid requests
  (using FastAPI `TestClient`).

### Property-Based Tests

Property-based tests use [**Hypothesis**](https://hypothesis.readthedocs.io/) (the standard PBT
library for Python). Each test is configured with `@settings(max_examples=100)`.

Each test is tagged with a comment referencing its design property:
`# Feature: shce-package-verification, Property N: <property_text>`

**Property 1 — Intent detection:**
Generate strings with and without trigger words; assert classification is consistent with
trigger-word presence.

**Property 2 — Lowercase normalisation:**
Generate package names with arbitrary `text.ascii_letters` casing; verify extracted name
is always `name.lower()`.

**Property 3 — Result field completeness:**
Generate arbitrary package name strings; run `verify()` with all subprocess calls mocked;
assert all required fields are present with correct types.

**Property 4 — Generate when ≥ 70:**
Generate confidence integers in `[70, 100]`; pass synthetic results through the gate; assert
`command` is non-empty and `verified = True`.

**Property 5 — Refuse when < 70:**
Generate confidence integers in `[0, 69]`; assert `command is None` and `verified = False`.

**Property 6 — PKS install method used:**
Generate `install_method` strings from `{"apt", "snap", "flatpak"}`; insert PKS record;
call `_build_command`; assert the method name appears in the produced command.

**Property 7 — Verified packages written to PKS:**
Generate valid package name strings; mock `apt-cache show` to succeed; call `verify()`;
assert PKS contains record with `verification_status = 'verified'`.

**Property 8 — Unknown packages written to PKS:**
Generate package name strings; mock all sources to fail; call `verify()`; assert PKS record
has `verification_status = 'unknown'`.

**Property 9 — Case-insensitive PKS lookup:**
Generate package names; insert via `upsert()`; query with `name.upper()`, `name.lower()`,
`name.title()`; assert same record returned each time.

**Property 10 — Offline never queries Web RAG:**
Generate package name strings; call `verify(online=False)` with a spy on `_query_web_rag`;
assert spy is never called.

**Property 11 — Installation failure classification:**
Generate arbitrary package name strings; construct `"unable to locate package {name}"` error;
pass to `handle_failure()`; assert classified as `installation_failure` and extracted name
matches the generated name.

**Property 12 — Candidates ranked by confidence:**
Generate lists of candidate dicts with random confidence integers; pass through the ranking
step; assert resulting list is sorted descending by confidence.

**Property 13 — Highest-ranked candidate enqueued:**
Generate ranked candidate lists; run `_handle_installation_failure` with mocked DB; assert
the inserted `selected_candidate` equals `candidates[0]["command"]`.

**Property 14 — Serialisation round-trip:**
Generate `VerificationResult` objects via Hypothesis strategies; assert
`from_dict(result.to_dict()) == result`.

### Integration Tests

- End-to-end: POST `/api/shce/verify-package` with a real package (`git`) on a Linux host that
  has apt-cache — expect confidence = 100, command present.
- End-to-end: POST `/api/shce/verify-package` with a clearly non-existent package name — expect
  confidence = 0, command null.
- Timing: POST `/api/shce/verify-package` completes within 10 seconds (Requirement 9.5).
- Offline timing: full offline pipeline completes within 5 seconds (Requirement 8.5).
