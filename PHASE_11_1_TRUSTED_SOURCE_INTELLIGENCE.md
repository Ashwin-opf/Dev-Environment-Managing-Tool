# PHASE 11.1 — Trusted Source Intelligence

**Milestone**: Phase 11.1 Capability Hardening  
**Target Capabilities**: 
* **Problem #4**: Trusted upstream release is newer than package-manager candidate
* **Problem #54**: Repository/package-manager version is outdated compared with trusted upstream
* **Problem #71**: Official download/update URL redirects incorrectly or becomes invalid  
**Ground Truth Invariant**: Pure decision/intelligence layer. No direct subprocess spawning, no installer execution, no direct package mutations. Strictly routes through the frozen execution architecture:
`Request → Detection / Diagnosis → Trusted Source Intelligence → ExecutionResolver → ExecutionPlan → Tier → Approval → Privilege → LIVE Safety Gate → Centralized Execution Engine → Verification → Rescan → Result → Logging`.

---

## 1. Executive Summary

Phase 11.1 unifies Problems #4, #54, and #71 into a single, reusable **Trusted Source Intelligence** system (`backend/trusted_source_intelligence.py`). It extends the canonical identity model (`CanonicalIdentity`) with trusted repository, API, domain, and release policy metadata without duplicating data structures or bypassing the frozen execution pipeline.

```text
Canonical Tool Identity
        ↓
Trusted Source Metadata
        ↓
Source Discovery
        ↓
Source Validation
        ↓
Version Comparison
        ↓
Compatibility Check
        ↓
Source Decision (SourceDecisionResult)
        ↓
Existing ExecutionResolver
        ↓
ExecutionPlan
        ↓
Existing Safety / Approval / Execution Pipeline
```

### Key Architectural Invariants Enforced
1. **Decision Layer Boundary**: The intelligence layer determines *what exists, what is compatible, what is newer, and whether it requires review*. It never invokes shell commands or installers directly.
2. **Explicit Trust Provenance**: Trust cannot be established by AI, RAG, search engines, or user input. Candidates from untrusted origins are strictly bounded (`trust <= 0.40`) and cannot self-promote to `STATIC_DB`.
3. **SSRF & Localhost Defense**: `OfficialUrlValidator` unconditionally rejects loopback addresses (`127.0.0.0/8`, `::1`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local/cloud metadata (`169.254.0.0/16`), localhost hostnames, and non-HTTP schemes (`file://`, `ftp://`).
4. **HTTPS Downgrade & Loop Prevention**: Redirects are tracked up to a hard limit of 5 hops; redirect loops and HTTPS → HTTP downgrades are immediately aborted.
5. **Downgrade Protection**: Any candidate version lower than the installed version is classified as `DOWNGRADE_CANDIDATE` and blocked from automatic update.
6. **Honest Offline States**: Network and upstream API failures produce `UPSTREAM_UNAVAILABLE` and are never misrepresented as "No update available."

---

## 2. Problem #4 — Trusted Upstream Newer Than Package Manager

### Detection Capability
The system compares the detected locally installed version, the package-manager candidate version, and the upstream release version:
```text
Installed <= Package Manager < Trusted Upstream
```
When this condition is met, the engine emits `SourceDecisionStatus.UPSTREAM_UPDATE_AVAILABLE`.

### Example Evaluation
* **Installed Version**: `2.40.0`
* **Package Manager Version**: `2.44.0`
* **Trusted Upstream Version**: `2.48.1`
* **Engine Decision**:
  - `status`: `UPSTREAM_UPDATE_AVAILABLE`
  - `update_available`: `true`
  - `source_trust`: `0.95`
  - `reason`: `"A newer compatible trusted upstream release (2.48.1) is available (package manager offers 2.44.0)."`

### Version Comparison & Normalization
* Handled via `VersionComparator`:
  - Strips `v`/`V` prefixes (e.g. `v2.44.0` == `2.44.0`).
  - Correctly evaluates semantic ordering: `2.10.0 > 2.9.0` (never naive lexicographical sorting).
  - Handles vendor build suffixes (e.g. `2.44.0.windows.1` -> `2.44.0.1`).
  - Rejects malformed strings (`xyz!!`, `???`) with `VERSION_COMPARISON_UNKNOWN`.

### Compatibility & Channel Awareness
* Compares target OS (`Windows`, `Linux`, `Darwin`) and architecture (`x64`, `arm64`, `x86`).
* If upstream OS does not match host OS, status is `UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE`.
* If a preview/prerelease build (e.g. `2.49.0-rc1`) is detected while the installation channel is `stable`, automatic selection is rejected and flagged as `REVIEW_REQUIRED`.

### Execution Integration
* When `UPSTREAM_UPDATE_AVAILABLE` is produced, `create_execution_request_from_decision` constructs an `ExecutionRequest` with `operation="UPDATE"`.
* `ExecutionResolver` evaluates the request into an `ExecutionPlan`. Because upstream direct updates carry potential environment impact, they resolve to `ExecutionTier.TIER_2_CONTROLLED` or `ExecutionTier.TIER_3_FULL_PROTECTED` with `approval_required=True`.

---

## 3. Problem #54 — Linux Outdated Repository Package

### Context & Challenge
Linux distributions (notably Debian and Ubuntu LTS) deliberately freeze package versions for stability throughout the lifecycle of a distribution release. Numerical version differences do not necessarily mean a package is broken or should be automatically superseded by a third-party PPA or raw upstream binary.

### Evaluation Flow
When `is_linux_distro_package=True`:
1. `Installed <= Repository Candidate < Trusted Upstream Release`
2. The engine emits `SourceDecisionStatus.REPOSITORY_OUTDATED`.
3. Sets `review_required=True` and `update_available=True`.
4. Does **NOT** execute an automatic bypass or blindly install third-party sources.

### Structured States Distinguished
* `REPOSITORY_UP_TO_DATE`: Distro repository candidate matches trusted upstream release.
* `REPOSITORY_OUTDATED`: Distro repository candidate is older than trusted upstream; human review required before source alteration.
* `UPSTREAM_UNAVAILABLE`: Upstream metadata unreachable; offline state preserved.
* `VERSION_COMPARISON_UNKNOWN`: Non-standard distro package version strings that cannot be safely parsed.
* `REVIEW_REQUIRED`: Defer to user approval.

---

## 4. Problem #71 — Official URL & Redirect Validation

### Security Boundary (`OfficialUrlValidator`)
Tied directly to the canonical tool identity. Validates canonical URLs and redirect chains.

```text
Candidate URL
     ↓
Scheme Check (only http/https; file:// and ftp:// rejected)
     ↓
SSRF & Local Destination Check (localhost, 127.0.0.1, 10.0.0.0/8, 169.254.169.254 rejected)
     ↓
Domain Whitelist Check (against CanonicalIdentity.trusted_download_domains)
     ↓
Redirect Hop Inspector (max 5 hops)
     ↓
HTTPS → HTTP Downgrade Check (rejected if downgraded)
     ↓
Redirect Loop Check (visited set tracking)
     ↓
Accepted (OFFICIAL_URL_VALIDATED) / Rejected (UNTRUSTED_REDIRECT / SSRF_ATTEMPT_BLOCKED)
```

### SSRF Protection Details
* Prohibits private IP addresses: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
* Prohibits loopback: `127.0.0.0/8`, `::1`.
* Prohibits link-local / cloud metadata services: `169.254.0.0/16` (e.g. AWS/GCP metadata endpoints).
* Prohibits broadcast / multicast / internal names (`.local`, `.internal`, `.localhost`).

### Trusted Domain Whitelist
* Subdomain policy: Exact domain or subdomains ending in `.domain` match only when authorized in `trusted_download_domains`.
* Example: `https://git-scm.com` redirects to `https://downloads.git-scm.com` → **ACCEPTED**.
* Example: `https://git-scm.com` redirects to `https://untrusted-mirror.example.com` → **REJECTED** (`UNTRUSTED_REDIRECT`).
* Example: AI/RAG proposes `https://ai-suggested-downloads.org/tool.exe` → **REJECTED** (`UNTRUSTED_REDIRECT`).

---

## 5. Security & AI / RAG Boundaries

| Threat Vector | Mitigation | Status |
| :--- | :--- | :---: |
| AI hallucinated download URL | Domain must match `CanonicalIdentity.trusted_download_domains`; non-matches rejected | **ENFORCED** |
| AI claims `STATIC_DB` provenance | `ExecutionResolver` forces `AI_RAG_CANDIDATE`, `trust <= 0.40` | **ENFORCED** |
| SSRF to AWS/cloud metadata (169.254.169.254) | IP network filter unconditionally blocks `169.254.0.0/16` | **ENFORCED** |
| Local service probe (`localhost:8080`) | Hostname and loopback filter blocks `localhost` and `127.0.0.0/8` | **ENFORCED** |
| HTTPS downgrade on redirect | `OfficialUrlValidator` aborts redirect on scheme downgrade | **ENFORCED** |
| Accidental version downgrade | `VersionComparator` flags `DOWNGRADE_CANDIDATE` and halts mutation | **ENFORCED** |
| Direct subprocess bypass from resolver | `TrustedSourceDecisionEngine` contains no subprocess calls; outputs only data models | **ENFORCED** |

---

## 6. Offline Behavior & Caching

* **Distinction between Offline and No Update**:
  When release APIs or network connections fail, the engine outputs `UPSTREAM_UNAVAILABLE` with `review_required=True`. It **never** outputs `NO_UPDATE`.
* **Cache Architecture (`ReleaseCache`)**:
  - In-memory cache with TTL (default: 3600 seconds).
  - Keyed by `(canonical_id, channel, os, arch)`.
  - Stale entries return `(release_info, is_fresh=False)` and log `STALE_SOURCE_DATA`.
  - Cache can be bypassed with `force_refresh=True` or explicit invalidation.

---

## 7. 75-Problem Master Matrix Updates

In strict accordance with the instructions, **ONLY** Problems #4, #54, and #71 were updated.

| # | Problem | Previous Status | New Status | Evidence |
|---|---|---|---|---|
| **4** | Package manager says no update but official source has newer version | `PARTIALLY_IMPLEMENTED` | **`DETECT_AND_REPAIR`** | `test_phase11_1_trusted_source_intelligence.py::TestProblem4TrustedUpstreamNewerThanPM` (12 tests) |
| **54** | Repository package outdated | `PARTIALLY_IMPLEMENTED` | **`REVIEW_ONLY`** | `test_phase11_1_trusted_source_intelligence.py::TestProblem54LinuxOutdatedRepository` (8 tests) |
| **71** | Official URL redirects | `NOT_IMPLEMENTED` | **`DETECT_AND_REPAIR`** | `test_phase11_1_trusted_source_intelligence.py::TestProblem71OfficialUrlValidation` (14 tests) |

### Summary Taxonomy Counts
| Classification | Previous Count | New Count | % |
| :--- | :---: | :---: | :---: |
| **`FULLY_SOLVABLE`** | 21 | **21** | 28.00% |
| **`DETECT_AND_REPAIR`** | 21 | **23** | 30.67% |
| **`DETECT_ONLY`** | 11 | **11** | 14.67% |
| **`REVIEW_ONLY`** | 9 | **10** | 13.33% |
| **`BLOCKED_BY_POLICY`** | 6 | **6** | 8.00% |
| **`PARTIALLY_IMPLEMENTED`** | 6 | **4** | 5.33% |
| **`NOT_IMPLEMENTED`** | 1 | **0** | 0.00% |
| **Total** | **75** | **75** | **100.00%** |

### Verified Metrics
* **Actionable Repair Boundary**: `(21 + 23) / 75 = 44 / 75 = 58.67%` (increased from 56.00%)
* **Detection Coverage**: `71 / 75 = 94.67%` (increased from 90.67%)
* **Zero Unimplemented Problems**: `NOT_IMPLEMENTED` count reduced to `0`.

---

## 8. Verification & Test Evidence

### Focused Test Suite (`tests/test_phase11_1_trusted_source_intelligence.py`)
* **38 passed**, 0 failed, 0 skipped in 15.73s:
  - 12 tests for Problem #4 (PM older, equal, newer; incompatible release; prerelease vs stable; 'v' prefix; malformed; network unavailable; stale cache; missing metadata; downgrade protection).
  - 8 tests for Problem #54 (repo older, equal, backport newer, incompatible arch, untrusted source, review required, offline behavior, version ambiguity).
  - 14 tests for Problem #71 (valid URL, trusted redirect, untrusted redirect, HTTPS downgrade, redirect loop, excessive hops, malformed URL, HTTP failure, localhost SSRF, private IP SSRF, link-local SSRF, file:// scheme, trusted replacement URL, AI/RAG URL rejection).
  - 4 integration & security tests (valid decision to ExecutionResolver, rejected decision cannot reach execution, GitHub repo injection prevention, AI/RAG cannot self-promote to STATIC_DB).

### Matrix Integrity Verification
* `tests/test_stage11_75_problem_audit.py`: **10 passed**, 0 failed in 0.10s.
* `tests/test_problem_coverage_matrix.py`: **4 passed**, 0 failed in 0.28s.
