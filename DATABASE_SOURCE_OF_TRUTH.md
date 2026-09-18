# DATABASE SOURCE OF TRUTH AUDIT

**Date**: 2026-09-15  
**Project**: PC Doctor  
**Status**: Authoritative Database Topology & Data Lifecycle Specification  

---

## 1. Database Inventory & Summary

All `.db`, `.db-wal`, and `.db-shm` files discovered across the repository were analyzed for byte size, schema structure, row counts, readers, and writers.

| Database Path | File Size | Table Count | Total Rows | Classification | Source of Truth? | Action / Recommendation |
|---|---|---|---|---|---|---|
| `backend/knowledge.db` | 339 KB | 8 tables | 433 rows | **Active Runtime & Legacy DB** | **Yes** (Self-healing & Legacy KB) | **RETAIN (Active)** |
| `backend/knowledge_static.db` | 90 KB | 7 tables | 222 rows (inc. FTS) | **Authoritative Static Catalog** | **Yes** (Immutable Verified Recipes) | **RETAIN (Active)** |
| `backend/knowledge_dynamic.db` | 28 KB | 4 tables | 2 rows | **Dynamic Knowledge Store** | **Yes** (Learned Fixes & Promotions) | **RETAIN (Active)** |
| `backend/resolution_cache.db` | 12 KB | 1 table | Cached entries | **Package Resolution Cache** | **Yes** (Provenance & Trust Scores) | **RETAIN (Active Cache)** |
| `backend/pc_doctor.db` | 0 bytes | 0 tables | 0 rows | **Empty Orphan** | No | **DELETE (0-byte artifact)** |
| `backend/engine.knowledge.db` | 0 bytes | 0 tables | 0 rows | **Empty Orphan** | No | **DELETE (0-byte artifact)** |
| `knowledge_static.db` (root) | 0 bytes | 0 tables | 0 rows | **Empty Orphan** | No | **DELETE (misplaced 0-byte file)** |
| `knowledge_dynamic.db` (root) | 0 bytes | 0 tables | 0 rows | **Empty Orphan** | No | **DELETE (misplaced 0-byte file)** |
| `backend/knowledge_static.db-wal` | 0 bytes | N/A | N/A | **SQLite Runtime WAL Artifact** | No | **REMOVE & IGNORE** |
| `backend/knowledge_static.db-shm` | 32 KB | N/A | N/A | **SQLite Runtime SHM Artifact** | No | **REMOVE & IGNORE** |

---

## 2. Deep-Dive Specification for Active Databases

### A. `backend/knowledge_static.db` (Authoritative Static Knowledge Base)

- **Purpose**: High-integrity, curated, immutable catalog of 111 verified repair recipes spanning Windows, Linux, and macOS across Runtimes, Environment Variables, Package Managers, Network, System Services, and Toolchains.
- **Source of Truth**: **PRIMARY SOURCE OF TRUTH for all verified system fixes**.
- **Schema**:
  1. `static_recipes` (111 rows):
     - Columns: `id` (INTEGER PRIMARY KEY), `issue` (TEXT), `os` (TEXT), `category` (TEXT), `command` (TEXT), `risk` (TEXT), `explanation` (TEXT), `tags` (TEXT), `created_at` (TIMESTAMP), `operation` (TEXT), `repair_strategy` (TEXT), `package_manager` (TEXT), `package_id` (TEXT), `verification_command` (TEXT), `official_url` (TEXT), `source` (TEXT), `app_id` (TEXT), `install_supported`, `update_supported`, `uninstall_supported`, `reinstall_supported`, `verify_supported`, `version_check_supported`, `repair_supported`, `update_method`, `publisher_update_command`, `publisher_update_instructions`.
  2. `static_recipes_fts` (SQLite FTS5 Full-Text Search Virtual Table, 111 indexed entries).
- **Readers**:
  - `backend/routes_kb.py` (`STATIC_DB_PATH`)
  - `backend/recipe_engine.py` (Recipe lookup by tool & OS)
  - `backend/plan_freeze.py` (Execution plan recipe binding)
  - `backend/state_refresh.py` (Validation checks)
- **Writers**:
  - `backend/populate_static_db.py` (Initial seeding and catalog updates)
  - `backend/automation_engine.py` (Promoting verified dynamic solutions into static entries)
- **WAL / SHM Handling**: SQLite generates temporary `.db-wal` and `.db-shm` files when transactions are executed in WAL mode. These are ephemeral runtime scratch spaces and must be excluded from version control.

---

### B. `backend/knowledge.db` (Self-Healing Core & Legacy Knowledge Base)

- **Purpose**: Operational runtime database driving the Self-Healing Core Engine (SHCE), adaptive failure intelligence, and legacy `RepairEngine` lookups.
- **Source of Truth**: **PRIMARY SOURCE OF TRUTH for autonomous self-healing, adaptive heuristics, and execution telemetry history**.
- **Schema & Contents**:
  1. `recipes` (117 rows): Baseline recipes used by legacy `RepairEngine`. Columns: `id`, `issue`, `os`, `command`, `risk`, `explanation`.
  2. `adaptive_knowledge_base` (5 rows): Self-healed error patterns and verified successful fixes. Columns: `id`, `os_name`, `os_version`, `kernel_version`, `error_pattern`, `successful_fix`, `default_fallback`, `confidence_score`, `success_count`, `failure_count`, `verification_status`, `source`, `last_verified`, `fingerprint_id`, `error_signature`, `related_fixes`.
  3. `self_healing_attempts` (81 rows): Historical log of automated remediation attempts with stdout/stderr outcomes.
  4. `error_intelligence` (46 rows): Pattern-indexed error catalog capturing command failures and candidate generation.
  5. `shce_queue` (45 rows): Remediation task queue state.
  6. `package_knowledge` (20 rows): Package installation methods, repo requirements, and fallback strategies.
  7. `safety_overrides` (9 rows): Audit log of manual safety overrides requested by user.
  8. `learned_command_mappings` (0 rows): Dynamic replacement command map.
- **Readers**:
  - `backend/shce_engine.py` (SHCE core loop)
  - `backend/self_healing.py` (Auto-remediation lookups)
  - `backend/repair_engine.py` (`get_repair_plan`, `search_knowledge`)
  - `backend/safety.py` (Safety overrides check)
  - `backend/app_context.py`
  - `backend/routes_shce.py`
  - `backend/routes_system.py`
- **Writers**:
  - `backend/shce_engine.py` (Healed attempts, intelligence records, queue items)
  - `backend/self_healing.py` (Recording successful fixes)
  - `backend/populate_static_db.py` (Syncs static recipes to keep legacy routes up to date)
  - `backend/populate_db.py` (Initial setup baseline)

---

### C. `backend/knowledge_dynamic.db` (Dynamic Learned Knowledge Store)

- **Purpose**: Stores newly discovered / synthesized repair commands generated at runtime by AI reasoning or heuristic adaptation, isolating them from the immutable static catalog until fully validated.
- **Source of Truth**: **SOURCE OF TRUTH for staged, candidate, and pending-approval remediation recipes**.
- **Schema**:
  1. `learned_solutions` (2 rows): Dynamic solutions awaiting lifecycle graduation. Columns: `id`, `trigger_pattern`, `proposed_fix`, `category`, `os`, `user_approved`, `success_count`, `fail_count`, `promoted_to_static`, `source`, `created_at`, `last_used`, `lifecycle_status`.
  2. `pending_approvals` (0 rows): User review queue for high-risk dynamic suggestions.
  3. `validation_evidence` (0 rows): Environmental verification proof for candidate solutions.
- **Readers**:
  - `backend/routes_kb.py` (`DYNAMIC_DB_PATH`)
  - `backend/automation_engine.py` (Monitors candidate solutions for promotion)
  - `backend/routes_shce.py`
- **Writers**:
  - `backend/routes_kb.py` (Learned fix insertion)
  - `backend/automation_engine.py` (Lifecycle status transitions)

---

### D. `backend/resolution_cache.db` (Package Resolution & Provenance Cache)

- **Purpose**: High-speed SQLite cache storing resolved package identifiers, upstream publisher domain verification, fuzzy match scores, and previous install success indicators.
- **Source of Truth**: **RUNTIME CACHE for Package Resolution Engine (`backend/pkg_resolution.py`)**.
- **Schema**:
  1. `provenance`: Columns: `query_name`, `variant`, `resolved_id`, `manager`, `source`, `publisher`, `homepage`, `verified`, `verified_at`, `install_success`, `last_used`.
- **Readers & Writers**:
  - Managed exclusively by `ProvenanceStore` in `backend/pkg_resolution.py`.

---

## 3. Orphan & Empty Database Analysis

### A. Root `knowledge_static.db` and Root `knowledge_dynamic.db`
- **File Size**: 0 bytes each.
- **Origin**: Created accidentally when a test script or command was launched from the repository root rather than the `backend/` directory without an explicit path resolution.
- **Evidence**:
  - Code references always target `backend/knowledge_static.db` or `Path(__file__).parent / "knowledge_static.db"`.
  - Zero tables, zero bytes, zero readers, zero writers.
- **Action**: **CONCLUDED SAFE TO DELETE**.

### B. `backend/engine.knowledge.db`
- **File Size**: 0 bytes.
- **Origin**: Created during early development experiment.
- **Evidence**:
  - Only string occurrence in the entire repository is in `scripts/inspect_db.py` (diagnostic inspection list).
  - No Python code, route, or test references or writes to this file.
- **Action**: **CONCLUDED SAFE TO DELETE**.

### C. `backend/pc_doctor.db`
- **File Size**: 0 bytes.
- **Origin**: Placeholder file created during early project scaffold.
- **Evidence**:
  - Listed in `.gitignore` and `scripts/inspect_db.py`.
  - No active module reads or writes to it (the active application uses `knowledge.db` and `knowledge_static.db`).
- **Action**: **CONCLUDED SAFE TO DELETE**.

---

## 4. Population & Migration Script Audit

### 1. `backend/populate_static_db.py`
- **Status**: **AUTHORITATIVE PRODUCTION SCRIPT**.
- **Responsibility**: Seeds `backend/knowledge_static.db` with 111 classified, multi-platform recipes and automatically syncs them into `backend/knowledge.db` so legacy engines and routes immediately benefit.
- **Execution**: Can be run idempotently at any time (`python backend/populate_static_db.py`).

### 2. `backend/populate_db.py`
- **Status**: **ACTIVE SETUP SCRIPT (Retained)**.
- **Responsibility**: Baseline seeder for `backend/knowledge.db`.
- **Callers**: Directly invoked by `scripts/setup.js` (line 124), `scripts/setup.ps1` (line 87), and `scripts/setup.sh` (line 64). Deleting this script would break all environment setup routines.
- **Recommendation**: Retain intact.

### 3. `scripts/cleanup_db.py`
- **Status**: **OBSOLETE / HARMFUL SCRATCH SCRIPT (Deletable)**.
- **Responsibility**: Contains a hardcoded script executing `DELETE FROM static_recipes WHERE issue LIKE 'Reinstall%' OR issue LIKE 'Repair%'`.
- **Callers**: Zero callers in any script, test, or workflow.
- **Risk**: Running this script would destructively purge valid catalog recipes from `knowledge_static.db`.
- **Action**: **CONCLUDED SAFE TO DELETE**.

### 4. `scripts/inspect_db.py`
- **Status**: **ACTIVE DIAGNOSTIC UTILITY (Retain)**.
- **Responsibility**: Useful diagnostic script for inspecting database tables and columns. Updated to reflect cleaned database topology.
