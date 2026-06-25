# Implementation Plan: SHCE Package Verification and Self-Healing Engine

## Overview

Implement the package verification safety gate inside the existing Python backend. The work splits into four layers: (1) data layer — SQLite migration for `package_knowledge` and the `PackageKnowledgeStore` DAO; (2) core engine — `IntentDetector`, `PackageVerifier`, and `VerificationResult` added to `shce_engine.py`; (3) orchestrator integration — extend `SHCEOrchestrator.handle_failure` with the installation-failure branch; (4) API layer — three new FastAPI routes in `routes_shce.py`. Property-based tests use Hypothesis; unit tests use pytest.

---

## Tasks

- [x] 1. Create `package_knowledge` table migration and `PackageKnowledgeStore` DAO
  - [x] 1.1 Add `PackageKnowledgeStore` class to `shce_engine.py`
    - Implement `ensure_table()` — `CREATE TABLE IF NOT EXISTS package_knowledge` with all columns from the design (`id`, `package_name`, `install_method`, `repository_required`, `verification_status`, `last_verified`, `fallback_methods`)
    - Implement `seed()` — idempotent insert of the 20 seed packages (`git`, `docker.io`, `nodejs`, `python3`, `curl`, `wget`, `vim`, `htop`, `tmux`, `build-essential`, `net-tools`, `ffmpeg`, `vlc`, `gimp`, `libreoffice`, `openssh-server`, `ufw`, `fail2ban`, `nginx`, `postgresql`); all with `install_method = 'apt'` and `verification_status = 'verified'`
    - Implement `get(package_name)` — case-insensitive exact lookup via `LOWER(package_name) = LOWER(?)`
    - Implement `upsert(package_name, **fields)` — `INSERT OR REPLACE` with timestamp update
    - Implement `list_all(limit, offset)` — paginated SELECT
    - Implement `count()` — `SELECT COUNT(*)`
    - Wrap all sqlite3 calls in try/except; log errors via module-level logger without raising
    - Call `pks.ensure_table()` and `pks.seed()` from `ErrorIntelligenceDB._ensure_tables()` so no changes to `main.py` are needed
    - _Requirements: 4.1, 4.2, 4.3, 4.6_

  - [ ]* 1.2 Write property test for PKS case-insensitive lookup
    - **Property 9: PKS lookup is case-insensitive**
    - **Validates: Requirements 4.6**
    - Use `@given(st.text(alphabet=st.characters(whitelist_categories=("Lu","Ll","Nd")), min_size=1, max_size=30))` to generate package names
    - Insert via `upsert()`; query with `.upper()`, `.lower()`, `.title()`; assert same record returned

  - [ ]* 1.3 Write unit tests for `PackageKnowledgeStore`
    - Test `ensure_table()` idempotency (call twice, no error)
    - Test `seed()` idempotency (call twice, exactly 20 rows)
    - Test `get()` / `upsert()` round-trip
    - Test `list_all()` pagination
    - _Requirements: 4.1, 4.2, 4.3, 4.6_

- [x] 2. Implement `VerificationResult` dataclass and `IntentDetector`
  - [x] 2.1 Add `VerificationResult` dataclass to `shce_engine.py`
    - Fields: `package` (str), `verified` (bool), `confidence` (int), `source` (str), `verification_source` (str), `command` (Optional[str])`, `reason` (Optional[str])`, `suggestion` (Optional[str])`
    - Implement `to_dict()` — returns JSON-safe dict; all Optional fields included (as `None` when absent)
    - Implement `from_dict(cls, data)` — reconstruct from dict; handle missing optional keys with `.get()`
    - _Requirements: 2.10, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 2.2 Add `IntentDetector` static-method class to `shce_engine.py`
    - `TRIGGER_WORDS = frozenset(["install", "get", "add", "setup"])`
    - `classify(query)` — return `(is_installation_request: bool, package_name: Optional[str])`; package name normalised to lowercase
    - `_extract_package(query)` — regex: find trigger word followed by `\s+(\S+)`, return group 1 lowercased; return `None` if no match
    - If trigger word present but no following token, `classify` returns `(True, None)` (no package name extracted)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.3 Write property test for intent detection trigger-word sensitivity
    - **Property 1: Intent detection is trigger-word sensitive**
    - **Validates: Requirements 1.1**
    - Generate strings with at least one trigger word + token; assert `classify()` returns `True`
    - Generate strings with no trigger words; assert `classify()` returns `False`

  - [ ]* 2.4 Write property test for lowercase normalisation
    - **Property 2: Extracted package name is always lowercase**
    - **Validates: Requirements 1.2, 1.4**
    - Generate package name tokens with mixed ASCII casing via `st.text(alphabet=string.ascii_letters, min_size=1, max_size=20)`
    - Construct query `"install {name}"`; assert extracted name equals `name.lower()`

  - [ ]* 2.5 Write property test for serialisation round-trip
    - **Property 14: Serialisation round-trip**
    - **Validates: Requirements 7.5**
    - Use Hypothesis `@composite` strategy to build valid `VerificationResult` objects
    - Assert `VerificationResult.from_dict(result.to_dict()) == result`

  - [ ]* 2.6 Write unit tests for `IntentDetector` and `VerificationResult`
    - Positive classification: "install git", "get curl", "add vim", "setup nginx"
    - Negative classification: "what is git", "how to uninstall vim"
    - Missing package name: "please install " (no trailing token)
    - `to_dict` / `from_dict` examples for verified and unverified results
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 7.2, 7.4, 7.5_

- [x] 3. Checkpoint — ensure table exists and intent detection tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement `PackageVerifier` — pipeline sources and command gate
  - [x] 4.1 Implement `PackageVerifier.__init__`, `_apt_cache_show`, and `_apt_cache_search`
    - `__init__(db_path)` — store path, instantiate `PackageKnowledgeStore`; check `shutil.which("apt-cache")`; store result as `self._has_apt`
    - `_apt_cache_show(pkg)` — `subprocess.run(["apt-cache", "show", pkg], ...)` with 5 s timeout; return `100` on zero exit code, `None` otherwise; catch `FileNotFoundError`, `TimeoutExpired`, any `Exception`
    - `_apt_cache_search(pkg)` — `subprocess.run(["apt-cache", "search", "--names-only", pkg], ...)`; return `80` if stdout non-empty, `None` otherwise; same error handling
    - Skip both sources (return `None`) when `not self._has_apt`
    - _Requirements: 2.1, 2.2, 2.3, 6.1_

  - [x] 4.2 Implement `_query_pks`, `_query_local_rag`, `_query_web_rag`, and `_fuzzy_match`
    - `_query_pks(pkg)` — call `self._pks.get(pkg)`; return `80` if record exists with `verification_status = 'verified'`, `None` otherwise
    - `_query_local_rag(pkg)` — reuse `VectorSearch` (already in `vector_search.py`); search by package name; return `60` on match, `None` otherwise; wrap in try/except
    - `_query_web_rag(pkg)` — DuckDuckGo instant-answer query (`urllib.request.urlopen` with `WEB_RAG_TIMEOUT`); return `60` on relevant result, `None` otherwise; catch `URLError`, `socket.timeout`, `json.JSONDecodeError`; NEVER call when `online=False`
    - `_fuzzy_match(pkg)` — compare `pkg` against all PKS package names using `difflib.get_close_matches`; return `(40, closest_name)` if best ratio ≥ 0.7, `(0, None)` otherwise
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.9, 6.3, 6.4, 8.1, 8.2_

  - [x] 4.3 Implement `PackageVerifier._build_command` and `PackageVerifier.verify`
    - `_build_command(pkg, install_method)` — map method to command: `apt` → `sudo apt install -y {pkg}`, `snap` → `sudo snap install {pkg}`, `flatpak` → `flatpak install -y flathub {pkg}`, `external_repo` → include repo-add step if PKS has `repository_required`; fallback to `apt`
    - `verify(package_name, online)`:
      - Raise `ValueError` for empty/whitespace-only name
      - Normalise to lowercase
      - Run pipeline in order: `_apt_cache_show` → `_apt_cache_search` → `_query_pks` → `_query_local_rag` → `_query_web_rag` (if `online`) → `_fuzzy_match`; stop at first non-`None` result
      - If confidence ≥ 70: look up PKS for `install_method`; call `_build_command`; set `verified=True`; upsert PKS with `verification_status='verified'`
      - If confidence == 40: set `verified=False`, `command=None`; include `suggestion` from fuzzy match
      - If confidence == 0 (no source): set `verified=False`, `command=None`; upsert PKS with `verification_status='unknown'`
      - Handle `offline + external_repo`: confidence=0, `verified=False`, prefix reason with offline message from Requirement 8.4
      - Return `VerificationResult`
    - _Requirements: 2.1–2.10, 3.1–3.5, 4.4, 4.5, 6.1–6.6, 7.1–7.4, 8.1–8.5_

  - [ ]* 4.4 Write property test — result always contains required fields
    - **Property 3: Verification result always contains required fields**
    - **Validates: Requirements 2.10, 6.8, 7.4**
    - Generate arbitrary non-empty package name strings; mock all subprocess/network calls; call `verify()`; assert all required fields present with correct Python types

  - [ ]* 4.5 Write property test — command gate: generate when confidence ≥ 70
    - **Property 4: Command generation gate — generate when confidence ≥ 70**
    - **Validates: Requirements 3.1, 7.1**
    - Use `@given(st.integers(min_value=70, max_value=100))` as confidence; construct synthetic `VerificationResult`; assert `command` is non-empty string and `verified is True`

  - [ ]* 4.6 Write property test — command gate: refuse when confidence < 70
    - **Property 5: Command generation gate — refuse when confidence < 70**
    - **Validates: Requirements 3.2, 6.7, 7.2**
    - Use `@given(st.integers(min_value=0, max_value=69))` as confidence; assert `command is None` and `verified is False`

  - [ ]* 4.7 Write property test — PKS install method used in command
    - **Property 6: PKS install method is used when available**
    - **Validates: Requirements 3.5**
    - Generate `install_method` from `st.sampled_from(["apt", "snap", "flatpak"])`; insert PKS record; call `_build_command`; assert method name appears in produced command string

  - [ ]* 4.8 Write property test — verified packages written to PKS
    - **Property 7: Verified packages written to PKS**
    - **Validates: Requirements 4.4**
    - Generate valid package name strings; mock `_apt_cache_show` to return 100; call `verify()`; assert PKS record exists with `verification_status='verified'` and non-null `last_verified`

  - [ ]* 4.9 Write property test — unknown packages written to PKS
    - **Property 8: Unknown packages written to PKS**
    - **Validates: Requirements 4.5**
    - Generate package name strings; mock all sources to return `None`; call `verify()`; assert PKS record has `verification_status='unknown'`

  - [ ]* 4.10 Write property test — offline never queries Web RAG
    - **Property 10: Offline mode never queries Web RAG**
    - **Validates: Requirements 2.7, 8.1, 8.2**
    - Generate package names; call `verify(online=False)` with `unittest.mock.patch` spy on `_query_web_rag`; assert spy `.call_count == 0` and returned `source != "web_rag"`

  - [ ]* 4.11 Write unit tests for `PackageVerifier`
    - Test each pipeline source independently (mocked subprocess / sqlite)
    - Test `verify()` with mocked sources returning each confidence tier (100, 80, 60, 40, 0)
    - Test offline guard: `online=False` skips web RAG
    - Test `ValueError` on empty package name
    - Test missing apt-cache: pipeline skips sources 1 & 2 gracefully
    - Test `offline + external_repo` produces correct reason prefix
    - _Requirements: 2.1–2.10, 3.1–3.5, 6.1–6.6, 8.1–8.5_

- [x] 5. Checkpoint — ensure verification pipeline tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Extend `SHCEOrchestrator` with installation failure self-healing
  - [x] 6.1 Add `_handle_installation_failure` method to `SHCEOrchestrator` in `shce_engine.py`
    - Extract package name from error string using `re.search(r"unable to locate package\s+(\S+)", error, re.I)`
    - Instantiate `PackageVerifier`; call `heal_installation_failure(failed_pkg, online)`
    - If candidates non-empty: enqueue best candidate via `self._db.enqueue()`; return structured success dict
    - If candidates empty: upsert PKS `verification_status='unknown'`; return `{"ok": False, "message": "..."}` per Requirement 5.7
    - _Requirements: 5.1, 5.2, 5.5, 5.7_

  - [x] 6.2 Implement `PackageVerifier.heal_installation_failure` in `shce_engine.py`
    - Query PKS for alternative install methods (e.g. `docker.io` when `docker` fails)
    - Query Local RAG for alternatives
    - Query Web RAG if `online=True`
    - If PKS record has `repository_required`: generate two-step candidate (add repo + install)
    - Return candidates sorted by confidence descending
    - _Requirements: 5.2, 5.3, 5.4, 5.6_

  - [x] 6.3 Patch `SHCEOrchestrator.handle_failure` entry point
    - At top of `handle_failure`, add: `if re.search(r"unable to locate package\s+(\S+)", error, re.I): return self._handle_installation_failure(command, error, source, auto_queue)`
    - Ensure the existing code path is unchanged for all other error types
    - _Requirements: 5.1_

  - [ ]* 6.4 Write property test — installation failure error classification
    - **Property 11: Installation failure error classification**
    - **Validates: Requirements 5.1**
    - Generate arbitrary package name strings via `st.text(min_size=1)`; construct `"unable to locate package {name}"` error string; pass to `handle_failure()`; assert routed to `_handle_installation_failure` and extracted name matches generated name

  - [ ]* 6.5 Write property test — self-healing candidates ranked by confidence
    - **Property 12: Self-healing candidates are ranked by confidence**
    - **Validates: Requirements 5.3**
    - Generate lists of candidate dicts with `st.lists(st.fixed_dictionaries({"command": st.text(), "confidence": st.integers(0, 100)}), min_size=1)`; pass through the ranking step; assert list is sorted descending by `confidence`

  - [ ]* 6.6 Write property test — highest-ranked candidate is enqueued
    - **Property 13: Highest-ranked candidate is enqueued**
    - **Validates: Requirements 5.5**
    - Generate ranked candidate lists; mock `self._db.enqueue`; run `_handle_installation_failure`; assert the `selected_candidate` argument passed to `enqueue` equals `candidates[0]["command"]`

  - [ ]* 6.7 Write unit tests for self-healing loop
    - Test error matching pattern detection
    - Test `heal_installation_failure` with PKS alternative (e.g. `docker` → `docker.io`)
    - Test two-step candidate when `repository_required` is set
    - Test empty candidate list path returns correct failure dict and updates PKS
    - _Requirements: 5.1–5.7_

- [x] 7. Checkpoint — ensure orchestrator integration tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Add three new API routes to `routes_shce.py`
  - [x] 8.1 Add Pydantic models and `POST /api/shce/verify-package` endpoint
    - Define `VerifyPackageRequest(BaseModel)` with `package_name: str`
    - Implement route: validate non-empty `package_name` (raise `HTTPException(400)` on empty/whitespace); detect online status via `EnvironmentProfiler.snapshot()`; call `PackageVerifier().verify()`; return `result.to_dict()`
    - Ensure response completes within 10 seconds (use `asyncio.wait_for` or route-level timeout if needed)
    - _Requirements: 9.1, 9.4, 9.5_

  - [x] 8.2 Add `GET /api/shce/package-knowledge` and `POST /api/shce/package-knowledge` endpoints
    - `GET` route: accept optional query params `limit` (default 100) and `offset` (default 0); return `{"total": pks.count(), "items": pks.list_all(limit, offset)}`
    - Define `PackageKnowledgeRecord(BaseModel)` with fields: `package_name` (str), `install_method` (str, default `"apt"`), `repository_required` (Optional[str]), `verification_status` (str, default `"verified"`), `fallback_methods` (Optional[str])`
    - `POST` route: call `pks.upsert(**record.dict())`; return `{"ok": True, "package_name": record.package_name}`
    - _Requirements: 9.2, 9.3_

  - [ ]* 8.3 Write unit tests for API routes
    - Use FastAPI `TestClient`
    - Test `POST /api/shce/verify-package` with empty `package_name` → HTTP 400
    - Test `POST /api/shce/verify-package` with `package_name="git"` (mocked verifier) → HTTP 200, correct schema
    - Test `GET /api/shce/package-knowledge` → HTTP 200, has `total` and `items` keys
    - Test `POST /api/shce/package-knowledge` with valid record → HTTP 200, `ok=True`
    - _Requirements: 9.1–9.5_

- [x] 9. Final checkpoint — all tests pass end-to-end
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All property-based tests use Hypothesis with `@settings(max_examples=100)`
- Each property test file should include the comment: `# Feature: shce-package-verification, Property N: <property_title>`
- `PackageKnowledgeStore`, `IntentDetector`, `PackageVerifier`, and `VerificationResult` all live in `shce_engine.py` alongside the existing classes
- The `ensure_table()` + `seed()` hook in `ErrorIntelligenceDB._ensure_tables()` means no changes to `main.py` are needed
- Checkpoints ensure incremental validation after each layer

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.5", "2.6"] },
    { "id": 3, "tasks": ["2.3", "2.4", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.11"] },
    { "id": 5, "tasks": ["4.3"] },
    { "id": 6, "tasks": ["4.4", "4.5", "4.6", "4.7", "4.8", "4.9", "4.10", "6.2"] },
    { "id": 7, "tasks": ["6.1"] },
    { "id": 8, "tasks": ["6.3"] },
    { "id": 9, "tasks": ["6.4", "6.5", "6.6", "6.7", "8.1"] },
    { "id": 10, "tasks": ["8.2"] },
    { "id": 11, "tasks": ["8.3"] }
  ]
}
```
